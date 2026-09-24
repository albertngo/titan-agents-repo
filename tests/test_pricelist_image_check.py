"""scripts/pricelist_image_check.py — the image path's two-reader check (2026-09-24, PL-170)."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("pic", REPO_ROOT / "scripts/pricelist_image_check.py")
pic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pic)


def item(x, y, text, conf=0.9):
    return {"box": [[x, y - 5], [x + 50, y - 5], [x + 50, y + 5], [x, y + 5]], "text": text, "conf": conf}


def page(*rows):
    """rows: (y, [cell texts]) -> fake OCR items laid out left to right."""
    out = [item(10, 20, "Baltic Home(Nature) Price List")]
    for y, cells in rows:
        out += [item(10 + 100 * i, y, c) for i, c in enumerate(cells)]
    return out


def run(items, rows):
    d = Path(tempfile.mkdtemp())
    (d / "t.json").write_text(json.dumps({"rows": rows}))
    code = pic.main([str(d / "img.jpg"), str(d / "t.json"), "--json", str(d / "r.json")],
                    ocr=lambda _: items)
    return code, json.loads((d / "r.json").read_text())


ROWS = [{"key": "HD-001", "money": ["3.48", "3.91"]},
        {"key": "HD-005", "money": ["3.49", "3.92"]}]


class TestImageCheck(unittest.TestCase):

    def test_both_readers_agree(self):
        code, rep = run(page((100, ["HD-001", "Oak", "19.43", "3.48", "3.91"]),
                             (120, ["HD-005", "Oak", "19.43", "3.49", "3.92"])), ROWS)
        self.assertEqual(0, code)
        self.assertEqual(2, rep["agree"])

    def test_a_misread_price_fails_that_row_only(self):
        """PL-170: OCR read HD-005's Tier 2 3.92 as 3.02."""
        code, rep = run(page((100, ["HD-001", "Oak", "19.43", "3.48", "3.91"]),
                             (120, ["HO-005", "Oak", "19.43", "3.49", "3.02"])), ROWS)
        self.assertEqual(1, code)
        self.assertEqual(["HD-005"], [p["key"] for p in rep["problems"]])
        self.assertEqual(["3.92"], rep["problems"][0]["missing_from_ocr"])

    def test_a_row_the_transcription_dropped_fails(self):
        code, rep = run(page((100, ["HD-001", "Oak", "3.48", "3.91"]),
                             (120, ["HD-005", "Oak", "3.49", "3.92"]),
                             (140, ["HD-006", "Oak", "3.48", "3.91"])), ROWS)
        self.assertEqual(1, code)
        self.assertEqual(1, len(rep["unclaimed_priced_lines"]))

    def test_a_code_inside_another_rows_description_is_not_a_match(self):
        """HD-008's description OCR'd as 'HD00,18', which folds to contain HD001."""
        code, rep = run(page((100, ["HD-008", "ENG Oak,HD00,18/2mm", "3.48", "3.91"]),
                             (120, ["HD-001", "Oak", "3.50", "3.99"])),
                        [{"key": "HD-008", "money": ["3.48", "3.91"]},
                         {"key": "HD-001", "money": ["3.50", "3.99"]}])
        self.assertEqual(0, code)

    def test_non_price_decimals_on_the_line_do_not_fail_it(self):
        code, _ = run(page((100, ["HD-001", "19.43", "50", "3.48", "3.91"])), ROWS[:1])
        self.assertEqual(0, code)

    def test_no_ocr_engine_stops(self):
        d = Path(tempfile.mkdtemp())
        (d / "t.json").write_text(json.dumps({"rows": ROWS}))
        self.assertEqual(2, pic.main([str(d / "i.jpg"), str(d / "t.json")], ocr=lambda _: None))


if __name__ == "__main__":
    unittest.main()
