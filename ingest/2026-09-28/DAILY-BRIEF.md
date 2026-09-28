## Daily Brief — 2026-09-28

**Needs attention today**
1. **Suspected payment-redirect fraud** — `mississauga@triforestflooring.com` emailed info@ (2026-09-23) claiming Triforest changed its banking details and asking Titan to update remittance records. Classic BEC pattern. Verify by phone with a known Triforest contact before touching any payment detail. Nothing acted on.
2. **Julie Ann Ohlman** — won project ($9,819) needs its 35% deposit confirmed landed before the crew is dispatched.
3. **Vic Montero** — underpad installation defect raised mid-August; Albert's promised 2026-08-28 follow-up never happened until a generic email today. Customer is still owed a resolution/deficiency list.
4. **Moe Nadeem** — stair-repair warranty claim unanswered >24h (since 2026-09-25 evening); he's asking Albert to confirm the Oct 7 repair date directly.
5. **Two likely phishing/malicious-attachment emails** — blank "invoice"/"invice" from `luxevistaconstruction@gmail.com` to albert@ and info@ (09-28), and a garbled "Xerox scan" sender to info@ (09-24). Don't open either attachment.
6. **Tactical Tasks List backlog worsening** — 194 of 248 open rows (~78%) now stale, up from 109/186 on the last comparable run (2026-09-08). Oldest is 175 days ("Call For Balance (Naqib)"). Overdue for a batch triage pass.
7. **Bookkeeper still blind** — no QuickBooks/Intuit MCP connector configured since 2026-07-26. Cash-in, overdue AR, and uncategorized transactions are unknown, not zero, for today.

**Numbers**
- GHL: 107 leads (24 hot/40 warm/21 cold/2 unqualified/4 stale), 2 new, 0 won, 1 unanswered conversation, 0 appointments booked, 8 pipeline moves, 47 drift findings, 11 untagged in queue.
- Outlook: 125 scanned (63 albert@, 53 info@, 16 pourya@, 3 mike@) — 3 customer, 20 supplier, 23 admin, 79 noise, 2 unanswered customer, 0 bounces.
- Bookkeeper: **error** — no data (QBO/Intuit MCP connector not configured; failing since 2026-07-26).
- Notion: 0 new won projects flagged today (cold-start seeded 2 from the last week silently), 0 work orders in error, 1 completed, 1 payment ($3,500), 194 stale tactical tasks, 0 new meetings.
- Meta Ads: $341.23 spend, 23 leads, $14.84 CPL, 1 active campaign, 0 flagged ads.

**By source**
- **GHL**: 2 new leads, 1 won-project deposit to confirm (Julie Ann Ohlman), 8 contacts with real two-way contact left untagged, and 17 Meeting-scheduled contacts (up to 99.9 days silent — Maria Wildfang worst) with no follow-up sequence. Parmjit Dhaliwal's day-5 quote follow-up silently didn't fire because she enabled DnD two days before it went out. Ulupi Babu and Richard Harris are the most overdue `stale_approaching` leads with no tag yet. A 16-opportunity STORE pipeline data-quality gap (status never flipped on old Closed rows) persists.
- **Outlook**: Top item is the suspected Triforest banking-fraud email (above). Also unanswered: Moe Nadeem's stair-repair claim and a 6-day-old website lead (`ezrareyes@foodmz.com`) with no reply found. Fall Home Show 2026 exhibitor-badge registration closes Oct 2.
- **Bookkeeper**: No data — standing connector gap since 2026-07-26; Finance department stays blocked until an Intuit QBO MCP server and credentials are added.
- **Notion**: Clean QA work-order queue (1 completed, none in error). Project Status Meeting cadence appears broken — last logged meeting was 2026-09-02, 26 days ago with nothing since; worth checking whether meetings are still happening but not being logged. Tactical Tasks backlog is the standing item (above).
- **Meta Ads**: Account healthy — Flooring Problems Campaign is the only active spender, CPL in line with the recent baseline, no disapproved/flagged ads. A 13-day ad-performance data gap (2026-09-08 to 2026-09-20) could not be backfilled within this run's budget.

**Sources missing today**
All sources reported (bookkeeper reported with `status: error`, per above — not a missing file).

Note: the local ingest history here shows a large gap between 2026-09-08 and today with no `ghl.json`/`outlook.json`/`meta-ads.json`/`notion.json` on this branch. Cross-checked against `titan-vault/01_daily/` (which has a daily note for every date from 2026-09-09 through 2026-09-27, each citing real per-source numbers): the daily-ingest funnel did run on those days, but its outputs landed on session branches never merged into `main-agents` — a branch-isolation artifact, consistent with the same finding recorded in the 2026-09-08 run-ledger entry, not an actual missed run. Two real, narrower gaps remain and could not be recovered within today's run: Outlook/Meta-Ads data for roughly 2026-09-09 through 2026-09-20 (both agents capped their catch-up pull at 7 days) — a manual wider backfill would be needed to see that window.
