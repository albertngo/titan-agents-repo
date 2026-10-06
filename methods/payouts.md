# Payouts, AR & commission — method

How Titan pays contractors, disposal vendors and commission at month-end with one
review from Albert. Agreed with Albert 2026-10-05 (grilling session), amended by his
review 2026-10-06. Commands: `/project-costs-sync` (daily), `/payout-run` (monthly).
Registries: `platform-settings/notion-finance.json`, `payout-policy.json`,
`commissions.json`. Contracts: `ls-sales-schema.md`, `ls-orders-schema.md`,
`costs-plan-schema.md`, `payout-run-schema.md`.

**Nothing in this flow pays anyone or marks anything paid.** Albert ticks `Approved`
on a payee's batch, sends the money his way, ticks `Paid` and types the reference.
Both commands start in `plan_only`; flipping either is a dated vault decision.

## Decisions

| # | Rule | Source |
|---|---|---|
| 1 | Payouts run monthly. | Albert 2026-10-05 |
| 2 | Customer balance never holds contractor pay. Open work orders do (labor holdback). | Albert |
| 3 | Labor can differ from the quote (change orders); every difference carries a reason. | Albert |
| 4 | Albert approves and sends the money himself. | Albert |
| 5 | The PM confirms final labor at submit; Albert sees only exceptions. | Albert |
| 6 | Commission → Pourya whenever he is Sales Person or Project Manager; one line per project even with both roles. Claimants are a list in `commissions.json`; how a pool splits between two people is **open**. | Albert, amendment §8, §10 |
| 7 | Commission releases on Costs Complete + no open work orders, or Albert's override. A customer still owing is office admin's to collect and does **not** hold commission. | amendment §7 |
| 8 | Disposal invoices vary per job; no rate card. | Albert |
| 9 | Every Lightspeed sale carrying the PP number counts; sales are keyed by id. | Albert |
| 10 | Flooring revenue = the quoted rate. NFM cost from Lightspeed. Margin and commission on the post-discount total. **Open:** NFM revenue from quote rate or from the LS pre-tax sale price. | amendment §2.2, §6 |
| 11 | New formulas apply to unpaid commission and going forward; paid commission is frozen. | Albert |
| 12 | Payments and costs are suggested, Albert confirms. Only real disagreements reach him. | Albert, amendment §4 |
| 13 | AP Disposal invoices are extracted from email; card-paid bins are recorded at booking. | Albert |
| 14 | No Excel parsing. The Airtable quote model becomes the source of quoted labor, the pack list and the discount (Phase 3). | Albert |
| 15 | Pay method per contractor. Paid is marked by Albert, never from a bank email. | Albert |

## What people do

**PMs**
1. One Lightspeed sale per project, note exactly `@pack for <name> PP-###`. Any extra
   sale for the project carries the same `PP-###`. (22 `@pack` sales in the last 120
   days had no number — each one is invisible to the payout flow.)
2. At quote time, enter the flooring cost from the supplier's price PDF
   (`Cost source = PM manual (supplier PDF)`).
3. At submit: enter final labor with its `Cost source` (Our calc / Sub invoice),
   attach the invoice when there is one, and write a `Change order reason` whenever
   labor differs from `Quoted Cost`. `Submit Blockers` must be empty.
4. Card-paid bins (In The Bin, Orion): enter the amount on the Disposal row at booking.

**Front desk**
1. Raise the stock purchase order in Lightspeed with the rate you looked up
   independently, and put `PP-### <name>` in the PO **name** (a PO has no note
   field). Today 4 of 209 POs carry a number; without it the PO cost cannot be tied
   to the job.
2. When PM and front desk disagree, front desk's rate is the working number until the
   supplier invoice arrives.

**Albert**
1. Weekly, five minutes: "Payments to confirm" and "Costs to confirm" — tick `Accept`.
2. Month-end: open "Payout Run — YYYY-MM", read only the flagged lines, tick
   `Approved`, pay, tick `Paid` + reference.

## Netted pay method

`Netted` means the payee is owed money **and** holds Titan's money (typically cash
collected on a job), and the two are settled against each other instead of a transfer.
Rules: the batch shows the gross payout, the amount held, and the net; the `Reference`
names what was netted ("netted vs cash PP-417 $5,500"); a negative net is a receivable
from the payee, never a negative transfer. Only Albert sets `Netted` on a Titan Team row.

## Notion fields to add (Workstream B)

Add exactly these names (they are in `notion-finance.json` as `to_add`; flip each to
`live` there once it exists). Nothing existing is renamed or removed.

- **Project Costs:** `Quoted Cost` (number) · `Cost source` (select: Quote, Our calc,
  Sub invoice, PM manual (supplier PDF), Front desk (stock order), Lightspeed,
  AP invoice (auto), Manual) · `Change order reason` (text) · `Invoice` (files) ·
  `Invoice #` (text) · `LS Sale IDs` (text) · `LS PO IDs` (text) ·
  `NFM Revenue (pre-tax)` (number) · `NFM POS Total (incl. tax)` (number) ·
  `Suggested Cost` (number) · `Suggestion source` (select) · `Suggestion confidence`
  (select: High, Medium, Low) · `Suggestion reason` (text) · `Accept suggestion`
  (checkbox) · `Payout Batch` (relation → Payout Batches). Views: **Costs to confirm**
  (`Suggested Cost` is not empty and `Accept suggestion` unticked).
- **Flooring Line Items:** `Quote Rate`, `PM Cost Rate`, `PO Cost Rate`,
  `LS Sale Cost Rate`, `Invoice Cost Rate` (numbers, $/sqft) · `Cost Rate Flag`
  (formula below) · `Cost Locked` (checkbox).
- **QA Work Orders:** `Charge to` (select: Titan, Installer; default Titan).
- **Titan Team:** `Pay method` (select: e-Transfer, Cash, Cheque, Direct deposit, Netted).
- **Titan Projects:** `LS Sale Found` (checkbox) · `Quote Discount` (number) ·
  `Submit Blockers` (formula below).
- **Master Payments Log:** `Suggested Project` (relation → Titan Projects) ·
  `Match Confidence` (select: High, Medium, Low) · `Match Reason` (text) · `Accept`
  (checkbox). View: **Payments to confirm** (`Projects` empty and `Suggested Project`
  not empty).
- **Project Financials:** the formulas below plus `Commission Paid Amount` (number),
  `Commission Release Override` (checkbox), `Override Reason` (text).
- **New database `Payout Batches`** (private, under Albert's Notion Directory):
  `Name` (title) · `Run` (select, YYYY-MM) · `Payee` (relation → Titan Team) ·
  `Pay method` (rollup) · `Lines` (relation → Project Costs) · `Commission lines`
  (relation → Project Financials) · `Claimant role` (select) · `Total` (number) ·
  `Flags` (text) · `Bank cross-check` (text) · `Approved` (checkbox) · `Paid`
  (checkbox) · `Paid Date` (date) · `Reference` (text). Paste its data source id into
  `notion-finance.json → payout_batches.data_source`.

## Formulas (paste in this order)

The API hides formula code, so the live `Commission Basis` text must be checked by eye
before replacing it. Its description and the March build notes say
`Total Project Profit + Total Non-Flooring Materials / 1.13 × 0.25`.

**0. Freeze first (Q6).** Before touching any commission formula, `Commission Paid
Amount` is filled on every row already paid with today's `Commission Amount` (one
logged bulk write, Albert's go). After this, a formula change cannot move what was
paid.

**Project Financials**

```
NFM Revenue Sum            rollup: Costs → NFM Revenue (pre-tax) → Sum
NFM Cost Sum               formula:
  prop("Costs").filter(current.prop("Category") == "Materials (Non-Flooring)").map(current.prop("Cost")).sum()
NFM Actual Margin (pre-tax) formula:
  if(empty(prop("NFM Revenue Sum")) or prop("NFM Revenue Sum") == 0,
     prop("Total Non-Flooring Materials") / 1.13 * 0.25,
     prop("NFM Revenue Sum") - prop("NFM Cost Sum"))
Total Non-Flooring Materials  (replace) formula — the full POS price incl. tax, as before:
  prop("Costs").filter(current.prop("Category") == "Materials (Non-Flooring)")
    .map(if(empty(current.prop("NFM POS Total (incl. tax)")), current.prop("Cost"),
            current.prop("NFM POS Total (incl. tax)"))).sum()
Commission Basis           (replace) formula:
  prop("Total Project Profit (For Store Calcs)") + prop("NFM Actual Margin (pre-tax)")
Open Work Orders           formula:
  prop("Project").map(current.prop("Deficiency Work Orders")).flat()
    .filter(current.prop("Status") != "Done" and current.prop("Status") != "Dropped").length()
Commission Releasable      formula:
  prop("Costs Complete") and (prop("Open Work Orders") == 0 or prop("Commission Release Override"))
Below Floor                formula:
  prop("Overall Margin (With NFM Profits)") < 0.20
```

Why the `Total Non-Flooring Materials` change matters: store profit subtracts it as a
pass-through of the full POS price. Once the sync puts the real Lightspeed cost into
`Cost`, summing `Cost` would turn the pass-through into a cost and the NFM margin
would be counted twice. Old rows (no `NFM POS Total`) fall back to `Cost`, which on
them still holds the POS price; `NFM Actual Margin` falls back to the 25% estimate.
`NFM Cost Sum` is a formula, not a rollup, because a rollup cannot filter by category
(amendment §1.2 asked for two rollups; this is the nearest Notion allows).

**Flooring Line Items**

```
Cost Rate Flag   formula:
  if(empty(prop("PM Cost Rate")) or empty(prop("PO Cost Rate")), false,
     abs(prop("PM Cost Rate") - prop("PO Cost Rate")) > 0.10)
```

**Titan Projects**

```
Submit Blockers  formula (text; empty = ready):
  join([
    if(prop("Final Walkthrough") != "Completed", "walkthrough", ""),
    if(prop("Project Costs").filter(current.prop("Category") == "Labor" and empty(current.prop("Cost"))).length() > 0, "labor cost", ""),
    if(prop("Project Costs").filter(current.prop("Category") == "Labor" and current.prop("Cost") != current.prop("Quoted Cost") and not empty(current.prop("Quoted Cost")) and empty(current.prop("Change order reason"))).length() > 0, "change-order reason", ""),
    if(not prop("LS Sale Found") and prop("Project Type") != "Management", "no PP-tagged LS sale", "")
  ].filter(current != ""), ", ")
```

## Traps

- **Lightspeed sale-line cost is frozen at sale time** from the product's average
  cost (stocked) or supply price (non-stock). A later PO receipt never fills it in, so
  a $0 stocked line stays $0 — it is flagged and the PO cost suggested instead.
  `PUT /sales/{id}` could in principle edit it; never used.
- **Receipt numbers repeat** (L-40372 is two sales). Join on sale `id`.
- **Parked/pending sales change**; every run re-pulls the window.
- **R-35375-style closes** (100% discount, $0 revenue, cost kept) distort margin;
  flagged `zero_revenue_sale`.
- **Consignments:** the API ignores `type=`; filter `SUPPLIER` yourself; `page_size`
  caps at 500. The PO `name` holds customer first names — never write it out.
- **Financials rows are matched by the `Project` relation**, never by title (two
  "Diego (Financials)" rows exist).
- **`PM Name` is mostly empty** — use the `Project Manager` person field.
- **`Calculated (1/3)` is not a completeness signal** — it is ticked on NFM rows with
  no cost.
- **Payments Log `Message` holds customer addresses and phones** — read for matching,
  never echoed.
- **Make draft 4911142** (LS sale → cost lines) is superseded by `ls_sales_pull.py`;
  leave it off.
- **Interac:** BMO sends no "you sent" email; the "transfer … deposited / accepted"
  notices are the only confirmation of a sent transfer and are a cross-check only.

## Phases

| Phase | Scope | Exit |
|---|---|---|
| 0 | Staff rules above; Notion fields; commission freeze | October projects follow the PP and cost-staging rules |
| 1 | Pulls + sync + run in `plan_only`; dry-run October | Run matches Albert's own list (PP-461 Roy 2,010; PP-450 Luxevista 1,642 + APS 279.34; PP-417 Roy 7,375) |
| 2 | AP invoice extraction; formula switch; `write` (dated) | First month-end with no hand-typed numbers |
| 2b | Supplier-invoice three-way cost check | An invoice locks a flooring cost end to end |
| 3 | Airtable quote → Notion push; LS pack-sale / PO writes (dated flips) | A Won quote fills quoted labor, quote rate, discount and the pack list |
