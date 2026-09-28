"""Product name clean-up (Albert, 2026-09-28: 'Can we improve its human readability?')."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import name_cleanup as nc  # noqa: E402


def rec(rid, supplier, name, notes=None):
    return {"id": rid, "Supplier": supplier, "Product name": name, "Salesperson notes": notes}


class TestNominalSize(unittest.TestCase):
    def test_metric_tiles_read_as_the_size_people_say(self):
        for actual, said in (("23.62", "24"), ("47.24", "48"), ("11.81", "12"), ("29.13", "30"),
                             ("58.27", "60"), ("94.49", "96"), ("15.75", "16"), ("3.94", "4"),
                             ("47.76", "48")):
            self.assertEqual(nc.nominal(actual), said, actual)

    def test_inch_tiles_are_kept(self):
        self.assertEqual(nc.nominal("12.01"), "12")
        self.assertEqual(nc.nominal("4.25"), "4-1/4")

    def test_the_size_comes_from_olympias_stock_code(self):
        self.assertEqual(nc.nominal_size("23.62 x 47.24 x 0.35", "MC.AP.LIB.2448.MT"), "24 x 48")
        self.assertEqual(nc.nominal_size("64.17 x 127.56 x 0.47", "FD.IN.FDB.64X128.PL"), "64 x 128")
        self.assertEqual(nc.nominal_size("2.36 x 9.84 x 0.39", "CX.FC.BLK.2.4X10.GL"), "2.4 x 10")

    def test_no_agreeing_code_keeps_the_measured_size(self):
        """Second pass, 2026-09-28: 110.24 had become 112, corner pieces 0 x 0."""
        self.assertEqual(nc.nominal_size("110.24 x 55.12 x 0.24", "OV.PS.XXX.SLAB"), "110.24 x 55.12")
        self.assertEqual(nc.nominal_size("12.99 x 12.99", "GE.CE.GRY.0202"), "12.99 x 12.99")


class TestOlympia(unittest.TestCase):
    def test_note_leaves_the_colour_and_descriptors_stay(self):
        new, note = nc.olympia("Muse — GREY AVAILABLE IN FINISH POLISHED (Matte) — 23.62 x 23.62 x 0.41", "", "MU.GRY.2424.MT")
        self.assertEqual(new, "Olympia Muse — Grey — 24 x 24 (Matte)")
        self.assertEqual(note, "AVAILABLE IN FINISH POLISHED")
        new, _ = nc.olympia("Quarry — ARCTIC WHITE COVE BASE INNER (Matte) — 5.91 x 5.91", "", "QT.ARW.0606.CBI")
        self.assertEqual(new, "Olympia Quarry — Arctic White Cove Base Inner — 6 x 6 (Matte)")

    def test_abbreviations_are_spelled_out(self):
        new, _ = nc.olympia("Overlay — DOLPHIN (LT GRY) (Matte) — 11.81 x 23.62", "", "OV.DLP.1224.MT")
        self.assertEqual(new, "Olympia Overlay — Dolphin (Light Grey) — 12 x 24 (Matte)")

    def test_a_note_already_in_salesperson_notes_is_not_repeated(self):
        _, note = nc.olympia("Galaxy — GREY OTHER SIZES AVAILABLE (Matte) — 11.81 x 23.62",
                             "OTHER SIZES AVAILABLE; (Rectified)")
        self.assertEqual(note, "")


class TestGeneric(unittest.TestCase):
    def test_brand_first_and_title_case(self):
        self.assertEqual(nc.generic("GRACIOUS", "Tiles — EUT-14 — 24 x 24"), "Gracious — EUT-14 — 24 x 24")
        self.assertEqual(nc.generic("OAKEL CITY", "European Oak 3-Ply 7 Series — Monza (Select)"),
                         "Oakel European Oak 3-Ply 7 Series — Monza (Select)")
        self.assertEqual(nc.generic("IMPRESSIVE", "IMPRESSIVE Classic Oak — CASTLE (3-1/4, Select & Better)"),
                         "Impressive Classic Oak — Castle (3-1/4, Select & Better)")

    def test_acronyms_and_grades_are_left_alone(self):
        self.assertEqual(nc.generic("SIMBA", "Simba Underlayment — IXPE (3.0mm)"),
                         "Simba Underlayment — IXPE (3.0mm)")

    def test_supplier_codes_keep_their_capitals(self):
        """Run 1 (2026-09-28) wrote `Faos` and `Mk-Ag-Gl` over CIF codes."""
        self.assertEqual(nc.generic("CIF DISTRIBUTORS", "Stainless Mosaic — FAOS — Random"),
                         "CIF Stainless Mosaic — FAOS — Random")
        self.assertEqual(nc.smart_title("BLACK RE-REX-CB"), "Black RE-REX-CB")

    def test_grandeur_repeated_width_is_dropped(self):
        self.assertEqual(nc.generic("GRANDEUR", 'Grandeur 6" EWO — Barossa (6") (AB)'),
                         'Grandeur 6" EWO — Barossa (AB)')


class TestCollisions(unittest.TestCase):
    def test_a_rename_never_merges_two_different_names(self):
        rows = nc.propose([
            rec("r1", "OLYMPIA TILE", "Regal — BROWN (Matte) — 11.69 x 23.62"),
            rec("r2", "OLYMPIA TILE", "Regal — BROWN POLISHED AND FINISH AVAILABLE FLAMED (Matte) — 11.69 x 23.62")])
        self.assertEqual({p["status"] for p in rows}, {"collision_kept_old"})

    def test_names_already_identical_may_still_be_cleaned(self):
        rows = nc.propose([
            {**rec("r1", "OLYMPIA TILE", "Acanto — ALMOND (Matte) — 3.94 x 15.75 x 0.31"), "SKU": "ES.AC.ALM.0416.VR"},
            {**rec("r2", "OLYMPIA TILE", "Acanto — ALMOND (Matte) — 3.94 x 15.75 x 0.31"), "SKU": "ES.AC.ALM.0416.RD"}])
        self.assertEqual({p["status"] for p in rows}, {"rename"})
        self.assertEqual(rows[0]["new_name"], "Olympia Acanto — Almond — 4 x 16 (Matte)")


if __name__ == "__main__":
    unittest.main()
