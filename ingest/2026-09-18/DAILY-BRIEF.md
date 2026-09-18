## Daily Brief — 2026-09-18

**Needs attention today**
1. **GHL ingest failed entirely today** — the `ghl` MCP server's tools were not attached to this session despite valid config/credentials in `.env`. Leads, pipeline moves, appointments, conversations, and workflow-drift findings are all unknown for the last 24h. GHL is the backbone source for this brief — re-run `ghl-ingest-agent` once MCP tool access is restored.
2. **[[cpitter01@yahoo.ca]] — Project Quote, 4798 Huron Heights Dr** — two messages (Sept 14, Sept 16) to albert@/pourya@, no reply found in Sent Items across the full pull window. Last message 40+ hours old.
3. **[[srisowm@gmail.com]] — "Need to speak urgently"** — opening message answered same day, but the customer's follow-up reply on the same thread (~3 days ago) has no reply found since.
4. **Oakel City check-payment fraud warning** — a check Titan mailed was intercepted, altered, and deposited by a third party; other mailed checks reportedly never arrived. Confirm no recent check was sent and consider a safer payment method.
5. **Bank/government mail going stale** — BMO reminder that an encrypted message from Brandon Donnelly (ref CS15164050, sent Sept 2) is still unread and may expire; separately, CRA posted a new PD7A (payroll source deductions) statement of account (Sept 12) — amount/due date not visible without logging in.
6. **QA Work Order (Major) completed** — WO-Jay Ventura -090826 (closet hardwood/nosing) closed 2026-09-16, $250 payout — confirm contractor payout and customer sign-off.
7. **Bookkeeper still down** — 11th consecutive failed run since 2026-07-26; no QuickBooks/Intuit MCP connector configured. Finance remains blocked (per `departments.json`).

**Numbers**
- GHL: error — no data (MCP tools unavailable this session).
- Outlook: 132 scanned (11 customer, 12 supplier, 7 admin, 65 noise), 2 unanswered customer threads, 0 bounces.
- Bookkeeper: error — no QuickBooks/Intuit connector (11th consecutive failure).
- Notion: 2 work orders completed, 2 payments received ($3,083.69), 153/210 tactical tasks past staleness threshold, cold start (no new_won_project/meeting items emitted — earned-relevance rule).
- Meta Ads: $48.69 spend, 3 leads, $16.23 CPL, 1 active campaign, 0 flagged ads.

**By source**
- **GHL**: No data — MCP server tools were not exposed to the ingest agent this session (config/credentials are valid; this looks like a session-level attachment failure, distinct from bookkeeper's standing config gap). Nothing else in this brief reflects GHL activity for 2026-09-18.
- **Outlook**: 4 mailboxes scanned, all reachable (no 403s). Two customer threads are unanswered past threshold (Huron Heights quote, "need to speak urgently" follow-up — both #2/#3 above). A warranty claim (Moe Nadeem, stair-nosing) and a complaint (5301 Churchill Meadows) are both active but already answered. Financial admin mail: ~$20,853 in incoming Interac transfers and ~$13,378 in Yardi/Amica remittances (informational), plus ~$9,521 in confirmed outgoing supplier payments. This run widened its window to the 7-day catch-up cap (last successful run was 2026-09-08) — the 2026-09-08→09-11 span remains uningested.
- **Bookkeeper**: No data, same standing QBO/Intuit connector gap as every run since 2026-07-26.
- **Notion**: Cold start (no prior `notion.json` within 7 days) — 4 recently-won Titan Projects and the latest meeting row were seeded into the snapshot but not emitted as new items, per the earned-relevance rule. Two QA work orders closed 2026-09-16 (Jay Ventura — Major, $250; Sowmya — Minor deficiency, $250 goodwill on an already-paid job). Tactical Tasks backlog remains large (153 of 210 open rows past threshold); only the 10 stalest are itemized, the rest rolled up.
- **Meta Ads**: Only "Flooring Problems Campaign" is delivering (the other three remain paused with no budget); yesterday's spend was under the $50 anomaly-check floor so wasn't compared to the 7-day baseline, but CPL ($16.23) tracks in line with it (~$16.81 over the trailing week).

**Sources missing today**
- GHL — error: MCP server tools not attached to this session despite valid `.mcp.json` config and `.env` credentials (`GHL_PIT_TOKEN`, `GHL_LOCATION_ID` both present). Re-run once tool access is restored.
- Bookkeeper — error: no QuickBooks/Intuit MCP connector configured (11th consecutive failed run since 2026-07-26).
- No run-ledger entry exists on `main-agents` for 2026-09-09 through 2026-09-17. Cross-checks (vault daily notes exist for every one of those dates; GHL/meta-ads/outlook ingest agents each independently confirmed real runs on unmerged session branches) show this is the known branch-isolation artifact, not genuinely missed days.
