## Daily Brief — 2026-10-01

**Needs attention today**
- **BMO Online Banking lockout** (Outlook): user Albert Ngo locked and a temp-password reset issued ~22:43 Toronto. Confirm it was you; if not, call BMO.
- **GHL not ingested** (error): no leads, conversations or drift today. Fix GHL MCP / `GHL_PIT_TOKEN` / `GHL_LOCATION_ID`, re-run.
- **Payments ≥ $5k** (Notion): $15,028 Basil (09-29); $9,700 Rachita Saini (09-30); $5,000 Mayuri Bhatti (09-30).
- **35 Humberstone Cres**: broker asked 09-28 to drop the $450 disposal line and resend quote. No reply found.
- **Open install complaint** (Jul 2 job): contesting repairs and balance; Albert replied 09-30, unresolved.
- **Vidar** asked for a pick-up date, no reply. Two empty-body "invoice" emails from a gmail sender look like phishing. Do not open.
- **32 stale Tactical Tasks** (9 are GHL-sourced rows from 09-11).

**Numbers**
- GHL: no data (error).
- Outlook: 126 scanned, 20 items (7 customer, 6 supplier, 7 admin), 1 unanswered customer, 0 bounces.
- Bookkeeper: no data (error); zeros in file are placeholders.
- Notion: 7 payments ($36,108.99), 32 stale tasks, 0 WOs in error, new meetings unknown.
- Meta Ads (09-24→09-30, 7 days): $343.21 spend, 22 leads, CPL $15.60, 241 clicks, 10,341 impressions, 1 active campaign, 0 flagged ads.

**By source**
- **GHL:** MCP server exposed no tools. Nothing reported.
- **Outlook:** Catch-up run, 7-day cap; 09-09→09-23 not covered. Highest priority is the BMO lockout. Customer: Humberstone quote unanswered, install dispute open. Supplier: Vidar pick-up date. Pourya items are private.
- **Bookkeeper:** QBO connector unavailable (long-running; no connector since 2026-07-26).
- **Notion:** Partial. Project Status Meetings query failed (Notion 500), snapshot carried from 09-08. Cold start: 3 projects won in last 7 days (Jeevan, Arika $12,825.50, Mayuri Bhatti $16,498) not itemized as new. Settings drift in `notion-ingest-sources.json`: "Budget Expense" and "Description To Send" renamed, "Pending Status" removed.
- **Meta Ads:** Flooring Problems Campaign ($50/day) is the only one delivering; three others paused. Weekly window, so no anomaly comparison was run.

**Sources missing today**
- ghl: error — MCP tools unavailable.
- bookkeeper: error — QBO connector unavailable.
- notion: partial — meetings query failed (500).
No run at all on: 2026-09-09 → 2026-09-30 per ledger (ledger last entry 09-08; ingest folders exist for 09-27 to 09-29, so some of this may be ledger drift).
