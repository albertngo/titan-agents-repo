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


def run(rows, products, existing=None, supplier="Test"):
    return cr.reconcile(rows, fake_ls(products), existing or {}, supplier, LEAVES)


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
        actions, blocked, _ = run(rows, [])
        self.assertEqual(blocked, [])
        ops = [(a["target_system"], a["op"]) for a in actions]
        self.assertIn(("lightspeed", "create"), ops)
        self.assertIn(("airtable", "backfill_ls_id"), ops)
        create = next(a for a in actions if a["op"] == "create")
        self.assertIsNone(create["ls_id"], "LS mints the UUID; never invent one")


class TestOrderingAndIds(unittest.TestCase):

    def test_forced_dependency_order(self):
        rows = [row(SKU="NEW-1", MatchStatus="new", **{"LS Handle / Parent ID": "HN"})]
        actions, _, _ = run(rows, [])
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


if __name__ == "__main__":
    unittest.main()
