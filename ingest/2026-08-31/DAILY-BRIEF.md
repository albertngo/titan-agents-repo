## Daily Brief — 2026-08-31

**Needs attention today**
- Gina Martino (won, $6,130.50, deposit paid): baseboards need to reach Georgetown this week for her father to paint before the Sept 8 install — asked yesterday, no reply ~15h+.
- MetCredit collections still chasing the Rogers Communications debt on Titan's account — now $444.17 (up from $438.57), unresolved 17+ days, needs a decision.
- ~$83K of Meeting-scheduled GHL work (Maria Wildfang $41.1K, Mizanur Bhuiyan $15.2K, Fareeda Chand $14.7K, Tina Tran $12.0K) sits 68–116 days into a 30-day stage with no `stale_lead` tag — 14 of 24 in that stage are past threshold.
- Biyork Canada (Account 998) and Liftow (2 invoices) both sent past-due/payment-needed notices to info@/albert@ with no reply in-window.
- Bookkeeper ingest has produced zero data on all 8 recorded runs since 2026-07-26 — standing gap, no QuickBooks MCP connector configured.
- Meta Ads and Outlook both hit the 7-day catch-up cap: 2026-08-14 through 2026-08-23 (10 days) of spend/lead and mail data was never scanned and is not recoverable.
- Unreturned voicemail from (416) 433-9872, unanswered ~21h, no name/opportunity on file.

**Numbers**
- GHL: 4 new leads, 3 pipeline moves, 0 appointments booked, 0 wins, 5 unanswered conversations, 73 workflow-drift findings (12 suppressed by the 0a. New Lead exclusion).
- Outlook: 126 scanned (4 customer, 7 supplier, 6 admin), 0 unanswered customers, 2 unanswered suppliers.
- Bookkeeper: error — no data (connector unconfigured).
- Notion: 100/100 open tactical tasks now past staleness threshold (cold-start after 17-day gap); 0 new won projects emitted (3 in-window, withheld per cold-start rule); last team meeting logged 2026-08-04 (27 days ago).
- Meta Ads: $351.86 CAD spend, 27 leads, $13.03 CPL, 1 active campaign, 0 flagged ads.

**By source**
- **GHL**: Light window activity (4 leads, 3 opportunities, 0 stage moves) but a heavy drift backlog: 59 stale-approaching findings, 8 categorization misses, 5 meeting-no-followup, plus the Silviya Jardany case where her appointment was booked 39 days after stage entry — stale fires before follow-up is even possible, a gap the new Meeting-scheduled sequence needs to absorb. An undocumented `abandoned-stale` tag is on 7 opportunities where `stale_lead` is expected.
- **Outlook**: All 4 configured mailboxes scanned clean, 0 errors. Same-day customer threads were all answered. The overdue items are all supplier/collections-side: MetCredit/Rogers ($444.17), Biyork (Account 998), Liftow (2 invoices, PSI-1436313/PSI-1436176).
- **Bookkeeper**: No data — QuickBooks/Intuit MCP connector still missing from `.mcp.json`. 8th consecutive failed run since 2026-07-26; needs a connector added before this source can report anything.
- **Notion**: Cold-started after a 17-day monitoring gap (last run 2026-08-14). 3 Titan Projects rows (Stephen Burns/Whitby ×2, Basil Felix Da Souza/Mississauga, ~$56.8K combined) landed in-window but were correctly withheld as new-won per the cold-start rule rather than misreported as today's wins. Tactical Tasks List staleness (100/100) is very likely gap-inflated, not a real one-day spike. Two registry field-mapping bugs in `notion-ingest-sources.json` (QA Work Orders columns, an invalid error status) remain uncorrected since first flagged 2026-08-14.
- **Meta Ads**: Only 1 of 4 campaigns delivered ("Flooring Problems Campaign"); CPL held roughly flat vs. baseline. Same 17-day gap as Notion/Outlook — pulled the capped 7-day maximum (08-24–08-30), leaving 08-14–08-23 permanently uncaptured.

**Sources missing today**
All sources reported (GHL, Outlook, Notion, Meta Ads: ok; Bookkeeper: error — QuickBooks connector unconfigured, see above).
No run at all on: 2026-08-15 through 2026-08-30 (16 days) — this branch's run-ledger has no entries in that span, though git history shows several of those days' ingest work exists on other, unmerged session branches (e.g. runs through 2026-08-24) that never reached `main-agents`. Worth reconciling separately; not resolved by this run.
