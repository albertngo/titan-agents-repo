#!/usr/bin/env python3
"""Pull Lightspeed supplier purchase orders and their line costs. READ ONLY.

For the payout flow (methods/payouts.md, amendment §2.4): the stock purchase order
front desk raises is the second view of a flooring line's cost — the rate they keyed
when ordering. On X-Series a purchase order is a *consignment* of type SUPPLIER and
its lines are *consignment products* (verified live 2026-10-06; R-Series
Order/OrderLine/OrderShipment do not exist here).

    python3 scripts/ls_orders_pull.py               # last orders_window_days
    python3 scripts/ls_orders_pull.py --days 60

Output: ingest/YYYY-MM-DD/ls-orders.json per contracts/ls-orders-schema.md, with
  * `projects`        — POs whose `name` carries a project number, by project;
  * `product_po_cost` — the latest PO line cost per product in the window, for a
                        flooring line whose PO carries no project number (a weaker,
                        product-level suggestion; see the contract).

Facts this relies on (platform-settings/lightspeed.json → api.consignments):
  * the documented `type=` filter is ignored, so every consignment is walked and
    filtered on its own `type`; page_size caps at 500; there is no date filter;
  * there is no note field — the PP lives in `name`, which also carries customer
    first names. This script keeps the parsed number only and never writes `name`.

Environment: LIGHTSPEED_DOMAIN_PREFIX, LIGHTSPEED_PERSONAL_TOKEN, read from .env.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lightspeed_client import LightspeedClient, LightspeedError, load_config  # noqa: E402
from ls_sales_pull import (REPO_ROOT, TZ, load_dotenv, load_policy, num,  # noqa: E402
                           parse_pp, pp_candidates, pp_regex)

CONTRACT = "ls-orders-1"


def po_date(po):
    """The date a PO counts from: consignment_date, else created_at."""
    return po.get("consignment_date") or po.get("created_at") or ""


def in_window(po, since_iso):
    return po_date(po)[:10] >= since_iso[:10]


def slim_line(line):
    count = num(line.get("count"))
    cost = num(line.get("cost"))
    return {
        "product_id": line.get("product_id"),
        "count": count,
        "received": num(line.get("received")),
        "unit_cost": cost,
        "cost_total": round(count * cost, 2),
        "status": line.get("status"),
    }


def slim_po(po, lines, supplier_names, regex):
    name = po.get("name") or ""
    return {
        "consignment_id": po.get("id"),
        "reference": po.get("reference"),
        "supplier_invoice": po.get("supplier_invoice"),
        "supplier": supplier_names.get(po.get("supplier_id")),
        "status": po.get("status"),
        "po_date": po_date(po),
        "due_at": po.get("due_at"),
        "received_at": po.get("received_at"),
        "pp": parse_pp(name, regex),
        "pp_candidates": pp_candidates(name, regex),
        "lines": [slim_line(l) for l in lines if not l.get("deleted_at")],
    }


def build(pos, lines_by_id, supplier_names, policy, window):
    regex = pp_regex(policy)
    projects, ambiguous, product_cost = {}, [], {}
    counts = {"supplier_pos_in_window": 0, "pp_tagged": 0, "lines": 0}
    for po in sorted(pos, key=po_date):
        rec = slim_po(po, lines_by_id.get(po.get("id"), []), supplier_names, regex)
        counts["supplier_pos_in_window"] += 1
        counts["lines"] += len(rec["lines"])
        for line in rec["lines"]:
            if line["unit_cost"] > 0 and line["product_id"]:
                # sorted oldest first, so the last write is the latest PO
                product_cost[line["product_id"]] = {
                    "unit_cost": line["unit_cost"], "po_reference": rec["reference"],
                    "po_date": rec["po_date"], "status": rec["status"],
                    "supplier": rec["supplier"]}
        if len(rec["pp_candidates"]) > 1:
            ambiguous.append({k: rec[k] for k in ("consignment_id", "reference", "po_date", "pp_candidates")})
            continue
        if rec["pp"] is None:
            continue
        counts["pp_tagged"] += 1
        projects.setdefault(rec["pp"], {"pp": f"PP-{rec['pp']}", "purchase_orders": []})[
            "purchase_orders"].append(rec)
    for proj in projects.values():
        proj["po_ids"] = [p["consignment_id"] for p in proj["purchase_orders"]]
        proj["cost_total"] = round(sum(l["cost_total"] for p in proj["purchase_orders"]
                                       for l in p["lines"]), 2)
        flags = []
        if any(p["status"] != "RECEIVED" for p in proj["purchase_orders"]):
            flags.append("not_yet_received")
        if len(proj["purchase_orders"]) > 1:
            flags.append("multiple_pos")
        proj["flags"] = flags
    counts["projects"] = len(projects)
    counts["ambiguous_pp_pos"] = len(ambiguous)
    counts["products_with_po_cost"] = len(product_cost)
    return {
        "contract": CONTRACT,
        "source": "lightspeed-orders",
        "pulled_at": datetime.now(TZ).isoformat(),
        "window": window,
        "counts": counts,
        "projects": dict(sorted(projects.items(), key=lambda kv: int(kv[0]))),
        "ambiguous_pp_pos": ambiguous,
        "product_po_cost": product_cost,
    }


def add_product_names(out, client):
    """SKU and name on PP-tagged PO lines, so a flooring line can be named by what was
    ordered (Decision 17). One product GET per distinct product; untagged POs skipped."""
    ids = {l["product_id"] for proj in out["projects"].values()
           for po in proj["purchase_orders"] for l in po["lines"] if l["product_id"]}
    names = {}
    for pid in sorted(ids):
        body = client.get(f"{client.products_path()}/{pid}")
        rec = body.get("data", body) if isinstance(body, dict) else {}
        names[pid] = (rec.get("sku"), rec.get("name"))
    for proj in out["projects"].values():
        for po in proj["purchase_orders"]:
            for l in po["lines"]:
                l["sku"], l["product_name"] = names.get(l["product_id"], (None, None))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, help="Window in days (default policy orders_window_days)")
    ap.add_argument("--out", type=Path, help="Default ingest/<today>/ls-orders.json")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    load_dotenv(REPO_ROOT / ".env")
    policy = load_policy()
    days = args.days or policy["lightspeed"]["orders_window_days"]
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    window = {"since": since, "days": days}
    try:
        client = LightspeedClient(config=load_config(), verbose=args.verbose)
        cc = client.cfg["api"]["consignments"]
        suppliers = {s.get("id"): s.get("name")
                     for s in client.paginate(cc["suppliers_path"], page_size=cc["page_size"])}
        pos = [po for po in client.supplier_consignments() if in_window(po, since)]
        lines_by_id = {po["id"]: client.consignment_products(po["id"]) for po in pos}
    except LightspeedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    out = build(pos, lines_by_id, suppliers, policy, window)
    try:
        add_product_names(out, client)
    except LightspeedError as e:
        print(f"warning: product names not added: {e}", file=sys.stderr)
    out["api_stats"] = client.stats()
    path = args.out or REPO_ROOT / "ingest" / datetime.now(TZ).date().isoformat() / "ls-orders.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    c = out["counts"]
    print(f"{c['supplier_pos_in_window']} supplier POs since {since}, {c['pp_tagged']} PP-tagged "
          f"across {c['projects']} projects, PO cost for {c['products_with_po_cost']} products "
          f"-> {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
