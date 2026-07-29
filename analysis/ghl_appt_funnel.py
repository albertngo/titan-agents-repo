#!/usr/bin/env python3
"""Appointment funnel over ALL GoHighLevel opportunities, not just wins.

Read-only against GHL (uses $GHL_PIT_TOKEN / $GHL_LOCATION_ID).
Pulls every opportunity (open/won/lost/abandoned), every calendar event, and
every referenced contact; joins appointments to opportunities on the same
deal-scoped window as ghl_win_timeline.py v2; writes per-opportunity rows and
aggregates by outcome and source.

Appointments come from the calendars API (booking time = event dateAdded),
NOT from conversation TYPE_ACTIVITY_APPOINTMENT events — pulling conversations
for ~1,700 contacts costs 10x more API calls. The two sources are reconciled
in the validation block against the won corpus, where both exist; read the
coverage numbers there before trusting per-source appointment rates.

Raw pulls are cached under analysis/cache/ (gitignored, regenerable with
--refresh; contacts/ is shared with ghl_win_timeline.py). Outputs land in
analysis/output/ and ARE committed — same PII tradeoff as the won analysis.

Usage: python3 analysis/ghl_appt_funnel.py [--refresh]
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

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
OUT = ROOT / "output"

SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"Bearer {TOKEN}",
    "Version": "2021-07-28",
    "Accept": "application/json",
})

# PIT burst limit is 100 req/10s; stay well under it.
MIN_INTERVAL = 0.17
_last_call = [0.0]

# Same constant, same meaning as ghl_win_timeline.py — one line defines both
# "repeat customer" and the deal-activity window. Definitions live in
# methods/ghl-analysis-framework.md.
REPEAT_GAP_DAYS = 30

# Calendar events are pulled month-by-month from here to now. Earliest known
# contact in the corpus is 2022; a few empty months cost one call each.
EVENTS_FROM = datetime(2022, 1, 1, tzinfo=timezone.utc)


def get(path, params=None):
    wait = MIN_INTERVAL - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    for attempt in range(5):
        _last_call[0] = time.monotonic()
        r = SESSION.get(f"{BASE}{path}", params=params, timeout=30)
        if r.status_code == 404:
            return None
        # 401 included: GHL intermittently rejects a valid PIT mid-burst
        # (observed 2026-07-29, single 401 in ~1,900 calls, same call 200 on
        # retry). A genuinely dead token exhausts the retries and still raises.
        if r.status_code in (401, 429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"giving up on {path} after retries (last {r.status_code})")


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


def days(a, b):
    return round((b - a).total_seconds() / 86400, 1)


# ---------- pulls ----------

def pull_all_opportunities():
    def fetch():
        opps, params = [], {"location_id": LOCATION, "limit": 100}
        while True:
            page = get("/opportunities/search", params)
            opps.extend(page.get("opportunities", []))
            meta = page.get("meta", {})
            print(f"  opportunities: {len(opps)}/{meta.get('total')}")
            if not meta.get("nextPageUrl"):
                return opps
            params["startAfter"] = meta["startAfter"]
            params["startAfterId"] = meta["startAfterId"]
    return cached(CACHE / "all_opportunities.json", fetch)


def pull_pipelines():
    return cached(CACHE / "pipelines.json",
                  lambda: get("/opportunities/pipelines", {"locationId": LOCATION}))


def pull_calendars():
    return cached(CACHE / "calendars.json",
                  lambda: get("/calendars/", {"locationId": LOCATION}))


def pull_calendar_events(calendar_id):
    """All events for one calendar, month-windowed so the cache is resumable."""
    events = []
    cursor = EVENTS_FROM
    now = datetime.now(tz=timezone.utc)
    while cursor < now:
        nxt = (cursor.replace(day=1) + timedelta(days=32)).replace(day=1)
        window = f"{cursor:%Y-%m}"
        def fetch(cursor=cursor, nxt=nxt):
            page = get("/calendars/events", {
                "locationId": LOCATION, "calendarId": calendar_id,
                "startTime": int(cursor.timestamp() * 1000),
                "endTime": int(min(nxt, now).timestamp() * 1000),
            })
            return (page or {}).get("events", [])
        events.extend(cached(CACHE / "calendar_events" / f"{calendar_id}-{window}.json", fetch))
        cursor = nxt
    return events


def pull_contact(contact_id):
    return cached(CACHE / "contacts" / f"{contact_id}.json",
                  lambda: get(f"/contacts/{contact_id}"))


# ---------- shaping ----------

def normalize_source(raw):
    """Source labels drift ('Store' vs 'store' vs trailing spaces) — see the
    2026-07-26 won analysis. Collapse case/whitespace variants, keep the rest."""
    s = (raw or "").strip()
    if not s:
        return "Unknown"
    canon = {"store": "Store", "meta ad": "Meta Ad", "google ad": "Google Ad"}
    return canon.get(s.lower(), s)


def build_row(opp, pipelines_by_id, appts_by_contact, contact):
    created = parse_ts(opp["createdAt"])
    status = opp.get("status", "open")
    closed = parse_ts(opp.get("lastStatusChangeAt")) if status != "open" else None
    window_end = closed or datetime.now(tz=timezone.utc)
    window_start = created - timedelta(days=REPEAT_GAP_DAYS)

    c = (contact or {}).get("contact", {})
    contact_added = parse_ts(c.get("dateAdded"))
    contact_to_opp = days(contact_added, created) if contact_added else None

    # First appointment BOOKED inside the deal window (booking time, not the
    # scheduled visit time — consistent with the conversation-event semantics
    # the won analysis used).
    appt = None
    for ev in appts_by_contact.get(opp.get("contactId"), []):
        booked = ev["booked"]
        if window_start <= booked <= window_end:
            appt = ev
            break

    pipeline = pipelines_by_id.get(opp.get("pipelineId"), opp.get("pipelineId") or "")
    return {
        "opportunity_id": opp["id"],
        "name": opp.get("name", ""),
        "contact_id": opp.get("contactId", ""),
        "status": status,
        "pipeline": pipeline,
        "source": normalize_source(opp.get("source") or c.get("source")),
        "value_cad": opp.get("monetaryValue") or 0,
        "opp_created_date": created.astimezone(TZ).strftime("%Y-%m-%d"),
        "close_date": closed.astimezone(TZ).strftime("%Y-%m-%d") if closed else "",
        "contact_added_date": contact_added.astimezone(TZ).strftime("%Y-%m-%d")
                              if contact_added else "",
        "days_contact_to_opp": contact_to_opp,
        "repeat_customer": contact_to_opp is not None and contact_to_opp > REPEAT_GAP_DAYS,
        "appt_booked": bool(appt),
        "appt_status": appt["status"] if appt else "",
        "appt_calendar": appt["calendar"] if appt else "",
        "days_opp_to_appt": days(created, appt["booked"]) if appt else None,
        "days_contact_to_appt": days(contact_added, appt["booked"])
                                if appt and contact_added else None,
        "days_booked_to_visit": days(appt["booked"], appt["start"])
                                if appt and appt["start"] else None,
        "days_appt_to_close": days(appt["booked"], closed) if appt and closed else None,
        "cycle_days": days(created, closed) if closed else None,
    }


# ---------- aggregation ----------

def five_num(values):
    if not values:
        return None
    vals = sorted(values)
    # method="inclusive" — same reasoning as ghl_win_timeline.py: descriptive
    # percentiles of observed deals must stay inside [min, max].
    q = statistics.quantiles(vals, n=4, method="inclusive") if len(vals) > 1 else None
    return {
        "n": len(vals),
        "min": vals[0],
        "p25": round(q[0], 1) if q else vals[0],
        "median": round(statistics.median(vals), 1),
        "p75": round(q[2], 1) if q else vals[0],
        "max": vals[-1],
        "avg": round(statistics.mean(vals), 1),
    }


def group_stats(rows, key):
    groups = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    out = {}
    for k, grp in sorted(groups.items(), key=lambda kv: str(kv[0])):
        booked = [r for r in grp if r["appt_booked"]]
        out[k] = {
            "n": len(grp),
            "appt_rate": round(len(booked) / len(grp), 2),
            "repeat_rate": round(sum(1 for r in grp if r["repeat_customer"]) / len(grp), 2),
            "opp_to_appt": five_num([r["days_opp_to_appt"] for r in booked]),
            "contact_to_appt": five_num([r["days_contact_to_appt"] for r in booked
                                         if r["days_contact_to_appt"] is not None]),
            "booked_to_visit": five_num([r["days_booked_to_visit"] for r in booked
                                         if r["days_booked_to_visit"] is not None]),
            "appt_to_close": five_num([r["days_appt_to_close"] for r in booked
                                       if r["days_appt_to_close"] is not None]),
            "value_total_cad": round(sum(r["value_cad"] for r in grp), 2),
        }
    return out


def validate_against_won_corpus(appts_by_contact):
    """Where conversation history is cached (the won corpus), check that the
    calendar pull sees the same appointments. Prints coverage; a big gap means
    a booking path (e.g. store walk-ins) never touches calendars."""
    msg_dir = CACHE / "messages"
    if not msg_dir.exists():
        print("  (no cached conversations — skipping)")
        return None
    matched = missing = 0
    missing_examples = []
    for f in msg_dir.glob("*.json"):
        cid = f.stem
        # Conversation appointment events log near the VISIT, calendar
        # dateAdded is the BOOKING — match against either timestamp.
        cal_times = [t for a in appts_by_contact.get(cid, [])
                     for t in (a["booked"], a["start"]) if t]
        for m in json.loads(f.read_text()):
            if m.get("messageType") != "TYPE_ACTIVITY_APPOINTMENT":
                continue
            ts = parse_ts(m.get("dateAdded"))
            if ts is None:
                continue
            if any(abs((ts - ct).total_seconds()) <= 86400 for ct in cal_times):
                matched += 1
            else:
                missing += 1
                if len(missing_examples) < 5:
                    missing_examples.append((cid, str(ts.date()), (m.get("body") or "")[:40]))
    total = matched + missing
    coverage = round(matched / total, 2) if total else None
    print(f"  conversation appointments matched in calendars: {matched}/{total}"
          f" ({coverage:.0%})" if total else "  no conversation appointments found")
    for ex in missing_examples:
        print(f"    unmatched e.g.: {ex}")
    return {"matched": matched, "total": total, "coverage": coverage,
            "note": "conversation TYPE_ACTIVITY_APPOINTMENT events (won corpus) "
                    "found in the calendar pull within ±1 day"}


def main():
    if not TOKEN or not LOCATION:
        sys.exit("GHL_PIT_TOKEN / GHL_LOCATION_ID not set")
    if "--refresh" in sys.argv and CACHE.exists():
        import shutil
        for sub in ("all_opportunities.json", "pipelines.json", "calendars.json",
                    "calendar_events"):
            p = CACHE / sub
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
    CACHE.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)

    print("Pulling pipelines…")
    pipelines = pull_pipelines() or {}
    pipelines_by_id = {p["id"]: p.get("name", p["id"])
                       for p in pipelines.get("pipelines", [])}

    print("Pulling all opportunities…")
    opps = pull_all_opportunities()
    print(f"  {len(opps)} opportunities")

    print("Pulling calendar events…")
    appts_by_contact = {}
    n_events = 0
    for cal in (pull_calendars() or {}).get("calendars", []):
        for ev in pull_calendar_events(cal["id"]):
            if ev.get("deleted"):
                continue
            booked = parse_ts(ev.get("dateAdded"))
            if booked is None or not ev.get("contactId"):
                continue
            n_events += 1
            appts_by_contact.setdefault(ev["contactId"], []).append({
                "booked": booked,
                "start": parse_ts(ev.get("startTime")),
                "status": ev.get("appointmentStatus", ""),
                "calendar": cal.get("name", cal["id"]).strip(),
            })
    for lst in appts_by_contact.values():
        lst.sort(key=lambda a: a["booked"])
    print(f"  {n_events} events across {len(appts_by_contact)} contacts")

    print("Validating calendar coverage against the won corpus…")
    validation = validate_against_won_corpus(appts_by_contact)

    print("Pulling contacts…")
    contact_ids = sorted({o["contactId"] for o in opps if o.get("contactId")})
    contacts = {}
    for i, cid in enumerate(contact_ids, 1):
        contacts[cid] = pull_contact(cid)
        if i % 100 == 0 or i == len(contact_ids):
            print(f"  contacts {i}/{len(contact_ids)}")

    rows = [build_row(o, pipelines_by_id, appts_by_contact,
                      contacts.get(o.get("contactId")))
            for o in opps]
    rows.sort(key=lambda r: r["opp_created_date"])

    with (OUT / "appt_funnel_rows.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    stats = {
        "generated_at": datetime.now(tz=TZ).isoformat(),
        "opportunities": len(rows),
        "calendar_events": n_events,
        "calendar_coverage_of_won_corpus": validation,
        "repeat_gap_days": REPEAT_GAP_DAYS,
        "by_status": group_stats(rows, lambda r: r["status"]),
        "by_status_source": group_stats(rows, lambda r: (r["status"], r["source"])),
        "by_source": group_stats(rows, lambda r: r["source"]),
        "by_pipeline_status": group_stats(rows, lambda r: (r["pipeline"], r["status"])),
    }
    stats["by_status_source"] = {f"{a}|{b}": v
                                 for (a, b), v in stats["by_status_source"].items()}
    stats["by_pipeline_status"] = {f"{a}|{b}": v
                                   for (a, b), v in stats["by_pipeline_status"].items()}
    (OUT / "appt_funnel_stats.json").write_text(json.dumps(stats, indent=2))
    print(f"\nWrote {OUT/'appt_funnel_rows.csv'} and {OUT/'appt_funnel_stats.json'}")
    print(json.dumps(stats["by_status"], indent=2))


if __name__ == "__main__":
    main()
