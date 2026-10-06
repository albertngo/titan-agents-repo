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
| 10 | **NFM stays exactly as it works today** (Albert 2026-10-06, to minimise calculation errors): the NFM cost row holds the full Lightspeed POS total incl. tax, and commission keeps the fixed 25% margin estimate (`÷ 1.13 × 0.25`). The sync only fills that number from Lightspeed instead of it being typed. Flooring revenue = the quoted rate; margin and commission on the post-discount total. | Albert 2026-10-06, amendment §2.2, §6 |
| 11 | No commission formula changes, so no restatement and no freeze is needed. | Albert 2026-10-06 |
| 12 | Payments and costs are suggested, Albert confirms. Only real disagreements reach him. | Albert, amendment §4 |
| 13 | AP Disposal invoices are extracted from email; card-paid bins are recorded at booking. | Albert |
| 14 | No Excel parsing. The Airtable quote model becomes the source of quoted labor, the pack list and the discount (Phase 3). | Albert |
| 15 | Pay method per contractor. Paid is marked by Albert, never from a bank email. | Albert |
| 16 | Scope: only projects with a Project End Date on or after 2026-09-01. Older or undated unpaid rows are left out and counted on the run, for Albert to settle by hand (`payout-policy.json → scope`). | Albert 2026-10-06 |
| 17 | **What was ordered is the truth for flooring, not the Lightspeed sale.** The chain is LS purchase order → supplier sales-order confirmation → supplier invoice (and any credit memo). When the sale line's product or rate differs from what was ordered, the sale is flagged as a **PM entry mistake** for the PM to correct; the ordered product and the invoiced rate are what cost and margin use. Found on PP-461 (sold Click 5", ordered 6" T&G, as the PM's own notes said) and PP-439 (sold 9" White Oak at $6.99, ordered 7.5" White Ash at $3.49). | Albert 2026-10-06 |

## What people do

**PMs**
1. One Lightspeed sale per project, note exactly `@pack for <name> PP-###`. Any extra
   sale for the project carries the same `PP-###`. (22 `@pack` sales in the last 120
   days had no number — each one is invisible to the payout flow.)
2. At quote time, enter the flooring cost from the supplier's price PDF
   (`Cost source = PM manual (supplier PDF)`).
3. At submit: enter final labor with its `Cost Source` (Our Cost / Sub Invoice),
   attach the invoice when there is one, and write a `Change order reason` whenever
   labor differs from `Quoted Cost` (`Change Order Reason`). `Submit Blockers` must be empty.
4. Card-paid bins (In The Bin, Orion): enter the amount on the Disposal row at booking.

**Front desk**
1. Raise the stock purchase order in Lightspeed with the rate you looked up
   independently, and put `PP-### <name>` in the PO **name** (a PO has no note
   field). Today 4 of 209 POs carry a number; without it the PO cost cannot be tied
   to the job.
2. When PM and front desk disagree, front desk's rate is the working number until the
   supplier invoice arrives.
3. When the supplier's sales-order confirmation arrives, check it against the PO
   (product, boxes, rate). A price change between confirmation and invoice (Vidar's
   Aug 1 increase on PP-417) is the supplier's to explain, not the PM's.

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

## Notion fields (added 2026-10-06)

All added, with Albert's own capitalisation where he made the field first; the exact
names are in `notion-finance.json`. Each database has a **💸 Payout Setup** view showing
the new fields together (Payments Log: **💸 Payments to confirm**), so they can be seen
— or removed — in one place.

- **Titan Team:** `Pay Method` (multi-select: e-Transfer, Cash, Cheque, Direct Deposit,
  Netted). Albert sets it per contractor.
- **QA Work Orders:** `Charge To` (Titan / Installer; blank = Titan).
- **Project Costs:** `Quoted Cost`, `Cost Source` (Sub Invoice, Our Cost, Quote, Manual,
  Front Desk (Stock Order), Lightspeed, AP Invoice (auto), PM Manual (Supplier PDF)),
  `Change Order Reason`, `Invoice` (files), `Invoice #`, `LS Sale IDs`, `LS PO IDs`,
  `Suggested Cost`, `Suggestion source`, `Suggestion confidence`, `Suggestion reason`,
  `Accept suggestion`, `Payout Batch` (reverse of Payout Batches → Lines).
- **Titan Projects:** `LS Sale Found`, `Quote Discount`.
- **Flooring Line Items:** `Quote Rate`, `PM Cost Rate`, `PO Cost Rate`,
  `LS Sale Cost Rate`, `Invoice Cost Rate`, `Cost Rate Flag` (formula), `Cost Locked`.
- **Master Payments Log:** `Suggested Project` (relation → Titan Projects),
  `Match Confidence`, `Match Reasoning`, `Accept`.
- **Project Financials:** `Commission Release Override`, `Override Reason`,
  `Below Floor` (formula).
- **💸 Payout Batches** (new, private to Albert): Name, Run, Payee, Pay Method (rollup),
  Lines, Commission lines, Claimant role, Total, Flags, Bank cross-check, Approved, Paid,
  Paid Date, Reference.

## Formulas to paste by hand (optional)

Notion's API refuses any formula that reads through a link to another database, so
these three must be pasted in the Notion UI (property → Edit formula). They are
convenience columns only: `payout_run.py` works out the work-order hold itself.

**Project Financials → `Open Work Orders`** (new formula property)
```
prop("Project").map(current.prop("Deficiency Work Orders")).flat()
  .filter(current.prop("Status") != "Done" and current.prop("Status") != "Dropped").length()
```

**Project Financials → `Commission Releasable`** (new formula property, after the one above)
```
prop("Costs Complete") and (prop("Open Work Orders") == 0 or prop("Commission Release Override"))
```

**Titan Projects → `Submit Blockers`** (new formula property; empty = ready)
```
[
  if(prop("Final Walkthrough") != "Completed", "walkthrough", ""),
  if(prop("Project Costs").filter(current.prop("Category") == "Labor" and empty(current.prop("Cost"))).length() > 0, "labor cost", ""),
  if(prop("Project Costs").filter(current.prop("Category") == "Labor" and not empty(current.prop("Quoted Cost")) and current.prop("Cost") != current.prop("Quoted Cost") and empty(current.prop("Change Order Reason"))).length() > 0, "change-order reason", ""),
  if(not prop("LS Sale Found") and prop("Project Type") != "Management", "no PP-tagged LS sale", "")
].filter(current != "").join(", ")
```

No existing formula changes (`Total Non-Flooring Materials`, `Commission Basis`,
`Commission Amount` stay as they are — Decision 10). `Cost Rate Flag` and `Below Floor`
were added by API and need nothing.

## Why every project has a Lightspeed sale (Albert, 2026-10-06)

The PP-tagged Lightspeed sale is a bookkeeping record, not the customer's checkout.
Materials are re-entered as if sold to the client so Lightspeed carries the cost,
profit and inventory movement. The sale stays parked until Albert moves the money into
Titan (the customer may have paid cash or to a personal account) and is completed after
the fact. Consequences for this flow:

- A parked sale on a finished project is normal. Once the project is Ready To Submit or
  Submitted, its totals are treated as final (`payout-policy.json → lightspeed`).
- A parked sale on a submitted project is also a to-do: funds still to transfer into
  Titan, then close the sale.

## Traps

- **Lightspeed sale-line cost is frozen at sale time** from the product's average
  cost (stocked) or supply price (non-stock). A later PO receipt never fills it in, so
  a $0 stocked line stays $0 — it is flagged and the PO cost suggested instead.
  `PUT /sales/{id}` could in principle edit it; never used.
- **The Lightspeed sale is the PM's entry, not the purchase.** It can name the wrong
  product (PP-461, PP-439) or carry a stale catalogue cost (Vidar engineered sells at
  about $0.70/sqft over what Vidar bills). It is compared, never preferred, once a PO,
  confirmation or invoice exists.
- **Vidar documents** (info@): confirmations in PURCHASE ORDERS / PO Confirmed
  ("Estimate – Sales order N", prints `P.O. Number: 8xxx`); invoices in INVOICE (prints
  the estimate number); credit memos in CREDIT (restocking fee shows as a reduced box
  rate). Orders placed by email have no LS PO and no P.O. number on the document.
  An estimate and an invoice can share a number by coincidence (103399).
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
| 0 | Staff rules above; Notion fields | October projects follow the PP and cost-staging rules |
| 1 | Pulls + sync + run in `plan_only`; dry-run October | Run matches Albert's own list (PP-461 Roy 2,010; PP-450 Luxevista 1,642 + APS 279.34; PP-417 Roy 7,375) |
| 2 | AP invoice extraction; `write` (dated) | First month-end with no hand-typed numbers |
| 2b | Supplier-invoice three-way cost check | An invoice locks a flooring cost end to end |
| 3 | Airtable quote → Notion push; LS pack-sale / PO writes (dated flips) | A Won quote fills quoted labor, quote rate, discount and the pack list |
