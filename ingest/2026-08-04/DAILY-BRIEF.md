## Daily Brief — 2026-08-04

**Needs attention today**
- Vic Montero is demanding the install now start Tuesday Aug 11 (Titan's last offer was Aug 27/28) and says he'll call tomorrow — needs an explicit written answer today.
- Shaker Matti, a brand-new ASAP lead (1000+sf laminate, Brampton), called back 38 minutes after automated outreach and nobody answered — callback needed before he cools off.
- Outlook ingest is down for a 2nd straight day — proxy is blocking `graph.microsoft.com` (403 at egress). Blind spot since 2026-08-02T18:46 is now ~38h+ and growing; needs an admin to allow the host through the session's egress allowlist.
- Bookkeeper/QuickBooks ingest has no connector configured (`.mcp.json` has no QBO/Intuit entry) — zero financial visibility today; needs the MCP server added/repaired.
- 31 of 44 `stale_lead`-tagged GHL opportunities have passed 2x their stage's stale threshold (the documented auto-abandon point) and are still open — 24 of the 31 sit in *Meeting (Scheduled)*, echoing the Postponed-stage gap from 07-31 and now looking like a systemic automation failure.
- Janny Huynh's win got created as 5 duplicate rows in Notion Titan Projects within 17 minutes — likely a retry loop in the GHL→Notion win automation; 4 stray rows need manual cleanup.
- Ben (Burlington)'s Meeting-scheduled follow-up window is still negative (-69 days), a workflow-timing bug flagged 07-31 and still unresolved 4+ days later.

**Numbers**
- GHL: 5 new leads, 3 unanswered conversations, 1 appointment booked, 0 won today, 48 workflow-drift findings, 21 contacts untagged 24h+ in queue.
- Outlook: **error** — 0 items scanned (egress blocked, see above).
- Bookkeeper: **error** — 0 transactions/receipts/invoices (no connector configured).
- Notion: 2 new won projects ($12,769.00 CAD), 3 payments ($5,880.00 CAD), 51 stale tactical tasks (up from 16 on 07-31), 0 new meetings.

**By source**
- **GHL** (ok): 5 new leads including two hot ASAP laminate jobs (Tejinder Jammu, Shaker Matti) and a referral win-in-progress (Janny Huynh, Oakville, in-home visit today 5:15pm). Vic Montero's install-date dispute is the top item needing a same-day written reply. Drift findings are worsening across the board — untagged queue backlog (21, up from 17), the systemic 2x-threshold auto-abandon gap, and a repeating DND-opt-out pattern on the automated nurture SMS (3rd occurrence: Shaheen Sheikh, Baba, now Muhammad Butt).
- **Outlook** (error): No mailboxes could be scanned — Graph API calls were rejected at the outbound proxy (403, policy denial), not a Microsoft outage or credentials issue. This compounds the existing 07-26→07-31 coverage gap; the next successful run must widen its catch-up window back to 2026-08-02T18:46.
- **Bookkeeper** (error): No QuickBooks connector is configured in this environment at all, so today produced no payment, invoice, or receipt data. Distinct from a platform outage — this is a setup gap.
- **Notion** (ok): Two new wins (Therese Gomes $12,769 Cambridge; Janny Huynh Oakville) and $5,880 in payments logged, none over the $5,000 single-payment flag threshold. The Janny Huynh row duplicated itself 5x in a 17-minute window — an automation bug worth checking. Stale tactical tasks jumped from 16 to 51 (42 Not-started, 9 In-progress, two over 100 days old) — worth a batch triage pass.

**Sources missing today**
- Outlook — error: outbound proxy blocked `graph.microsoft.com` (403 at CONNECT), 0 items retrieved.
- Bookkeeper — error: no QuickBooks/Intuit MCP connector configured, 0 items retrieved.
