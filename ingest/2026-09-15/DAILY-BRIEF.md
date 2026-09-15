## Daily Brief — 2026-09-15

**Needs attention today**
- **GHL fully missing** — MCP tools not bound this session; zero lead/pipeline/appointment/conversation coverage for Sales today. Re-run with the `ghl` server attached.
- **Bookkeeper still blocked** — 11th consecutive failed run since 2026-07-26 (no QBO/Intuit MCP connector configured). All payments/overdue/uncategorized figures unknown.
- **2 open customer complaints from Outlook** — [srisowm@gmail.com](mailto:srisowm@gmail.com) (2160 Peachtree Lane, Oakville: paid in full, says work isn't finished) and [virayn@gmail.com](mailto:virayn@gmail.com) (5301 Churchill Meadows: deficiency/crew-quality pushback). Both replied to, worth confirming actually resolved.
- **MetCredit collections notice** re: a Rogers Communications account, emailed albert@ 2026-09-10 — no reply found; verify it isn't heading further into collections.
- **9 new won projects since 2026-09-08** ($41,975.58 CAD total), incl. [Jeevan Ramkelawan — Mississauga](https://app.notion.com/3d8596a4505f8147abdac3273b573826) and [Brooks Persad — Mississauga](https://app.notion.com/3d8596a4505f81c3bfe6cf95f324de0c) (Description names a different person, "Judy Ramkelawan," at the same address as another new row — check for a duplicate/mis-entry).
- **Tactical Tasks backlog: 123 of 200 open rows stale (61.5%)**, up from 58.6% on 09-08 — oldest is 162 days ("Call For Balance (Naqib)"). Overdue for a batch triage pass.
- **Notion Project Status Meetings query is hard-blocked** by a workspace plan quota (not transient) — meeting coverage unknown this run, not confirmed clear.

**Numbers**
- GHL: error — no data (MCP not bound).
- Outlook: 31 items counted (12 customer, 8 supplier, 11 admin) of 152 scanned across 4 mailboxes; 0 unanswered customer threads.
- Bookkeeper: error — no data (no QBO connector).
- Notion: 9 new won projects ($41,975.58 CAD), 1 open work order (0 in error), 6 payments totaling $9,383.04 CAD, 123 stale tactical tasks, meetings unknown.
- Meta Ads: $363.66 CAD spend, 28 leads, $12.99 CPL, 1 active campaign, 0 flagged ads.

**By source**
- **GHL** — Full outage this run: the `ghl` MCP server wasn't bound to the session, so no leads, opportunities, appointments, or conversations were pulled. Credentials are confirmed present in `.env`; this is a tool-binding gap, not a config problem. Treat today's brief as having zero Sales/GHL visibility.
- **Outlook** — Ran a 7-day catch-up (last success was 2026-09-08) across all 4 mailboxes with no gaps. Two active customer complaints and a MetCredit collections notice on a Rogers account need a status check; a CRA "New mail" notice to albert@ also looks unopened.
- **Bookkeeper** — Full outage again: no QuickBooks/Intuit MCP connector exists in this environment (`.mcp.json` only has `ghl`). This is the 11th straight failed run since 2026-07-26 — a standing setup gap, not an outage, per CLAUDE.md's Finance department status.
- **Notion** — 4 of 5 sub-sources ok; Project Status Meetings failed twice on a genuine workspace quota. 9 new won projects landed over a 7-day gap (no local notion.json existed 09-09 through 09-14), largest single-window count on record — two rows are missing Name/Opportunity ID/Sales Person (recurring data-entry gap). Tactical Tasks staleness keeps climbing and is overdue for triage.
- **Meta Ads** — Widened to a 7-day pull (2026-09-08 through 09-14) to cover the same branch-isolation gap Outlook and Notion hit. Only "Flooring Problems Campaign" delivered ($50/day budget), CPL improved slightly vs. the prior 7-day baseline (~$14.00 → $12.99), no disapprovals or delivery issues.

**Sources missing today**
- GHL — error (MCP tools not bound this session).
- Bookkeeper — error (no QBO/Intuit MCP connector configured; 11th consecutive failure).
- Notion — partial (Project Status Meetings sub-source failed on a workspace quota; the other 4 sub-sources reported ok).
- No run at all on: none — 2026-09-01 through 2026-09-14 all have runs recorded, either in this branch's ledger or confirmed via unmerged session branches and vault `01_daily/` notes (see run-ledger note for today).
