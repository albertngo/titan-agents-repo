## Daily Brief — 2026-10-08

**Needs attention today**
1. **GHL and QuickBooks did not report** (no MCP tools in this session). Leads, pipeline, conversations, overdue invoices and payments are unchecked. Re-run those two in a session that has the connectors.
2. **Shannon Kitamura (info@)** asked on Oct 5 for a Nov 2 home visit at 2 Wylie Circle #85, Georgetown, and about the referral offer. No reply found.
3. **PBS Supplies** wants a billing preference (per invoice or monthly) and a card on file. Titan's reply bounced because accounting@pbssupplies.ca doesn't exist. Luxevista invoices of Oct 4–6 also have no reply.
4. **Security:** BMO Online Banking lockout and password reset on Oct 6 (albert@). Confirm it was Albert, and delete the email that holds a temporary password. A likely phishing email "Titanfloors Compensation Updat" is in info@ — don't open its attachment.
5. **Make:** scenario "Lightspeed - Notion @order" was deactivated by an error on Oct 7. Earlier GHL Call-Note probe scenarios (Oct 2) also errored.
6. **Meeting "Project Status — Oct 6/26"** has no Meeting Summary. Run the meeting processor on it.
7. **225 stale tactical tasks** (215 Not started over 14 days, 10 In progress over 21 days). Diego Contecha (opp 7LrToJPA2nhKZj5wWcyw) also has a duplicate Titan Projects row on Oct 5, probably a re-sync.

**Numbers**
- GHL: not reported (error).
- Outlook: 142 scanned, 3 customer, 9 supplier, 9 admin, 1 unanswered customer, 1 bounce. This is a 7-day catch-up window.
- Bookkeeper: not reported (error).
- Notion: 1 new won project ($28,080, likely duplicate), 2 payments ($4,674.32), 0 work orders in error, 1 new meeting, 225 stale tasks.
- Meta Ads (7 days, Oct 1–7): $342.45 spend, 18 leads, CPL $19.03, 9,403 impressions, 215 clicks, 0 flagged ads.

**By source**
- **GHL:** Failed, no data. The call pull did run (22 calls listed, 20 from existing notes, 1 transcribed), but nothing is joined to conversations. See `analysis/cache/ghl-calls/runs/2026-10-08.json`.
- **Outlook:** The window was widened to 7 days because there was no file for Oct 1–7, so anything before Oct 1 isn't covered. Customer items: Kitamura (above). Supplier items: PBS Supplies, Luxevista, a Prosol price increase notice, a Floordi October promo list (pourya@, private), a Solmo catalogue and a Sidco Global Trade payment reminder (amount not stated).
- **Bookkeeper:** QuickBooks connector unavailable. Nothing was read.
- **Notion:** Cold start, so the snapshot was seeded and only in-window activity reported. Payments were $4,000 from AP Landscaping and $674.32 cash from Basil, both under the $5,000 threshold. No work orders are in error. Two column names in `notion-ingest-sources.json` for the work-orders table are wrong: "Budget Expense ($$ Payout)" and "Description To Send (To Contractor)".
- **Meta Ads:** Only Flooring Problems Campaign is active ($50/day). The other three are paused. No CPL baseline exists, so no anomaly check was run.

**Sources missing today**
- ghl: error. The GHL MCP tools were not available in the ingest session.
- bookkeeper: error. The Intuit QuickBooks MCP connector was unavailable.
- No run at all on: 2026-09-09 through 2026-10-07 (29 days).
