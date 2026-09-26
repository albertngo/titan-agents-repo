#!/usr/bin/env python3
"""Promo lane of /price-list-sweep: make Lightspeed show what Airtable says. READ ONLY.

    python3 scripts/promo_sweep.py \\
        --airtable ingest/<date>/airtable-promo-snapshot.json \\
        --lightspeed ingest/<date>/lightspeed-products.json \\
        --out plans/<date>/catalog-plan-promo-sweep.json

Albert, 2026-09-26: "I'd want the (P) renaming to happen when the promo goes in, and
leaves when it goes out. During the sweep." Airtable holds each record's promo
(`Promo cost ($/sf)`, `Promo end date`) and never clears it (2026-09-23 ruling), so
Lightspeed is DERIVED from it every morning:

    active  = Promo cost is set AND Promo end date is on/after today
              (a blank end date is NOT active — every promo is dated, 2026-09-26)

    supply_price   active -> Promo cost          over -> Cost/unit, only while
                                                         Lightspeed still holds the
                                                         promo cost (never a general
                                                         cost sync)
    name prefix    active -> "(P YYYY-MM-DD) "
                   else   -> no prefix

A promo that ends therefore comes off by itself the next morning, and a verbal
extension is one Airtable edit (move `Promo end date` forward) — the next sweep puts
the marker and the promo cost back. Nothing here writes Airtable, ever.

This script writes a plan (contracts/catalog-plan-schema.md) and nothing else.
scripts/lightspeed_push.py executes it, through the same approval file and
actions-log as every other catalogue write; lightspeed_write.set_promo_marker() is
the only code that sends the name.

## Deliberate limits

- **Standalone products only get the marker.** A variant family shares one name, so
  a marker on it would mark every member; the per-member place for it (the variant
  value) is a 2.1 attribute write that has bitten once already. A family member gets
  its price and a `marker_on_variant` warning.
- **Retail is never touched.** It stays Cost/unit + markup off the REGULAR cost.
- **No `PROMO` tag.** The live account has no such tag (checked 2026-09-26), and a
  pipeline never creates a Lightspeed entity. Once a person creates it, adding it
  here is a small change — made only after one verified live write.
- **Only the marker may change in a name.** The base name is kept byte for byte; a
  product whose live name has moved since the pull is refused at write time.
- **A marker is removed only where Airtable has an opinion.** A Lightspeed product
  carrying `(P)` whose SKU/UUID matches no Airtable record is left alone and reported.
- **Inactive products are skipped** — nobody sells from them.
- **A large morning is a person's call.** More than --max-changes actions writes the
  plan with `status: "needs_person"`; the sweep does not auto-approve it.
"""

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/Toronto")

SKU = "SKU"
LS_ID = "Lightspeed ID"
COST = "Cost/unit"
PROMO_COST = "Promo cost ($/sf)"
PROMO_END = "Promo end date"
PROMO_URL = "Promo List URL"
SUPPLIER = "Supplier"

# The same pattern lives in lightspeed_write.py (a read-only script must not import
# the write transport); tests hold the two to each other.
MARKER = re.compile(r"^\(P(?: \d{4}-\d{2}-\d{2})?\)\s*")
RECENT_DAYS = 14
MAX_CHANGES = 50
PRICE_TOLERANCE = 0.005


def today():
    return datetime.now(TZ).date().isoformat()


def strip_marker(name):
    return MARKER.sub("", name or "", count=1)


def marker_for(end):
    return f"(P {end}) "


def number(value):
    if value in (None, ""):
        return None
    try:
        return round(float(str(value).replace("$", "").replace(",", "").strip()), 2)
    except ValueError:
        return None


def is_active(record, as_of):
    """Strict (Albert, 2026-09-26): a promo with no end date is NOT running. Every
    promo is dated at extraction; an undated one is a gap for a person to fill."""
    if number(record.get(PROMO_COST)) is None:
        return False
    end = (record.get(PROMO_END) or "")[:10]
    return bool(end) and end >= as_of


def action_id(as_of, sku, op, value):
    """Daily and value-bound: a re-run the same morning resumes, a changed target
    (someone edited Airtable and re-ran) is a new action, and nothing collides with
    /catalog-sync's supplier|sku|system|op ids on the same day."""
    raw = f"promo-sweep|{as_of}|{sku}|{op}|{value}".encode()
    return "promo-" + hashlib.sha1(raw).hexdigest()[:12]


def load_airtable(path):
    """A full-catalogue read. Refuses a partial one: a record missing from the read
    would look like "no promo" and have its marker stripped."""
    data = json.loads(Path(path).read_text())
    records = data["records"] if isinstance(data, dict) else data
    if isinstance(data, dict):
        total = data.get("total_record_count")
        if total is not None and total != len(records):
            raise SystemExit(f"airtable read is partial: {len(records)} of {total} records")
    flat = []
    for r in records:
        if "cellValuesByFieldId" in r:
            raise SystemExit("pass a flattened snapshot (field names), not raw MCP output")
        flat.append(r)
    return flat


def load_airtable_raw(paths):
    """The Airtable MCP's own output pages (cellValuesByFieldId), merged and mapped
    to field names via platform-settings/airtable-master-catalogue-fields.json.
    Refuses a partial read, same as load_airtable()."""
    registry = json.loads((REPO_ROOT / "platform-settings" /
                           "airtable-master-catalogue-fields.json").read_text())
    names = {fid: f["name"] for fid, f in registry.get("fields", registry).items()
             if isinstance(f, dict) and "name" in f}
    records, totals = [], set()
    for path in paths:
        page = json.loads(Path(path).read_text())
        totals.add((page.get("metadata") or {}).get("totalRecordCount"))
        for r in page["records"]:
            row = {"id": r["id"]}
            for fid, value in (r.get("cellValuesByFieldId") or {}).items():
                if isinstance(value, dict):
                    value = value.get("name")
                row[names.get(fid, fid)] = value
            records.append(row)
    ids = {r["id"] for r in records}
    total = max((t for t in totals if t is not None), default=None)
    if len(ids) != len(records):
        raise SystemExit("airtable pages overlap: the same record appears twice")
    if total is None or total != len(records):
        raise SystemExit(f"airtable read is partial: {len(records)} of {total} records")
    return records


def load_lightspeed(path):
    payload = json.loads(Path(path).read_text())
    return payload.get("products", payload)


def plan(airtable, products, as_of=None, max_changes=MAX_CHANGES):
    as_of = as_of or today()
    by_id = {p["id"]: p for p in products if p.get("id")}
    by_sku = {str(p["sku"]).strip(): p for p in products if p.get("sku")}
    name_owner = {}
    for p in products:
        name_owner.setdefault(p.get("name"), set()).add(p.get("id"))

    actions, blocked, warnings, recently_ended = [], [], [], []
    counts = {"airtable_records": len(airtable), "with_promo": 0, "active": 0,
              "not_in_lightspeed": 0, "inactive_skipped": 0}
    seen_ls = set()

    def add(op, sku, product, fields, before, reason):
        value = json.dumps(fields, sort_keys=True)
        actions.append({"id": action_id(as_of, sku, op, value),
                        "target_system": "lightspeed", "op": op, "sku": sku,
                        "ls_id": product["id"], "airtable_rec_id": None,
                        "fields": fields, "before": before, "reason": reason})

    for rec in airtable:
        sku = (rec.get(SKU) or "").strip()
        if not sku:
            continue
        has_promo = number(rec.get(PROMO_COST)) is not None
        product = by_id.get((rec.get(LS_ID) or "").strip()) or by_sku.get(sku)
        if product is not None:
            seen_ls.add(product["id"])
        if not has_promo and not (product and MARKER.match(product.get("name") or "")):
            continue  # no promo, no marker: nothing to reconcile
        active = is_active(rec, as_of)
        end = (rec.get(PROMO_END) or "")[:10] or None
        if has_promo and not end:
            warnings.append({"sku": sku, "reason": "promo_end_missing",
                             "detail": "promo cost with no end date is treated as over; "
                                       "give it an end date in Airtable to turn it on"})
        if has_promo:
            counts["with_promo"] += 1
            counts["active"] += active
            if end and not active and (date.fromisoformat(as_of)
                                       - date.fromisoformat(end)).days <= RECENT_DAYS:
                recently_ended.append({"sku": sku, "supplier": rec.get(SUPPLIER),
                                       "promo_cost": number(rec.get(PROMO_COST)),
                                       "regular_cost": number(rec.get(COST)),
                                       "promo_end_date": end,
                                       "promo_list_url": rec.get(PROMO_URL)})
        if product is None:
            if active:
                counts["not_in_lightspeed"] += 1
                warnings.append({"sku": sku, "reason": "not_in_lightspeed",
                                 "detail": "active promo in Airtable, no Lightspeed "
                                           "product by UUID or SKU"})
            continue
        if product.get("active") is False:
            counts["inactive_skipped"] += 1
            continue

        # -- price -----------------------------------------------------------
        # Only moves a price INTO or OUT OF the promo — never a general cost sync.
        # Off means "Lightspeed still holds the promo cost": any other mismatch with
        # Cost/unit is /catalog-sync's business, not this lane's.
        promo, cost = number(rec.get(PROMO_COST)), number(rec.get(COST))
        live = number(product.get("supply_price"))
        differs = lambda a, b: a is None or b is None or abs(a - b) > PRICE_TOLERANCE  # noqa: E731
        if active and differs(live, promo):
            add("update", sku, product, {"supply_price": promo}, {"supply_price": live},
                "promo_price_on")
        elif has_promo and not active and not differs(live, promo) and differs(promo, cost):
            if cost is None:
                blocked.append({"sku": sku, "reason": "no_regular_cost",
                                "detail": "promo is over and Cost/unit is blank, so there "
                                          "is no cost to return Lightspeed to"})
            else:
                add("update", sku, product, {"supply_price": cost}, {"supply_price": live},
                    "promo_price_off")

        # -- marker ----------------------------------------------------------
        name = product.get("name") or ""
        base = strip_marker(name)
        target = (marker_for(end) + base) if active else base
        if target == name:
            continue
        if product.get("has_variants") or product.get("variant_parent_id"):
            warnings.append({"sku": sku, "reason": "marker_on_variant",
                             "detail": "variant family member: price handled, marker "
                                       f"left as {name[:40]!r} (family-wide name)"})
            continue
        if not base.strip():
            blocked.append({"sku": sku, "reason": "empty_base_name", "detail": name})
            continue
        if name_owner.get(target, set()) - {product["id"]}:
            blocked.append({"sku": sku, "reason": "name_collision",
                            "detail": f"another live product is already named {target!r}; "
                                      "Lightspeed would group them into one family"})
            continue
        add("promo_marker", sku, product,
            {"name": target, "expect_name": name, "expect_sku": str(product.get("sku"))},
            {"name": name}, "promo_marker_on" if active else "promo_marker_off")

    for p in products:
        if p["id"] not in seen_ls and MARKER.match(p.get("name") or "") \
                and p.get("active") is not False:
            warnings.append({"sku": p.get("sku"), "reason": "marker_without_airtable_record",
                             "detail": "carries (P) but matches no Airtable record; left alone"})

    for i, a in enumerate(sorted(actions, key=lambda a: (a["op"] != "update", a["sku"])), 1):
        a["seq"] = i
    status = "ready" if len(actions) <= max_changes else "needs_person"
    recently_ended.sort(key=lambda r: (r["promo_end_date"], r["supplier"] or "", r["sku"]))
    return {
        "contract_version": "catalog-plan-1",
        "supplier": f"PROMO SWEEP {as_of}",
        "run_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "as_of": as_of,
        "status": status,
        "cost_basis": "airtable (the promo lane mirrors Airtable's own Cost/unit and Promo cost)",
        "summary": {**counts,
                    "actions": len(actions),
                    "price_on": sum(a["reason"] == "promo_price_on" for a in actions),
                    "price_off": sum(a["reason"] == "promo_price_off" for a in actions),
                    "marker_on": sum(a["reason"] == "promo_marker_on" for a in actions),
                    "marker_off": sum(a["reason"] == "promo_marker_off" for a in actions),
                    "blocked": len(blocked), "warnings": len(warnings),
                    "recently_ended": len(recently_ended),
                    "max_changes": max_changes},
        "actions": sorted(actions, key=lambda a: a["seq"]),
        "blocked": blocked,
        "warnings": warnings,
        "recently_ended": recently_ended,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--airtable", type=Path, help="flattened snapshot (field names)")
    src.add_argument("--airtable-raw", type=Path, nargs="+",
                     help="the Airtable MCP's saved list_records pages, all of them")
    ap.add_argument("--lightspeed", type=Path)
    ap.add_argument("--as-of")
    ap.add_argument("--max-changes", type=int, default=MAX_CHANGES)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    as_of = args.as_of or today()
    ls_path = args.lightspeed or REPO_ROOT / "ingest" / as_of / "lightspeed-products.json"
    out = args.out or REPO_ROOT / "plans" / as_of / "catalog-plan-promo-sweep.json"
    airtable = (load_airtable_raw(args.airtable_raw) if args.airtable_raw
                else load_airtable(args.airtable))
    result = plan(airtable, load_lightspeed(ls_path), as_of,
                  args.max_changes)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(out)
    for k, v in result["summary"].items():
        print(f"  {k:20} {v}")
    print(f"  status               {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
