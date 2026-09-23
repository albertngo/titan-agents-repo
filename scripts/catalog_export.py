#!/usr/bin/env python3
"""Re-render a run's two CSVs from the live systems, after the writes. READ ONLY.

    python3 scripts/catalog_export.py \
        --upload        ingest/<date>/<slug>_airtable_upload_<date>.csv \
        --ls-upload     ingest/<date>/<slug>_ls_upload_<date>.csv \
        --airtable-live /tmp/<slug>_airtable_live.json \
        --lightspeed    ingest/<date>/lightspeed-products.json

Why (Albert, 2026-09-23): every run keeps BOTH files on the Notion row, the Airtable
CSV and the Lightspeed CSV, so the uploaded items can be seen, and re-imported by
hand if needed, without opening either system. Until now the CSVs showed what the
sheet said before the sync, the Lightspeed file was skipped on promo-only and
status-only runs, and nothing put a new product's Lightspeed UUID back into the
Airtable file. After this step:

- The **Airtable CSV** holds, for every SKU on the run, the record exactly as it is
  live in Airtable now: every column, Lightspeed ID included. A SKU Airtable does
  not hold (a held or refused create) keeps its extracted row untouched, so a re-run
  can still pick it up. A blank Lightspeed ID is filled from the live Lightspeed
  pull by sku, so the file carries the POS UUID even where the Airtable backfill has
  not run.
- The **Lightspeed CSV** holds one row per SKU as it is live on the POS now (id,
  handle, name, prices, supplier, category, active), in the import column order.
  Columns the pull does not carry (description, brand, tags) come from the run's
  own LS row where one exists. A SKU that is not on the POS keeps its extracted row
  if it had one, and is otherwise left out: there is nothing live to show.

Both files are rewritten in place. The pre-sync version is the commit
/process-price-list made, so git shows exactly what the sync changed.

Inputs are files, never API calls: the run saves list_records_for_table output
read after the writes, and refreshes the Lightspeed pull (`lightspeed_pull.py
--refresh`) after its own writes. Airtable returns cells keyed by field id; the
id -> name map is platform-settings/airtable-master-catalogue-fields.json unless
--schema points at fresh list_tables_for_base output. A CSV column that map does
not know is reported, because that is what a renamed Airtable field looks like.
This script writes only the two CSVs.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA = REPO_ROOT / "platform-settings/airtable-master-catalogue-fields.json"
# Columns the upload CSV carries for the reviewer that are not Airtable fields.
HELPER_COLUMNS = {"MatchedRecId", "MatchStatus", "LS Match status"}

SKU = "SKU"
LS_ID = "Lightspeed ID"
MATCHED_REC = "MatchedRecId"
MATCH_STATUS = "MatchStatus"

# The import column order from ls-upload-instructions, with the live outlet name
# (platform-settings/lightspeed.json -> outlet.name). Used only when the run built no
# LS file of its own; otherwise that file's header is kept as-is.
DEFAULT_LS_HEADER = [
    "id", "handle", "sku", "comp4", "comp5", "comp6", "name", "description",
    "product_category", "variant_option_one_name", "variant_option_one_value",
    "opt2n", "opt2v", "opt3n", "opt3v", "tags", "supply_price", "retail_price",
    "loyalty1", "loyalty2", "loyalty3", "loyalty4", "brand_name", "supplier_name",
    "supplier_code", "active", "track_inventory",
    "outlet_tax_Mississauga Outlet", "inventory_Mississauga Outlet",
    "reorder_point_Mississauga Outlet", "restock_level_Mississauga Outlet",
]
# Variant columns sit in pairs after product_category, whatever a file calls them.
VARIANT_PAIR_START = 9


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path, header, rows):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def load_schema(path):
    """{field_id: (name, type)} from list_tables_for_base output, the committed
    registry ({"fields": {id: {name, type}}}), or a plain {id: name} map."""
    data = json.loads(Path(path).read_text())
    if isinstance(data.get("fields"), dict):
        return {fid: (f["name"], f.get("type")) for fid, f in data["fields"].items()}
    if "tables" not in data:
        return {fid: (name, None) for fid, name in data.items()}
    fields = {}
    for table in data["tables"]:
        for field in table.get("fields", []):
            if "name" in field:
                fields[field["id"]] = (field["name"], field.get("type"))
    if not fields:
        raise SystemExit(f"{path}: no field names found — pass list_tables_for_base "
                         "output (get_table_schema carries ids only).")
    return fields


def load_live_records(paths, schema):
    """{sku: (record_id, {field name: value})}. Accepts list_records_for_table output
    ({"records": [...]}) or a bare list, keyed by field id or by field name."""
    by_sku, types = {}, {}
    for path in paths:
        data = json.loads(Path(path).read_text())
        records = data.get("records", data) if isinstance(data, dict) else data
        for rec in records:
            cells = rec.get("cellValuesByFieldId") or rec.get("fields") or {}
            named = {}
            for key, value in cells.items():
                name, ftype = schema.get(key, (key, None))
                named[name] = value
                types[name] = ftype
            sku = named.get(SKU)
            if sku:
                by_sku[str(sku).strip()] = (rec.get("id"), named)
    return by_sku, types


def fmt_airtable(value, ftype):
    """One live cell as the upload CSV spells it."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("name", value.get("id", "")))
    if isinstance(value, list):
        return ", ".join(fmt_airtable(v, None) for v in value)
    if isinstance(value, bool):
        return "TRUE" if value else ""
    if ftype == "checkbox":
        return "TRUE" if value else ""
    if ftype == "currency" and isinstance(value, (int, float)):
        return f"{value:.2f}"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def load_lightspeed(path):
    payload = json.loads(Path(path).read_text())
    products = payload.get("products", payload)
    return {str(p["sku"]).strip(): p for p in products if p.get("sku")}


def money(value):
    return "" if value is None else f"{float(value):.2f}"


def airtable_rows(header, rows, live, types, ls):
    out, stats = [], {"live": 0, "kept_extracted": 0, "ls_id_from_lightspeed": 0}
    for row in rows:
        sku = (row.get(SKU) or "").strip()
        new = dict(row)
        hit = live.get(sku)
        if hit:
            rec_id, fields = hit
            stats["live"] += 1
            for col in header:
                if col in types:  # a real Airtable field: live wins, empty included
                    new[col] = fmt_airtable(fields.get(col), types[col])
            if MATCHED_REC in header:
                new[MATCHED_REC] = rec_id or new.get(MATCHED_REC, "")
            # It is in the catalogue now. Left at `new`, a re-run of the reconciler on
            # this file would treat the row as a create and rewrite every column.
            if MATCH_STATUS in header:
                new[MATCH_STATUS] = "matched"
        else:
            stats["kept_extracted"] += 1
        product = ls.get(sku)
        if LS_ID in header and not (new.get(LS_ID) or "").strip() and product:
            new[LS_ID] = product["id"]
            stats["ls_id_from_lightspeed"] += 1
        out.append(new)
    return out, stats


def ls_rows(header, skus, existing, ls):
    """One row per SKU in the Airtable file's order."""
    by_sku = {(r.get("sku") or "").strip(): r for r in existing}
    variant_cols = header[VARIANT_PAIR_START:VARIANT_PAIR_START + 6]
    out, stats = [], {"live": 0, "kept_extracted": 0, "omitted": 0}
    for sku in skus:
        base = by_sku.get(sku)
        product = ls.get(sku)
        if not product:
            if base:
                out.append(base)
                stats["kept_extracted"] += 1
            else:
                stats["omitted"] += 1
            continue
        row = dict(base) if base else {h: "" for h in header}
        row.update({
            "id": product.get("id", ""),
            "handle": product.get("handle") or row.get("handle", ""),
            "sku": sku,
            "name": product.get("name") or row.get("name", ""),
            "product_category": product.get("category") or row.get("product_category", ""),
            "supply_price": money(product.get("supply_price")),
            "retail_price": money(product.get("price_excluding_tax")),
            "supplier_name": product.get("supplier_name") or row.get("supplier_name", ""),
            "active": "1" if product.get("active") else "0",
        })
        options = product.get("variant_options") or []
        if options and not base:
            for i, opt in enumerate(options[:3]):
                row[variant_cols[2 * i]] = opt.get("name", "")
                row[variant_cols[2 * i + 1]] = opt.get("value", "")
        out.append(row)
        stats["live"] += 1
    return out, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--upload", required=True, help="The run's Airtable upload CSV; rewritten in place")
    ap.add_argument("--ls-upload", required=True,
                    help="The run's LS upload CSV; rewritten in place, created if the run built none")
    ap.add_argument("--airtable-live", required=True, action="append",
                    help="list_records_for_table output read AFTER the writes. Repeatable")
    ap.add_argument("--schema", default=str(DEFAULT_SCHEMA),
                    help="Field id -> name map. Default: the committed registry")
    ap.add_argument("--lightspeed", required=True,
                    help="Lightspeed pull refreshed AFTER the writes")
    args = ap.parse_args(argv)

    schema = load_schema(args.schema)
    live, types = load_live_records(args.airtable_live, schema)
    # A column is an Airtable field if the schema says so, even when no live record
    # carries a value for it (Airtable omits empty cells from the payload).
    for name, ftype in schema.values():
        types.setdefault(name, ftype)
    ls = load_lightspeed(args.lightspeed)

    header, rows = read_csv(args.upload)
    if SKU not in header:
        raise SystemExit(f"{args.upload}: no {SKU} column")
    unknown = [c for c in header if c not in types and c not in HELPER_COLUMNS]
    if unknown:
        print(f"WARNING: not Airtable fields per {args.schema}, kept as extracted: "
              f"{unknown}. A renamed field looks like this; refresh the map from "
              "list_tables_for_base.", file=sys.stderr)
    at_rows, at_stats = airtable_rows(header, rows, live, types, ls)

    ls_path = Path(args.ls_upload)
    ls_header, ls_existing = read_csv(ls_path) if ls_path.exists() else (DEFAULT_LS_HEADER, [])
    skus = [(r.get(SKU) or "").strip() for r in at_rows if (r.get(SKU) or "").strip()]
    out_ls, ls_stats = ls_rows(ls_header, skus, ls_existing, ls)

    write_csv(args.upload, header, at_rows)
    write_csv(ls_path, ls_header, out_ls)
    print(f"{args.upload}: {len(at_rows)} rows — {at_stats['live']} from live Airtable, "
          f"{at_stats['kept_extracted']} kept as extracted (not in Airtable), "
          f"{at_stats['ls_id_from_lightspeed']} Lightspeed ID filled from the POS")
    print(f"{ls_path}: {len(out_ls)} rows — {ls_stats['live']} from live Lightspeed, "
          f"{ls_stats['kept_extracted']} kept as extracted (not on the POS), "
          f"{ls_stats['omitted']} omitted (on neither)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
