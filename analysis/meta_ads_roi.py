#!/usr/bin/env python3
"""Meta Ads ROI — ad spend joined to what the leads actually did in GHL.

Read-only. Meta side comes from scripts/meta_ads_pull.py (GET-only Marketing
API puller, same one meta-ads-ingest-agent uses); GHL side is pulled here with
$GHL_PIT_TOKEN / $GHL_LOCATION_ID.

Answers: what did the spend buy — leads, conversations, replies, appointments,
won work — and how fast did we respond. See methods/meta-ads-roi.md for the
attribution rule, the metric definitions, and the cohort-maturity caveat that
governs how the closing-end numbers may be read.

Raw pulls cache under analysis/cache/meta_roi/ (gitignored, regenerable).
Committed outputs: analysis/output/meta_roi_rows.csv, meta_roi_stats.json.

Usage:
    python3 analysis/meta_ads_roi.py [--days N] [--refresh] [--compare]

    --days N    window length, default 30 (full days ending yesterday)
    --compare   also compute the preceding window of equal length, for trend
    --label X   suffix the output filenames (a second window keeps its own pair)
    --wins-lookback N   how far back to resolve Meta-attributed wins (default 365)
"""

import csv
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
CACHE = ROOT / "cache" / "meta_roi"
OUT = ROOT / "output"
sys.path.insert(0, str(ROOT))
from lead_funnel import normalize_source  # the dirty-label map has one home

BASE = "https://services.leadconnectorhq.com"
TOKEN = os.environ.get("GHL_PIT_TOKEN")
LOCATION = os.environ.get("GHL_LOCATION_ID")
TZ = ZoneInfo("America/Toronto")

SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"Bearer {TOKEN}",
    "Version": "2021-07-28",
    "Accept": "application/json",
})

# PIT burst limit is 100 req/10s; stay well under it (same as sibling scripts).
MIN_INTERVAL = 0.17
_last_call = [0.0]

STATUSES = ["open", "won", "lost", "abandoned"]

# Communication message types → channel buckets, verbatim from
# ghl_win_timeline.py so touch counts are comparable across analyses.
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

# message.source values that mean "not a person typing". "app" = sent by a
# user from the GHL app; anything else on an outbound message is automation.
AUTOMATED_SOURCES = {"workflow", "campaign", "bulk_actions", "api", "automation"}

# An appointment counts for a lead if booked from its creation onward; leads
# born from an ad have no pre-history, so no lookback (unlike the
# opportunity-anchored analyses, which allow REPEAT_GAP_DAYS of runway).
APPT_TAGS = ("appt-home", "appt-store", "appt-call")


def get(path, params=None):
    wait = MIN_INTERVAL - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    for attempt in range(5):
        _last_call[0] = time.monotonic()
        r = SESSION.get(f"{BASE}{path}", params=params, timeout=30)
        if r.status_code == 404:
            return None
        # 401 included: GHL intermittently rejects a valid PIT mid-burst.
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


def pct(n, d):
    return round(n / d, 3) if d else None


def median(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 1) if vals else None


def p90(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    # Inclusive percentile, same convention as ghl-analysis-framework.md.
    k = (len(vals) - 1) * 0.9
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 1)


# ---------- Meta side ----------

def pull_meta(since, until):
    """scripts/meta_ads_pull.py is the only route to Meta (GET-only)."""
    def fetch():
        out = CACHE / f"meta_raw_{since}_{until}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(REPO / "scripts" / "meta_ads_pull.py"),
               "--since", since, "--until", until, "--out", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if not out.exists():
            raise RuntimeError(f"meta pull failed: {r.stdout}{r.stderr}")
        return json.loads(out.read_text())
    return cached(CACHE / f"meta_{since}_{until}.json", fetch)


# ---------- GHL side ----------

def pull_contacts(since_utc, until_utc, tag):
    """Contacts list is dateAdded-descending; page until older than the window."""
    def fetch():
        rows, params = [], {"locationId": LOCATION, "limit": 100}
        while True:
            page = get("/contacts/", params) or {}
            batch = page.get("contacts", [])
            if not batch:
                return rows
            oldest = None
            for c in batch:
                ts = parse_ts(c.get("dateAdded"))
                oldest = ts or oldest
                if ts and since_utc <= ts <= until_utc:
                    rows.append(c)
            meta = page.get("meta", {})
            print(f"  contacts scanned to {oldest}; kept {len(rows)}")
            if oldest and oldest < since_utc:
                return rows
            if not meta.get("nextPageUrl"):
                return rows
            params["startAfter"] = meta["startAfter"]
            params["startAfterId"] = meta["startAfterId"]
    return cached(CACHE / f"contacts_{tag}.json", fetch)


def pull_opportunities(status):
    def fetch():
        opps, params = [], {"location_id": LOCATION, "status": status, "limit": 100}
        while True:
            page = get("/opportunities/search", params)
            opps.extend(page.get("opportunities", []))
            meta = page.get("meta", {})
            if not meta.get("nextPageUrl"):
                return opps
            params["startAfter"] = meta["startAfter"]
            params["startAfterId"] = meta["startAfterId"]
    return cached(CACHE / f"opps_{status}.json", fetch)


def pull_contact(contact_id):
    return cached(CACHE / "contacts" / f"{contact_id}.json",
                  lambda: get(f"/contacts/{contact_id}"))


def pull_pipelines():
    return cached(CACHE / "pipelines.json",
                  lambda: get("/opportunities/pipelines", {"locationId": LOCATION}))


def pull_calendars():
    return cached(CACHE / "calendars.json",
                  lambda: get("/calendars/", {"locationId": LOCATION}))


def pull_calendar_events(calendar_id, since_utc, until_utc, tag):
    """Calendar bookings in the window. Second, independent appointment signal —
    conversation events and appt-* tags are the other two; methods/appt-funnel.md
    explains why no single one of them is trusted alone."""
    def fetch():
        page = get("/calendars/events", {
            "locationId": LOCATION, "calendarId": calendar_id,
            "startTime": int(since_utc.timestamp() * 1000),
            "endTime": int(until_utc.timestamp() * 1000),
        })
        return (page or {}).get("events", [])
    return cached(CACHE / "calendar_events" / f"{calendar_id}-{tag}.json", fetch)


def calendar_appts_by_contact(since_utc, until_utc, tag):
    """contact_id -> earliest (booking ts, calendar name). Booking moment is
    event.dateAdded, matching methods/appt-funnel.md; the visit itself may be
    later. The scheduled-visit window is widened past the lead window so a lead
    from the window's last days that books a visit for next month still counts."""
    out = {}
    cals = (pull_calendars() or {}).get("calendars", [])
    for cal in cals:
        for e in pull_calendar_events(cal["id"], since_utc,
                                      until_utc + timedelta(days=90), tag):
            if e.get("deleted"):
                continue
            cid = e.get("contactId")
            booked = parse_ts(e.get("dateAdded"))
            if not cid or not booked:
                continue
            prev = out.get(cid)
            if not prev or booked < prev[0]:
                out[cid] = (booked, cal.get("name", ""), e.get("appointmentStatus", ""),
                            parse_ts(e.get("startTime")))
    return out


def pull_messages(contact_id):
    """Every message on every conversation of one contact, newest page first."""
    def fetch():
        found = get("/conversations/search",
                    {"locationId": LOCATION, "contactId": contact_id, "limit": 100}) or {}
        msgs = []
        for conv in found.get("conversations", []):
            last_id = None
            for _ in range(20):
                params = {"limit": 100}
                if last_id:
                    params["lastMessageId"] = last_id
                page = get(f"/conversations/{conv['id']}/messages", params)
                block = (page or {}).get("messages", {})
                for m in block.get("messages", []):
                    msgs.append({
                        "dateAdded": m.get("dateAdded"),
                        "messageType": m.get("messageType"),
                        "direction": m.get("direction") or "unknown",
                        # GHL stamps every outbound message with how it was
                        # sent: "workflow"/"campaign"/"api" = automation,
                        # "app" = a person typing. messageType does NOT
                        # separate them — the instant follow-up SMS a workflow
                        # fires is a plain TYPE_SMS. See methods/meta-ads-roi.md.
                        "source": m.get("source") or "",
                        "userId": m.get("userId") or "",
                        "body": (m.get("body") or "")[:200],
                    })
                if not block.get("nextPage"):
                    break
                last_id = block.get("lastMessageId")
        return msgs
    return cached(CACHE / "messages" / f"{contact_id}.json", fetch)


# ---------- attribution ----------

def meta_attribution(contact, meta_campaign_ids):
    """(is_meta, signal, campaign_id, campaign_name, ad_id, creative).

    Attribution beats the source label here, deliberately: a Meta lead-form
    contact was observed carrying source "Direct" while its first attribution
    read Paid Social / facebook with the live campaign id. See
    methods/meta-ads-roi.md.
    """
    attrs = contact.get("attributions") or []
    attrs = sorted(attrs, key=lambda a: not a.get("isFirst"))  # isFirst first
    for a in attrs:
        blob = " ".join(str(a.get(k) or "").lower() for k in
                        ("adSource", "medium", "utmSource", "utmSessionSource"))
        cid = str(a.get("utmCampaignId") or "")
        hit = ("facebook" in blob or "instagram" in blob or "meta" in blob
               or "paid social" in blob or (cid and cid in meta_campaign_ids))
        if hit:
            return (True, "attribution", cid, a.get("utmCampaign") or "",
                    str(a.get("utmAdId") or ""), a.get("utmContent") or a.get("utmMedium") or "")
    tags = [t.lower() for t in (contact.get("tags") or [])]
    for t in tags:
        if t.startswith("meta-ad") or t in ("facebook", "facebook form lead"):
            return (True, "tag", "", "", "", t)
    norm, raw, carrier = normalize_source({"source": contact.get("source") or ""},
                                          {"contact": contact}, contact.get("tags") or [])
    if norm == "Meta Ads":
        return (True, f"source:{carrier}", "", "", "", raw)
    return (False, "", "", "", "", "")


# ---------- per-lead metrics ----------

def lead_row(c, opps_by_contact, pipelines, meta_campaign_ids, cal_appts):
    added = parse_ts(c.get("dateAdded"))
    tags = c.get("tags") or []
    is_meta, signal, camp_id, camp_name, ad_id, creative = meta_attribution(c, meta_campaign_ids)

    msgs = pull_messages(c["id"])
    comm, appt_events = [], []
    for m in msgs:
        ts = parse_ts(m.get("dateAdded"))
        if not ts:
            continue
        mt = m.get("messageType") or ""
        if mt == "TYPE_ACTIVITY_APPOINTMENT":
            appt_events.append((ts, m.get("body") or ""))
        elif mt in CHANNEL_MAP:
            src = (m.get("source") or "").lower()
            comm.append({"ts": ts, "direction": m["direction"],
                         "channel": CHANNEL_MAP[mt], "src": src,
                         "automated": mt in AUTOMATED_TYPES or src in AUTOMATED_SOURCES})
    comm.sort(key=lambda m: m["ts"])
    appt_events.sort()

    outbound = [m for m in comm if m["direction"] == "outbound"]
    inbound = [m for m in comm if m["direction"] == "inbound"]

    # Speed to lead: ad leads never message first, so the clock that matters
    # starts at contact creation and ends at our first outbound touch.
    speed_min = (round((outbound[0]["ts"] - added).total_seconds() / 60, 1)
                 if outbound and added else None)
    # The instant first touch is almost always the workflow firing. A human
    # picking the lead up is a different clock and the one Albert controls.
    manual_out = [m for m in outbound if not m["automated"]]
    speed_manual_min = (round((manual_out[0]["ts"] - added).total_seconds() / 60, 1)
                        if manual_out and added else None)
    # Our responsiveness once the lead does write back.
    first_response_min = first_response_manual_min = None
    if inbound:
        first_in = inbound[0]["ts"]
        later = [m["ts"] for m in outbound if m["ts"] > first_in]
        if later:
            first_response_min = round((later[0] - first_in).total_seconds() / 60, 1)
        later_manual = [m["ts"] for m in manual_out if m["ts"] > first_in]
        if later_manual:
            first_response_manual_min = round(
                (later_manual[0] - first_in).total_seconds() / 60, 1)

    appt_tags = sorted(t for t in tags if t in APPT_TAGS)
    first_appt = appt_events[0] if appt_events else None
    cal = cal_appts.get(c["id"])
    appt_booked = bool(first_appt) or bool(appt_tags) or bool(cal)
    signals = ("+".join(s for s, on in (("event", bool(first_appt)),
                                        ("tag", bool(appt_tags)),
                                        ("calendar", bool(cal))) if on))
    booked_ts = min([t for t in (first_appt[0] if first_appt else None,
                                 cal[0] if cal else None) if t], default=None)

    opp = opps_by_contact.get(c["id"])
    pipeline = stage = ""
    if opp:
        p = pipelines.get(opp.get("pipelineId")) or {}
        pipeline = (p.get("name") or "").strip()
        stage = next((s["name"].strip() for s in p.get("stages", [])
                      if s["id"] == opp.get("pipelineStageId")), "")

    return {
        "contact_id": c["id"],
        "name": c.get("contactName") or "",
        "date_added": added.astimezone(TZ).strftime("%Y-%m-%d %H:%M") if added else "",
        "week": added.astimezone(TZ).strftime("%G-W%V") if added else "",
        "is_meta": is_meta,
        "attr_signal": signal,
        "campaign_id": camp_id,
        "campaign": camp_name,
        "ad_id": ad_id,
        "creative": creative,
        "source_raw": c.get("source") or "",
        "assigned": bool(c.get("assignedTo")),
        "conversation": bool(comm),
        "touches_out": len(outbound),
        "touches_out_manual": sum(1 for m in outbound if not m["automated"]),
        "touches_out_automated": sum(1 for m in outbound if m["automated"]),
        "touches_in": len(inbound),
        "channels": "+".join(sorted({m["channel"] for m in comm})),
        "contacted": bool(outbound),
        "two_way": bool(inbound and outbound),
        "speed_to_lead_min": speed_min,
        "speed_to_lead_manual_min": speed_manual_min,
        "first_response_min": first_response_min,
        "first_response_manual_min": first_response_manual_min,
        "appt_booked": appt_booked,
        "appt_signal": signals,
        "appt_calendar": cal[1] if cal else "",
        "appt_status": cal[2] if cal else "",
        "appt_visit_date": (cal[3].astimezone(TZ).strftime("%Y-%m-%d")
                            if cal and cal[3] else ""),
        "days_lead_to_appt": (round((booked_ts - added).total_seconds() / 86400, 2)
                              if booked_ts and added else None),
        "has_opp": bool(opp),
        "opp_status": (opp or {}).get("status", ""),
        "opp_value_cad": (opp or {}).get("monetaryValue") or 0,
        "pipeline": pipeline,
        "stage": stage,
    }


def summarize(rows, meta, since, until):
    spend_cents = sum(i.get("spend_cents") or 0 for i in meta.get("insights", []))
    meta_leads = sum(i.get("leads") or 0 for i in meta.get("insights", []))
    clicks = sum(int(i.get("clicks") or 0) for i in meta.get("insights", []))
    impressions = sum(int(i.get("impressions") or 0) for i in meta.get("insights", []))

    n = len(rows)
    contacted = sum(1 for r in rows if r["contacted"])
    convo = sum(1 for r in rows if r["conversation"])
    two_way = sum(1 for r in rows if r["two_way"])
    appts = sum(1 for r in rows if r["appt_booked"])
    opps = sum(1 for r in rows if r["has_opp"])
    won = [r for r in rows if r["opp_status"] == "won"]
    open_ = [r for r in rows if r["opp_status"] == "open"]
    lost = [r for r in rows if r["opp_status"] in ("lost", "abandoned")]
    won_value = sum(r["opp_value_cad"] for r in won)
    pipe_value = sum(r["opp_value_cad"] for r in open_)

    def cost(k):
        return round(spend_cents / 100 / k, 2) if k else None

    return {
        "window": {"since": since, "until": until, "timezone": "America/Toronto"},
        "spend": {
            "spend_cad": round(spend_cents / 100, 2),
            "impressions": impressions,
            "clicks": clicks,
            "meta_reported_leads": meta_leads,
            "meta_cpl_cad": round(spend_cents / 100 / meta_leads, 2) if meta_leads else None,
            "account_status": meta.get("account", {}).get("account_status_name"),
            "currency": meta.get("account", {}).get("currency"),
        },
        "funnel": {
            "ghl_leads": n,
            "contacted": contacted,
            "conversations": convo,
            "two_way_conversations": two_way,
            "appointments": appts,
            "opportunities": opps,
            "won": len(won),
            "open": len(open_),
            "lost_or_abandoned": len(lost),
        },
        "rates": {
            "contacted_rate": pct(contacted, n),
            "reply_rate": pct(two_way, contacted),
            "appt_rate": pct(appts, n),
            "appt_rate_of_repliers": pct(appts, two_way),
            "won_rate_of_leads": pct(len(won), n),
            "won_rate_of_appts": pct(len(won), appts),
        },
        "cost_per": {
            "lead_ghl_cad": cost(n),
            "conversation_cad": cost(convo),
            "two_way_conversation_cad": cost(two_way),
            "appointment_cad": cost(appts),
            "won_job_cad": cost(len(won)),
        },
        "response": {
            "speed_to_lead_min_median": median([r["speed_to_lead_min"] for r in rows]),
            "speed_to_lead_min_p90": p90([r["speed_to_lead_min"] for r in rows]),
            "within_5_min": pct(sum(1 for r in rows if (r["speed_to_lead_min"] or 1e9) <= 5), n),
            "within_60_min": pct(sum(1 for r in rows if (r["speed_to_lead_min"] or 1e9) <= 60), n),
            "never_contacted": n - contacted,
            "speed_to_lead_manual_min_median": median([r["speed_to_lead_manual_min"] for r in rows]),
            "manual_touch_within_60_min": pct(
                sum(1 for r in rows if (r["speed_to_lead_manual_min"] or 1e9) <= 60), n),
            "never_touched_by_a_human": sum(1 for r in rows
                                            if r["speed_to_lead_manual_min"] is None),
            "reply_to_inbound_min_median": median([r["first_response_min"] for r in rows]),
            "reply_to_inbound_min_p90": p90([r["first_response_min"] for r in rows]),
            "reply_to_inbound_manual_min_median": median(
                [r["first_response_manual_min"] for r in rows]),
            "inbound_never_answered": sum(1 for r in rows if r["touches_in"]
                                          and r["first_response_min"] is None),
            "median_outbound_touches": median([r["touches_out"] for r in rows]),
        },
        "value": {
            "won_value_cad": won_value,
            "open_pipeline_value_cad": pipe_value,
            "roas_won": round(won_value / (spend_cents / 100), 2) if spend_cents else None,
            "roas_won_plus_open": (round((won_value + pipe_value) / (spend_cents / 100), 2)
                                   if spend_cents else None),
            "median_won_value_cad": median([r["opp_value_cad"] for r in won]),
            "note": ("opportunity monetaryValue = quoted/booked deal value in GHL, "
                     "not collected revenue; open pipeline is unrealized"),
        },
    }


def closed_wins(all_opps, since_utc, until_utc, meta_campaign_ids, lookback_days):
    """The other half of the ROI question.

    The lead cohort above answers "what did leads born in this window do" —
    honest, but its wins are immature. This answers "what closed in this
    window", whatever day the lead arrived. Both are true; neither alone is
    ROI. `lag_days` is why they differ.
    """
    horizon = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    wins, in_window = [], []
    for o in all_opps:
        if o.get("status") != "won":
            continue
        closed = parse_ts(o.get("lastStatusChangeAt"))
        if not closed or closed < horizon:
            continue
        cid = o.get("contactId")
        if not cid:
            continue
        c = (pull_contact(cid) or {}).get("contact")
        if not c:
            continue
        if not meta_attribution(c, meta_campaign_ids)[0]:
            continue
        added = parse_ts(c.get("dateAdded"))
        created = parse_ts(o.get("createdAt"))
        row = {
            "name": o.get("name", ""),
            "value_cad": o.get("monetaryValue") or 0,
            "lead_date": added.astimezone(TZ).strftime("%Y-%m-%d") if added else "",
            "opp_created": created.astimezone(TZ).strftime("%Y-%m-%d") if created else "",
            "closed": closed.astimezone(TZ).strftime("%Y-%m-%d"),
            "lead_to_win_days": (round((closed - added).total_seconds() / 86400, 1)
                                 if added else None),
            "opp_to_win_days": (round((closed - created).total_seconds() / 86400, 1)
                                if created else None),
        }
        wins.append(row)
        if since_utc <= closed <= until_utc:
            in_window.append(row)
    return {
        "lookback_days": lookback_days,
        "meta_wins_closed_in_window": len(in_window),
        "value_closed_in_window_cad": round(sum(r["value_cad"] for r in in_window), 2),
        "wins_in_window": sorted(in_window, key=lambda r: -r["value_cad"]),
        "lag_days": {
            "n": len(wins),
            "lead_to_win_median": median([r["lead_to_win_days"] for r in wins]),
            "lead_to_win_p90": p90([r["lead_to_win_days"] for r in wins]),
            "opp_to_win_median": median([r["opp_to_win_days"] for r in wins]),
        },
        "note": ("wins closed in the window against spend in the window is a "
                 "cash-period view, not a cohort return — the leads behind "
                 "these wins were mostly bought in earlier windows"),
    }


def maturity(rows, until):
    """Wins lag leads by weeks; a young cohort under-reports every closing
    metric. Report how old the cohort is rather than letting 0 wins read as a
    result."""
    end = datetime.combine(until, datetime.max.time(), TZ)
    ages = []
    for r in rows:
        d = datetime.strptime(r["date_added"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        ages.append(round((end - d).total_seconds() / 86400, 1))
    return {
        "median_lead_age_days": median(ages),
        "leads_older_than_30d": sum(1 for a in ages if a > 30),
        "still_open": sum(1 for r in rows if r["opp_status"] == "open"),
        "note": ("won counts here are a floor: leads younger than a typical "
                 "sales cycle have not had time to close"),
    }


def breakdown(rows, key):
    out = {}
    for r in rows:
        k = r[key] or "(none)"
        b = out.setdefault(k, {"leads": 0, "two_way": 0, "appts": 0, "won": 0,
                               "won_value_cad": 0})
        b["leads"] += 1
        b["two_way"] += 1 if r["two_way"] else 0
        b["appts"] += 1 if r["appt_booked"] else 0
        b["won"] += 1 if r["opp_status"] == "won" else 0
        b["won_value_cad"] += r["opp_value_cad"] if r["opp_status"] == "won" else 0
    for b in out.values():
        b["appt_rate"] = pct(b["appts"], b["leads"])
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["leads"]))


def build_window(since_d, until_d, opps_by_contact, pipelines, meta_campaign_ids, tag):
    since_utc = datetime.combine(since_d, datetime.min.time(), TZ).astimezone(timezone.utc)
    until_utc = datetime.combine(until_d, datetime.max.time(), TZ).astimezone(timezone.utc)
    meta = pull_meta(since_d.isoformat(), until_d.isoformat())
    meta_campaign_ids |= {str(i.get("campaign_id")) for i in meta.get("insights", [])}
    meta_campaign_ids |= {str(c.get("id")) for c in meta.get("campaigns", [])}

    cal_appts = calendar_appts_by_contact(since_utc, until_utc, tag)
    contacts = pull_contacts(since_utc, until_utc, tag)
    print(f"  {tag}: {len(contacts)} contacts in window; scanning attribution...")
    rows = []
    for i, c in enumerate(contacts):
        if i % 50 == 0:
            print(f"    {i}/{len(contacts)}")
        is_meta = meta_attribution(c, meta_campaign_ids)[0]
        if not is_meta:
            continue
        rows.append(lead_row(c, opps_by_contact, pipelines, meta_campaign_ids, cal_appts))
    return meta, rows, len(contacts)


def main():
    if not TOKEN or not LOCATION:
        sys.exit("Missing GHL_PIT_TOKEN / GHL_LOCATION_ID (see .env.example).")
    if "--refresh" in sys.argv and CACHE.exists():
        shutil.rmtree(CACHE)
    days = 30
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    # A second window (e.g. a 90-day close-rate view) writes its own files
    # instead of overwriting the default 30-day pair.
    label = ""
    if "--label" in sys.argv:
        label = "_" + sys.argv[sys.argv.index("--label") + 1]

    yesterday = datetime.now(TZ).date() - timedelta(days=1)
    since_d = yesterday - timedelta(days=days - 1)

    print("pulling opportunities (all statuses)...")
    opps_by_contact, pipelines, all_opps = {}, {}, []
    for st in STATUSES:
        for o in pull_opportunities(st):
            all_opps.append(o)
            cid = o.get("contactId")
            if not cid:
                continue
            prev = opps_by_contact.get(cid)
            # Keep the newest opportunity per contact; ad leads are new
            # records, so this only matters for the rare repeat customer.
            if not prev or (o.get("createdAt") or "") > (prev.get("createdAt") or ""):
                opps_by_contact[cid] = o
    pipelines = {p["id"]: p for p in (pull_pipelines() or {}).get("pipelines", [])}

    meta_campaign_ids = set()
    meta, rows, scanned = build_window(since_d, yesterday, opps_by_contact,
                                       pipelines, meta_campaign_ids, f"cur_{days}")
    stats = summarize(rows, meta, since_d.isoformat(), yesterday.isoformat())
    stats["attribution"] = {
        "contacts_scanned_in_window": scanned,
        "meta_attributed": len(rows),
        "by_signal": breakdown(rows, "attr_signal"),
        "note": ("attribution beats the source label — see methods/meta-ads-roi.md; "
                 "Meta's own lead count and GHL's contact count are different "
                 "counters and are expected to disagree"),
    }
    stats["maturity"] = maturity(rows, yesterday)
    win_lookback = 365
    if "--wins-lookback" in sys.argv:
        win_lookback = int(sys.argv[sys.argv.index("--wins-lookback") + 1])
    print("resolving Meta-attributed wins closed in the window...")
    stats["closed_wins"] = closed_wins(
        all_opps,
        datetime.combine(since_d, datetime.min.time(), TZ).astimezone(timezone.utc),
        datetime.combine(yesterday, datetime.max.time(), TZ).astimezone(timezone.utc),
        meta_campaign_ids, win_lookback)
    spend_cad = stats["spend"]["spend_cad"]
    cw = stats["closed_wins"]
    stats["value"]["closed_value_in_window_cad"] = cw["value_closed_in_window_cad"]
    stats["value"]["roas_closed_in_window"] = (
        round(cw["value_closed_in_window_cad"] / spend_cad, 2) if spend_cad else None)
    stats["appt_signal_mix"] = breakdown(rows, "appt_signal")
    stats["by_creative"] = breakdown(rows, "creative")
    stats["by_week"] = breakdown(rows, "week")

    if "--compare" in sys.argv:
        prev_until = since_d - timedelta(days=1)
        prev_since = prev_until - timedelta(days=days - 1)
        pmeta, prows, pscanned = build_window(prev_since, prev_until, opps_by_contact,
                                              pipelines, meta_campaign_ids,
                                              f"prev_{days}")
        stats["previous_window"] = summarize(prows, pmeta, prev_since.isoformat(),
                                             prev_until.isoformat())

    OUT.mkdir(exist_ok=True)
    rows_path = OUT / f"meta_roi_rows{label}.csv"
    stats_path = OUT / f"meta_roi_stats{label}.json"
    if rows:
        with open(rows_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    stats_path.write_text(json.dumps(stats, indent=2))
    print(json.dumps({k: stats[k] for k in ("window", "spend", "funnel", "rates",
                                            "cost_per", "response", "value")}, indent=2))
    print(f"wrote {rows_path} and {stats_path}")


if __name__ == "__main__":
    main()
