## Daily Brief — 2026-08-15

**Needs attention today**
- **GHL ingest FAILED** — session tool-provisioning gap (mcp__ghl__* bindings missing, not a GHL outage; endpoint confirmed reachable). Today's brief is missing its primary source: no leads/opportunities/appointments/conversations pulled, no workflow-drift check ran. Re-run once bindings are restored.
- Dang Associates needs the Hold-Co T183/OAR forms signed "asap" plus a combined YE2025 invoice — part of the ongoing CRA-discrepancy thread.
- CRA sent 3 notices that Titan's books/mailing/physical address of record changed — verify this was authorized before it becomes a filing problem.
- Prospect Sri (2160 Peachtree Lane) is at the Titan showroom **today, 11am–12:30pm** to finalize documentation and warranty paperwork.
- Frontier Grp (Lakeview Golf Course GC): route future quotes to new contact Jack Wu, not Eljona Muzha.
- 76 of 137 open Tactical Tasks are stale (up from 132/? on 2026-08-14) — flagged 4 days running now (7-31, 8-08, 8-14, today); needs a batch triage pass, not another daily flag.
- Bookkeeper (QuickBooks) ingest FAILED — 5th+ consecutive day, connector still unconfigured.

**Numbers**
- GHL: error — no data (tool-provisioning gap)
- Outlook: 26 scanned, 7 kept (3 admin/2 high, 2 customer, 2 supplier), 0 unanswered customer, 0 bounces
- Bookkeeper: error — no data (QBO connector unconfigured)
- Notion: 0 new won projects, 1 open work order (minor), 2 payments totaling $3,878.63 CAD, 76 stale tactical tasks, 0 new meetings
- Meta Ads: $45.73 spend, 1 lead, $45.73 CPL, 1 active campaign, 0 flagged ads

**By source**
- **GHL** — No data this run; a session configuration gap, not a platform issue (GHL_PIT_TOKEN/location present, endpoint reachable, tool bindings simply weren't granted to the subagent). Treat this brief as missing its backbone source until re-run.
- **Outlook** — Two high-priority admin threads: Dang Associates' YE2025 tax filing/signature request and three CRA address-of-record-change notices, both continuing from 2026-08-14. On the customer side, the Peachtree Lane prospect (Sri) is in-showroom today, and Frontier Grp wants quotes redirected to Jack Wu going forward. No unanswered customers, no bounces.
- **Bookkeeper** — No data; Intuit/QuickBooks MCP connector still not configured, 5th+ consecutive failed day. Needs connector setup before it can report again.
- **Notion** — Quiet on wins/meetings (all reported yesterday). One minor deficiency work order opened (Vic Montero, contractor notified). $3,878.63 CAD across 2 payments, both under the attention threshold. The stale Tactical Tasks backlog keeps growing (76 now) and has been flagged repeatedly without action — worth a dedicated sweep rather than continued daily noting. A registry column-name mismatch (`qa_work_orders.select_columns`) is still unfixed from yesterday.
- **Meta Ads** — Light spend day: $45.73 on the one active campaign (Flooring Problems Campaign), 1 lead. CPL ran ~2.9x the 7-day baseline but stayed under the $50 minimum-spend floor for anomaly flagging, so it's contextual only — worth watching if lead volume stays low.

**Sources missing today**
- **GHL** — status: error. mcp__ghl__* tool bindings not provisioned to the ingest subagent this run (server config and credentials confirmed present/reachable). Not a GHL outage — a session issue. Re-run once bindings are restored.
- **Bookkeeper** — status: error. QuickBooks/Intuit MCP connector not configured (5th+ consecutive day).

All other sources (Outlook, Notion, Meta Ads) reported ok.
