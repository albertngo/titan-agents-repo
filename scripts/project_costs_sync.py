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
  disposal_cost       Disposal row <- AP Disposal invoice total incl. HST, matched by
                      street + date window; zero or several candidates -> a note,
                      never a pick; a re-issued invoice that moved site -> suggest
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
from supplier_docs_pull import parse_street  # noqa: E402

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
    """The sync may set `Cost` on a row it filled itself, or on an empty row. A cost with
    no `Cost Source` was typed by a person (every row before 2026-10 is like that)."""
    src = cost_row.get("cost_source")
    if src in reg["project_costs"]["sync_owned_sources"]:
        return True
    return src in (None, "") and pr.money(cost_row.get("cost")) is None


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


def ordered_items(proj_orders, product_po, supplier, sale_lines, flooring_prefixes=()):
    """Every flooring product ordered for the project, with its staged cost."""
    sale_pids = {l["product_id"] for l in sale_lines}
    prefixes = tuple(p.upper() for p in flooring_prefixes)
    items = []
    for po in (proj_orders or {}).get("purchase_orders", []):
        sorder = supplier_order_for(po["reference"], supplier)
        for line in po["lines"]:
            code, sp = match_supplier_product(line, sorder)
            if not sp and line["product_id"] not in sale_pids and \
                    not (prefixes and str(line.get("sku") or "").upper().startswith(prefixes)):
                continue            # trims / sundries: not a flooring line
            it = {"product_id": line["product_id"], "sku": line.get("sku"),
                  "product_name": line.get("product_name"), "po_reference": po["reference"],
                  "po_status": po["status"], "po_received": line.get("received"),
                  "po_sqft": line["count"], "po_rate": line["unit_cost"], "supplier_code": code,
                  "estimate_no": (sorder or {}).get("estimate_no"),
                  "order_flags": list((sorder or {}).get("flags", [])),
                  "confirmation_date": ((sorder or {}).get("confirmation") or {}).get("date"),
                  "credits": [c["doc_no"] for c in (sorder or {}).get("credits", [])],
                  "invoices": [i["doc_no"] for i in (sorder or {}).get("invoices", [])],
                  "supplier": po.get("supplier"),
                  "taxed": any((i.get("tax") or 0) > 0 for i in (sorder or {}).get("invoices", []))}
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


def title_sku(title):
    """'SPC-VIDR-0002_Yukon' -> 'spc-vidr-0002' (staff naming); a bare SKU is itself."""
    return (title or "").strip().split("_")[0].strip().lower()


def line_title(ff, sku, product_name):
    m = re.search(r"\(([^)]+)\)", product_name or "")
    if not sku:
        return product_name
    return ff.get("title_format", "{sku}").format(sku=sku, colour=m.group(1).strip()) if m else sku


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


def QC(ff, key):
    return ff["qty_check_options"][key]


def box_sqft(item, sale, fc):
    """sqft per box: supplier document, else 'NN.NNsf/b' in the LS name, else the default."""
    if item.get("sf_per_box"):
        return item["sf_per_box"]
    for name in ((sale or {}).get("product_name"), item.get("product_name")):
        m = re.search(r"([\d.]+)\s*sf\s*/\s*b", name or "", re.I)
        if m:
            return float(m.group(1))
    return fc["qty_check_default_box_sqft"]


def quantity_check(item, sale, target, stage, truth_sqft, rate, ff, fc):
    """(Qty Check value, auto note, (sqft, rate) once a person has verified, else None).

    Sold/quoted vs invoiced/ordered: within qty_check_band_boxes -> OK; a credit memo that
    accounts for the gap -> OK; less ordered -> Verify - part from stock; more -> Verify -
    leftover. A Verified answer already on the line is kept and decides sqft and cost."""
    current = ((target or {}).get("qty_check") or "").strip()
    quoted = pr.money((target or {}).get("quoted_sqft"))
    sold = quoted if quoted is not None else (sale or {}).get("quantity")
    band = box_sqft(item, sale, fc) * fc["qty_check_band_boxes"]
    sale_cost = (sale or {}).get("unit_cost")

    if current.startswith("Verified"):
        if current == QC(ff, "verified_from_stock") and sold and truth_sqft is not None and rate is not None:
            stock_sqft = max(sold - truth_sqft, 0)
            stock_rate = sale_cost if sale_cost else rate
            bought = item.get("net_amount") if stage.startswith("invoice") else truth_sqft * rate
            return current, None, (sold, round((bought + stock_sqft * stock_rate) / sold, 4))
        if current == QC(ff, "verified_leftover_to_stock") and sold:
            return current, None, (sold, rate)
        return current, None, None

    if stage in ("purchase_order_untagged", "ls_sale"):
        why = (f"no PO tagged with this project; latest {item.get('po_reference')} for the product is the cost"
               if stage == "purchase_order_untagged" else "no order found; the cost is the LS sale's")
        return QC(ff, "no_order"), f"Auto: {why}. Where did this material come from?", None
    if sold is None:
        return QC(ff, "no_sale"), (f"Auto: {round(truth_sqft or 0, 2)} sqft ordered, nothing on the LS sale "
                                   f"or Quoted Sqft. How much was installed?"), None
    if truth_sqft is None:
        return QC(ff, "ok"), None, None
    gap = truth_sqft - sold
    if abs(gap) <= band:
        return QC(ff, "ok"), None, None
    if gap < 0:
        credited = item.get("credited_sqft") or 0
        if credited and abs(truth_sqft + credited - sold) <= band:
            return QC(ff, "ok"), None, None          # the return explains it (PP-417 Toffee)
        stock_hint = (f"LS sale cost {sale_cost:.2f}/sqft: the product had stock value when sold"
                      if sale_cost else "LS sale cost 0: no stock value when sold, so another order?")
        return QC(ff, "part_from_stock"), (f"Auto: {round(truth_sqft, 2)} sqft ordered/invoiced vs {sold} sold "
                                            f"({round(-gap, 2)} short). {stock_hint}"), None
    return QC(ff, "leftover"), (f"Auto: {round(truth_sqft, 2)} sqft ordered/invoiced vs {sold} sold "
                                f"({round(gap, 2)} over). Back to stock, or used on the job?"), None


def flooring_actions(project, pp, num, ls, proj_orders, product_po, supplier, rows, fins, reg, policy):
    fc = policy["flooring_cost"]
    delta = fc["flag_delta_per_sqft_cents"] / 100
    ff = reg["flooring_line_items"]
    P = ff["properties"]
    T = {k: v["name"] for k, v in ff["to_add"].items()}
    sale_lines = (ls or {}).get("flooring_lines", [])
    items = ordered_items(proj_orders, product_po, supplier, sale_lines, ff.get("flooring_sku_prefixes", ()))
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
        legacy_po_sku = bool(sale and item.get("sku") and str(item["sku"]).isdigit()
                             and item.get("product_id") and sale["product_id"] != item["product_id"])
        if legacy_po_sku:
            # an old duplicate LS product (numeric SKU, e.g. 11401 for Vidar VS84) was put on the PO:
            # the cost still comes from what was ordered, the line is named after the catalogue SKU sold
            flags.append("legacy_ls_product_on_po")
            sku = sale["sku"]
        elif sale and item.get("product_id") and sale["product_id"] != item["product_id"]:
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
        # Order of truth for sqft AND cost (Albert 2026-10-07): supplier invoice -> what Titan
        # ordered (confirmation / project PO) -> the PM's quote (a typed line) -> the LS sale
        strong = stage.startswith("invoice") or stage in ("confirmation", "purchase_order")
        sale_sqft = (sale or {}).get("quantity")
        truth_sqft = (item.get("net_sqft") if stage.startswith("invoice") else
                      item.get("confirmed_sqft") if stage == "confirmation" else
                      item.get("po_sqft") if stage == "purchase_order" else None)
        sold_sqft = truth_sqft if truth_sqft is not None else sale_sqft

        row = next((r for r in rows if title_sku(r.get("title")) == (sku or "").lower()), None)
        wrong_row = None
        if row is None and sale and sale["sku"] != sku:
            wrong_row = next((r for r in rows if title_sku(r.get("title")) == sale["sku"].lower()), None)
        target = row or wrong_row

        # Quantity check (Albert 2026-10-08): what was sold/quoted vs what was invoiced/ordered
        qc, note, qty_rate = quantity_check(item, sale, target, stage, truth_sqft, rate, ff, fc)
        verified = qc.startswith("Verified")
        if qc == QC(ff, "part_from_stock") or qc == QC(ff, "leftover"):
            flags.append("qty_gap")
        if verified and qty_rate is not None:
            # a person said where the difference went: that answer sets the job's sqft and cost
            sold_sqft, rate = qty_rate
        hold_figures = (target is not None and not verified and
                        (not strong or qc == QC(ff, "part_from_stock")))

        fields = {P["cost_rate"]: rate, T["ls_sale_cost_rate"]: (sale or {}).get("unit_cost"),
                  T["po_cost_rate"]: item.get("po_rate"),
                  T["invoice_cost_rate"]: item.get("actual_rate_sqft") if stage.startswith("invoice") else None,
                  T["cost_locked"]: stage == "invoice_final"}
        if target is None or wrong_row is not None:
            fields[P["title"]] = line_title(ff, sku, (sale or {}).get("product_name") if legacy_po_sku
                                            else item.get("product_name") or (sale or {}).get("product_name"))
        if target is None or strong or verified:
            fields[P["sqft_sold"]] = round(sold_sqft, 2) if sold_sqft is not None else None
        if target is None:
            company = ff.get("material_company_from_supplier", {}).get((item.get("supplier") or "").upper())
            mtype = ff.get("material_type_from_category", {}).get(((sale or {}).get("category") or "").upper())
            if company:
                fields[P["material_company"]] = [company]
            if mtype:
                fields[P["material_type"]] = [mtype]
            if stage.startswith("invoice") and item.get("taxed"):
                fields[P["taxed_vs_cash"]] = "Taxed"
            fields[P["project"]] = [project["url"]]
            if len(fins) == 1:
                fields[P["project_financials"]] = [fins[0]["url"]]
        if hold_figures:
            # an untagged PO / the LS sale never overwrites a figure on the line, and a
            # part-from-stock line keeps its figures until front desk answers
            fields = {}
        if not verified:
            fields[T["qty_check"]] = qc
        if note and not ((target or {}).get("qty_note") or "").strip():
            fields[T["qty_note"]] = note
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
                    try:                    # full precision: rates carry 4 decimals ($3.8573)
                        return cur not in (None, "") and abs(float(cur) - v) < 0.00005
                    except (TypeError, ValueError):
                        return False
                return cur == v
            fields = {k: v for k, v in fields.items() if not same(k, v)}
            if not fields:
                continue
            if pr.truthy(target.get("cost_locked")) and P["cost_rate"] in fields:
                flags.append("changed_after_lock")

        mode = "suggest" if wrong_row is not None else "write"   # renaming a PM's line is their call
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
        if truth_sqft is not None:
            bits.append(f"sqft {round(truth_sqft, 2)} from {'invoice' if stage.startswith('invoice') else 'the order'}")
        bits.append(f"Qty Check: {qc}")
        if "po_not_received_in_lightspeed" in flags:
            bits.append(f"{item['po_reference']} not received in Lightspeed")
        reason = "; ".join(bits)
        op = "create" if target is None else "update"
        out.append(mk("flooring_line", target["url"] if target else project["url"], mode, fields,
                      conf, reason, pp, op=op, stage=stage, flags=sorted(set(flags)), qty_check=qc))
    return out


def same_street(a, b):
    if not a or not b or a["number"] != b["number"] or a["name_key"] != b["name_key"]:
        return False
    return not (a.get("unit") and b.get("unit") and a["unit"] != b["unit"])


def street_candidates(street, inv_date, projects, policy):
    """Projects at this street whose end date fits the invoice date (or have none yet)."""
    dp = policy["disposal"]
    hits, near = [], []
    for pid, proj in projects.items():
        ps = parse_street(proj.get("street_address"))
        if not ps or not street:
            continue
        if ps["name_key"] == street["name_key"] and ps["number"] != street["number"]:
            near.append(pid)
            continue
        if not same_street(street, ps):
            continue
        end = pr.parse_date(proj.get("project_end_date"))
        if end and inv_date and not (-dp["match_window_days_after_end"] <=
                                     (end - inv_date).days <= dp["match_window_days_before_end"]):
            continue
        hits.append(pid)
    return hits, near


def disposal_actions(supplier, projects, costs_by_project, reg, policy):
    """AP Disposal invoices -> the matched project's Disposal cost row (Decision 13)."""
    cats = reg["project_costs"]["categories"]
    pnames = reg["project_costs"]["properties"]
    names = {k: v["name"] for k, v in reg["project_costs"]["to_add"].items()}
    vendors = reg["project_costs"].get("disposal_vendors", {})
    actions, notes, by_project = [], [], {}

    def label(pid):
        return pr.pp_label(projects[pid]) or pid

    for inv in (supplier or {}).get("disposal_invoices", []):
        vendor = vendors.get(inv.get("supplier"), {})
        inv_date = pr.parse_date(inv.get("date"))
        flags = []
        if inv.get("previous_streets"):
            flags.append("reissued_new_site")
        hits, near = street_candidates(inv.get("street"), inv_date, projects, policy)
        prev_hits = []
        for st in inv.get("previous_streets", []):
            prev_hits += street_candidates(st, inv_date, projects, policy)[0]
        base = {"invoice": inv["doc_no"], "date": inv.get("date"), "total": inv.get("total")}
        if prev_hits:
            base["previously_matched"] = [label(p) for p in prev_hits]
        if not hits and near and vendor.get("team_page"):
            # AP has keyed a wrong house number before (2390: 4500 for 4600 Kimbermount).
            # One near miss whose Disposal row is already this vendor's -> a suggestion, never a write
            team = pr.page_id(vendor["team_page"])
            mine = [p for p in near if any(team in [pr.page_id(u) for u in pr.as_list(r.get("assigned_to"))]
                                          for r in costs_by_project.get(p, [])
                                          if r.get("category") == cats["disposal"])]
            if len(mine) == 1 and pr.in_scope(projects[mine[0]], policy):
                hits, flags = mine, flags + ["street_number_differs"]
        if len(hits) != 1:
            why = ("no street on the invoice" if not inv.get("street") else
                   "no project at that street in the date window" if not hits else
                   "more than one project at that street — not picked")
            notes.append(dict(base, kind="disposal_unmatched", reason=why,
                              candidates=[label(p) for p in hits], near_misses=[label(p) for p in near],
                              flags=flags))
            continue
        pid = hits[0]
        if not pr.in_scope(projects[pid], policy):
            rows = [r for r in costs_by_project.get(pid, []) if r.get("category") == cats["disposal"]]
            have = [pr.money(r.get("cost")) for r in rows]
            note = dict(base, kind="disposal_out_of_scope", pp=label(pid), flags=flags, row_costs=have)
            if inv.get("total") is not None and inv["total"] not in have:
                note["check"] = "Disposal row cost differs from this invoice"
            notes.append(note)
            continue
        by_project.setdefault(pid, {"invoices": [], "flags": set(flags), "vendor": vendor,
                                    "prev": []})
        by_project[pid]["invoices"].append(inv)
        by_project[pid]["prev"] += [label(p) for p in prev_hits]

    for pid, m in by_project.items():
        project, pp = projects[pid], label(pid)
        flags = set(m["flags"])
        total = round(sum(i["total"] or 0 for i in m["invoices"]), 2)
        nos = ", ".join(i["doc_no"] for i in m["invoices"])
        team = m["vendor"].get("team_page")
        assigned = [pr.page_id(u) for u in pr.as_list(project.get("assign_disposal"))]
        if team and pr.page_id(team) not in assigned:
            flags.add("project_assigned_other_disposal")
        rows = [r for r in costs_by_project.get(pid, []) if r.get("category") == cats["disposal"]]
        if not rows:
            notes.append({"kind": "disposal_no_row", "pp": pp, "invoice": nos, "total": total})
            continue
        row = next((r for r in rows if team and pr.page_id(team) in
                    [pr.page_id(u) for u in pr.as_list(r.get("assigned_to"))]), rows[0])
        if team and pr.page_id(team) not in [pr.page_id(u) for u in pr.as_list(row.get("assigned_to"))]:
            flags.add("row_assigned_to_other_payee")
        if len(rows) > 1:
            flags.add("several_disposal_rows")
        reason = (f"AP Disposal invoice {nos}: ${total:.2f} incl. HST, street matches {pp}"
                  + (f" (re-issued; earlier copy pointed at {', '.join(m['prev'])})" if m["prev"] else ""))
        current = pr.money(row.get("cost"))
        if current is not None and abs(current - total) < 0.005:
            if not row.get("invoice_number"):
                actions.append(mk("disposal_cost", row["url"], "write", {names["invoice_number"]: nos},
                                  "High", reason + "; cost already matches — invoice number only", pp,
                                  flags=sorted(flags)))
            continue
        fields = {pnames["cost"]: total, names["invoice_number"]: nos, names["cost_source"]: "AP Invoice (auto)"}
        blocking = flags & {"reissued_new_site", "several_disposal_rows", "row_assigned_to_other_payee",
                            "street_number_differs"}
        if sync_owns(row, reg) and not blocking:
            actions.append(mk("disposal_cost", row["url"], "write", fields, "High", reason, pp,
                              flags=sorted(flags)))
        else:
            why = reason if sync_owns(row, reg) else f"{reason}; row holds a hand-entered cost ({current}) — confirm"
            if blocking:
                why += f"; check: {', '.join(sorted(blocking))}"
            actions.append(mk("disposal_cost", row["url"], "suggest", {
                names["suggested_cost"]: total, names["suggestion_source"]: "AP Invoice (auto)",
                names["suggestion_confidence"]: "Medium" if blocking else "High",
                names["suggestion_reason"]: why[:1900]}, "Medium" if blocking else "High", why, pp,
                flags=sorted(flags)))
    return actions, notes


def kind_write_mode(policy, kind):
    """write_mode.project_costs_sync, unless project_costs_sync_kinds names the kind."""
    wm = policy["write_mode"]
    return (wm.get("project_costs_sync_kinds") or {}).get(kind, wm["project_costs_sync"])


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

    # disposal invoices -> Disposal cost rows
    d_actions, d_notes = disposal_actions(supplier, idx["projects"], costs_by_project, reg, policy)
    actions += d_actions
    notes += d_notes

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
        a["apply"] = kind_write_mode(policy, a["kind"]) == "write" and \
            (a["mode"] == "write" or a["kind"] != "flooring_line")
    return {
        "contract": CONTRACT,
        "built_at": datetime.now(pr.TZ).isoformat(),
        "write_mode": policy["write_mode"]["project_costs_sync"],
        "write_mode_kinds": {k: kind_write_mode(policy, k) for k in sorted(counts)},
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
