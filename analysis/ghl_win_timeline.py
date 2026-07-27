#!/usr/bin/env python3
"""Win-timeline + activity analysis over GoHighLevel won opportunities.

Read-only against GHL (uses $GHL_PIT_TOKEN / $GHL_LOCATION_ID).
Pulls all won opportunities, their contacts, and full conversation
histories; computes lead-to-close durations, appointment timing, and
touch/workload metrics; writes CSV + stats JSON + markdown tables.

Raw pulls are cached under analysis/cache/ so re-runs only fetch what's
missing; that dir stays gitignored (full message bodies, regenerable with
--refresh). Outputs land in analysis/output/ and ARE committed during the
build phase — they contain customer PII and this repo is public, which is a
deliberate accepted tradeoff for now. See .gitignore.

Usage: python3 analysis/ghl_win_timeline.py [--refresh]
"""

import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
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

# Communication message types → channel buckets. TYPE_ACTIVITY_* and
# internal comments are events, not touches, and are handled separately.
CHANNEL_MAP = {
    "TYPE_SMS": "sms", "TYPE_CAMPAIGN_SMS": "sms", "TYPE_CUSTOM_SMS": "sms",
    "TYPE_CUSTOM_PROVIDER_SMS": "sms", "TYPE_SMS_REVIEW_REQUEST": "sms",
    "TYPE_SMS_NO_SHOW_REQUEST": "sms", "TYPE_CAMPAIGN_MANUAL_SMS": "sms",
    "TYPE_EMAIL": "email", "TYPE_CAMPAIGN_EMAIL": "email",
    "TYPE_CUSTOM_EMAIL": "email", "TYPE_CUSTOM_PROVIDER_EMAIL": "email",
    "TYPE_CALL": "call", "TYPE_CAMPAIGN_CALL": "call",
    "TYPE_CAMPAIGN_MANUAL_CALL": "call", "TYPE_CUSTOM_CALL": "call",
    "TYPE_IVR_CALL": "call", "TYPE_CAMPAIGN_VOICEMAIL": "call",
    "TYPE_WHATSAPP": "whatsapp",
    "TYPE_FACEBOOK": "social", "TYPE_CAMPAIGN_FACEBOOK": "social",
    "TYPE_INSTAGRAM": "social", "TYPE_GMB": "social", "TYPE_CAMPAIGN_GMB": "social",
    "TYPE_LIVE_CHAT": "chat", "TYPE_WEBCHAT": "chat",
}
AUTOMATED_TYPES = {t for t in CHANNEL_MAP if "CAMPAIGN" in t or t == "TYPE_IVR_CALL"}


def get(path, params=None):
    wait = MIN_INTERVAL - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    for attempt in range(5):
        _last_call[0] = time.monotonic()
        r = SESSION.get(f"{BASE}{path}", params=params, timeout=30)
        if r.status_code == 404:
            return None
        if r.status_code in (429, 500, 502, 503, 504):
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


# A contact whose record predates its opportunity by more than this is treated as a
# repeat customer. Threshold is a judgment call, not a GHL field — it is stated here
# and in methods/ghl-analysis-framework.md so the repeat rate is reproducible. Changing
# it changes every repeat figure downstream.
REPEAT_GAP_DAYS = 30


# ---------- pulls ----------

def pull_won_opportunities():
    def fetch():
        opps, params = [], {"location_id": LOCATION, "status": "won", "limit": 100}
        while True:
            page = get("/opportunities/search", params)
            opps.extend(page.get("opportunities", []))
            meta = page.get("meta", {})
            print(f"  opportunities: {len(opps)}/{meta.get('total')}")
            if not meta.get("nextPageUrl"):
                return opps
            params["startAfter"] = meta["startAfter"]
            params["startAfterId"] = meta["startAfterId"]
    return cached(CACHE / "won_opportunities.json", fetch)


def pull_contact(contact_id):
    return cached(CACHE / "contacts" / f"{contact_id}.json",
                  lambda: get(f"/contacts/{contact_id}"))


def pull_messages(contact_id):
    def fetch():
        found = get("/conversations/search",
                    {"locationId": LOCATION, "contactId": contact_id, "limit": 100}) or {}
        messages = []
        for conv in found.get("conversations", []):
            last_id = None
            for _ in range(20):  # pagination safety cap
                params = {"limit": 100}
                if last_id:
                    params["lastMessageId"] = last_id
                page = get(f"/conversations/{conv['id']}/messages", params)
                block = (page or {}).get("messages", {})
                messages.extend(block.get("messages", []))
                if not block.get("nextPage"):
                    break
                last_id = block.get("lastMessageId")
        return messages
    return cached(CACHE / "messages" / f"{contact_id}.json", fetch)


# ---------- per-opportunity record ----------

def build_record(opp, contact, messages, anomalies):
    close = parse_ts(opp.get("lastStatusChangeAt"))
    if close is None:
        close = parse_ts(opp.get("updatedAt"))
        anomalies["no_close_ts"] += 1
    opp_created = parse_ts(opp["createdAt"])

    c = (contact or {}).get("contact", {})
    contact_added = parse_ts(c.get("dateAdded"))
    if contact_added is None:
        anomalies["contact_missing"] += 1
    # Earliest credible lead date: contact creation usually precedes the
    # opportunity; take the earlier of the two.
    lead = min([d for d in (contact_added, opp_created) if d])

    duration = days(lead, close)
    # Sales-cycle time, distinct from lead age: contacts often predate their
    # opportunity by months (repeat customers), which inflates `duration_days`.
    cycle = days(opp_created, close)
    contact_to_opp = days(contact_added, opp_created) if contact_added else None
    source = (opp.get("source") or c.get("source") or "").strip() or "Unknown"

    attribution = ""
    for a in opp.get("attributions", []):
        if a.get("isFirst"):
            attribution = a.get("utmSessionSource") or a.get("medium") or ""
            break

    comm = []
    appts = []
    for m in messages:
        ts = parse_ts(m.get("dateAdded"))
        if ts is None:
            continue
        mtype = m.get("messageType", "")
        if mtype == "TYPE_ACTIVITY_APPOINTMENT":
            body = m.get("body") or ""
            mode = ("in-home" if body.startswith("Visit") else
                    "in-store" if body.startswith("Store") else "unknown")
            appts.append((ts, mode))
        elif mtype in CHANNEL_MAP:
            comm.append({
                "ts": ts,
                "direction": m.get("direction") or "unknown",
                "channel": CHANNEL_MAP[mtype],
                "automated": mtype in AUTOMATED_TYPES,
            })
    comm.sort(key=lambda m: m["ts"])
    appts.sort()

    pre = [m for m in comm if m["ts"] <= close]
    inbound = [m for m in pre if m["direction"] == "inbound"]
    outbound = [m for m in pre if m["direction"] == "outbound"]

    first_response_min = None
    if inbound:
        first_in = inbound[0]["ts"]
        later_out = [m["ts"] for m in outbound if m["ts"] > first_in]
        if later_out:
            first_response_min = round((later_out[0] - first_in).total_seconds() / 60, 1)

    cadence = None
    if len(outbound) >= 2:
        gaps = [(b["ts"] - a["ts"]).total_seconds() / 86400
                for a, b in zip(outbound, outbound[1:])]
        cadence = round(statistics.median(gaps), 2)

    first_appt = next((a for a in appts if a[0] <= close), None)
    appt_modes = sorted({mode for ts, mode in appts if ts <= close})

    channels = {}
    for m in pre:
        channels[m["channel"]] = channels.get(m["channel"], 0) + 1

    return {
        "opportunity_id": opp["id"],
        "name": opp.get("name", ""),
        "contact_id": opp.get("contactId", ""),
        "source": source,
        "attribution_first": attribution,
        "value_cad": opp.get("monetaryValue") or 0,
        "lead_date": lead.astimezone(TZ).strftime("%Y-%m-%d"),
        "opp_created_date": opp_created.astimezone(TZ).strftime("%Y-%m-%d"),
        "close_date": close.astimezone(TZ).strftime("%Y-%m-%d"),
        "close_month": close.astimezone(TZ).strftime("%Y-%m"),
        "duration_days": duration,
        "cycle_days": cycle,
        "days_contact_to_opp": contact_to_opp,
        "repeat_customer": contact_to_opp is not None and contact_to_opp > REPEAT_GAP_DAYS,
        "touches_total": len(pre),
        "touches_outbound": len(outbound),
        "touches_inbound": len(inbound),
        "touches_automated": sum(1 for m in pre if m["automated"]),
        "channels": json.dumps(channels, sort_keys=True),
        "first_response_min": first_response_min,
        "outbound_cadence_days": cadence,
        "appt_booked": bool(first_appt),
        "appt_modes": "+".join(appt_modes),
        "days_lead_to_appt": days(min([d for d in (contact_added, opp_created) if d]),
                                  first_appt[0]) if first_appt else None,
        "days_appt_to_close": days(first_appt[0], close) if first_appt else None,
        "touches_before_appt": sum(1 for m in comm if first_appt and m["ts"] <= first_appt[0])
                               if first_appt else None,
    }


# ---------- aggregation ----------

def five_num(values):
    if not values:
        return None
    vals = sorted(values)
    # method="inclusive": these percentiles are read as descriptions of the wins we
    # actually observed ("3 of every 4 from this source closed within X"), so they
    # must stay inside [min, max]. The default "exclusive" method estimates a wider
    # parent population and extrapolates past both ends — on a 3-4 win source, which
    # the by_source table has, that yields a p75 above every deal in the group and a
    # p25 that can go negative. A negative duration is not a follow-up window.
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
    for k, grp in sorted(groups.items()):
        durations = [r["duration_days"] for r in grp]
        out[k] = {
            "duration": five_num(durations),
            "cycle": five_num([r["cycle_days"] for r in grp if r["cycle_days"] >= 0]),
            "repeat_rate": round(sum(1 for r in grp if r["repeat_customer"]) / len(grp), 2),
            "value_total_cad": round(sum(r["value_cad"] for r in grp), 2),
            "touches": five_num([r["touches_total"] for r in grp]),
            "outbound": five_num([r["touches_outbound"] for r in grp]),
            "appt_rate": round(sum(1 for r in grp if r["appt_booked"]) / len(grp), 2),
            "lead_to_appt": five_num([r["days_lead_to_appt"] for r in grp
                                      if r["days_lead_to_appt"] is not None]),
            "appt_to_close": five_num([r["days_appt_to_close"] for r in grp
                                       if r["days_appt_to_close"] is not None]),
            "first_response_min": five_num([r["first_response_min"] for r in grp
                                            if r["first_response_min"] is not None]),
            "cadence_days": five_num([r["outbound_cadence_days"] for r in grp
                                      if r["outbound_cadence_days"] is not None]),
        }
    return out


DIST_BUCKETS = [(0, 1), (1, 3), (3, 7), (7, 14), (14, 30), (30, 60), (60, 90),
                (90, 180), (180, 100000)]


def distribution(rows):
    counts = {f"{lo}-{hi if hi < 100000 else '+'}d": 0 for lo, hi in DIST_BUCKETS}
    for r in rows:
        for lo, hi in DIST_BUCKETS:
            if lo <= r["duration_days"] < hi:
                counts[f"{lo}-{hi if hi < 100000 else '+'}d"] += 1
                break
    return counts


def main():
    if not TOKEN or not LOCATION:
        sys.exit("GHL_PIT_TOKEN / GHL_LOCATION_ID not set")
    if "--refresh" in sys.argv and CACHE.exists():
        import shutil
        shutil.rmtree(CACHE)
    CACHE.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)

    print("Pulling won opportunities…")
    opps = pull_won_opportunities()
    print(f"  {len(opps)} won opportunities")

    anomalies = {"no_close_ts": 0, "contact_missing": 0, "negative_duration": 0,
                 "negative_cycle": 0}
    rows, excluded = [], []
    for i, opp in enumerate(opps, 1):
        cid = opp.get("contactId")
        contact = pull_contact(cid) if cid else None
        messages = pull_messages(cid) if cid else []
        rec = build_record(opp, contact, messages, anomalies)
        if rec["duration_days"] < 0:
            anomalies["negative_duration"] += 1
            excluded.append(rec)
        else:
            # A row can have a valid lead-age but a negative cycle if the close
            # predates the opportunity record. Keep it — only the cycle aggregate
            # skips it — but surface the count.
            if rec["cycle_days"] < 0:
                anomalies["negative_cycle"] += 1
            rows.append(rec)
        if i % 25 == 0 or i == len(opps):
            print(f"  processed {i}/{len(opps)}")

    rows.sort(key=lambda r: r["close_date"])

    with (OUT / "won_rows.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    stats = {
        "generated_at": datetime.now(tz=TZ).isoformat(),
        "won_total": len(opps),
        "analyzed": len(rows),
        "anomalies": anomalies,
        "overall": {
            "duration": five_num([r["duration_days"] for r in rows]),
            "cycle": five_num([r["cycle_days"] for r in rows if r["cycle_days"] >= 0]),
            "repeat_rate": round(sum(1 for r in rows if r["repeat_customer"]) / len(rows), 2),
            "repeat_gap_days": REPEAT_GAP_DAYS,
            "distribution": distribution(rows),
            "appt_rate": round(sum(1 for r in rows if r["appt_booked"]) / len(rows), 2),
            "value_total_cad": round(sum(r["value_cad"] for r in rows), 2),
        },
        "by_month": group_stats(rows, lambda r: r["close_month"]),
        "by_source": group_stats(rows, lambda r: r["source"]),
        "by_month_source": group_stats(rows, lambda r: (r["close_month"], r["source"])),
        "by_appt_mode": group_stats([r for r in rows if r["appt_modes"]],
                                    lambda r: r["appt_modes"]),
    }
    # JSON keys must be strings
    stats["by_month_source"] = {f"{m}|{s}": v
                                for (m, s), v in stats["by_month_source"].items()}
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2))
    print(f"\nWrote {OUT/'won_rows.csv'} and {OUT/'stats.json'}")
    print(json.dumps({"overall": stats["overall"], "anomalies": anomalies}, indent=2))


if __name__ == "__main__":
    main()
