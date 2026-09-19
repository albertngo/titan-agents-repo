## Daily Brief — 2026-09-19

**Needs attention today**
- Moenad Nadeem's warranty repair (vinyl stair treads, 24 steps — QA flagged Major) has a 50% e-transfer deposit requested Sep 18; confirm it landed before the tentative Oct 7 date slips. [Conversation](https://app.gohighlevel.com/v2/location/4BwjVRlyDCR4ZRdcSrFR/conversations/conversations/huk6TAFkVlONhmD4yUsR) · [QA Work Order](https://app.notion.com/3df596a4505f81c29f5bebc57a52d759)
- Mike & Sabrina Agard: bin still blocking their driveway at 9 Midnight Lane. $3,000 already sent, more coming — they're waiting on pickup confirmation and receipts. [Conversation](https://app.gohighlevel.com/v2/location/4BwjVRlyDCR4ZRdcSrFR/conversations/conversations/jnjaIuR4T8DxbDw1vyzp)
- Allison Hubson's install date is unresolved: baseboards still in transit from Vancouver, no date confirmed between her Sep 24/29 availability and Titan's Sep 28/Oct 6/8 offers. [Conversation](https://app.gohighlevel.com/v2/location/4BwjVRlyDCR4ZRdcSrFR/conversations/conversations/2j99fXSritgaJptU83vX)
- Muhammad Rafiq declined Sep 6 and his opportunity auto-abandoned today, but he's still tagged `lead: hot` and automation kept messaging him through Sep 18 — fix the tag or stop the drip. [Conversation](https://app.gohighlevel.com/v2/location/4BwjVRlyDCR4ZRdcSrFR/conversations/conversations/7meSyCRX3JKlijqbXkYC) · [Opportunity](https://app.gohighlevel.com/v2/location/4BwjVRlyDCR4ZRdcSrFR/contacts/detail/IwxPuw1IDDifSpReVNA9)
- 3 new contacts today are missed calls with no voicemail and no name captured — (780) 916-1099, (647) 247-3199, (437) 494-4585. No way to reach back until they call again.
- Recurring, escalating finding across GHL/Outlook/Meta-ads: this session branch's local ledger/ingest history lags (last merged entries ~2026-09-08), but real daily runs happened every day through 2026-09-18 on unmerged session branches. Outlook's run flagged a real unanswered high-priority customer thread from 2026-09-18 that isn't visible here. Worth confirming with Albert whether `/daily-ingest` output is reliably merging to `main-agents`.
- QuickBooks/Intuit MCP connector is still not configured — bookkeeper has produced zero data on every recorded run since 2026-07-26. Add an Intuit QBO MCP server entry with credentials before the next scheduled run.

**Numbers**
- GHL: 7 new leads, 7 unanswered conversations, 1 appointment booked, 0 won, 35 workflow-drift findings (113 total leads: 25 hot / 43 warm / 26 cold / 5 stale).
- Outlook: 25 scanned (2 customer, 1 supplier, 4 admin, 14 noise), 0 unanswered customer threads, 0 bounces.
- Bookkeeper: error — QBO connector unconfigured, no data.
- Notion: 5 payments totaling $45,933.60, 1 open work order (Major/Warranty), 153 stale Tactical Tasks, cold-start snapshot (0 new won emitted, 3 seeded for tomorrow's diff).
- Meta Ads: $45.48 spend, 2 leads, $22.74 CPL, 1 active campaign, 0 flagged ads.

**By source**
- **GHL:** 7 new leads, 7 real unanswered conversations (after excluding 10 missed-call-no-voicemail and 1 scam solicitation). 35 drift findings dominate today — 22 `stale_approaching` (worst: Maria | Waterdown, 95 days / 316% of threshold on a $41,150 quote), 9 `meeting_no_followup` (Mona and Mizanur worst, 87/79 days since their visit), 4 `categorization_miss`. Chris Portelli's `stale_lead` tag looks premature (49% into threshold) and risks a false abandonment on an active hot deal.
- **Outlook:** Quiet day — no high-priority items, 0 unanswered customer threads. Notable admin item: Albert engaged Dang & Associates (accountant) at $400/month for QBO cleanup, relevant given bookkeeper's standing outage.
- **Bookkeeper:** Full outage, unchanged since 2026-07-26 — no QBO/Intuit MCP server configured. Zero visibility into payments received, overdue invoices, or uncategorized transactions.
- **Notion:** Cold-start run (no prior snapshot in the 7-day lookback). 1 Major/Warranty QA work order (Moe Nadeem, stair treads). 3 payments ≥$5,000 including a $27,700 cash payment from Diego (2026-09-17) and a $5,500 cash payment from Gustavo. 153 Tactical Tasks are past their staleness threshold (oldest 166 days) — several "Update POS Price List" tasks may be superseded by the automated `/catalog-sync` pipeline and worth a bulk review. A stale property-name mapping in `platform-settings/notion-ingest-sources.json` (`qa_work_orders.select_columns`) caused live 400s and should be corrected.
- **Meta Ads:** $45.48 spend on the sole active campaign (Flooring Problems), 2 leads at $22.74 CPL, in line with the 7-day baseline (~$16.77 CPL). No disapprovals or delivery issues. Lead-action-type drift in the script's `LEAD_ACTION_TYPES` set recurs (no count discrepancy) and should be fixed at the source.

**Sources missing today**
- `bookkeeper`: status `error` — QuickBooks/Intuit MCP connector not configured (no `.mcp.json` entry, no credentials in `.env`/`.env.example`). Standing gap since 2026-07-26, not a transient outage.
- All other sources reported `ok`.
