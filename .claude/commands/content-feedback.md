---
description: Pull 7-day, 30-day and rolling post stats from Metricool onto the Content Calendar Log, rank hook patterns and caption formulas per platform, and update the Performance notes page the content skill reads.
---

# /content-feedback

Answers one question: **what is working, on each platform, by Titan's own numbers?**

Run it daily, right after `/content-sweep`. It's cheap because it only pulls rows that
are due, and most days nothing is. It isn't wired into `/daily-ingest` or a Routine.
Doing that adds a scheduled Notion write, which is Albert's call.

Authoritative procedure. The decision logic is `scripts/social_feedback.py`: read its
docstring before changing any rule here. Metric ids are data, in
`platform-settings/social-destinations.json` → `analytics.surfaces.<surface>.stats`.

## What it must never do

- **Never estimate a number.** Metricool returns null for "not available", and null stays
  blank. Four gaps are known and permanent: Instagram has no per-reel follows, TikTok
  has no saves, Facebook has no 3-second views (Views are **10-second** views there),
  and YouTube has no % viewed and no subscribers-per-video.
- **Never compare across platforms.** Every rate is judged against that platform's own
  Titan average, never another platform's and never an industry benchmark.
- **Never rewrite a frozen pull.** Day-7 and day-30 columns are written once. Only the
  `… Latest` columns are overwritten.
- **Never match on `Metricool Post ID`.** The planner id and the network's post id never map
  to each other. Match on `Live URL`, and on the time slot only when there is no URL.

## The pull schedule

| Pull | When | Writes | Used for |
|---|---|---|---|
| `day7` | first run on or after day 7 | `Views` `Reach` `Likes` `Comments` `Saves` `Shares` `Avg Watch Time (s)` `Completion %` `Caption Edited` `Stats Pulled At`, `Tracking = Active` | every ranking |
| `day30` | first run on or after day 30 | `Views 30d` `Saves 30d` `Shares 30d` `Comments 30d` `30d Pulled At` | long-tail view |
| `rolling` | every 30 days from day 60 | `Views Latest` `Saves Latest` `Shares Latest` `Comments Latest` `Latest Pulled At`, `Tracking` | late-surge watch |

`Tracking`: **Late Surge** when `Views Latest` ≥ 2× `Views 30d`. **Quiet** after one rolling
pull that added under 5%. **Settled** after two in a row, and then it's never pulled again.
Nothing is pulled past 12 months. A first pull taken after day 10 is written, but it isn't
ranked alongside true day-7 pulls.

## Steps

### 1: Find what's due
Query Content Calendar Log (`collection://38c596a4-505f-80b4-9b03-000bf7d7d77b`) for
`Post Status = Posted`. Take `url`, `Content Name`, `Post To`, `Post Status`, `Posted At`,
`Live URL`, `Caption`, `Posted Caption`, `Content Series`, `Tracking`, `Views 30d`,
`Views Latest` and the three `… Pulled At` dates. Then:

    python3 scripts/social_feedback.py --mode due --rows log.json --now <local now>

Nothing due → skip to step 4 (the report still runs on what exists).

### 2: Pull
`getBrandSettings` confirms brand 3951085. For each surface in `by_surface`, request
exactly the ids in `stats` **in registry order** via `getAnalyticsDataByMetrics`, with a
date range spanning that surface's due posts' `Posted At` (the filter is by publication
date; ±1 day, in UTC, which the timestamp is). Save as `{surface: response}` and run:

    python3 scripts/social_feedback.py --mode match --rows due.json --analytics stats.json --now <local now>

`unmatched` rows are reported, never written. The detail says why: a Live URL missing from
the pull, or two posts in one slot. If a whole platform returns no rows at all, stop and
name it, so Albert can read the numbers from the native app.

### 3: Write
For each `matched` result, `notion-update-page` with exactly its `write` (numbers as
numbers, dates as `date:<col>:start`, `Caption Edited` as `__YES__`/`__NO__`). Then:
- **Caption Formula**, on day-7 rows only. Fetch the linked idea, find the `### <platform>`
  heading under `📝 CAPTIONS`, and copy the value after `Formula:` on its label line if it
  matches a `Caption Formula` option exactly. Otherwise leave it blank. Entries written
  before the skill (TC-86, TC-161/164/166/169/170) have no label, so it stays blank.
- **Hook**: if the idea's `Hook Used` is blank, set it to **A** (Albert, 2026-09-28: until
  the transcript step exists). Set `Hook Pattern` only from the idea's own hook table
  label. In skill-format entries Hook A reads `Hook A (AEO)`, so it becomes `AEO`. Older
  entries (TC-86, for one) label hooks with no pattern, and there `Hook Pattern` stays
  **blank**: a pattern is never inferred from the wording. Say in the report that
  hook-pattern ranking has at most one group (AEO) until real B/C data exists. When `Hook Used` is
  B or C, read that hook's label from the idea's hook table and map it to the option:
  Story opener → `Story`, Statistic / data → `Statistic`, List preview → `List`,
  Before / after → `Before/After`, Pick one → `Pick One`. Every other label is its own
  option name. Anything that doesn't map stays blank and gets named in the report.
- Log each row to `ingest/<date>/actions-log.json` as `notion_update_content_stats`.

### 4: Analyse
Re-query every row with `Views` set. Merge in from each linked idea `Hook Pattern`,
`Series`, `Content Type` and `CTA Goal` (the Big Idea box's **CTA goal:** line), plus the
row's `Caption Formula` and `Caption Edited`. Then:

    python3 scripts/social_feedback.py --mode analyse --rows ranked.json

Groups under 5 posts are `early_signal`, not conclusions. Rows with `Caption Edited` count
for everything except Caption Formula, because that result belongs to the edit.

### 5: Report (PARA, short)
- **Point**: top and bottom post per platform, and any **Late Surge** first, naming its hook,
  formula and series.
- **Action**: which hook patterns and caption formulas to use more or less, with the numbers.
  Mark every early signal as one.
- **Result**: what changes in the next batch.
- **Ask**: one question.

### 6: Performance notes
Rewrite the **Performance notes** page under Content Creation
(`131596a4505f80a2bdb7cbf3e2d6583b`), at the id in `content-sources.json` →
`content_calendar_log.performance_notes_page`. It was created 2026-09-28; never create a second one. It holds, per
platform, the current ranking of hook patterns and caption formulas, each with n and
early-signal or conclusion, the platform averages, and the date. This page is what
`titan-content-scripts` reads before writing new entries, so it holds rankings only, no prose.
