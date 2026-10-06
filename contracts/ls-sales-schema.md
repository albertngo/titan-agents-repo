# Lightspeed Sales Contract — ls-sales-1

Project-tagged Lightspeed X-Series sales, for the payout flow. One file per day,
overwritten on re-run (an ingest file, not a log):

```
ingest/YYYY-MM-DD/ls-sales.json
```

Produced by `scripts/ls_sales_pull.py` (read only). Read by
`scripts/project_costs_sync.py` and `scripts/payout_run.py`; anything else may read it.
Rules, windows, the PP regex and the flooring-category list live in
`platform-settings/payout-policy.json`; API shape in `platform-settings/lightspeed.json`
→ `api.sales`. Method: `methods/payouts.md`.

## Envelope

```json
{
  "contract": "ls-sales-1",
  "source": "lightspeed-sales",
  "pulled_at": "2026-10-06T09:00:12-04:00",
  "window": {"date_from": "2026-06-08T00:00:00Z", "date_to": null, "days": 120},
  "pp_filter": null,
  "counts": {"sales_total": 966, "voided_skipped": 16, "pp_tagged": 32, "projects": 31,
             "untagged_pack_sales": 22, "ambiguous_pp_sales": 0},
  "projects": { "463": { ...project... } },
  "untagged_pack_sales": [{"sale_id": "…", "receipt": "R-…", "sale_date": "…", "state": "closed"}],
  "ambiguous_pp_sales": [{"sale_id": "…", "receipt": "…", "sale_date": "…", "state": "…", "pp_candidates": ["411", "416"]}],
  "api_stats": {"requests": 17, "throttle_events": [], "api_version": "2.0"}
}
```

## Project

Keyed by the bare project number as a string (`"463"`, `"1000"`), sorted numerically.

| Field | Meaning |
|---|---|
| `pp` | `"PP-463"` |
| `sale_ids` | Every sale filed on this project, oldest first. **The join key is the sale `id`** — receipt numbers repeat across sales. |
| `sales[]` | One record per sale (below). |
| `totals_by_class` | Sum over the sales, per class: `{flooring, nfm, unclassified} → {revenue_pretax, tax, cost}`. |
| `flooring_lines[]` | Every flooring line across the sales: `sale_id, product_id, sku, product_name, category, quantity (= sqft), unit_price, unit_cost, price_total_pretax, cost_total, is_return`. |
| `flags` | Union of sale flags, plus `multiple_sales` when more than one sale carries the number. |

## Sale

| Field | Meaning |
|---|---|
| `sale_id`, `receipt`, `sale_date`, `state`, `status` | From Lightspeed. `state` ∈ parked / pending / closed (voided sales are dropped). |
| `keyword` | The `@pack` / `@order` / `@stock` / `@return` / `@material` keyword in the note, or null. |
| `pp`, `pp_candidates` | The parsed number; `pp` is null when the note carries two different numbers. |
| `total_price_pretax`, `total_tax`, `total_cost` | Sale totals (card surcharges in `adjustments` are excluded, as in Lightspeed's own `total_price`). |
| `totals_by_class` | As above, for this sale. |
| `lines[]` | Non-voided lines: `line_id, product_id, sku, product_name, category, class, quantity, unit_price, unit_cost, price_total_pretax, tax_total, cost_total, is_return, zero_cost?, flags`. |
| `flags` | See below. |

## Classes

A line is **flooring** when its product's Lightspeed category leaf is in
`payout-policy.json → lightspeed.flooring_category_leaves`, **nfm** for any other
known leaf, **unclassified** when the product has no category (delivery, discount and
some service items). Flooring quantity is square feet.

## Flags

| Flag | Level | Meaning |
|---|---|---|
| `provisional_open_sale` | sale | Parked or pending: totals can still change. Re-pulled every run. |
| `zero_cost_line` | line/sale | A line with cost 0 that is not an expected non-stock item. Sale-line cost is frozen at sale time, so it never fills in — the PO cost (`ls-orders.json`) becomes the suggestion. |
| `zero_revenue_sale` | sale | Revenue 0 with cost > 0 (e.g. closed at a 100% discount). Distorts margin; always reviewed. |
| `unclassified_line` | line/sale | No category on the product. Neither flooring nor NFM until resolved. |
| `ambiguous_pp` | sale | Note carries two different project numbers; filed on neither. |
| `multiple_sales` | project | More than one sale carries the number. Legitimate (split invoices), shown so a duplicate is caught. |

## Personal data

No note text, no customer id, no customer name. Product names are catalogue data.
