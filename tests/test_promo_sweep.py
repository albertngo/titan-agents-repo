"""The promo lane: Lightspeed derived from Airtable's promo every morning.

Albert, 2026-09-26: "I'd want the (P) renaming to happen when the promo goes in, and
leaves when it goes out. During the sweep." These pin what the lane may and may not
touch; tests/test_lightspeed.py pins the writer's guard.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import promo_sweep as ps  # noqa: E402
import lightspeed_write as lw  # noqa: E402

TODAY = "2026-09-26"
NAME = 'NAFLAM - Handscraped Laminates (Aphrodite) Click | 7.71" x 12mm x RL - 20.5sf/b'


def rec(**kw):
    base = {"SKU": "A-1", "Lightspeed ID": "u-1", "Cost/unit": 1.19,
            "Promo cost ($/sf)": 1.09, "Promo end date": "2026-09-30",
            "Supplier": "FLOORS AT WORK", "Promo List URL": "https://x/promo"}
    base.update(kw)
    return base


def prod(**kw):
    base = {"id": "u-1", "sku": "A-1", "name": NAME, "supply_price": 1.09,
            "active": True, "has_variants": False, "variant_parent_id": None}
    base.update(kw)
    return base


def run(records, products, as_of=TODAY, **kw):
    return ps.plan(records, products, as_of, **kw)


def ops(result):
    return {(a["op"], a["reason"]) for a in result["actions"]}


class TestPromoOn(unittest.TestCase):
    def test_an_active_promo_puts_the_dated_marker_on(self):
        r = run([rec()], [prod()])
        (a,) = r["actions"]
        self.assertEqual(a["op"], "promo_marker")
        self.assertEqual(a["fields"]["name"], f"(P 2026-09-30) {NAME}")
        self.assertEqual(a["fields"]["expect_name"], NAME)

    def test_an_active_promo_moves_the_cost_to_the_promo_cost(self):
        r = run([rec()], [prod(supply_price=1.19)])
        self.assertIn(("update", "promo_price_on"), ops(r))
        up = next(a for a in r["actions"] if a["op"] == "update")
        self.assertEqual(up["fields"], {"supply_price": 1.09})

    def test_the_last_day_is_still_on(self):
        r = run([rec()], [prod()], as_of="2026-09-30")
        self.assertIn(("promo_marker", "promo_marker_on"), ops(r))

    def test_no_end_date_is_not_a_running_promo(self):
        """Albert, 2026-09-26: every promo has an end date, strictly guessed if it
        must be. An undated one is reported, not treated as running forever."""
        r = run([rec(**{"Promo end date": None})], [prod(name=f"(P) {NAME}", supply_price=1.19)])
        self.assertEqual(ops(r), {("promo_marker", "marker_off")})
        self.assertIn("promo_end_missing", {w["reason"] for w in r["warnings"]})

    def test_a_marker_already_right_writes_nothing(self):
        r = run([rec()], [prod(name=f"(P 2026-09-30) {NAME}")])
        self.assertEqual(r["actions"], [])

    def test_a_verbal_extension_redates_the_marker(self):
        """The rep extends by a month: move Promo end date in Airtable, and the next
        sweep re-dates the marker (and restores the cost if it had come off)."""
        r = run([rec(**{"Promo end date": "2026-10-31"})],
                [prod(name=f"(P 2026-09-30) {NAME}", supply_price=1.19)], as_of="2026-10-01")
        marker = next(a for a in r["actions"] if a["op"] == "promo_marker")
        self.assertEqual(marker["fields"]["name"], f"(P 2026-10-31) {NAME}")
        self.assertIn(("update", "promo_price_on"), ops(r))


class TestPromoOff(unittest.TestCase):
    def test_the_day_after_the_end_takes_the_marker_and_the_promo_cost_off(self):
        r = run([rec()], [prod(name=f"(P 2026-09-30) {NAME}")], as_of="2026-10-01")
        self.assertEqual(ops(r), {("promo_marker", "marker_off"),
                                  ("update", "price_off")})
        marker = next(a for a in r["actions"] if a["op"] == "promo_marker")
        self.assertEqual(marker["fields"]["name"], NAME)
        up = next(a for a in r["actions"] if a["op"] == "update")
        self.assertEqual(up["fields"], {"supply_price": 1.19})

    def test_an_ended_promo_is_listed_for_the_rep_question(self):
        r = run([rec()], [prod()], as_of="2026-10-01")
        (e,) = r["recently_ended"]
        self.assertEqual((e["kind"], e["sku"], e["link"]), ("promo", "A-1", "https://x/promo"))

    def test_the_lane_is_not_a_general_cost_sync(self):
        """Lightspeed at a cost that is neither the promo nor Cost/unit is
        /catalog-sync's business; the lane only moves a price out of the promo."""
        r = run([rec()], [prod(supply_price=1.50)], as_of="2026-10-01")
        self.assertNotIn("update", {a["op"] for a in r["actions"]})

    def test_a_legacy_bare_marker_comes_off_where_airtable_has_no_promo(self):
        r = run([rec(**{"Promo cost ($/sf)": None, "Promo end date": None})],
                [prod(name=f"(P) {NAME}", supply_price=1.19)])
        self.assertEqual(ops(r), {("promo_marker", "marker_off")})

    def test_a_marker_with_no_airtable_record_is_left_alone(self):
        r = run([], [prod(name=f"(P) {NAME}")])
        self.assertEqual(r["actions"], [])
        self.assertEqual(r["warnings"][0]["reason"], "marker_without_airtable_record")

    def test_no_regular_cost_blocks_instead_of_guessing(self):
        r = run([rec(**{"Cost/unit": None})], [prod()], as_of="2026-10-01")
        self.assertEqual(r["blocked"][0]["reason"], "no_regular_cost")


class TestRepRate(unittest.TestCase):
    """Albert, 2026-09-26: a rep's special rate is its own field, marked (R), may have
    no end date, and the lower of rep and promo wins."""

    def test_a_rep_rate_with_no_end_is_ongoing(self):
        r = run([rec(**{"Promo cost ($/sf)": None, "Promo end date": None,
                        "Rep cost ($/sf)": 0.99})], [prod(supply_price=1.19)])
        self.assertIn(("update", "rep_price_on"), ops(r))
        marker = next(a for a in r["actions"] if a["op"] == "promo_marker")
        self.assertEqual(marker["fields"]["name"], f"(R) {NAME}")

    def test_a_dated_rep_rate_carries_its_date(self):
        r = run([rec(**{"Promo cost ($/sf)": None, "Rep cost ($/sf)": 0.99,
                        "Rep cost end date": "2026-12-31"})], [prod(supply_price=0.99)])
        self.assertEqual(r["actions"][0]["fields"]["name"], f"(R 2026-12-31) {NAME}")

    def test_the_lower_of_rep_and_promo_wins(self):
        rep_lower = run([rec(**{"Rep cost ($/sf)": 0.95})], [prod()])
        self.assertEqual(next(a for a in rep_lower["actions"] if a["op"] == "update")
                         ["fields"], {"supply_price": 0.95})
        self.assertTrue(next(a for a in rep_lower["actions"] if a["op"] == "promo_marker")
                        ["fields"]["name"].startswith("(R) "))
        promo_lower = run([rec(**{"Rep cost ($/sf)": 1.15})], [prod()])
        self.assertEqual(promo_lower["actions"][0]["fields"]["name"], f"(P 2026-09-30) {NAME}")

    def test_when_the_promo_ends_the_rep_rate_takes_over(self):
        r = run([rec(**{"Rep cost ($/sf)": 1.15})],
                [prod(name=f"(P 2026-09-30) {NAME}")], as_of="2026-10-01")
        self.assertEqual({a["reason"] for a in r["actions"]},
                         {"rep_price_on", "rep_marker_on"})

    def test_an_ended_rep_rate_reverts_and_is_listed(self):
        r = run([rec(**{"Promo cost ($/sf)": None, "Promo end date": None,
                        "Rep cost ($/sf)": 0.99, "Rep cost end date": "2026-09-25",
                        "Rep cost note": "Mike, phone"})],
                [prod(name=f"(R 2026-09-25) {NAME}", supply_price=0.99)])
        self.assertEqual(ops(r), {("update", "price_off"), ("promo_marker", "marker_off")})
        self.assertEqual(r["recently_ended"][0]["kind"], "rep rate")

    def test_a_rep_rate_at_or_above_the_list_cost_does_not_apply(self):
        r = run([rec(**{"Promo cost ($/sf)": None, "Promo end date": None,
                        "Rep cost ($/sf)": 1.19})], [prod(supply_price=1.19)])
        self.assertEqual(r["actions"], [])
        self.assertIn("rep_rate_not_better", {w["reason"] for w in r["warnings"]})


class TestLimits(unittest.TestCase):
    def test_a_variant_member_is_marked_on_its_own_value_not_the_family_name(self):
        """Albert, 2026-09-26: 'the P marker can go on variant names, not the parent
        one'. Verified live on ENG-VIDR-0046."""
        grade = {"id": "attr-grade", "name": "Grade", "value": "Character"}
        sibling = prod(id="u-2", sku="A-2", has_variants=True, variant_options=[
            {"id": "attr-grade", "name": "Grade", "value": "Select"}])
        r = run([rec()], [prod(has_variants=True, variant_options=[grade]), sibling])
        (a,) = r["actions"]
        self.assertEqual(a["op"], "variant_marker")
        self.assertEqual(a["fields"], {"attribute_id": "attr-grade", "expect_value": "Character",
                                       "value": "(P 2026-09-30) Character",
                                       "expect_sku": "A-1"})

    def test_a_variant_marker_comes_off_its_value(self):
        grade = {"id": "attr-grade", "name": "Grade", "value": "(P 2026-09-30) Character"}
        r = run([rec()], [prod(has_variants=True, variant_options=[grade])],
                as_of="2026-10-01")
        marker = next(a for a in r["actions"] if a["op"] == "variant_marker")
        self.assertEqual((marker["fields"]["value"], marker["reason"]), ("Character", "marker_off"))

    def test_a_variant_value_a_sibling_already_holds_blocks(self):
        grade = {"id": "attr-grade", "name": "Grade", "value": "Character"}
        twin = prod(id="u-2", sku="A-2", has_variants=True, variant_options=[
            {"id": "attr-grade", "name": "Grade", "value": "(P 2026-09-30) Character"}])
        r = run([rec()], [prod(has_variants=True, variant_options=[grade]), twin])
        self.assertEqual(r["blocked"][0]["reason"], "variant_value_collision")

    def test_a_name_collision_blocks(self):
        other = prod(id="u-2", sku="B-1", name=f"(P 2026-09-30) {NAME}")
        r = run([rec()], [prod(), other])
        self.assertEqual(r["blocked"][0]["reason"], "name_collision")

    def test_an_inactive_product_is_skipped(self):
        r = run([rec()], [prod(active=False, supply_price=1.19)])
        self.assertEqual(r["actions"], [])

    def test_a_product_is_found_by_uuid_before_sku(self):
        r = run([rec(**{"Lightspeed ID": "u-9"})],
                [prod(), prod(id="u-9", sku="LEGACY-9", name="Other")])
        self.assertTrue(all(a["ls_id"] == "u-9" for a in r["actions"]))

    def test_a_large_morning_needs_a_person(self):
        records = [rec(SKU=f"A-{i}", **{"Lightspeed ID": f"u-{i}"}) for i in range(3)]
        products = [prod(id=f"u-{i}", sku=f"A-{i}", name=f"{NAME} {i}") for i in range(3)]
        self.assertEqual(run(records, products, max_changes=2)["status"], "needs_person")
        self.assertEqual(run(records, products, max_changes=3)["status"], "ready")

    def test_ids_are_daily_and_bound_to_the_target(self):
        a = run([rec()], [prod()])["actions"][0]["id"]
        self.assertEqual(a, run([rec()], [prod()])["actions"][0]["id"])
        self.assertNotEqual(a, run([rec()], [prod()], as_of="2026-09-27")["actions"][0]["id"])
        b = run([rec(**{"Promo end date": "2026-10-31"})], [prod()])["actions"][0]["id"]
        self.assertNotEqual(a, b)

    def test_a_partial_airtable_read_is_refused(self):
        import json
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"total_record_count": 2, "records": [rec()]}, f)
        with self.assertRaises(SystemExit):
            ps.load_airtable(f.name)

    def test_raw_mcp_pages_are_mapped_and_a_missing_page_is_refused(self):
        import json
        import tempfile
        page = {"records": [{"id": "rec1", "cellValuesByFieldId": {
            "fldx3byCOht5HbKmH": "A-1", "fldRZJ5JW4G6Yig8x": {"id": "sel", "name": "FAW"},
            "fldluA0eeTCwfton7": "2026-09-30"}}], "metadata": {"totalRecordCount": 1}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(page, f)
        (r,) = ps.load_airtable_raw([f.name])
        self.assertEqual((r["SKU"], r["Supplier"], r["Promo end date"]), ("A-1", "FAW", "2026-09-30"))
        page["metadata"]["totalRecordCount"] = 2
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(page, f)
        with self.assertRaises(SystemExit):
            ps.load_airtable_raw([f.name])

    def test_the_planner_contains_no_write_verb(self):
        src = (REPO_ROOT / "scripts" / "promo_sweep.py").read_text()
        for verb in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertNotIn(f'"{verb}"', src)
        self.assertNotRegex(src, r"(?m)^\s*(from|import)\s+lightspeed_(write|push)")

    def test_planner_and_writer_agree_on_the_marker(self):
        for name in ("(P 2026-09-30) X", "(P) X", "(P)X", "X (P) Y", "(PP) X", "(P 26-9-30) X",
                     "(R) X", "(R 2026-12-31) X", "(Q) X"):
            self.assertEqual(ps.strip_marker(name), lw.strip_promo_marker(name), name)


if __name__ == "__main__":
    unittest.main()
