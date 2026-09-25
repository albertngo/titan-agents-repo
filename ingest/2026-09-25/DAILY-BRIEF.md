## Daily Brief — 2026-09-25

**Needs attention today**
1. **Naveen Sharma (lead: hot)** — unanswered pricing question (8mm vs. current quote) sitting 16+ hours; he's mentioned a competitor quote. Reply before we lose him.
2. **Duplicate-send automation bug live now** — Arvind got a templated nurture SMS 3 minutes after declining a $14,477 opportunity ("gone with someone else"); same bug hit 5 other `lead: hot` contacts yesterday. Mark Arvind's opportunity lost, stop the sequence, and look at the automation.
3. **Suspected fraud: Triforest Inc. banking-change notice** to info@ (Sept 23) — classic vendor-email-compromise pattern; do not update any remittance details without phone verification. Titan has an active Triforest relationship. Still unresolved from yesterday.
4. **Manjinder Athwal's opportunity auto-abandoned after only 7 days** against the documented 28-day threshold — carries an `ai_qualify` tag that may be running its own undocumented cadence. Worth confirming with Albert.
5. **Tactical Tasks backlog worsening** — 179 of 236 open rows (76%) are now past their staleness threshold, up from 59% on 2026-09-08. Oldest is 172 days old. Overdue for a batch triage pass (flagged repeatedly since 07-31).
6. **Blue Ant Media / Fall Home Show final payment still unpaid** — booth/badge access will be blocked before the show. Still unresolved from yesterday.
7. **QuickBooks connector still broken** — 11th consecutive failed run since 2026-07-26. All payments-received, overdue-invoice, and uncategorized-transaction figures are unknown until an Intuit QBO MCP server is configured.

**Numbers**
- GHL: 116 leads (25 hot/38 warm/24 cold/2 unqualified/4 stale), 2 new, 9 unanswered conversations, 1 appointment, 1 pipeline move, 0 won today, 38 drift findings.
- Outlook: 138 scanned (67 albert@, 45 info@, 24 pourya@, 2 mike@) — 4 customer, 8 supplier, 9 admin, 3 unanswered customer, 0 bounces.
- Bookkeeper: unknown — source unreachable (error).
- Notion: 2 payments received ($2,587.70 CAD), 0 work orders touched, 179 stale tactical tasks, 0 new meetings logged.
- Meta Ads: $356.12 spend / 27 leads / $13.19 CPL over 2026-09-18–09-24 (window widened, see below), 1 active campaign, 0 flagged ads.

**By source**
- **GHL**: Quiet on wins (0 today) but busy on drift — 38 findings after exclusions, led by Maria Wildfang at 336% of the Meeting-Scheduled threshold (97 days silent). A completed 3m43s inbound call produced no tag/opportunity (categorization miss), and Miko Mesfin's voicemail from yesterday afternoon has no callback yet. Julie Ann Ohlman's 35%-deposit payment schedule went out Sept 23 — confirm it landed.
- **Outlook**: Mostly clean besides the fraud/phishing items above. Ezra Reyes (foodmz.com) asked about measurement/install timing on Sept 22 with no reply found in Sent Items. A "Xerox scan 9/24/2026" message from a spoofed sender is likely phishing — don't open it.
- **Bookkeeper**: No data — see Sources missing below.
- **Notion**: Cold-start run (no prior `notion.json` since 2026-09-08) — 5 won projects (~$53,502.74 CAD combined: Julie Ann Ohlman $9,819, Amica Whitby $24,668.24, Allison Hubson $0/deficiency, Rachita Saini $17,345.50, Moe Nadeem $1,670 warranty) and the last logged Project Status Meeting (Sept 2, 23 days old) were seeded into the snapshot rather than reported as fresh activity — worth a manual glance since tomorrow resumes normal day-over-day dedupe.
- **Meta Ads**: Healthy week — CPL ($13.19) beat the prior-week baseline ($16.82), no disapprovals, no account issues. Coverage gap below is the only flag.

**Sources missing today**
- **Bookkeeper**: `status: "error"` — no QuickBooks/Intuit MCP connector configured (11th consecutive failed run since 2026-07-26).
- No ledger entry exists for 2026-09-09 through 2026-09-24 (16 days) in `run-ledger.json` on `main-agents`. This is **not** a run gap: vault `01_daily/` notes exist for every one of those dates, and GHL/Outlook/Meta-Ads all independently confirmed real ingest activity through those days — the ledger entries were written on session branches that never merged back into `main-agents` (the same branch-isolation pattern already documented in the 2026-09-08 ledger note). Two real, partial gaps remain regardless of branch merging: Outlook and Meta Ads both have no raw ingest file anywhere for 2026-09-09 through 2026-09-17 (10 days), now outside the 7-day catch-up window and permanently un-recoverable by those agents.
