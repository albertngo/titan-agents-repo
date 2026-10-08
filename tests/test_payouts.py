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
import supplier_docs_pull as sd  # noqa: E402

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

    def test_typed_cost_without_a_source_is_hand_entered(self):
        out = pcs.plan(sync_snapshot(cost=250, source=None), REG, POLICY, ls_sales=LS)
        nfm = next(a for a in out["actions"] if a["kind"] == "nfm_cost")
        self.assertEqual(nfm["mode"], "suggest")

    def test_agreeing_value_produces_no_action(self):
        out = pcs.plan(sync_snapshot(cost=582.67, source="Lightspeed"), REG, POLICY, ls_sales=LS)
        self.assertNotIn("nfm_cost", self.kinds(out))

    def test_relations_copied_and_costs_complete_only_when_nothing_missing(self):
        out = pcs.plan(sync_snapshot(cost=582.67, source="Lightspeed"), REG, POLICY, ls_sales=LS)
        self.assertIn("financials_relations", self.kinds(out))
        self.assertIn("costs_complete", self.kinds(out))
        out = pcs.plan(sync_snapshot(cost=None), REG, POLICY, ls_sales=None)
        self.assertNotIn("costs_complete", self.kinds(out))

    def test_parked_sale_on_a_submitted_project_is_final(self):
        ls = json.loads(json.dumps(LS)); ls["projects"]["463"]["flags"] = ["provisional_open_sale"]
        nfm = next(a for a in pcs.plan(sync_snapshot(), REG, POLICY, ls_sales=ls)["actions"] if a["kind"] == "nfm_cost")
        self.assertEqual(nfm["mode"], "write")
        nfm = next(a for a in pcs.plan(sync_snapshot(submitted="Not Submitted"), REG, POLICY, ls_sales=ls)["actions"]
                   if a["kind"] == "nfm_cost")
        self.assertEqual(nfm["mode"], "suggest")

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


# --- supplier documents and the invoice-driven flooring line (Decisions 17-18) ---

EST = """    Estimate details                                      P.O. Number: 8135
    Estimate no.: 103273                                  Sales Rep: XL
    Estimate date: 2026-08-07
#       Product or service                     Description                             Qty               Rate                Amount              Tax
1.      OKMO161C                               6" X 3/4" (161mmX18mm),                  80         $97.8588                  $7,828.70       HST ON
                                               American White Oak, MOON
                                               LIGHT-ABC, 21.32 SF/BOX, T&G,
2.      TMMO                                   T-Molding, MOON LIGHT                     2              $15.00                $30.00      HST ON
                                                                                             Subtotal                                      $7,858.70
        Note to customer                                                                     HST (ON) @ 13% on
        Price includes a $0.20 discount.                                                 Total                                           $8,880.33
"""


def inv(no, boxes, amount):
    return f"""    Invoice details                       P.O. Number: 8135
    Invoice no.: {no}                   Sales Rep: XL
    Terms: C.O.D                          Estimate No.: 103273
    Invoice date: 2026-09-10
#       Product or service     Description                       Qty               Rate                Amount              Tax
1.      OKMO161C               6" X 3/4" (161mmX18mm),            {boxes}         $97.8588                  ${amount}       HST ON
                               American White Oak, MOON
                               LIGHT-ABC, 21.32 SF/BOX, T&G,
                                                                       Subtotal                                      ${amount}
                                                                   Total                                           $0.00
"""


def credit(no, boxes, rate, amount, when="17/09/2026", fee=False):
    return f"""CREDIT TO                                                          CREDIT # {no}
Titan Flooring Inc                                                    DATE {when}
 ACTIVITY        DESCRIPTION                               TAX      QTY     RATE    AMOUNT
 OKMO161C        6" X 3/4" (161mmX18mm), American White    HST        {boxes}   {rate}       {amount}
                 Oak, MOON LIGHT-ABC, 21.32                 ON
                 SF/BOX, T&G, ENG, WB
{"                 with 25 % restocking fee" if fee else ""}
                                                  SUBTOTAL                              {amount}
                                                  HST (ON) @ 13%                         0.00
                                                  TOTAL                                 {amount}
"""


def vidar_docs(credits=()):
    docs = [sd.parse_quickbooks(EST, "confirmation", "Estimate - Sales order 103273 from VIDAR DESIGN FLOORING"),
            sd.parse_quickbooks(inv("104771", 48, "4,697.22"), "invoice"),
            sd.parse_quickbooks(inv("104785", 32, "3,131.48"), "invoice")]
    docs += [sd.parse_quickbooks(c, "credit_memo") for c in credits]
    for d in docs:
        d["supplier"] = "vidar"
    return docs


class TestSupplierDocs(unittest.TestCase):
    def test_estimate_parsed_per_box_to_per_sqft(self):
        d = sd.parse_quickbooks(EST, "confirmation", "Estimate - Sales order 103273 from VIDAR DESIGN FLOORING")
        self.assertEqual((d["doc_no"], d["po_number"], d["date"], d["revision"]), ("103273", "8135", "2026-08-07", "original"))
        floor, trim = d["lines"]
        self.assertEqual((floor["code"], floor["qty"], floor["sqft"], floor["rate_per_sqft"]), ("OKMO161C", 80, 1705.6, 4.59))
        self.assertIsNone(trim["sqft"])          # per piece, not a flooring line
        self.assertEqual(d["total"], 8880.33)

    def test_credit_memo_layout_and_restocking_fee(self):
        d = sd.parse_quickbooks(credit("Cr1", 3, "97.8588", "293.58", fee=True), "credit_memo")
        self.assertEqual((d["doc_no"], d["date"]), ("Cr1", "2026-09-17"))
        self.assertEqual(d["lines"][0]["sqft"], 63.96)
        self.assertTrue(d["lines"][0]["restocking_fee"])

    def test_net_of_credit_is_the_actual_cost(self):
        orders, un = sd.build_orders(vidar_docs([credit("Cr1", 3, "97.8588", "293.58")]))
        p = orders["103273"]["products"]["OKMO161C"]
        self.assertEqual((p["stage"], p["net_sqft"], p["net_amount"], p["actual_rate_sqft"]),
                         ("invoice_final", 1641.64, 7535.12, 4.59))
        self.assertEqual(un, [])

    def test_restocking_fee_raises_the_rate_on_what_was_kept(self):
        # 14 boxes back at 75% of the box rate: the fee is a job cost
        orders, _ = sd.build_orders(vidar_docs([credit("Cr2", 14, "73.3941", "1,027.52", fee=True)]))
        p = orders["103273"]["products"]["OKMO161C"]
        self.assertGreater(p["actual_rate_sqft"], 4.59)
        self.assertIn("restocking_fee", orders["103273"]["flags"])

    def test_partial_invoice_and_confirmed_not_invoiced(self):
        docs = vidar_docs()[:2]
        p = sd.build_orders(docs)[0]["103273"]["products"]["OKMO161C"]
        self.assertEqual(p["stage"], "invoice_partial")
        o = sd.build_orders(docs[:1])[0]["103273"]
        self.assertEqual(o["products"]["OKMO161C"]["stage"], "confirmation")
        self.assertIn("confirmed_not_invoiced", o["flags"])

    def test_credit_with_two_candidate_orders_is_not_picked(self):
        docs = vidar_docs()
        other = sd.parse_quickbooks(inv("200001", 5, "489.29").replace("103273", "200000")
                                    .replace("8135", "9999"), "invoice")
        other["supplier"] = "vidar"
        docs += [other, sd.parse_quickbooks(credit("Cr3", 1, "97.8588", "97.86"), "credit_memo")]
        orders, un = sd.build_orders(docs)
        self.assertEqual(un[0]["doc_no"], "Cr3")
        self.assertEqual(sorted(un[0]["candidates"]), ["103273", "200000"])
        self.assertEqual(orders["103273"]["credits"], [])

    def test_reconfirmed_po_supersedes_the_old_estimate(self):
        old = sd.parse_quickbooks(EST.replace("103273", "100000").replace("2026-08-07", "2026-08-01"),
                                  "confirmation", "Estimate - Sales order 100000 from VIDAR DESIGN FLOORING")
        old["supplier"] = "vidar"
        orders, _ = sd.build_orders([old] + vidar_docs())
        self.assertEqual(orders["100000"]["status"], "superseded")
        self.assertNotIn("confirmed_not_invoiced", orders["100000"]["flags"])

    def test_read_only(self):
        src = (REPO_ROOT / "scripts" / "supplier_docs_pull.py").read_text()
        for verb in ('"POST"', '"PUT"', '"PATCH"', '"DELETE"', "/move", "/send", "/copy", "data="):
            self.assertNotIn(verb, src)


def floor_fixture(credits=(), row=None, sale_sku="ENG-VIDR-0178", sale_pid="click5", sold=1705.6):
    snap = sync_snapshot()
    snap["projects"][0]["ID"] = 461
    if row is not None:
        snap["flooring_lines"] = [dict({"url": P(400), "Project": [P(100)]}, **row)]
    ls = {"projects": {"461": {"pp": "PP-461", "sale_ids": ["s1"], "flags": [],
                               "totals_by_class": LS["projects"]["463"]["totals_by_class"],
                               "flooring_lines": [{"product_id": sale_pid, "sku": sale_sku,
                                                   "product_name": "x", "quantity": sold,
                                                   "category": "ENGINEERED HARDWOOD",
                                                   "unit_cost": 4.19}]}}}
    orders = {"projects": {"461": {"purchase_orders": [{"reference": "PO-8135", "status": "SENT", "supplier": "VIDAR",
                                                        "lines": [
        {"product_id": "tg6", "sku": "ENG-VIDR-0023",
         "product_name": "VIDENG - 6 American White Oak (Moon Light) T&G", "count": 1705.6,
         "received": 0, "unit_cost": 4.59}]}]}}, "product_po_cost": {}}
    o, un = sd.build_orders(vidar_docs(credits))
    docs = {"orders": o, "orders_by_po": {"8135": ["103273"]}, "unattributed_credits": un}
    return snap, ls, orders, docs


def floor_action(*a, **k):
    snap, ls, orders, docs = floor_fixture(*a, **k)
    out = pcs.plan(snap, REG, POLICY, ls_sales=ls, ls_orders=orders, supplier_docs=docs)
    return [x for x in out["actions"] if x["kind"] == "flooring_line"]


class TestFlooringLine(unittest.TestCase):
    def test_invoice_net_of_credit_creates_the_ordered_product_locked(self):
        (a,) = floor_action([credit("Cr1", 3, "97.8588", "293.58")], sold=1586.0)
        self.assertEqual((a["op"], a["mode"], a["stage"]), ("create", "write", "invoice_final"))
        self.assertEqual(a["fields"]["Sqft Sold"], 1641.64)       # invoice net of the credit, not the sale
        f = a["fields"]
        self.assertEqual(f["Floor SKU"], "ENG-VIDR-0023_Moon Light")   # ordered product, staff naming
        self.assertEqual((f["Material Company"], f["Material Type"]), (["VIDAR"], ["Engineered Hardwood"]))
        self.assertTrue(a["apply"])
        self.assertEqual((f["Cost Rate"], f["Invoice Cost Rate"], f["Cost Locked"]), (4.59, 4.59, True))
        self.assertEqual(f["LS Sale Cost Rate"], 4.19)            # compared, never used
        self.assertNotIn("Sold At Rate", f)                       # never from Lightspeed
        for flag in ("pm_entry_product_mismatch", "sale_cost_gap", "qty_gap",
                     "po_not_received_in_lightspeed", "quote_rate_missing"):
            self.assertIn(flag, a["flags"])

    def test_existing_line_matched_on_the_sku_before_the_underscore(self):
        acts = floor_action(row={"Floor SKU": "ENG-VIDR-0023_Moon Light", "Quote Rate": 6.29, "Sold At Rate": 6.29, "Sqft Sold": 1705.6, "Qty Check": "OK",
                                 "Cost Rate": 4.59, "Invoice Cost Rate": 4.59, "PO Cost Rate": 4.59,
                                 "LS Sale Cost Rate": 4.19, "Cost Locked": "__YES__"})
        self.assertEqual(acts, [])

    def test_only_flooring_lines_are_set_to_apply(self):
        snap, ls, orders, docs = floor_fixture()
        out = pcs.plan(snap, REG, POLICY, ls_sales=ls, ls_orders=orders, supplier_docs=docs)
        applied = {a["kind"] for a in out["actions"] if a["apply"]}
        self.assertEqual(applied, {"flooring_line"})
        self.assertEqual(out["write_mode"], "plan_only")

    def test_invoice_sqft_and_cost_win_over_the_sale(self):
        # PP-417 shape: boxes returned with a fee. Sqft and cost both come from the invoice net.
        (a,) = floor_action([credit("Cr2", 14, "73.3941", "1,027.52", fee=True)])
        self.assertEqual(a["qty_check"], "OK")                    # the 14 returned boxes explain the gap
        self.assertEqual((a["mode"], a["fields"]["Sqft Sold"]), ("write", 1407.12))
        self.assertAlmostEqual(a["fields"]["Cost Rate"] * a["fields"]["Sqft Sold"], 7828.70 - 1027.52, places=0)

    def test_legacy_numeric_sku_on_the_po_is_not_a_pm_mistake(self):
        snap, ls, orders, docs = floor_fixture(sale_sku="SPC-VIDR-0004")
        ls["projects"]["461"]["flooring_lines"][0]["product_name"] = "VIDLVP-SPC - SPC (Toffee Crunch) Click"
        orders["projects"]["461"]["purchase_orders"][0]["lines"][0].update(sku="11401", product_name="VIDVIN - VS084")
        (a,) = [x for x in pcs.plan(snap, REG, POLICY, ls_sales=ls, ls_orders=orders, supplier_docs=docs)["actions"]
                if x["kind"] == "flooring_line"]
        self.assertIn("legacy_ls_product_on_po", a["flags"])
        self.assertNotIn("pm_entry_product_mismatch", a["flags"])
        self.assertEqual(a["fields"]["Floor SKU"], "SPC-VIDR-0004_Toffee Crunch")

    def test_flooring_on_a_po_with_no_sale_uses_the_ordered_sqft(self):
        snap, ls, orders, docs = floor_fixture()
        orders["projects"]["461"]["purchase_orders"].append({"reference": "PO-9", "status": "SENT", "supplier": "EVERGREEN",
            "lines": [{"product_id": "lam", "sku": "LAM-EVGR-72740", "product_name": "x", "count": 582.3,
                       "received": 0, "unit_cost": 1.79}, {"product_id": "trim", "sku": "LRED", "product_name": "x",
                       "count": 1, "received": 0, "unit_cost": 15}]})
        acts = [x for x in pcs.plan(snap, REG, POLICY, ls_sales=ls, ls_orders=orders, supplier_docs=docs)["actions"]
                if x["kind"] == "flooring_line" and x["fields"].get("Floor SKU", "").startswith("LAM-")]
        (a,) = acts                                               # the trim is not a flooring line
        self.assertEqual((a["mode"], a["fields"]["Sqft Sold"]), ("write", 582.3))   # ordered sqft
        self.assertIn("ordered_not_on_sale", a["flags"])

    def _po_only(self, count, sold, row=None):
        snap, ls, orders, docs = floor_fixture(sold=sold, row=row)
        orders["projects"]["461"]["purchase_orders"][0]["lines"][0].update(count=count)
        (a,) = [x for x in pcs.plan(snap, REG, POLICY, ls_sales=ls, ls_orders=orders,
                                    supplier_docs={"orders": {}, "orders_by_po": {}})["actions"]
                if x["kind"] == "flooring_line"]
        return a

    def test_within_two_boxes_is_ok(self):
        self.assertEqual(self._po_only(1705.6, 1680.0)["qty_check"], "OK")     # 25.6 sqft, under 2 boxes

    def test_top_up_order_flags_part_from_stock_and_keeps_the_line(self):
        row = {"Floor SKU": "ENG-VIDR-0023", "Sqft Sold": 680, "Cost Rate": 2.09, "Sold At Rate": 3}
        a = self._po_only(54.39, 680.0, row=row)
        self.assertEqual(a["qty_check"], "Verify - part from stock")
        self.assertEqual(set(a["fields"]), {"Qty Check", "Qty Note"})       # figures untouched
        self.assertTrue(a["fields"]["Qty Note"].startswith("Auto:"))

    def test_more_ordered_than_sold_flags_leftover(self):
        self.assertEqual(self._po_only(1705.6, 1500.0)["qty_check"], "Verify - leftover")

    def test_verified_from_stock_blends_the_stock_cost(self):
        row = {"Floor SKU": "ENG-VIDR-0023", "Sqft Sold": 680, "Cost Rate": 2.09, "Sold At Rate": 3,
               "Qty Check": "Verified - from stock", "Qty Note": "rest from shelf"}
        a = self._po_only(54.39, 680.0, row=row)
        # 54.39 sqft at the PO 4.59 + 625.61 sqft at the LS average cost 4.19, over 680 sold
        self.assertEqual(a["fields"]["Cost Rate"], round((54.39 * 4.59 + 625.61 * 4.19) / 680, 4))
        self.assertNotIn("Qty Check", a["fields"])                           # a person's answer is kept
        self.assertNotIn("Sqft Sold", a["fields"])                           # 680 already right

    def test_verified_leftover_to_stock_charges_only_what_was_sold(self):
        row = {"Floor SKU": "ENG-VIDR-0023", "Sqft Sold": 1705.6, "Cost Rate": 4.59, "Sold At Rate": 6,
               "Qty Check": "Verified - leftover to stock"}
        a = self._po_only(1705.6, 1500.0, row=row)
        self.assertEqual(a["fields"]["Sqft Sold"], 1500.0)

    def test_sold_at_rate_comes_from_the_pm_quote(self):
        (a,) = floor_action(row={"Floor SKU": "ENG-VIDR-0023", "Quote Rate": 6.29, "Cost Rate": 4.59, "Sqft Sold": 1705.6,
                                 "Qty Check": "OK",
                                 "Invoice Cost Rate": 4.59, "PO Cost Rate": 4.59, "LS Sale Cost Rate": 4.19,
                                 "Cost Locked": "__YES__"})
        self.assertEqual(a["fields"], {"Sold At Rate": 6.29})
        self.assertNotIn("quote_rate_missing", a["flags"])

    def test_matching_line_is_silent(self):
        acts = floor_action(row={"Floor SKU": "ENG-VIDR-0023", "Quote Rate": 6.29, "Sold At Rate": 6.29, "Sqft Sold": 1705.6, "Qty Check": "OK",
                                 "Cost Rate": 4.59, "Invoice Cost Rate": 4.59, "PO Cost Rate": 4.59,
                                 "LS Sale Cost Rate": 4.19, "Cost Locked": "__YES__"})
        self.assertEqual(acts, [])

    def test_late_credit_with_fee_updates_a_locked_line(self):
        (a,) = floor_action([credit("Cr2", 14, "73.3941", "1,027.52", fee=True)], sold=1407.12,
                            row={"Floor SKU": "ENG-VIDR-0023", "Sold At Rate": 6.29, "Cost Rate": 4.59,
                                 "Invoice Cost Rate": 4.59, "PO Cost Rate": 4.59, "LS Sale Cost Rate": 4.19,
                                 "Cost Locked": "__YES__"})
        self.assertEqual(a["mode"], "write")
        self.assertGreater(a["fields"]["Cost Rate"], 4.59)
        self.assertIn("changed_after_lock", a["flags"])
        self.assertIn("restocking_fee", a["flags"])

    def test_invoice_replaces_an_earlier_hand_entered_rate(self):
        (a,) = floor_action(row={"Floor SKU": "ENG-VIDR-0023", "Sold At Rate": 6.29, "Cost Rate": 4.19})
        self.assertEqual((a["mode"], a["fields"]["Cost Rate"]), ("write", 4.59))

    def test_before_the_invoice_the_confirmation_is_the_truth(self):
        snap, ls, orders, docs = floor_fixture()
        o, _ = sd.build_orders(vidar_docs()[:1])                 # confirmation only
        docs["orders"] = o
        (a,) = [x for x in pcs.plan(snap, REG, POLICY, ls_sales=ls, ls_orders=orders, supplier_docs=docs)["actions"]
                if x["kind"] == "flooring_line"]
        self.assertEqual((a["stage"], a["mode"], a["fields"]["Cost Rate"], a["fields"]["Cost Locked"]),
                         ("confirmation", "write", 4.59, False))
        snap["flooring_lines"] = [{"url": P(400), "Project": [P(100)], "Floor SKU": "ENG-VIDR-0023",
                                   "Cost Rate": 4.39, "Sold At Rate": 6.29}]
        (a,) = [x for x in pcs.plan(snap, REG, POLICY, ls_sales=ls, ls_orders=orders, supplier_docs=docs)["actions"]
                if x["kind"] == "flooring_line"]
        self.assertEqual((a["mode"], a["fields"]["Cost Rate"]), ("write", 4.59))   # ordered beats a typed quote

    def test_line_named_after_the_wrong_sale_product_is_a_suggested_rename(self):
        (a,) = floor_action(row={"Floor SKU": "ENG-VIDR-0178", "Sold At Rate": 6.29, "Cost Rate": 4.19})
        self.assertEqual((a["op"], a["mode"], a["fields"]["Floor SKU"]), ("update", "suggest", "ENG-VIDR-0023_Moon Light"))

    def test_no_order_falls_back_to_the_sale_as_a_low_suggestion(self):
        snap, ls, orders, docs = floor_fixture()
        out = pcs.plan(snap, REG, POLICY, ls_sales=ls, ls_orders={"projects": {}, "product_po_cost": {}})
        (a,) = [x for x in out["actions"] if x["kind"] == "flooring_line"]
        self.assertEqual((a["stage"], a["mode"], a["confidence"]), ("ls_sale", "write", "Low"))
        self.assertIn("no_order_found", a["flags"])
        self.assertEqual(a["fields"]["Qty Check"], "Verify - no order")   # lands in front desk's view


# --- AP Disposal invoices -> Disposal cost row (Decision 13) ---

def disposal_text(no, street_line, total, date="2026-09-19", note=None):
    return f"""    Invoice no.: {no}
    Invoice date: {date}
#       Date           Product or service           Description                   Qty            Rate                 Amount         Tax
1.                     20 yard                     20 yard - Service Charge - 9      1         $150.00                $150.00     HST ON
                                                   {street_line}
2.      2026-08-24     Disposal Fee                Disposal Fee / Ton - Mixed     0.81         $120.00                 $97.20     HST ON
                                                   Garbage - Sept 18
                                                                                    Subtotal                                     $247.20
{"        Note to customer" if note else ""}
{("        " + note) if note else ""}
                                                                                  Total                                         ${total}
"""


AP_PAGE = "https://app.notion.com/32b596a4505f802b9b31f593bf2db68e"


def disposal_case(rows_cost=None, street="9 Midnight lane Brampton", end="2026-09-15", extra_projects=(),
                  invoices=None, assigned=AP_PAGE):
    snap = {"projects": [{"url": P(100), "ID": 450, "Street Address": street, "Assign Disposal": [AP_PAGE],
                          "Project End Date": end, "Submission Status": "Submitted"}] + list(extra_projects),
            "costs": [{"url": P(200), "Category": "Disposal", "Cost": rows_cost, "Assigned To": [assigned],
                       "Project": [P(100)]}],
            "financials": [], "work_orders": [], "payments": [], "team": [], "flooring_lines": []}
    if invoices is None:
        d = sd.parse_disposal(disposal_text("2406", "Midnight Lane", "279.34"))
        d.update(supplier="ap_disposal", received_at="2026-09-19T10:00:00Z")
        invoices = [d]
    docs = {"disposal_invoices": sd.disposal_invoices(invoices)}
    out = pcs.plan(snap, REG, POLICY, supplier_docs=docs)
    return [a for a in out["actions"] if a["kind"] == "disposal_cost"], out["notes"]


class TestDisposal(unittest.TestCase):
    def test_street_parsed_across_the_wrapped_description(self):
        d = sd.parse_disposal(disposal_text("2406", "Midnight Lane", "279.34"))
        self.assertEqual((d["doc_no"], d["total"], d["subtotal"]), ("2406", 279.34, 247.20))
        self.assertEqual(d["street"], {"number": "9", "name_key": "midnight", "unit": None})
        self.assertIsNone(sd.parse_street("20 yard"))

    def test_project_street_shapes(self):
        self.assertEqual(sd.parse_street("1109-5 Michael Power Place"), {"number": "5", "name_key": "michael", "unit": "1109"})
        self.assertEqual(sd.parse_street("4230 Fieldgate drive unit 4")["unit"], "4")
        self.assertEqual(sd.parse_street("1 Hurontario St #1705")["unit"], "1705")

    def test_matched_invoice_fills_an_empty_disposal_row_with_the_total_incl_tax(self):
        (a,), _ = disposal_case()
        self.assertEqual(a["mode"], "write")
        self.assertEqual(a["fields"], {"Cost": 279.34, "Invoice #": "2406", "Cost Source": "AP Invoice (auto)"})

    def test_matching_hand_entered_cost_only_gains_the_invoice_number(self):
        (a,), _ = disposal_case(rows_cost=279.34)
        self.assertEqual(a["fields"], {"Invoice #": "2406"})

    def test_different_hand_entered_cost_is_only_suggested(self):
        (a,), _ = disposal_case(rows_cost=300)
        self.assertEqual(a["mode"], "suggest")
        self.assertNotIn("Cost", a["fields"])

    def test_two_projects_at_one_street_are_never_picked(self):
        twin = {"url": P(101), "ID": 451, "Street Address": "9 Midnight Lane", "Project End Date": "2026-09-20"}
        acts, notes = disposal_case(extra_projects=[twin])
        self.assertEqual(acts, [])
        self.assertEqual(notes[0]["kind"], "disposal_unmatched")
        self.assertEqual(sorted(notes[0]["candidates"]), ["PP-450", "PP-451"])

    def test_date_window_separates_a_repeat_customer(self):
        old = {"url": P(101), "ID": 300, "Street Address": "9 Midnight Lane", "Project End Date": "2025-11-01"}
        (a,), _ = disposal_case(extra_projects=[old])
        self.assertEqual(a["pp"], "PP-450")

    def test_wrong_house_number_is_a_suggestion_when_one_ap_row_is_near(self):
        acts, notes = disposal_case(street="11 Midnight Lane")
        (a,) = acts
        self.assertEqual(a["mode"], "suggest")
        self.assertIn("street_number_differs", a["flags"])

    def test_reissued_invoice_follows_the_latest_copy_and_says_so(self):
        first = sd.parse_disposal(disposal_text("2410", "Huron heights", "279.34").replace(" - 9  ", " - 4798"))
        first.update(supplier="ap_disposal", received_at="2026-09-24T10:00:00Z")
        second = sd.parse_disposal(disposal_text("2410", "Midnight Lane", "279.34"))
        second.update(supplier="ap_disposal", received_at="2026-09-25T10:00:00Z")
        (inv,) = sd.disposal_invoices([first, second])
        self.assertEqual((inv["copies"], inv["street"]["name_key"]), (2, "midnight"))
        (a,), _ = disposal_case(invoices=[first, second])
        self.assertEqual(a["mode"], "suggest")              # the site moved: a person confirms
        self.assertIn("reissued_new_site", a["flags"])

    def test_out_of_scope_match_is_a_note_with_a_cross_check(self):
        acts, notes = disposal_case(rows_cost=288.15, end="2026-08-20")
        self.assertEqual(acts, [])
        self.assertEqual((notes[0]["kind"], notes[0]["check"]),
                         ("disposal_out_of_scope", "Disposal row cost differs from this invoice"))
