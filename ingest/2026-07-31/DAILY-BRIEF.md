## Daily Brief — 2026-07-31

**Needs attention today**
- **All 4 sources failed today — this is an outage report, not a quiet day.** No lead, opportunity, appointment, project, payment, or transaction data was pulled for 2026-07-31.
- **GHL: auth failure.** `$GHL_PIT_TOKEN` rejected with 401 "Invalid Private Integration token" on every call (verified via direct REST and via the MCP server). Rotate the PIT token in GHL (Settings > Private Integrations) and update the environment.
- **Outlook: 4th consecutive dark day** (2026-07-26, 07-27, 07-28, 07-31). No Outlook/M365 MCP connector or Graph credentials are attached to this session. Four days of customer/supplier/admin email are unscanned.
- **Notion: connector not wired.** `notion-ingest-agent`'s declared tools (`mcp__notion__*` / connector-prefixed variants) aren't reachable in-session; `.mcp.json` has no `notion` server entry. Titan Projects, QA Work Orders, Payments, Tactical staleness, and Meetings are all blind today.
- **Bookkeeper: no QuickBooks connector.** No QBO/Intuit MCP server configured, no credentials present. No transactions, receipts, or overdue invoices checked.
- **Ask:** these are four separate infrastructure gaps (one token rotation, three missing connectors), not a data-freshness issue. Nothing below can be trusted until they're fixed.

**Numbers**
- GHL: no data (auth failure)
- Outlook: no data (no connector, day 4)
- Bookkeeper: no data (no connector)
- Notion: no data (no connector)

**By source**
- **GHL** — Ingest could not authenticate; PIT token rejected account-wide. No leads, opportunities, appointments, or conversations retrieved.
- **Outlook** — No connector/credentials available. Zero items scanned; this is the fourth straight day this feed has been dark.
- **Bookkeeper** — No QuickBooks connector available. No transactions, receipts, or invoices checked.
- **Notion** — No connector reachable. All 5 tracked sources (Titan Projects, QA Work Orders, Master Payments Log, Tactical Tasks List, Project Status Meetings) were skipped before any query ran. Cross-day dedupe snapshot carried forward from 2026-07-28 (now 3 days stale) so tomorrow's diff won't be corrupted once the connector is restored.

**Sources missing today**
- ghl — status: error — 401 Invalid Private Integration token (auth/token rotation needed)
- outlook — status: error — no MCP connector / Graph credentials (4th consecutive day)
- bookkeeper — status: error — no QuickBooks MCP connector configured
- notion — status: error — no Notion MCP connector wired in this session
