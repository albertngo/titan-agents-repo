#!/usr/bin/env python3
"""Match a vanished scheduled post to the published thing it became — or refuse.

Pure function, no I/O, same shape as the other three deciders. The caller fetches.

    python3 scripts/social_publish_reconcile.py \
        --rows vanished.json --analytics ig.json --surface 'Instagram Reels' \
        --registry platform-settings/social-destinations.json

Exit 0 = a report; exit 1 = bad input. Like the sweep, this never refuses wholesale —
it decides per row and says why.

WHY THIS EXISTS. scripts/social_publish_sweep.py can only observe an ABSENCE: a uuid
is no longer in the scheduled set. Absence is ambiguous (published / deleted /
outside the window), so the sweep surrounds it with four guards and still only ever
INFERS publication. This module removes the inference. Analytics is a second,
independent source: if a post exists there matching the slot, it published, and here
is its URL and the text it published with.

    sweep says      "uuid gone, due time passed"        -> a candidate
    this says       "and here it is, published, at this URL"  -> confirmed
    this says       "and there is nothing there"        -> NOT published; deleted

THE JOIN IS NOT AN ID. Metricool's planner uuid and the network's own post id live in
different namespaces, and nothing maps between them. So a published post is matched to
its row by SLOT: the same surface, within a tolerance of the time it was scheduled for.
That is a heuristic, and it is only sound at low volume -- at Titan's few-posts-a-week
it is unambiguous; at thirty a day it would not be. When two candidates fall in the
same window this module refuses rather than guessing, because a wrong match writes
another post's URL and caption onto this row and nothing downstream can detect it.

THE TOLERANCE IS DELIBERATELY WIDE. The analytics timestamp format is a compact
YYYYMMDDHHMMSS whose timezone is NOT confirmed (see the registry's analytics block).
Rather than depend on that, the matcher uses a window measured in hours. A timezone
error inside the window costs nothing; exact matching would have made the whole path
wrong in a way that looks like "the post was never published".
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Toronto")

# Hours either side of the scheduled slot in which a published post is considered the
# same post. Wide on purpose -- see the module docstring.
DEFAULT_TOLERANCE_HOURS = 12

COMPACT_TS = re.compile(r"^\d{14}$")
HAS_ZONE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


class BadInput(Exception):
    pass


def parse_local(value, tz=LOCAL_TZ, assume_utc=True):
    """Parse any timestamp these two systems emit into naive local wall-clock time.

    Three shapes reach this function:
      - Notion:    2026-09-17T00:00:00.000Z   (an instant, in UTC)
      - Metricool planner: 2026-09-16T20:00:00 (local wall clock, zone sent separately)
      - Metricool analytics: 20260806033114    (compact, believed UTC -- unconfirmed)
    """
    if not value:
        return None
    text = str(value).strip()

    if COMPACT_TS.match(text):
        naive = datetime.strptime(text, "%Y%m%d%H%M%S")
        if not assume_utc:
            return naive
        return naive.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).replace(tzinfo=None)

    if HAS_ZONE.search(text):
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(tz).replace(tzinfo=None)
        except ValueError:
            return None

    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def surface_fields(registry, surface):
    """Ordered {role: fieldId} for a surface, or raise. Order is load-bearing."""
    entry = (registry.get("analytics", {}).get("surfaces", {}) or {}).get(surface)
    if entry is None:
        raise BadInput(f"surface {surface!r} has no analytics mapping in the registry")
    if "_unavailable" in entry:
        raise BadInput(f"surface {surface!r}: {entry['_unavailable']}")
    fields = entry.get("fields")
    if not fields:
        raise BadInput(f"surface {surface!r} has no analytics fields mapped")
    return entry, fields


def unpack(rows, fields):
    """Positional analytics rows -> dicts, using the SAME order that was requested.

    getAnalyticsDataByMetrics returns bare arrays. If the request order and the
    unpack order ever diverge, columns transpose silently -- a caption lands in the
    url slot and nothing errors. Both sides come from this one ordered mapping.
    """
    roles = list(fields)
    out = []
    for row in rows:
        if len(row) != len(roles):
            raise BadInput(
                f"analytics row has {len(row)} columns but {len(roles)} metrics were "
                f"mapped for this surface. Refusing to unpack -- misaligned columns "
                f"would write a caption into the URL field with no error. Row: {row!r}"
            )
        out.append(dict(zip(roles, row)))
    return out


def reconcile_row(row, published, tolerance_hours, assume_utc=True):
    """One vanished row -> (verdict, detail, fields_to_write)."""
    due = parse_local(row.get("Post Date"))
    if due is None:
        return ("no_due_date",
                "the row has no Post Date, so there is no slot to match a published "
                "post against. Fix the row.", {})

    window = timedelta(hours=tolerance_hours)
    candidates = []
    for p in published:
        when = parse_local(p.get("posted_at"), assume_utc=assume_utc)
        if when is not None and abs(when - due) <= window:
            candidates.append((abs(when - due), when, p))

    if not candidates:
        return ("not_published",
                f"nothing published on this surface within {tolerance_hours}h of "
                f"{due:%Y-%m-%d %H:%M}. The post left the scheduled set without "
                "publishing -- deleted in the planner, or it failed. Analytics can "
                "also lag; if this row only just vanished, re-run before acting.", {})

    if len(candidates) > 1:
        near = ", ".join(f"{w:%Y-%m-%d %H:%M}" for _, w, _ in sorted(candidates))
        return ("ambiguous_match",
                f"{len(candidates)} posts published on this surface within "
                f"{tolerance_hours}h of {due:%Y-%m-%d %H:%M} ({near}). Refusing to "
                "pick one: a wrong match writes another post's URL and caption onto "
                "this row, and nothing downstream could detect it. Match by hand, or "
                "narrow --tolerance-hours.", {})

    _, when, post = candidates[0]
    write = {"Post Status": "Posted",
             "Posted At": when.strftime("%Y-%m-%dT%H:%M:%S")}
    if post.get("url"):
        write["Live URL"] = post["url"]
    if post.get("text"):
        write["Posted Caption"] = post["text"]

    missing = []
    if not post.get("url"):
        missing.append("no permalink on this surface (Live URL stays blank)")
    if not post.get("text"):
        missing.append("no caption field on this surface (Posted Caption stays blank"
                       + (f"; title was {post['title']!r}" if post.get("title") else "") + ")")

    detail = f"published {when:%Y-%m-%d %H:%M}"
    if missing:
        detail += " -- " + "; ".join(missing)
    return "published_confirmed", detail, write


def reconcile(rows, published, tolerance_hours, assume_utc=True):
    results, counts = [], {}
    for row in rows:
        verdict, detail, write = reconcile_row(row, published, tolerance_hours, assume_utc)
        counts[verdict] = counts.get(verdict, 0) + 1
        entry = {"notion_page_url": row.get("url"),
                 "content_name": row.get("Content Name"),
                 "surface": row.get("Post To"),
                 "metricool_uuid": (row.get("Metricool UUID") or "").strip() or None,
                 "verdict": verdict, "detail": detail}
        if write:
            entry["write"] = write
        results.append(entry)

    matched = {r["write"]["Live URL"] for r in results
               if r.get("write", {}).get("Live URL")}
    return {
        "reconciled_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "rows_examined": len(rows),
        "published_posts_seen": len(published),
        "tolerance_hours": tolerance_hours,
        "counts": counts,
        "results": results,
        "unclaimed_published": [p.get("url") or p.get("posted_at") for p in published
                                if p.get("url") not in matched],
        "_unclaimed_comment": ("Published posts no vanished row claimed. Posted outside "
                               "this pipeline, or published before it existed. Reported, "
                               "never actioned -- this pipeline does not own posts it "
                               "did not create."),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=Path, required=True,
                    help="JSON list of log rows whose uuid vanished from the scheduled set")
    ap.add_argument("--analytics", type=Path, required=True,
                    help="getAnalyticsDataByMetrics response for this surface")
    ap.add_argument("--surface", required=True, help="exact Post To value")
    ap.add_argument("--registry", type=Path,
                    default=Path("platform-settings/social-destinations.json"))
    ap.add_argument("--tolerance-hours", type=int, default=DEFAULT_TOLERANCE_HOURS)
    ap.add_argument("--assume-local", action="store_true",
                    help="treat the compact analytics timestamp as local, not UTC. "
                         "Only once the timezone has actually been confirmed.")
    ap.add_argument("--print-metrics", action="store_true",
                    help="print the ordered metric ids to request, and exit")
    args = ap.parse_args()

    try:
        registry = json.loads(args.registry.read_text())
        entry, fields = surface_fields(registry, args.surface)

        if args.print_metrics:
            print(json.dumps({"network": entry["network"], "connector": entry["connector"],
                              "metrics": list(fields.values()), "roles": list(fields)}, indent=2))
            return 0

        rows = json.loads(args.rows.read_text())
        if isinstance(rows, dict) and "results" in rows:
            rows = rows["results"]
        if not isinstance(rows, list):
            raise BadInput("--rows must be a JSON list of log rows")

        raw = json.loads(args.analytics.read_text())
        published = unpack(raw.get("rows", raw) if isinstance(raw, dict) else raw, fields)
        report = reconcile(rows, published, args.tolerance_hours, not args.assume_local)
        report["surface"] = args.surface
    except (OSError, ValueError, BadInput) as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
