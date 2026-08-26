## Daily Brief — 2026-08-26

**Needs attention today**
- **2160 Peachtree Lane** (srisowm@gmail.com) — asked 2026-08-22 about hardwood delivery/stair design, still no reply; install expected to start tomorrow, 2026-08-27.
- **BMO annual review** — Dang Associates sent 4 outstanding invoices + an Engagement Letter Hien Nguyen asked Albert to sign "today" to hit BMO's Thursday (2026-08-27) compilation-financials deadline.
- **Basil Felix Da Souza** (won $19,888, largest deal this window) — $1,972 balance still pending on an e-transfer limit delay; called again this morning, no answer.
- **Damian** (won $4,850, Innisfil) — ~$2,430 balance uncollected; repeated unreturned call-back requests since Aug 18, silent 5.8 days.
- **Vic Montero** (won $5,227.47) — Albert admitted an underpad workmanship mistake at the Aug 14 walkthrough; customer's request for a written deficiency list has gone unanswered 12 days.
- **Bookkeeper (QuickBooks) ingest down 4 runs running** (08-08, 08-09, 08-14, today) — MCP connector still not configured in `.mcp.json`; 11-day data blackout on payments/invoices. Needs an infra fix, not another repeat flag.
- **100 of 100 open Notion Tactical Tasks are now stale** (up from 76/132 on 08-14) — flagged on 07-31, 08-08, 08-14, and today. Overdue for a batch triage.

**Numbers**
- GHL: 211 leads (74 new), 41 unanswered conversations, 5 appointments booked, 5 won ($43,856.80), 164 workflow-drift findings.
- Outlook: 103 scanned (5 customer, 2 supplier, 13 admin), 1 unanswered customer, 0 bounces.
- Bookkeeper: **error** — no data (connector unconfigured).
- Notion: 7 new won projects ($47,803.80), 6 payments received ($17,596.96), 100 stale tactical tasks, 0 new meetings.
- Meta Ads: $349.35 spend, 33 leads, CPL $10.59 (well under the ~$14.59 prior-week baseline), 1 active campaign, 0 flagged ads.

**By source**
- **GHL**: Catch-up pull covering the 11-day gap since 08-14. 74 new leads, 5 wins worth $43,856.80, and 262 open opportunities scanned for drift — 164 underlying drift-affected records (stale_approaching 143, meeting_no_followup 14, categorization_miss 5). Carryovers unresolved since 08-14: the 93-record frozen "0b. Far Out (Cold)" bulk-import batch, Ghandi (97% to auto-abandon, $21,283 quote) and Zinat Hirji (76.9 days past auto-abandon, $14,000 quote), and 3 opportunities with an undocumented "abandoned-stale" tag.
- **Outlook**: 168h/192h widened catch-up window (still leaves ~5 days, 08-14–08-19, unscanned, outside the 7-day cap). Beyond Peachtree Lane and the BMO letter, a new CRA source-deductions statement (PD7A) landed 08-20 and Blue Ant Media says Titan's Fall Home Show interim payment is overdue.
- **Bookkeeper**: Error — no QuickBooks MCP connector configured this session; zero data for the 4th consecutive run.
- **Notion**: 7 new won projects since 08-14 (~$47,803.80); 4 of the 7 have no Opportunity ID, so they won't cross-reference cleanly against `ghl.json`. One payment ($6,382.78) cleared the $5,000 attention threshold. No new Project Status Meeting logged since 08-04 (22 days) despite the weekly-cadence expectation.
- **Meta Ads**: 7-day window (08-19–08-25) pulled under the documented cap; 08-14–08-18 (5 days) remain un-ingested for spend/lead reporting — recommend a manual backfill if those days matter. CPL improved to $10.59 from a ~$14.59 baseline, no delivery/disapproval flags.

**Sources missing today**
- **Bookkeeper**: status `error` — QuickBooks/Intuit MCP connector still not configured (4th consecutive failure; 11-day data gap since 2026-08-14).
- No run at all on: 2026-08-15 through 2026-08-25 (11 days, all sources) — last logged run before today was 2026-08-14.
