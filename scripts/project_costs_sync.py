#!/usr/bin/env python3
"""Plan the daily cost updates for the payout flow. READ ONLY.

Deterministic half of /project-costs-sync (.claude/commands/project-costs-sync.md).
Reads a Notion finance snapshot, today's ls-sales.json and ls-orders.json, and
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
  flooring_cost_rate  flooring line cost rates: PM vs PO (front desk) vs LS sale-line,
                      >$0.10/sqft apart -> suggest; front desk wins interim (§2.3)
  financials_relations Financials `Costs` / `Flooring Line Items` <- project's own
  costs_complete      tick when submitted and no cost is missing
  payment_project     suggest a project for an unlinked payment (Decision 12)
  stamp_paid          Payout Batches marked Paid -> cost rows' paid date/reference
"""

import argparse
import hashlib
import json
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


def mk(kind, target, mode, fields, confidence, reason, pp=None):
    return {"id": action_id(kind, target, fields), "kind": kind, "target_url": target, "pp": pp,
            "mode": mode, "fields": fields, "confidence": confidence, "reason": reason}


def sync_owns(cost_row, reg):
    src = cost_row.get("cost_source")
    return src in (None, "") or src in reg["project_costs"]["sync_owned_sources"]


def plan(snapshot, reg, policy, ls_sales=None, ls_orders=None):
    n = pr.normalize_snapshot(snapshot, reg)
    idx, wo_by_project, pay_by_project, fin_by_project = pr.build_index(n)
    cats = reg["project_costs"]["categories"]
    names = {k: v["name"] for k, v in reg["project_costs"]["to_add"].items()}
    pnames = reg["project_costs"]["properties"]
    actions, notes = [], []
    sales = (ls_sales or {}).get("projects", {})
    orders = (ls_orders or {}).get("projects", {})
    product_po = (ls_orders or {}).get("product_po_cost", {})
    delta = policy["flooring_cost"]["flag_delta_per_sqft_cents"] / 100

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

        # flooring cost rates: PM vs PO (front desk) vs LS sale line
        if ls:
            po_lines = {}
            for po in (orders.get(num) or {}).get("purchase_orders", []):
                for l in po["lines"]:
                    po_lines[l["product_id"]] = (l["unit_cost"], po["reference"], "project PO")
            for fl in ls["flooring_lines"]:
                pid_prod = fl["product_id"]
                po = po_lines.get(pid_prod)
                if not po and pid_prod in product_po:
                    q = product_po[pid_prod]
                    po = (q["unit_cost"], q["po_reference"], "latest PO for this product (not project-linked)")
                sale_cost = fl["unit_cost"]
                rec = {"sku": fl["sku"], "product": fl["product_name"], "sqft": fl["quantity"],
                       "ls_sale_cost_rate": sale_cost, "po_cost_rate": po[0] if po else None,
                       "po_reference": po[1] if po else None}
                if po and abs(po[0] - sale_cost) > delta:
                    conf, mode = "Medium", "suggest"
                    reason = (f"{fl['sku']}: PO {po[0]:.2f}/sqft ({po[2]}, {po[1]}) vs LS sale-line "
                              f"{sale_cost:.2f}/sqft — more than ${delta:.2f}/sqft apart; front desk "
                              f"(PO) is the interim number, check the supplier invoice")
                elif not po:
                    conf, mode = "Low", "suggest"
                    reason = (f"{fl['sku']}: no purchase order found — only the LS sale-line cost "
                              f"{sale_cost:.2f}/sqft (an average-cost snapshot); front desk rate missing")
                else:
                    continue    # sources agree: pass silently (amendment §4)
                actions.append(mk("flooring_cost_rate", project["url"], mode, rec, conf, reason, pp))

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
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    s = pr.SETTINGS
    out = plan(pr.load_json(args.snapshot), pr.load_json(s / "notion-finance.json"),
               pr.load_json(s / "payout-policy.json"),
               ls_sales=pr.load_json(args.ls_sales) if args.ls_sales else None,
               ls_orders=pr.load_json(args.ls_orders) if args.ls_orders else None)
    path = args.out or pr.REPO_ROOT / "plans" / datetime.now(pr.TZ).date().isoformat() / "costs-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(out['actions'])} actions {out['counts']} (write_mode {out['write_mode']}) "
          f"-> {path.relative_to(pr.REPO_ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
