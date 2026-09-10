#!/usr/bin/env python3
"""Reconcile a processed price list against Airtable and Lightspeed. READ ONLY.

Produces the single reviewable diff the pipeline's approval gate acts on, per
contracts/catalog-plan-schema.md:

    plans/YYYY-MM-DD/catalog-plan-<supplier-slug>.json

This writes no platform and holds no credentials. It reads three files and emits
one. Executing the plan is a separate, approved step.

## What it does and does not do

It does NOT re-implement extraction or the Airtable fuzzy match — /process-price-list
already does that, over 8+ suppliers, and its `MatchStatus` column is taken as
given. What it adds is the check that column cannot make: verifying every identity
claim in the upload against the LIVE Lightspeed catalogue, and turning the result
into an executable plan.

That check is the point. On 2026-09-03 a Grandeur backfill matched on colour alone
and Lightspeed rejected 9 products with "handle already exists for your retailer,
sku already exists for your retailer". Every one of those rows carried a UUID
belonging to a different SKU, and four also shared a UUID with a second row in the
same file. Neither is visible from the upload file alone; both are obvious once the
live catalogue is joined on `sku`.

A blank `Lightspeed ID` on a row whose SKU already exists in Lightspeed is the same
bug facing the other way — it makes Lightspeed create a duplicate instead of
updating. That one is repairable rather than fatal: the SKU join recovers the real
UUID, and the plan records it as `uuid_recovered`.

Usage:
    python3 scripts/catalog_reconcile.py \
        --upload ingest/2026-09-09/lee_airtable_upload_2026-09-09.csv

    # explicit inputs, and a live-Airtable snapshot for before/after
    python3 scripts/catalog_reconcile.py \
        --upload ingest/2026-09-03/grandeur_airtable_upload_2026-09-03.csv \
        --lightspeed ingest/2026-09-10/lightspeed-products.json \
        --airtable-existing ingest/2026-09-03/grandeur_airtable_existing.json

Config: platform-settings/lightspeed.json, platform-settings/airtable-destinations.json.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/Toronto")
CONTRACT_VERSION = "catalog-plan-1"

SKU = "SKU"
LS_ID = "Lightspeed ID"
HANDLE = "LS Handle / Parent ID"
MATCH_STATUS = "MatchStatus"
LS_MATCH_STATUS = "LS Match status"
MATCHED_REC = "MatchedRecId"
SUPPLIER = "Supplier"

# Fields worth diffing against the live Airtable record. Keys are upload-CSV
# column names; values are the aliases a live-record snapshot may use instead.
DIFF_FIELDS = {
    "Product name": ("ProductName", "Product name"),
    "Supplier SKU": ("SupplierSKU", "Supplier SKU"),
    "Category": ("Category",),
    "Cost/unit": ("Cost", "Cost/unit"),
    "Retail price/unit": ("Retail", "Retail price/unit"),
    LS_ID: ("LightspeedID", "Lightspeed ID"),
}
PRICE_FIELDS = ("Cost/unit", "Retail price/unit")

# MatchStatus / LS Match status values that must never reach a write.
AMBIGUOUS = {"ambiguous", "AMBIGUOUS", "DUPLICATE"}


def today():
    return datetime.now(TZ).date().isoformat()


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", (name or "unknown").lower()).strip("_")


def clean(value):
    """Upload-CSV cell -> a value, or None.

    Blank means genuinely empty. Never 0, never "", never a sentinel — the
    ls-id-backfill skill is explicit about this and the writers depend on it.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_number(value):
    try:
        return round(float(str(value).strip()), 4)
    except (TypeError, ValueError):
        return None


def comparable(field, value):
    """Normalise for change detection: prices numerically, everything else as text."""
    if value is None:
        return None
    if field in PRICE_FIELDS or field.endswith(("($/sf)", "(in)", "(mm)")):
        num = as_number(value)
        if num is not None:
            return num
    return str(value).strip()


def action_id(supplier, sku, target_system, op):
    """Stable across re-runs — that is what makes actions-log idempotency work."""
    raw = f"{supplier}|{sku}|{target_system}|{op}".encode()
    return "cat-" + hashlib.sha1(raw).hexdigest()[:12]


def load_lightspeed(path):
    """Index the LS pull by sku and by id.

    Both are unique across the live catalogue (verified 2026-09-10: 14,525
    products, 0 blank skus, 0 duplicates), which is what makes sku a safe join
    key. If that ever stops being true, say so loudly rather than silently
    picking a winner.
    """
    payload = json.loads(Path(path).read_text())
    products = payload.get("products", payload)
    by_sku, by_id, by_handle = {}, {}, defaultdict(list)
    collisions = []
    for product in products:
        sku, pid = clean(product.get("sku")), clean(product.get("id"))
        if sku:
            if sku in by_sku:
                collisions.append(sku)
            by_sku[sku] = product
        if pid:
            by_id[pid] = product
        handle = clean(product.get("handle"))
        if handle:
            by_handle[handle].append(product)
    return {"by_sku": by_sku, "by_id": by_id, "by_handle": by_handle,
            "sku_collisions": collisions, "count": len(products),
            "pulled_at": payload.get("pulled_at")}


def load_airtable_existing(path):
    if not path:
        return {}
    records = json.loads(Path(path).read_text())
    if isinstance(records, dict):
        records = list(records.values())
    return {clean(r.get(SKU)): r for r in records if clean(r.get(SKU))}


def live_value(record, field):
    """(value, readable). `readable` False means the snapshot carries no such key.

    The distinction matters: a reviewer approving a diff must be able to tell
    "this field was empty" from "we could not read this field", and null renders
    both the same.
    """
    for alias in DIFF_FIELDS.get(field, (field,)):
        if alias in record:
            return record[alias], True
    return None, False


def reconcile(upload_rows, ls, existing, supplier, categories):
    """Every row -> an action or a block. Never both, never neither.

    Warnings are separate: things worth a reader's attention that are not a
    reason to withhold a write.
    """
    actions, blocked, warnings = [], [], []

    def block(sku, reason, detail, rows=None):
        blocked.append({"sku": sku, "reason": reason, "detail": detail,
                        **({"rows": rows} if rows else {})})

    def warn(sku, reason, detail):
        warnings.append({"sku": sku, "reason": reason, "detail": detail})

    # Pass 1 — UUIDs reused within this one file. Four of the nine Grandeur
    # rejections were this, and it is detectable without touching Lightspeed.
    uuid_rows = defaultdict(list)
    for row in upload_rows:
        uuid = clean(row.get(LS_ID))
        if uuid:
            uuid_rows[uuid].append(clean(row.get(SKU)))
    collided = {u: skus for u, skus in uuid_rows.items() if len(skus) > 1}

    # Pass 2 — per row.
    for row in upload_rows:
        sku = clean(row.get(SKU))
        if not sku:
            block(None, "sku_missing",
                  f"row for {clean(row.get('Product name')) or '<unnamed>'} carries no SKU")
            continue

        uuid = clean(row.get(LS_ID))
        handle = clean(row.get(HANDLE))
        match_status = clean(row.get(MATCH_STATUS))
        ls_match_status = clean(row.get(LS_MATCH_STATUS))
        rec_id = clean(row.get(MATCHED_REC))

        if match_status in AMBIGUOUS or ls_match_status in AMBIGUOUS:
            block(sku, "ambiguous_match",
                  f"MatchStatus={match_status!r} LS Match status={ls_match_status!r}; "
                  "resolve by hand, never guess")
            continue

        if uuid and uuid in collided:
            owner = ls["by_id"].get(uuid)
            owner_sku = clean(owner.get("sku")) if owner else None
            detail = (f"Lightspeed ID {uuid} is claimed by {len(collided[uuid])} rows in this "
                      f"file: {', '.join(sorted(s or '?' for s in collided[uuid]))}")
            if owner_sku:
                detail += (f". Lightspeed holds it against {owner_sku}"
                           + (" — this row" if owner_sku == sku
                              else f", so {sku} is not its owner"))
            block(sku, "uuid_collision", detail, rows=collided[uuid])
            continue

        ls_by_id = ls["by_id"].get(uuid) if uuid else None
        ls_by_sku = ls["by_sku"].get(sku)

        if uuid and ls_by_id is None:
            block(sku, "uuid_not_in_lightspeed",
                  f"row carries {uuid}, which Lightspeed does not hold")
            continue

        if uuid and clean(ls_by_id.get("sku")) != sku:
            block(sku, "uuid_belongs_to_other_sku",
                  f"{uuid} belongs to {clean(ls_by_id.get('sku'))} "
                  f"({clean(ls_by_id.get('name')) or ''}) — writing it would overwrite that product")
            continue

        # A blank UUID whose SKU already lives in Lightspeed: repairable, and the
        # bug that otherwise makes Lightspeed create a duplicate.
        recovered = None
        if not uuid and ls_by_sku:
            recovered = clean(ls_by_sku.get("id"))
            uuid = recovered

        if not uuid and handle:
            clash = [p for p in ls["by_handle"].get(handle, [])
                     if clean(p.get("sku")) != sku]
            if clash:
                block(sku, "handle_collision_on_create",
                      f"handle {handle} is already held by "
                      f"{', '.join(sorted(clean(p.get('sku')) or '?' for p in clash)[:4])}")
                continue

        category = clean(row.get("Category"))
        if category and not category_resolves(category, categories):
            warn(sku, "category_unresolved",
                 f"Airtable category {category!r} does not map to a Lightspeed leaf on its "
                 "own — LVP/LVT are formats, and Lightspeed classifies vinyl by core and "
                 "install (SPC / WPC / GLUE DOWN / LOOSE LAY). Needs Material type and "
                 "Install method. Not blocking: no write path sets a category yet.")

        # ---- Airtable side ----
        live = existing.get(sku)
        is_new_in_airtable = (match_status == "new") or (live is None and match_status != "matched")
        fields, before, unreadable = {}, {}, []
        for field in DIFF_FIELDS:
            new = clean(row.get(field))
            if new is None:
                continue
            if live is None:
                old, readable = None, False
            else:
                raw, readable = live_value(live, field)
                old = clean(raw)
            if not readable:
                # No prior value to compare against, so write it and say so rather
                # than implying it was empty.
                fields[field] = new
                unreadable.append(field)
                continue
            if comparable(field, new) != comparable(field, old):
                fields[field] = new
                before[field] = old

        if recovered:
            fields[LS_ID] = recovered
            before[LS_ID] = None
            if LS_ID in unreadable:
                unreadable.remove(LS_ID)

        uuid_source = ("recovered_by_sku" if recovered
                       else "upload" if uuid else "lightspeed_on_create")

        if fields:
            price_moved = any(f in PRICE_FIELDS for f in fields)
            reason = ("new_product" if is_new_in_airtable
                      else "price_change" if price_moved else "field_update")
            action = {
                "id": action_id(supplier, sku, "airtable", "upsert"),
                "target_system": "airtable",
                "op": "upsert",
                "sku": sku,
                "airtable_rec_id": rec_id,
                "ls_id": uuid,
                "handle": handle,
                "fields": fields,
                "before": None if is_new_in_airtable else before,
                "reason": reason,
                "uuid_source": uuid_source,
            }
            if unreadable and not is_new_in_airtable:
                action["before_unreadable"] = sorted(unreadable)
            actions.append(action)

        # ---- Lightspeed side ----
        if uuid:
            actions.append({
                "id": action_id(supplier, sku, "lightspeed", "update"),
                "target_system": "lightspeed", "op": "update", "sku": sku,
                "airtable_rec_id": rec_id, "ls_id": uuid, "handle": handle,
                "fields": ls_fields(row), "before": ls_before(ls_by_id or ls_by_sku),
                "reason": "price_change", "uuid_source": uuid_source,
            })
        else:
            actions.append({
                "id": action_id(supplier, sku, "lightspeed", "create"),
                "target_system": "lightspeed", "op": "create", "sku": sku,
                "airtable_rec_id": rec_id, "ls_id": None, "handle": handle,
                "fields": ls_fields(row), "before": None, "reason": "new_product",
                "uuid_source": "lightspeed_on_create",
            })
            actions.append({
                "id": action_id(supplier, sku, "airtable", "backfill_ls_id"),
                "target_system": "airtable", "op": "backfill_ls_id", "sku": sku,
                "airtable_rec_id": rec_id, "ls_id": None, "handle": handle,
                "fields": {LS_ID: "<assigned by Lightspeed on create>"},
                "before": {LS_ID: None}, "reason": "uuid_from_create",
                "uuid_source": "lightspeed_on_create",
            })

    return order(actions), blocked, warnings


def category_resolves(category, leaves):
    """Does an Airtable category correspond, unambiguously, to a Lightspeed leaf?

    Compared on the final path segment because the two systems disagree on form:
    the API returns leaf names alone ('SPC', 'ENGINEERED HARDWOOD') while the CSV
    importer takes ' / '-separated paths.

    'Laminate', 'Engineered hardwood' and 'Solid hardwood' resolve. 'LVP' and
    'LVT' do NOT, and that is correct rather than a gap in this function: they name
    a FORMAT, while Lightspeed classifies vinyl by core and install method — the
    live catalogue holds SPC, WPC, GLUE DOWN and LOOSE LAY as separate leaves.
    Deriving the right one needs Material type and Install method, and the live
    catalogue also uses leaves the documented list does not cover. That mapping is
    an open question for the Phase 3 spike, so a miss here is a warning.
    """
    want = category.strip().lower().replace("-", " ")
    return any(want == leaf.split("/")[-1].strip().lower() for leaf in leaves)


def ls_fields(row):
    """The Lightspeed-side payload. Names and prices only — see the note below.

    Deliberately narrow. The API is NOT the CSV importer: it has no retail_price
    field (0 of 14,525 live products carry one — there is price_including_tax and
    price_excluding_tax instead), and product_category is a leaf name rather than
    a path. Choosing between those tax-qualified fields, and the variant-family
    shape, are open questions the Phase 3 spike settles. Until then this records
    intent and the writer refuses anything it cannot map.
    """
    return {k: v for k, v in (
        ("name", clean(row.get("Product name"))),
        ("handle", clean(row.get(HANDLE))),
        ("sku", clean(row.get(SKU))),
        ("supply_price", as_number(row.get("Cost/unit"))),
        ("retail_price_intent", as_number(row.get("Retail price/unit"))),
        ("category_intent", clean(row.get("Category"))),
        ("supplier_name", clean(row.get(SUPPLIER))),
        ("brand_name", clean(row.get("Brand"))),
    ) if v is not None}


def ls_before(product):
    if not product:
        return None
    return {k: product.get(k) for k in
            ("name", "handle", "sku", "supply_price", "price_including_tax",
             "price_excluding_tax", "category", "supplier_name", "active")
            if k in product}


def order(actions):
    """Forced dependency order: Airtable state, then Lightspeed, then backfill."""
    rank = {("airtable", "upsert"): 0, ("lightspeed", "update"): 1,
            ("lightspeed", "create"): 1, ("airtable", "backfill_ls_id"): 2}
    actions.sort(key=lambda a: (rank[(a["target_system"], a["op"])], a["sku"]))
    for seq, action in enumerate(actions, 1):
        action["seq"] = seq
    return actions


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upload", type=Path, required=True,
                    help="Airtable upload CSV from /process-price-list")
    ap.add_argument("--lightspeed", type=Path,
                    help="LS pull JSON. Default ingest/<today>/lightspeed-products.json")
    ap.add_argument("--airtable-existing", type=Path,
                    help="JSON of live Airtable records, for before/after")
    ap.add_argument("--supplier", help="Override the Supplier read from the CSV")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--cost-basis", help="e.g. 'dealer'. Recorded, never inferred.")
    ap.add_argument("--confirmed-by", help="Who confirmed the cost basis, and when")
    args = ap.parse_args()

    ls_path = args.lightspeed or (REPO_ROOT / "ingest" / today() / "lightspeed-products.json")
    if not ls_path.exists():
        print(f"error: no Lightspeed pull at {ls_path}. Run scripts/lightspeed_pull.py first — "
              "the identity checks are not possible without the live catalogue.", file=sys.stderr)
        return 2

    with open(args.upload, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print(f"error: {args.upload} has no rows", file=sys.stderr)
        return 2

    supplier = args.supplier or clean(rows[0].get(SUPPLIER)) or "unknown"
    ls = load_lightspeed(ls_path)
    if ls["sku_collisions"]:
        print(f"error: the Lightspeed pull has duplicate SKUs "
              f"({ls['sku_collisions'][:5]}...). sku is the join key; resolve before "
              "reconciling.", file=sys.stderr)
        return 2

    existing = load_airtable_existing(args.airtable_existing)
    categories = json.loads(
        (REPO_ROOT / "platform-settings" / "lightspeed.json").read_text()
    )["product_categories"]["leaves"]

    actions, blocked, warnings = reconcile(rows, ls, existing, supplier, categories)

    kinds = Counter(f"{a['target_system']}_{a['op']}" for a in actions)
    recovered = len({a["sku"] for a in actions if a.get("uuid_source") == "recovered_by_sku"})
    plan = {
        "contract_version": CONTRACT_VERSION,
        "supplier": supplier,
        "run_at": datetime.now(TZ).isoformat(),
        "status": "partial" if blocked else "ok",
        "inputs": [
            {"file": str(args.upload), "rows": len(rows)},
            {"file": str(ls_path), "products": ls["count"], "run_at": ls["pulled_at"]},
        ] + ([{"file": str(args.airtable_existing), "records": len(existing)}]
             if args.airtable_existing else []),
        "cost_basis": ({"value": args.cost_basis, "confirmed_by": args.confirmed_by}
                       if args.cost_basis else None),
        "summary": {**dict(sorted(kinds.items())),
                    "actions_total": len(actions),
                    "uuid_recovered_by_sku": recovered,
                    "blocked": len(blocked),
                    "warnings": len(warnings),
                    "rows_in": len(rows)},
        "actions": actions,
        "blocked": blocked,
        "warnings": warnings,
    }

    out = args.out or (REPO_ROOT / "plans" / today() /
                       f"catalog-plan-{slugify(supplier)}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=1) + "\n")

    print(f"{out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out}")
    print(f"  supplier   {supplier}")
    print(f"  rows in    {len(rows)}")
    for kind, n in sorted(kinds.items()):
        print(f"  {kind:24} {n}")
    if recovered:
        print(f"  {'uuid recovered by sku':24} {recovered}   "
              f"(blank in the upload, found live — would have duplicated)")
    print(f"  blocked    {len(blocked)}")
    for reason, n in Counter(b["reason"] for b in blocked).most_common():
        print(f"    {reason:28} {n}")
    if warnings:
        print(f"  warnings   {len(warnings)}")
        for reason, n in Counter(w["reason"] for w in warnings).most_common():
            print(f"    {reason:28} {n}")
    if blocked:
        print("\n  Blocked rows are NOT approvable and never reach a write. Fix the data "
              "and re-run.")
    if plan["cost_basis"] is None and any(a["reason"] == "new_product" for a in actions):
        print("\n  This plan creates products and carries no cost basis. Pass --cost-basis "
              "once Albert confirms it; it is never inferred.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
