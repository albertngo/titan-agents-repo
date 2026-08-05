#!/usr/bin/env python3
"""Missed inbound calls for one GHL user (default: Pourya) + response quality.

Read-only against GHL (uses $GHL_PIT_TOKEN / $GHL_LOCATION_ID). Pulls every
conversation with activity in the analysis window, keeps inbound TYPE_CALL
messages routed to the target user (message.userId or the `to` number matching
his direct line), and classifies each as answered vs missed
(meta.call.status != "completed").

Consecutive missed calls from the same contact within EPISODE_GAP_MIN are one
"episode" — one caller ringing three times unanswered is one miss to respond
to, not three. Response = first outbound touch (call/SMS/email/WhatsApp, any
user) to that contact after the episode's last attempt; an inbound completed
call before any outbound touch counts as "caller reached us again" (resolved,
but not a response by us).

Raw pulls cached under analysis/cache/pourya_calls/ (gitignored).
Outputs: analysis/output/pourya_missed_calls.csv + .json summary.

Usage: python3 analysis/pourya_missed_calls.py [--refresh] [--days 61]
"""

import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE = "https://services.leadconnectorhq.com"
TOKEN = os.environ.get("GHL_PIT_TOKEN")
LOCATION = os.environ.get("GHL_LOCATION_ID")
TZ = ZoneInfo("America/Toronto")

TARGET_USER_ID = "rAMFCiXbAjJOEjtyyvmn"   # Pourya Lalee
TARGET_NAME = "Pourya"
TARGET_PHONE = "+16476060295"             # his GHL direct line
EPISODE_GAP_MIN = 60
RESPONSE_HORIZON_H = 72                   # stop looking for a response after this

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache" / "pourya_calls"
OUT = ROOT / "output"

SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"Bearer {TOKEN}",
    "Version": "2021-07-28",
    "Accept": "application/json",
})

MIN_INTERVAL = 0.17  # PIT burst limit is 100 req/10s
_last_call = [0.0]

OUTBOUND_TOUCH_TYPES = {
    "TYPE_SMS", "TYPE_CUSTOM_SMS", "TYPE_CUSTOM_PROVIDER_SMS",
    "TYPE_CAMPAIGN_SMS", "TYPE_CAMPAIGN_MANUAL_SMS",
    "TYPE_EMAIL", "TYPE_CUSTOM_EMAIL", "TYPE_CAMPAIGN_EMAIL",
    "TYPE_CUSTOM_PROVIDER_EMAIL",
    "TYPE_CALL", "TYPE_CUSTOM_CALL", "TYPE_CAMPAIGN_CALL",
    "TYPE_CAMPAIGN_MANUAL_CALL",
    "TYPE_WHATSAPP", "TYPE_FACEBOOK", "TYPE_INSTAGRAM", "TYPE_GMB",
    "TYPE_LIVE_CHAT", "TYPE_WEBCHAT",
}


def get(path, params=None):
    wait = MIN_INTERVAL - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    r = None
    for attempt in range(5):
        _last_call[0] = time.monotonic()
        try:
            r = SESSION.get(f"{BASE}{path}", params=params, timeout=30)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:
            return None
        # 401 included: GHL intermittently rejects a valid PIT mid-burst.
        if r.status_code in (401, 429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"giving up on {path} after retries "
                       f"(last {r.status_code if r is not None else 'timeout'})")


def cached(cache_file, fetch):
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    data = fetch()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data))
    return data


def parse_ts(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------- pulls ----------

def pull_window_conversations(since):
    """Every conversation whose last message falls on/after `since`."""
    def fetch():
        convs, seen = [], set()
        params = {
            "locationId": LOCATION, "limit": 100,
            "sortBy": "last_message_date", "sort": "desc",
        }
        while True:
            page = get("/conversations/search", params) or {}
            batch = page.get("conversations", [])
            if not batch:
                return convs
            oldest = None
            for c in batch:
                ts = c.get("lastMessageDate")
                ts = (datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                      if isinstance(ts, (int, float)) else parse_ts(ts))
                if ts:
                    oldest = ts
                if c["id"] in seen:
                    continue
                seen.add(c["id"])
                if ts and ts >= since:
                    convs.append({"id": c["id"], "contactId": c.get("contactId"),
                                  "lastMessageDate": ts.isoformat()})
            print(f"  conversations kept: {len(convs)} (oldest on page {oldest and oldest.date()})")
            if oldest is None or oldest < since:
                return convs
            params["startAfterDate"] = int(oldest.timestamp() * 1000)
    return cached(CACHE / "conversations.json", fetch)


def pull_messages(conv_id, since):
    def fetch():
        messages, last_id = [], None
        for _ in range(30):  # pagination safety cap
            params = {"limit": 100}
            if last_id:
                params["lastMessageId"] = last_id
            page = get(f"/conversations/{conv_id}/messages", params)
            block = (page or {}).get("messages", {})
            batch = block.get("messages", [])
            messages.extend(batch)
            oldest = min((parse_ts(m.get("dateAdded")) for m in batch
                          if m.get("dateAdded")), default=None)
            if not block.get("nextPage") or (oldest and oldest < since):
                break
            last_id = block.get("lastMessageId")
        return messages
    return cached(CACHE / "messages" / f"{conv_id}.json", fetch)


def pull_contact(contact_id):
    return cached(CACHE / "contacts" / f"{contact_id}.json",
                  lambda: get(f"/contacts/{contact_id}"))


# ---------- analysis ----------

def main():
    if not TOKEN or not LOCATION:
        sys.exit("GHL_PIT_TOKEN / GHL_LOCATION_ID missing from environment")
    if "--refresh" in sys.argv:
        import shutil
        shutil.rmtree(CACHE, ignore_errors=True)
    days = 61
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    print(f"window: {since.date()} → {now.date()} ({days}d)")

    convs = pull_window_conversations(since)
    print(f"{len(convs)} conversations in window")

    # Global per-contact message stream — a response can live in a sibling
    # conversation (calls and SMS sometimes split), so index by contact.
    by_contact = {}
    conv_contact = {}
    for i, c in enumerate(convs):
        msgs = pull_messages(c["id"], since)
        if i % 50 == 0:
            print(f"  messages: {i}/{len(convs)} conversations")
        for m in msgs:
            cid = m.get("contactId") or c.get("contactId")
            if not cid:
                continue
            conv_contact.setdefault(c["id"], cid)
            ts = parse_ts(m.get("dateAdded"))
            if ts is None:
                continue
            m["_ts"] = ts
            by_contact.setdefault(cid, []).append(m)
    for msgs in by_contact.values():
        msgs.sort(key=lambda m: m["_ts"])

    # Inbound calls to the target user, inside the window.
    def is_target(m):
        return (m.get("userId") == TARGET_USER_ID
                or (m.get("to") or "").strip() == TARGET_PHONE)

    inbound, statuses = [], {}
    for cid, msgs in by_contact.items():
        for m in msgs:
            if (m.get("messageType") == "TYPE_CALL"
                    and m.get("direction") == "inbound"
                    and since <= m["_ts"] <= now
                    and is_target(m)):
                st = ((m.get("meta") or {}).get("call") or {}).get("status") \
                     or m.get("status") or "unknown"
                statuses[st] = statuses.get(st, 0) + 1
                inbound.append((cid, m, st))
    print(f"inbound calls to {TARGET_NAME}: {len(inbound)}; statuses: {statuses}")

    MISSED = {"no-answer", "voicemail", "busy", "failed", "canceled", "no_answer"}
    missed = [(cid, m, st) for cid, m, st in inbound if st in MISSED]
    answered = [x for x in inbound if x[2] == "completed"]

    # Group missed calls into episodes per contact.
    episodes = []
    by_c = {}
    for cid, m, st in sorted(missed, key=lambda x: x[1]["_ts"]):
        by_c.setdefault(cid, []).append((m, st))
    for cid, calls in by_c.items():
        cur = None
        for m, st in calls:
            if cur and (m["_ts"] - cur["last_ts"]).total_seconds() <= EPISODE_GAP_MIN * 60:
                cur["attempts"] += 1
                cur["last_ts"] = m["_ts"]
                cur["statuses"].append(st)
            else:
                cur = {"contactId": cid, "first_ts": m["_ts"], "last_ts": m["_ts"],
                       "attempts": 1, "statuses": [st]}
                episodes.append(cur)

    # Response per episode: first outbound touch after last attempt; note if an
    # inbound completed call arrived first instead.
    for ep in episodes:
        msgs = by_contact.get(ep["contactId"], [])
        horizon = ep["last_ts"] + timedelta(hours=RESPONSE_HORIZON_H)
        ep.update(response_type=None, response_min=None, responder=None,
                  caller_reached_us=False)
        for m in msgs:
            if m["_ts"] <= ep["last_ts"] or m["_ts"] > horizon:
                continue
            mtype = m.get("messageType", "")
            if m.get("direction") == "outbound" and mtype in OUTBOUND_TOUCH_TYPES:
                if mtype.endswith("CALL"):
                    cst = ((m.get("meta") or {}).get("call") or {}).get("status")
                    rtype = "callback-connected" if cst == "completed" else "callback-attempt"
                else:
                    rtype = "sms" if "SMS" in mtype else mtype.replace("TYPE_", "").lower()
                ep["response_type"] = rtype
                ep["response_min"] = round((m["_ts"] - ep["last_ts"]).total_seconds() / 60, 1)
                ep["responder"] = m.get("userId") or ""
                break
            if (mtype == "TYPE_CALL" and m.get("direction") == "inbound"
                    and ((m.get("meta") or {}).get("call") or {}).get("status") == "completed"):
                ep["caller_reached_us"] = True
                ep["response_type"] = "caller-called-back-and-connected"
                ep["response_min"] = round((m["_ts"] - ep["last_ts"]).total_seconds() / 60, 1)
                break

    # Contact names for the CSV.
    names = {}
    for ep in episodes:
        cid = ep["contactId"]
        if cid not in names:
            c = (pull_contact(cid) or {}).get("contact", {})
            names[cid] = (c.get("contactName")
                          or f"{c.get('firstName','')} {c.get('lastName','')}".strip()
                          or cid)

    OUT.mkdir(exist_ok=True)
    rows = []
    for ep in sorted(episodes, key=lambda e: e["first_ts"]):
        local = ep["first_ts"].astimezone(TZ)
        rows.append({
            "date": local.strftime("%Y-%m-%d"),
            "time_local": local.strftime("%H:%M"),
            "weekday": local.strftime("%a"),
            "contact": names[ep["contactId"]],
            "contact_id": ep["contactId"],
            "attempts": ep["attempts"],
            "statuses": "|".join(ep["statuses"]),
            "response_type": ep["response_type"] or "none-within-72h",
            "response_min": ep["response_min"],
            "responder_user_id": ep.get("responder") or "",
        })
    with open(OUT / "pourya_missed_calls.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else ["date"])
        w.writeheader()
        w.writerows(rows)

    # Weekly buckets (ISO week, local time) over the full window.
    weeks = {}
    for cid, m, st in inbound:
        wk = m["_ts"].astimezone(TZ).strftime("%G-W%V")
        weeks.setdefault(wk, {"inbound": 0, "missed": 0})
        weeks[wk]["inbound"] += 1
        weeks[wk]["missed"] += st in MISSED
    n_weeks = days / 7
    resp = [e for e in episodes if e["response_type"] and not e["caller_reached_us"]]
    resp_times = sorted(e["response_min"] for e in resp)
    within = lambda mins: sum(1 for t in resp_times if t <= mins)

    summary = {
        "window": {"since": since.isoformat(), "until": now.isoformat(), "days": days},
        "target": {"name": TARGET_NAME, "userId": TARGET_USER_ID, "phone": TARGET_PHONE},
        "inbound_calls": len(inbound),
        "answered": len(answered),
        "missed_calls": len(missed),
        "missed_episodes": len(episodes),
        "per_week": {
            "inbound": round(len(inbound) / n_weeks, 1),
            "missed_calls": round(len(missed) / n_weeks, 1),
            "missed_episodes": round(len(episodes) / n_weeks, 1),
        },
        "call_statuses": statuses,
        "weekly": dict(sorted(weeks.items())),
        "episode_outcomes": {
            "responded_by_us": len(resp),
            "caller_reached_us_first": sum(1 for e in episodes if e["caller_reached_us"]),
            "no_response_within_72h": sum(1 for e in episodes if not e["response_type"]),
        },
        "our_response_minutes": {
            "median": statistics.median(resp_times) if resp_times else None,
            "p75": (statistics.quantiles(resp_times, n=4, method="inclusive")[2]
                    if len(resp_times) >= 2 else None),
            "within_15m": within(15), "within_1h": within(60),
            "within_4h": within(240), "within_24h": within(1440),
        },
        "response_types": {},
    }
    for e in episodes:
        k = e["response_type"] or "none-within-72h"
        summary["response_types"][k] = summary["response_types"].get(k, 0) + 1
    (OUT / "pourya_missed_calls_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
