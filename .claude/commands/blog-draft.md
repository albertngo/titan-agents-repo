---
description: Draft one Blog Posts row per the AEO Blog Post Structure (one H1, 40-60-word direct answer, question H2s, local + trust layer, 3-5 FAQ), validate it with scripts/blog_plan.py --stage draft, and plan the append-only body write plus Status Review. plan_only until deliberately flipped.
---

# /blog-draft `BP-<n>`

Write the post for a row at `Briefed` (or `Drafting`), validate it against the AEO
structure, and plan the body append plus the move to `Review` — the one human gate.
The run **never** writes `Approved`, and from `Review` onward the body belongs to a
person.

```
[1] Notion snapshot: Blog Posts (MCP SQL) + fetch the row's page body (the brief)   read only
[2] the model writes ingest/<date>/blog-body-BP-<n>.md  (Markdown, the post)
[3] scripts/blog_plan.py --stage draft -> plans/<date>/blog-plan-draft-BP-<n>.json
[4] POLICY approves append_blog_body + update_blog_post (Status Review)            (approval file)
[5] blog-actions-agent appends the body under "## Draft <date>", sets Review       (actions log)
[6] PushNotification; commit; PR
```

Authoritative procedure. `contracts/blog-plan-schema.md` (plan, approval, body file
shape); `platform-settings/content-engine.json` → `aeo_structure` (every length and
count), `sources.blog_posts` (`body_policy`, `run_may_set_status`);
`platform-settings/titan-facts.md` (the only source of Titan numbers);
`methods/content-engine.md` → AEO structure.

## Before you start

1. **`write_mode`** in `platform-settings/content-engine.json`. While `plan_only`
   this command runs steps 1–3 and 6 and writes **no approval file and no Notion
   body**.
2. **Notion is reachable** through `mcp__Notion__*`.
3. **The row is at `Briefed` or `Drafting`.** `Review`, `Approved` and `Published`
   bodies are a person's: stop and say so (`body_is_a_persons`). `Idea` has no brief:
   run `/blog-brief` first.

## 1. Snapshot and brief — read only

Posts query from `scripts/blog_snapshot.py` → `ingest/<date>/blog-posts-sql.json`,
normalised to `ingest/<date>/blog-posts-snapshot.json`. Then `notion-fetch` the row's
page and save its body (the brief Markdown `/blog-brief` wrote, plus any notes a
person added) as `ingest/<date>/blog-row-BP-<n>-body.md`. If the brief JSON from the
same day exists under `ingest/`, pass it to the plan stage too — it carries the
keyword and slug.

## 2. Write the post — the model's draft

`ingest/<date>/blog-body-BP-<n>.md`, plain Markdown, exactly this shape (the plan
stage enforces it and `blog_render.py` lifts the H1, snippet and FAQ into frontmatter):

```
# <the core question, as typed, ending with ?>

<direct answer: ONE paragraph, 40–60 words, answering the question outright>

## <question H2>
…
## <question H2 — the local layer: material + Mississauga/GTA>
…
## FAQ
### <question?>
<answer>
### <question?>
<answer>
(3–5 items)

## Sources            (optional; ignored by the renderer)
```

Writing rules, in order of weight:

- **Facts.** Every Titan-specific number, policy or claim comes from
  `titan-facts.md` by id (`facts_used` in the brief). A fact the brief lists under
  `facts_missing` is **not written** — the sentence is left out, not approximated. A
  general industry fact may be stated in general terms without a number.
- **Structure.** One H1. The first paragraph is the snippet and stands alone. Every
  H2 is a question ending with `?`. One H2 is the local layer. 3–5 FAQ items, each a
  `###` question with a one-paragraph answer. Body ≥ `aeo_structure.min_body_words`.
- **Voice.** Friendly expert, Mississauga/GTA, second person, short paragraphs. The
  reader should be able to stop after the snippet and have the answer.
- **Links.** Internal links use the flat slug form `/<slug>/` only for posts that
  exist in the snapshot with a `Direct URL` or `Slug`. No external links to competitors;
  a manufacturer or a public authority is fine when it supports a claim.
- **No images, no embeds** (Phase 1 is text-only). No CTA markup — the site renders
  the CTA with the UTM triple itself.

## 3. Plan — read only

```bash
python3 scripts/blog_plan.py --stage draft --body ingest/<date>/blog-body-BP-<n>.md \
    --brief ingest/<date>/blog-brief-TB-<m>.json --posts ingest/<date>/blog-posts-snapshot.json --bp BP-<n>
```

Output `plans/<date>/blog-plan-draft-BP-<n>.json`: `append_blog_body` (the whole file,
under a `## Draft <date>` heading, expect Status ∈ {Briefed, Drafting}) and
`update_blog_post` (`Status: Review`, `Snippet`, `Slug`, `Primary Keyword`). A hold
(`snippet_length`, `h2_not_question`, `faq_count`, `body_too_short`, `slug_*`,
`stale_status`, `body_is_a_persons`) is fixed in the body file and the stage re-run.
Exit 3 means nothing was plannable; read the holds.

Then prove it renders:

```bash
python3 scripts/blog_render.py --row ingest/<date>/blog-row-BP-<n>.json --body ingest/<date>/blog-body-BP-<n>.md \
    --out ingest/<date>/blog-mdx/<slug>.mdx && python3 scripts/blog_render.py --check ingest/<date>/blog-mdx/<slug>.mdx
```

`--row` is the small JSON the docstring of `scripts/blog_render.py` describes,
assembled from the snapshot row and the brief. The rendered file is a preview only —
`/blog-publish` re-renders from the approved body.

## 4. Policy — the approval file

**Under `write_mode: plan_only`, skip to step 6.**

Under `write`, re-run step 3's plan command with `--write-approval` →
`plans/<date>/blog-approval-draft-BP-<n>.json`.

## 5. Act — `blog-actions-agent`

Action types `notion_append_blog_body` then `notion_update_blog_post`. The agent
re-reads `Status` before each write (append only while `Briefed`/`Drafting`; the
status write expects the same), appends — never replaces — and sets `Review`. It
cannot set `Approved`; that is Albert, in Notion, after reading.

## 6. Report — the ping, the commit

1. **PushNotification** — always — the row, the slug, word count, FAQ count, what
   `facts_missing` kept out of the post, and "waiting for your Approved" under `write`.
2. **Commit** the run's files (SQL result, snapshot, row body, post body, plan,
   approval, preview MDX, actions-log) and open the run's PR with
   `python3 scripts/publish_run.py`.

## Done means

- The body file passes the draft stage and `blog_render.py --check`, and is committed.
- Under `plan_only`: **nothing was written to Notion**; under `write`: the body was
  appended and the row reads `Review`, logged.
- No fact outside `titan-facts.md`; no `Approved` written by anything but a person.

Report honestly. If a step did not run, say which.
