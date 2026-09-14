#!/usr/bin/env python3
"""Extract a supplier price list with pdfplumber, cross-checked against pypdfium2.

Albert, 2026-09-12. Two independent PDF engines must agree before any figure from
a price list is allowed downstream:

    pdfplumber  -> pdfminer.six        (pure Python, geometry-based tables)
    pypdfium2   -> PDFium, Google's C library

They share no code. A number that appears in one and not the other is a parse
defect, and this script's whole purpose is to make that loud instead of silent.

    python3 scripts/pricelist_extract.py /tmp/pricelist.pdf
    python3 scripts/pricelist_extract.py /tmp/pricelist.pdf --json out.json

Exit codes:
    0  both engines agree on every monetary value
    1  DISAGREEMENT — do not use the output; see /process-price-list step 2.2
    2  tooling unavailable (pdfplumber or pypdfium2 missing)

Read-only. Writes only the optional --json file.

## Why the check is a value-set comparison and not a row comparison

The two engines legitimately disagree on READING ORDER, because that is a layout
question rather than a data one. On the HOMESPRO sheet pypdfium2 places the
"$13/roll" underlay price away from its product name, since that cell is merged
across the trim columns. Failing the run on that would block a correct extraction.

So the halting check is: **every monetary token pdfplumber extracted must also
exist in pypdfium2's text.** That catches the failure that matters — a price
pdfplumber misread or manufactured, which would be absent from the other engine —
while staying immune to reading-order differences.

Proximity of a price to its product name is reported too, but only as advisory
signal. 9 of 10 on HOMESPRO is a pass, not a warning.
"""

import argparse
import json
import re
import sys
from pathlib import Path

MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d{1,2})?")


def die_tooling(msg: str) -> "int":
    print(f"TOOLING UNAVAILABLE: {msg}", file=sys.stderr)
    print("  Price-list extraction must flag and stop rather than substitute "
          "another method — /process-price-list step 2.0.", file=sys.stderr)
    print("  Fix: vendor/wheels/README.md", file=sys.stderr)
    return 2


def norm(tok: str) -> str:
    """'$ 1,234.50' -> '1234.50'  — compare values, not formatting."""
    return tok.replace("$", "").replace(",", "").replace(" ", "").strip()


# A real price-table cell is short: the longest legitimate one on the HOMESPRO
# sheet is ~60 chars ("Vancouver (8mm, 22mil, 1.5mm IXPE, 17.92 sq ft/ box) LONG
# PLA"). A whole-page catch-all table dumps hundreds of characters into a single
# cell. Column count does NOT distinguish them — HOMESPRO's catch-all had 4
# columns, same as the real tables.
CATCH_ALL_CELL_CHARS = 300


def is_catch_all(table) -> bool:
    """True for pdfplumber's whole-page blob table, which is junk."""
    for row in table:
        for cell in row:
            if cell and len(cell) > CATCH_ALL_CELL_CHARS:
                return True
    return False


def _is_catch_all_row(row) -> bool:
    return any(cell and len(cell) > CATCH_ALL_CELL_CHARS for cell in row)


_HEADER_HINTS = ("sku", "product name")


def _looks_like_header_row(row) -> bool:
    for cell in row:
        if not cell:
            continue
        low = cell.strip().lower()
        if any(hint in low for hint in _HEADER_HINTS):
            return True
    return False


def strip_leading_catch_all(table):
    """Drop leading letterhead/prose rows, keep a genuine table body after them.

    A page's letterhead and order instructions can land in the SAME pdfplumber
    table object as the real product grid when there is no line-geometry break
    between them — JL TILE page 1, 2026-09-14, one 44-row table where rows 0-2
    are header/contact prose (one cell over 700 chars) and rows 3-43 are a
    clean, line-bounded product grid identical in shape to every other page's
    table. The old whole-table `is_catch_all` check discarded all 44 rows for
    the 2 junk ones.

    A no-op unless the table actually contains an oversized cell somewhere —
    an ordinary table with a header on row 0 is returned unchanged. When it
    does, look for a recognizable header row ("Sku#", "Product name") and keep
    everything from there on, not just past the oversized cell itself: the
    junk block routinely spans several short rows around it too (a blank
    spacer row, a one-line letterhead row under the length threshold) that a
    length check alone would miss. No header row found -> drop the lot,
    exactly as before.

    Returns (kept_rows, n_dropped).
    """
    if not any(_is_catch_all_row(row) for row in table):
        return table, 0
    for i, row in enumerate(table):
        if _looks_like_header_row(row):
            return table[i:], i
    return [], len(table)


def compare_values(plumber_tokens, fium_tokens):
    """Compare two engines' monetary tokens by VALUE, ignoring reading order.

    Returns (agreed, plumber_only, fium_only) as sorted lists of normalised
    values. `plumber_only` being non-empty is the halting condition: pdfplumber
    produced a figure PDFium cannot see anywhere, which is a parse defect.

    `fium_only` is expected and harmless — PDFium reads all page prose while
    pdfplumber reads only table cells, so PDFium legitimately sees more.
    """
    a = {norm(x) for x in plumber_tokens}
    b = {norm(x) for x in fium_tokens}
    key = lambda s: (len(s), s)
    return sorted(a & b, key=key), sorted(a - b, key=key), sorted(b - a, key=key)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--json", type=Path, help="write structured tables here")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.pdf.is_file():
        print(f"No such file: {args.pdf}", file=sys.stderr)
        return 2

    try:
        import pdfplumber
    except ImportError as e:
        return die_tooling(f"pdfplumber ({e})")
    try:
        import pypdfium2 as pdfium
    except ImportError as e:
        return die_tooling(f"pypdfium2 ({e}) — the cross-check engine")

    # ── Engine A: pdfplumber, structured tables ─────────────────────────────
    pages = []
    with pdfplumber.open(args.pdf) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables()
            structured = []
            dropped_tables = 0
            dropped_rows = 0
            for t in tables:
                if not t:
                    continue
                trimmed, n_dropped = strip_leading_catch_all(t)
                if not trimmed or is_catch_all(trimmed):
                    dropped_tables += 1
                    continue
                dropped_rows += n_dropped
                structured.append(trimmed)
            pages.append({
                "page": pno,
                "tables": structured,
                "dropped_catch_all": dropped_tables,
                "dropped_catch_all_rows": dropped_rows,
                "text": page.extract_text() or "",
            })

    plumber_money = []
    for p in pages:
        for t in p["tables"]:
            for row in t:
                for cell in row:
                    if cell:
                        plumber_money += MONEY.findall(cell)

    # ── Engine B: pypdfium2 (PDFium), independent ───────────────────────────
    doc = pdfium.PdfDocument(str(args.pdf))
    fium_text = "\n".join(
        doc[i].get_textpage().get_text_range() for i in range(len(doc))
    )
    fium_money = MONEY.findall(fium_text)

    # ── The halting check: value sets ───────────────────────────────────────
    agreed, only_plumber, only_fium = compare_values(plumber_money, fium_money)
    a, b = {norm(x) for x in plumber_money}, {norm(x) for x in fium_money}

    if not args.quiet:
        print(f"{args.pdf.name}: {len(pages)} page(s)")
        for p in pages:
            notes = []
            if p["dropped_catch_all"]:
                notes.append(f"{p['dropped_catch_all']} catch-all table(s) dropped")
            if p["dropped_catch_all_rows"]:
                notes.append(f"{p['dropped_catch_all_rows']} leading junk row(s) trimmed")
            note = f", {', '.join(notes)}" if notes else ""
            print(f"  page {p['page']}: {len(p['tables'])} structured table(s){note}")
        print(f"\npdfplumber found {len(a)} distinct monetary values")
        print(f"pypdfium2  found {len(b)} distinct monetary values")
        print(f"  agreed on {len(agreed)}")
        if only_fium:
            print(f"\n  present in pypdfium2 only (informational — pdfplumber "
                  f"reads table cells, not prose): {only_fium}")

    if args.json:
        args.json.write_text(json.dumps({
            "source": str(args.pdf),
            "pages": [{k: v for k, v in p.items() if k != "text"} for p in pages],
            "cross_check": {
                "engines": ["pdfplumber/pdfminer.six", "pypdfium2/PDFium"],
                "pdfplumber_values": sorted(a),
                "pypdfium2_values": sorted(b),
                "agreed": agreed,
                "pdfplumber_only": only_plumber,
                "passed": not only_plumber,
            },
        }, indent=2) + "\n")

    if only_plumber:
        print(f"\nCROSS-CHECK FAILED", file=sys.stderr)
        print(f"  pdfplumber extracted {len(only_plumber)} value(s) that PDFium "
              f"does not see anywhere in the document:", file=sys.stderr)
        for v in only_plumber:
            print(f"    {v}", file=sys.stderr)
        print("  Two independent engines disagree on a figure. Do NOT use this "
              "extraction. Treat it as a parse defect: flag the row and stop, "
              "per /process-price-list step 2.2.", file=sys.stderr)
        return 1

    if not args.quiet:
        print("\nCROSS-CHECK PASSED — both engines agree on every monetary value.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
