# Costs Plan Contract — costs-plan-1

The day's proposed Notion changes for the payout flow. One file per day, overwritten
on re-run:

```
plans/YYYY-MM-DD/costs-plan.json
```

Built by `scripts/project_costs_sync.py` from the Notion finance snapshot
(`contracts/payout-run-schema.md` → notion-finance-1, plus the Payments Log `Message`
column and any `payout_batches` rows), `ingest/<date>/ls-sales.json` and
`ingest/<date>/ls-orders.json`. Applied by `/project-costs-sync` **only** while
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
    "fields": {"Cost": 228.3, "NFM Revenue (pre-tax)": 515.64, "LS Sale IDs": "…", "Cost source": "Lightspeed"},
    "confidence": "High",
    "reason": "Lightspeed NFM cost-of-goods 228.30, pre-tax revenue 515.64 over 1 sale(s)"
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
| `nfm_cost` | Project Costs (NFM row) | write: `Cost`, `NFM Revenue (pre-tax)`, `NFM POS Total (incl. tax)`, `LS Sale IDs`, `Cost source = Lightspeed`; suggest: suggestion fields |
| `flooring_cost_rate` | Titan Projects (per flooring line) | `sku, product, sqft, ls_sale_cost_rate, po_cost_rate, po_reference` — always `suggest` until Flooring Line Items carry the rate columns |
| `financials_relations` | Project Financials | `Costs` ← the project's `Project Costs` |
| `costs_complete` | Project Financials | `Costs Complete` |
| `payment_project` | Master Payments Log | `Suggested Project`, `Match Confidence`, `Match Reason` |
| `stamp_paid` | Project Costs | `Paid Out Date (2/3)`, `Paid Reference (3/3)` from a Payout Batch Albert marked `Paid` |

Every applied action is one `actions-log.json` entry (`notion_update_page`, agent
`.claude/commands/project-costs-sync.md`, `raw_ref_action_id` = the action `id`).
