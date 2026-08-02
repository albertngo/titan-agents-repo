## Daily Brief — 2026-08-02

**Needs attention today**
1. [Therese Gomes deposit](https://app.gohighlevel.com/v2/location/4BwjVRlyDCR4ZRdcSrFR/contacts/detail/OT0kdd7OrXCpNI6Hmb70) — won $11,300 (Notion shows $12,769 full contract, $3,000 received so far). Deposit is arriving in installments due to an e-transfer daily limit; confirm the full 35% lands before scheduling install crew/materials.
2. [17 opportunities (~$87,296)](https://app.gohighlevel.com/v2/location/4BwjVRlyDCR4ZRdcSrFR/opportunities/list) auto-abandoned in one batch sweep today — ages (~66 days) don't match the documented 80-day threshold. Confirm against the live GHL automation before treating these warm quotes as dead.
3. [Ben, Burlington](https://app.gohighlevel.com/v2/location/4BwjVRlyDCR4ZRdcSrFR/contacts/detail/Jn1HvMRPtzfdhFiZ7kyz) — 127.9 days in Meeting-Scheduled (4x threshold), never tagged stale. Automation appears to have skipped this one.
4. [Natalee](https://app.gohighlevel.com/v2/location/4BwjVRlyDCR4ZRdcSrFR/contacts/detail/pLPwvh4QMjJtRt1aM5cF) — call-queue tagged with no `lead:*` tag since 2026-03-08 (147 days). Oldest uncategorized contact found today.
5. [Samriti Khanna](https://app.gohighlevel.com/v2/location/4BwjVRlyDCR4ZRdcSrFR/contacts/detail/nRKthDez64COjA0iyWPg) — in-home visit cancelled 2026-06-26, never rescheduled. 38 days of automated-only nurture since.
6. Outlook ingest has now failed 5 consecutive run-days (07-26, 07-27, 07-28, 07-31, 08-02) — no M365 connector configured. Inbox is a growing blind spot; any unanswered customer email is currently invisible to this brief.
7. Notion Tactical Tasks staleness jumped from 16 to 51 today, driven by a batch of "In progress" rows dated April–June. Confirm whether this is a real backlog or a status-transition artifact, plus triage recurring duplicate clusters (Update POS Price List, Create Gift Box For, No Opportunity ID Found, Add Tags in CCAM).

**Numbers**
- GHL: 273 leads, 3 new, 7 unanswered conversations, 1 won ($11,300), 9 drift findings.
- Outlook: error — 0 scanned (5th consecutive failed run).
- Bookkeeper: error — $0 (QuickBooks MCP connector not configured).
- Notion: 1 new won project ($12,769), 2 open work orders (both minor, contractor notified), 1 payment received ($3,000), 51 stale Tactical Tasks.

**By source**
- **GHL** — 3 new Meta-ad leads (Sukhjinder Virdi, John Keay, Quel Molina), all still early/normal priority. The big story is the Therese Gomes win ($11,300, deposit installments in progress) alongside a 17-opportunity, ~$87K auto-abandon batch whose timing doesn't match the documented threshold. Drift findings: 4 leads stuck untagged in the call queue (Natalee worst at 147 days), 3 hot/meeting-stage leads never tagged stale despite blowing past thresholds (Ben, Charles Crooks, Jly), and Samriti Khanna's cancelled meeting with no reschedule.
- **Outlook** — Ingest failed again: no Outlook/M365 MCP connector or Graph credentials available in this session. This is the 5th straight failed day; the inbox has been unscanned for over a week of run-days.
- **Bookkeeper** — Ingest failed: no QuickBooks/Intuit MCP connector configured (`.mcp.json` only defines `ghl`). No transaction, receipt, or invoice data pulled today.
- **Notion** — One new won project, [Therese Gomes, Cambridge](https://app.notion.com/3af596a4505f81509ffeef9c6f4631d0) ($12,769, sales: Pourya Lalee, no PM assigned yet) — matches the GHL win above. Two minor deficiency work orders opened and already routed to contractors (WO-Daria, WO-Arkadi Chmir). Tactical Tasks staleness spiked 16→51, mostly older "In progress" rows surfacing for the first time; worth a triage pass on the recurring duplicate-title clusters.

**Sources missing today**
- `outlook` — status: error. No Outlook/M365 MCP connector or Microsoft Graph credentials (`GRAPH_*`/`AZURE_*`) present. 5th consecutive failed run.
- `bookkeeper` — status: error. No QuickBooks/Intuit MCP connector configured in `.mcp.json`; no QBO credentials present.
