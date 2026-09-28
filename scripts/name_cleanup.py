#!/usr/bin/env python3
"""Propose readable `Product name`s for the Master Flooring Catalogue. READ ONLY.

    python3 scripts/name_cleanup.py --airtable <flattened records.json> --out <proposals.csv>

Albert, 2026-09-28: "the NAME field in airtable. Can we improve its human
readability?" ... "start all". One naming shape across the catalogue:

    wood / vinyl / laminate   Brand Collection Size — Colour (Grade)     (unchanged)
    tile                      Brand Collection — Colour — W x L (Finish)

What this changes, and only this:

- **Olympia** (3,028 records): the PDF merged supplier notes into the colour
  ("GREY AVAILABLE IN FINISH POLISHED", "AQUA WET AREAS EXCLUDING SWIMMING POOLS").
  The note is cut off and moved to `Salesperson notes`; product descriptors that
  name a different piece (Cove Base Inner, Round Edge Corner, Decor, Bookmatch A)
  stay. Sizes are actual measurements of metric tiles (23.62 = 60 cm): the name
  carries the nominal inch size a salesperson says out loud (24 x 24), and drops the
  thickness, which has its own field.
- **Brand first** where the name started with a collection: Olympia, CIF, Gracious
  ("Tiles —" was not a collection), JL Tile, Oakel.
- **ALL CAPS colours** become title case (IMPRESSIVE, Olympia, strays elsewhere).
- **Grandeur**: a width repeated in parentheses — `6" EWO — Barossa (6") (AB)`.

What it never does: touch `Colour / tone` (the LS handle is built from it), touch
Lightspeed, or change a name in a way that makes two records identical — every
record in a collision keeps its current name and is reported instead.
"""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

SEP = " — "

BRAND_PREFIX = {          # supplier -> the word(s) the name should start with
    "OLYMPIA TILE": "Olympia",
    "CIF DISTRIBUTORS": "CIF",
    "GRACIOUS": "Gracious",
    "JL TILE": "JL Tile",
    "OAKEL CITY": "Oakel",
}

# Words that start a supplier note inside an Olympia colour. Everything from the
# earliest one onward is a note, not part of the colour.
NOTE_START = re.compile(
    r"\s*,|\s*/\d|\s+X\d|\s*-?THICKNES|"
    r"\s+(?:AVAIL\w*|AVAIALBLE|ALSO\b|OTHER\b|MATCHING\b|COMPLEMENTARY\b|WET AREAS|"
    r"WALLS ONLY|WALL TILE\b|NOT (?:TO|FOR|SUITABLE)\b|SOLD\b|ROUGHER\b|USE \d|CAN BE USED|"
    r"RANDOM FINISH|\d+ DIFF|\d+ PIECE SET|\d+\s*`?\d*\s*in\s*X|\d+X\d+|"
    r"FINISH\b|POLISHED\b|POLISH\b|SEMI[- ]?POL\w*|SATIN\b|MATTE\b|MAT\b|HONED\b|POL\b|"
    r"STRUCTURED\b|SECURA\b|ANTI-SLIP|-MESHBACK|\d?D? ?DECOR (?:ALSO|NOT)|3D DECOR AVAILABLE|"
    r"MOSAICS AVAILABLE|AND (?=\d|FINISH|POLISHED|POL\b|WALL|MATCHING|OTHER|MOSAICS|SECURA))",
    re.I)

ABBREV = {"GRY": "Grey", "LT": "Light", "LT.": "Light", "DK": "Dark", "DRK": "Dark",
          "MED": "Medium", "BGE": "Beige", "BWN": "Brown", "BLK": "Black", "WHT": "White",
          "IVO": "Ivory", "TPE": "Taupe", "DGR": "Dark Grey"}
NO_TITLE_CASE = {"CIF DISTRIBUTORS"}
ACRONYMS = {"EVA", "IXPE", "IPES", "SPC", "WPC", "LVT", "LVP", "PVC", "HDF", "MDF", "EIR"}
LOWER = {"and", "or", "of", "di", "de", "del", "della", "la", "le", "in", "with", "w/"}


def smart_title(text):
    """GREY (LT GREY) -> Grey (Light Grey); keeps codes with digits (EUT-14, 3D)."""
    def word(w, first):
        core = w.strip("()")
        pre, post = w[:len(w) - len(w.lstrip("("))], w[len(w.rstrip(")")):]
        up = core.upper()
        if re.fullmatch(r"[A-Z]{1,3}(?:-[A-Z]{1,3}){2,}", core):     # a code: MK-AG-GL, RE-REX-CB
            out = core
        elif up in ABBREV:
            out = ABBREV[up]
        elif any(ch.isdigit() for ch in core):
            out = core.upper()
        elif core.lower() in LOWER and not first:
            out = core.lower()
        else:
            out = "-".join("/".join(p[:1].upper() + p[1:].lower() for p in part.split("/"))
                           for part in core.split("-"))
        return pre + out + post
    words = text.split()
    return " ".join(word(w, i == 0) for i, w in enumerate(words))


def is_shouting(text):
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.8


def split_note(colour):
    """(colour, note) — the note is the supplier text merged into the colour."""
    m = NOTE_START.search(colour)
    if not m or m.start() == 0:
        return colour.strip(" :-,"), ""
    return colour[:m.start()].strip(" :-,"), colour[m.start():].strip(" ,:-")


def nominal(inches):
    """Actual size of a metric tile -> the nominal inches people say.

    23.62 (60 cm) -> 24; 47.24 (120 cm) -> 48; 29.13 (74 cm, sold as 75) -> 30;
    58.27 (148 cm, sold as 150) -> 60; 11.97 (30.4 cm) -> 12. A size that is
    already whole or a quarter inch (a North American tile) is kept: 4.25 -> 4-1/4.
    """
    x = float(inches)
    if abs(x - round(x)) <= 0.05:
        return str(round(x))
    cm = x * 2.54
    step = 5 if cm >= 40 else 2.5
    if abs(cm - round(cm / step) * step) <= 0.4:          # a metric tile: 60 cm, 120 cm
        return str(round(round(cm / step) * step / 2.5))
    for frac, label in ((0.25, "1/4"), (0.5, "1/2"), (0.75, "3/4")):
        if x < 24 and abs(x - int(x) - frac) <= 0.02:
            return f"{int(x)}-{label}" if int(x) else label
    return str(round(round(cm / step) * step / 2.5))


def nominal_size(text):
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    if len(nums) < 2 or not re.fullmatch(r"[\d.\sx]+", text.strip()):
        return None
    return f"{nominal(nums[0])} x {nominal(nums[1])}"


def olympia(name, notes):
    parts = name.split(SEP)
    if len(parts) != 3:
        return None, ""
    collection, colour_finish, size = parts
    m = re.match(r"(.*?)\s*\(([^()]*)\)\s*$", colour_finish)
    colour, finish = (m.group(1), m.group(2)) if m else (colour_finish, "")
    colour, note = split_note(colour)
    size_n = nominal_size(size) or size
    new = f"{BRAND_PREFIX['OLYMPIA TILE']} {collection}{SEP}{smart_title(colour)}{SEP}{size_n}"
    if finish:
        new += f" ({finish})"
    if note and note.lower() in (notes or "").lower():
        note = ""
    return new, note


def generic(supplier, name):
    new = name
    prefix = BRAND_PREFIX.get(supplier)
    if supplier == "GRACIOUS" and new.startswith("Tiles" + SEP):
        new = "Gracious" + SEP + new[len("Tiles" + SEP):]
    elif prefix and not new.lower().startswith(prefix.lower()):
        new = f"{prefix} {new}"
    if supplier == "IMPRESSIVE" and new.startswith("IMPRESSIVE "):
        new = "Impressive " + new[len("IMPRESSIVE "):]
    # ALL CAPS colour segment(s) -> title case; parentheses (grade/specs) untouched.
    # Never for CIF: its colours are already mixed case, so an all-caps segment there
    # is a supplier code (FAOS, MK-AG-GL) — run 1 of 2026-09-28 lowercased 14 of them.
    segs = new.split(SEP)
    for i in range(1 if supplier not in NO_TITLE_CASE else len(segs), len(segs)):
        head, paren = re.match(r"([^(]*)(.*)", segs[i]).groups()
        if is_shouting(head) and not re.search(r"\d", head) \
                and head.strip().upper() not in ACRONYMS:
            segs[i] = smart_title(head.strip()) + (" " + paren if paren else "")
    new = SEP.join(segs)
    # Grandeur: `6" EWO — Barossa (6") (AB)` -> drop the repeated width
    m = re.search(r'\s\((\d+(?:\.\d+)?")\)', new)
    if m and m.group(1) in new[:m.start()]:
        new = new[:m.start()] + new[m.end():]
    return new


def propose(records):
    out = []
    for r in records:
        name = (r.get("Product name") or "").strip()
        supplier = r.get("Supplier") or ""
        if not name:
            continue
        note = ""
        if supplier == "OLYMPIA TILE":
            new, note = olympia(name, r.get("Salesperson notes"))
            new = new or name
        else:
            new = generic(supplier, name)
        if new != name or note:
            out.append({"id": r["id"], "sku": r.get("SKU"), "supplier": supplier,
                        "old_name": name, "new_name": new, "note_moved": note,
                        "salesperson_notes": r.get("Salesperson notes") or ""})
    # Never MERGE two names: if a new name would be shared by records whose current
    # names differ, every one of them keeps its current name. Records that already
    # share one name today (Olympia .VR / .RD stock-code pairs) are not made worse.
    old = {r["id"]: (r.get("Product name") or "").strip() for r in records}
    final = dict(old)
    for p in out:
        final[p["id"]] = p["new_name"]
    olds_by_new = defaultdict(set)
    for rid, new in final.items():
        olds_by_new[new.lower()].add(old[rid].lower())
    for p in out:
        merged = len(olds_by_new[p["new_name"].lower()]) > 1
        p["status"] = ("collision_kept_old" if merged
                       else "rename" if p["new_name"] != p["old_name"] else "note_only")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--airtable", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    records = json.loads(args.airtable.read_text())
    records = records.get("records", records) if isinstance(records, dict) else records
    rows = propose(records)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cols = ["status", "supplier", "sku", "old_name", "new_name", "note_moved", "id"]
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda p: (p["status"], p["supplier"], p["old_name"])))
    by = defaultdict(Counter)
    for p in rows:
        by[p["supplier"]][p["status"]] += 1
    print(args.out)
    for s, c in sorted(by.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  {s:22} {dict(c)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
