#!/usr/bin/env python3
"""Pull Lightspeed sales tagged with a Titan project number. READ ONLY.

For the payout flow (methods/payouts.md): every sale whose sale-level note carries
a project number (PP-###) in the window, grouped by project, with each line
classified flooring / non-flooring (NFM) / unclassified and its pre-tax revenue,
tax and cost-of-goods. /project-costs-sync turns this into suggested NFM costs,
NFM revenue and Flooring Line Items; nothing here touches Notion or writes to
Lightspeed.

    python3 scripts/ls_sales_pull.py                  # last sales_window_days
    python3 scripts/ls_sales_pull.py --days 30
    python3 scripts/ls_sales_pull.py --pp 463         # one project, still full window

Output: ingest/YYYY-MM-DD/ls-sales.json per contracts/ls-sales-schema.md.

Facts this relies on (verified live 2026-10-06, platform-settings/lightspeed.json
`api.sales`):
  * the project number lives ONLY in the sale-level `note`; line notes never
    carry it, and there is no tag or custom field;
  * receipt numbers are NOT unique (L-40372 is two different sales), so sales
    are keyed on `id`;
  * parked / pending sales change, so every run re-pulls the whole window;
  * a line's cost is frozen at sale time (average cost for stocked items), so a
    zero-cost stocked line never fills in later — it is flagged instead.

Personal data: sale notes and customer records hold customer names. This script
keeps only the parsed project number and the @keyword from a note; it writes no
note text, no customer id and no customer name.

Environment: LIGHTSPEED_DOMAIN_PREFIX, LIGHTSPEED_PERSONAL_TOKEN, read from .env.
Config: platform-settings/lightspeed.json (API), platform-settings/payout-policy.json
(regex, windows, flooring categories, zero-cost allow-list).
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lightspeed_client import LightspeedClient, LightspeedError, load_config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY = REPO_ROOT / "platform-settings" / "payout-policy.json"
TZ = ZoneInfo("America/Toronto")
CONTRACT = "ls-sales-1"
KEYWORD_RE = re.compile(r"@(pack|order|stock|return|material)\b", re.IGNORECASE)


def load_policy(path=POLICY):
    return json.loads(Path(path).read_text())


def load_dotenv(path):
    """Minimal .env loader (same rule as scripts/ghl_client.py: real env wins)."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        if val:
            os.environ.setdefault(key.strip(), val)


def pp_regex(policy):
    return re.compile(policy["lightspeed"]["pp_regex"])


def parse_pp(text, regex):
    """The project number in a note, as an int string ('463'), or None.

    More than one distinct number in one note is ambiguous and returns None —
    the caller flags it rather than filing the sale on either project.
    """
    if not text:
        return None
    found = {m.group(1).lstrip("0") or "0" for m in regex.finditer(text)}
    return found.pop() if len(found) == 1 else None


def pp_candidates(text, regex):
    return sorted({m.group(1).lstrip("0") or "0" for m in regex.finditer(text or "")})


def keyword_of(text):
    m = KEYWORD_RE.search(text or "")
    return m.group(1).lower() if m else None


def money(x):
    """Lightspeed money -> float rounded to cents (it sends floats and strings)."""
    try:
        return round(float(x or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def num(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def product_index(products):
    """id -> {sku, name, category} from the LS product walk."""
    from lightspeed_pull import category_of
    idx = {}
    for p in products:
        idx[p.get("id")] = {
            "sku": p.get("sku"),
            "name": p.get("name"),
            "category": category_of(p),
        }
    return idx


def classify(product, policy):
    """'flooring' | 'nfm' | 'unclassified' for one line's product."""
    if not product or not product.get("category"):
        return "unclassified"
    leaves = {c.upper() for c in policy["lightspeed"]["flooring_category_leaves"]}
    return "flooring" if product["category"].upper() in leaves else "nfm"


def is_nonstock_zero_ok(product, policy):
    allow = {a.lower() for a in policy["lightspeed"]["nonstock_zero_cost_ok"]}
    if not product:
        return False
    for key in ("sku", "name"):
        v = (product.get(key) or "").lower()
        if v in allow:
            return True
    return False


def summarize_line(line, product, policy):
    cls = classify(product, policy)
    cost_total = money(line.get("total_cost", line.get("cost_total")))
    price_total = money(line.get("total_price", line.get("price_total")))
    out = {
        "line_id": line.get("id"),
        "product_id": line.get("product_id"),
        "sku": (product or {}).get("sku"),
        "product_name": (product or {}).get("name"),
        "category": (product or {}).get("category"),
        "class": cls,
        "quantity": num(line.get("quantity")),
        "unit_price": num(line.get("unit_price", line.get("price"))),
        "unit_cost": num(line.get("unit_cost", line.get("cost"))),
        "price_total_pretax": price_total,
        "tax_total": money(line.get("total_tax", line.get("tax_total"))),
        "cost_total": cost_total,
        "is_return": bool(line.get("is_return")),
        "flags": [],
    }
    if out["unit_cost"] == 0 and out["quantity"] != 0:
        if is_nonstock_zero_ok(product, policy):
            out["zero_cost"] = "expected_nonstock"
        else:
            out["zero_cost"] = "stocked_or_unknown"
            out["flags"].append("zero_cost_line")
    if cls == "unclassified":
        out["flags"].append("unclassified_line")
    return out


def summarize_sale(sale, products, policy, regex):
    """One sale -> the slim record the contract carries, or None if voided."""
    if (sale.get("state") or "").lower() == "voided" or sale.get("status") == "VOIDED":
        return None
    note = sale.get("note") or ""
    lines = []
    for li in sale.get("line_items") or []:
        if (li.get("status") or "").upper() == "VOIDED":
            continue
        lines.append(summarize_line(li, products.get(li.get("product_id")), policy))
    totals = {}
    for cls in ("flooring", "nfm", "unclassified"):
        sel = [l for l in lines if l["class"] == cls]
        totals[cls] = {
            "revenue_pretax": round(sum(l["price_total_pretax"] for l in sel), 2),
            "tax": round(sum(l["tax_total"] for l in sel), 2),
            "cost": round(sum(l["cost_total"] for l in sel), 2),
        }
    flags = sorted({f for l in lines for f in l["flags"]})
    revenue = money(sale.get("total_price"))
    cost = round(sum(l["cost_total"] for l in lines), 2)
    if revenue == 0 and cost > 0:
        flags.append("zero_revenue_sale")
    state = (sale.get("state") or "").lower()
    if state in ("parked", "pending"):
        flags.append("provisional_open_sale")
    candidates = pp_candidates(note, regex)
    if len(candidates) > 1:
        flags.append("ambiguous_pp")
    return {
        "sale_id": sale.get("id"),
        "receipt": sale.get("invoice_number") or sale.get("receipt_number"),
        "sale_date": sale.get("sale_date"),
        "state": state,
        "status": sale.get("status"),
        "keyword": keyword_of(note),
        "pp": parse_pp(note, regex),
        "pp_candidates": candidates,
        "total_price_pretax": revenue,
        "total_tax": money(sale.get("total_tax")),
        "total_cost": cost,
        "totals_by_class": totals,
        "lines": lines,
        "flags": sorted(set(flags)),
    }


def build(sales, products, policy, window, pp_filter=None):
    regex = pp_regex(policy)
    projects, untagged_pack, ambiguous = {}, [], []
    seen = set()
    counts = {"sales_total": 0, "voided_skipped": 0, "pp_tagged": 0}
    for sale in sales:
        sid = sale.get("id")
        if sid in seen:            # offset paging can repeat a record if sales shift
            continue
        seen.add(sid)
        counts["sales_total"] += 1
        rec = summarize_sale(sale, products, policy, regex)
        if rec is None:
            counts["voided_skipped"] += 1
            continue
        if rec["pp"] is None:
            if "ambiguous_pp" in rec["flags"]:
                ambiguous.append({k: rec[k] for k in ("sale_id", "receipt", "sale_date", "state", "pp_candidates")})
            elif rec["keyword"] == "pack":
                untagged_pack.append({k: rec[k] for k in ("sale_id", "receipt", "sale_date", "state")})
            continue
        if pp_filter and rec["pp"] != str(pp_filter).lstrip("0"):
            continue
        counts["pp_tagged"] += 1
        proj = projects.setdefault(rec["pp"], {"pp": f"PP-{rec['pp']}", "sales": []})
        proj["sales"].append(rec)

    for proj in projects.values():
        proj["sales"].sort(key=lambda s: s["sale_date"] or "")
        agg = {}
        for cls in ("flooring", "nfm", "unclassified"):
            agg[cls] = {k: round(sum(s["totals_by_class"][cls][k] for s in proj["sales"]), 2)
                        for k in ("revenue_pretax", "tax", "cost")}
        proj["totals_by_class"] = agg
        proj["sale_ids"] = [s["sale_id"] for s in proj["sales"]]
        proj["flooring_lines"] = [
            {"sale_id": s["sale_id"], **{k: l[k] for k in (
                "product_id", "sku", "product_name", "category", "quantity",
                "unit_price", "unit_cost", "price_total_pretax", "cost_total", "is_return")}}
            for s in proj["sales"] for l in s["lines"] if l["class"] == "flooring"]
        flags = sorted({f for s in proj["sales"] for f in s["flags"]})
        if len(proj["sales"]) > 1:
            flags.append("multiple_sales")
        proj["flags"] = flags

    counts["projects"] = len(projects)
    counts["untagged_pack_sales"] = len(untagged_pack)
    counts["ambiguous_pp_sales"] = len(ambiguous)
    return {
        "contract": CONTRACT,
        "source": "lightspeed-sales",
        "pulled_at": datetime.now(TZ).isoformat(),
        "window": window,
        "pp_filter": pp_filter,
        "counts": counts,
        "projects": dict(sorted(projects.items(), key=lambda kv: int(kv[0]))),
        "untagged_pack_sales": untagged_pack,
        "ambiguous_pp_sales": ambiguous,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, help="Window in days (default policy sales_window_days)")
    ap.add_argument("--pp", help="Keep one project number, e.g. 463")
    ap.add_argument("--out", type=Path, help="Default ingest/<today>/ls-sales.json")
    ap.add_argument("--refresh-products", action="store_true",
                    help="Re-walk the LS product catalogue even if today's cache exists")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    load_dotenv(REPO_ROOT / ".env")
    policy = load_policy()
    days = args.days or policy["lightspeed"]["sales_window_days"]
    now = datetime.now(timezone.utc)
    window = {"date_from": (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z"),
              "date_to": None, "days": days}
    try:
        client = LightspeedClient(config=load_config(), verbose=args.verbose)
        import lightspeed_pull
        products, _ = lightspeed_pull.load_or_walk(
            client, lightspeed_pull.today(), args.refresh_products, None)
        sales = list(client.search_sales(window["date_from"]))
    except LightspeedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    out = build(sales, product_index(products), policy, window, pp_filter=args.pp)
    out["api_stats"] = client.stats()
    path = args.out or REPO_ROOT / "ingest" / datetime.now(TZ).date().isoformat() / "ls-sales.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    c = out["counts"]
    print(f"{c['sales_total']} sales, {c['pp_tagged']} PP-tagged across {c['projects']} projects, "
          f"{c['untagged_pack_sales']} @pack without PP, {c['ambiguous_pp_sales']} ambiguous "
          f"-> {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
