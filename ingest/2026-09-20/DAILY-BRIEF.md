## Daily Brief — 2026-09-20

**Needs attention today**
1. **GHL fully down today** — `mcp__ghl__*` tools were not bound to this session (same failure class as 2026-08-15/18/19/24). Zero lead, pipeline, conversation, or drift visibility for Sales; re-run once MCP access is restored.
2. **[[Moe Nadeem]]** — warranty stair-repair claim is waiting on Titan to confirm the Oct 7 install date; last customer message 2026-09-18 12:43 ET, no reply found since (~48h).
3. **Oakel City (supplier)** warns mailed checks to them have been intercepted/altered by a third party, others never arrived — confirm Titan doesn't pay this supplier by mail.
4. **cpitter01 (4798 Huron Heights Dr)** — asked twice for a final sales receipt (warranty) and a leftover-wood pickup; no reply found since 2026-09-16 19:26 ET.
5. **rajanfiroz73 (36 Lee Centre Dr insurance job)** — waiting on Titan to coordinate with the insurance adjuster; no reply found since 2026-09-16 16:51 ET.
6. **Two new Notion won-projects** ([[Allison Hubson]], [[Moe Nadeem]]) tagged `[DEFICIENCY]`/`[WARRANTY]`, missing Opportunity ID/Sales Person/other standard fields — confirm these are genuine tracked jobs, not mislabeled rework (recurring pattern, also flagged 2026-08-31 and 2026-09-07).
7. **Bookkeeper/QuickBooks still down** — 11th consecutive failed run since 2026-07-26, no QBO/Intuit MCP connector configured. Zero payments/invoices/transaction visibility.

**Numbers**
- GHL: error — no data (MCP tools not bound this session).
- Outlook: 137 scanned across 4 mailboxes (9 customer / 8 supplier / 6 admin / 73 noise), 4 unanswered customer threads, 0 bounces.
- Bookkeeper: error — no data (QBO connector never configured).
- Notion: partial — 4 new won projects ($23,083.50 CAD), 3 payments ($6,096.77 CAD), 154 of 224 tactical tasks stale, meetings unknown (workspace query-quota hit).
- Meta Ads: $349.76 spend (7-day capped window), 24 leads, $14.57 CPL, 1 active campaign, 0 flagged ads.

**By source**
- **GHL**: Failed entirely — `mcp__ghl__*` tools weren't granted to this session; credentials confirmed present and valid. No leads, pipeline moves, or drift findings today.
- **Outlook**: 137 messages scanned, 4 unanswered customer threads flagged high priority (items 2, 4, 5 above). $22,164.02 in Interac deposits landed 09-14–09-19 and $12,513.71 went out to suppliers (Triforest, Zion, Canoe Trading) — routine. Accountant (Dang & Associates) engaged for a Jan–Sep QBO cleanup, in progress.
- **Bookkeeper**: Still fully blocked — no QBO/Intuit MCP connector in `.mcp.json`, no credential documented in `.env.example`. Standing gap, not a transient outage.
- **Notion**: Partial run — `titan_projects`, `qa_work_orders`, `master_payments_log`, `tactical_tasks_list` all completed; `project_status_meetings` failed on the workspace's shared SQL query-quota cap. 4 new won projects, including the two flagged above. 3 payments totaling $6,096.77, none linked to a Projects relation. Tactical Tasks backlog now 154/224 stale (69%, oldest 167 days) — overdue for a batch triage pass, flagged repeatedly since 2026-07-31.
- **Meta Ads**: $349.76 spend / 24 leads / $14.57 CPL over the capped 7-day catch-up window — ~8% above the trailing baseline, well under the 2x anomaly threshold. Sole active campaign: Flooring Problems Campaign. No flagged ads.

**Sources missing today**
- `ghl`: status `error` — `mcp__ghl__*` tools not bound this session (confirmed via ToolSearch: no GHL MCP tools exist in this session at all). Not a credential or platform issue.
- `bookkeeper`: status `error` — QuickBooks/Intuit MCP connector not configured (no `.mcp.json` entry, no `.env.example` credential). 11th consecutive failure since 2026-07-26.
- `notion`: status `partial` — `project_status_meetings` sub-source failed on a Notion workspace SQL query-quota limit; the other 4 sub-sources reported ok.
- `outlook`, `meta-ads` reported ok.
- **Ledger note, not a missed-run gap**: `run-ledger.json` had no entries between 2026-09-08 and today, and `/ingest/` on this branch is missing the standard 5-source files for 2026-09-09 through 2026-09-19. This looked like an 11-day gap, but is confirmed **not** one: `titan-vault/01_daily/2026-09-09.md` through `2026-09-19.md` all carry full, real daily-ingest content (GHL/Outlook/Bookkeeper/Notion/Meta-Ads numbers) for every one of those days — the same recurring branch-isolation pattern already documented and recovered for August (see ledger entries for 2026-08-29, 2026-08-31, 2026-09-08). `git ls-remote` confirms ~30 stranded `claude/kind-feynman-*` session branches still exist on `origin`, likely holding the raw ingest JSON for those days. Recovering/merging them is a distinct cleanup task for Albert to schedule, not done as part of this run — today's ingest agents used 2026-09-08 as their local diff baseline and flagged the resulting dedupe/window caveats inline (see each source's `needs_attention`).
