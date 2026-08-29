## Daily Brief — 2026-08-18

**Needs attention today**
- **GHL ingest failed** — `ghl` MCP server unreachable this session (tools not registered despite config present). No leads/pipeline/appointments/conversations pulled today — re-run once MCP connectivity is restored.
- **Bookkeeper ingest failed** — QuickBooks/Intuit MCP connector still unconfigured (open gap since at least 2026-07-26, now 4+ weeks running). Needs setup, not a re-run.
- **2 customers unanswered >24h** (Outlook): Felix D'Souza (combined flooring/stair/baseboard quote, asked 2026-08-16) and Ryan Langen, 301 Markham St #404 (arrival-time question, asked 2026-08-16 evening — may be resolved by phone already).
- **Active roof leak into showroom** (PCC296 / 1060 Britannia Rd) — MRCM sending a contractor to inspect, but warned cost falls to Titan if not roof-related. Needs follow-up on scheduling/cost exposure.
- **Dang Associates**: Hold-Co T183/OAR forms need Albert's signature ASAP to close YE2025 filing; separate YE2025 accounting-fee invoice awaiting review/payment (amount in attachment).
- **Notion "David Ngo" won project** has no populated fields (Opportunity ID, Name, City, Address, Contact, Sales Person, Value all blank/$0) — can't cross-reference or value it; verify data entry.
- **82 stale Tactical Tasks** (up from 132→146 open, 82 past threshold) — flagged 4th run in a row (07-31, 08-08, 08-14, today); worth a batch triage pass.

**Numbers**
- GHL: error — 0 items (MCP unreachable)
- Outlook: 18 items (5 customer, 5 supplier, 7 admin, 1 bounce), 2 unanswered customers, 27 noise skipped
- Bookkeeper: error — 0 items (connector unconfigured)
- Notion: 50 items (1 new won project, 82 stale tasks flagged, 0 work orders, 0 payments, 0 new meetings)
- Meta Ads: $198.40 spend / 11 leads / $18.04 CPL (4-day catch-up window 08-14–08-17, not a single day)

**By source**
- **GHL**: No data — session-level MCP tool failure, not a GHL outage confirmed. Zero leads, opportunities, appointments, or conversations captured for 08-18.
- **Outlook**: 4 mailboxes scanned (albert@, info@, pourya@, mike@), catch-up window widened to 97h/121h to cover the 08-15–08-17 gap. Two customer threads unanswered >24h (Felix D'Souza, Ryan Langen). High-priority admin items: [Dang Associates filing/invoice](https://outlook.office365.com/owa/?ItemID=AAMkADliNWJmMjVmLTA2YzctNGRlMC1iMmVlLTkyNjdhZjBmYzUwZABGAAAAAABHf1EfuF%2FiToI4%2BcF0d6pDBwDbPhKQg8c%2FRp%2Bc7qfEdjkNAAAAAAEMAADbPhKQg8c%2FRp%2Bc7qfEdjkNAAKqr%2B%2FOAAA%3D&exvsurl=1&viewmodel=ReadMessageItem), [roof leak](https://outlook.office365.com/owa/?ItemID=AAMkADliNWJmMjVmLTA2YzctNGRlMC1iMmVlLTkyNjdhZjBmYzUwZABGAAAAAABHf1EfuF%2FiToI4%2BcF0d6pDBwDbPhKQg8c%2FRp%2Bc7qfEdjkNAAAAAAEMAADbPhKQg8c%2FRp%2Bc7qfEdjkNAAKqr%2B%2FMAAA%3D&exvsurl=1&viewmodel=ReadMessageItem), and a Prosol price-increase notice (feeds Airtable catalogue workflow, review before next order).
- **Bookkeeper**: No data — QBO/Intuit MCP server not configured in `.mcp.json`. Same failure every recent run; this is a setup task, not transient.
- **Notion**: 1 new won project ([David Ngo](https://app.notion.com/3bd596a4505f80ccbf6ef1f653d0c65b), fields blank — needs verification), 0 work orders/payments/meetings in window, 82/146 open Tactical Tasks stale (oldest 133 days). Registry file still has stale QA Work Order column names (flagged since 08-14, adjusted live again).
- **Meta Ads**: Flooring Problems Campaign is the only active campaign; $198.40 spend, 11 leads, $18.04 CPL over the 4-day catch-up window — above the 7-day baseline ($16.64) but under the 2x anomaly threshold. Account active, no disapproved/flagged ads. Repeat note: raw lead-like conversion action types outside the documented set still match counted leads exactly — candidate to extend `LEAD_ACTION_TYPES`.

**Sources missing today**
- `ghl`: status `error` — GHL MCP server tools unavailable this session.
- `bookkeeper`: status `error` — QuickBooks/Intuit MCP connector not configured.
- No run at all on: 2026-08-15, 2026-08-16, 2026-08-17
