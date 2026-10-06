#!/usr/bin/env python3
"""Tests for the payout flow: Lightspeed sales/PO pulls and the payout run.

Stdlib unittest, no network.  python3 -m unittest tests.test_payouts -v

The release-rule truth table is the point of this file. A wrong rule here does not
fail loudly — it pays a contractor early, holds one forever, or pays commission
twice — so every rule Albert set on 2026-10-05 has a case.
"""

import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import ls_orders_pull as lop  # noqa: E402
import ls_sales_pull as lsp  # noqa: E402
import payout_run as pr  # noqa: E402

SETTINGS = REPO_ROOT / "platform-settings"
POLICY = json.loads((SETTINGS / "payout-policy.json").read_text())
REG = json.loads((SETTINGS / "notion-finance.json").read_text())
COMM = json.loads((SETTINGS / "commissions.json").read_text())
AS_OF = date(2026, 10, 1)


class TestPPRegex(unittest.TestCase):
    rx = lsp.pp_regex(POLICY)

    def test_accepted_shapes(self):
        for note, want in [("@pack for <name> PP-463", "463"), ("@pack <name> PP463", "463"),
                           ("@pack @PP463", "463"), ("Project <name> <name> PP-411", "411"),
                           ("PP-451 <name>\n12345", "451"), ("PP439 <name>", "439")]:
            self.assertEqual(lsp.parse_pp(note, self.rx), want, note)

    def test_four_digits_is_never_read_as_three(self):
        self.assertEqual(lsp.parse_pp("@pack for <name> PP-1000", self.rx), "1000")

    def test_rejected_shapes(self):
        for note in ["108", "@pack 108", "<name> - <name>pp 6242 (450sf)", "PP-46", "pp-463", ""]:
            self.assertIsNone(lsp.parse_pp(note, self.rx), note)

    def test_two_numbers_is_ambiguous(self):
        self.assertIsNone(lsp.parse_pp("PP-411 and PP-416", self.rx))
        self.assertEqual(lsp.pp_candidates("PP-411 and PP-416", self.rx), ["411", "416"])


def sale(sid, receipt, note, lines, state="closed", total=None):
    return {"id": sid, "invoice_number": receipt, "note": note, "state": state,
            "status": "CLOSED" if state == "closed" else "SAVED", "sale_date": "2026-09-10T10:00:00Z",
            "total_price": total if total is not None else sum(l["total_price"] for l in lines),
            "total_tax": 0, "line_items": lines}


def line(pid, qty, price, cost, status="CONFIRMED"):
    return {"id": f"l-{pid}-{qty}", "product_id": pid, "quantity": qty, "unit_price": price,
            "unit_cost": cost, "total_price": round(qty * price, 2), "total_cost": round(qty * cost, 2),
            "total_tax": round(qty * price * 0.13, 2), "status": status}


PRODUCTS = {
    "floor": {"sku": "VID-1", "name": "Oak", "category": "ENGINEERED HARDWOOD"},
    "mould": {"sku": "M-1", "name": "Reducer", "category": "MOULDING"},
    "dep": {"sku": "DEPOSIT", "name": "SAMPLE DEPOSIT", "category": None},
    "bucket": {"sku": "BKT", "name": "bucket", "category": "OTHER"},
}


class TestSalesPull(unittest.TestCase):
    def test_duplicate_receipts_are_two_sales_keyed_on_id(self):
        out = lsp.build([sale("a", "L-40372", "@pack PP-439", [line("floor", 100, 4, 3)]),
                         sale("b", "L-40372", "@pack PP-450", [line("floor", 50, 4, 3)])],
                        PRODUCTS, POLICY, {})
        self.assertEqual(set(out["projects"]), {"439", "450"})

    def test_voided_lines_and_sales_are_dropped(self):
        out = lsp.build([sale("a", "R-1", "@pack PP-463",
                              [line("floor", 100, 4, 3), line("mould", 1, 50, 30, status="VOIDED")]),
                         sale("v", "R-2", "@pack PP-463", [line("floor", 9, 9, 9)], state="voided")],
                        PRODUCTS, POLICY, {})
        p = out["projects"]["463"]
        self.assertEqual(p["sale_ids"], ["a"])
        self.assertEqual(p["totals_by_class"]["nfm"]["revenue_pretax"], 0)
        self.assertEqual(out["counts"]["voided_skipped"], 1)

    def test_split_by_class_reproduces_r35833(self):
        # PP-463 / R-35833: flooring 880 sqft @ 4.39 / 3.39 + mouldings
        out = lsp.build([sale("x", "R-35833", "@pack for <name> PP-463",
                              [line("floor", 880, 4.39, 3.39), line("mould", 1, 515.64, 228.30)],
                              state="parked")], PRODUCTS, POLICY, {})
        t = out["projects"]["463"]["totals_by_class"]
        self.assertAlmostEqual(t["flooring"]["revenue_pretax"] + t["nfm"]["revenue_pretax"], 4378.84, places=2)
        self.assertAlmostEqual(t["flooring"]["cost"] + t["nfm"]["cost"], 3211.50, places=2)
        self.assertIn("provisional_open_sale", out["projects"]["463"]["flags"])

    def test_zero_cost_nonstock_is_expected_stocked_is_flagged(self):
        out = lsp.build([sale("a", "R-1", "@pack PP-470",
                              [line("dep", 1, 100, 0), line("bucket", 2, 5, 0)])], PRODUCTS, POLICY, {})
        lines = out["projects"]["470"]["sales"][0]["lines"]
        by = {l["sku"]: l for l in lines}
        self.assertEqual(by["DEPOSIT"]["zero_cost"], "expected_nonstock")
        self.assertIn("zero_cost_line", by["BKT"]["flags"])

    def test_zero_revenue_sale_is_flagged(self):
        out = lsp.build([sale("a", "R-35375", "@pack PP-416", [line("floor", 100, 4, 3)], total=0)],
                        PRODUCTS, POLICY, {})
        self.assertIn("zero_revenue_sale", out["projects"]["416"]["flags"])

    def test_pack_without_pp_is_reported_not_filed(self):
        out = lsp.build([sale("a", "R-1", "@Pack For <name>", [line("floor", 1, 1, 1)])], PRODUCTS, POLICY, {})
        self.assertEqual(out["projects"], {})
        self.assertEqual(len(out["untagged_pack_sales"]), 1)

    def test_no_note_text_or_customer_reaches_the_output(self):
        s = sale("a", "R-1", "@pack for Secretname PP-463", [line("floor", 1, 1, 1)])
        s["customer_id"] = "cust-123"
        dumped = json.dumps(lsp.build([s], PRODUCTS, POLICY, {}))
        self.assertNotIn("Secretname", dumped)
        self.assertNotIn("cust-123", dumped)


class TestOrdersPull(unittest.TestCase):
    def test_pp_from_name_and_latest_product_cost(self):
        pos = [{"id": "c1", "type": "SUPPLIER", "name": "Project <name> PP-411", "reference": "PO-8086",
                "status": "RECEIVED", "consignment_date": "2026-07-01", "supplier_id": "s"},
               {"id": "c2", "type": "SUPPLIER", "name": "12 boxes for Secretname", "reference": "PO-8200",
                "status": "SENT", "consignment_date": "2026-09-01", "supplier_id": "s"}]
        lines = {"c1": [{"product_id": "floor", "count": "100.5", "cost": "3.10", "received": "100.5"}],
                 "c2": [{"product_id": "floor", "count": "50", "cost": "3.39", "received": "0"}]}
        out = lop.build(pos, lines, {"s": "VIDAR"}, POLICY, {})
        self.assertEqual(list(out["projects"]), ["411"])
        self.assertEqual(out["product_po_cost"]["floor"]["unit_cost"], 3.39)   # latest PO wins
        self.assertNotIn("Secretname", json.dumps(out))

    def test_client_filters_supplier_type_itself(self):
        import lightspeed_client as lsc
        cl = lsc.LightspeedClient(domain_prefix="x", token="y", config=lsc.load_config())
        cl.min_interval = 0
        pages = iter([{"data": [{"id": "1", "type": "SUPPLIER", "version": 1},
                                {"id": "2", "type": "STOCKTAKE", "version": 2}],
                       "version": {"min": 1, "max": 2}}])
        cl.get = lambda path, params=None: next(pages)
        self.assertEqual([r["id"] for r in cl.supplier_consignments()], ["1"])


# -- payout run ------------------------------------------------------------------

def P(n):
    return f"https://www.notion.so/{n:032x}"


def snapshot(**over):
    """Albert's PP-461 shape: Roy, labor 2010, disposal, Pourya sales+PM."""
    snap = {
        "team": [{"url": P(1), "Name": "Roy", "Role": ["Subcontractor"], "Pay Method": "Cash"},
                 {"url": P(2), "Name": "John - APS Disposal", "Role": ["Bin Disposal"], "Pay Method": "e-Transfer"},
                 {"url": P(3), "Name": "Pourya Lalee", "Role": ["Sales", "Project Manager"], "Pay Method": "Cash"},
                 {"url": P(4), "Name": "None"}],
        "projects": [{"url": P(100), "ID": 461, "Value Approx": 28080, "Project Type": "Both",
                      "Sales Person": "Pourya Lalee", "Project Manager": "Pourya Lalee",
                      "Contractor": [P(1)], "Project End Date": "2026-09-14"}],
        "costs": [{"url": P(200), "Name": "Diego (Labor)", "Category": "Labor", "Cost": 2010,
                   "Assigned To": [P(1)], "Project": [P(100)]},
                  {"url": P(201), "Name": "Diego (Disposal)", "Category": "Disposal", "Cost": 279.34,
                   "Assigned To": [P(2)], "Project": [P(100)]},
                  {"url": P(202), "Name": "Diego (NFM)", "Category": "Materials (Non-Flooring)", "Cost": None,
                   "Assigned To": [P(4)], "Project": [P(100)]}],
        "financials": [{"url": P(300), "Project": [P(100)], "Costs Complete": "__YES__",
                        "Commission Amount": 812.5, "Commission Paid Out": "__NO__"}],
        "work_orders": [],
        "payments": [{"url": P(400), "Amount": 28080, "Projects": [P(100)]}],
        "flooring_lines": [],
    }
    for k, v in over.items():
        snap[k] = v
    return snap


def run(snap, notices=None):
    return pr.build_run(snap, REG, POLICY, COMM, "2026-09", AS_OF, notices=notices)


def payee(r, name):
    return next((p for p in r["payees"] if p["payee"].startswith(name)), None)


class TestPayoutRun(unittest.TestCase):
    def test_clean_project_pays_labor_disposal_and_one_commission(self):
        r = run(snapshot())
        self.assertEqual(payee(r, "Roy")["total"], 2010)
        self.assertEqual(payee(r, "John")["total"], 279.34)
        pourya = payee(r, "Pourya")
        self.assertEqual(len(pourya["lines"]), 1, "both roles -> one commission line")
        self.assertEqual(pourya["lines"][0]["amount"], 812.5)

    def test_open_work_order_holds_labor_and_commission_not_disposal(self):
        r = run(snapshot(work_orders=[{"url": P(500), "Generated Reference": "WO-Diego",
                                       "Status": "Notified Contractor", "Project": [P(100)]}]))
        self.assertIsNone(payee(r, "Roy"))
        self.assertEqual(r["held"]["labor"][0]["days_held"], 17)
        self.assertEqual(r["held"]["commission"][0]["open_work_orders"], ["WO-Diego"])
        self.assertEqual(payee(r, "John")["total"], 279.34)

    def test_customer_balance_never_holds_labor_or_commission(self):
        r = run(snapshot(payments=[{"url": P(400), "Amount": 1000, "Projects": [P(100)]}]))
        self.assertEqual(payee(r, "Roy")["total"], 2010)
        self.assertIsNotNone(payee(r, "Pourya"))
        self.assertEqual(r["ar_flags"][0]["balance_owing"], 27080)

    def test_override_releases_commission_with_open_wo(self):
        snap = snapshot(work_orders=[{"url": P(500), "Generated Reference": "WO-1", "Status": "Reviewing",
                                      "Project": [P(100)]}])
        snap["financials"][0]["Commission Release Override"] = "__YES__"
        snap["financials"][0]["Override Reason"] = "Stephen"
        r = run(snap)
        self.assertIn("override", payee(r, "Pourya")["lines"][0]["flags"][0])

    def test_costs_incomplete_blocks_commission(self):
        snap = snapshot()
        snap["financials"][0]["Costs Complete"] = "__NO__"
        r = run(snap)
        self.assertIsNone(payee(r, "Pourya"))
        self.assertTrue(any("Costs Complete" in b["issue"] for b in r["blockers"]))

    def test_paid_out_without_a_date_is_still_paid(self):
        snap = snapshot()
        snap["financials"][0]["Commission Paid Out"] = "__YES__"   # March bulk-import shape
        self.assertIsNone(payee(run(snap), "Pourya"))

    def test_paid_rows_and_paid_commission_are_skipped(self):
        snap = snapshot()
        snap["costs"][0]["Paid Out Date (2/3)"] = "2026-09-09"
        snap["financials"][0].update({"Commission Paid Out": "__YES__", "Commission Paid Date": "2026-09-09"})
        r = run(snap)
        self.assertIsNone(payee(r, "Roy"))
        self.assertIsNone(payee(r, "Pourya"))

    def test_installer_back_charge_deducts_only_when_charge_to_installer(self):
        wo = {"url": P(500), "Generated Reference": "WO-1", "Status": "Done", "Project": [P(100)],
              "Budget Expense ($$ Payout)": 300}
        self.assertEqual(payee(run(snapshot(work_orders=[wo])), "Roy")["total"], 2010)
        r = run(snapshot(work_orders=[{**wo, "Charge To": "Installer"}]))
        self.assertEqual(payee(r, "Roy")["total"], 1710)

    def test_missing_cost_and_placeholder_payee_are_blockers_not_payments(self):
        snap = snapshot()
        snap["costs"][1]["Cost"] = None
        snap["costs"][0]["Assigned To"] = [P(4)]
        r = run(snap)
        issues = {b["issue"] for b in r["blockers"]}
        self.assertIn("cost missing", issues)
        self.assertIn("no real payee in Assigned To", issues)
        self.assertNotIn("NFM", json.dumps(r["blockers"]))   # NFM is not a payable

    def test_other_rows_without_a_payee_are_info_not_blockers(self):
        snap = snapshot()
        snap["costs"].append({"url": P(203), "Category": "Other", "Cost": -4177.16, "Project": [P(100)]})
        snap["costs"].append({"url": P(204), "Category": "Delivery", "Cost": 150, "Project": [P(100)]})
        r = run(snap)
        self.assertEqual([u["amount"] for u in r["unassigned_other"]], [-4177.16])
        self.assertEqual([b["category"] for b in r["blockers"]], ["Delivery"])

    def test_work_order_payment_rows_skip_the_band(self):
        projects, costs = [], []
        for i in range(30):
            projects.append({"url": P(1000 + i), "ID": 300 + i, "Value Approx": 10000, "Project Type": "Both"})
            costs.append({"url": P(2000 + i), "Category": "Labor", "Cost": 3000, "Assigned To": [P(1)],
                          "Project": [P(1000 + i)], "Paid Out Date (2/3)": "2026-08-01"})
        snap = snapshot()
        snap["projects"] += projects
        snap["costs"] += costs
        snap["costs"].append({"url": P(205), "Name": "Work Order Payment: fix", "Category": "Labor",
                              "Cost": 100, "Assigned To": [P(1)], "Project": [P(100)]})
        lines = payee(run(snap), "Roy")["lines"]
        wo = next(l for l in lines if l["title"].startswith("Work Order Payment"))
        self.assertEqual(wo["flags"], [])

    def test_projects_before_september_are_left_out_and_counted(self):
        snap = snapshot()
        snap["projects"][0]["Project End Date"] = "2026-08-31"
        r = run(snap)
        self.assertEqual(r["payees"], [])
        self.assertEqual(r["summary"]["out_of_scope"], {"cost_rows": 3, "commission_rows": 1, "projects": 1})
        self.assertIn("PP-461", r["out_of_scope_projects"])

    def test_project_with_no_end_date_is_out_of_scope(self):
        snap = snapshot()
        del snap["projects"][0]["Project End Date"]
        self.assertEqual(run(snap)["payees"], [])

    def test_september_first_is_in_scope(self):
        snap = snapshot()
        snap["projects"][0]["Project End Date"] = "2026-09-01"
        self.assertIsNotNone(payee(run(snap), "Roy"))

    def test_labor_check_layers(self):
        snap = snapshot()
        snap["costs"][0].update({"Quoted Cost": 1900, "Cost Source": "Sub Invoice"})
        flags = payee(run(snap), "Roy")["lines"][0]["flags"]
        self.assertTrue(any("sub invoice" in f for f in flags))
        snap["costs"][0].update({"Cost Source": "Our Cost", "Change Order Reason": "extra stairs"})
        self.assertEqual([f for f in payee(run(snap), "Roy")["lines"][0]["flags"] if "quoted" in f], [])
        snap["costs"][0]["Change Order Reason"] = None
        self.assertTrue(any("no change-order reason" in f
                            for f in payee(run(snap), "Roy")["lines"][0]["flags"]))

    def test_band_falls_back_to_overall_when_a_type_is_thin(self):
        projects, costs = [], []
        for i in range(30):
            projects.append({"url": P(1000 + i), "ID": 300 + i, "Value Approx": 10000,
                             "Project Type": "Flooring"})
            costs.append({"url": P(2000 + i), "Category": "Labor", "Cost": 2000 + i * 10,
                          "Assigned To": [P(1)], "Project": [P(1000 + i)],
                          "Paid Out Date (2/3)": "2026-08-01"})
        snap = snapshot()
        snap["projects"] += projects
        snap["costs"] += costs
        r = run(snap)
        self.assertGreaterEqual(r["labor_bands"]["_overall"]["n"], 30)
        flags = payee(r, "Roy")["lines"][0]["flags"]
        self.assertTrue(any("_overall" in f and "outside" in f for f in flags), flags)

    def test_two_claimants_without_a_split_rule_hold_the_pool(self):
        comm = json.loads(json.dumps(COMM))
        comm["claimants"].append({"person": "Amir", "titan_team_name_contains": "Amir",
                                  "eligible_when_role_any": ["project_manager"], "share_of_pool": 1.0})
        snap = snapshot()
        snap["projects"][0]["Project Manager"] = "Amir Zare"
        r = pr.build_run(snap, REG, POLICY, comm, "2026-09", AS_OF)
        self.assertEqual(r["held"]["commission"][0]["reason"], "split undecided")

    def test_unreadable_commission_amount_is_flagged_not_guessed(self):
        snap = snapshot()
        del snap["financials"][0]["Commission Amount"]
        line = payee(run(snap), "Pourya")["lines"][0]
        self.assertIsNone(line["amount"])
        self.assertTrue(line["flags"])

    def test_bank_cross_check_never_marks_paid(self):
        r = run(snapshot(), notices=[{"date": "2026-09-30", "recipient": "ROY CONTRACTING",
                                      "amount": 2010.0, "reference": "C1A"}])
        roy = payee(r, "Roy")
        self.assertTrue(roy["bank_cross_check"][0]["matches_total"])
        self.assertNotIn("paid", json.dumps(roy["lines"]).lower().replace("unpaid", ""))

    def test_render_mentions_every_section(self):
        snap = snapshot(work_orders=[{"url": P(500), "Generated Reference": "WO-1", "Status": "Reviewing",
                                      "Project": [P(100)]}],
                        payments=[{"url": P(400), "Amount": 1, "Projects": [P(100)]}])
        md = pr.render_md(run(snap))
        for heading in ("Payout Run — 2026-09", "Held — carried from prior runs",
                        "Held — waiting on WO", "AR — for office admin"):
            self.assertIn(heading, md)


class TestRegistries(unittest.TestCase):
    def test_write_modes_start_safe(self):
        wm = POLICY["write_mode"]
        self.assertEqual(wm["lightspeed_create_pack_sale"], "off")
        self.assertEqual(wm["lightspeed_create_purchase_order"], "off")
        self.assertIn(wm["payout_run"], ("plan_only", "write"))

    def test_bank_never_marks_paid(self):
        self.assertFalse(POLICY["bank_cross_check"]["mark_paid_from_bank"])
        self.assertFalse(POLICY["payments_match"]["auto_link"])

    def test_commission_gate_does_not_require_customer_paid(self):
        self.assertNotIn("customer_paid", json.dumps(COMM["gate"]["requires"]))

    def test_every_to_add_field_has_a_name_and_type(self):
        for tkey, table in REG.items():
            if not isinstance(table, dict):
                continue
            for k, spec in (table.get("to_add") or {}).items():
                self.assertTrue(spec.get("name") and spec.get("type"), f"{tkey}.{k}")


if __name__ == "__main__":
    unittest.main()


# -- payments match + cost sync ---------------------------------------------------

import payments_match as pm  # noqa: E402
import project_costs_sync as pcs  # noqa: E402


def match_snapshot(memo="", sender="", amount=100.0):
    return {"projects": [{"url": P(100), "ID": 450, "Name": "Sabrina Rossi", "Description": "Sabrina | Brampton",
                          "Street Address": "12 Maple Ave", "Contact": "+1 (905) 555-0101",
                          "Value Approx": 7706.26},
                         {"url": P(101), "ID": 417, "Name": "Gustavo G", "Street Address": "9 Oak St",
                          "Value Approx": 22251.80}],
            "payments": [{"url": P(600), "Amount": amount, "Sender's Name": sender, "Message": memo}],
            "costs": [], "financials": [], "work_orders": [], "team": [], "flooring_lines": []}


class TestPaymentsMatch(unittest.TestCase):
    def test_address_in_memo_is_high_and_memo_never_echoed(self):
        s = pm.suggest(match_snapshot(memo="deposit 12 maple ave unit 3"), REG, POLICY)
        self.assertEqual((s[0]["pp"], s[0]["confidence"]), ("PP-450", "High"))
        self.assertNotIn("maple", s[0]["reason"].lower())

    def test_name_and_installment_amount_is_high(self):
        s = pm.suggest(match_snapshot(sender="SABRINA ROSSI", amount=2697.19), REG, POLICY)
        self.assertEqual(s[0]["confidence"], "High")

    def test_name_alone_is_medium_nothing_is_none(self):
        self.assertEqual(pm.suggest(match_snapshot(sender="Rossi family", amount=5), REG, POLICY)[0]["confidence"],
                         "Medium")
        self.assertEqual(pm.suggest(match_snapshot(sender="Someone Else", amount=5), REG, POLICY), [])

    def test_already_linked_payment_is_skipped(self):
        snap = match_snapshot(sender="SABRINA ROSSI")
        snap["payments"][0]["Projects"] = [P(100)]
        self.assertEqual(pm.suggest(snap, REG, POLICY), [])


def sync_snapshot(cost=None, source=None, submitted="Submitted"):
    return {"projects": [{"url": P(100), "ID": 463, "Value Approx": 9000, "Submission Status": submitted,
                          "Project End Date": "2026-09-20",
                          "Project Costs": [P(200), P(201)]}],
            "costs": [{"url": P(200), "Category": "Materials (Non-Flooring)", "Cost": cost,
                       "Cost Source": source, "Project": [P(100)]},
                      {"url": P(201), "Category": "Labor", "Cost": 1500, "Project": [P(100)]}],
            "financials": [{"url": P(300), "Project": [P(100)], "Costs": [P(200)]}],
            "work_orders": [], "payments": [], "team": [], "flooring_lines": []}


LS = {"projects": {"463": {"pp": "PP-463", "sale_ids": ["s1"], "flags": [],
                           "totals_by_class": {"nfm": {"cost": 228.3, "revenue_pretax": 515.64, "tax": 67.03},
                                               "flooring": {"cost": 2983.2, "revenue_pretax": 3863.2, "tax": 0},
                                               "unclassified": {"cost": 0, "revenue_pretax": 0, "tax": 0}},
                           "flooring_lines": [{"product_id": "floor", "sku": "VID-1", "product_name": "Oak",
                                               "quantity": 880, "unit_cost": 3.39}]}}}


class TestCostSync(unittest.TestCase):
    def kinds(self, out, mode=None):
        return {a["kind"] for a in out["actions"] if mode is None or a["mode"] == mode}

    def test_empty_nfm_row_is_written_silently(self):
        out = pcs.plan(sync_snapshot(), REG, POLICY, ls_sales=LS)
        nfm = next(a for a in out["actions"] if a["kind"] == "nfm_cost")
        self.assertEqual(nfm["mode"], "write")
        self.assertEqual(nfm["fields"]["Cost"], 582.67)      # POS total incl. tax, as typed today

    def test_hand_entered_cost_is_never_overwritten(self):
        out = pcs.plan(sync_snapshot(cost=250, source="Manual"), REG, POLICY, ls_sales=LS)
        nfm = next(a for a in out["actions"] if a["kind"] == "nfm_cost")
        self.assertEqual(nfm["mode"], "suggest")
        self.assertNotIn("Cost", nfm["fields"])

    def test_agreeing_value_produces_no_action(self):
        out = pcs.plan(sync_snapshot(cost=582.67, source="Lightspeed"), REG, POLICY, ls_sales=LS)
        self.assertNotIn("nfm_cost", self.kinds(out))

    def test_po_far_from_sale_cost_is_suggested_per_sqft(self):
        orders = {"projects": {"463": {"purchase_orders": [{"reference": "PO-1", "lines": [
            {"product_id": "floor", "unit_cost": 3.55}]}]}}, "product_po_cost": {}}
        fl = next(a for a in pcs.plan(sync_snapshot(), REG, POLICY, ls_sales=LS, ls_orders=orders)["actions"]
                  if a["kind"] == "flooring_cost_rate")
        self.assertEqual(fl["confidence"], "Medium")
        self.assertIn("apart", fl["reason"])
        orders["projects"]["463"]["purchase_orders"][0]["lines"][0]["unit_cost"] = 3.45   # 6 cents: fine
        fl = next(a for a in pcs.plan(sync_snapshot(), REG, POLICY, ls_sales=LS, ls_orders=orders)["actions"]
                  if a["kind"] == "flooring_cost_rate")
        self.assertEqual(fl["confidence"], "High")

    def test_relations_copied_and_costs_complete_only_when_nothing_missing(self):
        out = pcs.plan(sync_snapshot(cost=582.67, source="Lightspeed"), REG, POLICY, ls_sales=LS)
        self.assertIn("financials_relations", self.kinds(out))
        self.assertIn("costs_complete", self.kinds(out))
        out = pcs.plan(sync_snapshot(cost=None), REG, POLICY, ls_sales=None)
        self.assertNotIn("costs_complete", self.kinds(out))

    def test_out_of_scope_project_gets_no_sync_actions(self):
        snap = sync_snapshot()
        snap["projects"][0]["Project End Date"] = "2026-08-31"
        out = pcs.plan(snap, REG, POLICY, ls_sales=LS)
        self.assertEqual({a["kind"] for a in out["actions"]} - {"payment_project"}, set())

    def test_stamp_paid_only_from_batches_albert_marked_paid(self):
        snap = sync_snapshot()
        snap["payout_batches"] = [{"url": P(700), "Name": "Roy 2026-09", "Paid": "__NO__", "Reference": "x",
                                   "Lines": [P(201)]},
                                  {"url": P(701), "Name": "APS 2026-09", "Paid": "__YES__", "Reference": "C1A",
                                   "Paid Date": "2026-10-02", "Lines": [P(201)]}]
        stamps = [a for a in pcs.plan(snap, REG, POLICY)["actions"] if a["kind"] == "stamp_paid"]
        self.assertEqual(len(stamps), 1)
        self.assertEqual(stamps[0]["fields"]["Paid Reference (3/3)"], "C1A")
