#!/usr/bin/env python3
"""Reconcile Calendar Log rows against Metricool's scheduled set — and say what changed.

Pure function, no I/O, same shape as content_media_select.py and
social_post_rebuild.py. The caller fetches; this decides.

    python3 scripts/social_publish_sweep.py \
        --rows rows.json --posts scheduled.json \
        --write-mode draft --timezone America/Toronto

Exit 0 always (a sweep has no refusal — it reports). Exit 1 = bad input.

WHY A SWEEP IS NEEDED AT ALL. `getScheduledPosts` returns only posts that have NOT
published. So the moment a post goes live it disappears from the only endpoint this
repo queries, and nothing notices. Without this, a row sits at `Scheduled` forever and
the Notion calendar stops describing reality about a week after go-live.

THE WHOLE DIFFICULTY: ABSENCE IS AMBIGUOUS. A uuid missing from the scheduled set can
mean three very different things:

    1. it published                     -> Posted
    2. somebody deleted it in the planner   -> never went out
    3. it was moved outside the queried window -> still pending, we just missed it

Writing `Posted` for case 2 records a post that never happened. Nothing downstream can
detect that later, because the evidence is gone from both systems. So this script
NEVER infers `Posted` from absence alone. It requires absence PLUS a due time that has
passed PLUS a wide enough query window, and even then only when publishing was
possible at all -- see the draft rule below.

THE DRAFT RULE. While `write_mode.mode` is `draft` every post carries `info.draft:
true`, and a Metricool draft does not publish when its time arrives -- that is what
draft means. So during draft mode, publication is impossible by construction and a
vanished uuid CANNOT be a publish. It is a human deleting something. The sweep
therefore refuses to mark anything `Posted` while draft mode is on, and reports the
disappearance for a person instead.

    NOT YET OBSERVED: no post has ever published through this pipeline, so the
    `published` and `overdue` verdicts below are reasoned from the endpoint contract
    and from what draft mode means, not from a run we have watched. The first live
    publish is the test. Watch it rather than trusting this docstring.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# How long after its due time a post may still legitimately appear as scheduled.
# Metricool publishes on a queue, not on the second; a post read at 10:00:30 for a
# 10:00 slot is normal, not a failure.
DEFAULT_GRACE_MINUTES = 30

# How far past its due time a row may sit before "still scheduled" stops being a
# plausible explanation and it reads as stuck.
DEFAULT_STUCK_HOURS = 6

FMT = "%Y-%m-%dT%H:%M:%S"

# Verdicts that call for a Notion write, and the Post Status each one sets.
WRITES = {
    "published": "Posted",
    "vanished_before_due": "Manual Required",
    "vanished_in_draft_mode": "Manual Required",
    "stuck_past_due": "Failed",
    "missing_uuid": "Manual Required",
}


# THE TWO SYSTEMS SPEAK DIFFERENT TIME. Notion's API returns Post Date as an
# INSTANT, normalised to UTC: 8pm Toronto comes back as "2026-09-16T00:00:00.000Z".
# Metricool returns publicationDate as a LOCAL WALL CLOCK plus a separate timezone
# field: the same moment is "2026-09-15T20:00:00" + "America/Toronto".
#
# So an offset-bearing value must be CONVERTED, never just stripped. Stripping "Z"
# off the Notion value above yields midnight on the wrong day -- four hours and one
# date out. That is not a cosmetic error: it reports date_drift on every correctly
# scheduled row, and it moves every deadline four hours early, so the sweep can call
# a post published before it has gone anywhere. Found on the first real row.
LOCAL_TZ = ZoneInfo("America/Toronto")
HAS_ZONE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


def parse_dt(value, tz=LOCAL_TZ):
    """Return the local wall-clock time as a naive datetime, or None.

    Naive-local is the pipeline's internal currency: the repo's convention is
    America/Toronto throughout, Metricool sends the zone separately, and mixing naive
    and aware datetimes raises at comparison time -- in a sweep that would blow up
    exactly when a row needed judging. So anything aware is converted to `tz` first
    and then flattened; anything already naive is taken as local.
    """
    if not value:
        return None
    text = str(value).strip()

    if HAS_ZONE.search(text):
        try:
            aware = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return aware.astimezone(tz).replace(tzinfo=None)

    for fmt in (FMT, "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def is_date_only(value):
    """True when Notion gave a DATE, not a datetime.

    Notion's Post Date is a date property whose `is_datetime` flag is per-row: a row
    can say '2026-09-15' with no time at all, and the first real row through this
    pipeline (TC-86) did exactly that. That is not midnight -- it is an unspecified
    time, and the two must not be confused. Treating it as 00:00 would (a) flag
    date_drift forever against a post scheduled at 20:00 the same day, and (b) make
    the row look overdue from 00:30, so a sweep could call it published twenty hours
    before it was due.
    """
    return bool(value) and "T" not in str(value).strip()


def end_of_day(dt):
    return dt.replace(hour=23, minute=59, second=59)


def scheduled_index(posts):
    """uuid -> post, from a getScheduledPosts response."""
    if isinstance(posts, dict) and "data" in posts:
        posts = posts["data"]
    if not isinstance(posts, list):
        raise ValueError("expected the getScheduledPosts {'data': [...]} envelope or a list")
    return {str(p.get("uuid")): p for p in posts if p.get("uuid")}


def classify(row, index, now, grace, stuck, draft_mode, window):
    """One row -> (verdict, detail). See the module docstring for the reasoning."""
    uuid = (row.get("Metricool UUID") or "").strip()
    raw_due = row.get("Post Date")
    due = parse_dt(raw_due)
    date_only = is_date_only(raw_due)

    if not uuid:
        return "missing_uuid", (
            "row is Scheduled but carries no Metricool UUID. A write died between "
            "Metricool and Notion, so this row's post cannot be identified -- check "
            "the planner by hand before re-running, or it will be scheduled twice."
        )

    post = index.get(uuid)

    if post is not None:
        live_due = parse_dt((post.get("publicationDate") or {}).get("dateTime"))
        # A date-only row names a DAY, so only the day can disagree. Comparing its
        # implicit midnight against a real scheduled time reports drift on every
        # correctly-scheduled row.
        drifted = bool(due and live_due) and (
            due.date() != live_due.date() if date_only else due != live_due
        )
        if drifted:
            return "date_drift", (
                f"Notion says {due:%Y-%m-%d %H:%M}, Metricool says {live_due:%Y-%m-%d %H:%M}. "
                "The row was edited after scheduling and never rescheduled. Fix with "
                "/content-schedule <logID> --reschedule; this sweep does not guess "
                "which date is the intended one."
            )
        if live_due and now - live_due > timedelta(hours=stuck):
            return "stuck_past_due", (
                f"due {live_due:%Y-%m-%d %H:%M}, still sitting in the scheduled set "
                f"{_ago(now - live_due)} later. Metricool did not publish it. Check the "
                "planner for a delivery error -- a network disconnect and an expired "
                "token both look like this."
            )
        return "still_scheduled", f"due {live_due:%Y-%m-%d %H:%M}" if live_due else "pending"

    # --- absent from the scheduled set: the ambiguous case ---

    if window and due and not (window[0] <= due <= window[1]):
        return "outside_window", (
            f"due {due:%Y-%m-%d %H:%M}, outside the queried range "
            f"{window[0]:%Y-%m-%d}..{window[1]:%Y-%m-%d}. Absence here means nothing. "
            "Widen the window and re-run rather than reading this as published."
        )

    if draft_mode:
        return "vanished_in_draft_mode", (
            "gone from the scheduled set while write_mode is 'draft'. A draft does not "
            "publish, so this CANNOT be a publication -- somebody deleted it in the "
            "planner. Not marked Posted."
        )

    if due is None:
        return "vanished_no_date", (
            "gone from the scheduled set, and the row has no Post Date to reason "
            "from. Cannot tell a publish from a deletion. Check the planner."
        )

    # For a date-only row the post could legitimately be scheduled any time that day,
    # so nothing before the day is out proves it published.
    deadline = end_of_day(due) if date_only else due
    if now < deadline + timedelta(minutes=grace):
        return "vanished_before_due", (
            f"gone from the scheduled set but not due until {deadline:%Y-%m-%d %H:%M}"
            f"{' (end of a date-only row)' if date_only else ''}. "
            "A post cannot publish before its time, so this is a deletion or a move "
            "made in the planner. Not marked Posted."
        )

    return "published", (
        f"due {deadline:%Y-%m-%d %H:%M}, no longer in the scheduled set "
        f"{_ago(now - deadline)} later. getScheduledPosts returns only unpublished posts, "
        "so it has published. Live URL is NOT recoverable from this endpoint -- it "
        "stays blank until somebody fills it or an analytics lookup is built."
    )


def _ago(delta):
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(delta.total_seconds() // 60)}m"
    if hours < 48:
        return f"{hours:.0f}h"
    return f"{hours / 24:.0f}d"


def sweep(rows, posts, now, grace, stuck, draft_mode, window=None):
    index = scheduled_index(posts)
    results, counts = [], {}
    for row in rows:
        verdict, detail = classify(row, index, now, grace, stuck, draft_mode, window)
        counts[verdict] = counts.get(verdict, 0) + 1
        entry = {
            "notion_page_url": row.get("url"),
            "content_name": row.get("Content Name"),
            "surface": row.get("Post To"),
            "metricool_uuid": (row.get("Metricool UUID") or "").strip() or None,
            "verdict": verdict,
            "detail": detail,
        }
        if verdict in WRITES:
            entry["set_post_status"] = WRITES[verdict]
        results.append(entry)

    return {
        "swept_at": now.strftime(FMT),
        "write_mode": "draft" if draft_mode else "live",
        "rows_examined": len(rows),
        "scheduled_posts_seen": len(index),
        "counts": counts,
        "results": results,
        "orphans": sorted(set(index) - {(r.get("Metricool UUID") or "").strip() for r in rows}),
        "_orphans_comment": (
            "uuids scheduled in Metricool that no Calendar Log row claims. Posted from "
            "the planner by hand, or a row was deleted after scheduling. Never "
            "actioned automatically -- this pipeline does not own posts it did not create."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=Path, required=True,
                    help="JSON list of Calendar Log rows with Post Status = Scheduled")
    ap.add_argument("--posts", type=Path, required=True, help="getScheduledPosts JSON")
    ap.add_argument("--write-mode", required=True, choices=("draft", "live"),
                    help="from social-destinations.json write_mode.mode — never guess it")
    ap.add_argument("--grace-minutes", type=int, default=DEFAULT_GRACE_MINUTES)
    ap.add_argument("--stuck-hours", type=int, default=DEFAULT_STUCK_HOURS)
    ap.add_argument("--window", nargs=2, metavar=("FROM", "TO"),
                    help="the range passed to getScheduledPosts, so a row outside it "
                         "is reported as unknowable rather than published")
    ap.add_argument("--now", help="override for tests; local YYYY-MM-DDTHH:MM:SS")
    args = ap.parse_args()

    try:
        rows = json.loads(args.rows.read_text())
        posts = json.loads(args.posts.read_text())
        if isinstance(rows, dict) and "results" in rows:
            rows = rows["results"]
        if not isinstance(rows, list):
            raise ValueError("--rows must be a JSON list of Calendar Log rows")
        window = None
        if args.window:
            window = (parse_dt(args.window[0]), parse_dt(args.window[1]))
            if not all(window):
                raise ValueError("--window values must be YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD")
        report = sweep(
            rows, posts,
            parse_dt(args.now) or datetime.now(),
            args.grace_minutes, args.stuck_hours,
            args.write_mode == "draft", window,
        )
    except (OSError, ValueError) as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
