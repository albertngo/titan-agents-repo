#!/usr/bin/env python3
"""Tests for the post-sync CSV export.

    python3 -m unittest discover -s tests -v

Albert, 2026-09-23: keep both CSVs on every run, the Airtable one carrying each
SKU's Lightspeed UUID and reflecting live Airtable for the items the run touched.
What these tests hold: live wins wherever a record exists (an emptied cell
included), a SKU that is not live keeps its extracted row so a re-run still sees
it, and the exported file is a fixed point for the reconciler: fed back in against
the same live state, it plans nothing.
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


def load(name):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / f"scripts/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ce = load("catalog_export")
cr = load("catalog_reconcile")

LEAVES = json.loads((REPO_ROOT / "platform-settings/lightspeed.json").read_text()
                    )["product_categories"]["leaves"]

HEADER = ["SKU", "Product name", "Supplier", "Lightspeed ID", "Cost/unit",
          "Retail price/unit", "Stock status", "Promo cost ($/sf)", "Active",
          "Width (in)", "MatchedRecId", "MatchStatus"]

SCHEMA = {"tables": [{"id": "tblX", "fields": [
    {"id": "fSKU", "name": "SKU", "type": "singleLineText"},
    {"id": "fName", "name": "Product name", "type": "singleLineText"},
    {"id": "fSup", "name": "Supplier", "type": "singleSelect"},
    {"id": "fLS", "name": "Lightspeed ID", "type": "singleLineText"},
    {"id": "fCost", "name": "Cost/unit", "type": "currency"},
    {"id": "fRet", "name": "Retail price/unit", "type": "currency"},
    {"id": "fStock", "name": "Stock status", "type": "singleSelect"},
    {"id": "fPromo", "name": "Promo cost ($/sf)", "type": "currency"},
    {"id": "fActive", "name": "Active", "type": "checkbox"},
    {"id": "fW", "name": "Width (in)", "type": "number"},
]}]}


def upload_row(**kw):
    base = {h: "" for h in HEADER}
    base.update({"SKU": "LAM-TEST-0001", "Product name": "As extracted",
                 "Supplier": "TEST", "Cost/unit": "1.19", "Retail price/unit": "2.19",
                 "Stock status": "Clearance", "Promo cost ($/sf)": "0.99",
                 "Active": "TRUE", "Width (in)": "7.71", "MatchStatus": "new"})
    base.update(kw)
    return base


def live_record(rec_id="recA", **cells):
    base = {"fSKU": "LAM-TEST-0001", "fName": "As live", "fSup": {"id": "s", "name": "TEST"},
            "fCost": 1.2, "fRet": 2.2, "fStock": {"id": "c", "name": "Clearance"},
            "fActive": True, "fW": 7.71}
    base.update(cells)
    return {"id": rec_id, "cellValuesByFieldId": {k: v for k, v in base.items() if v is not None}}


def ls_product(**kw):
    base = {"id": "uuid-1", "sku": "LAM-TEST-0001", "handle": "LAMTEST1",
            "name": "TESTLAM - As live | 7.71\"", "supply_price": 1.2,
            "price_excluding_tax": 2.2, "active": True, "variant_options": [],
            "supplier_name": "TEST", "category": "LAMINATE"}
    base.update(kw)
    return base


def read_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def read_header(path):
    with open(path, newline="") as f:
        return next(csv.reader(f))


class Run:
    """Writes the inputs to a temp dir, runs main(), reads both CSVs back."""

    def __init__(self, rows, records, products, ls_rows=None, ls_header=None):
        self.dir = Path(tempfile.mkdtemp())
        self.upload = self.dir / "t_airtable_upload.csv"
        self.ls = self.dir / "t_ls_upload.csv"
        with open(self.upload, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()
            w.writerows(rows)
        if ls_rows is not None:
            with open(self.ls, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=ls_header or ce.DEFAULT_LS_HEADER)
                w.writeheader()
                w.writerows(ls_rows)
        (self.dir / "live.json").write_text(json.dumps({"records": records}))
        (self.dir / "schema.json").write_text(json.dumps(SCHEMA))
        (self.dir / "ls.json").write_text(json.dumps({"products": products}))
        ce.main(["--upload", str(self.upload), "--ls-upload", str(self.ls),
                 "--airtable-live", str(self.dir / "live.json"),
                 "--schema", str(self.dir / "schema.json"),
                 "--lightspeed", str(self.dir / "ls.json")])
        self.at = {r["SKU"]: r for r in read_rows(self.upload)}
        self.ls_out = {r["sku"]: r for r in read_rows(self.ls)}


class TestAirtableSide(unittest.TestCase):

    def test_live_record_replaces_the_extracted_row(self):
        out = Run([upload_row()], [live_record()], [ls_product()]).at["LAM-TEST-0001"]
        self.assertEqual("As live", out["Product name"])
        self.assertEqual("1.20", out["Cost/unit"])
        self.assertEqual("Clearance", out["Stock status"])
        self.assertEqual("TRUE", out["Active"])
        self.assertEqual("7.71", out["Width (in)"])
        self.assertEqual("recA", out["MatchedRecId"])
        self.assertEqual("matched", out["MatchStatus"], "a live record is matched now")

    def test_a_cell_empty_in_airtable_is_empty_in_the_file(self):
        # Airtable omits empty cells; the extracted 0.99 promo must not survive.
        out = Run([upload_row()], [live_record()], [ls_product()]).at["LAM-TEST-0001"]
        self.assertEqual("", out["Promo cost ($/sf)"])

    def test_the_lightspeed_uuid_comes_from_airtable_when_it_holds_one(self):
        out = Run([upload_row()], [live_record(fLS="uuid-in-airtable")],
                  [ls_product()]).at["LAM-TEST-0001"]
        self.assertEqual("uuid-in-airtable", out["Lightspeed ID"])

    def test_a_missing_backfill_is_filled_from_the_pos(self):
        out = Run([upload_row()], [live_record()], [ls_product()]).at["LAM-TEST-0001"]
        self.assertEqual("uuid-1", out["Lightspeed ID"])

    def test_a_sku_airtable_does_not_hold_keeps_its_extracted_row(self):
        held = upload_row(SKU="LAM-TEST-0002")
        out = Run([held], [live_record()], [ls_product(sku="LAM-TEST-0002", id="uuid-2")]
                  ).at["LAM-TEST-0002"]
        self.assertEqual("As extracted", out["Product name"])
        self.assertEqual("0.99", out["Promo cost ($/sf)"])
        self.assertEqual("new", out["MatchStatus"], "still a create for the next run")
        self.assertEqual("uuid-2", out["Lightspeed ID"], "but it carries the POS uuid")

    def test_row_order_is_preserved(self):
        rows = [upload_row(SKU=f"LAM-TEST-000{i}") for i in (3, 1, 2)]
        run = Run(rows, [], [])
        self.assertEqual(["LAM-TEST-0003", "LAM-TEST-0001", "LAM-TEST-0002"], list(run.at))

    def test_a_schema_without_names_is_refused(self):
        path = Path(tempfile.mkdtemp()) / "s.json"
        path.write_text(json.dumps({"tables": [{"tableId": "t", "fields": [{"id": "f", "type": "x"}]}]}))
        with self.assertRaises(SystemExit):
            ce.load_schema(path)


class TestLightspeedSide(unittest.TestCase):

    def test_a_live_product_is_rendered_from_the_pos(self):
        out = Run([upload_row()], [live_record()], [ls_product()]).ls_out["LAM-TEST-0001"]
        self.assertEqual("uuid-1", out["id"])
        self.assertEqual("1.20", out["supply_price"])
        self.assertEqual("2.20", out["retail_price"])
        self.assertEqual("LAMINATE", out["product_category"])
        self.assertEqual("1", out["active"])

    def test_columns_the_pull_lacks_come_from_the_runs_own_row(self):
        mine = {h: "" for h in ce.DEFAULT_LS_HEADER}
        mine.update({"sku": "LAM-TEST-0001", "description": "from the run",
                     "brand_name": "BRAND", "supply_price": "9.99"})
        out = Run([upload_row()], [live_record()], [ls_product()],
                  ls_rows=[mine]).ls_out["LAM-TEST-0001"]
        self.assertEqual("from the run", out["description"])
        self.assertEqual("BRAND", out["brand_name"])
        self.assertEqual("1.20", out["supply_price"], "live price wins")

    def test_a_product_under_a_different_pos_sku_is_found_by_its_uuid(self):
        """JL Tile, PL-372: Airtable TIL-JLTI-36M0633H is Lightspeed 36M0633H."""
        rec = live_record(fSKU="TIL-JLTI-36M0633H", fLS="uuid-9")
        mine = {h: "" for h in ce.DEFAULT_LS_HEADER}
        mine.update({"id": "uuid-9", "sku": "TIL-JLTI-36M0633H", "description": "from the run"})
        out = Run([upload_row(SKU="TIL-JLTI-36M0633H", **{"Lightspeed ID": "uuid-9"})], [rec],
                  [ls_product(id="uuid-9", sku="36M0633H", supply_price=2.3,
                              price_excluding_tax=4.3)], ls_rows=[mine]).ls_out
        self.assertNotIn("TIL-JLTI-36M0633H", out, "the POS sku is what the POS holds")
        row = out["36M0633H"]
        self.assertEqual(("uuid-9", "2.30", "4.30"),
                         (row["id"], row["supply_price"], row["retail_price"]))
        self.assertEqual("from the run", row["description"])

    def test_not_on_the_pos_keeps_its_row_or_is_left_out(self):
        mine = {h: "" for h in ce.DEFAULT_LS_HEADER}
        mine.update({"sku": "LAM-TEST-0002", "name": "to create"})
        rows = [upload_row(), upload_row(SKU="LAM-TEST-0002"), upload_row(SKU="LAM-TEST-0003")]
        out = Run(rows, [], [], ls_rows=[mine]).ls_out
        self.assertEqual("to create", out["LAM-TEST-0002"]["name"])
        self.assertNotIn("LAM-TEST-0003", out)
        self.assertNotIn("LAM-TEST-0001", out)

    def test_a_run_with_no_ls_file_gets_one(self):
        run = Run([upload_row()], [live_record()], [ls_product()])
        self.assertTrue(run.ls.exists())
        header = read_header(run.ls)
        self.assertEqual(ce.DEFAULT_LS_HEADER, header)

    def test_the_runs_own_header_is_kept(self):
        header = ["id", "handle", "sku", "name", "supply_price", "retail_price", "custom_col"]
        run = Run([upload_row()], [live_record()], [ls_product()],
                  ls_rows=[{"sku": "LAM-TEST-0001", "custom_col": "keep"}], ls_header=header)
        self.assertEqual(header, read_header(run.ls))
        self.assertEqual("keep", run.ls_out["LAM-TEST-0001"]["custom_col"])


class TestCommittedFieldMap(unittest.TestCase):

    def test_it_names_every_column_a_real_upload_carries(self):
        schema = ce.load_schema(ce.DEFAULT_SCHEMA)
        names = {name for name, _ in schema.values()}
        header = read_header(REPO_ROOT / "ingest/2026-09-21/faw_airtable_upload_2026-09-21.csv")
        self.assertEqual([], [c for c in header if c not in names and c not in ce.HELPER_COLUMNS])

    def test_the_key_fields_sit_on_the_ids_the_registry_uses(self):
        schema = ce.load_schema(ce.DEFAULT_SCHEMA)
        dest = json.loads((REPO_ROOT / "platform-settings/airtable-destinations.json").read_text())
        table = dest["tables"]["master_flooring_catalogue"]
        self.assertEqual("SKU", schema[table["primary_field_id"]][0])
        for name, fid in table["fields"].items():
            self.assertEqual(name, schema[fid][0])


class TestFixedPoint(unittest.TestCase):
    """The exported file, fed back to the reconciler against the same live state,
    must plan nothing. If it planned something, the CSV would not be 'as live'."""

    def test_reconciling_the_export_is_a_no_op(self):
        run = Run([upload_row()], [live_record(fLS="uuid-1")], [ls_product()])
        rows = read_rows(run.upload)
        existing = {"LAM-TEST-0001": {"SKU": "LAM-TEST-0001", "Product name": "As live",
                                      "Supplier SKU": None, "Category": None,
                                      "Cost/unit": 1.2, "Retail price/unit": 2.2,
                                      "Stock status": "Clearance", "Promo cost ($/sf)": None,
                                      "Promo end date": None, "Lightspeed ID": "uuid-1"}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"products": [ls_product()]}, fh)
        plan_actions, blocked, _ = cr.reconcile(rows, cr.load_lightspeed(fh.name), existing,
                                                "TEST", LEAVES)
        self.assertEqual([], blocked)
        self.assertEqual([], plan_actions)


if __name__ == "__main__":
    unittest.main()
