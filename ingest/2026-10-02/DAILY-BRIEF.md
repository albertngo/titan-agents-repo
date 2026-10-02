## Daily Brief — 2026-10-02

**Needs attention today**
- **Complaint, albert@** — ashrim.narsinh disputes the Jul 2 install and balance; newest message (9/29) has no reply found (Albert replied to an earlier one 9/30).
- **Humberstone quote** — 35 Humberstone Cres broker wants the quote resent without the $450 disposal line (info@, since 9/28). No reply found.
- **Vidar** — asking pick-up date for the Mayuri order since 9/26. No reply found.
- **Security check** — BMO Business Online lockout + password reset (10/1) and a Notion password reset at info@: confirm these were Albert's. Also a phishing-like "Compensation Update" attachment email at info@.
- **Floordi Oct promo list (Oct 5–20)** arrived only in pourya@ (private) — needs routing to the price-list pipeline before it starts.
- **3 new won projects, $32,523.50** — Jeevan (~$3,200, no Opportunity ID/sales person, can't be tied to GHL), Arika (~$12,825.50), Mayuri Bhatti (~$16,498.00). Payments 9/30: $9,700 Rachita Saini, $5,000 Mayuri Bhatti.
- **GHL and bookkeeper both down** — no lead, drift or finance data today; this is not a quiet day.

**Numbers**
- GHL: no data (source error).
- Outlook: 136 scanned, 7 customer, 8 supplier, 8 admin, 3 unanswered customer.
- Bookkeeper: no data (source error; zeros are placeholders).
- Notion: 3 won ($32,523.50), 6 payments ($24,489.06), 8 open WOs, 0 in error, 42 stale tasks.
- Meta Ads: $39.40 spend, 2 leads, CPL $19.70 (7-day ~$14.74, 1.34x), 22 clicks, 1 active campaign, 0 flagged.

**By source**
- **GHL:** MCP tools were not exposed to the ingest session; nothing pulled, nothing fabricated. All six drift checks unrun.
- **Outlook:** Catch-up run — last prior file was 2026-09-08 and the window is capped at 7 days, so 09-09 to 09-24 is not covered. Customer: complaint, Humberstone and an unverified ultimateprotx.com RFQ (likely solicitation) are unanswered. Suppliers: Floordi promo list, Sidco payment reminder (no amount in preview). Interac e-Transfer notices rolled into admin items.
- **Bookkeeper:** QuickBooks connector unavailable; no data.
- **Notion:** Cold start (no notion.json since 09-08), so no diff. 42 tactical tasks stale >14 days (7 Gift Box, 17 GHL-sourced, many catalogue blockers marked high). 8 open work orders. Settings drift: QA Work Orders properties renamed and `Pending Status` removed — `notion-ingest-sources.json` needs updating. "Project Status — Oct 6/26" row exists with no summary (future-dated).
- **Meta Ads:** Healthy. Flooring Problems Campaign, $50/day budget, spent $39.40; CPL within 2x threshold.

**Sources missing today**
- ghl — error: GHL MCP tools unavailable in the ingest session.
- bookkeeper — error: QuickBooks MCP connector unavailable (still failing since 2026-07-26).
- No run at all on: 2026-09-09 through 2026-10-01 (per run-ledger; the ledger's last entry is 2026-09-08 — may be a branch-isolation artifact as noted on 09-08, unverified).
