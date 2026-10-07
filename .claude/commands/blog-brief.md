---
description: Pick the top unclaimed Backlog topic (or a named TB id), have the session model write the brief from titan-facts.md and the catalogue, validate it with scripts/blog_plan.py --stage brief, and plan a Blog Posts row at Briefed. plan_only until deliberately flipped.
---

# /blog-brief [`TB-<n>`] [`--count 1|2`]

Turn a ranked topic into a brief and a Blog Posts row. The brief is the session
model's judgement file; the plan script validates it and plans the row. One topic per
brief, at most `policy.max_briefs_per_run` per run (the weekly routine's two).

```
[1] Notion snapshot: Topic Backlog + Blog Posts (MCP SQL, saved as JSON)    read only
[2] pick the topic: top of ingest/<date>/topic-scores.json not yet claimed
[3] the model writes ingest/<date>/blog-brief-TB-<n>.json  (blog-brief-1)
[4] scripts/blog_plan.py --stage brief -> plans/<date>/blog-plan-brief-TB-<n>.json
[5] POLICY approves create_blog_post (+ topic -> Briefed)                     (approval file)
[6] blog-actions-agent creates the row, body = the brief                      (actions log)
[7] PushNotification; commit; PR
```

Authoritative procedure. `contracts/blog-plan-schema.md` defines the plan, the
approval file and the `blog-brief-1` judgement shape; `platform-settings/content-engine.json`
every id, option string and rule; `platform-settings/titan-facts.md` the **only** source
of a Titan-specific number or claim; `methods/content-engine.md` the AEO structure and
the pillar rules.

## Before you start

1. **`write_mode`** in `platform-settings/content-engine.json`. While `plan_only`
   this command runs steps 1–4 and 7 and writes **no approval file and no Notion row**.
2. **Notion is reachable** through `mcp__Notion__*`.
3. **`titan-facts.md` has content for the cluster.** A `TODO` line there is an absent
   fact. The brief may still be written — it lists what is missing under
   `facts_missing` and the plan flags `titan_facts_missing` — but the draft stage will
   not invent it. If the topic is a pricing question and every price is `TODO`, say so
   in the report and prefer the next topic.
4. **Airtable is optional**: product names (and nothing else) may be read from the
   Master Flooring Catalogue through `mcp__Airtable__*` to name real products. No
   prices from Airtable — a cost is not a retail price.

## 1. Snapshot — read only

Same two queries as `/topic-harvest` step 1 (SQL in `scripts/blog_snapshot.py`):

```bash
python3 scripts/blog_snapshot.py --kind backlog --in ingest/<date>/topic-backlog-sql.json --out ingest/<date>/topic-backlog-snapshot.json
python3 scripts/blog_snapshot.py --kind posts   --in ingest/<date>/blog-posts-sql.json   --out ingest/<date>/blog-posts-snapshot.json
```

If today's `ingest/<date>/topic-scores.json` does not exist, run `/topic-rank` step 2
first (the ranker only, no plan): the brief takes the top row of that file.

## 2. Pick the topic

Walk `topic-scores.json` → `ranked` from the top and take the first row that is in
the backlog snapshot with `status == "Backlog"` and an empty `blog_post`. A named
`TB-<n>` overrides the ranking but still has to pass the same two checks. Record why
the row was chosen (its `effective`, and what above it was skipped and why) — that goes
in the report.

## 3. Write the brief — the model's judgement

Write `ingest/<date>/blog-brief-TB-<n>.json`, shape `blog-brief-1`
(`contracts/blog-plan-schema.md`, "Judgement files"). The discipline:

- **`core_question`** is the customer's question **as typed**, ending with `?`. It
  becomes the H1 and the Blog Title. Rephrase for clarity only if the backlog wording
  is not a question.
- **`keyword`** is the phrase the page targets — usually the question minus the
  function words, with the local token if the topic is local.
- **`cluster`** is a registry slug; take it from the backlog row's `Cluster` label.
  **`material`** uses the Blog Posts option strings. **`intent`** uses the backlog
  spelling (`Commercial`); the plan converts to the Blog Posts spelling.
- **`slug`**: lower-case, hyphens, ≤ `website.slug_max`, not in `reserved_slugs`,
  not already on a Blog Posts row. Flat — no `blog/` prefix.
- **`content_type`**: `Supporting Content` unless this topic *is* the material's
  pillar. **`pillar_slug`**: the pillar's slug when one is published; `null` is fine
  while `pillar_rules.required` is false (the plan flags `pillar_not_required_yet`).
- **`h2s`**: at least three, each a question ending with `?`, in the order the
  reader would ask them. One of them is the local layer (`[material] + Mississauga/GTA`).
- **`facts_used`**: the ids from `titan-facts.md` the draft will quote.
  **`facts_missing`**: what the post wants that the facts file does not hold. The
  draft stage treats `facts_missing` as "do not invent", never as "estimate".
- **`snippet_draft`**: the direct answer, 40–60 words, answering `core_question`
  outright in the first sentence.
- Never name a competitor as a source. Speers is a gap source, never a link.

## 4. Plan — read only

```bash
python3 scripts/blog_plan.py --stage brief --brief ingest/<date>/blog-brief-TB-<n>.json \
    --backlog ingest/<date>/topic-backlog-snapshot.json --posts ingest/<date>/blog-posts-snapshot.json
```

Output `plans/<date>/blog-plan-brief-TB-<n>.json` plus the brief rendered as
Markdown beside the JSON (`blog-brief-TB-<n>.md`, the new row's body). The plan holds
rather than plans when the brief fails a rule (`h2_not_question`, `slug_*`,
`cluster_unresolved`, `stale_status` for a topic no longer `Backlog`,
`possible_duplicate` for a topic that already has a post). A hold is fixed in the
brief and the stage re-run, never in the plan.

For a second brief in the same run, repeat steps 2–4 with the next topic; the plan
script is per topic and `policy.max_briefs_per_run` is the ceiling.

## 5. Policy — the approval file

**Under `write_mode: plan_only`, skip to step 7.**

Under `write`, re-run step 4 with `--write-approval` →
`plans/<date>/blog-approval-brief-TB-<n>.json`.

## 6. Act — `blog-actions-agent`

Action type `notion_create_blog_post`. The agent re-reads the topic and refuses if it
is no longer `Backlog` or already has a `Blog Post`; it creates the row with the
`fields` in the plan and the brief Markdown as the body, then sets the topic's
`Status` to `Briefed` (the action's `then` step). It never sets any Blog Posts status
but `Briefed` here.

## 7. Report — the ping, the commit

1. **PushNotification** — always — the topic, its score and why it was chosen, the
   slug, `facts_missing` if any, and whether a row was created.
2. **Commit** the run's files (SQL results, snapshots, scores, brief JSON + MD, plan,
   approval, actions-log) and open the run's PR with `python3 scripts/publish_run.py`.
   A `facts_missing` list goes in the PR body as the ask to Albert.

## Done means

- The brief exists, validated by the plan stage, and is committed.
- Under `plan_only`: **nothing was written to Notion**, and the report says so.
- No Titan fact in the brief comes from anywhere but `titan-facts.md`; no price from
  Airtable; no competitor link.

Report honestly. If a step did not run, say which.
