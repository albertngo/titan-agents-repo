## Daily Brief — 2026-08-12

**Needs attention today**
- **Firoz Rajan** (~$9,000 insurance claim, hot lead) — opportunity auto-abandoned today after 118 days with zero follow-up in Meeting-Scheduled; he emailed the same day saying he never received an estimate. Needs an immediate manual save. [GHL]
- **Naushaba Haque** (Aviva insurance, 36 Lee Centre Dr #601) — still has not received a flooring estimate despite re-asking; thread with pourya@ (cc albert@) has no reply. [Outlook]
- **SYSTEMIC**: 97 open opportunities in "0b. Far Out (Cold)" are frozen at exactly 287.4 days in stage (319% of the 90-day threshold), only 4 tagged `stale_lead` — the stage's stale/abandon automation appears to have stopped firing for the whole cohort. Needs a platform-level check, not a one-by-one review. [GHL]
- 6 opportunities are within 4 days of auto-abandonment, including a **$21,283 warm lead (Ghandi, unassigned)** and a $7,235 warm lead — largest dollar value currently at risk. [GHL]
- **Today**: Damian's stairs install (Innisfil) crew arrives 9–10am; $2,430 balance is still outstanding. [GHL]
- Bookkeeper (QuickBooks) ingest has never succeeded since tracking began (2026-07-26) — no Intuit MCP server or QBO credentials are configured. One-time setup needed; all financial metrics for today are unknown, not zero. [Bookkeeper]
- **Today**: Albert has an in-branch RBC MyAdvisor annual financial review appointment at 10:30 AM EDT. [Outlook]

**Numbers**
- GHL: 212 leads, 7 new, 27 unanswered conversations, 19 untagged in call-queue, 1 won today ($9,250), 195 workflow-drift findings.
- Outlook: 52 scanned (4 mailboxes, 80h catch-up window), 1 customer / 5 supplier / 12 admin items, 1 unanswered customer thread.
- Bookkeeper: error — no data (QBO never connected).
- Notion: 6 new won projects (~$42,536.50 CAD), 1 payment ($5,648.00), 76 stale tactical tasks (up from 55 on 2026-08-08), 0 new meetings.
- Meta Ads: $52.71 CAD spend, 1 lead, CPL $52.71 (≈2.8x the 7-day baseline of $18.58).

**By source**
- **GHL**: Won $9,250 today (Ricardo, Mississauga, repeat contractor). Beyond Firoz Rajan and the Far Out cohort freeze above, Muhammad Alams ($8,908, hot, Meeting-Scheduled) is 0.6 days from going stale and his last inbound message (29 days ago) was never answered; Khadija and Shafqat Khan both have same-day questions awaiting reply; mobile-quote follow-up texts are firing at 3 days instead of the configured 5.
- **Outlook**: Catch-up run covered the 2026-08-09→11 gap (no prior failure — last run was mid-morning 2026-08-09). Besides Naushaba Haque and today's RBC appointment, Tosca Flooring offered special pricing ($3.39/sqft, Long Beach engineered) on 2026-08-10 that hasn't been confirmed and may lapse.
- **Bookkeeper**: Hard-down since tracking began — `.mcp.json` has no Intuit/QBO server entry and `.env.example` has no `QBO_*` vars. Needs a one-time config fix, not a retry.
- **Notion**: 6 new won projects total ~$42,536.50 CAD, but two data-quality issues surfaced: Ricardo Mendoza has two Titan Projects rows sharing one Opportunity ID with different values ($9,250 vs $10,452.50), and "Clerance Pitters" / "Clarance Pittson" look like the same Mississauga project entered twice. Edwin Wong's $5,648.00 payment cleared the $5,000 flag threshold. The stale tactical task backlog (76, was 55 on 08-08) has now been flagged three runs running — worth a batch triage.
- **Meta Ads**: Only "Flooring Problems Campaign" is active; its CPL is running well above its 7-day baseline (still under the $100/day high-priority threshold). Raw lead-action types outside the documented set showed up again but didn't affect today's counts.

**Sources missing today**
- Bookkeeper: `status: "error"` — QuickBooks/Intuit MCP server and credentials were never provisioned for this environment; every run since 2026-07-26 has failed the same way.
- No run at all on: 2026-08-09, 2026-08-10, 2026-08-11 (Outlook's catch-up window covered its own gap for that span; GHL, Notion, Bookkeeper, and Meta Ads have no equivalent backfill for those three days).
