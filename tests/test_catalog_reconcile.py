#!/usr/bin/env python3
"""Tests for the catalogue reconciler.

    python3 -m unittest discover -s tests -v

The centrepiece is TestGrandeurRegression. On 2026-09-03 a Grandeur backfill
matched products on colour alone, and Lightspeed rejected 9 of them with
"handle already exists for your retailer, sku already exists for your retailer".
The evidence is committed: ingest/2026-09-03/grandeur_ls_ignored_products_*.csv
holds the rejected rows with the UUIDs they wrongly carried.

The upload CSV in the repo is the CORRECTED file (commit 492cb03), so the test
reconstructs the broken state by putting the bad UUIDs back, and asserts the
reconciler blocks every one. That is the guarantee: the incident cannot recur
silently.
"""

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

spec = importlib.util.spec_from_file_location(
    "catalog_reconcile", REPO_ROOT / "scripts/catalog_reconcile.py")
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)

GRANDEUR_UPLOAD = REPO_ROOT / "ingest/2026-09-03/grandeur_airtable_upload_2026-09-03.csv"
GRANDEUR_IGNORED = REPO_ROOT / "ingest/2026-09-03/grandeur_ls_ignored_products_2026-09-03.csv"
GRANDEUR_EXISTING = REPO_ROOT / "ingest/2026-09-03/grandeur_airtable_existing.json"
LEE_UPLOAD = REPO_ROOT / "ingest/2026-09-09/lee_airtable_upload_2026-09-09.csv"

LEAVES = json.loads((REPO_ROOT / "platform-settings/lightspeed.json").read_text()
                    )["product_categories"]["leaves"]


def fake_ls(products):
    """An LS pull index built from plain dicts."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"products": products, "pulled_at": "2026-09-10T00:00:00-04:00"}, fh)
    return cr.load_lightspeed(fh.name)


def run(rows, products, existing=None, supplier="Test", ls_upload=None):
    return cr.reconcile(rows, fake_ls(products), existing or {}, supplier, LEAVES,
                        ls_upload)


def ls_upload_row(sku="NEW-1", handle="HNEW", name="BUILT NAME | 7\" x 6mm"):
    """A row as /process-price-list's ls_upload CSV would carry it."""
    return {sku: {"sku": sku, "handle": handle, "name": name,
                  "supply_price": "1.00", "retail_price": "2.00",
                  "product_category": "FLOORING / LAMINATE",
                  "brand_name": "B", "supplier_name": "S", "description": "d"}}


def row(**kw):
    base = {"SKU": "X-1", "Product name": "Thing", "Supplier": "Test",
            "Lightspeed ID": "", "LS Handle / Parent ID": "HX1",
            "MatchStatus": "matched", "Cost/unit": "1.00",
            "Retail price/unit": "2.00", "Category": "Laminate"}
    base.update(kw)
    return base


def product(**kw):
    base = {"id": "u-1", "sku": "X-1", "handle": "HX1", "name": "Thing",
            "supply_price": 1.0}
    base.update(kw)
    return base


class TestBlockReasons(unittest.TestCase):

    def reasons(self, blocked):
        return {b["reason"] for b in blocked}

    def test_uuid_belonging_to_another_sku_blocks(self):
        rows = [row(SKU="A-1", **{"Lightspeed ID": "u-other"})]
        ls = [product(id="u-other", sku="B-2", handle="HB2")]
        actions, blocked, _ = run(rows, ls)
        self.assertEqual(self.reasons(blocked), {"uuid_belongs_to_other_sku"})
        self.assertEqual(actions, [], "a blocked row must produce no action")

    def test_uuid_reused_within_the_file_blocks_every_row_involved(self):
        rows = [row(SKU="A-1", **{"Lightspeed ID": "dup"}),
                row(SKU="A-2", **{"Lightspeed ID": "dup"})]
        ls = [product(id="dup", sku="A-1"), product(id="o", sku="A-2", handle="H2")]
        actions, blocked, _ = run(rows, ls)
        self.assertEqual(len(blocked), 2)
        self.assertEqual(self.reasons(blocked), {"uuid_collision"})
        self.assertEqual(actions, [])

    def test_unknown_uuid_blocks(self):
        actions, blocked, _ = run([row(**{"Lightspeed ID": "ghost"})], [product()])
        self.assertEqual(self.reasons(blocked), {"uuid_not_in_lightspeed"})

    def test_ambiguous_match_blocks(self):
        for col, val in (("MatchStatus", "ambiguous"),
                         ("LS Match status", "AMBIGUOUS"),
                         ("LS Match status", "DUPLICATE")):
            with self.subTest(col=col, val=val):
                _, blocked, _ = run([row(**{col: val})], [])
                self.assertEqual(self.reasons(blocked), {"ambiguous_match"})

    def test_handle_collision_on_create_blocks(self):
        """A create whose handle already belongs to a different SKU."""
        rows = [row(SKU="NEW-1", MatchStatus="new", **{"LS Handle / Parent ID": "SHARED"})]
        ls = [product(id="u9", sku="OTHER-9", handle="SHARED")]
        _, blocked, _ = run(rows, ls)
        self.assertEqual(self.reasons(blocked), {"handle_collision_on_create"})

    def test_missing_sku_blocks(self):
        _, blocked, _ = run([row(SKU="")], [])
        self.assertEqual(self.reasons(blocked), {"sku_missing"})

    def test_blocked_entries_carry_no_id(self):
        """Unapprovable by construction — an approval names an action id."""
        _, blocked, _ = run([row(**{"Lightspeed ID": "ghost"})], [product()])
        for entry in blocked:
            self.assertNotIn("id", entry)


class TestUuidRecovery(unittest.TestCase):
    """A blank UUID whose SKU is already in LS is repairable, not a create."""

    def test_blank_uuid_recovers_from_the_sku_join(self):
        rows = [row(SKU="A-1", **{"Lightspeed ID": ""})]
        ls = [product(id="real-uuid", sku="A-1")]
        actions, blocked, _ = run(rows, ls)
        self.assertEqual(blocked, [])
        kinds = {(a["target_system"], a["op"]) for a in actions}
        self.assertIn(("lightspeed", "update"), kinds)
        self.assertNotIn(("lightspeed", "create"), kinds,
                         "recovering a UUID must never fall through to a create — "
                         "that is what makes Lightspeed duplicate the product")
        upsert = next(a for a in actions if a["op"] == "upsert")
        self.assertEqual(upsert["fields"]["Lightspeed ID"], "real-uuid")
        self.assertEqual(upsert["uuid_source"], "recovered_by_sku")

    def test_genuinely_new_sku_creates_and_queues_a_backfill(self):
        rows = [row(SKU="NEW-1", MatchStatus="new", **{"LS Handle / Parent ID": "HNEW"})]
        actions, blocked, _ = run(rows, [], ls_upload=ls_upload_row())
        self.assertEqual(blocked, [])
        ops = [(a["target_system"], a["op"]) for a in actions]
        self.assertIn(("lightspeed", "create"), ops)
        self.assertIn(("airtable", "backfill_ls_id"), ops)
        create = next(a for a in actions if a["op"] == "create")
        self.assertIsNone(create["ls_id"], "LS mints the UUID; never invent one")

    def test_create_without_the_ls_upload_file_is_blocked(self):
        """A create needs the skill-built name; it is never derived or guessed."""
        rows = [row(SKU="NEW-1", MatchStatus="new", **{"LS Handle / Parent ID": "HNEW"})]
        actions, blocked, _ = run(rows, [])
        self.assertEqual([b["reason"] for b in blocked], ["ls_payload_unavailable"])
        self.assertEqual(actions, [])

    def test_create_payload_comes_from_the_skill_built_row(self):
        rows = [row(SKU="NEW-1", MatchStatus="new",
                    **{"LS Handle / Parent ID": "HNEW", "Product name": "Airtable Name"})]
        actions, _, _ = run(rows, [], ls_upload=ls_upload_row())
        create = next(a for a in actions if a["op"] == "create")
        self.assertEqual(create["fields"]["name"], 'BUILT NAME | 7" x 6mm')
        self.assertNotEqual(create["fields"]["name"], "Airtable Name")

    def test_create_product_category_is_the_flat_api_leaf_not_the_csv_path(self):
        """lightspeed_push.py resolves product_category by exact name against the
        live /api/2.0/product_types list, which holds flat leaves ('SPC',
        'LAMINATE') — never the LS-upload CSV's ' / '-separated import-path form
        ('FLOORING / VINYL / SPC'). Confirmed live 2026-09-18: a create shipped
        with the path form 404s with "no product type named ... exists".
        """
        rows = [row(SKU="NEW-1", MatchStatus="new", **{"LS Handle / Parent ID": "HNEW"})]
        actions, _, _ = run(rows, [], ls_upload=ls_upload_row())
        create = next(a for a in actions if a["op"] == "create")
        self.assertEqual(create["fields"]["product_category"], "LAMINATE")
        self.assertEqual(create["fields"]["price_excluding_tax"], 2.0)


class TestNewToAirtableWritesTheFullRow(unittest.TestCase):
    """Found 2026-09-13, HOMESPRO: the first genuine new-to-Airtable supplier
    this reconciler was ever run against for real. DIFF_FIELDS exists to write
    only what changed on an UPDATE and is correct there; applied to a CREATE
    (no live record to diff against) it silently produced an Airtable upsert
    with ~5 of 57 columns populated and everything else blank — Supplier,
    Brand, Material type, Install method, Box size, Waterproof, and so on,
    simply never written. A create has to write the whole row instead."""

    def test_create_writes_every_non_blank_column_not_just_the_diff_set(self):
        # Box size (sf) deliberately omitted here — exposing it correctly is
        # TestSfbAlwaysExposed's concern, not this test's.
        rows = [row(SKU="NEW-1", MatchStatus="new", **{
            "LS Handle / Parent ID": "HNEW",
            "Brand": "Acme", "Material type": "SPC core",
            "Install method": "Click", "Waterproof": "TRUE",
            "Salesperson notes": "Sells well.",
        })]
        actions, blocked, _ = run(rows, [], ls_upload=ls_upload_row(sku="NEW-1"))
        self.assertEqual(blocked, [])
        upsert = next(a for a in actions if a["op"] == "upsert")
        for field, expected in {
            "Brand": "Acme", "Material type": "SPC core",
            "Install method": "Click", "Waterproof": "TRUE",
            "Salesperson notes": "Sells well.",
        }.items():
            self.assertEqual(upsert["fields"].get(field), expected,
                             f"{field} missing from a create's payload — this "
                             f"is the DIFF_FIELDS-on-create gap")

    def test_sku_is_never_in_the_create_payload(self):
        """RULE 0: the SKU is the merge key and immutable — never in the write."""
        rows = [row(SKU="NEW-1", MatchStatus="new",
                    **{"LS Handle / Parent ID": "HNEW"})]
        actions, _, _ = run(rows, [], ls_upload=ls_upload_row(sku="NEW-1"))
        upsert = next(a for a in actions if a["op"] == "upsert")
        self.assertNotIn("SKU", upsert["fields"])

    def test_blank_columns_are_excluded_not_written_as_empty_strings(self):
        rows = [row(SKU="NEW-1", MatchStatus="new", **{
            "LS Handle / Parent ID": "HNEW", "Brand": "",
            "Salesperson notes": "   ",
        })]
        actions, _, _ = run(rows, [], ls_upload=ls_upload_row(sku="NEW-1"))
        upsert = next(a for a in actions if a["op"] == "upsert")
        self.assertNotIn("Brand", upsert["fields"])
        self.assertNotIn("Salesperson notes", upsert["fields"])

    def test_helper_columns_never_reach_the_payload(self):
        """MatchStatus/MatchedRecId/LS Match status are reviewer scratch columns,
        never real Airtable fields — RULE 0a and process-price-list step 3."""
        rows = [row(SKU="NEW-1", MatchStatus="new", **{
            "LS Handle / Parent ID": "HNEW", "MatchedRecId": "recABC123",
            "LS Match status": "MATCHED",
        })]
        actions, _, _ = run(rows, [], ls_upload=ls_upload_row(sku="NEW-1"))
        upsert = next(a for a in actions if a["op"] == "upsert")
        self.assertNotIn("MatchedRecId", upsert["fields"])
        self.assertNotIn("MatchStatus", upsert["fields"])
        self.assertNotIn("LS Match status", upsert["fields"])

    def test_update_path_is_unaffected_still_writes_only_the_diff(self):
        """Regression guard: an existing, MATCHED record must still only get
        the narrow DIFF_FIELDS treatment — this fix must not widen updates."""
        rows = [row(SKU="A-1", MatchStatus="matched", **{
            "Lightspeed ID": "u-1", "Cost/unit": "5.00",
            "Salesperson notes": "New note that changed too.",
        })]
        ls = [product(id="u-1", sku="A-1", supply_price=1.0)]
        existing = {"A-1": {"SKU": "A-1", "ProductName": "Thing", "Cost": 1.0,
                            "Retail price/unit": "2.00", "Category": "Laminate"}}
        actions, _, _ = run(rows, ls, existing)
        upsert = next(a for a in actions if a["op"] == "upsert")
        self.assertIn("Cost/unit", upsert["fields"])
        self.assertNotIn("Salesperson notes", upsert["fields"],
                         "an update must still write only DIFF_FIELDS, not the "
                         "whole row — that widening is create-only")


class TestOrderingAndIds(unittest.TestCase):

    def test_forced_dependency_order(self):
        rows = [row(SKU="NEW-1", MatchStatus="new", **{"LS Handle / Parent ID": "HN"})]
        actions, _, _ = run(rows, [], ls_upload=ls_upload_row(handle="HN"))
        rank = [a["target_system"] + ":" + a["op"] for a in actions]
        self.assertLess(rank.index("airtable:upsert"), rank.index("lightspeed:create"))
        self.assertLess(rank.index("lightspeed:create"), rank.index("airtable:backfill_ls_id"))
        self.assertEqual([a["seq"] for a in actions], list(range(1, len(actions) + 1)))

    def test_action_ids_are_stable_across_runs(self):
        """Idempotent resume depends on this: the actions-log is keyed by id."""
        rows = [row(SKU="A-1", **{"Lightspeed ID": "u-1"})]
        ls = [product(id="u-1", sku="A-1")]
        first, _, _ = run(rows, ls)
        second, _, _ = run(rows, ls)
        self.assertEqual([a["id"] for a in first], [a["id"] for a in second])
        self.assertTrue(all(a["id"].startswith("cat-") for a in first))

    def test_action_ids_differ_per_target_system(self):
        rows = [row(SKU="A-1", **{"Lightspeed ID": "u-1"})]
        actions, _, _ = run(rows, [product(id="u-1", sku="A-1")])
        self.assertEqual(len({a["id"] for a in actions}), len(actions))


class TestDiff(unittest.TestCase):

    def test_unreadable_is_not_reported_as_empty(self):
        """A reviewer must tell 'was blank' from 'could not be read'."""
        rows = [row(SKU="A-1", **{"Lightspeed ID": "u-1"})]
        ls = [product(id="u-1", sku="A-1")]
        existing = {"A-1": {"SKU": "A-1", "ProductName": "Thing"}}  # no Cost, no Retail
        actions, _, _ = run(rows, ls, existing)
        upsert = next(a for a in actions if a["op"] == "upsert")
        self.assertIn("Retail price/unit", upsert["before_unreadable"])
        self.assertNotIn("Retail price/unit", upsert["before"])

    def test_prices_compare_numerically(self):
        """'3.40' and '3.4' are the same price and must not read as a change."""
        rows = [row(SKU="A-1", **{"Lightspeed ID": "u-1", "Cost/unit": "3.40"})]
        ls = [product(id="u-1", sku="A-1")]
        existing = {"A-1": {"SKU": "A-1", "Cost": 3.4, "ProductName": "Thing",
                            "SupplierSKU": None, "Category": "Laminate",
                            "Retail price/unit": "2.00", "Lightspeed ID": "u-1"}}
        actions, _, _ = run(rows, ls, existing)
        upserts = [a for a in actions if a["op"] == "upsert"]
        self.assertEqual(upserts, [], "no real change should produce no Airtable action")

    def test_blank_never_becomes_a_sentinel(self):
        self.assertIsNone(cr.clean(""))
        self.assertIsNone(cr.clean("   "))
        self.assertIsNone(cr.clean(None))
        self.assertEqual(cr.clean(" x "), "x")


class TestCategoryIsAWarningNotABlock(unittest.TestCase):

    def test_lvp_warns_because_the_mapping_is_unsettled(self):
        """LVP is a format; LS classifies vinyl by core (SPC/WPC/GLUE DOWN)."""
        rows = [row(SKU="A-1", Category="LVP", **{"Lightspeed ID": "u-1"})]
        actions, blocked, warnings = run(rows, [product(id="u-1", sku="A-1")])
        self.assertEqual(blocked, [])
        self.assertTrue(actions)
        self.assertEqual({w["reason"] for w in warnings}, {"category_unresolved"})

    def test_known_categories_do_not_warn(self):
        for cat in ("Laminate", "Engineered hardwood", "Solid hardwood"):
            with self.subTest(cat=cat):
                _, _, warnings = run([row(Category=cat, **{"Lightspeed ID": "u-1"})],
                                     [product(id="u-1")])
                self.assertEqual(warnings, [])


class TestRowInvariant(unittest.TestCase):
    """Every row yields actions OR a block, never both and never neither.

    The contract states this and it is easy to break: an early Airtable action can
    be emitted before a later Lightspeed check decides the row is unwritable,
    leaving a half-executed row in an approved plan.
    """

    def assert_partitioned(self, rows, actions, blocked):
        acted = {a["sku"] for a in actions}
        stopped = {b["sku"] for b in blocked if b["sku"]}
        self.assertFalse(acted & stopped,
                         f"rows both acted on and blocked: {sorted(acted & stopped)}")
        seen = acted | stopped
        for r in rows:
            sku = cr.clean(r.get("SKU"))
            if sku:
                self.assertIn(sku, seen, f"{sku} produced neither an action nor a block")

    def test_create_without_payload_emits_nothing_for_that_row(self):
        rows = [row(SKU="NEW-1", MatchStatus="new", **{"LS Handle / Parent ID": "HNEW"})]
        actions, blocked, _ = run(rows, [])
        self.assert_partitioned(rows, actions, blocked)

    def test_mixed_batch_stays_partitioned(self):
        rows = [
            row(SKU="OK-1", **{"Lightspeed ID": "u1"}),                      # clean update
            row(SKU="NEW-1", MatchStatus="new", **{"LS Handle / Parent ID": "HNEW"}),
            row(SKU="BAD-1", **{"Lightspeed ID": "u-elsewhere"}),            # wrong owner
            row(SKU="AMB-1", MatchStatus="ambiguous"),
        ]
        ls = [product(id="u1", sku="OK-1", handle="HOK"),
              product(id="u-elsewhere", sku="SOMEONE-ELSE", handle="HSE")]
        actions, blocked, _ = run(rows, ls, ls_upload=ls_upload_row())
        self.assert_partitioned(rows, actions, blocked)
        self.assertEqual({b["sku"] for b in blocked}, {"BAD-1", "AMB-1"})

    def test_grandeur_broken_file_stays_partitioned(self):
        pull = REPO_ROOT / "ingest/2026-09-10/lightspeed-products.json"
        if not (GRANDEUR_UPLOAD.exists() and pull.exists()):
            self.skipTest("missing fixture")
        products = json.loads(pull.read_text())["products"]
        with open(GRANDEUR_IGNORED, newline="", encoding="utf-8") as fh:
            bad = {r["sku"]: r["id"] for r in csv.DictReader(fh)}
        with open(GRANDEUR_UPLOAD, newline="", encoding="utf-8") as fh:
            rows = [dict(r) for r in csv.DictReader(fh)]
        for r in rows:
            if r["SKU"] in bad:
                r["Lightspeed ID"] = bad[r["SKU"]]
        actions, blocked, _ = cr.reconcile(rows, fake_ls(products), {}, "Grandeur", LEAVES)
        self.assert_partitioned(rows, actions, blocked)


class TestSfbAlwaysExposed(unittest.TestCase):
    """Enforced always, variant groups included (Albert, 2026-09-10)."""

    def upload(self, **kw):
        base = {"sku": "A-1", "handle": "HX1",
                "name": 'VIDENG - 7 AWO (X) T&G | 7.5" x 3mm x RL - 25.32sf/b',
                "variant_option_one_value": "", "supply_price": "1", "retail_price": "2",
                "product_category": "FLOORING / ENGINEERED HARDWOOD"}
        base.update(kw)
        return {"A-1": base}

    def test_sfb_in_the_name_passes(self):
        rows = [row(SKU="A-1", **{"Lightspeed ID": "", "Box size (sf)": "25.32"})]
        _, blocked, _ = run(rows, [], ls_upload=self.upload())
        self.assertEqual(blocked, [])

    def test_sfb_in_the_variant_value_passes(self):
        """A tile size group — the one family type whose name carries no sf/b."""
        rows = [row(SKU="A-1", **{"Lightspeed ID": "", "Box size (sf)": "20.18"})]
        _, blocked, _ = run(rows, [], ls_upload=self.upload(
            name="CIFDTIL - Aldo (Bianco)",
            variant_option_one_name="Size",
            variant_option_one_value="12 x 24 - 20.18sf/b"))
        self.assertEqual(blocked, [])

    def test_sfb_in_neither_is_blocked(self):
        """Exactly the ENG-VIDR-0038 defect: a uniform group with no sf/b anywhere."""
        rows = [row(SKU="A-1", **{"Lightspeed ID": "", "Box size (sf)": "25.32"})]
        actions, blocked, _ = run(rows, [], ls_upload=self.upload(
            name='VIDENG - 7 AWO (Snowwhite) T&G | 7.5" x 3mm x RL'))
        self.assertEqual([b["reason"] for b in blocked], ["sfb_not_exposed"])
        self.assertEqual(actions, [], "a blocked row must emit no action")

    def test_per_piece_items_are_exempt(self):
        """Accessories and STONE legitimately have no box size."""
        rows = [row(SKU="A-1", **{"Lightspeed ID": "", "Box size (sf)": ""})]
        _, blocked, _ = run(rows, [], ls_upload=self.upload(
            name="Vidar - Transition | Nosing | SPC"))
        self.assertEqual(blocked, [])

    def test_a_wrong_box_size_in_the_name_is_still_caught(self):
        rows = [row(SKU="A-1", **{"Lightspeed ID": "", "Box size (sf)": "18.19"})]
        _, blocked, _ = run(rows, [], ls_upload=self.upload())  # name says 25.32
        self.assertEqual([b["reason"] for b in blocked], ["sfb_not_exposed"])

    def test_an_update_is_not_blocked_on_a_name_it_never_sends(self):
        """8780af9 bug #2 (IMPRESSIVE 2026-09-14, again PL-381 2026-09-22).

        An update writes prices only, so the ls_upload row's name never reaches
        Lightspeed for a matched product. Checking it blocked 187 of 220 IMPRESSIVE
        rows on 09-14 and 67 of 250 on 09-22, while the fix sat unmerged.
        """
        rows = [row(SKU="A-1", **{"Lightspeed ID": "u-1", "Box size (sf)": "25.32",
                                  "Cost/unit": "2.00"})]
        ls = [product(id="u-1", sku="A-1", supply_price=1.0, price_excluding_tax=2.0)]
        actions, blocked, _ = run(rows, ls, ls_upload=self.upload(
            name="IMPRESSIVE legacy name with no box size"))
        self.assertEqual(blocked, [])
        self.assertIn("lightspeed", {a["target_system"] for a in actions})


class TestSelectOptionPreflight(unittest.TestCase):
    """A value Airtable lacks blocks the SKU on BOTH systems, before either write.

    IMPRESSIVE PL-381, 2026-09-22: Lightspeed took 151 writes, then Airtable refused
    all 282 because "IMPRESSIVE" was not a Supplier option. The pre-flight turns
    that into one block per SKU and zero writes anywhere.
    """

    OPTIONS = {"Supplier": {"IMPRESSIVE", "FLOORS AT WORK"},
               "Category": {"Laminate", "Engineered hardwood"}}

    def new_row(self, supplier="IMPRESSIVE", category="Laminate"):
        return row(SKU="LAM-IMPR-0001", MatchStatus="new", Supplier=supplier,
                   Category=category, **{"Lightspeed ID": "", "LS Handle / Parent ID": "HNEW"})

    def run_new(self, r, options):
        return cr.reconcile([r], fake_ls([]), {}, "IMPRESSIVE", LEAVES,
                            ls_upload_row(sku="LAM-IMPR-0001"), airtable_snapshot=True,
                            select_options=options)

    def test_a_missing_supplier_option_blocks_both_sides(self):
        actions, blocked, _ = self.run_new(self.new_row(),
                                           {"Supplier": {"FLOORS AT WORK"}})
        self.assertEqual(["supplier_option_missing"], [b["reason"] for b in blocked])
        self.assertEqual([], actions, "no Lightspeed create may run ahead of Airtable")

    def test_a_live_option_writes_normally(self):
        actions, blocked, _ = self.run_new(self.new_row(), self.OPTIONS)
        self.assertEqual([], blocked)
        self.assertEqual({"airtable", "lightspeed"}, {a["target_system"] for a in actions})

    def test_a_case_only_difference_is_blocked_and_named(self):
        """Typecast is off, so 'Floors At Work' is refused; with it on, it duplicates."""
        _, blocked, _ = self.run_new(self.new_row(supplier="Floors At Work"), self.OPTIONS)
        self.assertEqual("supplier_option_missing", blocked[0]["reason"])
        self.assertIn("FLOORS AT WORK", blocked[0]["detail"])

    def test_other_select_fields_use_their_own_reason(self):
        _, blocked, _ = self.run_new(self.new_row(category="LAM"), self.OPTIONS)
        self.assertEqual(["select_option_missing"], [b["reason"] for b in blocked])

    def test_no_options_means_no_check(self):
        """Backwards compatible: main() warns select_options_not_checked instead."""
        _, blocked, _ = self.run_new(self.new_row(), None)
        self.assertEqual([], blocked)

    def test_raw_schema_output_is_accepted(self):
        schema = {"tables": [{"id": "tbl", "fields": [
            {"name": "Supplier", "type": "singleSelect",
             "options": {"choices": [{"id": "sel1", "name": "IMPRESSIVE"}]}},
            {"name": "Tags", "type": "multipleSelects",
             "options": {"choices": [{"name": "Clearance"}, {"name": "Promo"}]}},
            {"name": "Product name", "type": "singleLineText"}]}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(schema, fh)
        got = cr.load_select_options(fh.name)
        self.assertEqual({"Supplier": {"IMPRESSIVE"}, "Tags": {"Clearance", "Promo"}}, got)

    def test_multi_select_values_are_checked_one_by_one(self):
        missing = cr.missing_select_options({"Tags": "Clearance, Bogus"},
                                            {"Tags": {"Clearance", "Promo"}})
        self.assertEqual([("Tags", "Bogus", None)], missing)


class TestSupplierSkuIdentity(unittest.TestCase):
    """8780af9 bug #1: a pre-pipeline Lightspeed product keeps the supplier's raw code.

    RULE 0a's third state (new to Airtable, already live in Lightspeed): the live
    `sku` is the supplier's code, recorded in Airtable's `Supplier SKU`, never the
    Airtable SKU. IMPRESSIVE blocked 156 of 156 matched rows on 2026-09-14 for this;
    on 2026-09-22 PL-381 worked around it by giving Airtable SKUs LS raw codes.
    """

    def test_uuid_whose_ls_sku_is_the_supplier_sku_is_accepted(self):
        rows = [row(SKU="ENG-IMPR-0001", **{"Supplier SKU": "4400",
                                             "Lightspeed ID": "u-1", "Cost/unit": "2.00"})]
        ls = [product(id="u-1", sku="4400", supply_price=1.0)]
        actions, blocked, _ = run(rows, ls)
        self.assertEqual(blocked, [])
        self.assertTrue(actions)

    def test_a_blank_uuid_is_recovered_through_the_supplier_sku(self):
        rows = [row(SKU="ENG-IMPR-0001", **{"Supplier SKU": "4400", "Lightspeed ID": ""})]
        ls = [product(id="u-1", sku="4400")]
        actions, blocked, _ = run(rows, ls)
        self.assertEqual(blocked, [])
        self.assertFalse([a for a in actions if a["op"] == "create"],
                         "a live product must never be created again")

    def test_a_genuinely_different_product_is_still_blocked(self):
        """The Grandeur guard is untouched: neither identifier matches."""
        rows = [row(SKU="ENG-IMPR-0001", **{"Supplier SKU": "4400",
                                             "Lightspeed ID": "u-1"})]
        ls = [product(id="u-1", sku="9999")]
        _, blocked, _ = run(rows, ls)
        self.assertEqual([b["reason"] for b in blocked], ["uuid_belongs_to_other_sku"])


class TestMixedBoxSizeGroup(unittest.TestCase):
    """A grade group boxing two ways states BOTH in the name (Albert, 2026-09-10).

    The combined `18.19/20.18sf/b` is identical on every row, so Lightspeed's
    one-name-per-family rule still holds, and it is the standing prompt to confirm
    with the supplier which size this product actually is. Column 11 still carries
    this row's own value, because the combined name cannot tell a staff member how
    many square feet are in the box they are holding.
    """

    MIXED_NAME = ('VIDENG - HB 5 AWO (Macaroon) T&G | 5" x 18mm x RL - 3mm top'
                  " - 18.19/20.18sf/b")

    def ls_rows(self, name=MIXED_NAME, values=("Select - 20.18sf/b",
                                               "Select & Better - 18.19sf/b")):
        return {f"A-{i + 1}": {"sku": f"A-{i + 1}", "handle": "HX1", "name": name,
                               "variant_option_one_name": "Grade",
                               "variant_option_one_value": v,
                               "supply_price": "1", "retail_price": "2",
                               "product_category": "FLOORING / ENGINEERED HARDWOOD"}
                for i, v in enumerate(values)}

    def upload_rows(self, boxes=("20.18", "18.19")):
        return [row(SKU=f"A-{i + 1}", **{"Lightspeed ID": "", "Box size (sf)": b,
                                         "LS Handle / Parent ID": "HX1"})
                for i, b in enumerate(boxes)]

    def test_combined_name_plus_per_row_value_passes(self):
        rows = self.upload_rows()
        _, blocked, _ = run(rows, [], ls_upload=self.ls_rows())
        self.assertEqual(blocked, [])

    def test_combined_value_is_ascending_two_decimals_unit_once(self):
        self.assertEqual(cr.combined_sfb(["18.19", "20.18"]), "18.19/20.18sf/b")
        self.assertEqual(
            cr.box_sizes_by_handle(self.upload_rows())["HX1"], ["18.19", "20.18"],
            "sorted numerically, not as strings")

    def test_only_one_size_in_the_name_is_blocked(self):
        """The old rule's output: one grade's number standing for the whole family."""
        rows = self.upload_rows()
        actions, blocked, _ = run(rows, [], ls_upload=self.ls_rows(
            name='VIDENG - HB 5 AWO (Macaroon) T&G | 5" x 18mm x RL - 3mm top'
                 " - 20.18sf/b"))
        self.assertEqual([b["reason"] for b in blocked],
                         ["sfb_not_exposed", "sfb_not_exposed"])
        self.assertEqual(actions, [], "blocked rows must emit no action")

    def test_no_sfb_in_the_name_is_blocked_even_when_column_11_has_it(self):
        """What the superseded rule produced — column 11 alone is no longer enough."""
        rows = self.upload_rows()
        _, blocked, _ = run(rows, [], ls_upload=self.ls_rows(
            name='VIDENG - HB 5 AWO (Macaroon) T&G | 5" x 18mm x RL - 3mm top'))
        self.assertEqual(len(blocked), 2)
        self.assertIn("confirm with the supplier", blocked[0]["detail"])

    def test_combined_name_without_the_per_row_value_is_blocked(self):
        """The other half: which of the two is THIS grade?"""
        rows = self.upload_rows()
        _, blocked, _ = run(rows, [], ls_upload=self.ls_rows(
            values=("Select", "Select & Better")))
        self.assertEqual(len(blocked), 2)
        self.assertIn("does not say which", blocked[0]["detail"])

    def test_a_uniform_group_still_wants_only_the_name(self):
        """Unchanged: one number, in the name, and column 11 left a clean grade."""
        rows = self.upload_rows(boxes=("20.18", "20.18"))
        _, blocked, _ = run(rows, [], ls_upload=self.ls_rows(
            name='VIDENG - HB 5 AWO (Macaroon) T&G | 5" x 18mm x RL - 3mm top'
                 " - 20.18sf/b",
            values=("Select", "Select & Better")))
        self.assertEqual(blocked, [])

    def test_a_tile_size_group_is_exempt_from_the_name_half(self):
        """Box size varies with size by construction — nothing to ask the supplier."""
        rows = self.upload_rows(boxes=("15.52", "21.33"))
        ls_rows = self.ls_rows(name="CIFDTIL - Aldo (Bianco)",
                               values=("12 x 24 - 15.52sf/b", "32 x 32 - 21.33sf/b"))
        for r in ls_rows.values():
            r["variant_option_one_name"] = "Size"
        _, blocked, _ = run(rows, [], ls_upload=ls_rows)
        self.assertEqual(blocked, [])


class TestPromoPricing(unittest.TestCase):
    """supply_price follows the promo; retail does not (Albert, 2026-09-10).

    `Cost/unit` keeps the REGULAR cost — it is what the price reverts to — so the
    promo cost reaches Lightspeed through supply_price only, and clearing
    `Promo cost ($/sf)` on `Promo end date` puts supply_price back with no second
    decision needed.
    """

    def test_promo_cost_becomes_supply_price(self):
        out = cr.ls_update_fields({"Cost/unit": "4.20", "Retail price/unit": "5.20",
                                   "Promo cost ($/sf)": "3.15"})
        self.assertEqual(out["supply_price"], 3.15)

    def test_retail_stays_off_the_regular_cost(self):
        """Retail is Cost + $ 1.00 on the REGULAR cost, not the promo cost."""
        out = cr.ls_update_fields({"Cost/unit": "4.20", "Retail price/unit": "5.20",
                                   "Promo cost ($/sf)": "3.15"})
        self.assertEqual(out["price_excluding_tax"], 5.20)
        self.assertNotEqual(out["price_excluding_tax"], 4.15,
                            "retail must not be derived from the promo cost")

    def test_no_promo_uses_the_regular_cost(self):
        out = cr.ls_update_fields({"Cost/unit": "4.20", "Retail price/unit": "5.20"})
        self.assertEqual(out["supply_price"], 4.20)

    def test_a_cleared_promo_reverts_supply_price(self):
        """Blank means genuinely empty, so the promo simply stops applying."""
        for blank in ("", "   ", None):
            out = cr.ls_update_fields({"Cost/unit": "4.20", "Retail price/unit": "5.20",
                                       "Promo cost ($/sf)": blank})
            self.assertEqual(out["supply_price"], 4.20, f"blank={blank!r}")

    def test_update_still_writes_only_prices(self):
        """A promo must not widen the payload — no name, no supplier, no category."""
        out = cr.ls_update_fields({"Cost/unit": "4.20", "Retail price/unit": "5.20",
                                   "Promo cost ($/sf)": "3.15",
                                   "Product name": "X", "Supplier": "Y",
                                   "Category": "Z"})
        self.assertEqual(set(out), {"supply_price", "price_excluding_tax"})


class TestPromoMarkerAndSfb(unittest.TestCase):
    """The `(P YYYY-MM-DD)` prefix lives in column 11 and must not disturb sf/b.

    The date is inside the marker so a stale one exposes its own staleness — the
    marker is a prompt to verify, not a claim the sale is live (Albert, 2026-09-10).
    """

    def test_p_prefix_does_not_hide_sfb_in_a_mixed_group(self):
        rows = [row(SKU=f"A-{i}", **{"Lightspeed ID": "", "Box size (sf)": b,
                                     "LS Handle / Parent ID": "HX1"})
                for i, b in ((1, "20.18"), (2, "18.19"))]
        ls_rows = {
            f"A-{i}": {"sku": f"A-{i}", "handle": "HX1",
                       "name": 'VIDENG - HB 5 AWO (Macaroon) T&G | 5" x 18mm x RL'
                               " - 18.19/20.18sf/b",
                       "variant_option_one_name": "Grade",
                       "variant_option_one_value": v,
                       "supply_price": "1", "retail_price": "2",
                       "product_category": "FLOORING / ENGINEERED HARDWOOD"}
            for i, v in ((1, "(P 2026-10-31) Select - 20.18sf/b"),
                         (2, "Select & Better - 18.19sf/b"))}
        _, blocked, _ = run(rows, [], ls_upload=ls_rows)
        self.assertEqual(blocked, [],
                         "a dated (P ...) variant value still exposes its box size")

    def test_p_prefix_on_a_singleton_name_keeps_sfb_readable(self):
        rows = [row(SKU="A-1", **{"Lightspeed ID": "", "Box size (sf)": "25.32"})]
        _, blocked, _ = run(rows, [], ls_upload={"A-1": {
            "sku": "A-1", "handle": "HX1",
            "name": '(P 2026-10-31) VIDENG - 7 AWO (X) T&G | 7.5" x 3mm x RL - 25.32sf/b',
            "variant_option_one_value": "", "supply_price": "1", "retail_price": "2",
            "product_category": "FLOORING / ENGINEERED HARDWOOD"}})
        self.assertEqual(blocked, [])


class TestAirtableSnapshotRequired(unittest.TestCase):
    """Planning Airtable writes from the upload CSV is not allowed.

    The CSV records the base as it stood when the price list was processed. On
    2026-09-10 that difference was real: the Lee plan claimed 50 rows needed a
    Lightspeed ID backfill when the live base was missing exactly 5, because the
    other 45 had been filled in after the CSV was written.
    """

    def test_no_snapshot_means_no_airtable_actions(self):
        rows = [row(SKU="A-1", **{"Lightspeed ID": "u-1", "Cost/unit": "9.99"})]
        ls = [product(id="u-1", sku="A-1", supply_price=1.0, price_excluding_tax=2.0)]
        actions, blocked, _ = cr.reconcile(rows, fake_ls(ls), {}, "T", LEAVES,
                                           airtable_snapshot=False)
        self.assertEqual([a for a in actions if a["target_system"] == "airtable"], [])
        self.assertEqual(blocked, [])

    def test_the_lightspeed_side_still_plans(self):
        """LS is reconciled against the live pull, so it is unaffected."""
        rows = [row(SKU="A-1", **{"Lightspeed ID": "u-1", "Cost/unit": "9.99"})]
        ls = [product(id="u-1", sku="A-1", supply_price=1.0, price_excluding_tax=2.0)]
        actions, _, _ = cr.reconcile(rows, fake_ls(ls), {}, "T", LEAVES,
                                     airtable_snapshot=False)
        ls_actions = [a for a in actions if a["target_system"] == "lightspeed"]
        self.assertEqual([a["op"] for a in ls_actions], ["update"])

    def test_a_create_still_queues_its_backfill_shape(self):
        """A create's backfill action is about a UUID that does not exist yet, so it
        does not depend on knowing current Airtable state."""
        rows = [row(SKU="NEW-1", MatchStatus="new", **{"LS Handle / Parent ID": "HNEW"})]
        actions, blocked, _ = cr.reconcile(rows, fake_ls([]), {}, "T", LEAVES,
                                           ls_upload_row(), airtable_snapshot=False)
        self.assertEqual(blocked, [])
        ops = {(a["target_system"], a["op"]) for a in actions}
        self.assertIn(("lightspeed", "create"), ops)
        self.assertIn(("airtable", "backfill_ls_id"), ops)


class TestPriceMapping(unittest.TestCase):
    """Airtable -> Lightspeed price fields, verified against every matched row."""

    @classmethod
    def setUpClass(cls):
        pull = REPO_ROOT / "ingest/2026-09-10/lightspeed-products.json"
        if not pull.exists():
            raise unittest.SkipTest("no Lightspeed pull")
        cls.ls = {p["sku"]: p for p in json.loads(pull.read_text())["products"]}

    def test_payload_uses_the_verified_field_names(self):
        fields = cr.ls_update_fields(row(**{"Cost/unit": "3.69", "Retail price/unit": "4.69"}))
        self.assertEqual(fields["supply_price"], 3.69)
        self.assertEqual(fields["price_excluding_tax"], 4.69)
        self.assertNotIn("retail_price", fields,
                         "the API has no retail_price field; that name is CSV-only")
        self.assertNotIn("price_including_tax", fields,
                         "inclusive price is derived at checkout, never written")

    def test_an_update_never_writes_name_or_supplier(self):
        """The destructive payload. LS holds a constructed name and its own
        supplier spelling; writing Airtable's would rename products in the POS."""
        fields = cr.ls_update_fields(row(**{"Product name": "Grandeur 6.5\" EWO",
                                            "Supplier": "Grandeur", "Brand": "Grandeur",
                                            "Category": "Engineered hardwood"}))
        for forbidden in ("name", "supplier_name", "brand_name", "product_category",
                          "handle", "sku"):
            self.assertNotIn(forbidden, fields)
        self.assertEqual(set(fields), {"supply_price", "price_excluding_tax"})

    def test_mapping_holds_across_every_matched_row(self):
        checked = 0
        for path in (GRANDEUR_UPLOAD, LEE_UPLOAD):
            if not path.exists():
                continue
            with open(path, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    live = self.ls.get(r["SKU"])
                    if not live or live.get("price_excluding_tax") is None:
                        continue
                    try:
                        cost = round(float(r["Cost/unit"]), 2)
                        retail = round(float(r["Retail price/unit"]), 2)
                    except (ValueError, TypeError, KeyError):
                        continue
                    self.assertEqual(round(live["supply_price"], 2), cost, r["SKU"])
                    self.assertEqual(round(live["price_excluding_tax"], 2), retail, r["SKU"])
                    checked += 1
        self.assertGreaterEqual(checked, 300, "expected ~315 comparable rows")

    def test_prices_are_stored_tax_exclusive(self):
        """HST is applied at checkout by the outlet rule, not held on the product.

        If this ever fails, Lightspeed has started storing an inclusive price and
        the write rule in platform-settings/lightspeed.json needs revisiting.
        """
        priced = [p for p in self.ls.values()
                  if p.get("active") and p.get("price_excluding_tax")]
        inclusive = [p for p in priced
                     if p.get("price_including_tax") is not None
                     and abs(p["price_including_tax"] / p["price_excluding_tax"] - 1.13) < 0.0005]
        self.assertGreater(len(priced), 10000)
        self.assertEqual(inclusive, [],
                         f"{len(inclusive)} products now carry a tax-inclusive price")


class TestGrandeurRegression(unittest.TestCase):
    """The 2026-09-03 incident, replayed against the live catalogue."""

    @classmethod
    def setUpClass(cls):
        for path in (GRANDEUR_UPLOAD, GRANDEUR_IGNORED):
            if not path.exists():
                raise unittest.SkipTest(f"missing fixture {path}")
        cls.ls_pull = REPO_ROOT / "ingest/2026-09-10/lightspeed-products.json"
        if not cls.ls_pull.exists():
            raise unittest.SkipTest("no Lightspeed pull; run scripts/lightspeed_pull.py")
        cls.products = json.loads(cls.ls_pull.read_text())["products"]
        with open(GRANDEUR_IGNORED, newline="", encoding="utf-8") as fh:
            cls.rejected = list(csv.DictReader(fh))
        with open(GRANDEUR_UPLOAD, newline="", encoding="utf-8") as fh:
            cls.upload = list(csv.DictReader(fh))

    def broken_upload(self):
        """Put the bad UUIDs back, reconstructing the pre-fix file."""
        bad = {r["sku"]: r["id"] for r in self.rejected}
        rows = [dict(r) for r in self.upload]
        applied = 0
        for r in rows:
            if r["SKU"] in bad:
                r["Lightspeed ID"] = bad[r["SKU"]]
                applied += 1
        self.assertEqual(applied, len(bad),
                         "every rejected SKU should exist in the upload file")
        return rows

    def test_the_rejected_rows_are_all_blocked(self):
        rows = self.broken_upload()
        actions, blocked, _ = cr.reconcile(
            rows, fake_ls(self.products), {}, "Grandeur", LEAVES)

        rejected_skus = {r["sku"] for r in self.rejected}
        blocked_skus = {b["sku"] for b in blocked}
        self.assertEqual(len(rejected_skus), 9)
        self.assertTrue(rejected_skus <= blocked_skus,
                        f"Lightspeed rejected these and the reconciler let them through: "
                        f"{sorted(rejected_skus - blocked_skus)}")

        acted = {a["sku"] for a in actions}
        self.assertFalse(rejected_skus & acted,
                         "a blocked row must never also appear as an action")

    def test_reproduces_the_documented_7_uuids_across_16_rows(self):
        """Commit 492cb03: "Grandeur LS upload had 7 UUIDs shared across 16 rows".

        Restoring the bad UUIDs makes each one collide with the row that
        legitimately owns it — ENG-GRAN-0056 carried ENG-GRAN-0050's UUID, so both
        rows are implicated. The reconciler reproduces that count exactly, which is
        a stronger result than flagging the 9 Lightspeed happened to reject: it
        catches the four rows whose identity was equally wrong but which Lightspeed
        processed anyway.
        """
        rows = self.broken_upload()
        _, blocked, _ = cr.reconcile(rows, fake_ls(self.products), {}, "Grandeur", LEAVES)
        collided = {b["sku"] for b in blocked if b["reason"] == "uuid_collision"}
        uuids = {u for b in blocked if b["reason"] == "uuid_collision"
                 for u in [next(r["Lightspeed ID"] for r in rows if r["SKU"] == b["sku"])]}
        self.assertEqual(len(collided), 16)
        self.assertEqual(len(uuids), 7)
        self.assertTrue({r["sku"] for r in self.rejected} <= collided)

    def test_a_wrong_owner_alone_is_still_caught(self):
        """With no colliding partner, uuid_belongs_to_other_sku is the detector."""
        bad = {r["sku"]: r["id"] for r in self.rejected}
        sku, uuid = sorted(bad.items())[0]
        rows = [dict(r) for r in self.upload if r["SKU"] == sku]
        rows[0]["Lightspeed ID"] = uuid
        _, blocked, _ = cr.reconcile(rows, fake_ls(self.products), {}, "Grandeur", LEAVES)
        self.assertEqual([b["reason"] for b in blocked], ["uuid_belongs_to_other_sku"])

    def test_the_corrected_file_passes_cleanly(self):
        """The fix that shipped must reconcile with nothing blocked."""
        existing = cr.load_airtable_existing(GRANDEUR_EXISTING) if GRANDEUR_EXISTING.exists() else {}
        actions, blocked, _ = cr.reconcile(
            [dict(r) for r in self.upload], fake_ls(self.products), existing, "Grandeur", LEAVES)
        self.assertEqual(blocked, [], f"corrected file should not block: {blocked[:3]}")
        self.assertEqual(len(self.upload), 231)
        self.assertTrue(actions)


class TestLeeRoundTrip(unittest.TestCase):
    """Re-running a shipped file must not duplicate what Lightspeed already holds."""

    @classmethod
    def setUpClass(cls):
        pull = REPO_ROOT / "ingest/2026-09-10/lightspeed-products.json"
        if not (LEE_UPLOAD.exists() and pull.exists()):
            raise unittest.SkipTest("missing Lee fixture or Lightspeed pull")
        cls.products = json.loads(pull.read_text())["products"]
        with open(LEE_UPLOAD, newline="", encoding="utf-8") as fh:
            cls.rows = list(csv.DictReader(fh))

    def test_no_creates_because_every_sku_now_exists(self):
        """All 84 Lee SKUs were imported to LS on 2026-09-09; only 34 UUIDs came
        back into the committed file. Re-running it must recover the other 50
        rather than create duplicates."""
        actions, blocked, _ = cr.reconcile(
            [dict(r) for r in self.rows], fake_ls(self.products), {}, "Lee Flooring", LEAVES)
        self.assertEqual(blocked, [])
        creates = [a for a in actions if a["op"] == "create"]
        self.assertEqual(creates, [],
                         f"{len(creates)} rows would have been created as duplicates")
        carried = sum(1 for r in self.rows if (r.get("Lightspeed ID") or "").strip())
        recovered = {a["sku"] for a in actions
                     if a.get("uuid_source") == "recovered_by_sku"}
        self.assertEqual(carried, 34)
        self.assertEqual(len(recovered), len(self.rows) - carried,
                         "every row without a UUID should have been repaired by the "
                         "sku join, not turned into a create")


class DiffFieldsAndSnapshotAgree(unittest.TestCase):
    """DIFF_FIELDS and the snapshot /catalog-sync takes must name the same fields.

    live_value() returns readable=False for a key the snapshot lacks, and the
    caller then writes the field anyway. That is right for a genuinely new record
    and is a blanket overwrite on every matched row when the column was simply not
    selected. So the two lists drifting apart does not fail loudly — it quietly
    converts a diff into an overwrite, which is the failure this test exists for.
    """

    COMMAND = REPO_ROOT / ".claude" / "commands" / "catalog-sync.md"

    def test_every_diff_field_is_named_in_the_command(self):
        doc = self.COMMAND.read_text()
        block = doc.split("The snapshot must carry every field", 1)[1][:800]
        for field in cr.DIFF_FIELDS:
            self.assertIn(field, block,
                          f"{field!r} is diffed but /catalog-sync does not ask the "
                          f"snapshot for it — every matched row would be overwritten")

    def test_stock_status_and_promo_are_diffed(self):
        # Added 2026-09-22. Their absence is what let ~56 FAW clearance flags go
        # unwritten, and let a promo reach Lightspeed with nothing in Airtable to
        # clear it.
        for field in ("Stock status", "Promo cost ($/sf)", "Promo end date"):
            self.assertIn(field, cr.DIFF_FIELDS)

    def test_an_unreadable_field_is_written_not_treated_as_unchanged(self):
        """Pins the behaviour the two tests above exist to protect against."""
        value, readable = cr.live_value({"SKU": "X"}, "Stock status")
        self.assertIsNone(value)
        self.assertFalse(readable)


if __name__ == "__main__":
    unittest.main()
