# Content engine — method

> **STATUS (2026-10-07): Phase 0 built.** Notion schema and registry exist; every command is a
> stub that stops; `write_mode` is `plan_only`; no script exists yet. Phase 1 builds the first
> end-to-end slice. Plan of record: `methods/content-engine-plan.md` (grilled with Albert
> 2026-10-07, 24 decisions). Registry: `platform-settings/content-engine.json`.

## Why

Titan's blog is 106 WordPress posts written to a 2024 topical map, with no keyword on any
row, no link structure, and no way to tell which topic ever produced a sale. Albert wants
a loop that (1) keeps a large, scored backlog of real questions, (2) turns the best one
into an AEO-structured post with one human gate, (3) publishes it on the Next.js site he
is building, and (4) learns from won deals which topic clusters deserve more posts.
Video is repurposed from the blog afterwards, never the other way round.

Albert's own design pages are canonical for structure and are quoted, not restated:
"AEO Blog Post Structure" (`3f1596a4-505f-81f3-9899-cb75edd0d9ce`) and "AEO Site
Architecture Blueprint" (`3f1596a4-505f-816f-8c0d-cc5a3c5951dd`).

## Decisions (Albert, grilled 2026-10-07)

| Q | Decision |
|---|---|
| 1 | Engine lives in titan-agents-repo; titan-website receives rendered posts; OpenSEO is a deployment. |
| 2 | Two axes: `Material` (pillar / site structure) and `Topic Cluster` (scoring + `utm_campaign`). |
| 3 | Publish to Next.js only; Phase 1 builds the flat-slug blog route. |
| 4 | The 106 legacy posts are in scope: import via the public WP REST API, slugs preserved, media into the repo. |
| 5 | Body is canonical in Notion until publish, then in the MDX file. |
| 6 | Topic Backlog is its own Notion database. |
| 7 | One content gate: `Review -> Approved` by a person; PR merge is the mechanical second gate. |
| 8 | Titan-only facts come from `platform-settings/titan-facts.md` plus catalogue product names. |
| 9 / 22 | Seeds mined from call transcripts and inquiries, question only, land at `Proposed`; a person confirms. |
| 10 / 17 | OpenSEO hosted (openseo.so) first; self-host later = Cloudflare Workers + Supabase Postgres. |
| 11 | 2 posts/week; harvest + rank weekly; sweep daily; attribution monthly. |
| 12 | UTM path: site CTAs -> GHL contact `UTM_*` fields -> Make 3710214 -> Titan Projects `Campaign`. |
| 13 | Scoring v1 defaults accepted. |
| 14 | Flat root slugs with trailing slash; Vercel production URL counts as live until DNS cut-over. |
| 15 | Blog Posts gets `ID` (BP); `Posted` renamed `Published`; Briefed / Review / Approved added. |
| 16 | Video embed: YouTube only. |
| 18 | Attribution basis: `Value Approx` share, trailing 12 months, plus GHL lead counts incl. never-closed. |
| 19 | The weekly routine drafts two posts into Review; it never opens a PR. |
| 21 | Gap domains: The Floor Box, Word of Mouth Floors, Speers, plus national publishers. |
| 23 | Phase 1 posts are text-only. |
| 24 | DataForSEO: $1 per harvest, $20 per month, hard caps in the registry. |

Also 2026-10-07, Albert: "run grilling when planning" — any re-plan of this engine is
grilled first (CLAUDE.md, Planning).

## The loop

```
seeds + OpenSEO + GSC -> /topic-harvest -> Topic Backlog (Proposed -> Backlog)
                         /topic-rank    -> Score (deterministic)
weekly                   /blog-brief + /blog-draft -> Blog Posts row, Status Review
                         [person: Review -> Approved]
                         /blog-publish  -> MDX -> PR on titan-website
                         [person: merge]
daily                    /blog-sweep    -> Direct URL, Published; YouTube embed
monthly                  /content-attribution -> per-cluster report -> proposed cluster_performance
                         [person: dated decision -> registry]
```

Every write goes through `blog-actions-agent` under an approval file. Scripts are pure
and never reach a platform.

## State machine

Topic Backlog `Status`: `Proposed` (mined, awaiting a person) -> `Backlog` (scored) ->
`Briefed` (a Blog Posts row exists) -> `Drafting` -> `Published` -> or `Retired`
(`covered` / `duplicate` by policy; `out_of_scope` / `no_volume` by a person).

Blog Posts `Status`: `Idea` -> `Briefed` -> `Drafting` -> `Review` -> **`Approved`
(person only)** -> `Published`. The run may set every value except `Approved`. The body
is append-only while Briefed / Drafting and a person's from Review onward.

## Scoring (what the numbers mean)

Weights live in the registry; the meaning lives here.

- **Volume** (0.30): log-scaled against a 5,000/month cap, so 300 searches is worth
  about two thirds of 5,000. Unknown volume is 0.25 and flagged, never treated as zero.
- **Difficulty** (0.20): inverted keyword difficulty. Unknown is 0.5.
- **Local** (0.15): the cluster's local prior plus 0.5 when the query itself names
  Mississauga / GTA / Ontario / "near me". Local-first is the whole strategy.
- **Cluster** (0.25): the cluster's commercial prior, blended with measured conversion
  performance on a ramp that reaches 60% weight at 20 attributed wins. Performance is
  won-value share divided by published-post share, halved and clipped to [0, 1], so 0.5
  means "fair share" and 1.0 means "twice its share".
- **Intent** (0.10): Transaction 1.0, Commercial 0.8, Informational 0.5.
- **Diversity**: +15% for a cluster with nothing published; −10% per post already in
  flight in that cluster, floor 0.5. One cluster cannot monopolise the queue.

Only `Backlog` rows are scored. `Score inputs` stores every term so a number can be
explained a month later. Two worked examples are pinned by `tests/test_topic_rank.py`
(Phase 1): a 320/month local pricing question scores 95.9; a 2,400/month waterproof
question with three posts in flight scores 43.5.

## AEO structure (from Albert's page)

H1 is the question as typed. The 40–60-word direct answer comes first. Body H2s are
questions. A local + trust layer (Mississauga / GTA specifics, a real project, honest
ranges from `titan-facts.md`). A 3–5 question FAQ closes. Video embeds below the
snippet, never above. `blog_plan.py --stage draft` and `blog_render.py` enforce the
counts (registry `aeo_structure`).

## Pillar and spoke (from Albert's blueprint)

Flat URLs always; hierarchy lives in links, nav and the `Pillar` relation. Every spoke
has ONE primary pillar (`Pillar`), 3–6 sibling links, and two levels at most. The 106
legacy posts keep their URLs and join by links only. A pillar lists its `Spokes` from the
relation, so adding a spoke never edits the pillar.

## What it never does

- Writes `Approved`, merges a PR, deletes or archives a page, edits a Published body.
- Quotes a price that is not in `titan-facts.md`.
- Writes a transcript seed anywhere but `Proposed`, or carries a name, phone, address or
  project detail out of a transcript.
- Links to Speers from a post (gap-analysis source only).
- Spends past the DataForSEO caps; a harvest that would exceed them stops and reports.
- Changes `cluster_performance` or a weight from a run.

## Phases

0 schema + registry (done 2026-10-07) · 1 smallest slice · 1b legacy import · 2 OpenSEO ·
3 feedback loop · 4 video layer · 5 automation. Detail and verification per phase:
`methods/content-engine-plan.md`.

## Log

- 2026-10-07 — Phase 0. Topic Backlog created (db `1fb201bb-56d1-449f-9229-f9d0ec117bcf`,
  ds `collection://91bd484f-88b9-47d2-ba13-abcc5efd34a1`); Blog Posts gained ID (BP),
  Topic Cluster, Slug, Snippet, Video URL, PR URL, Topic, Content Idea, Pillar/Spokes;
  Titan Content Ideas gained Topic Cluster; Titan Projects gained Campaign. The Blog Posts
  `Status` rename (Posted -> Published) and the new options (Briefed, Review, Approved) are
  a Notion-UI task for Albert: a status option cannot be renamed through the DDL used here,
  and the engine reads `Posted` as `Published` until then.
