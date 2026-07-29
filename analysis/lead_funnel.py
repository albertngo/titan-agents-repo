#!/usr/bin/env python3
"""Lead-funnel analysis over the last N days of GoHighLevel opportunities.

Read-only against GHL (uses $GHL_PIT_TOKEN / $GHL_LOCATION_ID).
Pulls opportunities of ALL statuses (open/won/lost/abandoned), their contacts,
and conversation histories; normalizes lead source (see
methods/lead-funnel.md for the mapping and its precedence order); detects
booked appointments from conversation TYPE_ACTIVITY_APPOINTMENT events with
appt-* tag corroboration; writes lead_rows.csv + lead_stats.json.

Raw pulls are cached under analysis/cache/lead_funnel/ (gitignored,
regenerable with --refresh). Derived outputs land in analysis/output/ and are
committed — same PII tradeoff as won-analysis, accepted during build phase.

Usage: python3 analysis/lead_funnel.py [--refresh] [--days N]   (default 60)
"""

import csv
import json
import os
import shutil
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
CACHE = ROOT / "cache" / "lead_funnel"
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

STATUSES = ["open", "won", "lost", "abandoned"]

# Appointment window relative to the opportunity, mirroring won-analysis's
# REPEAT_GAP_DAYS logic: appointments logged shortly before the opp record
# (walk-ins) still count toward it.
APPT_LOOKBACK_DAYS = 30

STORE_PIPELINE_PREFIX = "STORE:"


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


# ---------- source normalization (methods/lead-funnel.md is the authority) ----------

def normalize_source(opp, contact, tags):
    """Return (normalized, raw, carrier). Precedence: opp.source >
    contact.source > source tags > first attribution."""
    c = (contact or {}).get("contact", {}) if contact else {}

    def bucket(raw):
        s = raw.strip().lower()
        s = s.removeprefix("online")  # 'onlineMeta Ad' → 'meta ad'
        if not s:
            return None
        if "meta" in s or "facebook" in s:
            return "Meta Ads"
        if "mobile quote" in s:
            return "Mobile Quote"
        if s in ("store", "lightspeed", "walk in", "walk-in", "pos"):
            return "Store / Walk-in"
        if "referral" in s or "recommended" in s or "refpro" in s:
            return "Referral"
        if "contractor" in s:
            return "Contractor"
        if "tradeshow" in s or "carrasauga" in s:
            return "Tradeshow"
        if "google" in s or "paid search" in s:
            return "Google"
        if "website" in s or s == "web":
            return "Website"
        if "estimate" in s or "appointment" in s or s == "calendar":
            return "Booked appointment (direct)"
        if "door hanger" in s or "flyer" in s or "neighbour" in s:
            return "Flyers / Door hangers"
        if "phone" in s or s == "call":
            return "Inbound call"
        if s in ("david", "pourya", "rep", "manual", "crm ui"):
            return "Rep / Manual"
        return None

    for carrier, raw in (
        ("opportunity.source", opp.get("source") or ""),
        ("contact.source", c.get("source") or ""),
    ):
        if raw.strip():
            b = bucket(raw)
            return (b or "Other", raw.strip(), carrier)

    SOURCE_TAGS = {
        "referral": "Referral", "website": "Website", "google-ad": "Google",
        "google lead": "Google", "meta-ad-b&a": "Meta Ads",
        "meta-ad-squeeky": "Meta Ads", "door hanger": "Flyers / Door hangers",
        "flyer ad": "Flyers / Door hangers",
        "contractor sms flyer": "Contractor", "real estate": "Referral",
        "refpro": "Referral", "rep": "Rep / Manual",
        "src: online": "Website",
    }
    for t in tags:
        tl = t.lower()
        if tl in SOURCE_TAGS:
            return (SOURCE_TAGS[tl], t, "tag")
        if tl.startswith("src: carrasauga"):
            return ("Tradeshow", t, "tag")

    for a in opp.get("attributions", []):
        if a.get("isFirst"):
            raw = a.get("utmSessionSource") or a.get("medium") or ""
            if raw:
                b = bucket(raw) or {
                    "paid social": "Meta Ads", "paid search": "Google",
                    "direct traffic": "Website", "social media": "Meta Ads",
                }.get(raw.strip().lower())
                return (b or "Other", raw.strip(), "attribution")

    return ("Unknown", "", "none")


# ---------- pulls ----------

def pull_opportunities(status):
    def fetch():
        opps, params = [], {"location_id": LOCATION, "status": status, "limit": 100}
        while True:
            page = get("/opportunities/search", params)
            opps.extend(page.get("opportunities", []))
            meta = page.get("meta", {})
            print(f"  {status}: {len(opps)}/{meta.get('total')}")
            if not meta.get("nextPageUrl"):
                return opps
            params["startAfter"] = meta["startAfter"]
            params["startAfterId"] = meta["startAfterId"]
    return cached(CACHE / f"opps_{status}.json", fetch)


def pull_pipelines():
    return cached(CACHE / "pipelines.json",
                  lambda: get("/opportunities/pipelines", {"locationId": LOCATION}))


def pull_contact(contact_id):
    return cached(CACHE / "contacts" / f"{contact_id}.json",
                  lambda: get(f"/contacts/{contact_id}"))


def pull_appt_events(contact_id):
    """Only TYPE_ACTIVITY_APPOINTMENT events are kept — a fraction of the
    won-analysis message pull, since the funnel needs booking signals, not
    touch metrics."""
    def fetch():
        found = get("/conversations/search",
                    {"locationId": LOCATION, "contactId": contact_id, "limit": 100}) or {}
        events = []
        for conv in found.get("conversations", []):
            last_id = None
            for _ in range(20):
                params = {"limit": 100}
                if last_id:
                    params["lastMessageId"] = last_id
                page = get(f"/conversations/{conv['id']}/messages", params)
                block = (page or {}).get("messages", {})
                for m in block.get("messages", []):
                    if m.get("messageType") == "TYPE_ACTIVITY_APPOINTMENT":
                        events.append({"dateAdded": m.get("dateAdded"),
                                       "body": m.get("body") or ""})
                if not block.get("nextPage"):
                    break
                last_id = block.get("lastMessageId")
        return events
    return cached(CACHE / "appt_events" / f"{contact_id}.json", fetch)


# ---------- main ----------

def main():
    if "--refresh" in sys.argv and CACHE.exists():
        shutil.rmtree(CACHE)
    window_days = 60
    if "--days" in sys.argv:
        window_days = int(sys.argv[sys.argv.index("--days") + 1])
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    pipelines = {p["id"]: p for p in (pull_pipelines() or {}).get("pipelines", [])}

    def stage_name(opp):
        p = pipelines.get(opp.get("pipelineId"))
        if not p:
            return ""
        for s in p.get("stages", []):
            if s["id"] == opp.get("pipelineStageId"):
                return s["name"].strip()
        return ""

    def pipeline_name(opp):
        p = pipelines.get(opp.get("pipelineId"))
        return p["name"].strip() if p else ""

    print("pulling opportunities (all statuses)...")
    window_opps = []
    for st in STATUSES:
        for o in pull_opportunities(st):
            created = parse_ts(o.get("createdAt"))
            if created and created >= cutoff:
                o["_status"] = st
                window_opps.append(o)
    print(f"in {window_days}d window: {len(window_opps)}")

    anomalies = {"contact_missing": 0, "no_created_ts": 0,
                 "unknown_source": 0, "cancel_only_appt": 0}
    rows = []
    for i, opp in enumerate(window_opps):
        if i % 50 == 0:
            print(f"  contacts/events: {i}/{len(window_opps)}")
        contact = pull_contact(opp["contactId"]) if opp.get("contactId") else None
        if contact is None:
            anomalies["contact_missing"] += 1
        c = (contact or {}).get("contact", {}) if contact else {}
        tags = c.get("tags", []) or []

        opp_created = parse_ts(opp["createdAt"])
        contact_added = parse_ts(c.get("dateAdded"))
        lead = min([d for d in (contact_added, opp_created) if d])

        norm, raw_src, carrier = normalize_source(opp, contact, tags)
        if norm == "Unknown":
            anomalies["unknown_source"] += 1

        events = pull_appt_events(opp["contactId"]) if opp.get("contactId") else []
        win_start = opp_created - timedelta(days=APPT_LOOKBACK_DAYS)
        appts = []
        for e in events:
            ts = parse_ts(e["dateAdded"])
            if ts and ts >= win_start:
                body = e["body"]
                mode = ("in-home" if body.startswith("Visit") else
                        "in-store" if body.startswith("Store") else "unknown")
                appts.append((ts, mode))
        appts.sort()

        appt_tags = sorted(t for t in tags
                           if t in ("appt-home", "appt-store", "appt-call"))
        cancelled_only = "appt-cancelled" in tags and not appt_tags and not appts
        if cancelled_only:
            anomalies["cancel_only_appt"] += 1
        booked = bool(appts) or bool(appt_tags)
        signal = ("both" if appts and appt_tags else
                  "event" if appts else "tag" if appt_tags else "")

        first_appt = appts[0] if appts else None
        rows.append({
            "opportunity_id": opp["id"],
            "name": opp.get("name", ""),
            "contact_id": opp.get("contactId", ""),
            "status": opp["_status"],
            "pipeline": pipeline_name(opp),
            "stage": stage_name(opp),
            "business": ("store" if pipeline_name(opp).startswith(STORE_PIPELINE_PREFIX)
                         else "project"),
            "source_normalized": norm,
            "source_raw": raw_src,
            "source_carrier": carrier,
            "value_cad": opp.get("monetaryValue") or 0,
            "lead_date": lead.astimezone(TZ).strftime("%Y-%m-%d"),
            "opp_created_date": opp_created.astimezone(TZ).strftime("%Y-%m-%d"),
            "appt_booked": booked,
            "appt_signal": signal,
            "appt_modes": "+".join(sorted({m for _, m in appts})) if appts else
                          ("+".join(t.removeprefix("appt-") for t in appt_tags)),
            "days_lead_to_appt": (round((first_appt[0] - lead).total_seconds() / 86400, 1)
                                  if first_appt else None),
        })

    # ---------- aggregates ----------
    by_day, by_source, by_day_source = {}, {}, {}
    for r in rows:
        d = r["opp_created_date"]
        by_day.setdefault(d, {"project": 0, "store": 0})
        by_day[d][r["business"]] += 1
        s = r["source_normalized"]
        by_source.setdefault(s, {"leads": 0, "appts": 0, "won": 0, "value_cad": 0})
        by_source[s]["leads"] += 1
        by_source[s]["appts"] += 1 if r["appt_booked"] else 0
        by_source[s]["won"] += 1 if r["status"] == "won" else 0
        by_source[s]["value_cad"] += r["value_cad"]
        by_day_source.setdefault(d, {}).setdefault(s, 0)
        by_day_source[d][s] += 1
    for s, v in by_source.items():
        v["appt_rate"] = round(v["appts"] / v["leads"], 3) if v["leads"] else 0

    stats = {
        "generated": datetime.now(TZ).isoformat(timespec="seconds"),
        "window_days": window_days,
        "total_leads": len(rows),
        "project_leads": sum(1 for r in rows if r["business"] == "project"),
        "store_leads": sum(1 for r in rows if r["business"] == "store"),
        "appt_booked_total": sum(1 for r in rows if r["appt_booked"]),
        "anomalies": anomalies,
        "by_day": by_day,
        "by_source": by_source,
        "by_day_source": by_day_source,
    }

    OUT.mkdir(exist_ok=True)
    with open(OUT / "lead_rows.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (OUT / "lead_stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps({k: stats[k] for k in
                      ("total_leads", "project_leads", "store_leads",
                       "appt_booked_total", "anomalies")}, indent=2))
    print(f"wrote {OUT / 'lead_rows.csv'} and {OUT / 'lead_stats.json'}")


if __name__ == "__main__":
    main()
