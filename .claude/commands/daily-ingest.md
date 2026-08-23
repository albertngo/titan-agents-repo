---
description: Run all ingest subagents in parallel, then synthesize the daily brief.
---

Run the daily ingest funnel for Titan Flooring.

## Steps

1. Compute today's date `YYYY-MM-DD` in America/Toronto. Create `/ingest/<date>/` if missing.
   Read `/ingest/run-ledger.json` (create with `[]` if absent) and note any calendar
   days between the last entry's `date` and today that have no entry — these are
   **missed run days** and must surface in step 4.

   **Before claiming a day was missed, check whether it was merely stranded.** A run
   whose artifacts never reached `main-agents` looks identical to a run that never
   happened. Run `git ls-remote --heads origin`, then for any candidate branch
   `git ls-tree -d --name-only origin/<branch> -- ingest/` — if the day's folder exists
   on an unmerged branch, it ran. Recover it (`git checkout origin/<branch> -- ingest/<date>`)
   and ledger it as recovered rather than reporting a false gap. This is not
   hypothetical: 2026-08-15 through 2026-08-22 were all reported as "no run at all" for
   over a week while sitting complete on eight unmerged branches.

2. Spawn these subagents IN PARALLEL using the Task tool, one task each:
   - `ghl-ingest-agent`
   - `outlook-ingest-agent`
   - `bookkeeper-ingest-agent`
   - `notion-ingest-agent`
   - `meta-ads-ingest-agent`
   Do not do their work yourself. Do not let one failure stop the others.

3. When all tasks return, read every `*.json` in `/ingest/<date>/`.

4. Write `/ingest/<date>/DAILY-BRIEF.md` with exactly these sections:

   ## Daily Brief — <date>
   **Needs attention today** — merged `needs_attention` from all sources,
   deduped, ordered by priority. Max 7 bullets. This section comes first, always.
   **Numbers** — one line per source from `metrics` (e.g. GHL: 3 new leads, 2 unanswered).
   **By source** — 2–4 sentence digest per source from its items. High-priority items named explicitly with links.
   **Sources missing today** — any expected source whose file is absent or status != ok, with the error. If none, write "All sources reported." If step 1 found missed run days, add one line: `No run at all on: <dates>` — a skipped day is a finding, never silent.

   **Connector health.** Any source failing for an auth or approval reason — not a data
   reason — gets its own bullet in "Needs attention today", naming who fixes it and the
   consecutive-failure count. Connector auth is the system's dominant failure mode
   (QuickBooks: 16+ consecutive runs on an expired token, misreported as "not
   configured"; GHL: 3 runs lost to a `Pending approval` server state a non-interactive
   run cannot clear). A connector Albert must re-auth is a same-day ask, not a footnote
   in "Sources missing" — it never fixes itself and every silent day compounds.

5. **Run ledger.** Append one entry to `/ingest/run-ledger.json` (append-only, one
   entry per run; a same-day re-run appends another entry, latest wins):

   ```json
   {"date": "<date>", "run_at": "<ISO timestamp, America/Toronto>",
    "sources": {"ghl": "ok|partial|error|missing", "outlook": "...", "bookkeeper": "...", "notion": "...", "meta-ads": "..."},
    "brief": true}
   ```

   An optional `note` field may explain anomalies (catch-up run, backfill, outage,
   recovery from a stranded branch). `missing` means the source wrote no file at all.
   This step runs even if every source errored — the ledger records that the run
   happened; its absence for a date is what marks a missed day.

6. **Persist — do not end the run with today's data only in the working tree.**
   Commit `/ingest/<date>/` and the updated `run-ledger.json` and push **directly to
   `main-agents`**, no PR (Albert, 2026-08-23). Ingest output is data, not code: review
   adds nothing and demonstrably lost eight days. Commit as
   `daily-ingest: <date> run`. Code changes to agents, commands or contracts still go
   through a session branch and a PR against `main-agents` — this exemption covers
   `ingest/` only.

   If the push fails, retry with backoff (2s, 4s, 8s, 16s). If it still fails, say so
   loudly in the chat reply — an unpushed run is a lost run, and the next day's run will
   report it as a gap that never happened.

7. Reply in chat with the "Needs attention today" section verbatim, then the file path.

8. **Vault handoff.** Spawn `vault-writer-agent` (per its own instructions — read
   the brief, the day's `*.json`, and `actions-log.json` if present; write only
   within its whitelist; propose-and-stop on anything else). A vault failure
   (missing repo, git error) must not roll back or edit `DAILY-BRIEF.md` — it is
   already written and final.

9. **Notion handoff.** Run `.claude/commands/notion-sync.md` against today's date.
   Team-destination writes happen automatically; private-destination candidates
   are proposed in chat and only written on explicit approval. A Notion failure
   must not affect `DAILY-BRIEF.md` or block step 8.

10. Reply with a one-line summary of steps 8–9 (vault: notes created/updated/declined;
    Notion: created/updated/skipped/failed counts, plus any private candidates still
    awaiting approval).

## Rules

- Terse. No filler. The brief must be readable in under 60 seconds.
- Never invent data for a missing source.
- If ALL sources errored, still write the brief — it becomes an outage report.
- Step 6 runs before the handoffs, so the vault and Notion never distil a run that
  isn't durable. Steps 8 and 9 run after the brief is fully written and are independent
  of each other and of it — a failure in either must never touch `DAILY-BRIEF.md`, and a
  failure in one must never block the other.
