## Daily Brief — 2026-08-21

**Needs attention today**
- Vic Montero (won customer) has had no reply in 6.5 days on install deficiencies Albert reportedly agreed to fix — send the deficiency list/solution.
- Daniella Powel is waiting on the water-leak repair e-transfer the team already agreed to send; she's now provided her e-transfer email, so payment is the only thing outstanding.
- 3 unanswered customer threads in pourya@'s inbox, all over the 24h threshold: Sabrina/9 Midnight Lane (deposit already sent, needs Sept 10 install confirmed), Ryan Langen/301 Markham St (asking arrival time), Felix D'Souza (asking a full flooring + stair quote).
- A $6,382.78 "Second Install" payment (Aug 19, credit card) has no sender name captured — confirm which project it belongs to.
- Make.com's "Website Inquiry Ingester" automation errored Aug 19 and is still unpaused — check whether inbound website leads have been silently dropped since then.
- No run at all on: 2026-08-15 through 2026-08-20 (6 missed days — last run before today was 2026-08-14).
- Zinat Hirji is 140% past the auto-abandon threshold in "1b. Postponed" and still shows open — the automation didn't fire; needs a manual check.

**Numbers**
- GHL (7-day catch-up window): 33 new leads, 41 unanswered conversations, 5 appointments booked, 2 won ($11,827.26), 147 workflow-drift findings.
- Outlook (7-day catch-up window): 121 messages scanned — 10 customer / 5 supplier / 13 admin, 3 unanswered customers, 1 bounce.
- Bookkeeper: error — no data (connector unconfigured).
- Notion: 4 new won projects ($15,774.26), 3 payments received ($8,899.77), 88 of 161 open tactical tasks now stale.
- Meta Ads (7-day catch-up window): $349.29 spend, 23 leads, $15.19 CPL, 0 flagged ads.

**By source**
- **GHL**: 7-day catch-up after the gap since 08-14. Full analysis for all 46 threads awaiting our reply; other 99 contact-side threads reviewed only at tag/volume level. Two wins this week (Glendy Chang $4,121, Sabrina Agard $7,706.26), but the standout is Vic Montero's stalled deficiency-fix reply and a batch of ~111 "Far Out (Cold)" opportunities still frozen since 07-28.
- **Outlook**: 7-day catch-up (168h/192h windows) across 4 mailboxes; no credential failures. Three unanswered customer threads all sit in pourya@. Also flagged: BMO's Jason Law still waiting on financial statements Albert already has, and three CRA business-address-change notices worth a quick "was this you" check.
- **Bookkeeper**: 8th consecutive documented failure (since 07-26) — the QuickBooks/Intuit MCP connector is still not configured. No transactions, receipts, or invoices could be pulled.
- **Notion**: 4 new won projects this week (~$15,774.26 total), but 3 of them are missing an Opportunity ID/Contact link on their Titan Projects row, so they won't cross-reference cleanly against ghl.json. Stale tactical-task backlog keeps growing (88, up from 76 on 08-14), and no Project Status Meeting has been logged in 17 days.
- **Meta Ads**: One active campaign (Flooring Problems Campaign) delivering normally at $15.19 CPL vs. a $14.37 baseline — no anomalies. Recurring trap: its lead-count still comes from conversion-action types outside the documented `LEAD_ACTION_TYPES` set, worth a script fix.

**Sources missing today**
- Bookkeeper: status `error` — QuickBooks/Intuit MCP connector not configured, no data pulled.
- GHL: status `partial` — 7-day catch-up window; full per-thread analysis limited to the 46 threads awaiting our reply, and reliable appointment dates were only available for 3 of 22 open Meeting-Scheduled contacts.
- No run at all on: 2026-08-15 through 2026-08-20.
