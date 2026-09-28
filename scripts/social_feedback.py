#!/usr/bin/env python3
"""Decide which posts need stats, turn Metricool's rows into row writes, rank what works.

Pure function, no I/O, same shape as the other social deciders. The caller fetches
(Notion rows, getAnalyticsDataByMetrics per surface) and writes; this only decides.

    python3 scripts/social_feedback.py --mode due     --rows log.json --now 2026-09-28T12:00:00
    python3 scripts/social_feedback.py --mode match   --rows due.json --analytics stats.json
    python3 scripts/social_feedback.py --mode analyse --rows with-stats.json

Exit 0 = a report; exit 1 = bad input. Like the sweep, it decides per row and says why.

THE PULL SCHEDULE (Albert, 2026-09-28). Metricool's per-post numbers are LIFETIME TO
DATE, so a number is only comparable with another taken at the same age.

    day7     first run on/after day 7    main columns, frozen      -> every ranking
    day30    first run on/after day 30   '... 30d' columns, frozen -> long-tail view
    rolling  every 30 days from day 60   '... Latest', overwritten -> late-surge watch

Late Surge = Views Latest >= 2x Views 30d. Quiet = one rolling pull that added under 5%;
two in a row = Settled, and a settled row is never pulled again. Nothing is pulled past
12 months. Every pull is idempotent on its own '... Pulled At' date.

THE JOIN IS THE POST URL. Metricool's planner id and the network's own post id never map
to each other, but the row's Live URL (written by /content-sweep) equals the analytics
`url` field exactly. Without a Live URL it falls back to the time slot, and refuses when
two posts share one -- a wrong match writes another post's numbers onto this row and
nothing downstream could tell.

RATES, NOT COUNTS. A Facebook post with small reach and an Instagram post with large
reach can only be compared as rates, and they are compared only WITHIN a platform, never
across: each platform counts a "view" differently (Facebook's is 10 seconds).
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from social_publish_reconcile import BadInput, parse_local, unpack  # noqa: E402

DAY7, DAY30, ROLLING = "day7", "day30", "rolling"
ROLLING_START_DAYS = 60
ROLLING_EVERY_DAYS = 30
MAX_AGE_DAYS = 365
LATE_PULL_DAYS = 10          # a day-7 pull taken later than this is not ranked
SURGE_MULTIPLE = 2.0
QUIET_GROWTH = 0.05
EARLY_SIGNAL_N = 5
OUTLIER_MULTIPLE = 2.0
SLOT_TOLERANCE_HOURS = 12

# role in the registry's stats block -> Notion column, per pull
DAY7_COLUMNS = {
    "views": "Views", "reach": "Reach", "likes": "Likes", "comments": "Comments",
    "saves": "Saves", "shares": "Shares", "avg_watch_s": "Avg Watch Time (s)",
    "completion_pct": "Completion %",
}
DAY30_COLUMNS = {"views": "Views 30d", "saves": "Saves 30d", "shares": "Shares 30d",
                 "comments": "Comments 30d"}
LATEST_COLUMNS = {"views": "Views Latest", "saves": "Saves Latest",
                  "shares": "Shares Latest", "comments": "Comments Latest"}
PULLED_AT = {DAY7: "Stats Pulled At", DAY30: "30d Pulled At", ROLLING: "Latest Pulled At"}
COLUMNS = {DAY7: DAY7_COLUMNS, DAY30: DAY30_COLUMNS, ROLLING: LATEST_COLUMNS}

RATES = ("save_rate", "share_rate", "comment_rate", "engagement_rate")
DIMENSIONS = {
    "Hook Pattern": ("avg_watch_s", "completion_pct", "share_rate"),
    "Caption Formula": ("save_rate", "comment_rate", "engagement_rate"),
    "Series": RATES,
    "Content Type": RATES,
}
# The one CTA goal Metricool can measure directly. The others (quote, showroom, DM) are
# conversions that happen off-platform; they are reported against engagement and say so.
CTA_SIGNAL = {"Save": "save_rate"}


def get(row, name):
    """A column from either shape the caller may pass: plain, or SQL's date:<x>:start."""
    if name in row and row[name] not in (None, ""):
        return row[name]
    return row.get(f"date:{name}:start") or None


def num(value):
    """Metricool sends numbers as strings, and null for 'not available'. Never guess."""
    if value is None or value == "":
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return int(n) if n.is_integer() else n


def norm_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def norm_url(url):
    return str(url or "").strip().rstrip("/").lower()


def stats_block(registry, surface):
    entry = (registry.get("analytics", {}).get("surfaces", {}) or {}).get(surface) or {}
    return entry.get("stats")


def pull_age_days(row):
    """Days between going live and the day-7 pull. Over LATE_PULL_DAYS is not ranked."""
    posted, pulled = parse_local(get(row, "Posted At")), parse_local(get(row, PULLED_AT[DAY7]))
    if posted is None or pulled is None:
        return None
    return (pulled.date() - posted.date()).days


# ---- due ---------------------------------------------------------------------------

def due_pull(row, now, registry):
    """Which pull this row needs today, or (None, reason)."""
    if (row.get("Post Status") or "") != "Posted":
        return None, "not posted"
    surface = row.get("Post To")
    if not stats_block(registry, surface):
        return None, f"no stats mapping for {surface!r}"
    posted = parse_local(get(row, "Posted At"))
    if posted is None:
        return None, "no Posted At"
    age = (now - posted).total_seconds() / 86400
    if age < 7:
        return None, f"day {age:.0f}, first pull on day 7"
    if not get(row, PULLED_AT[DAY7]):
        return DAY7, f"day {age:.0f}"
    if age >= 30 and not get(row, PULLED_AT[DAY30]):
        return DAY30, f"day {age:.0f}"
    if (row.get("Tracking") or "") == "Settled":
        return None, "settled"
    if age > MAX_AGE_DAYS:
        return None, "past 12 months"
    if age < ROLLING_START_DAYS or not get(row, PULLED_AT[DAY30]):
        return None, f"day {age:.0f}, rolling pulls start on day {ROLLING_START_DAYS}"
    last = parse_local(get(row, PULLED_AT[ROLLING]))
    if last is None or (now - last) >= timedelta(days=ROLLING_EVERY_DAYS):
        return ROLLING, f"day {age:.0f}"
    return None, f"rolling pull taken {(now - last).days} days ago"


def due(rows, now, registry):
    out, skipped = [], {}
    for row in rows:
        pull, reason = due_pull(row, now, registry)
        if pull:
            out.append({"pull": pull, "reason": reason, "row": row})
        else:
            skipped[reason] = skipped.get(reason, 0) + 1
    by_surface = {}
    for d in out:
        by_surface.setdefault(d["row"].get("Post To"), []).append(d["row"].get("url"))
    return {"due": out, "by_surface": by_surface, "skipped": skipped}


# ---- match -------------------------------------------------------------------------

def find_post(row, posts):
    """(post, how) or (None, reason). URL first; slot only when there is no URL."""
    url = norm_url(row.get("Live URL"))
    if url:
        hits = [p for p in posts if norm_url(p.get("url")) == url]
        if len(hits) == 1:
            return hits[0], "url"
        if len(hits) > 1:
            return None, "two analytics rows share this Live URL"
        return None, ("Live URL not in the analytics pull -- widen the date range, or "
                      "the post was deleted")
    posted = parse_local(get(row, "Posted At"))
    if posted is None:
        return None, "no Live URL and no Posted At to match on"
    window = timedelta(hours=SLOT_TOLERANCE_HOURS)
    hits = [p for p in posts
            if (t := parse_local(p.get("posted_at"))) is not None and abs(t - posted) <= window]
    if len(hits) == 1:
        return hits[0], "slot"
    if not hits:
        return None, f"no post on this surface within {SLOT_TOLERANCE_HOURS}h and no Live URL"
    return None, (f"{len(hits)} posts within {SLOT_TOLERANCE_HOURS}h and no Live URL -- "
                  "refusing to guess which is this row's")


def writes_for(pull, row, post, stats, now):
    cols = COLUMNS[pull]
    write = {}
    for role, col in cols.items():
        if role in stats:
            v = num(post.get(role))
            if v is not None:
                write[col] = v
    write[PULLED_AT[pull]] = now.strftime("%Y-%m-%d")
    notes = []
    if pull == DAY7:
        write["Tracking"] = "Active"
        posted, cap = row.get("Posted Caption"), row.get("Caption")
        if posted and cap:
            write["Caption Edited"] = norm_text(posted) != norm_text(cap)
        age = pull_age_days({"Posted At": get(row, "Posted At"),
                             PULLED_AT[DAY7]: write[PULLED_AT[DAY7]]})
        if age is not None and age > LATE_PULL_DAYS:
            notes.append(f"first pull on day {age}: kept, but not ranked with day-7 pulls")
    elif pull == ROLLING:
        latest = num(write.get(LATEST_COLUMNS["views"]))
        base30 = num(row.get("Views 30d"))
        prev = num(row.get("Views Latest"))
        before = prev if prev is not None else base30
        if latest is not None and base30 and latest >= SURGE_MULTIPLE * base30:
            write["Tracking"] = "Late Surge"
            notes.append(f"LATE SURGE: {latest} views vs {base30} at day 30")
        elif latest is not None and before:
            growth = (latest - before) / before
            if growth < QUIET_GROWTH:
                was_quiet = (row.get("Tracking") or "") == "Quiet"
                write["Tracking"] = "Settled" if was_quiet else "Quiet"
                notes.append(f"views +{growth:.1%} since last pull"
                             + (" (second quiet pull: tracking stops)" if was_quiet else ""))
            elif (row.get("Tracking") or "") == "Quiet":
                write["Tracking"] = "Active"
    return write, notes


def match(due_items, analytics, registry, now):
    unpacked = {}
    for surface, raw in analytics.items():
        stats = stats_block(registry, surface)
        if not stats:
            raise BadInput(f"analytics given for {surface!r}, which has no stats mapping")
        rows = raw.get("rows", raw) if isinstance(raw, dict) else raw
        unpacked[surface] = (stats, unpack(rows, stats))
    results = []
    for item in due_items:
        row, pull = item["row"], item["pull"]
        surface = row.get("Post To")
        entry = {"notion_page_url": row.get("url"), "content_name": row.get("Content Name"),
                 "surface": surface, "pull": pull}
        if surface not in unpacked:
            entry.update(verdict="not_pulled", detail=f"no analytics supplied for {surface}")
        else:
            stats, posts = unpacked[surface]
            post, how = find_post(row, posts)
            if post is None:
                entry.update(verdict="unmatched", detail=how)
            else:
                write, notes = writes_for(pull, row, post, stats, now)
                entry.update(verdict="matched", matched_by=how, write=write, notes=notes)
        results.append(entry)
    counts = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"matched_at": now.strftime("%Y-%m-%dT%H:%M:%S"), "counts": counts,
            "results": results,
            "surges": [r for r in results if r.get("write", {}).get("Tracking") == "Late Surge"]}


# ---- analyse -----------------------------------------------------------------------

def rates(row):
    views = num(row.get("Views"))
    out = {"avg_watch_s": num(row.get("Avg Watch Time (s)")),
           "completion_pct": num(row.get("Completion %"))}
    parts = {k: num(row.get(c)) for k, c in
             (("saves", "Saves"), ("shares", "Shares"), ("comments", "Comments"), ("likes", "Likes"))}
    for name, key in (("save_rate", "saves"), ("share_rate", "shares"), ("comment_rate", "comments")):
        out[name] = parts[key] / views if views and parts[key] is not None else None
    known = [v for v in parts.values() if v is not None]
    out["engagement_rate"] = sum(known) / views if views and known else None
    return out


def mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def values_of(row, dim):
    v = row.get(dim)
    if v in (None, "", []):
        return []
    if isinstance(v, str) and v.startswith("["):
        try:
            v = json.loads(v)
        except ValueError:
            pass
    return v if isinstance(v, list) else [v]


def analyse(rows):
    ranked, excluded = [], []
    for row in rows:
        if num(row.get("Views")) is None:
            excluded.append({"row": row.get("url"), "why": "no day-7 stats"})
        elif (pull_age_days(row) or 0) > LATE_PULL_DAYS:
            excluded.append({"row": row.get("url"), "why": "first pulled after day 10"})
        else:
            ranked.append(row)
    platforms = {}
    for row in ranked:
        platforms.setdefault(row.get("Post To"), []).append((row, rates(row)))
    report = {}
    for surface, items in platforms.items():
        metrics = ("avg_watch_s", "completion_pct") + RATES
        base = {m: mean(r[m] for _, r in items) for m in metrics}
        dims = {}
        for dim, dim_metrics in DIMENSIONS.items():
            groups = {}
            for row, r in items:
                if dim == "Caption Formula" and row.get("Caption Edited") in (True, "__YES__"):
                    continue    # the result belongs to Albert's edit, not the formula
                for value in values_of(row, dim):
                    groups.setdefault(value, []).append(r)
            dims[dim] = {
                value: {"n": len(rs),
                        "status": "early_signal" if len(rs) < EARLY_SIGNAL_N else "conclusion",
                        "metrics": {m: {"mean": mean(x[m] for x in rs),
                                        "vs_platform": _ratio(mean(x[m] for x in rs), base[m])}
                                    for m in dim_metrics}}
                for value, rs in sorted(groups.items())}
        cta = {}
        for row, r in items:
            goal = row.get("CTA Goal")
            if not goal:
                continue
            metric = CTA_SIGNAL.get(goal, "engagement_rate")
            cta.setdefault(goal, {"metric": metric, "direct_signal": goal in CTA_SIGNAL,
                                  "values": []})["values"].append(r[metric])
        for goal, c in cta.items():
            m = mean(c.pop("values"))
            c.update(mean=m, vs_platform=_ratio(m, base[c["metric"]]))
        outliers = []
        for row, r in items:
            for m in ("save_rate", "share_rate", "engagement_rate", "avg_watch_s"):
                ratio = _ratio(r[m], base[m])
                if ratio is not None and (ratio >= OUTLIER_MULTIPLE or ratio <= 1 / OUTLIER_MULTIPLE):
                    outliers.append({"row": row.get("url"), "content_name": row.get("Content Name"),
                                     "metric": m, "vs_platform": ratio})
        report[surface] = {"posts": len(items), "platform_average": base,
                           "dimensions": dims, "cta_goal": cta, "outliers": outliers}
    return {"platforms": report, "excluded": excluded,
            "_rule": "Within-platform only. Fewer than 5 posts in a group is an early signal, "
                     "not a conclusion. Averages are Titan's own, never industry benchmarks."}


def _ratio(value, base):
    if value is None or not base:
        return None
    return round(value / base, 2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=("due", "match", "analyse"))
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--analytics", type=Path,
                    help="match: JSON {surface: getAnalyticsDataByMetrics response}")
    ap.add_argument("--registry", type=Path,
                    default=Path("platform-settings/social-destinations.json"))
    ap.add_argument("--now", help="local wall-clock time, America/Toronto (default: now)")
    args = ap.parse_args()
    try:
        registry = json.loads(args.registry.read_text())
        now = parse_local(args.now) if args.now else datetime.now()
        if now is None:
            raise BadInput(f"--now {args.now!r} is not a date")
        rows = json.loads(args.rows.read_text())
        if isinstance(rows, dict):
            rows = rows.get("results", rows.get("due", rows))
        if not isinstance(rows, list):
            raise BadInput("--rows must be a JSON list")
        if args.mode == "due":
            out = due(rows, now, registry)
        elif args.mode == "match":
            if not args.analytics:
                raise BadInput("--mode match needs --analytics")
            out = match(rows, json.loads(args.analytics.read_text()), registry, now)
        else:
            out = analyse(rows)
    except (OSError, ValueError, KeyError, BadInput) as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
