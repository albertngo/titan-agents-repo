## Daily Brief — 2026-10-20

**Needs attention today**
1. **GHL is dark** — ingest failed (GHL MCP tools unavailable to the agent). No leads, unreads or drift reviewed today. Check `.mcp.json` / `GHL_PIT_TOKEN` / `GHL_LOCATION_ID`; re-run.
2. **Unanswered customer** — Brian Andrade (info@, 10-16): LVP over a 1/2" height difference, wants to buy. No reply found.
3. **Tax/bank/WSIB** — CRA corporation notice of assessment/reassessment posted 10-16; BMO sent two "final reminder" encrypted Annual Review messages; WSIB premiums due Oct 31.
4. **$5,000 payment unmatched** — Mayuri S Bhatti e-Transfer (Oct 19) at the threshold, not yet matched to a project.
5. **Supplier money/list** — Sidco asks payment ("cash account" $3,599) with statement; Olympia Tile OCT LIST attachment awaiting catalogue workflow.
6. **Books** — accountant says QBO bank feeds are broken, 4 accounts need reconnecting; bookkeeper ingest is also down.
7. **Coverage gap** — Outlook, Notion and Meta Ads each last ran 2026-09-08. Outlook covered only 7 days, so 2026-09-09 to 2026-10-12 was not scanned. Notion cold-started: 7 projects won Oct 13–17 (~$52.7k) were not emitted as new-won items; 2 have blank Opportunity ID/Name (1050 Paramount Drive, 43 Harvest moon drive).

**Numbers**
- GHL: no data (error).
- Outlook: 143 scanned; 6 customer, 4 supplier, 7 admin; 1 unanswered customer; 0 bounces.
- Bookkeeper: no data (error); zeros in the file are placeholders.
- Notion: 0 new won (cold start), 1 open work order, 2 payments ($9,558.73), 206 stale tactical tasks.
- Meta Ads (7 days, 10-13 to 10-19): $347.55 spend, 16 leads, CPL $21.72, 1 active campaign, 0 flagged ads.

**By source**
- **GHL:** Nothing pulled. The call-pull script listed 19 calls (15 from notes, 2 skipped-short, 2 no-recording) but they were not analysed.
- **Outlook:** Customer: Brian Andrade (above); a door-frame damage complaint after install (pourya@); 71 Porter Field Rd quote accepted, job wanted by Oct 30; Church Meadows customer confirms a $2,994.75 e-transfer. Money: 10 incoming Interac deposits (~$33,874.55), 3 outgoing e-transfers to Luxevista ($12,168.62), Atlantic Flooring invoice 50851. Admin: CRA, BMO, WSIB, QBO feeds. Low: condo notices, Biyork/Vizion notices, Kitchen Crafters bid requests (Nazih Henein job).
- **Bookkeeper:** Intuit QuickBooks MCP connector not available; no QBO data read.
- **Notion:** One minor warranty work order (WO-Silviya Jardany-102026, status "Sending...", not an error). Payments: $5,000.00 Mayuri S Bhatti (unmatched), $4,558.73 Edwin Wong. 206 stale tactical tasks (197 Not started, 9 In progress). Latest meeting (Oct 6) has no summary. Settings drift: QA Work Orders properties renamed (`Budget Expense` → `Budget Expense ($$ Payout)`, `Description To Send` → `Description To Send (To Contractor)`); `notion-ingest-sources.json` needs updating.
- **Meta Ads:** Flooring Problems Campaign is the only active campaign (9,330 impressions, 257 clicks, $50/day budget). Account active, no disapprovals. Weekly totals, so no daily baseline.

**Sources missing today**
- ghl: error — GHL MCP tools unavailable to the agent.
- bookkeeper: error — Intuit QuickBooks MCP connector not available.
- No run at all on: 2026-09-09 through 2026-10-19 (ledger's last entry is 2026-09-08; may be a branch-isolation artifact, unverified).
