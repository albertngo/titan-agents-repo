## Daily Brief — 2026-09-12

**Needs attention today**
1. **Three of five sources down today** — GHL (`mcp__ghl__*` tools unreachable this session, a wiring gap, not bad credentials), Outlook (egress proxy returned 403 on CONNECT to `login.microsoftonline.com`, unscanned since 09-08), Bookkeeper (no QuickBooks connector, 11th consecutive failed run since 2026-07-26). No lead/opportunity/conversation or mailbox visibility today.
2. **5 duplicate Notion "Project Won" pages** for the same opportunity (Jeevan Ramkelawan, `Yxb43wEmjLr6EECSllPf`) fired ~1.5h apart on 09-11 — likely a repeated webhook; dedupe collapsed it to one item here, but the 4 duplicate pages are still live in Notion and need manual deletion.
3. **Helena Toolsiedas [WARRANTY]** won-project row has no Name/Value/Sales Person — worth confirming this shouldn't be a QA Work Orders entry instead.
4. **Tactical Tasks List: 109 of 195 open rows (~56%) are stale**, oldest 159 days ("Call For Balance (Naqib)", in progress since 04-06) — flagged repeatedly since 2026-07-31, still awaiting a batch triage pass.
5. **Meta Ads window widened to 4 days** (09-08→09-11) to close an ingest gap: $201.10 spend, 16 leads, $12.57 CPL, in line with the 7-day baseline — flagged as possibly a branch-isolation artifact rather than a real gap, unconfirmed.
6. **Notion source config drift**: `notion-ingest-sources.json` still has stale QA Work Orders column names and an invalid `error_statuses` entry, first flagged 2026-08-14, still uncorrected.
7. **3 of 9 new Notion wins missing Opportunity ID/Sales Person** (Mien/David - Oakville, Helena Toolsiedas [WARRANTY], Gustavo - Oakville Tiles) — won't cross-reference cleanly against GHL once it's restored; recurring gap since 08-31.

**Numbers**
- GHL: error — no data (MCP tools unreachable).
- Outlook: error — no data (proxy blocked OAuth; 0 mailboxes scanned).
- Bookkeeper: error — no data (no QuickBooks connector).
- Notion: 9 new won projects ($41,975.58), 1 payment ($3,000.00), 109 stale tactical tasks, 0 new meetings.
- Meta Ads: $201.10 spend, 16 leads, $12.57 CPL, 1 active campaign, 0 flagged ads (4-day window).

**By source**
- **GHL**: Ingest failed entirely — no `mcp__ghl__*` tool was reachable this run despite valid-looking credentials in `.env`; a session-wiring gap distinct from a credentials problem. Zero leads/opportunities/appointments/conversations/drift data for today. Re-run once GHL MCP connectivity is confirmed restored.
- **Outlook**: Failed at the OAuth token step — egress proxy returned 403 on CONNECT to `login.microsoftonline.com`. Zero mailboxes scanned (albert/info/pourya/mike); unaudited window is now 2026-09-08 → 2026-09-12 and growing. Needs the session's egress allowlist widened to include `login.microsoftonline.com` and `graph.microsoft.com`.
- **Bookkeeper**: No QuickBooks/Intuit MCP connector configured — 11th consecutive failed run since 2026-07-26. All payments-received, overdue-invoice, and uncategorized-transaction figures remain unknown; Finance stays blocked per CLAUDE.md.
- **Notion**: A 4-day catch-up window (Sep 5–11) surfaced 9 new won projects ($41,975.58 total) and 1 payment ($3,000.00). Biggest flags: [[Jeevan Ramkelawan]]'s Project Won page duplicated 5x by a repeated webhook on 09-11 (manual cleanup needed), and the Helena Toolsiedas [WARRANTY] row possibly miscategorized. Tactical Tasks backlog holds at 109 stale rows of 195 open (total open rows grew from 186→195 since 09-08).
- **Meta Ads**: 4-day catch-up window (Sep 8–11) — $201.10 spend, 16 leads, $12.57 CPL, in line with the 7-day baseline ($12.80 CPL). One active campaign (Flooring Problems Campaign), no disapproved or flagged ads.

**Sources missing today**
- GHL: `status: "error"` — `mcp__ghl__*` tools not reachable this session (confirmed via tool search; a session-wiring gap, not a credentials problem).
- Outlook: `status: "error"` — egress proxy 403 on CONNECT to `login.microsoftonline.com`; unscanned since 2026-09-08 (~4-day gap, still within the 7-day catch-up cap).
- Bookkeeper: `status: "error"` — no QuickBooks/Intuit MCP connector configured (11th consecutive failed run since 2026-07-26).
- Notion and Meta Ads reported `status: "ok"`.
