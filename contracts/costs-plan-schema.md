# Costs Plan Contract — costs-plan-1

The day's proposed Notion changes for the payout flow. One file per day, overwritten
on re-run:

```
plans/YYYY-MM-DD/costs-plan.json
```

Built by `scripts/project_costs_sync.py` from the Notion finance snapshot
(`contracts/payout-run-schema.md` → notion-finance-1, plus the Payments Log `Message`
column and any `payout_batches` rows), `ingest/<date>/ls-sales.json` and
`ingest/<date>/ls-orders.json` and `ingest/<date>/supplier-docs.json`. Applied by `/project-costs-sync` **only** while
`payout-policy.json → write_mode.project_costs_sync` is `write`.

```json
{
  "contract": "costs-plan-1",
  "built_at": "…",
  "write_mode": "plan_only",
  "counts": {"nfm_cost": {"write": 3, "suggest": 2}, "payment_project": {"write": 0, "suggest": 4}},
  "actions": [{
    "id": "nfm_cost:3f2a9c1b0e",
    "kind": "nfm_cost",
    "target_url": "https://www.notion.so/…",
    "pp": "PP-463",
    "mode": "write",
    "fields": {"Cost": 582.67, "LS Sale IDs": "…", "Cost source": "Lightspeed"},
    "confidence": "High",
    "reason": "Lightspeed NFM POS total 582.67 incl. tax over 1 sale(s)"
  }],
  "notes": [{"pp": "PP-…", "note": "2 Financials rows point at this project — fix by hand"}],
  "ls_untagged_pack_sales": 22
}
```

## Modes

- **`write`** — sources agree and the field is empty or owned by the sync
  (`Cost source` ∈ `notion-finance.json → project_costs.sync_owned_sources`). Applied
  without review.
- **`suggest`** — sources disagree, the source is weak, the sale is still open, or
  the field holds a **hand-entered** value. Written only into the row's suggestion
  fields (`Suggested Cost`, `Suggestion source/confidence/reason`, or the Payments Log
  `Suggested Project` / `Match …` fields), which feed the "Costs to confirm" and
  "Payments to confirm" views. **A suggestion never changes `Cost`, `Projects` or
  any field a person typed.** When every source agrees there is no action at all.

`id` is a hash of kind + target + fields: the same proposal keeps the same id across
re-runs, so the actions log can skip what was already applied.

## Kinds

| Kind | Target | Fields |
|---|---|---|
| `ls_sale_found` | Titan Projects | `LS Sale Found` |
| `nfm_cost` | Project Costs (NFM row) | write: `Cost` = Lightspeed NFM POS total incl. tax (today's meaning, Decision 10), `LS Sale IDs`, `Cost source = Lightspeed`; suggest: suggestion fields |
| `flooring_line` | Flooring Line Items (`op: update`) or the project (`op: create`) | `Cost Rate` = best ordered source (below), `Invoice Cost Rate`, `PO Cost Rate`, `LS Sale Cost Rate`, `Cost Locked`; on create also `Floor SKU` (the **ordered** SKU), `Sqft Sold`, `Project`, `Project Financials`; `Sold At Rate` ← the line's `Quote Rate` only. Extra keys: `op`, `stage`, `flags` |
| `financials_relations` | Project Financials | `Costs` ← the project's `Project Costs` |
| `costs_complete` | Project Financials | `Costs Complete` |
| `payment_project` | Master Payments Log | `Suggested Project`, `Match Confidence`, `Match Reason` |
| `stamp_paid` | Project Costs | `Paid Out Date (2/3)`, `Paid Reference (3/3)` from a Payout Batch Albert marked `Paid` |

## `flooring_line` (Decisions 17–18, Albert 2026-10-06)

One action per flooring product ordered for the project (PP-tagged LS purchase order →
the supplier order that prints its PO number), paired with the Lightspeed sale line.

**Cost stages**, best first (`payout-policy.json → flooring_cost.cost_stages`):

| `stage` | `Cost Rate` | Mode |
|---|---|---|
| `invoice_final` | invoice $ − credit memo $ ÷ sqft kept (restocking fees land here) | `write`, `Cost Locked` ✓ — replaces any earlier figure |
| `invoice_partial` | invoiced so far ÷ sqft invoiced | `write` |
| `confirmation` | supplier confirmation $/sqft | `write` into an empty line, else `suggest` |
| `purchase_order` | LS PO cost (front desk) | same, Medium |
| `purchase_order_untagged` | latest PO for the product, not project-linked | `suggest`, Low |
| `ls_sale` | the sale-line cost (nothing ordered under the PP) | `suggest`, Low |

A new invoice or credit memo changes the figures, so the action reappears with a new
`id`; on a locked line it carries `changed_after_lock`. A line whose fields already
match produces no action. `Sold At Rate` is **never** taken from Lightspeed.

**Flags:** `pm_entry_product_mismatch` (sale keyed a different product than ordered),
`sale_cost_gap`, `po_rate_gap` (front desk's PO vs the supplier, > $0.10/sqft),
`rate_changed_after_confirmation`, `restocking_fee`, `credit_attributed_by_product`,
`po_not_received_in_lightspeed`, `confirmed_not_invoiced` (> 21 days), `qty_gap` (kept
vs sold, > 1 box), `ordered_not_on_sale`, `no_project_po`, `no_order_found`,
`quote_rate_missing`, `changed_after_lock`.

Every applied action is one `actions-log.json` entry (`notion_update_page`, agent
`.claude/commands/project-costs-sync.md`, `raw_ref_action_id` = the action `id`).
