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
        self.assertEqual(ops(r), {("promo_marker", "promo_marker_off")})
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
        self.assertEqual(ops(r), {("promo_marker", "promo_marker_off"),
                                  ("update", "promo_price_off")})
        marker = next(a for a in r["actions"] if a["op"] == "promo_marker")
        self.assertEqual(marker["fields"]["name"], NAME)
        up = next(a for a in r["actions"] if a["op"] == "update")
        self.assertEqual(up["fields"], {"supply_price": 1.19})

    def test_an_ended_promo_is_listed_for_the_rep_question(self):
        r = run([rec()], [prod()], as_of="2026-10-01")
        (e,) = r["recently_ended"]
        self.assertEqual((e["sku"], e["promo_list_url"]), ("A-1", "https://x/promo"))

    def test_the_lane_is_not_a_general_cost_sync(self):
        """Lightspeed at a cost that is neither the promo nor Cost/unit is
        /catalog-sync's business; the lane only moves a price out of the promo."""
        r = run([rec()], [prod(supply_price=1.50)], as_of="2026-10-01")
        self.assertNotIn("update", {a["op"] for a in r["actions"]})

    def test_a_legacy_bare_marker_comes_off_where_airtable_has_no_promo(self):
        r = run([rec(**{"Promo cost ($/sf)": None, "Promo end date": None})],
                [prod(name=f"(P) {NAME}", supply_price=1.19)])
        self.assertEqual(ops(r), {("promo_marker", "promo_marker_off")})

    def test_a_marker_with_no_airtable_record_is_left_alone(self):
        r = run([], [prod(name=f"(P) {NAME}")])
        self.assertEqual(r["actions"], [])
        self.assertEqual(r["warnings"][0]["reason"], "marker_without_airtable_record")

    def test_no_regular_cost_blocks_instead_of_guessing(self):
        r = run([rec(**{"Cost/unit": None})], [prod()], as_of="2026-10-01")
        self.assertEqual(r["blocked"][0]["reason"], "no_regular_cost")


class TestLimits(unittest.TestCase):
    def test_a_variant_member_gets_its_price_but_not_a_marker(self):
        r = run([rec()], [prod(variant_parent_id="fam-1", supply_price=1.19)])
        self.assertEqual({a["op"] for a in r["actions"]}, {"update"})
        self.assertEqual(r["warnings"][0]["reason"], "marker_on_variant")

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
        for name in ("(P 2026-09-30) X", "(P) X", "(P)X", "X (P) Y", "(PP) X", "(P 26-9-30) X"):
            self.assertEqual(ps.strip_marker(name), lw.strip_promo_marker(name), name)


if __name__ == "__main__":
    unittest.main()
