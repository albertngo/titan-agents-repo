## Daily Brief — 2026-08-30

**Needs attention today**
- Therese Gomes: disposal bin not picked up, guests arriving within the hour, hauler can't come today — needs an alternative fix now.
- Google account security: a new passkey was added to `titan991emt@gmail.com` (2026-08-29) — verify Albert/staff authorized this or secure the account.
- Bookkeeper connector down for the 4th consecutive check (2026-08-08, -09, -14, -30) — QuickBooks MCP server still unconfigured in `.mcp.json`; no financial data for over two weeks.
- 114 of 140 open Tactical Tasks in Notion are now stale (up from 76/132 on 08-14), and 4 customer-facing GHL follow-ups (Firoz Rajan, Vic Montero, Jonathan Spence, Daria) are buried in that rollup 16-17 days stale, still "Needs Verification."
- Biyork Canada past-due invoice (Acct 998, demanding payment ASAP) and MetCredit/Rogers collections balance now $444.17 — both unresolved, unreplied.
- Vimal Narayan explicitly declined 6 days ago but a duplicate $11,427 GHL opportunity is still open and receiving nurture emails; separately, two duplicate "Stephen Burns" Titan Projects rows risk double-counting ~revenue.
- **No run at all on: 2026-08-15 through 2026-08-29** (15 consecutive missed days) — every source's needs_attention below reflects a partial catch-up window only; nothing in that 15-day stretch has been ingested or can be recovered by a future catch-up run.

**Numbers**
- GHL: 4 new leads, 11 unanswered conversations, 1 appointment booked, 2 pipeline moves, 0 won today, 154 drift findings (mostly the long-running "Far Out (Cold)" batch and stale-approaching leads).
- Outlook: 128 unique messages scanned (12 customer, 13 supplier, 44 admin, 51 noise), 0 unanswered customer threads, 0 bounces.
- Bookkeeper: **error** — no data (connector unconfigured).
- Notion: 3 new won projects (~$56,846.85 CAD), 1 payment received ($1,966.27), 2 open / 1 completed work order, 114 stale tactical tasks, 0 new status meetings.
- Meta Ads: $349.67 spend / 29 leads / $12.06 CPL over a 7-day rollup (2026-08-23 to 08-29), 1 active campaign, 0 flagged ads.

**By source**
- **GHL** (ok): 210 total leads, 26 hot / 41 warm. Top issue is Therese Gomes' disposal-bin emergency. Several long-open items carry over unresolved from 08-14: Zinat Hirji (290% of stale threshold), Bash Saqr and Tina Tran (366-382%), and the ~119-opportunity "Far Out (Cold)" batch (339%, flagged every report since 07-28, needs a batch decision not one-by-one triage). Clarence Pitterson paid in full 08-27 but still hasn't gotten a receipt after two follow-ups. Michael Camara and Avishekh Pal are ~1 day from auto-tagging stale.
- **Outlook** (ok): Catch-up window widened to 168h/192h (2026-08-23→30); 2026-08-15→22 is permanently un-recovered. Beyond the security and collections items above, Liftow's two service invoices were only forwarded internally, never paid or answered.
- **Bookkeeper** (error): QuickBooks MCP connector unreachable — 4th straight failed check. Needs someone to add/repair the Intuit connector before the next run; this is a persistent config gap, not a transient outage.
- **Notion** (ok): Won projects: Stephen Burns/Whitby (x2 rows, one missing Opportunity ID/Contact/Sales Person — likely a duplicate) and Basil Felix Da Souza/Mississauga (~$19,888, also missing Opportunity ID). QA Work Order WO-Rino Del Giudice-041326 shows Status "Dropped" with a Completed Date 4 months after creation — likely a data-entry artifact. Status-meeting cadence appears lapsed for ~4 weeks (last row 08-04), coincident with the ingest gap.
- **Meta Ads** (ok): CPL improved slightly vs. the pre-gap baseline (7-day: $12.06 vs $13.45). Flooring Problems Campaign remains the only active campaign; recurring note that some lead-like conversion types fall outside the script's documented `LEAD_ACTION_TYPES` set, though counts still reconcile exactly.

**Sources missing today**
- Bookkeeper: error (QuickBooks MCP connector not configured/reachable — 4th consecutive occurrence).
- No run at all on: 2026-08-15 through 2026-08-29.
