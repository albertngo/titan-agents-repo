#!/usr/bin/env python3
"""
Read-only WhatsApp puller for whatsapp-ingest-agent (via 2Chat).

2Chat is the only source and the only store: it holds the messages for both connected
numbers, 1-to-1 and group chats. This script reads them through
scripts/twochat_client.py (GET only), for both numbers:

  1-to-1   GET /open/whatsapp/messages/{number}
  groups   GET /open/whatsapp/groups/{number}, then each group's messages

Each number, and each group, fails on its own: one failure makes the run `partial`,
never `error`, as long as anything came back. (A Make capture scenario and a Notion
archive were designed first and dropped on 2026-10-29: 2Chat already keeps the history,
group chats included, so nothing needs copying. See methods/whatsapp-ingest.md.)

Output (stdout, or --out) holds the full message text, because the agent needs it to
summarize. Always point --out under analysis/cache/whatsapp/ (gitignored). The
repo is public, so message text and phone numbers must never reach a committed file.
Phone numbers are emitted only as sha256(REQUESTER_ID_SALT + digits) plus the last
4 digits, as platform-settings/requesters.json requires.

Usage:
    python3 scripts/whatsapp_pull.py --hours 24 --out analysis/cache/whatsapp/2026-10-29.json
    python3 scripts/whatsapp_pull.py --hours 720 --channel business --out analysis/cache/whatsapp/q.json

Env (see .env.example):
    TWOCHAT_API_KEY, TWOCHAT_BUSINESS_NUMBER, TWOCHAT_PERSONAL_NUMBER, REQUESTER_ID_SALT
"""

import argparse
import hashlib
import json
import os
import re
import sys
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


def normalize(raw, channel, salt, chats, group=None, groups_by_wa_id=None):
    """One 2Chat message -> the record the agent reads. `group` is the group record
    from the groups listing, passed in for messages read per group.

    Field names pinned by the first live read (2026-10-29, methods/whatsapp-ingest.md):
      - session_key is "WW-<channel uuid>-<wa id>". The wa id ends "@g.us" for a group
        (it is the group's wa_group_id, so groups_by_wa_id maps it to uuid and name)
        and "@c.us" for a 1-to-1 chat. The number-level messages endpoint returns
        group messages too, so this is how they are recognised there.
      - remote_phone_number is set on 1-to-1 messages only; an inbound group message
        carries participant.phone_number / pushname instead.
      - sent_by "user" is the other side writing (inbound). "agent" (2Chat inbox),
        "api" and null (sent from the phone) are Titan's own (outbound).
      - created_at is naive UTC."""
    session_key = str(raw.get("session_key") or "")
    # "WW-" + 39-char channel uuid ("WPN" + 36) + "-" + wa id. Slice, don't split:
    # an old-style group wa id can contain a dash.
    wa_id = session_key[43:] if session_key.startswith("WW-WPN") else ""
    if not group and wa_id.endswith("@g.us"):
        group = (groups_by_wa_id or {}).get(wa_id) or {"uuid": wa_id}
    if group:
        raw = dict(raw)
        raw.setdefault("group", {"uuid": group.get("uuid"),
                                 "wa_group_name": group.get("wa_group_name") or group.get("name")})
    uuid = first(raw, "message_uuid", "uuid", "id", "message.id")
    if not uuid:
        return None
    is_group = bool(first(raw, "is_group", "group_uuid", "group.uuid") or
                    str(first(raw, "chat_uuid") or "").startswith("WAG"))
    chat_uuid = first(raw, "chat_uuid", "group_uuid", "group.uuid", "remote_phone_number", "contact.phone_number")
    peer = None if is_group else first(raw, "remote_phone_number", "peer_number", "contact.phone_number")
    contact_name = " ".join(x for x in (first(raw, "contact.first_name"), first(raw, "contact.last_name")) if x) or None
    direction = first(raw, "direction")
    if not direction:
        sent_by = str(raw.get("sent_by") or "").lower()
        if "sent_by" in raw:
            direction = "in" if sent_by in ("user", "contact") else "out"
        else:
            direction = "in"
    if direction == "out":
        sender = first(raw, "sender_number", "channel_phone_number")
    else:
        sender = first(raw, "sender_number", "participant.phone_number", "remote_phone_number")
    ts = parse_ts(first(raw, "sent_at", "created_at", "timestamp", "message.timestamp"))
    reg = chats.get(str(chat_uuid), {}) if chat_uuid else {}
    chat_key = (str(chat_uuid) if is_group else hash_number(chat_uuid, salt)) if chat_uuid else None
    return {
        "message_uuid": str(uuid),
        "channel": channel,
        "chat_key": chat_key,
        "chat_name": first(raw, "chat_name", "group_name", "wa_group_name", "group.wa_group_name", "contact.name") or (None if is_group else contact_name) or reg.get("label"),
        "is_group": is_group,
        "kind": reg.get("kind"),
        "sensitivity": reg.get("sensitivity"),
        "ghl_covered": bool(reg.get("ghl_covered")),
        "peer_hash": hash_number(peer, salt),
        "peer_last4": last4(peer),
        "sender_hash": hash_number(sender, salt),
        "sender_last4": last4(sender),
        "sender_name": first(raw, "sender_name", "participant.pushname", "participant.name", "contact.name") or contact_name,
        "direction": direction,
        "sent_at": ts.isoformat() if ts else None,
        "text": first(raw, "text", "message.text", "body") or "",
        "media_type": first(raw, "media_type", "message.media.type", "media.type"),
    }


# -- 2Chat (GET only, via twochat_client) ----------------------------------

def in_window(m, since):
    ts = parse_ts(m["sent_at"]) if m and m.get("sent_at") else None
    return ts is not None and ts >= since


def pull(since, salt, chats, channels, client=None):
    """Both numbers, 1-to-1 and groups. Returns (messages, errors)."""
    try:
        client = client or tc.TwoChatClient()
    except tc.TwoChatError as e:
        return [], [str(e)]
    out, errors = [], []
    for channel in channels:
        number = os.environ.get(CHANNEL_ENV[channel])
        if not number:
            errors.append("%s not set, %s number skipped" % (CHANNEL_ENV[channel], channel))
            continue
        try:
            groups = client.groups(number)
        except tc.TwoChatError as e:
            errors.append("%s group list: %s" % (channel, e))
            groups = None
        by_wa_id = {g["wa_group_id"]: g for g in groups or [] if g.get("wa_group_id")}
        try:
            for raw in client.messages(number, since=since):
                m = normalize(raw, channel, salt, chats, groups_by_wa_id=by_wa_id)
                if in_window(m, since):
                    out.append(m)
        except tc.TwoChatError as e:
            errors.append("%s 1-to-1 messages: %s" % (channel, e))
        if groups is None:
            continue
        for g in groups:
            if not g.get("uuid"):
                continue
            try:
                for raw in client.group_messages(g["uuid"], since=since):
                    m = normalize(raw, channel, salt, chats, group=g)
                    if in_window(m, since):
                        out.append(m)
            except tc.TwoChatError as e:
                errors.append("%s group %s: %s" % (channel, g.get("wa_group_name") or g["uuid"], e))
    return out, errors


def dedupe(messages):
    """One record per message uuid, oldest first."""
    seen = {}
    for m in messages:
        seen.setdefault(m["message_uuid"], m)
    return sorted(seen.values(), key=lambda m: m["sent_at"] or "")


def main():
    ap = argparse.ArgumentParser(description="Read-only WhatsApp puller (2Chat).")
    ap.add_argument("--hours", type=float, default=24)
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

    messages, errors = pull(since, salt, chats, channels)
    messages = dedupe(messages)

    result = {
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": args.hours,
        "since": since.isoformat(),
        "channels": channels,
        "status": "ok" if not errors else ("partial" if messages else "error"),
        "errors": errors,
        "count": len(messages),
        "groups": len({m["chat_key"] for m in messages if m["is_group"]}),
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
