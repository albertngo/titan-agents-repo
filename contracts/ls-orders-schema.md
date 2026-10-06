# Lightspeed Purchase Orders Contract — ls-orders-1

Supplier purchase orders (stock orders) and their line costs, for the payout flow's
flooring cost check (amendment §2.3–2.4). One file per day, overwritten on re-run:

```
ingest/YYYY-MM-DD/ls-orders.json
```

Produced by `scripts/ls_orders_pull.py` (read only). Read by
`scripts/project_costs_sync.py`. On X-Series a purchase order is a **consignment of
type SUPPLIER**; its lines are **consignment products** (`platform-settings/lightspeed.json`
→ `api.consignments`, verified live 2026-10-06).

## Envelope

```json
{
  "contract": "ls-orders-1",
  "source": "lightspeed-orders",
  "pulled_at": "…",
  "window": {"since": "2026-04-09", "days": 180},
  "counts": {"supplier_pos_in_window": 209, "pp_tagged": 4, "lines": 376, "projects": 4,
             "ambiguous_pp_pos": 0, "products_with_po_cost": 222},
  "projects": {"439": {"pp": "PP-439", "po_ids": ["…"], "cost_total": 4689.34,
                       "flags": ["not_yet_received"], "purchase_orders": [ …po… ]}},
  "ambiguous_pp_pos": [{"consignment_id": "…", "reference": "PO-…", "po_date": "…", "pp_candidates": ["…", "…"]}],
  "product_po_cost": {"<product_id>": {"unit_cost": 3.39, "po_reference": "PO-8143",
                       "po_date": "…", "status": "SENT", "supplier": "VIDAR"}},
  "api_stats": {…}
}
```

## Purchase order

| Field | Meaning |
|---|---|
| `consignment_id` | Join key. |
| `reference` | `PO-<n>`. |
| `supplier_invoice` | Bare number when front desk typed one (rare). |
| `supplier` | Business name from `/suppliers`; null when the supplier record is gone. |
| `status` | OPEN / SENT / RECEIVED. |
| `po_date`, `due_at`, `received_at` | `po_date` = `consignment_date`, else `created_at`. |
| `pp`, `pp_candidates` | Parsed from the PO `name` with the shared regex (`payout-policy.json`). |
| `lines[]` | `product_id, count (decimal sqft allowed), received, unit_cost, cost_total, status`; on PP-tagged POs also `sku, product_name` (one product GET each), so a flooring line is named by what was ordered. |

## Two ways a PO cost reaches a project

1. **By project** — the PO `name` carries `PP-###` (`projects`). Strong: front desk
   said which job it was for. **Rare today** (4 of 209 POs in the window); the staff
   rule in `methods/payouts.md` makes it the norm.
2. **By product** — `product_po_cost` holds the latest PO line cost per product in the
   window, PP or not. Weaker: it says what Titan last paid for that SKU, not what it
   paid for *this* job. `project_costs_sync.py` uses it only as a Medium-confidence
   suggestion when (1) is missing.

## Flags (project)

| Flag | Meaning |
|---|---|
| `not_yet_received` | At least one PO is OPEN or SENT — expected cost, not yet delivered. |
| `multiple_pos` | More than one PO carries the number (split delivery, or a duplicate). |

## Personal data

The PO `name` carries customer first names and is **never written**; only the parsed
project number is kept.
