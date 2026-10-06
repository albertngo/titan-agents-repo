#!/usr/bin/env python3
"""Plan the daily cost updates for the payout flow. READ ONLY.

Deterministic half of /project-costs-sync (.claude/commands/project-costs-sync.md).
Reads a Notion finance snapshot, today's ls-sales.json, ls-orders.json and
supplier-docs.json (scripts/supplier_docs_pull.py), and
writes ONE plan of proposed Notion changes. The command applies the plan through
the Notion MCP only when write_mode.project_costs_sync is `write`; in `plan_only`
nothing reaches Notion.

    python3 scripts/project_costs_sync.py --snapshot ingest/<date>/notion-finance.json \
        --ls-sales ingest/<date>/ls-sales.json --ls-orders ingest/<date>/ls-orders.json

Output: plans/<date>/costs-plan.json (contracts/costs-plan-schema.md).

Suggest-and-review (amendment §4): every action is either
  * `write`   — the sources agree and the target field is empty or owned by the
                sync (Cost source Lightspeed / AP invoice (auto)); applied silently;
  * `suggest` — sources disagree, or the field holds a hand-entered value, or the
                source is weak; lands in the row's Suggested* fields and the
                "Costs to confirm" view for Albert. The sync never overwrites a
                hand-entered `Cost source` (plan Workstream C step 4).

Actions:
  nfm_cost            NFM cost row <- Lightspeed NFM POS total incl. tax (today's meaning)
  ls_sale_found       Titan Projects `LS Sale Found` <- a PP-tagged sale exists
  flooring_line       one Flooring Line Item per ordered product (create or update):
                      Cost Rate = the best ordered source — supplier invoice net of
                      credit memos (final, locks) > supplier confirmation > LS purchase
                      order; re-proposed whenever an invoice or credit changes it.
                      Sold At Rate = the PM's Quote Rate, never the Lightspeed sale.
                      The LS sale is compared only: a different product or rate is
                      flagged as a PM entry mistake (Decisions 17-18)
  financials_relations Financials `Costs` / `Flooring Line Items` <- project's own
  costs_complete      tick when submitted and no cost is missing
  payment_project     suggest a project for an unlinked payment (Decision 12)
  stamp_paid          Payout Batches marked Paid -> cost rows' paid date/reference
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import payments_match  # noqa: E402
import payout_run as pr  # noqa: E402

CONTRACT = "costs-plan-1"


def action_id(kind, target, payload):
    h = hashlib.sha1(json.dumps([kind, target, payload], sort_keys=True).encode()).hexdigest()[:10]
    return f"{kind}:{h}"


def mk(kind, target, mode, fields, confidence, reason, pp=None, **extra):
    a = {"id": action_id(kind, target, fields), "kind": kind, "target_url": target, "pp": pp,
         "mode": mode, "fields": fields, "confidence": confidence, "reason": reason}
    a.update(extra)
    return a


def sync_owns(cost_row, reg):
    src = cost_row.get("cost_source")
    return src in (None, "") or src in reg["project_costs"]["sync_owned_sources"]


STAGE_RANK = {"invoice_final": 5, "invoice_partial": 4, "confirmation": 3, "purchase_order": 2,
              "purchase_order_untagged": 1, "ls_sale": 0}


def po_digits(reference):
    m = re.search(r"(\d+)", reference or "")
    return m.group(1) if m else None


def supplier_order_for(po_reference, supplier):
    """The live supplier order (estimate) behind one LS PO, by the PO number it prints."""
    keys = (supplier.get("orders_by_po") or {}).get(po_digits(po_reference) or "", [])
    live = [supplier["orders"][k] for k in keys
            if supplier["orders"][k]["status"] not in ("cancelled", "superseded")]
    return live[-1] if live else None


def match_supplier_product(po_line, sorder):
    """The supplier code a PO line was ordered as: the sqft product whose quantity is
    within one box of the PO line (a PO keys sqft; the supplier bills boxes)."""
    best = None
    for code, p in (sorder or {}).get("products", {}).items():
        if not p.get("sf_per_box"):
            continue
        sq = p.get("confirmed_sqft") or p.get("invoiced_sqft") or 0
        gap = abs(sq - (po_line.get("count") or 0))
        if gap <= p["sf_per_box"] + 0.5 and (best is None or gap < best[0]):
            best = (gap, code, p)
    return (best[1], best[2]) if best else (None, None)


def ordered_items(proj_orders, product_po, supplier, sale_lines):
    """Every flooring product ordered for the project, with its staged cost."""
    sale_pids = {l["product_id"] for l in sale_lines}
    items = []
    for po in (proj_orders or {}).get("purchase_orders", []):
        sorder = supplier_order_for(po["reference"], supplier)
        for line in po["lines"]:
            code, sp = match_supplier_product(line, sorder)
            if not sp and line["product_id"] not in sale_pids:
                continue            # trims / sundries: not a flooring line
            it = {"product_id": line["product_id"], "sku": line.get("sku"),
                  "product_name": line.get("product_name"), "po_reference": po["reference"],
                  "po_status": po["status"], "po_received": line.get("received"),
                  "po_sqft": line["count"], "po_rate": line["unit_cost"], "supplier_code": code,
                  "estimate_no": (sorder or {}).get("estimate_no"),
                  "order_flags": list((sorder or {}).get("flags", [])),
                  "confirmation_date": ((sorder or {}).get("confirmation") or {}).get("date"),
                  "credits": [c["doc_no"] for c in (sorder or {}).get("credits", [])],
                  "invoices": [i["doc_no"] for i in (sorder or {}).get("invoices", [])]}
            if sp:
                it.update({k: sp.get(k) for k in ("sf_per_box", "confirmed_rate_sqft", "confirmed_sqft",
                                                  "invoiced_rate_sqft", "net_sqft", "net_amount",
                                                  "actual_rate_sqft", "credited_sqft")})
                it["stage"] = sp["stage"]
                it["rate"] = sp["actual_rate_sqft"] if sp["stage"].startswith("invoice") \
                    else sp["confirmed_rate_sqft"]
            else:
                it["stage"], it["rate"] = "purchase_order", line["unit_cost"]
            items.append(it)
    return items


def pair_lines(sale_lines, items):
    """(sale_line, ordered_item) pairs: same product first, then one-to-one leftovers
    (the PM keyed a different product than was ordered)."""
    pairs, sl, it = [], list(sale_lines), list(items)
    for s in list(sl):
        hit = next((i for i in it if i["product_id"] == s["product_id"]), None)
        if hit:
            pairs.append((s, hit)); sl.remove(s); it.remove(hit)
    if len(sl) == 1 and len(it) == 1:
        pairs.append((sl.pop(), it.pop()))
    pairs += [(s, None) for s in sl] + [(None, i) for i in it]
    return pairs


def flooring_actions(project, pp, num, ls, proj_orders, product_po, supplier, rows, fins, reg, policy):
    fc = policy["flooring_cost"]
    delta = fc["flag_delta_per_sqft_cents"] / 100
    ff = reg["flooring_line_items"]
    P = ff["properties"]
    T = {k: v["name"] for k, v in ff["to_add"].items()}
    sale_lines = (ls or {}).get("flooring_lines", [])
    items = ordered_items(proj_orders, product_po, supplier, sale_lines)
    if not sale_lines and not items:
        return []
    out = []
    today = datetime.now(pr.TZ).date()
    for sale, item in pair_lines(sale_lines, items):
        flags = []
        if item is None:        # nothing ordered for this sale line under the PP
            q = product_po.get(sale["product_id"])
            if q:
                item = {"sku": sale["sku"], "product_name": sale["product_name"], "stage":
                        "purchase_order_untagged", "rate": q["unit_cost"], "po_reference": q["po_reference"],
                        "po_rate": q["unit_cost"], "order_flags": [], "credits": [], "invoices": []}
                flags.append("no_project_po")
            else:
                item = {"sku": sale["sku"], "product_name": sale["product_name"], "stage": "ls_sale",
                        "rate": sale["unit_cost"], "order_flags": [], "credits": [], "invoices": []}
                flags.append("no_order_found")
        sku = item["sku"] or (sale or {}).get("sku")
        stage, rate = item["stage"], item.get("rate")
        if sale and item.get("product_id") and sale["product_id"] != item["product_id"]:
            flags.append("pm_entry_product_mismatch")
        if sale is None:
            flags.append("ordered_not_on_sale")
        if sale and rate is not None and abs(sale["unit_cost"] - rate) > delta:
            flags.append("sale_cost_gap")
        truth = item.get("actual_rate_sqft") if stage.startswith("invoice") else item.get("confirmed_rate_sqft")
        if truth is not None and item.get("po_rate") is not None and abs(item["po_rate"] - truth) > delta:
            flags.append("po_rate_gap")
        flags += [f for f in item["order_flags"] if f.startswith(("rate_changed", "restocking",
                                                                  "credit_attributed"))]
        if stage.startswith("invoice") and item.get("po_status") not in (None, "RECEIVED"):
            flags.append("po_not_received_in_lightspeed")
        cd = pr.parse_date(item.get("confirmation_date"))
        if stage == "confirmation" and cd and (today - cd).days > fc["confirmed_not_invoiced_days"]:
            flags.append("confirmed_not_invoiced")
        sold_sqft = (sale or {}).get("quantity")
        if sold_sqft and item.get("net_sqft") and item.get("sf_per_box") and \
                abs(item["net_sqft"] - sold_sqft) > item["sf_per_box"] * fc["qty_gap_tolerance_boxes"]:
            flags.append("qty_gap")

        row = next((r for r in rows if (r.get("title") or "").strip() == (sku or "")), None)
        wrong_row = None
        if row is None and sale and sale["sku"] != sku:
            wrong_row = next((r for r in rows if (r.get("title") or "").strip() == sale["sku"]), None)
        target = row or wrong_row

        fields = {P["cost_rate"]: rate, T["ls_sale_cost_rate"]: (sale or {}).get("unit_cost"),
                  T["po_cost_rate"]: item.get("po_rate"),
                  T["invoice_cost_rate"]: item.get("actual_rate_sqft") if stage.startswith("invoice") else None,
                  T["cost_locked"]: stage == "invoice_final"}
        if target is None or wrong_row is not None:
            fields[P["title"]] = sku
        if target is None:
            fields[P["sqft_sold"]] = sold_sqft
            fields[P["project"]] = [project["url"]]
            if len(fins) == 1:
                fields[P["project_financials"]] = [fins[0]["url"]]
        quote = pr.money((target or {}).get("quote_rate"))
        sold_at = pr.money((target or {}).get("sold_at_rate"))
        if quote is not None and sold_at != quote:
            fields[P["sold_at_rate"]] = quote
        if quote is None and sold_at is None:
            flags.append("quote_rate_missing")
        fields = {k: v for k, v in fields.items() if v is not None}

        if target is not None:      # drop what already matches: agreement is silent
            fmap = pr.field_map(ff)
            def same(name, v):
                cur = target.get(fmap.get(name, name))
                if isinstance(v, bool):
                    return pr.truthy(cur) == v
                if isinstance(v, (int, float)):
                    return pr.money(cur) is not None and abs(pr.money(cur) - v) < 0.00005
                return cur == v
            fields = {k: v for k, v in fields.items() if not same(k, v)}
            if not fields:
                continue
            if pr.truthy(target.get("cost_locked")) and P["cost_rate"] in fields:
                flags.append("changed_after_lock")

        if wrong_row is not None:
            mode = "suggest"            # renaming a PM's line is their call
        elif stage.startswith("invoice"):
            mode = "write"              # the invoice is the truth, and replaces earlier stages
        elif stage in ("confirmation", "purchase_order") and \
                (target is None or pr.money(target.get("cost_rate")) is None):
            mode = "write"              # interim figure into an empty line
        else:
            mode = "suggest"
        conf = {"invoice_final": "High", "invoice_partial": "High", "confirmation": "High",
                "purchase_order": "Medium"}.get(stage, "Low")

        bits = [f"{sku}: cost {rate:.4f}/sqft from {stage.replace('_', ' ')}"]
        if stage.startswith("invoice"):
            bits.append(f"invoices {', '.join(item['invoices'])}"
                        + (f" less credits {', '.join(item['credits'])}" if item["credits"] else "")
                        + f" = {item['net_sqft']} sqft for ${item['net_amount']:.2f} pre-tax")
        if item.get("estimate_no"):
            bits.append(f"supplier order {item['estimate_no']} ({item.get('supplier_code')}) on {item['po_reference']}")
        elif item.get("po_reference"):
            bits.append(f"PO {item['po_reference']}")
        if "pm_entry_product_mismatch" in flags:
            bits.append(f"Lightspeed sale has {sale['sku']} — PM entry mistake, ordered product used")
        if "sale_cost_gap" in flags:
            bits.append(f"sale-line cost {sale['unit_cost']:.2f}/sqft")
        if "qty_gap" in flags:
            bits.append(f"kept {item['net_sqft']} sqft vs {sold_sqft} sold")
        if "po_not_received_in_lightspeed" in flags:
            bits.append(f"{item['po_reference']} not received in Lightspeed")
        reason = "; ".join(bits)
        op = "create" if target is None else "update"
        out.append(mk("flooring_line", target["url"] if target else project["url"], mode, fields,
                      conf, reason, pp, op=op, stage=stage, flags=sorted(set(flags))))
    return out


def plan(snapshot, reg, policy, ls_sales=None, ls_orders=None, supplier_docs=None):
    n = pr.normalize_snapshot(snapshot, reg)
    idx, wo_by_project, pay_by_project, fin_by_project = pr.build_index(n)
    cats = reg["project_costs"]["categories"]
    names = {k: v["name"] for k, v in reg["project_costs"]["to_add"].items()}
    pnames = reg["project_costs"]["properties"]
    actions, notes = [], []
    sales = (ls_sales or {}).get("projects", {})
    orders = (ls_orders or {}).get("projects", {})
    product_po = (ls_orders or {}).get("product_po_cost", {})
    supplier = supplier_docs or {}

    flines_by_project = {}
    for fl in n["flooring_lines"]:
        for p in pr.as_list(fl.get("project")):
            flines_by_project.setdefault(pr.page_id(p), []).append(fl)

    costs_by_project = {}
    for c in n["costs"]:
        for p in pr.as_list(c.get("project")):
            costs_by_project.setdefault(pr.page_id(p), []).append(c)

    for pid, project in idx["projects"].items():
        if not pr.in_scope(project, policy):
            continue
        pp = pr.pp_label(project)
        num = pp.replace("PP-", "") if pp else None
        ls = sales.get(num) if num else None
        rows = costs_by_project.get(pid, [])

        # LS Sale Found
        if ls and not pr.truthy(project.get("ls_sale_found")):
            actions.append(mk("ls_sale_found", project["url"], "write",
                              {reg["titan_projects"]["to_add"]["ls_sale_found"]["name"]: True},
                              "High", f"{len(ls['sale_ids'])} Lightspeed sale(s) carry {pp}", pp))

        # NFM cost: the full Lightspeed POS total incl. tax, exactly what is typed today
        # (Decision 10, Albert 2026-10-06). Commission's fixed 25% estimate is unchanged.
        if ls:
            nfm = ls["totals_by_class"]["nfm"]
            pos_total = round(nfm["revenue_pretax"] + nfm["tax"], 2)
            submitted = (project.get("submission_status") or "") in \
                policy["lightspeed"].get("parked_sale_final_when_submission_in", [])
            open_sale = "provisional_open_sale" in ls["flags"] and not submitted
            other_flags = [f for f in ls["flags"] if f != "provisional_open_sale"]
            conf = "Medium" if open_sale else "High"
            reason = (f"Lightspeed NFM POS total {pos_total:.2f} incl. tax over "
                      f"{len(ls['sale_ids'])} sale(s)" + (" — sale still open, may change" if open_sale else ""))
            for row in [r for r in rows if r.get("category") == cats["nfm"]]:
                current = pr.money(row.get("cost"))
                if current is not None and abs(current - pos_total) < 0.005:
                    continue
                fields = {pnames["cost"]: pos_total, names["ls_sale_ids"]: ", ".join(ls["sale_ids"]),
                          names["cost_source"]: "Lightspeed"}
                if sync_owns(row, reg) and conf == "High" and not other_flags:
                    actions.append(mk("nfm_cost", row["url"], "write", fields, conf, reason, pp))
                else:
                    why = reason if sync_owns(row, reg) else \
                        f"{reason}; row holds a hand-entered cost ({current}) — confirm"
                    if other_flags or open_sale:
                        why += f"; Lightspeed flags: {', '.join(other_flags + (['sale still open'] if open_sale else []))}"
                    actions.append(mk("nfm_cost", row["url"], "suggest", {
                        names["suggested_cost"]: pos_total, names["suggestion_source"]: "Lightspeed",
                        names["suggestion_confidence"]: conf, names["suggestion_reason"]: why[:1900]},
                        conf, why, pp))

        # flooring line items: cost = what was ordered, final = invoice net of credits;
        # sold-at = the PM's quote, never the Lightspeed sale (Decisions 17-18)
        fins_here = fin_by_project.get(pid, [])
        for a in flooring_actions(project, pp, num, ls, orders.get(num), product_po, supplier,
                                  flines_by_project.get(pid, []), fins_here, reg, policy):
            actions.append(a)

        # Financials relations copy (financials-relation-sync logic)
        fins = fin_by_project.get(pid, [])
        if len(fins) == 1:
            fin = fins[0]
            want = sorted(pr.page_id(u) for u in pr.as_list(project.get("project_costs")))
            have = sorted(pr.page_id(u) for u in pr.as_list(fin.get("costs")))
            if want and want != have:
                actions.append(mk("financials_relations", fin["url"], "write",
                                  {reg["project_financials"]["properties"]["costs"]:
                                   pr.as_list(project.get("project_costs"))},
                                  "High", f"Financials `Costs` relation differs from the project's "
                                          f"Project Costs ({len(have)} vs {len(want)})", pp))
            # Costs Complete
            submitted = (project.get("submission_status") or "") in ("Submitted", "Ready To Submit")
            missing = [r for r in rows if r.get("category") in (cats["labor"], cats["disposal"], cats["nfm"])
                       and not pr.money(r.get("cost"))]
            if submitted and rows and not missing and not pr.truthy(fin.get("costs_complete")):
                actions.append(mk("costs_complete", fin["url"], "write",
                                  {reg["project_financials"]["properties"]["costs_complete"]: True},
                                  "High", "submitted and every labor / disposal / NFM cost is present", pp))
        elif len(fins) > 1:
            notes.append({"pp": pp, "note": f"{len(fins)} Financials rows point at this project — fix by hand"})

    # payments
    for s in payments_match.suggest(snapshot, reg, policy):
        tn = reg["master_payments_log"]["to_add"]
        fields = {tn["match_confidence"]["name"]: s["confidence"], tn["match_reason"]["name"]: s["reason"]}
        if s["suggested_project_url"]:
            fields[tn["suggested_project"]["name"]] = [s["suggested_project_url"]]
        actions.append(mk("payment_project", s["payment_url"], "suggest", fields,
                          s["confidence"], s["reason"], s.get("pp")))

    # stamp paid from batches Albert marked Paid
    for b in snapshot.get("payout_batches") or []:
        if not pr.truthy(b.get("Paid")) or not b.get("Reference"):
            continue
        for line_url in pr.as_list(pr.coerce(b.get("Lines"))):
            actions.append(mk("stamp_paid", line_url, "write", {
                pnames["paid_out_date"]: (b.get("Paid Date") or "")[:10],
                pnames["paid_reference"]: b["Reference"]}, "High",
                f"batch {b.get('Name') or b.get('url')} marked Paid by Albert"))

    counts = {}
    for a in actions:
        counts.setdefault(a["kind"], {"write": 0, "suggest": 0})[a["mode"]] += 1
    return {
        "contract": CONTRACT,
        "built_at": datetime.now(pr.TZ).isoformat(),
        "write_mode": policy["write_mode"]["project_costs_sync"],
        "counts": counts,
        "actions": actions,
        "notes": notes,
        "ls_untagged_pack_sales": len((ls_sales or {}).get("untagged_pack_sales", [])),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", required=True, type=Path)
    ap.add_argument("--ls-sales", type=Path)
    ap.add_argument("--ls-orders", type=Path)
    ap.add_argument("--supplier-docs", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    s = pr.SETTINGS
    out = plan(pr.load_json(args.snapshot), pr.load_json(s / "notion-finance.json"),
               pr.load_json(s / "payout-policy.json"),
               ls_sales=pr.load_json(args.ls_sales) if args.ls_sales else None,
               ls_orders=pr.load_json(args.ls_orders) if args.ls_orders else None,
               supplier_docs=pr.load_json(args.supplier_docs) if args.supplier_docs else None)
    path = args.out or pr.REPO_ROOT / "plans" / datetime.now(pr.TZ).date().isoformat() / "costs-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(out['actions'])} actions {out['counts']} (write_mode {out['write_mode']}) "
          f"-> {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
