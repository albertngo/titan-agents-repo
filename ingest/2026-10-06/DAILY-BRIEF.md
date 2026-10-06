## Daily Brief — 2026-10-06

**Needs attention today**
1. **PBS Building Supplies — reply bounced.** info@'s reply went to accounting@pbssupplies.ca (doesn't exist); PBS has overdue invoices and sent a statement + invoice #13589 on 10-05. Resend to sabrina@pbssupplies.ca.
2. **Ashrim complaint** (July 2 install, disputed balance) — no reply after customer's 09-29 message. Also unanswered: RFQ from ultimateprotx.com (info@, since 09-30).
3. **GHL and bookkeeper both failed today** — no lead, pipeline, call-content or QBO data. GHL MCP tools unavailable (check `.mcp.json` / `GHL_PIT_TOKEN`); QBO connector missing. Re-run when reachable.
4. **BMO Online Banking** — Albert's user locked, password reset issued 10-01. Confirm Albert initiated it. Also a likely-phishing "compensation update" email (pastorbill@mymeadowood.org) in info@ — do not open the attachment.
5. **New won project: Diego Contecha** (Oakville, ~$28,080) — Project Type and PM unassigned. Major warranty WO (Helena Toolsiedas, cracked tiles) completed 10-05.
6. **Supplier money/pricing:** Sidco payment reminder; Floordi October promo price list (Oct 5–20, private, from pourya@).
7. **100 Tactical Tasks stale 14d+**, incl. catalogue blockers FAW PL-377/378 (Lightspeed write failures) and Vizion PL-373. Oct 6 status meeting has no summary yet.

**Numbers**
- GHL: no data (error).
- Outlook: 147 scanned; 4 customer, 9 supplier, 20 admin (12 Interac), 1 bounce; 1 unanswered customer.
- Bookkeeper: no data (error; zeros in file are placeholders).
- Notion: 1 won project ($28,080), 2 WOs created / 2 completed, 1 payment ($1,171.46), 100 stale tasks.
- Meta Ads (09-29→10-05): $356.10 spend, 19 leads, CPL $18.74, 224 clicks, 10,020 impressions, 1 active campaign, 0 flagged ads.

**By source**
- **GHL:** Failed; no leads, drift findings or call summaries today. The call-pull script ran (41 calls listed, 21 from notes, 5 transcribed) but nothing was summarised.
- **Outlook:** Catch-up run (no prior file in 7 days, Inbox widened to 168h). Highest-risk items are the PBS bounce and the Ashrim complaint; the Floordi promo list and In The Bin invoices are private.
- **Bookkeeper:** Failed; no QBO connector. Cash-in and overdue invoices unknown.
- **Notion:** Cold start (last file 2026-09-08), in-window activity only. Config drift in `notion-ingest-sources.json`: `Budget Expense` is really `Budget Expense ($$ Payout)`, `Description To Send` is `Description To Send (To Contractor)`, and `Pending Status` isn't a real status. 6 action items from Sep 29 still Not started.
- **Meta Ads:** Healthy, but the window was capped at 7 days; 09-09→09-28 is uncovered. No CPL anomaly comparison possible (single pull).

**Sources missing today**
- ghl — error: ghl MCP tools unavailable.
- bookkeeper — error: QuickBooks connector unavailable.
- No run at all on: 2026-09-09 → 2026-10-05 per this branch's ledger (last entry 2026-09-08). Vault daily notes exist through 10-05, so runs likely happened on other branches (branch-isolation artifact, as in the 09-08 ledger note); not verified.
