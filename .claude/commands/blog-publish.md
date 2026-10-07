---
description: For a Blog Posts row a person set to Approved, export the body, render it to MDX with scripts/blog_render.py, check it, and plan one pull request on titan-website (branch blog/<slug>, file content/blog/<slug>.mdx) plus the PR URL write-back. Never merges. plan_only until deliberately flipped.
---

# /blog-publish `BP-<n>`

Carry an approved post from Notion to the website as a pull request. The row's
`Status = Approved` is the content gate a person already passed; the PR merge is the
mechanical second gate and is Albert's. This command opens the PR and nothing more.

```
[1] Notion snapshot: Blog Posts (MCP SQL) + fetch the row's page body                read only
[2] ingest/<date>/blog-row-BP-<n>.json + ingest/<date>/blog-body-BP-<n>.md  (the approved body, verbatim)
[3] scripts/blog_render.py  -> ingest/<date>/blog-mdx/<slug>.mdx ; --check
[4] scripts/blog_plan.py --stage publish -> plans/<date>/blog-plan-publish-BP-<n>.json
[5] POLICY approves open_post_pr (expect Status Approved, re-read at write)           (approval file)
[6] blog-actions-agent: branch blog/<slug>, push the file, open the PR, write PR URL  (actions log)
[7] PushNotification; commit; PR (this repo's run PR, separate from the website PR)
```

Authoritative procedure. `contracts/blog-mdx-schema.md` (the file the PR carries);
`contracts/blog-plan-schema.md` (plan, approval); `platform-settings/content-engine.json`
→ `website` (repo, base branch, branch template, content dir, slug rules,
`never_merge`), `sources.blog_posts` (`person_only_status`).

## Before you start

1. **`write_mode`** in `platform-settings/content-engine.json`. While `plan_only`
   this command runs steps 1–4 and 7 and opens **no pull request and writes no Notion
   property**.
2. **Notion is reachable** through `mcp__Notion__*`.
3. **The row's `Status` is `Approved`** in the snapshot. Anything else stops here
   with `not_approved`; the command never nudges a row toward Approved.
4. **GitHub (under `write`).** The cloud path needs `albertngo/titan-website`
   attached with push access (`add_repo`) and `mcp__github__*` reachable; the Mac path
   uses `scripts/blog_publish_pr.py` with `GH_TOKEN` from `.env`. Neither can merge:
   the agent has no merge tool and `website.never_merge` is true.

## 1. Snapshot and body — read only

Posts query from `scripts/blog_snapshot.py` → `ingest/<date>/blog-posts-sql.json` →
`ingest/<date>/blog-posts-snapshot.json`. `notion-fetch` the row's page and save the
body as `ingest/<date>/blog-body-BP-<n>.md` — **the approved text, verbatim**. The
body is a person's from `Review` on: if it needs an edit, the edit happens in Notion
and this command re-runs. The latest `## Draft <date>` section is the post; strip the
heading line itself and any brief section above it, nothing else.

## 2. The row file

`ingest/<date>/blog-row-BP-<n>.json`, the shape in the docstring of
`scripts/blog_render.py`: `bp_id`, `page_id`, `title`, `slug`, `keyword`, `intent`
(the Blog Posts spelling), `cluster` (label or slug), `material`, `content_type`,
`pillar_slug`, `siblings` (slugs of posts in the same material that exist in the
snapshot), `video_url` (the row's `Video URL`, else null), `description` (≤160
characters; null lets the renderer trim the snippet), `publish_date` (null until the
sweep writes it). Every value comes from the snapshot row; nothing is invented.

## 3. Render and check — read only

```bash
python3 scripts/blog_render.py --row ingest/<date>/blog-row-BP-<n>.json --body ingest/<date>/blog-body-BP-<n>.md \
    --out ingest/<date>/blog-mdx/<slug>.mdx
python3 scripts/blog_render.py --check ingest/<date>/blog-mdx/<slug>.mdx
```

`--check` exit 1 lists the problems (snippet length, FAQ count, slug, description,
missing keys). A problem is fixed in Notion (the body) or in the row file (metadata),
never in the `.mdx` by hand — the sha1 of the rendered file is what the PR carries
and the sweep later compares.

## 4. Plan — read only

```bash
python3 scripts/blog_plan.py --stage publish --mdx ingest/<date>/blog-mdx/<slug>.mdx \
    --posts ingest/<date>/blog-posts-snapshot.json --bp BP-<n>
```

Output `plans/<date>/blog-plan-publish-BP-<n>.json`: one `open_post_pr` action
(repo, branch `blog/<slug>`, base, the file path and its sha1, the PR title and body,
`expect: {Status: Approved, re_read_at_write: true}`) with a `then` step that writes
`PR URL` on the row. Held `not_approved` / `stale_status` / render problems mean no
action; fix the cause and re-run.

## 5. Policy — the approval file

**Under `write_mode: plan_only`, skip to step 7.**

Under `write`, re-run step 4 with `--write-approval` →
`plans/<date>/blog-approval-publish-BP-<n>.json`.

## 6. Act — `blog-actions-agent`

Action type `website_open_post_pr` (or `website_update_post_pr` when an open PR for
the branch already exists — the agent lists PRs first and reuses it). It **re-reads
`Status` and refuses unless it is still `Approved`**, pushes the file whose sha1 matches
the plan, opens the PR against `website.base_branch`, then writes `PR URL` on the
Notion row. It never merges, never pushes to `main`, never touches another file.

## 7. Report — the ping, the commit

1. **PushNotification** — always — the row, the slug, the Vercel preview to look at
   under `write` (the PR URL), and "merge when happy — the sweep marks it Published".
2. **Commit** the run's files (SQL result, snapshot, row file, body, MDX, plan,
   approval, actions-log) and open **this repo's** run PR with
   `python3 scripts/publish_run.py`. Two PRs exist after a `write` run: the website's
   (the post) and this repo's (the audit trail). Name both.

## Done means

- The MDX renders and `--check` passes; the files are committed here.
- Under `plan_only`: **no pull request was opened and no Notion property written**,
  and the report says so. Under `write`: one PR on titan-website, `PR URL` on the row,
  one actions-log entry.
- Nothing was merged. The row's `Status` was not changed by this run.

Report honestly. If a step did not run, say which.
