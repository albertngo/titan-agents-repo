## Daily Brief — 2026-09-21

**Needs attention today**
- GHL ingest failed entirely — `ghl` MCP server never connected this session ("Pending approval," not an auth/network error). Zero leads, opportunities, appointments, conversations, or workflow-drift checks today; primary daily-brief source is missing until the MCP approval step is fixed and this ingest re-runs.
- Bookkeeper still blocked — 11th consecutive failed run since 2026-07-26. No QBO/Intuit MCP connector exists; Finance remains "blocked — the source has never worked" per CLAUDE.md.
- [Moe Nadeem](https://outlook.office365.com/owa/?ItemID=AQMkAGUwZmIwNGUzLTFjYmUtNDkyMC05ZWM4LTFjNGNkNWE3MzU2NABGAAADVDF%2BvOlcfUWouzaiZMo9EgcAnxwx6GogQ0C6e3q5wrzPwgAAAgEMAAAAnxwx6GogQ0C6e3q5wrzPwgABQuVgHgAAAA%3D%3D&exvsurl=1&viewmodel=ReadMessageItem) accepted the Oct 7 stair-warranty repair date — no reply from Titan confirming since Sept 18.
- [Atlantic Flooring Distributors](https://outlook.office365.com/owa/?ItemID=AQMkAGUwZmIwNGUzLTFjYmUtNDkyMC05ZWM4LTFjNGNkNWE3MzU2NABGAAADVDF%2BvOlcfUWouzaiZMo9EgcAnxwx6GogQ0C6e3q5wrzPwgAAAgEMAAAAnxwx6GogQ0C6e3q5wrzPwgABRCmvigAAAA%3D%3D&exvsurl=1&viewmodel=ReadMessageItem) — $3,740 deposit confirmation on Sales Order 50989 unanswered since Sept 19.
- Two more unanswered customer threads >24h: [4798 Huron Heights](https://outlook.office365.com/owa/?ItemID=AQMkAGUwZmIwNGUzLTFjYmUtNDkyMC05ZWM4LTFjNGNkNWE3MzU2NABGAAADVDF%2BvOlcfUWouzaiZMo9EgcAnxwx6GogQ0C6e3q5wrzPwgAAAgEMAAAAnxwx6GogQ0C6e3q5wrzPwgABQAIY1QAAAA%3D%3D&exvsurl=1&viewmodel=ReadMessageItem) (wants final receipt + replacement wood box, since Sept 16) and [Sowmya](https://outlook.office365.com/owa/?ItemID=AQMkAGUwZmIwNGUzLTFjYmUtNDkyMC05ZWM4LTFjNGNkNWE3MzU2NABGAAADVDF%2BvOlcfUWouzaiZMo9EgcAnxwx6GogQ0C6e3q5wrzPwgAAAgEMAAAAnxwx6GogQ0C6e3q5wrzPwgABQAIY0AAAAA%3D%3D&exvsurl=1&viewmodel=ReadMessageItem) (repeated urgent callback request, since Sept 15).
- Tactical Tasks List backlog: 153 of 228 open rows (67%) are past staleness threshold; oldest is 168 days ("Call For Balance (Naqib)"). Overdue for a triage pass.
- No Project Status Meeting logged since Sept 2 — 19 days past the normal weekly cadence.

**Numbers**
- GHL: error — 0 leads/opportunities/appointments/conversations pulled (MCP not connected)
- Outlook: 140 scanned → 27 items (12 customer, 7 supplier, 8 admin), 3 unanswered customer threads >24h, 0 bounces
- Bookkeeper: error — $0 payments/invoices/txns reported (no data pulled, not actual zero)
- Notion: 1 payment ($1,425.00), 153 stale tactical tasks, 0 new won projects (cold start), 0 work orders in error
- Meta Ads (7d, 09-14→09-20): $352.38 spend, 26 leads, $13.55 CPL, 0 flagged ads

**By source**
- **GHL**: No data today — the `ghl` MCP server showed "Pending approval" rather than connecting, so no leads, pipeline moves, or workflow-drift checks ran. Same failure mode as 2026-09-20. Needs the MCP approval step re-run before next scheduled ingest.
- **Outlook**: Ok, window widened to 7 days (last successful run was 2026-09-08). 3 high-priority customer threads sit unanswered >24h — Moe Nadeem (stair-warranty date), Atlantic Flooring ($3,740 deposit), Huron Heights (receipt/wood box), plus Sowmya's repeated callback request. [Oakel City](https://outlook.office365.com/owa/?ItemID=AAMkADg3ODE1NTk4LTZiNWQtNGQ5NC1iOWJhLWZhZTI0NjQ4ODRjOQBGAAAAAACfW0oVpd2VRJyg7ITCqcIQBwBFlqPg%2FSDYTaqiknz3W61PAAAAAAEMAABFlqPg%2FSDYTaqiknz3W61PAAP0GJeBAAA%3D&exvsurl=1&viewmodel=ReadMessageItem) flagged mailed-check fraud — worth confirming Titan hasn't mailed them a check recently. $18,600.98 in Interac deposits and $6,133.08 Yardi EFT landed this window; nothing owed.
- **Bookkeeper**: Error — no QBO/Intuit MCP connector configured, 11th consecutive failed run since 2026-07-26. This is a standing setup gap, not a transient outage; Finance dept remains blocked.
- **Notion**: Ok, but a cold start (no notion.json in the 7-day lookback), so 0 new-won-project/meeting items were emitted even though 5 Titan Projects rows and 3 Project Status Meeting rows were in scope — they're now seeded, real new rows surface tomorrow. One $1,425.00 e-Transfer payment logged. Tactical Tasks staleness backlog keeps growing (109/186 on 09-08 → 153/228 today). Config still references a non-existent "Pending Status" QA option — needs correcting.
- **Meta Ads**: Ok, window widened to 7 days (13-day gap since 2026-09-08; 6 days, 09-08→09-13, are unrecoverable). $352.38 spend on the sole active campaign (Flooring Problems Campaign) drove 26 leads at $13.55 CPL. No baseline pull this run, so no CPL-anomaly comparison. Account healthy, no disapproved/issue ads.

**Sources missing today**
- `ghl` — status: error. GHL MCP server never connected this session ("Pending approval," not an auth/network failure); zero platform data read.
- `bookkeeper` — status: error. No QBO/Intuit MCP connector configured (11th consecutive failure since 2026-07-26); standing setup gap, not a transient outage.
- No run at all on: none. The local run-ledger.json's last entry before today is 2026-09-08, but this is the same branch-isolation artifact already recorded in that entry: vault daily notes (`01_daily/2026-09-09.md` through `2026-09-20.md`) and an unmerged session branch (`origin/claude/adoring-mendel-3jv4ls`, ingest through 2026-09-20) confirm real daily-ingest runs happened on every intervening day — their ledger entries and ingest files simply never merged into this branch's history.
