## Daily Brief — 2026-08-28

**Needs attention today**
- **Amica Whitby (Stephen Burns)** — invoice label fix ("estimate" on invoices 616 & 305) requested Aug 27, unanswered; actively blocking Amica's accounting from paying Titan.
- **Ghandi GanSon Home Inc** — auto-abandons in ~5 hours (0.2 days remaining, "0b. Later Date (Warm)") — last chance to intervene before GHL closes it automatically.
- **Sri (2160 Peachtree Lane)** — delivery/stair-pieces question from Aug 22 unanswered; the Aug 27 install start date it was tied to has already passed.
- **Sonia Rocha (22 Erindale, Brampton)** — reschedule-to-Sept-18 request from Aug 24 evening, unanswered.
- **GHL staleness automation looks broken**: 93 cold leads sitting at 337% of stale threshold (~303 days) were never auto-tagged `stale_lead`; separately *Zinat is 78.9 days past its abandonment point but still open. Worth checking the workflow directly.
- **Bookkeeper (QuickBooks) still blind** — connector unconfigured since before 2026-07-26; zero cash-in/receipts/invoice data for over two weeks running.
- **120 Notion Tactical Tasks now stale** (up from 76 on 8/14), including 13 high-priority GHL drift/escalation items sitting untouched since Aug 11–13, still unassigned.

**Numbers**
- GHL: 211 leads (86 new), 43 unanswered conversations, 4 appointments booked, 123 pipeline moves, 5 wins ($43,857), 176 workflow-drift findings.
- Outlook: 152 messages scanned (5 customer / 9 supplier / 9 admin), 3 unanswered customer threads, 0 bounces.
- Bookkeeper: error — no data (QBO connector not configured).
- Notion: 0 new-won-projects reported (cold-start suppressed 8 unreported wins ≈ $78,751.61), 3 open work orders, 1 completed, 9 payments ($30,837.96), 120 stale tactical tasks.
- Meta Ads: $349.90 spend, 30 leads, $11.66 CPL, 1 active campaign.

**By source**
- **GHL**: Catch-up pull covered the full 14-day gap. 5 projects won ($43,857 total; largest: Basil Da Souza's $19,888 [stairs + flooring](https://app.gohighlevel.com/v2/location/4BwjVRlyDCR4ZRdcSrFR/contacts/detail/ECcnb0wnweKgs3Q6rjaG)). Ariel Aradanas carries conflicting `lead: hot` + `lead: unqualified` tags — needs a human call. 12 contacts with confirmed call+SMS contact were never given a qualification tag; 8 of those are already GHL-flagged `stale_lead`, meaning categorization was skipped, not delayed.
- **Outlook**: All 4 mailboxes clean (no 403s). Besides the 3 unanswered customer threads above, notable payables need review: Rogers account sent to MetCredit collections ($444.17, accruing interest), plus overdue notices from Biyork, Liftow, and Blue Ant Media (Fall Home Show payment). A "family office" M&A-style inquiry (Jasmine Romero) is unanswered on its 2nd ask.
- **Bookkeeper**: No QBO/Intuit MCP connector configured — same failure mode as every run since at least 2026-07-26. Needs the connector + credentials added before it can produce real data.
- **Notion**: 27 items surfaced (4 QA deficiencies, 9 payments, 13 high-priority stale tasks, 1 rollup of 107 more). Live schema drift confirmed in `notion-ingest-sources.json` (QA Work Orders column names) — still unfixed since first flagged 2026-08-14. Weekly Project Status Meeting cadence appears stalled — no new meeting logged since "Aug 4/26," which is itself still unprocessed.
- **Meta Ads**: Only Flooring Problems Campaign is actively delivering (3 others paused). CPL improved vs. the prior comparable window ($11.66 vs. $15.21). 2026-08-15 through 08-20 has no ad-spend coverage and was not backfilled — used only as a one-off CPL baseline.

**Sources missing today**
- Bookkeeper — error: QuickBooks/Intuit MCP connector not configured; no data retrieved.
- No run at all on: 2026-08-15 through 2026-08-27.
