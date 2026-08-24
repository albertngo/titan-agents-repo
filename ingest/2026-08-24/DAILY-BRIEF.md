## Daily Brief — 2026-08-24

**Needs attention today**
- Two unanswered customer emails, both time-sensitive: 2160 Peachtree Lane (job starts Aug 27, no reply since Aug 22) and Sabrina/9 Midnight Lane Brampton (payment already sent, date unconfirmed since Aug 18). Reply today.
- GHL ingest is down: the `ghl` MCP server is stuck on "Pending approval" (needs a human to run `claude` interactively and approve it). This extends the GHL blind spot to 10 days (2026-08-15 → 08-24) — leads, pipeline, and conversations are currently invisible to this brief.
- Blue Ant Media says the Fall Home Show interim payment is overdue and wants it paid now via the invoice's Pay Now link (info@, Aug 21) — amount not in the email body, check the attached invoice.
- Bookkeeper (QuickBooks) ingest has now failed 8 consecutive runs (since 2026-07-26) — no QBO/Intuit MCP connector is configured. This is an unresolved setup gap, not a transient outage.
- Make.com's "Website Inquiry Ingester" scenario errored on Aug 19 — it kept running but may be silently dropping inbound website leads; worth a manual check of its run history.
- Notion: 92 open Tactical Tasks are now past their staleness threshold, up from 76 on 2026-08-14 — dominated by "Update POS Price List" (34) and "Create Gift Box" (19). Flagged on four consecutive runs now; worth a batch triage pass.
- An unverified account statement claiming a Titan balance arrived from "Sidco Global Trade" via a personal Gmail address (not a known vendor domain) — verify before trusting or paying anything against it.

**Numbers**
- GHL: **error** — no data (MCP pending approval).
- Outlook: 97 scanned, 7 customer / 3 supplier / 20 admin, 2 unanswered customer, 1 bounce.
- Bookkeeper: **error** — no data (connector not configured).
- Notion: 92 stale tactical tasks, 0 new won projects (cold-start, 5 silently seeded), 0 open work orders.
- Meta Ads: $353.63 spend, 29 leads, $12.19 CPL (Aug 17–23; below the $17.66 prior-week baseline).

**By source**

*GHL* — Failed. The `ghl` MCP server requires a one-time interactive approval this session can't grant; no leads, opportunities, appointments, or conversations were pulled. No backfill attempted. See ingest/2026-08-24/ghl.json.

*Outlook* — OK, catch-up run (7-day window; last successful run was 10 days ago, days 08-15–08-17 still uncovered). Two high-priority unanswered customer threads (above) plus the overdue Blue Ant Media invoice and the Make.com automation error. A statement from "Sidco Global Trade" (unverified sender) also needs a look before it's acted on.

*Bookkeeper* — Failed, 8th straight run. No QBO/Intuit MCP connector configured; $0 payments/overdue-invoices/uncategorized reflect no data pulled, not a true zero.

*Notion* — OK, cold-start (last snapshot 10 days old). 5 projects won in the window (~$21.9k combined: Gina Martino, Jay Ventura, Sonia Rocha, Sabrina Agard, Glendy Chang) were seeded silently per the "earned relevance" rule, not surfaced as new items. Main flag is the growing stale-tactical-task backlog (above); 3 of the 5 won projects are also missing an Opportunity ID and won't cross-reference against GHL.

*Meta Ads* — OK. $353.63 spend / 29 leads / $12.19 CPL over Aug 17–23, beating the prior-week $17.66 CPL baseline. Account healthy, no disapprovals. An extra $148.06 spend / 6 leads from Aug 14–16 falls in a blind spot outside both this window and the baseline — not counted anywhere; may need a manual backfill entry to avoid undercounting month-to-date.

**Sources missing today**
- `ghl`: status `error` — MCP server pending approval, not reachable this run.
- `bookkeeper`: status `error` — no QuickBooks/Intuit MCP connector configured (8th consecutive failure).
- No run at all on: 2026-08-15, 2026-08-16, 2026-08-17, 2026-08-18, 2026-08-19, 2026-08-20, 2026-08-21, 2026-08-22, 2026-08-23 (9-day gap in the run ledger between 2026-08-14 and today).
