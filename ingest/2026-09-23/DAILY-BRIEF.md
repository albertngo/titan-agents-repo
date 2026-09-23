## Daily Brief — 2026-09-23

**Needs attention today**
- **GHL down all day** — the `ghl` MCP server was never approved for this session ("Pending approval"), so zero leads/opportunities/appointments/conversations were pulled. GHL normally drives most of this brief. Action: approve the `ghl` MCP server and re-run `ghl-ingest-agent` today (credentials are already valid).
- **Christine Pitter (4798 Huron Heights Dr) — unanswered 7+ days.** Asked albert@/pourya@ on 2026-09-16 for a final sales receipt for warranty purposes; no reply found in Sent Items.
- **Unopened encrypted BMO secure message** from Brandon Donnelly (case CS15164050, re: 1001321560 Ontario Inc.) sitting in albert@ — urgency unknown until opened.
- **Bookkeeper/QuickBooks still not connected** — 11th consecutive failed run since 2026-07-26 (no QBO/Intuit MCP server or credential exists). All cash-in, overdue-invoice, and uncategorized-transaction figures are unknown until this is set up.
- **Tactical Tasks List: 100/100 pulled rows are stale**, and the 100-row pagination cap (oldest-first) is hiding any newer row that's since crossed its own threshold — flagged on 5 separate runs now (07-31, 08-08, 08-14, 08-31, today). Overdue for a batch triage or a paginated pull.
- **Notion cold start**: no prior snapshot within 7 days, so 5 in-window Titan Projects rows ($9,819–$24,668 range) and 2 meeting rows were seeded silently, not surfaced as "new." 3 of the 5 have no Opportunity ID and won't cross-reference to GHL — worth a manual look.
- **Outlook/Meta Ads catch-up gap**: both sources' last successful run before today was 2026-09-08; windows were widened to their 7-day cap, but 2026-09-09→09-15 was never covered by any run and isn't recoverable from today's pull.

**Numbers**
- GHL: **error** — no data (MCP not approved this session).
- Outlook: 138 scanned, 8 customer / 9 supplier / 12 admin, 1 unanswered customer, 0 bounces.
- Bookkeeper: **error** — no QBO connector (unchanged since 2026-07-26).
- Notion: 1 payment ($2,574.00), 100 stale tactical tasks, 0 new won projects reported (cold start), 0 work orders in error.
- Meta Ads: $354.19 CAD spend, 25 leads, $14.17 CPL, 1 active campaign, 0 flagged ads.

**By source**
- **GHL** — Total outage today: the MCP server sat at "Pending approval" so no API calls were made. Every prior recorded run since 2026-07-26 succeeded, so this is a one-off session gap, not a credential or platform problem. Re-approve and re-run as soon as possible since this is the primary lead-workflow source.
- **Outlook** — Ran a 168h/192h catch-up window across 4 mailboxes (albert@, info@, pourya@, mike@) after a 15-day gap. Top item is Christine Pitter's overdue warranty-receipt request; also flagged an unopened encrypted BMO message and two unsolicited PE/M&A acquisition-outreach emails (no action taken — treated as broker cold outreach, not a real inquiry). A Fall Home Show badge-registration reminder is still open.
- **Bookkeeper** — Still fully blocked: no QuickBooks/Intuit MCP connector exists in `.mcp.json` or `.env.example`. This is a standing setup task, not a transient failure, and matches the Departments table ("Finance — blocked").
- **Notion** — 100 of 100 pulled Tactical Tasks are past their staleness threshold, and the pagination cap means newer overdue rows are currently invisible. Weekly Project Status meeting cadence has slipped to 21 days since the last one (2026-09-02), plus a likely duplicate/incomplete meeting row from 2026-09-01. Cold-start seeded 5 Titan Projects rows and 2 meetings without surfacing them as new — worth a manual check, especially the 3 rows with no linked Opportunity ID.
- **Meta Ads** — Only 1 active campaign (Flooring Problems Campaign), delivering normally, no disapprovals. A 15-day gap since the last successful run meant the 7-day catch-up window couldn't cover 2026-09-09→09-15, so that week's spend/lead numbers are permanently uncaptured by this pipeline. A recurring lead-action-type overlap (seen on 3 prior runs) still needs the script's `LEAD_ACTION_TYPES` set extended.

**Sources missing today**
- **GHL** — status: error. MCP server pending approval for this session; zero data pulled.
- **Bookkeeper** — status: error. No QuickBooks/Intuit MCP connector configured (11th consecutive failed run since 2026-07-26).
