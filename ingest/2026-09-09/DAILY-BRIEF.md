## Daily Brief — 2026-09-09

**Needs attention today**
- **BMO loan arrears, ~$5,700.91 short.** $8,895.08 owed on 1001321560 Ontario Inc. vs. $3,194.17 in the account (flagged 2026-09-02 by RM Jason Law). Albert replied "For sure!" but no confirmation a deposit was actually made appears in this window — NSF/default risk if still open.
- **Sowmya / 2160 Peachtree Lane Oakville — paid in full, unfinished work 12 days after the crew left.** Tone has escalated to "unprofessional" (GHL + Outlook, same complaint). Needs a concrete repair date, not another "someone will reach out."
- **Mohammad Abd Bint Azi** asked "What's the final no?" on a live pricing negotiation 7.7 days ago and never got a reply — highest-risk stale lead in the pipeline right now.
- **Arvind** — same-day visit at 4:30pm; customer explicitly asked for a confirmation call beforehand.
- **Sean K** — outstanding balance collection with 4 unread customer replies; could be a payment confirmation or a dispute, needs eyes today.
- **Two Major-severity QA Work Orders open**: Jay Ventura (Other, notified contractor) and Helena Toolsiedas (Warranty, sent to Projects). Helena's is also logged as a brand-new Won project with no Opportunity ID/contact/value — likely the same event double-logged; check before it distorts won-project counts. [Jay](https://app.notion.com/3d5596a4505f808bbd4cc78834b93a39) · [Helena](https://app.notion.com/3d5596a4505f8143b2affe085bf495f8)
- **Bookkeeper still blind**: QuickBooks/Intuit MCP connector unconfigured for the 10th consecutive run since 2026-07-26 — all payments-received, overdue-invoice, and uncategorized-txn figures are unknown until `.mcp.json` gets a real QBO entry.

**Numbers**
- GHL: 9 new leads, 20 unanswered conversations, 5 appointments booked, 1 won ($7,989.14 — Debbie Fung)
- Outlook: 32 items across 4 mailboxes (11 customer / 12 supplier / 8 admin / 1 bounce), 1 unanswered 3+ days
- Bookkeeper: error — no QBO connector, no data
- Notion: 5 new won projects ($43,770.70), 2 payments received ($9,651.39), 110 of 198 open tactical tasks stale, 1 meeting logged
- Meta Ads: $342.60 spend, 26 leads, $13.18 CPL (7-day window)

**By source**
- **GHL** — 260 leads in system, 9 new today. 39 workflow-drift findings after exclusions, dominated by 33 stale-lead-threshold misses (worst: Maria Waterdown at 283% of her window) — the stale-lead tag automation isn't reliably firing. Two opportunities (Thierry Beauvais, Noel Brillantes) auto-abandoned faster than the documented aging rules predict, worth a config-drift check. Harry (Brampton) still has a cancelled visit sitting unrescheduled 48.7 days.
- **Outlook** — Ran a 168h catch-up pull (7-day gap since the last successful run on 2026-09-02, fully closed, nothing missed). Beyond the items above: prospect dcyfung@gmail.com asked for a product comparison + install quote on 2026-09-05, still unanswered; a Prosol price-increase notice (2026-09-04) needs feeding into the Airtable catalogue; the Naveen/Helena tile-warranty thread is awaiting a reply since 2026-09-08 5:50pm.
- **Bookkeeper** — Zero data again; this is a standing setup gap (no QBO/Intuit MCP server configured), not a transient outage.
- **Notion** — 5 new won projects this window ($43,770.70 total); two of them (Gustavo, Diego Contecha) are missing Opportunity IDs so they won't cross-reference cleanly against GHL. The Sep 2 Project Status meeting logged four risk items now tracked as CIIs: zero jobs closed from month-old quotes, Roy's crew thinning/screw-down gaps, Moasure-vs-laser measurement accuracy, and a soft-subfloor quality miss at Edwin's. The 198-row Tactical Tasks List is 56% past staleness threshold and has been flagged repeatedly since 2026-07-31 — overdue for a batch triage pass.
- **Meta Ads** — Only active campaign (Flooring Problems, $50/day) delivering cleanly, no flagged ads. Window widened to the 7-day cap to close the same 09-03–09-08 gap as other sources; no distinct baseline existed this run so the CPL-anomaly check was skipped (resumes next normal run). Third recurrence of lead-like action types outside the documented `LEAD_ACTION_TYPES` set — no count discrepancy, but worth extending the script rather than continuing to hand-note it.

**Sources missing today**
All sources reported (bookkeeper reported `status: "error"` per its standing QBO-connector gap, not a silent omission).

No run at all on this branch's ledger for 2026-09-03 through 2026-09-08 — confirmed via cross-branch check to be a branch-isolation artifact, not a real gap: each of those days ran a full 5-source ingest + brief on its own unmerged session branch (`claude/adoring-mendel-855vhn`/`3rgf82`/`pccybs`/`gs75gw`/`6w3jna`), consistent with the same pattern already documented in the ledger for 2026-08-15–30 and 2026-09-01. No data was lost; the daily brief for those dates exists on those branches and their vault notes were written.
