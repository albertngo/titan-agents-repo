## Daily Brief — 2026-09-26

**Needs attention today**
1. **Suspected fraud: Triforest Inc. banking-change notice** to info@ (Sept 23) — self-addressed To: header, classic BEC/wire-fraud pattern. Do not update any remittance details without phone verification with a known Triforest contact.
2. **Moe(nad) Nadeem — Oct 7 install** — re-booked and asked for a deposit to hold the slot (unpaid as of this run); separately his warranty/stair-repair thread ("I am back now, please confirm for Oct 7th") is unanswered. He also carries no `lead:*` tag and no open opportunity tracking the job.
3. **Meeting-scheduled follow-up is structurally broken** — 24 of 25 open Meeting-scheduled opportunities have had no real follow-up since their appointment. Worst case: Maria Wildfang, $41,150, 98 days with zero follow-up. There is still no follow-up sequence for this stage.
4. **Fall Home Show final booth payment unpaid** (reported Sept 23) — booth/badge access will be blocked; Titan's own mail says booth setup is Thursday next week.
5. **Won customer Munsif** flagged a removed shoe moulding Sept 22 — 4 days later only automated nurture has touched him, no resolution.
6. **Ezra Reyes** (prospective customer) asked info@ Sept 22 about measuring/install timing — no reply found, unanswered >24h.
7. **Tactical Tasks backlog worsening** — 191 of 242 open rows (~79%) past staleness threshold, up from 59% on 2026-09-08. Oldest is 173 days ("Call For Balance (Naqib)"). Overdue for a batch triage pass (flagged repeatedly since 07-31).

**Numbers**
- GHL: 108 leads (25 hot/40 warm/22 cold/1 unqualified/4 stale), 4 new, 11 unanswered conversations, 0 appointments, 11 pipeline moves, 0 won today, 18 untagged in queue, 42 drift findings.
- Outlook: 125 scanned (59 albert@, 54 info@, 19 pourya@, 2 mike@) — 3 customer, 8 supplier, 9 admin, 1 unanswered customer, 0 bounces.
- Bookkeeper: **error** — no data (QuickBooks/Intuit MCP connector still not configured; 11th consecutive failed run since 2026-07-26).
- Notion: 0 new won projects, 0 payments received, 1 work order completed, 191 stale tactical tasks, 0 new meetings logged.
- Meta Ads: $356.26 CAD spend, 27 leads, CPL $13.19, 1 active campaign, 0 flagged ads.

**By source**
- **GHL** — Beyond the top items above: 3 stale-tagged 0a. New Leads were abandoned only 7–9 days after creation against a documented 14-day-stale/28-day-abandon rule, and 5 ASAP (Hot) leads are already past 100% of the 7-day stale threshold with no `stale_lead` tag ever applied — the automation doesn't appear to be firing reliably on either stage, and `platform-settings/ghl-workflow.json` may be stale relative to live behavior. Horshay Horhayba gave detailed marble specs before their opportunity lapsed to abandoned — worth one more manual look.
- **Outlook** — Two other suspicious emails this week beyond the Triforest notice (a garbled-sender "Xerox scan," an OFX "verify your business details" request) — treat with the same caution. **Process note:** this run confirms (via `git log --all`) that no `outlook.json` was ever produced for 2026-09-09 through 2026-09-18 — a real 10-day data gap for this source specifically, not recoverable, distinct from the branch-isolation pattern seen elsewhere.
- **Bookkeeper** — Still fully blocked; every field in Numbers above reflects "no data pulled," not a real $0 day. Needs an Intuit QuickBooks MCP server added to `.mcp.json` before this stops being reported daily.
- **Notion** — Cold start on this branch (last local snapshot was 2026-09-08): `new_won_projects` and `new_meetings` show 0 because the snapshot was reseeded from today's pull rather than diffed against a stale 18-day-old file — this is not a signal that nothing happened, just that nothing could be confidently called "new." Project Status Meetings' latest logged row is still Sept 2 (24 days old) against a weekly cadence — worth checking whether meetings are happening or the meeting-processor pipeline stalled. A settings-file column-name mismatch in `qa_work_orders.select_columns` (flagged since 08-14) was avoided but not fixed.
- **Meta Ads** — Flooring Problems Campaign remains the only active campaign; no delivery or disapproval issues, CPL well under the 2x-baseline anomaly threshold. Same widened-window caveat as Outlook: the last local `meta-ads.json` before today was 2026-09-08, so this run pulled 2026-09-19–09-25 (the 7-day cap) rather than a single day, and 2026-09-09–09-18 is not covered by any Meta Ads ingest. Recurring note (since 08-31): raw `actions` include lead-like conversion types outside the script's documented `LEAD_ACTION_TYPES` set — no count discrepancy, but the set should be extended rather than hand-noted again.

**Sources missing today**
- Bookkeeper: error — QuickBooks/Intuit MCP connector not configured (11th consecutive failure).
- All other sources reported ok. This local branch's `run-ledger.json` had not been appended to since 2026-09-08, but titan-vault's `01_daily/` notes exist continuously through 2026-09-25, confirming full daily-ingest runs happened on other session branches every day in between — a known branch-isolation artifact in this repo's ledger, not a missed run. The one confirmed real gap is narrower and source-specific: Outlook and Meta Ads each have no ingest file anywhere in git history for 2026-09-09 through 2026-09-18 (see By source above).
