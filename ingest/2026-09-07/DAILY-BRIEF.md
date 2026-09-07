## Daily Brief — 2026-09-07

**Needs attention today**
- **BMO loan arrears** on 1001321560 Ontario Inc.: $8,895.08 due, only $3,194.17 in the account (~$5,700 short). Albert replied 09-02, Jason Law looped in Brandon Donnelly same day, but two BMO Secure Email follow-ups since look unopened.
- **Allen Giacomelli** owes CA$5,390.10 on a completed project and enabled Do Not Disturb right after the payment reminder — SMS/email won't reach him, needs a phone call.
- **5 unanswered customer/prospect threads stacking up**: Arif Primek (WhatsApp pricing question, ~23h, no opportunity/tag created), Rasnatsum Hallib (refinishing estimate, 3 days), Sonia (repeat customer, new material order, ~23h), scrvik@gmail.com + dcyfung@gmail.com (quote threads, 39–46h), briannanorton@clickgrowcuration.com (prospect inquiry, ~70h).
- **Aviva Insurance claim** (36 Lee Centre Dr, via pourya@'s inbox) needs floor-area repair detail from Titan to proceed — unanswered ~92h.
- **Bookkeeper still dark**: QuickBooks MCP connector not configured — 10th consecutive failed run since 2026-07-26. All payments/overdue/uncategorized figures unknown.
- **Tactical Tasks backlog**: 113 of 189 open rows (~60%) past their staleness threshold, oldest 154 days — flagged repeatedly since 2026-07-31, overdue for a batch triage pass.
- **Muhammad Rafiq** still tagged `lead: hot` but replied "No thanks" yesterday — tag/contact mismatch, stop outreach.

**Numbers**
- GHL: 180 total leads, 5 new, 6 unanswered conversations, 0 won today, 34 workflow-drift findings.
- Outlook: 92 messages scanned (9 customer / 4 unanswered, 10 supplier, 9 admin, 1 bounce).
- Bookkeeper: error — no QBO connector, all figures unknown.
- Notion: 1 new won project ($4,000, Virdee Jasvir), 1 payment ($1,900), 113 stale tactical tasks, 1 new meeting logged.
- Meta Ads (5-day catch-up window 09-02→09-06): $242.94 spend, 17 leads, CPL $14.29 — below the ~$17 baseline, account healthy.

**By source**
- **GHL**: 5 new leads, 6 unanswered conversations. Beyond the headline items above, 11 Meeting-scheduled opportunities are at/beyond 100% of the 30-day stale threshold (up to 276%, Maria Wildfang) with no `stale_lead` tagging — direct input for Albert's planned follow-up sequence. Susham Sharma (Burlington) auto-abandoned after only 8 days in New Lead, well under the 28-day rule — worth a sanity check it wasn't a manual close. Store pipeline stage/status desync persists (13 Closed-Won + all 4 Closed-Lost records still `status: open`).
- **Outlook**: Catch-up run (last success 09-02; window widened to 120h/144h to cover the gap). Beyond BMO and the unanswered threads above, mailbox coverage was clean — albert@ 52, info@ 25, pourya@ 19, mike@ 0 scanned, no errors.
- **Bookkeeper**: Error — no QuickBooks/Intuit MCP connector configured. Standing setup gap, not a transient outage; needs a `.mcp.json` entry with valid credentials before it can produce data.
- **Notion**: 1 new won project (Edwin Wong, Mississauga — still missing Opportunity ID/contact/value since 08-31, flagged again). The Sep 2 meeting-processor summary claims 7 new Tactical Tasks created, but 2 of those pages now resolve as deleted (only 5 of 7 survive) — worth confirming with Albert whether intentional. Two new Operations CIIs opened (screw-down scope, measurement-device accuracy) from the same meeting; not visible in ingest since CII pull is disabled (v2).
- **Meta Ads**: Single active campaign (Flooring Problems), CPL healthy, 0 flagged ads. Lead-action-type set outside the script's documented list keeps recurring (3rd consecutive run) with no count discrepancy — worth extending the script's action-type list rather than continuing to hand-note it.

**Sources missing today**
- `bookkeeper` reported `status: error` (QuickBooks/Intuit MCP connector not configured) — see above.
- All other sources reported.
- No missed run days: the ledger's last recorded entry was 2026-09-02, but `outlook.json`/`meta-ads.json` catch-up windows and the vault's `01_daily/` notes confirm 2026-09-03 through 2026-09-06 actually ran (on branches not yet merged to this one) — the known branch-isolation gap in this repo's ledger, not lost coverage. See ledger entry note for today.
