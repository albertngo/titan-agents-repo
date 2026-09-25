#!/usr/bin/env python3
"""Cross-check a price list that arrived as an IMAGE against an independent OCR read.

Albert, 2026-09-24 (PL-170, Baltic Homes, a phone photo of a printed list):
"jpg (or any image file) should be allowed. BUT it should read the context of the
image, and decide if it is flooring. And if so, process just as pdfplumber does."

A PDF gets two engines that share no code (pdfplumber vs PDFium, see
scripts/pricelist_extract.py). An image gets the same shape of guarantee:

    reader 1  the model's structured transcription of the image (JSON, below)
    reader 2  RapidOCR (PaddleOCR models on ONNX Runtime), run here

Neither is trusted alone. Every price in the transcription must be read the same
way by OCR, ON THE SAME ROW, or that row is not usable.

    python3 scripts/pricelist_image_check.py photo.jpg transcription.json [--json report.json]

transcription.json:
    {"rows": [{"key": "HD-001", "money": ["3.48", "3.91"]}, ...]}
`key` is the row's printed code (or any text unique to the row) and is how the
row is found in the OCR output; `money` is every price printed on that row, as
printed.

Exit codes:
    0  every row located, every price agrees, no priced OCR line left unclaimed
    1  at least one row disagrees or cannot be located, or OCR saw a priced line
       the transcription does not have (a dropped row). Report says which.
    2  OCR engine unavailable (pip install rapidocr_onnxruntime)

## Why per row and not a value set

The PDF check compares value sets because two PDF engines differ on reading
order, not on characters. OCR on a photo is the opposite: rows are geometrically
obvious but characters are not (3.92 read as 3.02). A value-set check would let a
misread hide behind the same number on another row, so this one pins every value
to its row. The cost is that OCR noise fails individual rows, and the procedure
answers that by holding the row (Ambiguous Pricing), never by picking a reader.
Upscaling the image did not help on PL-170 — it introduced four new misreads —
so this runs at the image's own resolution.

Read-only. Writes only the optional --json file.
"""

import argparse
import difflib
import json
import re
import sys
from collections import Counter

MONEY = re.compile(r"(?<![\d.])\d{1,4}\.\d{2}(?![\d])")


def alnum(s):
    """Upper-case alphanumerics, with OCR's commonest letter/digit swaps folded."""
    s = re.sub(r"[^A-Za-z0-9]", "", s or "").upper()
    return s.translate(str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8"}))


def ocr_items(image_path):
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    result, _ = RapidOCR()(image_path)
    return [{"box": r[0], "text": r[1], "conf": float(r[2])} for r in (result or [])]


def group_lines(items):
    """Cluster OCR boxes into printed lines by vertical centre."""
    if not items:
        return []
    heights = sorted(abs(i["box"][2][1] - i["box"][0][1]) for i in items)
    tol = max(3.0, heights[len(heights) // 2] * 0.5)
    rows = []
    for it in sorted(items, key=lambda i: sum(p[1] for p in i["box"]) / 4):
        y = sum(p[1] for p in it["box"]) / 4
        if rows and abs(rows[-1]["y"] - y) <= tol:
            rows[-1]["items"].append(it)
        else:
            rows.append({"y": y, "items": [it]})
    lines = []
    for r in rows:
        cells = sorted(r["items"], key=lambda i: min(p[0] for p in i["box"]))
        text = " | ".join(c["text"] for c in cells)
        lines.append({"y": round(r["y"]), "text": text,
                      "money": MONEY.findall(text),
                      "min_conf": round(min(c["conf"] for c in cells), 2)})
    return lines


def locate(key, lines, start, window=4):
    """Index of the line holding this row, or None.

    Rows are matched in page order: the search starts after the previous row's
    line and looks a few lines ahead, scoring the key against the line's FIRST
    cell (the code column). Matching anywhere in the line is too loose — on
    PL-170 "HD00,18" in HD-008's description folds to text containing HD-001.
    """
    k = alnum(key)
    best, best_score = None, 0.0
    # Only priced lines are candidates: every transcribed row carries a price,
    # and the page header and section bands would otherwise eat the window.
    candidates = [i for i in range(start, len(lines)) if lines[i]["money"]][:window]
    for i in candidates:
        first = alnum(lines[i]["text"].split("|")[0])
        score = difflib.SequenceMatcher(None, k, first).ratio()
        if score > best_score:
            best, best_score = i, score
    return best if best_score >= 0.6 else None


def check(rows, lines):
    report = {"rows": [], "unclaimed_priced_lines": []}
    taken, start = set(), 0
    for row in rows:
        idx = locate(row["key"], lines, start)
        want = [f"{float(m):.2f}" for m in row["money"]]
        if idx is None:
            report["rows"].append({"key": row["key"], "status": "not_located", "transcribed": want})
            continue
        taken.add(idx)
        start = idx + 1
        got = [f"{float(m):.2f}" for m in lines[idx]["money"]]
        # Inclusion, not equality: a row also prints non-price decimals (19.43
        # sf/ctn) that the transcription need not list. Every transcribed price
        # must be on the OCR line; the OCR line may hold more.
        missing = Counter(want) - Counter(got)
        status = "agree" if not missing else "disagree"
        report["rows"].append({"key": row["key"], "status": status, "transcribed": want,
                               "ocr": got, "missing_from_ocr": sorted(missing.elements()),
                               "ocr_line": lines[idx]["text"]})
    for i, ln in enumerate(lines):
        if i not in taken and ln["money"]:
            report["unclaimed_priced_lines"].append(ln)
    report["agree"] = sum(r["status"] == "agree" for r in report["rows"])
    report["problems"] = [r for r in report["rows"] if r["status"] != "agree"]
    return report


def main(argv=None, ocr=ocr_items):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("image")
    ap.add_argument("transcription")
    ap.add_argument("--json", help="write the full report here")
    args = ap.parse_args(argv)

    items = ocr(args.image)
    if items is None:
        print("OCR engine unavailable: pip install rapidocr_onnxruntime. "
              "Per /process-price-list step 2.3, stop — never fall back to one reader.",
              file=sys.stderr)
        return 2
    rows = json.load(open(args.transcription))["rows"]
    report = check(rows, group_lines(items))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=1, ensure_ascii=False)

    print(f"rows {len(rows)}  agree {report['agree']}  problems {len(report['problems'])}  "
          f"unclaimed priced OCR lines {len(report['unclaimed_priced_lines'])}")
    for p in report["problems"]:
        print(f"  {p['status']:12} {p['key']}: transcribed {p['transcribed']}  ocr {p.get('ocr')}")
    for ln in report["unclaimed_priced_lines"]:
        print(f"  unclaimed    y={ln['y']}: {ln['text']}")
    if report["problems"] or report["unclaimed_priced_lines"]:
        print("\nCROSS-CHECK FAILED for the rows above — hold them; never pick a reader.")
        return 1
    print("\nCROSS-CHECK PASSED — both readers agree on every price, row by row.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
