#!/usr/bin/env python3
"""Build the month-end payout run from a Notion finance snapshot. READ ONLY.

Deterministic half of /payout-run (.claude/commands/payout-run.md). The command
takes a read-only snapshot of the finance databases through the Notion MCP and
saves it; this script applies the release rules, checks and flags and writes the
run. It never talks to Notion, Lightspeed or a bank, and it never marks anything
paid — Albert's `Approved` and `Paid` ticks on the Payout Batches rows are the only
approval (Decision 4, 15).

    python3 scripts/payout_run.py --snapshot ingest/2026-10-01/notion-finance.json \
        --run 2026-09 [--ls-sales ingest/2026-10-01/ls-sales.json] \
        [--bank ingest/2026-10-01/bank-notices.json] [--as-of 2026-10-01]

Writes plans/<as-of>/payout-run-<run>.json (contracts/payout-run-schema.md) and a
readable plans/<as-of>/payout-run-<run>.md, the text the command puts on the
"Payout Run — <run>" Notion page.

Rules (data in platform-settings/payout-policy.json and commissions.json; reasons
in methods/payouts.md):
  * labor is held while ANY work order on its project is open; customer balance
    never holds contractor pay (Decision 2);
  * a closed work order marked `Charge to = Installer` deducts its payout from that
    project's installer (Q5; default Titan = no deduction);
  * commission is releasable when Costs Complete and no open work order, or
    Albert's override; customer still owing is an AR flag, not a hold (Decision 7);
  * one commission line per project per eligible claimant — Pourya on a project
    where he is both Sales and PM gets ONE line (amendment §10);
  * labor check, layered (amendment §5): sub invoice vs quote → standard rate
    passes → manual rate override flags → band backstop.
"""

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS = REPO_ROOT / "platform-settings"
TZ = ZoneInfo("America/Toronto")
CONTRACT = "payout-run-1"

TABLES = {  # snapshot key -> registry table key
    "projects": "titan_projects",
    "costs": "project_costs",
    "financials": "project_financials",
    "work_orders": "qa_work_orders",
    "payments": "master_payments_log",
    "team": "titan_team",
    "flooring_lines": "flooring_line_items",
}


def load_json(path):
    return json.loads(Path(path).read_text())


# -- snapshot normalisation -----------------------------------------------------

def field_map(reg_table):
    """Notion property name -> logical key, for live and to_add fields."""
    m = {}
    for key, name in (reg_table.get("properties") or {}).items():
        if not key.startswith("_") and isinstance(name, str):
            m[name] = key
    for key, spec in (reg_table.get("to_add") or {}).items():
        if isinstance(spec, dict) and spec.get("name"):
            m[spec["name"]] = key
    return m


def coerce(value):
    """Notion MCP values -> plain Python: '__YES__' -> True, JSON arrays -> lists."""
    if isinstance(value, str):
        s = value.strip()
        if s in ("__YES__", "__NO__"):
            return s == "__YES__"
        if s.startswith("[") and s.endswith("]"):
            try:
                return json.loads(s)
            except ValueError:
                return value
        if s == "":
            return None
    return value


def normalize_row(raw, fmap):
    row = {"url": raw.get("url") or raw.get("id")}
    for name, value in raw.items():
        base = name
        m = re.match(r"^date:(.+):(start|end)$", name)
        if m:
            if m.group(2) == "end":
                continue
            base = m.group(1)
        key = fmap.get(base)
        if key:
            row[key] = coerce(value)
    return row


def normalize_snapshot(snap, reg):
    out = {}
    for skey, tkey in TABLES.items():
        fmap = field_map(reg[tkey])
        out[skey] = [normalize_row(r, fmap) for r in (snap.get(skey) or [])]
    return out


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def page_id(url):
    """Notion page url or id -> bare 32-hex id, for relation joins."""
    if not url:
        return None
    s = str(url).replace("-", "")
    m = re.search(r"([0-9a-f]{32})", s)
    return m.group(1) if m else s


def money(v):
    try:
        return round(float(v), 2) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_date(v):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def truthy(v):
    return v is True or (isinstance(v, str) and v.lower() in ("true", "yes", "__yes__"))


# -- rules ----------------------------------------------------------------------

def build_index(n):
    idx = {k: {page_id(r["url"]): r for r in rows} for k, rows in n.items()}
    wo_by_project = {}
    for wo in n["work_orders"]:
        for p in as_list(wo.get("project")):
            wo_by_project.setdefault(page_id(p), []).append(wo)
    pay_by_project = {}
    for pay in n["payments"]:
        for p in as_list(pay.get("projects")):
            pay_by_project.setdefault(page_id(p), []).append(pay)
    fin_by_project = {}
    for f in n["financials"]:
        for p in as_list(f.get("project")):
            fin_by_project.setdefault(page_id(p), []).append(f)
    return idx, wo_by_project, pay_by_project, fin_by_project


def open_work_orders(project_pid, wo_by_project, closed):
    return [wo for wo in wo_by_project.get(project_pid, [])
            if (wo.get("status") or "") not in closed]


def pp_label(project):
    v = project.get("pp_id") if project else None
    if v is None:
        return None
    s = str(v)
    return s if s.upper().startswith("PP-") else f"PP-{s}"


def is_unpaid(cost):
    return not cost.get("paid_out_date") and not (cost.get("paid_reference") or "").strip()


def labor_band(costs, idx, policy, as_of):
    """Labor share of project value per project type, from paid labor rows."""
    band_cfg = policy["labor_check"]["band"]
    lookback = band_cfg["lookback_months"] * 31
    groups = {}
    for c in costs:
        if c.get("category") != "Labor" or is_unpaid(c):
            continue
        paid = parse_date(c.get("paid_out_date"))
        if paid and (as_of - paid).days > lookback:
            continue
        cost = money(c.get("cost"))
        proj = idx["projects"].get(page_id((as_list(c.get("project")) or [None])[0]))
        value = money(proj.get("value")) if proj else None
        if not cost or not value:
            continue
        share = cost / value
        groups.setdefault(proj.get("project_type") or "_none", []).append(share)
        groups.setdefault("_overall", []).append(share)

    def pct(vals, q):
        vals = sorted(vals)
        if not vals:
            return None
        k = (len(vals) - 1) * q / 100
        lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
        return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 4)

    out = {}
    for g, vals in groups.items():
        out[g] = {"n": len(vals), "low": pct(vals, band_cfg["low_percentile"]),
                  "high": pct(vals, band_cfg["high_percentile"])}
    return out


def band_for(project_type, bands, policy):
    min_n = policy["labor_check"]["band"]["min_samples_per_group"]
    b = bands.get(project_type or "_none")
    if b and b["n"] >= min_n:
        return b, project_type or "_none"
    return bands.get("_overall"), "_overall"


def labor_checks(cost, project, bands, policy):
    """Layered labor check (amendment §5). Returns a list of flag strings."""
    flags = []
    amount = money(cost.get("cost"))
    quoted = money(cost.get("quoted_cost"))
    source = cost.get("cost_source")
    if source == "Sub invoice" and quoted is not None:
        tol = policy["labor_check"]["invoice_vs_quote_tolerance_cents"] / 100
        if amount is not None and abs(amount - quoted) > tol:
            flags.append(f"sub invoice {amount:.2f} ≠ quote {quoted:.2f}")
    elif truthy(cost.get("rate_overridden")):
        flags.append("labor rate manually overridden on the quote")
    if quoted is not None and amount is not None and abs(amount - quoted) > 0.005 \
            and not (cost.get("change_order_reason") or "").strip() and source != "Sub invoice":
        flags.append(f"labor {amount:.2f} ≠ quoted {quoted:.2f} with no change-order reason")
    value = money(project.get("value")) if project else None
    if amount and value:
        b, group = band_for(project.get("project_type"), bands, policy)
        if b and b["low"] is not None:
            share = amount / value
            if share < b["low"] or share > b["high"]:
                flags.append(f"labor is {share:.0%} of value, outside the "
                             f"{b['low']:.0%}–{b['high']:.0%} band ({group}, n={b['n']})")
    return flags


def eligible_claimants(project, commissions):
    """Claimants whose person appears in an eligible role on the project."""
    roles = {
        "sales_person": " ".join(str(x) for x in as_list(project.get("sales_person"))),
        "project_manager": " ".join(str(x) for x in as_list(project.get("project_manager"))),
    }
    out = []
    for c in commissions["claimants"]:
        needle = c["titan_team_name_contains"].lower()
        hit = [r for r in c["eligible_when_role_any"]
               if needle in roles.get(r, "").lower() or c.get("notion_person_id", "#") in roles.get(r, "")]
        if hit:
            out.append({**c, "roles": hit})
    return out


def balance_owing(project, pay_by_project, pid):
    readable = money(project.get("balance_owing"))
    if readable is not None:
        return readable
    value = money(project.get("value"))
    if value is None:
        return None
    paid = sum(money(p.get("amount")) or 0 for p in pay_by_project.get(pid, []))
    return round(value - paid, 2)


def bank_match(payee_name, total, notices):
    """Outgoing Interac notices whose recipient looks like the payee (cross-check only)."""
    if not notices or not payee_name:
        return []
    tokens = [t for t in re.split(r"[^a-z0-9]+", payee_name.lower()) if len(t) > 2]
    hits = []
    for n in notices:
        rec = (n.get("recipient") or "").lower()
        if tokens and any(t in rec for t in tokens):
            hits.append({"date": n.get("date"), "amount": n.get("amount"),
                         "reference": n.get("reference"),
                         "matches_total": money(n.get("amount")) == round(total, 2)})
    return hits


def build_run(snap, reg, policy, commissions, run_label, as_of, ls_sales=None, notices=None):
    n = normalize_snapshot(snap, reg)
    idx, wo_by_project, pay_by_project, fin_by_project = build_index(n)
    closed = set(reg["qa_work_orders"]["closed_statuses"])
    placeholders = {p.lower() for p in reg["titan_team"]["placeholder_names"]}
    cats = reg["project_costs"]["categories"]
    bands = labor_band(n["costs"], idx, policy, as_of)

    payees, held_labor, held_commission, blockers, ar_flags = {}, [], [], [], []

    def payee_entry(team_pid):
        t = idx["team"].get(team_pid) or {}
        return payees.setdefault(team_pid, {
            "payee": t.get("title") or "(unknown payee)", "payee_url": t.get("url"),
            "pay_method": t.get("pay_method"), "lines": [], "flags": []})

    # 1. cost rows: labor, disposal, delivery, other
    for c in n["costs"]:
        if not is_unpaid(c):
            continue
        ppid = page_id((as_list(c.get("project")) or [None])[0])
        project = idx["projects"].get(ppid) or {}
        pp = pp_label(project)
        amount = money(c.get("cost"))
        category = c.get("category")
        assigned = [page_id(a) for a in as_list(c.get("assigned_to"))]
        team = idx["team"].get(assigned[0]) if assigned else None
        line = {"kind": (category or "uncategorised").lower(), "pp": pp, "cost_url": c.get("url"),
                "title": c.get("title"), "amount": amount, "cost_source": c.get("cost_source"),
                "flags": []}
        if amount is None or amount == 0:
            if category != cats["nfm"]:
                blockers.append({"pp": pp, "cost_url": c.get("url"), "category": category,
                                 "issue": "cost missing"})
            continue
        if category == cats["nfm"]:
            continue                     # NFM is Titan's own stock, not a payee line
        if not team or (team.get("title") or "").lower() in placeholders:
            blockers.append({"pp": pp, "cost_url": c.get("url"), "category": category,
                             "issue": "no real payee in Assigned To"})
            continue
        if category == cats["labor"]:
            opens = open_work_orders(ppid, wo_by_project, closed)
            if opens and policy["labor_release"]["hold_while_work_order_open"]:
                since = parse_date(project.get("project_end_date")) or parse_date(c.get("created"))
                held_labor.append({**line, "payee": team.get("title"),
                                   "open_work_orders": [w.get("title") for w in opens],
                                   "days_held": (as_of - since).days if since else None})
                continue
            line["flags"] += labor_checks(c, project, bands, policy)
        if c.get("cost_source") == "AP invoice (auto)":
            line["flags"].append("disposal cost auto-extracted from an AP invoice — confirm")
        payee_entry(assigned[0])["lines"].append(line)

    # 2. work-order back-charges (Charge to = Installer, WO closed)
    if policy["labor_release"]["work_order_charge_to_installer_deducts"]:
        for wo in n["work_orders"]:
            if wo.get("charge_to") != "Installer" or (wo.get("status") or "") not in closed \
                    or (wo.get("status") == "Dropped"):
                continue
            amount = money(wo.get("budget_expense"))
            ppid = page_id((as_list(wo.get("project")) or [None])[0])
            project = idx["projects"].get(ppid) or {}
            installers = [page_id(x) for x in as_list(project.get("contractor"))]
            if not amount or not installers:
                continue
            if len(installers) > 1:
                blockers.append({"pp": pp_label(project), "issue":
                                 f"WO {wo.get('title')} charged to installer but the project has "
                                 f"{len(installers)} contractors — pick one"})
                continue
            payee_entry(installers[0])["lines"].append({
                "kind": "wo_deduction", "pp": pp_label(project), "wo": wo.get("title"),
                "amount": -amount, "flags": ["back-charge — confirm it was not deducted before"]})

    # 3. commission
    for f in n["financials"]:
        if truthy(f.get("commission_paid_out")) and f.get("commission_paid_date"):
            continue
        ppid = page_id((as_list(f.get("project")) or [None])[0])
        project = idx["projects"].get(ppid)
        if not project:
            continue
        pp = pp_label(project)
        claimants = eligible_claimants(project, commissions)
        if not claimants:
            continue
        opens = open_work_orders(ppid, wo_by_project, closed)
        override = truthy(f.get("commission_release_override"))
        bal = balance_owing(project, pay_by_project, ppid)
        if bal is not None and bal > 0.5:
            ar_flags.append({"pp": pp, "balance_owing": bal,
                             "note": "AR — office admin's to collect; does not hold commission"})
        amount = money(f.get("commission_amount"))
        base = {"kind": "commission", "pp": pp, "financials_url": f.get("url"),
                "amount": amount, "flags": []}
        if amount is None:
            base["flags"].append("commission amount not readable from the snapshot — read it in Notion")
        if not truthy(f.get("costs_complete")):
            blockers.append({"pp": pp, "financials_url": f.get("url"),
                             "issue": "commission waiting on Costs Complete"})
            continue
        if opens and not override:
            held_commission.append({**base, "claimant": ", ".join(c["person"] for c in claimants),
                                    "open_work_orders": [w.get("title") for w in opens]})
            continue
        if override:
            base["flags"].append(f"released by override: {f.get('override_reason') or '(no reason given)'}")
        if len(claimants) > 1 and not commissions.get("split_rule"):
            held_commission.append({**base, "claimant": ", ".join(c["person"] for c in claimants),
                                    "open_work_orders": [], "reason": "split undecided"})
            continue
        c = claimants[0]
        team_pid = next((pid for pid, t in idx["team"].items()
                         if c["titan_team_name_contains"].lower() in (t.get("title") or "").lower()), None)
        line = {**base, "claimant": c["person"], "roles": c["roles"],
                "amount": round(amount * c["share_of_pool"], 2) if amount is not None else None}
        floor = policy["margin_floor"]["min_margin_after_discount"]
        margin = f.get("overall_margin")
        try:
            if margin is not None and float(margin) < floor:
                line["flags"].append(f"margin {float(margin):.0%} is below the {floor:.0%} floor")
        except (TypeError, ValueError):
            pass
        payee_entry(team_pid or f"claimant:{c['person']}")["lines"].append(line)
        if not team_pid:
            payees[f"claimant:{c['person']}"]["payee"] = c["person"]

    # 4. totals, cross-checks
    for p in payees.values():
        p["total"] = round(sum(l["amount"] or 0 for l in p["lines"]), 2)
        p["flagged_lines"] = sum(1 for l in p["lines"] if l["flags"])
        if p["pay_method"] is None:
            p["flags"].append("no Pay method on Titan Team")
        p["bank_cross_check"] = bank_match(p["payee"], p["total"], notices)

    # 5. Lightspeed signals for projects on this run
    ls_flags = []
    if ls_sales:
        on_run = {l["pp"] for p in payees.values() for l in p["lines"] if l.get("pp")}
        for pp in sorted(on_run):
            num = pp.replace("PP-", "")
            proj = ls_sales["projects"].get(num)
            if not proj:
                ls_flags.append({"pp": pp, "flag": "no Lightspeed sale carries this project number"})
            elif proj["flags"]:
                ls_flags.append({"pp": pp, "flag": ", ".join(proj["flags"])})

    payee_list = sorted(payees.values(), key=lambda p: (-p["total"], p["payee"]))
    return {
        "contract": CONTRACT,
        "run": run_label,
        "as_of": as_of.isoformat(),
        "built_at": datetime.now(TZ).isoformat(),
        "write_mode": policy["write_mode"]["payout_run"],
        "summary": {
            "payees": len(payee_list),
            "total": round(sum(p["total"] for p in payee_list), 2),
            "flagged_lines": sum(p["flagged_lines"] for p in payee_list),
            "held_labor": len(held_labor),
            "held_commission": len(held_commission),
            "blockers": len(blockers),
            "ar_flags": len(ar_flags),
        },
        "payees": payee_list,
        "held": {"labor": sorted(held_labor, key=lambda h: -(h["days_held"] or 0)),
                 "commission": held_commission},
        "blockers": blockers,
        "ar_flags": ar_flags,
        "lightspeed_flags": ls_flags,
        "labor_bands": bands,
    }


# -- render ---------------------------------------------------------------------

def fmt(x):
    return "—" if x is None else f"${x:,.2f}"


def render_md(run):
    s = run["summary"]
    out = [f"# Payout Run — {run['run']}", "",
           f"As of {run['as_of']} · {s['payees']} payees · **{fmt(s['total'])}** · "
           f"{s['flagged_lines']} flagged lines · {s['held_labor']} labor held · "
           f"{s['held_commission']} commission held · {s['blockers']} blockers", "",
           "Review the flagged lines, tick **Approved** on each payee's batch, send the money, "
           "then tick **Paid** and type the reference. Nothing is marked paid until you do.", ""]
    for p in run["payees"]:
        out.append(f"## {p['payee']} — {fmt(p['total'])}  ({p['pay_method'] or 'no pay method'})")
        for f in p["flags"]:
            out.append(f"- ⚠ {f}")
        for l in p["lines"]:
            mark = "⚠ " if l["flags"] else ""
            label = l.get("wo") or l.get("title") or l["kind"]
            out.append(f"- {mark}{l['pp'] or '—'} · {l['kind']} · {label} · {fmt(l['amount'])}")
            for f in l["flags"]:
                out.append(f"    - {f}")
        for b in p["bank_cross_check"]:
            out.append(f"- bank: {b['date']} {b['amount']} ref {b['reference']}"
                       f"{' (matches total)' if b['matches_total'] else ''}")
        out.append("")
    if run["held"]["labor"]:
        out += ["## Held — carried from prior runs (labor, open work orders)", ""]
        for h in run["held"]["labor"]:
            out.append(f"- {h['pp']} · {h['payee']} · {fmt(h['amount'])} · "
                       f"{h['days_held'] if h['days_held'] is not None else '?'} days · "
                       f"WO: {', '.join(x or '?' for x in h['open_work_orders'])}")
        out.append("")
    if run["held"]["commission"]:
        out += ["## Held — waiting on WO (commission)", ""]
        for h in run["held"]["commission"]:
            why = h.get("reason") or "WO: " + ", ".join(x or "?" for x in h["open_work_orders"])
            out.append(f"- {h['pp']} · {h['claimant']} · {fmt(h['amount'])} · {why}")
        out.append("")
    if run["blockers"]:
        out += ["## Blockers (nothing paid until fixed)", ""]
        out += [f"- {b.get('pp') or '—'} · {b.get('category') or ''} · {b['issue']}" for b in run["blockers"]]
        out.append("")
    if run["ar_flags"]:
        out += ["## AR — for office admin (does not hold any payout)", ""]
        out += [f"- {a['pp']} owes {fmt(a['balance_owing'])}" for a in run["ar_flags"]]
        out.append("")
    if run["lightspeed_flags"]:
        out += ["## Lightspeed checks", ""]
        out += [f"- {f['pp']}: {f['flag']}" for f in run["lightspeed_flags"]]
        out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", required=True, type=Path)
    ap.add_argument("--run", required=True, help="Run label YYYY-MM (the month being paid)")
    ap.add_argument("--as-of", help="YYYY-MM-DD, default today (Toronto)")
    ap.add_argument("--ls-sales", type=Path)
    ap.add_argument("--bank", type=Path, help="Outgoing Interac notices JSON (cross-check only)")
    ap.add_argument("--out-dir", type=Path)
    args = ap.parse_args(argv)
    if not re.fullmatch(r"\d{4}-\d{2}", args.run):
        ap.error("--run must be YYYY-MM")

    as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(TZ).date()
    run = build_run(
        load_json(args.snapshot), load_json(SETTINGS / "notion-finance.json"),
        load_json(SETTINGS / "payout-policy.json"), load_json(SETTINGS / "commissions.json"),
        args.run, as_of,
        ls_sales=load_json(args.ls_sales) if args.ls_sales else None,
        notices=load_json(args.bank).get("notices") if args.bank else None)
    out_dir = args.out_dir or REPO_ROOT / "plans" / as_of.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"payout-run-{args.run}.json").write_text(json.dumps(run, indent=1, ensure_ascii=False) + "\n")
    (out_dir / f"payout-run-{args.run}.md").write_text(render_md(run) + "\n")
    s = run["summary"]
    print(f"run {args.run}: {s['payees']} payees, {fmt(s['total'])}, {s['flagged_lines']} flagged, "
          f"{s['held_labor']}+{s['held_commission']} held, {s['blockers']} blockers "
          f"-> {(out_dir / f'payout-run-{args.run}.json').relative_to(REPO_ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
