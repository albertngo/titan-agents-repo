## Daily Brief — 2026-09-11

**Needs attention today**
1. **Three of five sources down today**: Outlook (this session's egress proxy blocked `login.microsoftonline.com` with a 403 — unscanned since 2026-09-08, gap now 3 days), Notion (`query_data_sources` is plan-gated workspace-wide — a billing/plan issue, distinct from the 2026-07-28 rate-limit outage), Bookkeeper (no QuickBooks/Intuit connector, 11th consecutive failed run since 2026-07-26). Operational and financial visibility is largely blind today.
2. **Ghandi (R-34991)** STORE material deal moved to **lost** today — $38,450, the largest single dollar movement in the window — worth a quick check on why.
3. **Dante Spizziri**'s in-home visit is **today at 5:30pm** (Bolton) — he offered floor plans and a HouseSigma link yesterday, never acknowledged, still untagged despite clear direct contact.
4. **Gopichand Manubolu**'s opportunity auto-abandoned Sept 4 mid price-negotiation ($1,885 quote) — same pattern as the Michael Camara finding on 2026-09-08; re-open and schedule the visit rather than treat as dead.
5. **Brooks Persad**'s revised quote ($2,730, after an in-home visit + store follow-up) has sat in an internal note since yesterday evening — never sent to him.
6. **Silviya Jardany** is asking whether her in-store visit is this Saturday (Sep 12) or the 19th — unanswered, and it's 1–2 days out.
7. **Ali Abdel Fattah** (hot stairs lead) said he's home "anytime" for a site visit and gave his Oakville address — no appointment has actually been booked.

**Numbers**
- GHL: 116 total leads, 8 new, 8 unanswered conversations, 15 untagged in queue, 4 appointments booked, 15 pipeline moves, 1 won today ($3,959.97 — Chrissy McCormack), 30 workflow-drift findings (26 hot / 42 warm / 25 cold / 2 unqualified / 4 stale).
- Outlook: error — no data (egress proxy blocked Graph OAuth; unscanned since 2026-09-08).
- Bookkeeper: error — no data (no QuickBooks/Intuit connector, 11th consecutive failed run since 2026-07-26).
- Notion: error — no data (`query_data_sources` plan-required workspace-wide).
- Meta Ads: $154.65 spend, 14 leads, $11.05 CPL, 1 active campaign, 0 flagged ads (window widened to 3 days to close the 09-09/09-10 gap).

**By source**
- **GHL**: 8 new leads, 15 pipeline moves, 1 win ($3,959.97, same-day visit to same-evening close). Besides the items above, Susham Sharma still reads "abandoned" since Sep 7 though Albert is actively trying to reach her via her husband — status hasn't caught up to reality. Faziela Bashir's visit was cancelled yesterday for a family emergency and hasn't been rebooked; Mhay Cunanan (open warranty claim) has waited 15+ hours for a repair-schedule reply; a missed callback from (905) 815-3889 (Oakville) has no tag or follow-up. 30 drift findings surfaced, largest single miss: Maria Wildfang, 83 days since her Meeting-Scheduled visit with zero follow-up.
- **Outlook**: Error — this session's proxy returned a 403 to `login.microsoftonline.com` before any token request completed (an org egress-policy denial, not an expired credential or Microsoft outage). No mailbox data for any of the 4 mailboxes. See needs-attention item 1; the 2026-09-09→11 window must be caught up, not silently dropped back to 24h, on the next successful run.
- **Bookkeeper**: Error — connector still not configured. See needs-attention item 1.
- **Notion**: Error — `query_data_sources` returned a plan/usage-limit block on every attempt (SQL and rows modes), confirmed as a hard plan-tier gate via a self-diagnostic fetch, not a transient rate limit. Zero data for Titan Projects, QA Work Orders, Master Payments Log, Tactical Tasks staleness, and Project Status Meetings. Dedupe baseline carried forward unchanged from 2026-09-08 so tomorrow's run won't misfire "new" on known rows.
- **Meta Ads**: Flooring Problems Campaign is the only active spend; $11.05 CPL is in line with the ~$12.36 7-day baseline, no delivery issues, 0 flagged ads. Lead counts again include conversion types outside the ingest script's documented `LEAD_ACTION_TYPES` (recurring since 2026-08-31, no discrepancy in the counted total) — the script's set should be extended rather than continuing to hand-note it.

**Sources missing today**
- Outlook: `status: "error"` — egress proxy blocked `login.microsoftonline.com` (403 on CONNECT); needs the sandbox's allowlist widened to include `login.microsoftonline.com` and `graph.microsoft.com`.
- Bookkeeper: `status: "error"` — no QuickBooks/Intuit MCP connector configured (11th consecutive failure since 2026-07-26).
- Notion: `status: "error"` — `query_data_sources` is plan_required/full_version_required workspace-wide; needs the Notion MCP plan/trial resolved.
- GHL and Meta Ads reported `status: "ok"`.
- Note on the run-ledger gap: the local `run-ledger.json` on this branch last shows 2026-09-08, but vault daily notes `01_daily/2026-09-09.md` and `01_daily/2026-09-10.md` (confirmed by reading the titan-vault repo directly) show real five-source daily-ingest runs happened on both days — this branch's `ingest/` history just never merged their raw JSON. Same branch-isolation pattern noted in the 2026-09-02 and 2026-09-08 ledger entries, not an actual missed-run gap.
