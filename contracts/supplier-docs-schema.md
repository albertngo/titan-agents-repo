# Supplier Documents Contract — supplier-docs-1

Supplier order confirmations, invoices and credit memos, joined into orders, for the
payout flow's flooring cost (Decisions 17–18 in `methods/payouts.md`: what was
ordered is the truth; the invoice net of credits is the final cost). One file per
day, overwritten on re-run, gitignored (Titan's buy prices):

```
ingest/YYYY-MM-DD/supplier-docs.json
```

Produced by `scripts/supplier_docs_pull.py` (read only — app-only Graph GETs on
info@, `pdftotext -layout` on each PDF). Registry: `platform-settings/supplier-docs.json`.
Read by `scripts/project_costs_sync.py`. Vidar only today.

## Envelope

```json
{
  "contract": "supplier-docs-1",
  "source": "supplier-docs",
  "pulled_at": "…",
  "window": {"since": "2026-06-08", "days": 120},
  "counts": {"documents": 66, "confirmation": 40, "invoice": 22, "credit_memo": 4,
             "orders": 32, "errors": 0, "unattributed_credits": 0},
  "orders": {"103273": { …order… }},
  "orders_by_po": {"8135": ["103273"]},
  "unattributed_credits": [{"doc_no": "Cr…", "date": "…", "total": 0, "codes": ["…"],
                            "candidates": ["…", "…"], "reason": "…"}],
  "documents": [ …document… ],
  "errors": [{"folder": "…", "subject": "…", "error": "…"}],
  "api_stats": {"requests": 0}
}
```

## Document

`supplier, doc_type (confirmation | invoice | credit_memo), doc_no, date, po_number`
(bare digits = Lightspeed `PO-<n>`), `estimate_no` (the supplier's sales order; an
invoice prints it, a credit memo does not), `revision` (confirmations: original /
revised / update / cancelled, from the subject), `subtotal, tax, total` (pre-tax
subtotal), `lines[]`, `folder, received_at, message_id_tail`.

A line: `code` (supplier item code), `desc`, `qty` (boxes or pieces), `rate` (per box
or piece), `amount`, `sf_per_box` (from "NN.NN SF/BOX"; null for trims), `sqft`,
`rate_per_sqft`, `restocking_fee`.

## Order

Keyed by estimate number (an invoice with none: `INV<no>`).

| Field | Meaning |
|---|---|
| `po_number` | From the confirmation or invoice. Null → `no_po_number` (ordered by email; cannot reach a project). |
| `status` | `open`; `cancelled` (latest confirmation says so); `superseded` (the same PO was re-confirmed under a newer estimate and this one was never invoiced). |
| `confirmation` | Latest version: `doc_no, date, revision, versions`. |
| `invoices[]`, `credits[]` | `doc_no, date, subtotal, tax, total`; credits carry `attribution`. |
| `products{code}` | `confirmed_qty/sqft/rate_sqft`, `invoiced_qty/sqft/amount/rate_sqft`, `credited_qty/sqft/amount`, `net_qty/sqft/amount`, **`actual_rate_sqft`** = net $ ÷ net sqft, `stage`. |
| `flags[]` | `confirmed_not_invoiced`, `credit_attributed_by_product`, `restocking_fee`, `rate_changed_after_confirmation:<code>`, `superseded_by:<estimate>`, `no_po_number`. |

**Stage** per product: `invoice_final` (everything confirmed has been invoiced),
`invoice_partial`, `confirmation`, `cancelled`, `superseded`.

## Credit memo attribution

A credit memo prints no PO or estimate. It is attached to the **one** order that
invoiced the same supplier code within `credit_attribution.lookback_days` before the
credit date. Zero or several candidates → `unattributed_credits`, never picked.

## Limits

- Only documents filed in the registry's folders are seen.
- Vidar documents from May 2026 and earlier use an older layout that does not parse;
  they appear under `errors`, never guessed. The 120-day window keeps them out.
- Rates are pre-tax. Vidar's "$0.20 discount" is already in the rate; Vidar charges
  no freight (pickup).
