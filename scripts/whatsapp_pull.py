#!/usr/bin/env python3
"""
Read-only WhatsApp puller for whatsapp-ingest-agent (via 2Chat).

Two lanes, merged and deduped on the 2Chat message uuid:

  capture  The Make scenario "2Chat -> WhatsApp Log" receives 2Chat's instant
           webhooks (1-to-1 and group messages, both connected numbers) and writes
           one record per message into a Make data store. This script reads that
           store with GET only. It is the only lane that sees group messages:
           2Chat documents no group-history endpoint.
  api      scripts/twochat_client.py (GET only) reads 1-to-1 messages straight from
           2Chat, as a backstop for anything the webhook missed.

Each lane and each connected number fails on its own: one failure makes the run
`partial`, never `error`, as long as anything came back.

Output (stdout, or --out) holds the full message text, because the agent needs it to
summarize. Always point --out under analysis/cache/whatsapp/ (gitignored). The
repo is public, so message text and phone numbers must never reach a committed file.
Phone numbers are emitted only as sha256(REQUESTER_ID_SALT + digits) plus the last
4 digits, as platform-settings/requesters.json requires.

Usage:
    python3 scripts/whatsapp_pull.py --hours 24 --out analysis/cache/whatsapp/2026-10-29.json
    python3 scripts/whatsapp_pull.py --hours 24 --lane capture

Env (see .env.example):
    TWOCHAT_API_KEY, TWOCHAT_BUSINESS_NUMBER, TWOCHAT_PERSONAL_NUMBER
    MAKE_API_TOKEN, MAKE_API_HOST, WHATSAPP_LOG_DATASTORE_ID
    REQUESTER_ID_SALT
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import twochat_client as tc  # noqa: E402

SETTINGS = os.path.join(REPO_ROOT, "platform-settings", "whatsapp-ingest-sources.json")
CHANNEL_ENV = {"business": "TWOCHAT_BUSINESS_NUMBER", "personal": "TWOCHAT_PERSONAL_NUMBER"}


def load_dotenv(path):
    """Minimal .env loader — real env vars always win."""
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if val:
                os.environ.setdefault(key, val)


def load_settings(path=SETTINGS):
    with open(path) as fh:
        return json.load(fh)


# -- identity ---------------------------------------------------------------

def digits(number):
    return re.sub(r"\D", "", str(number or ""))


def hash_number(number, salt):
    d = digits(number)
    if not d:
        return None
    return hashlib.sha256((salt + d).encode()).hexdigest()[:16]


def last4(number):
    d = digits(number)
    return d[-4:] if len(d) >= 4 else None


# -- time -------------------------------------------------------------------

def parse_ts(value):
    """Epoch-ms / epoch-s number or ISO string -> aware UTC datetime, else None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        n = float(value)
        if n > 1e11:
            n /= 1000.0
        return datetime.fromtimestamp(n, tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# -- normalisation ----------------------------------------------------------

def first(d, *keys):
    for k in keys:
        cur = d
        for part in k.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur not in (None, ""):
            return cur
    return None


def normalize(raw, channel, lane, salt, chats):
    """One message from either lane -> the record the agent reads.

    Field names are read defensively (2Chat's payloads are not fully documented):
    the capture lane's names are the ones our own Make scenario writes; the api lane
    tries 2Chat's likely spellings. The first live probe pins them."""
    uuid = first(raw, "message_uuid", "uuid", "id", "message.id")
    if not uuid:
        return None
    is_group = bool(first(raw, "is_group", "group_uuid") or
                    str(first(raw, "chat_uuid") or "").startswith("WAG"))
    chat_uuid = first(raw, "chat_uuid", "group_uuid", "remote_phone_number", "contact.phone_number")
    peer = None if is_group else first(raw, "remote_phone_number", "peer_number", "contact.phone_number")
    sender = first(raw, "sender_number", "participant.phone_number", "remote_phone_number")
    direction = first(raw, "direction")
    if not direction:
        sent_by = str(first(raw, "sent_by", "from_me") or "").lower()
        direction = "out" if sent_by in ("user", "me", "true", "1", "api") else "in"
    ts = parse_ts(first(raw, "sent_at", "created_at", "timestamp", "message.timestamp"))
    reg = chats.get(str(chat_uuid), {}) if chat_uuid else {}
    chat_key = (str(chat_uuid) if is_group else hash_number(chat_uuid, salt)) if chat_uuid else None
    return {
        "message_uuid": str(uuid),
        "lane": lane,
        "channel": channel,
        "chat_key": chat_key,
        "chat_name": first(raw, "chat_name", "group_name", "wa_group_name", "contact.name") or reg.get("label"),
        "is_group": is_group,
        "kind": reg.get("kind"),
        "sensitivity": reg.get("sensitivity"),
        "ghl_covered": bool(reg.get("ghl_covered")),
        "peer_hash": hash_number(peer, salt),
        "peer_last4": last4(peer),
        "sender_hash": hash_number(sender, salt),
        "sender_last4": last4(sender),
        "sender_name": first(raw, "sender_name", "participant.name", "contact.name"),
        "direction": direction,
        "sent_at": ts.isoformat() if ts else None,
        "text": first(raw, "text", "message.text", "body") or "",
        "media_type": first(raw, "media_type", "message.media.type", "media.type"),
    }


# -- capture lane: Make data store (GET only) -------------------------------

def make_get(url, token):
    # No method argument: urllib sends GET for a request without a body.
    req = urllib.request.Request(url, headers={
        "Authorization": "Token " + token,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def pull_capture(since, salt, chats, page_size=100, max_pages=50):
    token = os.environ.get("MAKE_API_TOKEN")
    host = os.environ.get("MAKE_API_HOST")
    store = os.environ.get("WHATSAPP_LOG_DATASTORE_ID")
    missing = [n for n, v in (("MAKE_API_TOKEN", token), ("MAKE_API_HOST", host),
                              ("WHATSAPP_LOG_DATASTORE_ID", store)) if not v]
    if missing:
        return [], "capture lane not configured: missing " + ", ".join(missing)
    out, offset = [], 0
    for _ in range(max_pages):
        q = urllib.parse.urlencode({"pg[limit]": page_size, "pg[offset]": offset})
        url = "https://%s/api/v2/data-stores/%s/data?%s" % (host, store, q)
        try:
            data = make_get(url, token)
        except urllib.error.HTTPError as e:
            return out, "capture lane HTTP %s: %s" % (e.code, e.read()[:200].decode("utf-8", "replace"))
        except Exception as e:
            return out, "capture lane %s: %s" % (type(e).__name__, e)
        rows = data.get("records") or []
        for rec in rows:
            body = dict(rec.get("data") or {})
            body.setdefault("message_uuid", rec.get("key"))
            m = normalize(body, body.get("channel") or "business", "capture", salt, chats)
            if m and m["sent_at"] and parse_ts(m["sent_at"]) >= since:
                out.append(m)
        if len(rows) < page_size:
            break
        offset += page_size
    return out, None


# -- api lane: 2Chat (GET only, via twochat_client) -------------------------

def pull_api(since, salt, chats, channels):
    try:
        client = tc.TwoChatClient()
    except tc.TwoChatError as e:
        return [], [str(e)], {}
    out, errors, groups = [], [], {}
    for channel in channels:
        number = os.environ.get(CHANNEL_ENV[channel])
        if not number:
            errors.append("api lane: %s not set, %s channel skipped" % (CHANNEL_ENV[channel], channel))
            continue
        try:
            for raw in client.messages(number):
                m = normalize(raw, channel, "api", salt, chats)
                if m and m["sent_at"] and parse_ts(m["sent_at"]) >= since:
                    out.append(m)
            for g in client.groups(number):
                if g.get("uuid"):
                    groups[g["uuid"]] = g.get("wa_group_name") or g.get("name")
        except tc.TwoChatError as e:
            errors.append("api lane, %s channel: %s" % (channel, e))
    return out, errors, groups


def merge(lanes):
    """Dedupe on message_uuid; the capture record wins (it carries the group name)."""
    seen = {}
    for lane in lanes:
        for m in lane:
            if m["message_uuid"] not in seen or m["lane"] == "capture":
                seen[m["message_uuid"]] = m
    return sorted(seen.values(), key=lambda m: m["sent_at"] or "")


def main():
    ap = argparse.ArgumentParser(description="Read-only WhatsApp puller (2Chat).")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--lane", choices=["both", "capture", "api"], default="both")
    ap.add_argument("--channel", choices=["business", "personal"], action="append", dest="channels")
    ap.add_argument("--out", help="Write JSON here (keep it under analysis/cache/whatsapp/).")
    args = ap.parse_args()

    load_dotenv(os.path.join(REPO_ROOT, ".env"))
    try:
        settings = load_settings()
    except Exception as e:
        print(json.dumps({"status": "error", "errors": ["settings: %s" % e]}))
        sys.exit(1)
    salt = os.environ.get("REQUESTER_ID_SALT")
    if not salt:
        print(json.dumps({"status": "error", "errors": [
            "missing REQUESTER_ID_SALT — phone numbers cannot be hashed, so nothing is emitted"]}))
        sys.exit(1)

    chats = {k: v for k, v in (settings.get("chats") or {}).items() if not k.startswith("_")}
    channels = args.channels or [c for c, v in settings.get("channels", {}).items()
                                 if isinstance(v, dict) and v.get("enabled")]
    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)

    lanes, errors, groups = [], [], {}
    if args.lane in ("both", "capture"):
        cap, err = pull_capture(since, salt, chats)
        lanes.append(cap)
        if err:
            errors.append(err)
    if args.lane in ("both", "api"):
        api, errs, groups = pull_api(since, salt, chats, channels)
        lanes.append(api)
        errors.extend(errs)

    messages = merge(lanes)
    for m in messages:
        if m["is_group"] and not m["chat_name"]:
            m["chat_name"] = groups.get(m["chat_key"])

    result = {
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": args.hours,
        "since": since.isoformat(),
        "lanes": args.lane,
        "channels": channels,
        "status": "ok" if not errors else ("partial" if messages else "error"),
        "errors": errors,
        "count": len(messages),
        "counts_by_lane": {lane: sum(1 for m in messages if m["lane"] == lane)
                           for lane in ("capture", "api")},
        "counts_by_channel": {c: sum(1 for m in messages if m["channel"] == c) for c in channels},
        "messages": messages,
    }
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(payload + "\n")
        print("wrote %d messages to %s (status: %s)" % (len(messages), args.out, result["status"]))
    else:
        print(payload)
    sys.exit(0 if result["status"] != "error" else 1)


if __name__ == "__main__":
    main()
