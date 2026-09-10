#!/usr/bin/env python3
"""Pull the Lightspeed (X-Series) product catalogue. READ ONLY.

GET only — this script has no code path that writes to Lightspeed. It imports
scripts/lightspeed_client.py, which exposes GET and pagination and nothing else.
The write side lands separately with the catalogue-sync actions agents, so that
granting a write credential and shipping write code stay two decisions.

This replaces the manual step in the current backfill loop, where a person exports
the LS product list to .xlsx by hand before ls-id-backfill can run.

The products endpoint has no server-side supplier filter, so the walk fetches the
whole catalogue once, caches the raw records, and filters locally. The cache lives
under analysis/cache/ (gitignored, regenerable) so a re-run during a sync does not
re-page the catalogue and spend rate-limit budget for nothing. --refresh forces a
new walk.

Usage:
    # First run against a live account — dump the real response shape and stop.
    # Do this before trusting the pagination config; nothing is cached or written.
    python3 scripts/lightspeed_pull.py --probe

    # Full catalogue -> ingest/<today>/lightspeed-products.json
    python3 scripts/lightspeed_pull.py

    # One supplier, from cache if today's walk already happened
    python3 scripts/lightspeed_pull.py --supplier "Lee Flooring"

    # Compare a pull against a hand-exported LS workbook (the Phase 1 check)
    python3 scripts/lightspeed_pull.py --compare-export ingest/2026-09-03/grandeur_ls_product_export_2026-09-03.xlsx

Environment: LIGHTSPEED_DOMAIN_PREFIX, LIGHTSPEED_PERSONAL_TOKEN — see .env.example.
Config: platform-settings/lightspeed.json.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lightspeed_client import LightspeedClient, LightspeedError, load_config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "analysis" / "cache"
TZ = ZoneInfo("America/Toronto")

# Where a supplier name lives on an LS product record. Verified against the live
# catalogue 2026-09-10 (14,525 products): `supplier` is an object carrying `name`
# on 13,079 of them, 1,440 carry no supplier at all, and 6 have it only under
# `product_suppliers[].supplier_name`. The two never disagreed where both were
# present. A flat `supplier_name` key does not exist on the API (it is a CSV
# import/export column) but is kept first as a cheap no-op.
SUPPLIER_PATHS = (("supplier_name",), ("supplier", "name"), ("supplier",))


def today():
    return datetime.now(TZ).date().isoformat()


def dig(record, path):
    """Walk a tuple path through nested dicts, returning None on any miss."""
    cur = record
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def supplier_of(record):
    """The supplier name on an LS product, or None if it carries none.

    Note for anything joining on this: LS supplier names are their OWN namespace,
    neither Notion's nor Airtable's, and they are not one-to-one. The live
    catalogue holds 116 distinct names against 24 Airtable supplier choices, with
    several real suppliers split across more than one LS record — OLYMPIA (292)
    beside Olympia Tile (2,926), LEE (2) beside Lee Flooring (84), UMB beside
    Umbrellar, MARMOCA beside MARMOCA TILE, CIF Distributors beside CIF LTD.
    Join products on `sku` instead; it is unique and always present (verified:
    0 blanks and 0 duplicates across all 14,525). Supplier is for reporting.
    """
    for path in SUPPLIER_PATHS:
        value = dig(record, path)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for entry in (record.get("product_suppliers") or []):
        if isinstance(entry, dict):
            name = entry.get("supplier_name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return None


def category_of(record):
    """The LS category leaf name, or None.

    `product_category` comes back as an object carrying `name` (14,043 of 14,525;
    the rest are null), and the name is the LEAF ALONE — 'SPC', 'TILE',
    'ENGINEERED HARDWOOD' — never the ' / '-separated path the CSV importer
    takes. The two are different vocabularies for the same concept; see
    product_categories in platform-settings/lightspeed.json.
    """
    cat = record.get("product_category")
    if isinstance(cat, dict):
        name = cat.get("name")
        return name.strip() if isinstance(name, str) and name.strip() else None
    if isinstance(cat, str) and cat.strip():
        return cat.strip()
    return None


# The fields anything downstream actually reads. A raw product carries 56 fields
# and the full catalogue is ~41 MB of JSON — images, product_codes, descriptions
# and nested supplier/category objects are most of it. The slim projection is
# ~9 MB and is what gets written by default; --full keeps every field.
SLIM_FIELDS = ("id", "sku", "handle", "name", "variant_name", "supply_price",
               "price_including_tax", "price_excluding_tax", "active", "has_variants",
               "variant_parent_id", "variant_options", "variant_count", "version",
               "updated_at")


def slim(record):
    """One product, reduced to what the catalogue sync needs.

    `supplier_name` and `category` are flattened here so downstream never has to
    know that the API nests them in objects while the CSV keeps them flat.
    """
    out = {k: record.get(k) for k in SLIM_FIELDS}
    out["supplier_name"] = supplier_of(record)
    out["category"] = category_of(record)
    return out


def probe(client, page_size):
    """Fetch one page and describe it. Writes nothing, caches nothing.

    This exists because the pagination envelope and the product field names are
    configured, not verified — everything downstream assumes them. Run this first
    against a real account and reconcile platform-settings/lightspeed.json with
    what it prints.
    """
    body = client.get(client.products_path(), {client.page_size_param: page_size})
    print("=== response envelope ===")
    if isinstance(body, dict):
        for key, value in body.items():
            if key == "data" and isinstance(value, list):
                print(f"  {key}: list of {len(value)}")
            else:
                print(f"  {key}: {json.dumps(value)[:200]}")
    else:
        print(f"  (bare {type(body).__name__}, length {len(body) if hasattr(body, '__len__') else '?'})")

    records = body.get("data", body) if isinstance(body, dict) else body
    if not isinstance(records, list) or not records:
        print("\nNo records returned — cannot describe a product.")
        return 1

    first = records[0]
    print(f"\n=== first product: {len(first)} fields ===")
    for key in sorted(first):
        print(f"  {key}: {json.dumps(first[key])[:120]}")

    cfg = client.cfg["api"]["pagination"]
    print("\n=== reconcile against platform-settings/lightspeed.json ===")
    print(f"  cursor_field   {cfg['cursor_field']!r}: "
          f"{'present' if cfg['cursor_field'] in first else 'MISSING on the record'}")
    vb = body.get("version") if isinstance(body, dict) else None
    print(f"  version block  : {'present -> ' + json.dumps(vb) if vb else 'absent (cursor comes from records)'}")
    print(f"  supplier name  : {supplier_of(first)!r} via {[p for p in SUPPLIER_PATHS if dig(first, p)]}")
    print(f"\n  requests made  : {client.request_count}")
    return 0


def walk(client, max_pages=None):
    products = list(client.paginate(client.products_path(), max_pages=max_pages))
    return products


def cache_path(date):
    return CACHE_DIR / f"lightspeed-products-{date}.json"


def load_or_walk(client, date, refresh, max_pages):
    path = cache_path(date)
    if path.exists() and not refresh:
        cached = json.loads(path.read_text())
        print(f"cache hit: {path.relative_to(REPO_ROOT)} "
              f"({len(cached['products'])} products, walked {cached['walked_at']}) "
              f"— pass --refresh to re-walk", file=sys.stderr)
        return cached["products"], True

    products = walk(client, max_pages=max_pages)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "walked_at": datetime.now(TZ).isoformat(),
        "api_version": client.api_version,
        "stats": client.stats(),
        "products": products,
    }, indent=1) + "\n")
    print(f"walked {len(products)} products in {client.request_count} requests "
          f"-> cached at {path.relative_to(REPO_ROOT)}", file=sys.stderr)
    return products, False


def compare_export(products, export_path):
    """Check a pull against a hand-exported LS workbook.

    The committed exports are the only ground truth available before this script
    has ever run live, so this is the Phase 1 verification: every SKU in the
    export should appear in the pull, carrying the same UUID. Genuine drift since
    the export was taken is expected and is reported, not treated as failure.
    """
    try:
        from openpyxl import load_workbook
    except ImportError:
        print("openpyxl is required for --compare-export (pip install openpyxl)", file=sys.stderr)
        return 2

    # NOT read_only=True. These exports declare a wrong worksheet dimension, and
    # read_only mode trusts the declaration — it reports 1 column and 0 data rows
    # for a 33-column, 267-row sheet. Verified against the two committed exports
    # 2026-09-10. They are under 100 KB, so a normal load costs nothing.
    ws = load_workbook(export_path, data_only=True).active
    rows = ws.iter_rows(values_only=True)
    header = [str(c).strip().lower() if c is not None else "" for c in next(rows)]
    try:
        sku_col, id_col = header.index("sku"), header.index("id")
    except ValueError:
        print(f"export {export_path} has no 'sku'/'id' column; header was {header[:12]}",
              file=sys.stderr)
        return 2

    export = {}
    for row in rows:
        sku = row[sku_col]
        if sku is None or str(sku).strip() == "":
            continue
        export[str(sku).strip()] = (str(row[id_col]).strip() if row[id_col] else None)

    pulled = {}
    for p in products:
        sku = p.get("sku")
        if sku is not None and str(sku).strip():
            pulled[str(sku).strip()] = p.get("id")

    missing = sorted(s for s in export if s not in pulled)
    mismatched = sorted(s for s, uuid in export.items()
                        if s in pulled and uuid and pulled[s] and uuid != pulled[s])

    print(f"export {Path(export_path).name}: {len(export)} SKUs")
    print(f"pull:   {len(pulled)} SKUs")
    print(f"  matched with identical UUID : {len(export) - len(missing) - len(mismatched)}")
    print(f"  in export, absent from pull : {len(missing)}")
    print(f"  UUID disagreement           : {len(mismatched)}")
    for s in missing[:20]:
        print(f"    MISSING    {s}")
    for s in mismatched[:20]:
        print(f"    MISMATCH   {s}: export={export[s]} pull={pulled[s]}")
    if missing or mismatched:
        print("\nMissing SKUs may be genuine drift (products deleted or renamed since "
              "the export). A UUID disagreement is not drift — it means the pull is "
              "reading the wrong field. Investigate those first.")
    return 1 if mismatched else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--supplier", action="append", default=[],
                    help="Filter to this LS supplier_name. Repeatable. Matched "
                         "case-insensitively; the catalogue is still walked in full.")
    ap.add_argument("--out", type=Path,
                    help="Output path. Default ingest/<today>/lightspeed-products.json")
    ap.add_argument("--refresh", action="store_true",
                    help="Re-walk the catalogue even if today's cache exists.")
    ap.add_argument("--probe", action="store_true",
                    help="Fetch one page, describe the envelope and a product, exit. "
                         "Writes and caches nothing. Run this first.")
    ap.add_argument("--compare-export", type=Path,
                    help="Reconcile the pull against a hand-exported LS .xlsx.")
    ap.add_argument("--max-pages", type=int, help="Stop after N pages (testing).")
    ap.add_argument("--page-size", type=int, help="Override api.pagination.page_size.")
    ap.add_argument("--full", action="store_true",
                    help="Write every API field instead of the slim projection. "
                         "~41 MB for the whole catalogue against ~9 MB slim.")
    ap.add_argument("--verbose", action="store_true", help="Log each page to stderr.")
    args = ap.parse_args()

    cfg = load_config()
    try:
        client = LightspeedClient(config=cfg, verbose=args.verbose)
    except LightspeedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    page_size = args.page_size or cfg["api"]["pagination"]["page_size"]

    try:
        if args.probe:
            return probe(client, page_size)

        date = today()
        products, from_cache = load_or_walk(client, date, args.refresh, args.max_pages)
    except LightspeedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.compare_export:
        return compare_export(products, args.compare_export)

    wanted = {s.strip().lower() for s in args.supplier}
    if wanted:
        selected = [p for p in products
                    if (supplier_of(p) or "").lower() in wanted]
    else:
        selected = products

    suppliers = {}
    no_supplier = 0
    for p in selected:
        name = supplier_of(p)
        if name is None:
            no_supplier += 1
        else:
            suppliers[name] = suppliers.get(name, 0) + 1

    envelope = {
        "source": "lightspeed",
        "pulled_at": datetime.now(TZ).isoformat(),
        "api_version": client.api_version,
        "from_cache": from_cache,
        "full_records": args.full,
        "supplier_filter": sorted(wanted) or None,
        "counts": {
            "catalogue_total": len(products),
            "selected": len(selected),
            "without_supplier": no_supplier,
            "by_supplier": dict(sorted(suppliers.items())),
        },
        "stats": client.stats(),
    }

    out = args.out or (REPO_ROOT / "ingest" / today() / "lightspeed-products.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {**envelope, "products": selected if args.full else [slim(p) for p in selected]},
        indent=1) + "\n")

    # The product bodies are gitignored: ~9 MB slim, ~41 MB full, regenerable from
    # the API, and an input to the sync rather than a record of a decision. The
    # summary beside them is the committed audit trail — counts, stats and any
    # throttling, a couple of KB.
    summary = out.with_name(out.stem.replace("-products", "") + "-summary.json")
    summary.write_text(json.dumps(envelope, indent=1) + "\n")

    print(f"{out.relative_to(REPO_ROOT)} — {len(selected)} of {len(products)} products"
          + (" (full records)" if args.full else " (slim)")
          + (f", filtered to {sorted(wanted)}" if wanted else "")
          + (f", {no_supplier} carry no supplier" if no_supplier else ""))
    print(f"{summary.relative_to(REPO_ROOT)} — counts and stats (committed)")
    if wanted and not selected:
        print(f"  no products matched. Suppliers present in the catalogue: "
              f"{sorted({supplier_of(p) for p in products if supplier_of(p)})}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
