## Daily Brief — 2026-09-24

**Needs attention today**
- **Suspected vendor-email-compromise (fraud):** an email posing as Triforest Inc. ("Update to Triforest Inc. Banking Information") landed at info@ with a self-addressed To: field — classic VEC pattern. Titan has an active Triforest payment relationship. Do **not** update any banking/payment info from this email without phone verification first.
- **Rahma Rahman's opportunity ($1,826.67) auto-abandoned** — she'd chosen a floor and was waiting; the stall was Titan declining financing on Sep 14/15, not a customer rejection. Decide whether to re-approach.
- **Julie Ann Ohlman (won, $11,964.89):** sent her install address this morning; a $1,500 e-transfer landed today (Notion) and she has 10 mostly-unread live-chat messages (Outlook). Confirm the deposit, lock the install date, and close her stale duplicate $11,967.89 opportunity sitting in 0c. ASAP (Hot).
- **Ashrim Narsinh's Sep 11 warranty touchup was never repaired** — Albert's own internal note asked Pourya to set up a work order; still unresolved.
- **BMO encrypted secure message (case CS15164050) unopened since Sept 2**, reminder says it's nearing expiry — log into the BMO portal before access is lost.
- **Blue Ant Media / Toronto Home Shows: final Fall Home Show booth payment not received** — booth/badge access is blocked until paid.
- **Willy Reno called 4 times in under an hour** last night with no voicemail and no callback since — worth a call given the repeat attempts.

**Numbers**
- GHL: 120 leads (28 hot / 38 warm / 24 cold / 2 unqualified / 4 stale), 6 new, 6 unanswered conversations, 0 appointments booked, 3 pipeline moves, $0 won today, 51 workflow-drift findings.
- Outlook: 19 items (6 customer / 6 supplier / 7 admin) of 182 scanned across 4 mailboxes, 2 unanswered customer threads, 0 bounces. 7-day catch-up window (last run was 16 days stale).
- Bookkeeper: **error** — no data (QuickBooks connector still not configured).
- Notion: 1 payment ($1,500.00 CAD), 0 new-won-projects emitted (cold-start, earned-relevance rule), 176 of ~236 tactical tasks stale, meetings pull failed.
- Meta Ads: $361.32 spend, 29 leads, $12.46 CPL (below prior-week $16.88 baseline), 0 flagged ads. 7-day window (2026-09-17 to 2026-09-23).

**By source**
- **GHL** — Healthy volume, no appointments booked in 24h, zero wins/appointments today. Beyond the abandonment and Ashrim/Julie/Willy items above: 20 contacts sit untagged in the call queue awaiting categorization, and Meeting-Scheduled has 8 opportunities already past 150% of the 30-day stale threshold with no catch-up sequence (worst: Maria Waterdown at 100 days).
- **Outlook** — Widened to a 168h (7-day) catch-up window since the last successful run was 16 days stale; nothing older was re-scanned. Beyond the fraud alert, BMO message, and booth-payment items: Moe Nadeem's stair-repair warranty job is awaiting Titan's confirmation of a tentative Oct 7 date.
- **Bookkeeper** — Failed again: the QuickBooks/Intuit MCP connector has produced zero data on every recorded run since 2026-07-26. Standing setup gap, not a fresh outage — Finance stays `blocked` per `platform-settings/departments.json`.
- **Notion** — Partial: `project_status_meetings` hit a Notion workspace query-usage cap after the tactical-tasks pull, so new-meeting detection was skipped entirely this run (retry next run). Tactical Tasks backlog needs a batch triage pass (oldest: 171 days). A stale column-name mismatch in `platform-settings/notion-ingest-sources.json` (flagged since 2026-08-14) was worked around live again and still needs a real fix.
- **Meta Ads** — Account healthy: one active campaign (Flooring Problems Campaign, $50/day) delivered normally, no disapproved/flagged ads, CPL came in under the prior-week baseline. Widened to the 7-day cap since the last run was stale; 2026-09-09 through 2026-09-16 (8 days) remains uncovered and cannot be backfilled under the standard procedure.

**Sources missing today**
- Bookkeeper: `error` — QuickBooks/Intuit MCP connector not configured/reachable (10th+ consecutive failed run since 2026-07-26).
- Notion: `partial` — `project_status_meetings` sub-source failed (Notion workspace usage cap); tactical-tasks pull itself also incomplete (229/236 rows before the same cap hit).
- Ledger note: the run-ledger on this branch last recorded 2026-09-08, but vault `01_daily/` notes show continuous daily-ingest runs through 2026-09-23 with no actual gap — the same branch-isolation artifact recorded in the 2026-09-08 ledger entry (each session's local `run-ledger.json` doesn't merge back). No run at all on: none (confirmed via vault, not a missed-run gap).
