#!/usr/bin/env python3
"""
Read-only Meta Marketing API puller for meta-ads-ingest-agent.

Same rationale as scripts/outlook_pull.py: a session-attached connector dies
on scheduled runs and can't be resolved by subagents in deferred-tool
sessions. Bash always works. There is no Meta MCP in this environment anyway.

Auth: a long-lived System User access token (Meta Business Settings > System
Users; asset access to the ad account, ads_read permission only). GET only —
this script has no code path that writes to the ad account.

Usage:
    python3 scripts/meta_ads_pull.py --since 2026-08-09 --until 2026-08-09
    python3 scripts/meta_ads_pull.py --days 1                 # yesterday
    python3 scripts/meta_ads_pull.py --days 7 --out /tmp/baseline.json

One invocation pulls everything for the window: account health, per-campaign
insights, campaign statuses/budgets, and ads currently DISAPPROVED or
WITH_ISSUES. Emits JSON on stdout (--out <path> to write a file instead):
{status, errors[], account{}, insights[], campaigns[], flagged_ads[]}.

Env (see .env.example):
    META_ACCESS_TOKEN     system-user token, ads_read
    META_AD_ACCOUNT_ID    numeric id, with or without the act_ prefix
    META_API_VERSION      optional, default v23.0
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_VERSION = os.environ.get("META_API_VERSION", "v23.0")
GRAPH = "https://graph.facebook.com/%s" % API_VERSION

# Action types Meta uses for lead events, depending on where the lead form
# lives. `leads` per campaign = sum over these; raw actions ride along for
# audit so a new action_type is visible rather than silently dropped.
LEAD_ACTION_TYPES = {
    "lead",
    "leadgen_grouped",
    "onsite_conversion.lead_grouped",
    "offsite_conversion.fb_pixel_lead",
}

INSIGHTS_FIELDS = ",".join([
    "campaign_id", "campaign_name", "spend", "impressions", "clicks",
    "reach", "frequency", "actions", "cost_per_action_type",
])

CAMPAIGN_FIELDS = ",".join([
    "id", "name", "status", "effective_status", "objective",
    "daily_budget", "lifetime_budget", "start_time", "stop_time",
])

ACCOUNT_FIELDS = ",".join([
    "name", "account_status", "disable_reason", "currency", "timezone_name",
])

# graph.facebook.com account_status codes we care about naming.
ACCOUNT_STATUS = {
    1: "ACTIVE", 2: "DISABLED", 3: "UNSETTLED", 7: "PENDING_RISK_REVIEW",
    8: "PENDING_SETTLEMENT", 9: "IN_GRACE_PERIOD", 100: "PENDING_CLOSURE",
    101: "CLOSED",
}


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
            os.environ.setdefault(key, val)


def die(msg, hint=None, code=2):
    out = {"error": msg}
    if hint:
        out["hint"] = hint
    print(json.dumps(out, indent=2), file=sys.stderr)
    sys.exit(code)


def api_get(path, params, token):
    params = dict(params, access_token=token)
    url = "%s/%s?%s" % (GRAPH, path, urllib.parse.urlencode(params))
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def api_get_paged(path, params, token, max_pages=10):
    """Follow paging.next. Returns (rows, error_or_None)."""
    rows, url = [], None
    try:
        page = api_get(path, params, token)
        for _ in range(max_pages):
            rows.extend(page.get("data", []))
            url = page.get("paging", {}).get("next")
            if not url:
                return rows, None
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                page = json.load(r)
        return rows, "pagination stopped at %d pages" % max_pages
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        hint = ""
        try:
            err = json.loads(body).get("error", {})
            code = err.get("code")
            if code == 190:
                hint = " (code 190: token expired or revoked — first hypothesis, not an outage)"
            elif code in (4, 17, 32, 80004):
                hint = " (rate limited — retry later, do not tighten the loop)"
            body = err.get("message", body)
        except (ValueError, AttributeError):
            pass
        return rows, "%s: HTTP %s %s%s" % (path, e.code, body, hint)
    except Exception as e:  # network, timeout, bad JSON
        return rows, "%s: %s" % (path, e)


def currency_to_cents(val):
    """Meta returns money as decimal strings in the account currency."""
    if val in (None, ""):
        return None
    return int(round(float(val) * 100))


def leads_from_actions(actions):
    return sum(int(a.get("value", 0)) for a in (actions or [])
               if a.get("action_type") in LEAD_ACTION_TYPES)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="YYYY-MM-DD (ad-account timezone)")
    ap.add_argument("--until", help="YYYY-MM-DD (ad-account timezone)")
    ap.add_argument("--days", type=int, default=1,
                    help="last N full days ending yesterday; ignored if --since given")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    args = ap.parse_args()

    load_dotenv(os.path.join(REPO_ROOT, ".env"))
    token = os.environ.get("META_ACCESS_TOKEN")
    account = os.environ.get("META_AD_ACCOUNT_ID", "").strip()
    if not token or not account:
        die("Missing Meta credentials",
            "Set META_ACCESS_TOKEN and META_AD_ACCOUNT_ID (see .env.example). "
            "This is a setup gap, not a platform outage.")
    if not account.startswith("act_"):
        account = "act_" + account

    if args.since:
        since, until = args.since, args.until or args.since
    else:
        yesterday = date.today() - timedelta(days=1)
        since = (yesterday - timedelta(days=args.days - 1)).isoformat()
        until = yesterday.isoformat()

    errors = []

    # Account health first — a disabled account explains an empty insights pull.
    acct, err = {}, None
    try:
        acct = api_get(account, {"fields": ACCOUNT_FIELDS}, token)
    except urllib.error.HTTPError as e:
        err = "account: HTTP %s %s" % (e.code, e.read().decode("utf-8", "replace")[:300])
    except Exception as e:
        err = "account: %s" % e
    if err:
        errors.append(err)
    status_code = acct.get("account_status")
    acct["account_status_name"] = ACCOUNT_STATUS.get(status_code, str(status_code))

    insights, err = api_get_paged("%s/insights" % account, {
        "level": "campaign",
        "fields": INSIGHTS_FIELDS,
        "time_range": json.dumps({"since": since, "until": until}),
        "limit": 100,
    }, token)
    if err:
        errors.append(err)
    for row in insights:
        row["spend_cents"] = currency_to_cents(row.get("spend"))
        row["leads"] = leads_from_actions(row.get("actions"))

    campaigns, err = api_get_paged("%s/campaigns" % account, {
        "fields": CAMPAIGN_FIELDS, "limit": 100,
    }, token)
    if err:
        errors.append(err)
    for c in campaigns:
        c["daily_budget_cents"] = currency_to_cents(c.get("daily_budget"))
        c["lifetime_budget_cents"] = currency_to_cents(c.get("lifetime_budget"))

    flagged_ads, err = api_get_paged("%s/ads" % account, {
        "fields": "id,name,effective_status,campaign_id,ad_review_feedback",
        "filtering": json.dumps([{
            "field": "effective_status", "operator": "IN",
            "value": ["DISAPPROVED", "WITH_ISSUES"],
        }]),
        "limit": 100,
    }, token)
    if err:
        errors.append(err)

    got_anything = bool(acct.get("name") or insights or campaigns)
    result = {
        "status": "ok" if not errors else ("partial" if got_anything else "error"),
        "errors": errors,
        "window": {"since": since, "until": until,
                   "timezone": acct.get("timezone_name")},
        "account": acct,
        "insights": insights,
        "campaigns": campaigns,
        "flagged_ads": flagged_ads,
    }

    payload = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(payload)
        print("wrote %s (%s, %d insight rows)" % (args.out, result["status"], len(insights)))
    else:
        print(payload)
    sys.exit(0 if result["status"] != "error" else 1)


if __name__ == "__main__":
    main()
