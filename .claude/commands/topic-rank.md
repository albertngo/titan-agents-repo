---
description: Snapshot the Topic Backlog and Blog Posts, run scripts/topic_rank.py (deterministic v1 score with the cluster diversity factor), and plan Score / Score inputs / Last scored updates on Backlog rows. plan_only until deliberately flipped.
---

# /topic-rank

Re-score every `Backlog` row so `/blog-brief` can take the top one. The number is
explainable: every term lands in `Score inputs`, and the formula is pinned by
`tests/test_topic_rank.py` to the two worked examples Albert accepted. Weights, priors
and the cluster-performance values are **registry data** — a run reads them and never
changes them.

```
[1] Notion snapshot: Topic Backlog + Blog Posts (MCP SQL, saved as JSON)   read only
[2] scripts/topic_rank.py       -> ingest/<date>/topic-scores.json
[3] scripts/blog_plan.py --stage rank -> plans/<date>/blog-plan-rank-all.json
[4] POLICY approves update_topic_score (CAS Status == Backlog)              (approval file)
[5] blog-actions-agent writes Score, Score inputs, Last scored              (actions log)
[6] PushNotification; commit; PR
```

Authoritative procedure. `contracts/blog-plan-schema.md` defines the plan and the
approval file; `platform-settings/content-engine.json` → `scoring`, `clusters`,
`cluster_performance` every number; `methods/content-engine.md` → Scoring what each
term means. Nothing below restates a value that lives in one of those.

## Before you start

1. **`write_mode`** in `platform-settings/content-engine.json`. While `plan_only`
   this command runs steps 1–3 and 6 and writes **no approval file and no Notion row**.
2. **Notion is reachable** through `mcp__Notion__*`.
3. **`cluster_performance`** is whatever the registry holds. If `/content-attribution`
   proposed new values that are not yet in the registry, this run does **not** use
   them — a dated decision and a registry change apply them first.

## 1. Snapshot — read only

Same two queries as `/topic-harvest` step 1 (SQL in the docstring of
`scripts/blog_snapshot.py`), saved and normalised:

```bash
python3 scripts/blog_snapshot.py --kind backlog --in ingest/<date>/topic-backlog-sql.json --out ingest/<date>/topic-backlog-snapshot.json
python3 scripts/blog_snapshot.py --kind posts   --in ingest/<date>/blog-posts-sql.json   --out ingest/<date>/blog-posts-snapshot.json
```

The posts snapshot is load-bearing: the diversity factor counts what is published and
in flight per cluster, so a narrowed posts query inflates every uncovered cluster.

## 2. Rank — read only

```bash
python3 scripts/topic_rank.py --backlog ingest/<date>/topic-backlog-snapshot.json \
    --posts ingest/<date>/blog-posts-snapshot.json --out ingest/<date>/topic-scores.json
```

Only `Status = Backlog` rows are scored; a `Briefed` or `Drafting` topic never moves.
Read the printed top ten and the `skipped` list (`cluster_unresolved` means a row's
`Cluster` is blank or not a registry label — fix the row in Notion, not the file).

Sanity checks before planning, because a wrong score is quietly expensive:

- `volume_unknown` flags are expected on seeds without a volume source; they are a
  weak prior (`scoring.volume_unknown`), not zero.
- A cluster with nothing published should sit at `diversity` 1.15; one with three in
  flight at 0.7. If every row shows 1.0, the posts snapshot is probably empty.

## 3. Plan — read only

```bash
python3 scripts/blog_plan.py --stage rank --scores ingest/<date>/topic-scores.json \
    --backlog ingest/<date>/topic-backlog-snapshot.json
```

Output `plans/<date>/blog-plan-rank-all.json`: one `update_topic_score` action per
scored backlog row (`Score`, `Score inputs`, `Last scored`), each with
`expect: {Status: Backlog}` so a topic briefed between snapshot and write is skipped,
not overwritten. Candidates without a url are never planned here — `/topic-harvest`
creates them first.

## 4. Policy — the approval file

**Under `write_mode: plan_only`, skip to step 6.**

Under `write`, re-run step 3 with `--write-approval` →
`plans/<date>/blog-approval-rank-all.json`.

## 5. Act — `blog-actions-agent`

Action type `notion_update_topic_score`. The agent re-reads `Status` before each write
and drops a row that is no longer `Backlog`. One actions-log entry per row; batches of
at most `policy.max_batch`.

## 6. Report — the ping, the commit

1. **PushNotification** — always — the top five by `effective` with their cluster, the
   count scored, the count skipped and why, and whether anything was written.
2. **Commit** the run's files (SQL results, snapshots, scores, plan, approval,
   actions-log) and open the run's PR with `python3 scripts/publish_run.py`.

## Done means

- Steps 1–3 ran and their files are committed; the top of the ranking is in the report.
- Under `plan_only`: **nothing was written to Notion**, and the report says so.
- No weight, prior or performance value was changed by this run.

Report honestly. If a step did not run, say which.
