---
description: Run all ingest subagents in parallel, then synthesize the daily brief.
---

Run the daily ingest funnel for Titan Flooring.

## Steps

1. Compute today's date `YYYY-MM-DD` in America/Toronto. Create `/ingest/<date>/` if missing.
2. Spawn these subagents IN PARALLEL using the Task tool, one task each:
   - `ghl-ingest-agent`
   - `outlook-ingest-agent`
   - `bookkeeper-ingest-agent`
   - `notion-ingest-agent`
   Do not do their work yourself. Do not let one failure stop the others.
3. When all tasks return, read every `*.json` in `/ingest/<date>/`.
4. Write `/ingest/<date>/DAILY-BRIEF.md` with exactly these sections:

   ## Daily Brief — <date>
   **Needs attention today** — merged `needs_attention` from all sources,
   deduped, ordered by priority. Max 7 bullets. This section comes first, always.
   **Numbers** — one line per source from `metrics` (e.g. GHL: 3 new leads, 2 unanswered).
   **By source** — 2–4 sentence digest per source from its items. High-priority items named explicitly with links.
   **Sources missing today** — any expected source whose file is absent or status != ok, with the error. If none, write "All sources reported."

5. Reply in chat with the "Needs attention today" section verbatim, then the file path.

6. **Vault handoff.** Spawn `vault-writer-agent` (per its own instructions — read
   the brief, the day's `*.json`, and `actions-log.json` if present; write only
   within its whitelist; propose-and-stop on anything else). A vault failure
   (missing repo, git error) must not roll back or edit `DAILY-BRIEF.md` — it is
   already written and final.

7. **Notion handoff.** Run `.claude/commands/notion-sync.md` against today's date.
   Team-destination writes happen automatically; private-destination candidates
   are proposed in chat and only written on explicit approval. A Notion failure
   must not affect `DAILY-BRIEF.md` or block step 6.

8. Reply with a one-line summary of steps 6–7 (vault: notes created/updated/declined;
   Notion: created/updated/skipped/failed counts, plus any private candidates still
   awaiting approval).

## Rules

- Terse. No filler. The brief must be readable in under 60 seconds.
- Never invent data for a missing source.
- If ALL sources errored, still write the brief — it becomes an outage report.
- Steps 6 and 7 run after the brief is fully written and are independent of each
  other and of it — a failure in either must never touch `DAILY-BRIEF.md`, and a
  failure in one must never block the other.
