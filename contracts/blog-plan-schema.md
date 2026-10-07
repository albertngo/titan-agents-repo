# Blog plan and approval contract (`blog-plan-1` / `blog-approval-1`)

The content engine's plan is the only path to a write. Every `/topic-*` and `/blog-*`
command ends in `scripts/blog_plan.py --stage <stage>`, which writes one plan per stage
and scope; policy (the same script, `--write-approval`) or a person writes the approval
file; `blog-actions-agent` executes **only** an id that appears `approved` there.

Modelled on `contracts/style-plan-schema.md`. Registry:
`platform-settings/content-engine.json`. Method: `methods/content-engine.md`.

## Files

| File | Written by | Holds |
|---|---|---|
| `plans/<date>/blog-plan-<stage>-<scope>.json` | `blog_plan.py` | the plan: actions, held, flagged |
| `plans/<date>/blog-approval-<stage>-<scope>.json` | `blog_plan.py --write-approval` (policy) or a person | which ids may execute |
| `ingest/<date>/topic-backlog-snapshot.json` | the command, from a Notion SQL read | `topic-backlog-snapshot-1` |
| `ingest/<date>/blog-posts-snapshot.json` | the command, from a Notion SQL read | `blog-posts-snapshot-1` |
| `ingest/<date>/topic-seeds*.json` | a person, or `/topic-harvest --mode transcript` | `topic-seeds-1` |
| `ingest/<date>/topic-candidates-<mode>.json` | `scripts/topic_harvest.py` | `topic-candidates-1` |
| `ingest/<date>/topic-scores.json` | `scripts/topic_rank.py` | `topic-scores-1` |
| `ingest/<date>/blog-brief-<TB>.json` | the session model (`/blog-brief`) | `blog-brief-1` |
| `ingest/<date>/blog-body-<BP>.md` | the session model (`/blog-draft`) | the post, Markdown |
| `ingest/<date>/blog-mdx/<slug>.mdx` | `scripts/blog_render.py` | the file the PR carries (`contracts/blog-mdx-schema.md`) |

`<scope>` is the seed-file stem for `harvest`, `all` for `rank`, the Topic Backlog id
(`TB-12`) for `brief`, and the Blog Posts id (`BP-7`) for `draft` and `publish`.

**Plans expire at end of day.** A stale plan is re-derived, never re-approved.
**Absence of an approval file means nothing is approved.** Not "approve everything",
not "ask again later".

## Plan envelope

```json
{
  "contract_version": "blog-plan-1",
  "stage": "draft",
  "scope": "BP-7",
  "run_at": "2026-10-14T09:12:00-04:00",
  "write_mode": "plan_only",
  "registry_config_version": "1",
  "inputs": [{"file": "ingest/2026-10-14/blog-posts-snapshot.json"}, {"file": "ingest/2026-10-14/blog-body-BP-7.md", "sha1": "…"}],
  "summary": {"actions": 2, "held": 0, "held_by_reason": {}, "flagged": 1},
  "actions": [ … ],
  "held": [ … ],
  "flagged": [ … ],
  "warnings": []
}
```

`write_mode` is copied from the registry at plan time; the agent re-reads the registry at
execute time and stops if it differs.

## Actions

```json
{
  "id": "blg-9c2e41a7b0d3",
  "seq": 1,
  "target_system": "notion",
  "type": "notion_update_blog_post",
  "op": "update_blog_post",
  "target": {"page": "https://www.notion.so/…", "bp_id": "BP-7"},
  "fields": {"Status": "Review", "Snippet": "…", "Slug": "is-laminate-flooring-waterproof"},
  "expect": {"Status": "Drafting"},
  "flags": []
}
```

- `id` = `blg-` + sha1[:12] over `target_system | op | target key | sorted field names |
  sha1 of any body or file content`. Stable across re-runs of the same input; a different
  draft is a different id.
- `target_system` ∈ `notion | github`. `type` is the actions-log type; `op` is the short
  verb (`create_topic`, `update_topic_score`, `retire_topic`, `create_blog_post`,
  `update_blog_post`, `append_blog_body`, `open_post_pr`, `update_post_pr`,
  `create_tracking_row`, `update_idea_cluster`).
- `expect` is a compare-and-swap: the agent re-reads the row and refuses with
  `stale_status` when the live value differs.
- `github` actions carry `files: [{path, sha1, source}]`, `branch`, `base`, `pr: {title,
  body_file}` and `then: [...]` (the Notion `PR URL` write-back).

## Held

```json
{"title": "…", "reason": "possible_duplicate", "detail": "Jaccard 0.86 with TB-41 'is lvp waterproof'"}
```

A held entry carries **no id** and cannot be approved. `reason` is one of the registry's
`held_reasons`. `flagged[]` entries name an `action_id` and a `flagged_reasons` value;
they execute and are reported.

## Approval file (`blog-approval-1`)

```json
{
  "contract_version": "blog-approval-1",
  "stage": "draft",
  "scope": "BP-7",
  "plan": "plans/2026-10-14/blog-plan-draft-BP-7.json",
  "approved_by": "policy: content-engine auto-approval (v1)",
  "decisions": [{"id": "blg-9c2e41a7b0d3", "status": "approved", "at": "2026-10-14T09:12:30-04:00"}]
}
```

Written by `blog_plan.py --write-approval` only while the registry's `write_mode.mode`
is `write` (exit 4 otherwise), and only for ops in `policy.auto_approve_ops`. A person's
approval file carries the person's name in `approved_by`.

## Policy auto-approval (v1, Albert 2026-10-07)

An action is **approved by policy** only if all of the following hold:

1. `write_mode.mode` is `write`.
2. Its `op` (with the retire reason, e.g. `retire_topic:covered`) is in
   `policy.auto_approve_ops`.
3. The plan's `held[]` does not name the same target.
4. For `open_post_pr` / `update_post_pr`: the posts snapshot showed `Status == Approved`,
   and the agent re-checks it at write time.
5. For `create_topic`: the batch is within `policy.max_batch` and the run within
   `policy.max_new_topics_per_run`.

Never approved by policy, under any instruction: `retire_topic:out_of_scope`,
`retire_topic:no_volume`, any write of `Status = Approved`, `Proposed -> Backlog`, a PR
merge, a `cluster_performance` or weight edit, a `write_mode` flip.

## Stage inputs and what each stage validates

| Stage | Input | Validates | Plans |
|---|---|---|---|
| `harvest` | `topic-candidates-1` | cluster resolves; no duplicate / overlap; caps | `create_topic` per candidate |
| `rank` | `topic-scores-1` + backlog snapshot | only `Backlog` rows; score in [0, 100] | `update_topic_score` with `expect.Status = Backlog` |
| `brief` | `blog-brief-1` + backlog snapshot | keyword, core question, ≥3 question H2s, cluster valid, topic has no Blog Post yet, slug valid and unreserved | `create_blog_post` (Status Briefed) + topic `Briefed` |
| `draft` | `blog-body-<BP>.md` + posts snapshot + brief | one H1; snippet paragraph 40–60 words; every H2 ends with `?`; `## FAQ` with 3–5 Q&A; ≥ `min_body_words`; row Status ∈ {Briefed, Drafting} | `append_blog_body` + `update_blog_post` (Status Review, Snippet, Slug) |
| `publish` | posts snapshot + rendered MDX | row Status == Approved; `blog_render.py --check` passes; sha1 recorded | `open_post_pr` (+ `PR URL` write-back) |

## Judgement files

`blog-brief-1`:

```json
{"contract_version": "blog-brief-1", "topic": {"url": "…", "id": "TB-12", "title": "…"},
 "keyword": "vinyl plank flooring cost mississauga", "core_question": "How much does vinyl plank flooring cost in Mississauga?",
 "cluster": "installation-cost", "material": ["Vinyl"], "intent": "Transaction",
 "slug": "vinyl-plank-flooring-cost-mississauga", "content_type": "Supporting Content", "pillar_slug": null,
 "angle": "friendly expert, local; buying intent",
 "h2s": ["What affects the price?", "Is installation included?", "How does it compare to laminate?"],
 "facts_used": ["pricing.lvp.mid"], "facts_missing": ["installation.click_lock"],
 "snippet_draft": "…40–60 words…"}
```

The body file is plain Markdown: `# <H1 question>`, the snippet paragraph, `## <question>`
sections, a `## FAQ` section whose items are `### <question>` + answer paragraphs, and
optionally `## Sources` (ignored by the renderer). Nothing else.
