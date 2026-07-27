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

## Rules

- Terse. No filler. The brief must be readable in under 60 seconds.
- Never invent data for a missing source.
- If ALL sources errored, still write the brief — it becomes an outage report.
