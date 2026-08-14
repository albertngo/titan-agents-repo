## Daily Brief — 2026-08-14

**Needs attention today**
- ~~PR #14 ("daily-ingest: 2026-08-09 run") sat open and unmerged for 5 days — that run actually happened (GHL/Outlook/Notion ok) but never landed on `main-agents`.~~ **Resolved same-day**: merged into `main-agents` (commit `0bd73e1`) on Albert's request; 2026-08-09 is now correctly on record in `run-ledger.json`.
- Dang Associates (accountant) flagged that Titan's 2022–2024 historical QuickBooks numbers changed after those years' tax returns were already filed with CRA — a compliance exposure, needs review before it becomes a filing problem.
- Sowmya's project won today ($10,680) — the automated 35% deposit request just went out; confirm the e-transfer is received before the Aug 27 start date.
- MetCredit collections agency is chasing a $438.57 Rogers Communications debt on Titan's account, with a settlement offer on the table — needs a decision.
- Jonathan Spence (repeat hot customer, 2 prior won projects) asked for quotes on a 2nd restaurant and called again today with no answer — still unaddressed.
- Two Notion Titan Projects rows for new wins have data gaps: Clarance Pittson (~$11,719, no Opportunity ID/Contact) and Billy Le (no Opportunity ID, Value, or Address) — won't cross-reference against GHL until fixed.
- RBC flagged both a Low Balance Warning (Aug 12) and a "your email address was updated" notice addressed to "Cuu" — confirm cash position and that the email change was authorized.

**Numbers**
- GHL: 216 leads total, 6 new, 19 unanswered conversations, 1 appointment booked, 7 pipeline moves, 1 won today ($10,680.01), 176 workflow-drift findings
- Notion: 6 new won projects ($36,341.51 CAD), 4 payments ($4,383.03 CAD), 76 stale tactical tasks, 0 new meetings
- Outlook: 125 messages scanned across 4 mailboxes (catch-up window, ~130–154h), 15 flagged items (0 unanswered customer, 5 supplier, 7 admin, 3 customer), 66 noise skipped, 0 bounces
- Meta Ads: $47.09 CAD spend, 4 leads, $11.77 CPL, 1 active campaign, 0 flagged ads
- Bookkeeper: no data — no QuickBooks/Intuit MCP connector configured

**By source**
- **GHL** — Fully reachable. 6 new leads, 1 appointment, 1 win today (Sowmya, $10,680). 176 workflow-drift findings, still dominated by the ~121-record Oct-2025 "Far Out (Cold)" bulk-import backlog (149 stale_approaching). Also flagged: an undocumented `abandoned-stale` tag on 3 open opportunities (incl. Tina Tran, who told Titan months ago she's using someone else), Rose Vill still getting nurture after explicitly declining Aug 11, and 5 opportunities 165–272% past their auto-abandon point. Used the standard 24h window rather than backfilling the 08-09–08-13 gap.
- **Notion** — Reachable. 6 new won projects totaling $36,341.51 CAD, but 2 (Clarance Pittson, Billy Le) have missing fields (see above). 4 payments totaling $4,383.03 CAD, none over the $5k threshold. Stale tactical task backlog grew to 76/132, led by "Update POS Price List" (24) and general/other (23). Also flagged: `notion-ingest-sources.json` has stale column names for QA Work Orders (adjusted live this run, registry needs a fix).
- **Outlook** — Reachable, catch-up run (last success was 2026-08-09, window widened to 130h/154h to close the gap). Beyond the items above: nothing else customer-facing was unanswered. Two Interac roll-ups covered routine e-transfer noise ($20,910.88 in, $18,721.12 out, all accounted for).
- **Meta Ads** — First run for this source. $47.09 spend, 4 leads, $11.77 CPL — below the 7-day baseline CPL (~$14.37), no anomaly. Only "Flooring Problems Campaign" is active; 3 others paused with no budget.
- **Bookkeeper** — No QuickBooks/Intuit MCP server configured in this session (`.mcp.json` only defines `ghl`). Same failure mode as 2026-08-08.

**Sources missing today**
- bookkeeper — status: error — no QuickBooks/Intuit MCP connector configured
- No run at all on: 2026-08-10, 2026-08-11, 2026-08-12, 2026-08-13. (2026-08-09 did run — GHL/Outlook/Notion ok — and PR #14 has since been merged to `main-agents`; see "Needs attention" above.)
