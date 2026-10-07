---
description: Snapshot the Topic Backlog and Blog Posts, run scripts/topic_rank.py (deterministic v1 score), and plan Score / Score inputs / Last scored updates on Backlog rows (content engine, Phase 1 — NOT BUILT YET; stops immediately)
---

# /topic-rank

**Status: Phase 0 stub (2026-10-07).** This command is registered so the Marketing
department's `owns.commands` is complete, but it has no procedure yet. Phase 1 of
`methods/content-engine-plan.md` builds it.

## What it will do

Snapshot the Topic Backlog and Blog Posts, run scripts/topic_rank.py (deterministic v1 score), and plan Score / Score inputs / Last scored updates on Backlog rows.

## Until it is built

Stop here and say so. Do not improvise the procedure, do not call any platform, do not
write any file. `platform-settings/content-engine.json` → `write_mode.mode` is
`plan_only`, so even a built command would write no approval file, no Notion row and
no pull request.

Method: `methods/content-engine.md`. Registry: `platform-settings/content-engine.json`.
