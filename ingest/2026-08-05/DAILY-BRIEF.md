## Daily Brief — 2026-08-05

**Needs attention today**
- Azzam Rahman cancelled today's 11:30am in-home visit ($10,287.50 Meeting-Scheduled deal) — opportunity and calendar hold need to be formally closed out.
- Vic Montero (won project, $5,227.47) is upset about an install delay, took time off work, and is demanding the install start Tue Aug 11 — needs written confirmation today.
- Therese Gomes: sent an $11,300 deposit under a different name, still unconfirmed received (Pourya said he'd check back, no update logged) — and is also a new won project (~$12,769.00 CAD, Cambridge) with no PM assigned yet.
- Sonia's Aug 6 in-home visit needs a stock-availability confirmation before then.
- $37,438.26 Meeting-Scheduled deal (Ben, Burlington) has sat untouched 130.7 days — the appointment was booked so far out it consumed the entire 30-day follow-up window before the visit even happened; no follow-up sequence exists for this stage yet.
- 123 open Far Out (Cold) opportunities average 249 days in stage; ~118 share one bulk timestamp from an Oct 2025 data migration and have never been stale-tagged or auto-abandoned — looks like a migration cohort the automation never processed.
- 54 open Tactical Tasks are past their per-status staleness threshold, up to 121 days on one "In progress" item (Call For Balance, Naqib) vs. its 21d threshold — worth a batch triage pass.

**Numbers**
- GHL: 284 leads total, 10 new, 13 unanswered conversations, 1 appointment booked, 6 pipeline moves, 0 won today, 35 workflow-drift findings
- Notion: 1 new won project ($12,769.00 CAD), 4 payments received ($9,645.59 CAD, none ≥$5k), 54 stale tactical tasks, 0 new meetings
- Outlook: no data — egress-blocked, 0 mailboxes scanned
- Bookkeeper: no data — no connector configured

**By source**
- **GHL** — 10 new leads, 1 appointment booked (then same-day cancelled — Azzam Rahman), 6 pipeline moves, no wins today. 35 workflow-drift findings, headlined by the 123-opportunity Far Out bulk-migration cohort and a $37,438.26 deal stalled 130.7 days with no follow-up sequence for its stage. Two customer-facing items need same-day action: Vic Montero's install-delay confirmation and Therese Gomes's unconfirmed deposit. 17 contacts also remain untagged in the call queue over 24h (oldest 13.3 days), and Manjinder Singh — tagged unqualified/Far Out despite an "ASAP" urgency field — is worth a second look.
- **Notion** — One new won project, Therese Gomes (~$12,769 CAD, Cambridge, sales: Pourya Lalee, no PM assigned). 4 payments totaling $9,645.59 CAD, none over the $5k flag threshold. No new/errored QA work orders. 54 tactical tasks are stale and need triage; no new Project Status meeting since the last snapshot.
- **Outlook** — Zero mailboxes reachable. All 4 (albert@, info@, pourya@, mike@) failed identically with a 403 at the proxy's CONNECT step to graph.microsoft.com — this is a session egress-policy gap, not per-mailbox access-policy or expired credentials. The unscanned gap now spans ~62h since the last successful run (2026-08-02 18:00) and is growing.
- **Bookkeeper** — No QuickBooks MCP connector configured in this session (`.mcp.json` only defines `ghl`). No transactions, receipts, or invoices checked.

**Sources missing today**
- outlook — status: error — egress proxy blocked graph.microsoft.com at CONNECT (403) for all 4 mailboxes; not a credentials or per-mailbox access-policy issue
- bookkeeper — status: error — no QuickBooks/Intuit MCP connector configured
- No run at all on: 2026-08-03, 2026-08-04
