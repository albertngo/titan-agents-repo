## Daily Brief — 2026-10-26

**Needs attention today**
- GHL ingest FAILED (no GHL MCP tools in this session; unread triage timed out). No leads, pipeline, unanswered or drift data today. Re-run where the `ghl` MCP is attached.
- Bookkeeper unavailable (no QuickBooks connector). Payments, overdue invoices and uncategorized transactions NOT checked.
- Customer complaint, doorframe damage after install (Sylvia, Pourya mailbox): customer asked for Oct 30; no reply since 10-19. Private.
- Rogers collections notice via MetCredit, $465.77 outstanding, interest accruing (albert@, no reply found).
- 4 new won projects in 7 days (Behnam, Jonathan Stellnberger, Christopher, Tiago Pereira); none has a PM assigned; Behnam has no value set.
- Unanswered in Outlook: Luxevista "43 harvest moon dr" (attachment only) and ethanesus@gmail.com "Renovation details" (Pourya mailbox).
- PL-393 / PL-394 GLOBALCFS price-list tasks open 20 days (new supplier, cost basis needed, 45 products held); Prosol price increase notice (info@) is a catalogue review candidate.

**Numbers**
- GHL: error, no data.
- Outlook: 127 scanned, 21 items (2 customer, 6 supplier, 13 admin), 2 unanswered customers, 106 noise skipped.
- Bookkeeper: error, no data.
- Notion: 4 new won projects ($10,895.97 known value), 0 work orders in error, 4 payments ($11,492.11), 14 stale tactical tasks, 0 new meetings.
- Meta Ads (7 days, 10-19 to 10-25): $352.31 spend, 7,972 impressions, 226 clicks, 16 leads, CPL ~$22.02, 1 active campaign, 0 flagged ads.

**By source**
- GHL: Nothing pulled. See Sources missing.
- Outlook: Catch-up run capped at 7 days, so roughly 09-09 to 10-18 is not covered. Highest-priority items are the Sylvia doorframe complaint, the Rogers/MetCredit notice, the two unanswered attachment-only emails, and the Prosol price increase notice. Interac e-Transfer receipts: 7 external payers.
- Bookkeeper: Nothing pulled.
- Notion: Cold start (last notion.json 2026-09-08); snapshot seeded. Four new won projects, none with a PM. Latest status meeting (Oct 6) has no Meeting Summary and none since. 14 stale tactical tasks, the oldest being PL-393/PL-394. Settings drift: `notion-ingest-sources.json` QA Work Orders columns are renamed (`Budget Expense ($$ Payout)`, `Description To Send (To Contractor)`).
- Meta Ads: Flooring Problems Campaign is the only active campaign and takes all spend ($50/day budget). No alerts. No prior meta-ads.json, so no CPL baseline comparison.

**Sources missing today**
- ghl: status error. No GHL MCP tools in the session; `ghl_unread_pull.py` timed out twice. GHL unread triage did not report.
- bookkeeper: status error. QuickBooks connector not reachable.
- No run at all on: 2026-09-09 through 2026-10-25 per `run-ledger.json` (last entry 2026-09-08); an `ingest/2026-10-18` folder exists, so the ledger may be incomplete rather than every day skipped.
