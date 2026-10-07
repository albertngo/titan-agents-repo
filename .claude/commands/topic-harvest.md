---
description: Gather candidate topics (a seed file now; transcript questions, OpenSEO related / PAA / autocomplete / gap and GSC in Phase 2), normalise, map each to one cluster, dedupe against the Topic Backlog and the legacy posts, and plan Topic Backlog rows (transcript seeds at Proposed). plan_only until deliberately flipped.
---

# /topic-harvest `--mode seed|transcript` [`--seeds <file>`]

Turn raw questions into Topic Backlog rows. Same shape as `/style-tag`: pull → decide →
act, with a policy approval file, and under `write_mode: plan_only` the run stops at
the plan. The backlog is the standing supply the rest of the engine draws from; this
command is the only thing that adds to it.

```
[1] Notion snapshot: Topic Backlog + Blog Posts (MCP SQL, saved as JSON)   read only
[2] the raw file: ingest/<date>/topic-seeds.json (seed / transcript)      hand-written or mined
[3] scripts/topic_harvest.py   -> ingest/<date>/topic-candidates-<mode>.json
[4] scripts/topic_rank.py --candidates  (optional preview of where they would land)
[5] scripts/blog_plan.py --stage harvest -> plans/<date>/blog-plan-harvest-<mode>.json
[6] POLICY approves create_topic; held rows have no id                      (approval file)
[7] blog-actions-agent creates the rows                                      (actions log)
[8] PushNotification; commit; PR
```

`--mode` is the `source` the rows carry (`Source of idea`). Phase 1 supports `seed`
(questions Albert or the session wrote down) and `transcript` (questions mined from
call transcripts, which **land at `Proposed`** and wait for a person). The OpenSEO and
GSC modes are Phase 2: their adapters will write the same `topic-raw-1` file, and
nothing below changes.

Authoritative procedure. `contracts/blog-plan-schema.md` defines the plan, the
approval file and the policy; `platform-settings/content-engine.json` every id,
property name, cluster rule, local token, threshold and cap; `methods/content-engine.md`
the meaning of the score and the clusters. Nothing below restates a value that lives in
one of those.

## Before you start

Check in order and **stop on the first failure**:

1. **`write_mode`** in `platform-settings/content-engine.json`. While it is `plan_only`
   this command runs steps 1–5 and 8 and writes **no approval file and no Notion row**.
   Do not raise it. Flipping it is a dated decision recorded in the vault.
2. **Notion is reachable** through `mcp__Notion__*` — `notion-fetch` on the registry's
   `sources.topic_backlog.database_id` returns the database with its properties.
3. **The mode is one the registry lists** under `openseo.harvest_modes` and is built:
   `seed` or `transcript`. Any other mode stops here — Phase 2 builds it.
4. **Budget (Phase 2 modes only).** An OpenSEO mode never starts a harvest when the
   registry's `openseo.budget` month counter plus `estimated_usd_per_harvest` would pass
   `usd_per_month`. Phase 1 modes cost nothing and skip this check.

## 1. Snapshot — read only

Run both queries with `mcp__Notion__notion-query-data-sources` and save each tool
result's `results` array (or the whole response) as JSON. Copy the SQL from the
docstring of `scripts/blog_snapshot.py`, substituting the registry's data-source ids:

```sql
-- backlog -> ingest/<date>/topic-backlog-sql.json
SELECT url, "userDefined:ID", "Topic / Question", "Cluster", "Material", "Source of idea",
       "Volume", "Difficulty", "CPC", "Intent", "Local", "Score", "Status", "Canonical key", "Blog Post"
FROM "collection://<sources.topic_backlog.data_source>"
-- posts -> ingest/<date>/blog-posts-sql.json
SELECT url, "userDefined:ID", "Blog Title", "Status", "Slug", "Topic Cluster", "Material",
       "Content Type", "Search Intent", "Primary Keyword", "date:Publish Date:start", "Direct URL",
       "Pillar", "PR URL", "Video URL", "Snippet"
FROM "collection://<sources.blog_posts.data_source>"
```

Then normalise:

```bash
python3 scripts/blog_snapshot.py --kind backlog --in ingest/<date>/topic-backlog-sql.json --out ingest/<date>/topic-backlog-snapshot.json
python3 scripts/blog_snapshot.py --kind posts   --in ingest/<date>/blog-posts-sql.json   --out ingest/<date>/blog-posts-snapshot.json
```

A large result lands in a file — copy that file; never retype rows. Take **every**
column listed: the dedupe runs on `Canonical key` and on every post title, and a
narrowed snapshot turns "new topic" into "duplicate row".

## 2. The raw file

`ingest/<date>/topic-seeds.json`, shape `topic-seeds-1` (the docstring of
`scripts/topic_harvest.py` is the reference):

```json
{"contract_version": "topic-seeds-1", "source": "seed",
 "seeds": [{"question": "How much does vinyl plank flooring cost to install in Mississauga?",
            "material": ["Vinyl"], "volume": 320, "difficulty": 22}]}
```

- `question` is the customer's question as they would type it. Keep it a question.
- `material` is optional and uses the Blog Posts option strings. `cluster` is optional
  and is a registry slug; leave it out and the cluster rules decide. `volume`,
  `difficulty` and `cpc` are optional — absent means unknown, which the ranker treats
  as a weak prior and flags `volume_unknown`, never as zero.
- **Transcript mode** (`"source": "transcript"`): questions only, in the customer's
  words, generalised — **no names, addresses, phone numbers, quotes or project
  details**. `scripts/ghl_calls_pull.py` summaries under `analysis/cache/ghl-calls/`
  are the input; the question is the output. A seed that would identify a person is
  left out, not scrubbed. These rows land at `Proposed` and a person flips them.

## 3. Harvest — read only

```bash
python3 scripts/topic_harvest.py --mode <mode> --seeds ingest/<date>/topic-seeds.json \
    --backlog ingest/<date>/topic-backlog-snapshot.json \
    --posts   ingest/<date>/blog-posts-snapshot.json \
    --out     ingest/<date>/topic-candidates-<mode>.json
```

Read the printed summary: candidates, held by reason, flagged. A `cluster_unresolved`
hold means no registry rule matched — the fix is a `cluster_rules` edit in a separate
change, or a `cluster` on the seed, never a hand edit of the candidates file. A
`possible_duplicate` / `possible_overlap` hold is the dedupe doing its job; if it is
wrong, the Jaccard thresholds in `scoring` are the dial.

Optional preview of where the new rows would rank:

```bash
python3 scripts/topic_rank.py --backlog ingest/<date>/topic-backlog-snapshot.json \
    --posts ingest/<date>/blog-posts-snapshot.json --candidates ingest/<date>/topic-candidates-<mode>.json \
    --out ingest/<date>/topic-scores-preview.json
```

## 4. Plan — read only

```bash
python3 scripts/blog_plan.py --stage harvest --candidates ingest/<date>/topic-candidates-<mode>.json
```

Output `plans/<date>/blog-plan-harvest-<mode>.json`: one `create_topic` action per
candidate (Status `Backlog`, or `Proposed` for transcript seeds), the harvester's
holds carried across, and anything beyond `policy.max_new_topics_per_run` held
`run_cap` for the next run. Read `summary`, then every `held` row.

Everything the policy decides is in the script and the registry; there is nothing for
you to approve or hold by judgement here.

## 5. Policy — the approval file

**Under `write_mode: plan_only`, skip to step 7.** No approval file exists, nothing
executes, and the report says so.

Under `write_mode: write`, re-run step 4 with `--write-approval`. It writes
`plans/<date>/blog-approval-harvest-<mode>.json` naming every `actions[].id` as
`approved` by the registry's `policy.approved_by` string. Held rows have no id and
cannot be approved by anyone.

## 6. Act — `blog-actions-agent`

Hand the plan and the approval file to **`blog-actions-agent`**, action type
`notion_create_topic`. Its rules are in its own file; the ones that matter here:

- It **searches `Canonical key` before every create** and skips a key that now exists.
- Batches of at most `policy.max_batch`; one actions-log entry per row.
- It never writes `Backlog` on a transcript seed — that flip is a person's.

## 7. Report — the ping, the commit

1. **PushNotification** — always — naming the mode, rows planned (and created, under
   `write`), held by reason, and how many transcript seeds wait at `Proposed`.
2. **Commit** the run's files (SQL results, snapshots, seeds, candidates, preview,
   plan, approval, actions-log) and open the run's PR with
   `python3 scripts/publish_run.py`. A hold that points at a missing cluster rule goes
   in the PR body as a proposed registry change.

## Done means

- Steps 1–4 ran and their files are committed; the plan's `summary` is in the report.
- Under `plan_only`: **nothing was written to Notion**, and the report says so plainly.
  Under `write`: every approved action executed or explicitly logged as failed.
- No transcript seed carries PII; none was created at any status but `Proposed`.
- Every hold is named with its reason; none was cleared by hand.

Report honestly. If a step did not run, say which. Never mark a stage complete that
isn't.
