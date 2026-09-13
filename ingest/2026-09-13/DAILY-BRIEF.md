## Daily Brief — 2026-09-13

**Needs attention today**
1. **GHL down all day** — `ghl` MCP server stuck at "Pending approval," never connected. Zero lead/opportunity/appointment/conversation visibility. Fix: run `claude` interactively in the repo and approve the server before the next run.
2. **MetCredit collections notice** on Titan's Rogers account, $449.77 + accruing interest, no reply on file — needs a pay/dispute decision soon.
3. **5 duplicate Notion "Project Won" rows** for one opportunity (Jeevan Ramkelawan, Mississauga, `Yxb43wEmjLr6EECSllPf`) fired within a 5-hour window on 09-11 — likely a duplicate-write bug; 4 stray pages need cleanup.
4. **2 new Major-severity work orders** (09-08) need contractor/PM follow-through: Jay Ventura (Other — closet hardwood/nosing) and Helena Toolsiedas (Warranty).
5. **titanfloors.ca WordPress admin email-change request** (09-12) with no obvious originating action — confirm legitimacy before it's approved; landed alongside several other account-security notices.
6. **Payment ≥$5,000**: Ali Sohani, $6,855.19 e-Transfer received 09-08.
7. **Tactical Tasks backlog**: 109 of 195 open rows (~56%) stale, oldest 159 days — flagged repeatedly since 07-31, still no triage pass.

**Numbers**
- GHL: error — no data (MCP server pending approval).
- Outlook: 27 items (9 customer, 11 supplier, 7 admin), 0 unanswered customer, 0 bounces. 120h/144h catch-up window (last ok run 09-08).
- Bookkeeper: error — no data (no QuickBooks connector, 11th consecutive failed run since 07-26).
- Notion: partial — 9 new won projects ($41,975.58), 2 open work orders, 1 completed, 8 payments ($21,647.11), 109 stale tactical tasks, meetings unchecked (Notion query-limit hit).
- Meta Ads: $44.85 spend, 3 leads, $14.95 CPL (7-day baseline $13.45 — no anomaly), 1 active campaign, 0 flagged ads.

**By source**
- **GHL**: No data — MCP server pending interactive approval, same failure class as bookkeeper. This is the brief's primary usual driver, so lead/pipeline visibility is fully blind today.
- **Outlook**: 27 items across 4 mailboxes, widened to a 120h/144h catch-up window to bridge the gap since 09-08. Highest-priority: the MetCredit collections notice and the unconfirmed WordPress admin email-change request (both above); also an answered Oakville complaint, an active tile-warranty case in progress, a Printam proof-approval unanswered since 09-08, and recurring Make.com automation failures since 09-11 (Notion Project Blocker, Project Won celebration scenarios).
- **Bookkeeper**: No data — QuickBooks/Intuit MCP connector still unconfigured. Cash-in for today is unknown, not zero.
- **Notion**: 9 new won projects worth $41,975.58 (the Jeevan Ramkelawan duplicate-row issue above is the standout anomaly), 2 new Major work orders opened 09-08, Ali Sohani's $6,855.19 payment, and the persistent 109-row stale-tactical-task backlog. `project_status_meetings` couldn't be queried this run (workspace hit its Notion API usage cap) — new-meeting count is unverified. Config drift in `notion-ingest-sources.json`'s QA-Work-Orders column names remains unresolved since 08-14.
- **Meta Ads**: $44.85 spend, 3 leads, $14.95 CPL — in line with the 7-day $13.45 baseline, no anomaly. Recurring note: lead-like conversion action types outside the script's documented set keep appearing (since 08-31) with no count discrepancy — flagged again as a script-extension candidate, not hand-patched.

**Sources missing today**
- GHL: `status: "error"` — MCP server pending approval, never connected.
- Bookkeeper: `status: "error"` — no QuickBooks/Intuit MCP connector configured (11th consecutive failed run since 2026-07-26).
- Notion: `status: "partial"` — 4 of 5 sub-sources ok; `project_status_meetings` failed on a Notion API usage-limit error.
