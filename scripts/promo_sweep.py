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
actions-log as every other catalogue write; lightspeed_write.set_promo_marker() and
set_variant_marker() are the only code that sends a marker.

## Deliberate limits

- **A family member's marker goes on its own variant value**, never the shared family
  name (Albert, 2026-09-26; verified live on ENG-VIDR-0046). A value a sibling already
  holds is blocked, never sent.
- **Rep rates** (`Rep cost ($/sf)`, 2026-09-26) compete with promos: the lower active
  one wins and only its marker shows — `(R YYYY-MM-DD) `, or `(R) ` when undated
  (a rep rate may be open-ended; a promo may not). Neither applies unless it is below
  `Cost/unit`.
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
REP_COST = "Rep cost ($/sf)"
REP_END = "Rep cost end date"
REP_NOTE = "Rep cost note"
SUPPLIER = "Supplier"

# The same pattern lives in lightspeed_write.py (a read-only script must not import
# the write transport); tests hold the two to each other.
MARKER = re.compile(r"^\([PR](?: \d{4}-\d{2}-\d{2})?\)\s*")
RECENT_DAYS = 14
MAX_CHANGES = 50
PRICE_TOLERANCE = 0.005


def today():
    return datetime.now(TZ).date().isoformat()


def strip_marker(name):
    return MARKER.sub("", name or "", count=1)


def marker_for(kind, end):
    """`(P 2026-09-30) ` / `(R 2026-10-31) `; a rep rate may have no end: `(R) `."""
    return f"({kind} {end}) " if end else f"({kind}) "


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


def rep_active(record, as_of):
    """A rep rate MAY have no end date (Albert, 2026-09-26): blank = ongoing until a
    person clears `Rep cost`. Unlike a promo, which is always dated."""
    if number(record.get(REP_COST)) is None:
        return False
    end = (record.get(REP_END) or "")[:10]
    return not end or end >= as_of


def winner(record, as_of):
    """(kind, cost, end) of the discount in force, or None.

    Lower one wins (Albert, 2026-09-26): an active promo and an active rep rate
    compete, and neither applies unless it is below the regular Cost/unit. A tie
    between the two goes to the promo — it is printed and dated.
    """
    cost = number(record.get(COST))
    options = []
    if is_active(record, as_of):
        options.append((number(record.get(PROMO_COST)), 0, "P",
                        (record.get(PROMO_END) or "")[:10]))
    if rep_active(record, as_of):
        options.append((number(record.get(REP_COST)), 1, "R",
                        (record.get(REP_END) or "")[:10] or None))
    options = [o for o in options if cost is None or o[0] < cost - PRICE_TOLERANCE]
    if not options:
        return None
    price, _, kind, end = min(options)
    return kind, price, end


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
    name_owner, families = {}, {}
    for p in products:
        name_owner.setdefault(p.get("name"), set()).add(p.get("id"))
        if is_variant(p):
            families.setdefault(p.get("name"), []).append(p)

    actions, blocked, warnings, recently_ended = [], [], [], []
    counts = {"airtable_records": len(airtable), "with_promo": 0, "active": 0,
              "with_rep_rate": 0, "rep_active": 0,
              "not_in_lightspeed": 0, "inactive_skipped": 0}
    seen_ls = set()
    differs = lambda a, b: a is None or b is None or abs(a - b) > PRICE_TOLERANCE  # noqa: E731

    def add(op, sku, product, fields, before, reason):
        value = json.dumps(fields, sort_keys=True)
        actions.append({"id": action_id(as_of, sku, op, value),
                        "target_system": "lightspeed", "op": op, "sku": sku,
                        "ls_id": product["id"], "airtable_rec_id": None,
                        "fields": fields, "before": before, "reason": reason})

    def ended_recently(end):
        return end and (date.fromisoformat(as_of) - date.fromisoformat(end)).days \
            in range(1, RECENT_DAYS + 1)

    for rec in airtable:
        sku = (rec.get(SKU) or "").strip()
        if not sku:
            continue
        promo, rep, cost = (number(rec.get(PROMO_COST)), number(rec.get(REP_COST)),
                            number(rec.get(COST)))
        product = by_id.get((rec.get(LS_ID) or "").strip()) or by_sku.get(sku)
        if product is not None:
            seen_ls.add(product["id"])
        if promo is None and rep is None and not (product and has_marker(product)):
            continue  # no discount, no marker: nothing to reconcile
        promo_end = (rec.get(PROMO_END) or "")[:10] or None
        rep_end = (rec.get(REP_END) or "")[:10] or None
        if promo is not None:
            counts["with_promo"] += 1
            counts["active"] += is_active(rec, as_of)
            if not promo_end:
                warnings.append({"sku": sku, "reason": "promo_end_missing",
                                 "detail": "promo cost with no end date is treated as over; "
                                           "give it an end date in Airtable to turn it on"})
            if ended_recently(promo_end):
                recently_ended.append({"kind": "promo", "sku": sku,
                                       "supplier": rec.get(SUPPLIER), "cost": promo,
                                       "regular_cost": cost, "end_date": promo_end,
                                       "link": rec.get(PROMO_URL)})
        if rep is not None:
            counts["with_rep_rate"] += 1
            counts["rep_active"] += rep_active(rec, as_of)
            if ended_recently(rep_end):
                recently_ended.append({"kind": "rep rate", "sku": sku,
                                       "supplier": rec.get(SUPPLIER), "cost": rep,
                                       "regular_cost": cost, "end_date": rep_end,
                                       "link": rec.get(REP_NOTE)})
            if rep_active(rec, as_of) and cost is not None and rep >= cost - PRICE_TOLERANCE:
                warnings.append({"sku": sku, "reason": "rep_rate_not_better",
                                 "detail": f"rep rate {rep} is not below the list cost "
                                           f"{cost}; the list cost applies — clear or "
                                           "renegotiate the rep rate"})
        win = winner(rec, as_of)
        if product is None:
            if win:
                counts["not_in_lightspeed"] += 1
                warnings.append({"sku": sku, "reason": "not_in_lightspeed",
                                 "detail": "active discount in Airtable, no Lightspeed "
                                           "product by UUID or SKU"})
            continue
        if product.get("active") is False:
            counts["inactive_skipped"] += 1
            continue

        # -- price -----------------------------------------------------------
        # Moves a price INTO a discount, between discounts, or back OUT of one —
        # never a general cost sync. Off means "Lightspeed still holds a promo or rep
        # cost": any other mismatch with Cost/unit is /catalog-sync's business.
        live = number(product.get("supply_price"))
        if win and differs(live, win[1]):
            add("update", sku, product, {"supply_price": win[1]}, {"supply_price": live},
                "promo_price_on" if win[0] == "P" else "rep_price_on")
        elif not win and cost is not None and differs(live, cost) and any(
                d is not None and not differs(live, d) for d in (promo, rep)):
            add("update", sku, product, {"supply_price": cost}, {"supply_price": live},
                "price_off")
        elif not win and cost is None and any(
                d is not None and not differs(live, d) for d in (promo, rep)):
            blocked.append({"sku": sku, "reason": "no_regular_cost",
                            "detail": "the discount is over and Cost/unit is blank, so "
                                      "there is no cost to return Lightspeed to"})

        # -- marker ----------------------------------------------------------
        on = f"{'promo' if win and win[0] == 'P' else 'rep'}_marker_on"
        if is_variant(product):
            plan_variant_marker(product, sku, win, families, add, blocked, warnings, on)
            continue
        name = product.get("name") or ""
        base = strip_marker(name)
        target = (marker_for(win[0], win[2]) + base) if win else base
        if target == name:
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
            {"name": name}, on if win else "marker_off")

    for p in products:
        if p["id"] not in seen_ls and has_marker(p) and p.get("active") is not False:
            warnings.append({"sku": p.get("sku"), "reason": "marker_without_airtable_record",
                             "detail": "carries a marker but matches no Airtable record; "
                                       "left alone"})

    for i, a in enumerate(sorted(actions, key=lambda a: (a["op"] != "update", a["sku"])), 1):
        a["seq"] = i
    status = "ready" if len(actions) <= max_changes else "needs_person"
    recently_ended.sort(key=lambda r: (r["end_date"], r["supplier"] or "", r["sku"]))
    reasons = [a["reason"] for a in actions]
    return {
        "contract_version": "catalog-plan-1",
        "supplier": f"PROMO SWEEP {as_of}",
        "run_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "as_of": as_of,
        "status": status,
        "cost_basis": "airtable (the promo lane mirrors Airtable's Cost/unit, Promo cost "
                      "and Rep cost)",
        "summary": {**counts,
                    "actions": len(actions),
                    **{r: reasons.count(r) for r in (
                        "promo_price_on", "rep_price_on", "price_off",
                        "promo_marker_on", "rep_marker_on", "marker_off")},
                    "variant_markers": sum(a["op"] == "variant_marker" for a in actions),
                    "blocked": len(blocked), "warnings": len(warnings),
                    "recently_ended": len(recently_ended),
                    "max_changes": max_changes},
        "actions": sorted(actions, key=lambda a: a["seq"]),
        "blocked": blocked,
        "warnings": warnings,
        "recently_ended": recently_ended,
    }


def is_variant(product):
    return bool(product.get("has_variants") or product.get("variant_parent_id"))


def has_marker(product):
    if MARKER.match(product.get("name") or ""):
        return True
    return any(MARKER.match(o.get("value") or "") for o in product.get("variant_options") or [])


def plan_variant_marker(product, sku, win, families, add, blocked, warnings, on):
    """A family member's marker lives in its own variant value, never the family
    name (Albert, 2026-09-26; verified live on ENG-VIDR-0046). The first option is
    the one the CSV's column 11 carries."""
    options = product.get("variant_options") or []
    if not options:
        warnings.append({"sku": sku, "reason": "variant_without_options",
                         "detail": "family member with no variant value to mark"})
        return
    option = options[0]
    value = option.get("value") or ""
    base = strip_marker(value)
    target = (marker_for(win[0], win[2]) + base) if win else base
    if target == value:
        return
    if not base.strip():
        blocked.append({"sku": sku, "reason": "empty_base_value", "detail": value})
        return
    siblings = [p for p in families.get(product.get("name"), []) if p["id"] != product["id"]]
    if any((o.get("id"), o.get("value")) == (option.get("id"), target)
           for p in siblings for o in p.get("variant_options") or []):
        blocked.append({"sku": sku, "reason": "variant_value_collision",
                        "detail": f"a sibling already holds {target!r}; Lightspeed would "
                                  "reject a Duplicate Variant"})
        return
    add("variant_marker", sku, product,
        {"attribute_id": option.get("id"), "expect_value": value, "value": target,
         "expect_sku": str(product.get("sku"))},
        {"variant_value": value}, on if win else "marker_off")


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
