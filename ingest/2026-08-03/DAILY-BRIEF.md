## Daily Brief — 2026-08-03

**Needs attention today**
- Therese Gomes' final payment on the $11,300 Cambridge win arrived under a different name (Joseph Raymond Gomes) — confirm receipt/reconcile before marking the project fully paid.
- QuickBooks ingest has failed 5 consecutive days (since Jul 26) — payments, overdue invoices, and uncategorized transactions are unknown for the whole window. Fix/reconfigure the QBO MCP connector before the backlog grows further.
- Outlook ingest was blocked today by this run's own egress proxy (403 on `graph.microsoft.com` CONNECT, all 4 mailboxes) — not an Outlook outage. Confirm the proxy allowlist before the next run so no mail is silently dropped.
- GHL follow-up automation looks inconsistent: 3 opportunities (Hingora, Kapoor, Satwinder Singh) were auto-abandoned well before their documented threshold, while 8+ Meeting-Scheduled opportunities — incl. Basil Da Souza (53d) and 7 others (97–138d) — sit open past 2x threshold with no follow-up. Worth a workflow check.
- 51 open Notion Tactical Tasks are now past their staleness threshold (up from 16 on Jul 31). Heavy repeats ("Update POS Price List" x18, "Create Gift Box For" x7) — batch triage or a process fix, not one-offs.
- 20 GHL leads have sat untagged in the call-queue over 24h (oldest 13 days) — intake categorization isn't keeping pace.
- 4 fresh inbound GHL contacts (WhatsApp stairs/hardwood estimate, a voicemail, 2 missed calls) have had zero response for 14–22 hours.

**Numbers**
- GHL: 6 new leads, 5 unanswered conversations, 7 pipeline moves, 0 won today, 20 untagged in queue, 45 drift findings.
- Outlook: 0 scanned (all 4 mailboxes) — ingest blocked, see above.
- Bookkeeper: unknown — QBO connector unavailable, no data retrieved.
- Notion: 1 new won project ($12,769.99 CAD), 2 payments logged ($4,500 CAD), 51 stale tactical tasks, 2 open QA work orders (0 in error).

**By source**
- **GHL** — 6 new leads, 7 pipeline moves, no wins today. Highest-priority item is the Therese Gomes payment-name mismatch on the Cambridge win. Workflow drift is the bigger theme: 20 untagged leads in queue, 2 likely categorization misses (Muhammad Hingora, Premlata Kapoor auto-abandoned despite real two-way contact), and an abandonment automation that fires early in some cases and not at all in others (Meeting-Scheduled backlog).
- **Outlook** — Ingest produced zero data; root-caused to a proxy/network-policy block on `graph.microsoft.com`, distinct from the known credential/access-policy failure modes. Last good data still runs through 2026-08-02 18:00; next successful run must widen its catch-up window so today isn't lost.
- **Bookkeeper** — 5th straight failed day; MCP connector for QuickBooks is not configured in this environment. No visibility into payments, overdue invoices, or uncategorized transactions since Jul 26.
- **Notion** — All 5 sources (Projects, QA Work Orders, Payments, Tactical Tasks, Meetings) reported ok. Headline: Therese Gomes' win recorded ($12,769.99), 2 e-Transfer payments from Joseph Raymond Gomes ($1,500 + $3,000, both under the $5,000 threshold), and a growing Tactical Tasks staleness backlog (51, up from 16 three days ago).

**Sources missing today**
- Outlook — `status: error`. Egress proxy returned 403 on CONNECT to `graph.microsoft.com` for all 4 mailboxes; token request to Microsoft succeeded, so this is a network-layer block, not expired credentials.
- Bookkeeper — `status: error`. QuickBooks/Intuit MCP server not registered in `.mcp.json` this session; 5th consecutive day of failure.
