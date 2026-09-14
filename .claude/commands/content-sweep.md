---
description: Reconcile Content Calendar Log rows against Metricool's scheduled set. Marks what published, flags what vanished. Read-mostly; writes only Post Status.
---

# /content-sweep

Answers one question for every `Scheduled` row: **is that post still coming, did it go
out, or did something happen to it?**

Nothing else in this pipeline can answer it. `getScheduledPosts` returns only posts
that have **not** published, so a post disappears from the one endpoint we query at the
exact moment it succeeds. Without this sweep a row sits at `Scheduled` forever, and the
Notion calendar quietly stops describing reality about a week after go-live.

Run it daily. It is cheap: one Notion query, one Metricool read, no writes unless
something actually changed.

Authoritative procedure. The decision logic is
`scripts/social_publish_sweep.py` — read its docstring before changing any rule here.

## What it must never do

**Absence is not proof of publication.** A uuid missing from the scheduled set has
three possible causes that look identical from here: it published, somebody deleted it
in the planner, or it sits outside the window we queried. Marking a deleted post
`Posted` records a post that never went out, and nothing downstream can catch that
later — the evidence is gone from both systems.

So `Posted` requires absence **and** a due time that has passed **and** a window wide
enough to have contained it **and** draft mode being off. The script enforces all four;
do not second-guess it row by row.

**While `write_mode.mode` is `draft`, nothing is ever marked `Posted`.** A draft does
not publish when its time arrives — that is what draft means — so a vanished draft was
deleted by a person. Pass `--write-mode` from the registry; never assume it.

## Steps

### 1 — Read the rows

Query the Calendar Log for `Post Status = Scheduled`:

```sql
SELECT url, "Content Name", "Post To", "Post Status",
       "Metricool UUID", "Metricool Post ID", "date:Post Date:start" AS "Post Date"
FROM "collection://38c596a4-505f-80b4-9b03-000bf7d7d77b"
WHERE "Post Status" = 'Scheduled'
```

Zero rows is a normal, healthy result. Say so and stop.

### 2 — Read the scheduled set

`getScheduledPosts` for brand `3951085`. **Make the window wider than the rows you are
judging** — from the earliest `Post Date` you found, minus a day, to the latest plus a
day. A row outside the window looks identical to a published one, and the script will
correctly refuse to judge it, but that is a wasted sweep. Pass the same range to
`--window` so any row that still falls outside is reported honestly rather than guessed.

### 3 — Reconcile

```
python3 scripts/social_publish_sweep.py \
    --rows rows.json --posts scheduled.json \
    --write-mode "<write_mode.mode from social-destinations.json>" \
    --window <from> <to>
```

The verdicts, and what each one means:

| Verdict | Meaning | Write |
|---|---|---|
| `still_scheduled` | Present, dates agree, not yet due. Healthy. | — |
| `date_drift` | Present, but Notion and Metricool disagree on the date. | — (carries a `proposed_action`; see 3b) |
| `published` | Absent, due time passed, live mode. **A candidate — confirm in 3a.** | `Posted`, after 3a |
| `vanished_in_draft_mode` | Absent while drafting. Cannot be a publish — somebody deleted it. | `Manual Required` |
| `vanished_before_due` | Absent but not yet due. Nothing publishes early. | `Manual Required` |
| `stuck_past_due` | Still scheduled hours after its slot. Metricool did not publish it. | `Failed` |
| `missing_uuid` | `Scheduled` with no uuid — a write died mid-run. **Re-running would double-post.** | `Manual Required` |
| `outside_window` / `vanished_no_date` | Not enough information to judge. | — |

### 3a — Confirm every candidate publication against analytics

**A `published` verdict from step 3 is a candidate, not a conclusion.** It rests on an
absence, and absence is ambiguous. Analytics is an independent second source that
turns it into an observation — and it is also where `Live URL` and `Posted Caption`
come from, because a published post is gone from `getScheduledPosts` entirely.

For each surface with candidates:

1. Get the ordered metric ids — never hardcode them:
   ```
   python3 scripts/social_publish_reconcile.py --surface 'Instagram Reels' \
       --rows /dev/null --analytics /dev/null --print-metrics
   ```
2. `getAnalyticsDataByMetrics` for brand `3951085` with exactly those metrics, in that
   order, over a window comfortably wider than the candidates' dates.
3. Pipe rows and response back through the script (without `--print-metrics`).

**The response is positional arrays with no field names**, so the request order and
the unpack order must both come from the registry's `analytics.surfaces.<surface>.fields`.
Reorder one without the other and columns transpose silently: a caption lands in
`Live URL`, well-formed, erroring nowhere.

Verdicts: `published_confirmed` (write `Posted`, `Posted At`, and whichever of
`Live URL` / `Posted Caption` that surface exposes), `not_published` (it left the
scheduled set without publishing — deleted or failed; **analytics also lags**, so
re-run before acting on a row that only just vanished), `ambiguous_match` (two posts
in the window — refused, because a wrong match writes another post's URL and caption
onto this row undetectably).

Two surfaces are permanently partial, and this is a platform limit, not a gap to fill:
**YouTube** exposes a title, not a description, so `Posted Caption` stays blank — a
title is never written there as if it were a caption. **Google Business Profile**
exposes no per-post permalink, so `Live URL` stays blank.

### 3b — Drift proposes a reschedule, it does not perform one

A `date_drift` row now carries a `proposed_action`. Notion owns `Post Date`, so the
fix is mechanical — but it is a platform write, so it goes through the normal plan,
approval file and actions log as a `social_reschedule_post`, exactly like a manual
reschedule. The sweep itself still writes nothing for drift.

The sweep withholds the proposal, and says so, when Notion's date is in the **past**
(a stale row is not an instruction to move a post backwards) or when either side
fires within `--imminent-hours` (the post can publish while the update is in flight,
leaving the update applied to nothing and the row wrong).

`orphans` lists Metricool posts no row claims — posted from the planner by hand, or a
row deleted after scheduling. **Report them; never action them.** This pipeline does not
own posts it did not create.

### 4 — Write back

Only `Post Status`, only on the Calendar Log, only for verdicts carrying
`set_post_status`. Log each one to `ingest/<date>/actions-log.json` as
`notion_update_task` with the verdict in the entry.

`Live URL`, `Posted Caption` and `Posted At` come from step 3a, never from
`getScheduledPosts` — a published post is gone from it, and carries no permalink while
scheduled. Where a surface exposes no such field, leave it blank rather than
substituting something adjacent.

### 5 — Report

Counts by verdict, then every row that is not `still_scheduled`, with its reason.
Push a notification only if something needs a person: `missing_uuid`, `stuck_past_due`,
or any `vanished_*`. A clean sweep is silent.

## Done means

- Every `Scheduled` row has a verdict, including the ones left alone.
- No row was marked `Posted` on absence alone.
- Nothing was written to Titan Content Ideas, and no `Post Date` was edited.
- Orphans were reported, not touched.

## Not yet wired

Not part of `/daily-ingest` — adding a write to the orchestrator is Albert's call, and
`/daily-ingest` is deliberately stable. Run it by hand, or schedule it separately, until
that decision is made.

**Nothing has published through this pipeline yet**, so the confirmation path in step
3a has never run against a real publication. The metric ids are read from the live API
and the unpacking is pinned by a test against a verbatim response, but the MATCH itself
— a published post to the row that scheduled it — has only been exercised on fixtures.
Watch the first live one.

The join is also a heuristic, not a key: Metricool's planner uuid and the network's own
post id are different namespaces with nothing mapping between them, so a post is matched
to its row by surface and time-proximity. That is sound at a few posts a week and would
not be at thirty a day.
