## Daily Brief — 2026-10-30

**Needs attention today**
1. **Google account security** — alerts on albertngo95@gmail.com: password changed and a blocked sign-in by someone holding the password. Confirm it was you. (Outlook)
2. **GHL not ingested** — GHL MCP unavailable this session; leads, conversations, drift and unread triage are NOT covered today. Re-run where `ghl` MCP is connected. (GHL)
3. **Unanswered customers (Pourya's mailbox)** — Mayuri, 4485 Full Moon Circle: revised quote wrong (30 spindles installed vs 42 quoted, $324 to deduct); ethanesus@gmail.com renovation details, attachment only, since 10-24. (Outlook)
4. **Possible spoof** — Bella Flooring email from a Gmail address asks suppliers to CC a new contact. Verify before changing anything. (Outlook)
5. **Supplier payables** — Floordi asks for payment of invoice 000957; Grandeur statement $3,126.62 outstanding. (Outlook)
6. **Notion** — ~100 stale Tactical Tasks (incl. high-priority price-list decisions open since early Sept); won project "Albert Ngo" ($11,470.74) looks like a test row; Oct 6/26 Project Status has no summary. (Notion)
7. **Coverage gaps** — Bookkeeper and WeChat errored (below); Outlook covers 10-23..10-30 only, so 10-08..10-22 is unread.

**Numbers**
- GHL: no data (error)
- Outlook: 129 scanned, 17 items (3 customer, 6 supplier, 8 admin), 2 unanswered customers
- Bookkeeper: no data (error)
- Notion: 4 won projects ($31,851.01), 7 payments ($12,508.50), 1 open work order, 100 stale tasks, 0 new meetings
- Meta Ads: $47.62 spend, 2 leads, CPL $23.81 (7-day baseline ~$18.33), 1 active campaign, 0 flagged ads
- WeChat: no data (error)

**By source**
- **GHL** — Errored: no MCP. Call pull did work (21 calls listed, 18 with notes) but no summaries were written; unread triage timed out. Nothing about leads or pipeline can be said today.
- **Outlook** — Catch-up run, widened to the 7-day cap. Main findings are the Google security alerts, two unanswered customer emails in Pourya's mailbox (private), a suspect Bella Flooring request, and two supplier payment asks (Floordi, Grandeur).
- **Bookkeeper** — Errored: no QuickBooks connector in this session. Its zero metrics are placeholders, not real.
- **Notion** — Cold start (last file 10-07), so the 4 won projects are the last 7 days and may not be new. Work order WO-Moe Nadeem-102926 lacks QA Type/Severity. Payments all under the $5,000 threshold.
- **Meta Ads** — Healthy for 10-29: $47.62 on the Flooring Problems campaign, 2 leads, CPL about 1.3x the 7-day baseline, under the 2x flag.
- **WeChat** — Errored: `NOTION_WECHAT_READ_TOKEN` missing from .env. Zero items does not mean a quiet day.

**Sources missing today**
- ghl: error — GHL MCP tools unavailable; triage status error (pull timed out).
- bookkeeper: error — no QuickBooks/Intuit MCP connector in this session.
- wechat: error — NOTION_WECHAT_READ_TOKEN missing from .env.
- No run at all on: 2026-10-08 through 2026-10-29 per this branch's run ledger (last entry 2026-10-07). An `ingest/2026-10-29/` folder exists (whatsapp.json only), so the ledger may simply be stale on this branch.
