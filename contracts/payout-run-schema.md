# Payout Run Contract — payout-run-1

The month-end payout run: who gets paid what, what is held and why, and what blocks a
payment. One run per month label, re-derived (never edited) on re-run:

```
ingest/YYYY-MM-DD/notion-finance.json        input  — read-only Notion snapshot
plans/YYYY-MM-DD/payout-run-<YYYY-MM>.json   output — this contract
plans/YYYY-MM-DD/payout-run-<YYYY-MM>.md     output — the Notion page text
```

Built by `scripts/payout_run.py` from the snapshot (taken by `/payout-run` through the
Notion MCP), today's `ls-sales.json` and, optionally, outgoing Interac notices. Rules
and thresholds: `platform-settings/payout-policy.json`, `commissions.json`; ids and
property names: `notion-finance.json`. Method: `methods/payouts.md`.

## The approval boundary

- The run is a **proposal**. Nothing in it pays anyone or marks anything paid.
- **Albert's `Approved` tick on a Payout Batches row is the approval** (Decision 4).
  His `Paid` tick plus a typed `Reference` is the only thing that marks a batch paid
  (Decision 15). The next `/project-costs-sync` stamps `Paid Out Date (2/3)` /
  `Paid Reference (3/3)` / commission paid fields from batches he marked `Paid` —
  never from a bank notice, never from this file.
- While `write_mode.payout_run` is `plan_only`, `/payout-run` writes this file and the
  `.md` and **nothing to Notion**.

## Input: the snapshot — notion-finance-1

`ingest/YYYY-MM-DD/notion-finance.json`, one key per table, rows as the Notion MCP
returns them, **keyed by the exact Notion property name** (the script maps names to
logical keys through `notion-finance.json`, so a renamed property is a registry edit):

```json
{
  "contract": "notion-finance-1",
  "taken_at": "2026-10-01T09:20:00-04:00",
  "projects":       [{"url": "…", "ID": 461, "Value Approx": 28080, "Project Type": "Both", "Sales Person": "Pourya Lalee", "Project Manager": "[\"user://…\"]", "Contractor": "[\"https://www.notion.so/…\"]", "Project End Date": "2026-09-14", "…": "…"}],
  "costs":          [{"url": "…", "Name": "…", "Category": "Labor", "Cost": 2010, "Assigned To": "[…]", "Project": "[…]", "Paid Out Date (2/3)": null, "Paid Reference (3/3)": null}],
  "financials":     [{"url": "…", "Project": "[…]", "Costs Complete": "__YES__", "Commission Paid Out": "__NO__", "Commission Amount": 812.5}],
  "work_orders":    [{"url": "…", "Generated Reference": "WO-…", "Status": "Done", "Project": "[…]", "Budget Expense ($$ Payout)": 300}],
  "payments":       [{"url": "…", "Amount": 3000, "Projects": "[…]"}],
  "team":           [{"url": "…", "Name": "Roy", "Role": "[…]", "Pay method": "Cash"}],
  "flooring_lines": []
}
```

Accepted value shapes: relations as a list or a JSON-array string of page urls;
checkboxes as `__YES__` / `__NO__` or booleans; dates as `YYYY-MM-DD` or the SQL
`date:<Name>:start` column. **Scope:** every cost row with no paid date and no paid
reference, every Financials row whose commission is not paid, and the projects, work
orders, payments and team rows those reference — plus 12 months of paid Labor rows
for the band. A formula the API will not resolve (`Commission Amount`) may be absent;
the run flags it rather than computing its own.

## Output

```json
{
  "contract": "payout-run-1",
  "run": "2026-09",
  "as_of": "2026-10-01",
  "write_mode": "plan_only",
  "summary": {"payees": 4, "total": 11872.34, "flagged_lines": 2, "held_labor": 1,
              "held_commission": 1, "blockers": 3, "ar_flags": 2},
  "payees": [{
    "payee": "Roy", "payee_url": "…", "pay_method": "Cash", "total": 9385.0,
    "lines": [{"kind": "labor", "pp": "PP-461", "cost_url": "…", "title": "…",
               "amount": 2010.0, "cost_source": "Our calc", "flags": []}],
    "flags": [], "flagged_lines": 0,
    "bank_cross_check": [{"date": "…", "amount": 2010.0, "reference": "…", "matches_total": true}]
  }],
  "held": {
    "labor": [{"kind": "labor", "pp": "PP-450", "payee": "Luxevista", "amount": 1642.0,
               "open_work_orders": ["WO-…"], "days_held": 21, "…": "…"}],
    "commission": [{"kind": "commission", "pp": "PP-417", "claimant": "Pourya",
                    "amount": 950.0, "open_work_orders": ["WO-…"]}]
  },
  "blockers": [{"pp": "PP-461", "category": "Disposal", "issue": "cost missing"}],
  "ar_flags": [{"pp": "PP-…", "balance_owing": 2009.07, "note": "…"}],
  "lightspeed_flags": [{"pp": "PP-471", "flag": "zero_cost_line, provisional_open_sale"}],
  "labor_bands": {"_overall": {"n": 431, "low": 0.08, "high": 0.41}, "Flooring": {"…": "…"}}
}
```

### Line kinds

| `kind` | Source | Paid when |
|---|---|---|
| `labor` | Project Costs, Category Labor (incl. `Work Order Payment:` rows) | No open work order on the project (Decision 2). Customer balance never holds it. |
| `disposal`, `delivery`, `other` | Project Costs | Cost present and a real payee. |
| `wo_deduction` | QA Work Order, `Charge to = Installer`, status Done | Negative line on the project's installer (Q5). Default `Titan` = no line. |
| `commission` | Project Financials | Costs Complete AND no open WO, or `Commission Release Override` (Decision 7). One line per claimant per project; Pourya with both roles = one line. Two eligible claimants with no `split_rule` → held, "split undecided". |

Non-Flooring Materials rows are Titan's own stock and never produce a payee line.

### Held, blockers, flags

- **`held.labor`** — "Held — carried from prior runs": labor on a project with an open
  work order, with `days_held` from the project end date. Carried every month until
  the work orders close.
- **`held.commission`** — "Held — waiting on WO", the open work orders listed.
- **`blockers`** — nothing is paid until fixed: cost missing; no real payee (empty,
  or a placeholder like `None` / `Titan Flooring Inc.`); commission waiting on Costs
  Complete; a back-charge on a project with several contractors.
- **Line flags** (the only lines Albert needs to read): sub invoice ≠ quote; labor ≠
  quoted with no change-order reason; manual rate override; labor share outside the
  band (overall band when the project type has fewer than `min_samples_per_group`);
  auto-extracted disposal; margin below the 20% floor; commission amount unreadable;
  back-charge confirmation; override used.
- **`ar_flags`** — balance owing on the post-discount total, for office admin. Holds
  nothing.
- **`lightspeed_flags`** — for projects on the run: no PP-tagged sale, zero-cost line,
  zero-revenue sale, open (parked) sale, multiple sales.
- **`bank_cross_check`** — outgoing Interac notices whose recipient resembles the
  payee. Information only.
