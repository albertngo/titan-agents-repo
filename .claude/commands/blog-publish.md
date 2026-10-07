---
description: For a Blog Posts row at Approved, render the body to MDX with scripts/blog_render.py and plan a pull request on titan-website (branch blog/<slug>); never merge (content engine, Phase 1 — NOT BUILT YET; stops immediately)
---

# /blog-publish

**Status: Phase 0 stub (2026-10-07).** This command is registered so the Marketing
department's `owns.commands` is complete, but it has no procedure yet. Phase 1 of
`methods/content-engine-plan.md` builds it.

## What it will do

For a Blog Posts row at Approved, render the body to MDX with scripts/blog_render.py and plan a pull request on titan-website (branch blog/<slug>); never merge.

## Until it is built

Stop here and say so. Do not improvise the procedure, do not call any platform, do not
write any file. `platform-settings/content-engine.json` → `write_mode.mode` is
`plan_only`, so even a built command would write no approval file, no Notion row and
no pull request.

Method: `methods/content-engine.md`. Registry: `platform-settings/content-engine.json`.
