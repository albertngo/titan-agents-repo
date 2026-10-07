---
description: Bring a HikePOS product export up to date from Airtable for one supplier — update existing rows (never Name or SKU), add new products with the Airtable SKU. Writes a file to import; touches no platform.
---

# /hike-update `<SUPPLIER>`

Method and schema: `methods/hike-pos.md`. Registry: `platform-settings/hike.json`. Script:
`scripts/hike_update.py`. `<SUPPLIER>` is a key under the registry's `suppliers` (e.g. `FAW`);
no entry → stop and ask Albert for the supplier's markup and Hike supplier name.

## Steps

1. **Get the Hike export** from Albert (Hike → Products → EXPORT). Save it unchanged as
   `ingest/<date>/hike_<scope>_export_<date>.xlsx`. If it is more than a day old, ask for a
   fresh one: stock columns are re-imported as exported.
2. **Snapshot Airtable.** MCP `list_records_for_table`, base `appWHOVZ0QCS0xQ3M`, table
   `tblfLXD3zkSdNQGbS`, filter `Supplier` = the registry's `airtable_supplier_choice_id`,
   `fieldIds` = `hike_update.SNAPSHOT_FIELD_IDS`, `pageSize` 1000. Save the raw result as
   `ingest/<date>/<scope>_airtable_snapshot.json`.
3. **Run** `python3 scripts/hike_update.py --supplier <SUPPLIER> --hike-export … --airtable-snapshot …
   --ls-snapshot <latest ingest/*/lightspeed-products.json> --out ingest/<date>/hike_<scope>_products_<date>.xlsx
   --report ingest/<date>/hike_<scope>_report_<date>.csv`.
4. **Read the report.** Every `hike_only` row that is active and names a colour Airtable has
   under a different spelling → add it to `colour_aliases` (checked by eye, never guessed) and
   re-run. Every `ambiguous` note → resolve in `manual_matches`. Never fuzzy-match.
5. **Verify** the output against the export: Name, SKU, Barcode and the stock columns are
   identical on every existing row; no SKU or Name appears twice.
6. **Hand over** the `.xlsx` and the report. Albert imports it in Hike (Products → IMPORT).
   Commit the export, snapshot, output and report.

## Rules that do not bend

- Never change `Name`, `SKU` or `Barcode` on an existing row: Hike makes a new product.
- Never write stock, average cost, slug or image on an existing row.
- Hike-only rows stay exactly as exported unless Albert says otherwise.
- Retail is cost + the registry `markup` (Hike's own), not Airtable's Retail.
