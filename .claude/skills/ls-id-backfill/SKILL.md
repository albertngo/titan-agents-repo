---
name: ls-id-backfill
description: "Backfill Lightspeed Retail X UUIDs into an Airtable upload file by matching against an LS product export. Use this skill AFTER uploading a batch of new products to Lightspeed, when LS has assigned UUIDs and the user wants to copy those UUIDs into their existing Airtable upload file before re-importing into Airtable. Triggers include: 'backfill LS IDs', 'copy Lightspeed UUIDs into Airtable', 'match LS export to Airtable file', 'get the LS IDs into my Airtable sheet', or any workflow where two files need to be merged — the Airtable upload file (with blank Lightspeed ID column) and the Lightspeed product export (with UUIDs filled in). This skill performs the matching, copies UUIDs over, and flags rows that fail to match. Output is always a .csv."
---

# Bert — Lightspeed ID Backfill Skill

Match products between an Airtable upload file and a Lightspeed product export, copy LS UUIDs into the Airtable file, and flag any rows that don't match cleanly.

## When to use this skill

The user has:
1. An **Airtable upload file** — the `.csv` produced by the ingest workflow: the 57 canonical columns from `bert-airtable-schema` plus helper columns (`MatchedRecId`, `MatchStatus`). The `Lightspeed ID` column is either blank (new products) or partially populated (mix of new and updates).
2. A **Lightspeed product export** — a CSV or XLSX with LS UUIDs in column 1 (`id`), SKUs, handles, prices, etc. Typically exported from LS after a product import completes. **This is the one file that may be .xlsx** — LS exports as a workbook. Read it with `openpyxl`; it is input only.

The user wants the LS UUIDs copied into the Airtable file so they can re-import into Airtable with the IDs already filled in.

Triggers include: "backfill LS IDs", "match my LS export to the Airtable file", "copy the Lightspeed UUIDs over", "get the LS IDs into Airtable".

**Matching is color-first, then confirmed by other details.** Titan Airtable SKUs and LS SKUs are different namespaces — don't try to match them directly. The match is driven by the **colour name**, then **confirmed** against `Collection`, `Species`, and spec details (width, thickness, cost, sf/box). A colour match with a confirming detail is accepted; conflicts are **flagged in the notes, not blocking** (cost and sf/box drift legitimately; species and collection conflicts are stronger signals). See Step 2 for the algorithm. This logic is supplier-agnostic — it works for any supplier's LS export, not just one brand.

**Code-only lines:** some collections have no colour name in LS (e.g. a row reading `... - SPC ()` whose only identifier is a numeric code like `601`). For these, bridge on the **numeric product code** (the `#NNN` token in the LS name and/or the numeric segment of the LS sku), and **require the collection to be compatible** so a shared code across collections can't cause a false match.

---

## Workflow

### Step 1 — Read both files

**Airtable upload file** — expect the 57 canonical columns from `bert-airtable-schema`, plus helper columns. Key columns:
- `SKU` (used only to derive product type via the 3-4 char prefix, e.g. `LAM-PLUX-0001` → `LAM`)
- `Product name`
- `LS Handle / Parent ID` — **the primary source for color extraction**
- `Collection`, `Product type`
- `Width (in)`, `Thickness (mm)`, `Cost ($/sf)`, `Box size (sf)` — secondary signals
- `Lightspeed ID` — target column where UUIDs get written

**Lightspeed export** — expect the 31-column LS schema from `ls-upload-instructions`. Key columns:
- `id` (the LS UUID — source)
- `sku`, `handle`, `name` — all three feed the color extractor
- `supply_price` — compared against Airtable Cost

If the column headers differ slightly from the expected schema (e.g. extra columns, reordered), still work with whatever is present — match by column name, not position.

### Step 2 — Color-token match algorithm

**Do NOT try to match on SKU directly.** Titan's Airtable SKUs (e.g. `LAM-PLUX-0001`, `ENG-WODN-0042`) and LS SKUs (e.g. `PUR.S.0.Ban.1`, `WOD.E.RO.Cash.6`) are different namespaces — they almost never align. The reliable bridge is the **colour name** that identifies the specific product variant, confirmed by collection/species/specs.

**Step 2a — Extract identity tokens from each side.**

From the LS export, for each row, collect:
- **Colour candidates** — parenthesized text in `name`, e.g. `(Banwell)`, `(Grand Marais)`, `(Cashmere)`, `(WHISPERING BREEZE)`. Normalize to alphanumeric-lowercase (`Grand Marais` → `grandmarais`). This is the primary identifier.
- **Numeric code candidates** — the `#NNN`/`#NNNN` token in `name` and any 3-4 digit numeric segment of `sku` (e.g. name `... | #601 | ...` → `601`; sku `WOD.705` → `705`; bare sku `1204` → `1204`). Used for code-only lines where the colour parens are empty (`SPC ()`).
- **Collection** — the section token in the LS name, typically the 2nd ` - `-delimited segment (e.g. `WODENG - ELITE - ...` → `elite`; `WODVIN - 9 Collection - ...` → `9collection`).
- **Species** — scan the LS name for a wood species (`red oak`, `white oak`, `walnut`, `hickory`, `maple`).

From the Airtable file, for each row, collect:
- **Colour** — the text after the last em-dash (` — `) in `Product name`, stripped of any trailing grade token (`AB`, `ABC`, `ABCD`, `EF`) and normalized. (Handle tail works too where the AT handle embeds the colour; the em-dash colour is more reliable across suppliers.)
- **Numeric code** — a leading `NNN`/`HNN`/`NNNN` token right after the em-dash (e.g. `... — 601`, `... — 101 Farmhouse`, `... — H01 ...` → strip leading letter → `01`/use as-is).
- **Collection** — the `Collection` column value, normalized.
- **Species** — the `Species` column value, normalized.

The brand/type prefix in LS names varies by supplier (`PUR…`, `WODVIN`/`WODENG`, etc.) — **do not hardcode it**. Parse colour from parens, collection from the delimited section, code from `#`/sku. The approach is the same regardless of supplier.

**Step 2b — Match LS against AT, then confirm.**

For each AT row, find LS candidates and classify the colour match:

| Match type | Condition | Example |
|---|---|---|
| Exact (colour) | LS colour equals the AT colour token | LS `cashmere` vs AT `cashmere` ✓ |
| Exact (near-spelling) | Edit distance ≤ 1 between LS colour and AT colour (both length ≥ 5) | LS `coronada` vs AT `coronado` ✓ |
| Exact (code bridge) | AT numeric code ∈ LS codes **AND** collection compatible | AT `601` / `6collection` vs LS `601` / `6collection` ✓ |
| Fuzzy | Substring / shared-prefix overlap between colour tokens (only when exact fails) | LS `gramar` vs AT `grandmarais` |

**Confirm every candidate** against collection, species, and the four specs (Step 3). Track `passes` (confirming details) and `conflicts` (contradicting details). Collection and species are stronger signals than cost/box; surface all conflicts in the note.

**Narrow candidates** before matching:
- Exclude LS rows whose name matches the moulding/accessory regex: `MOULDING|STAIR SET|RISER|NOSING|REDUCER|T-MOULD`.
- Optionally narrow by product family (laminate vs vinyl vs hardwood) using whatever family marker the supplier's LS name uses; if the marker is unknown, rely on colour + collection + specs to disambiguate rather than a hardcoded table.

**Step 2c — Decision rule.**

| Situation | Outcome |
|---|---|
| Exactly 1 exact/code candidate | `OK` — accept. Note any conflicts as warnings. |
| Multiple exact/code candidates | Disambiguate by confirmation score. Accept best if ≥2 passes with no conflicts, OR ≥3 passes. `AMBIGUOUS` on a tie. |
| Fuzzy candidate(s), no exact | Require corroboration — ≥2 passes with no conflicts, or ≥3 passes. Else `NOT_FOUND`. |
| No candidates | `NOT_FOUND` — likely a new product not yet uploaded to LS. |

**Each LS UUID maps to at most ONE Airtable row.** The relationship between LS products and Airtable products is strictly one-to-one — a given Lightspeed `id` must never be written into more than one Airtable row. If two AT rows both resolve to the same LS UUID, that is a signal of a genuine ambiguity (near-duplicate colours, a shared code with compatible collections, etc.) and **must not** be silently resolved by reusing the ID. See Step 2c-bis for how to enforce this.

**Step 2c-bis — One-to-one enforcement (no duplicate IDs).**

Matching is run in two phases so that a UUID is never assigned twice:

1. **Score phase.** For every AT row, run the decision rule above and record its *best* LS candidate UUID together with its confirmation score (number of `passes`, number of `conflicts`, and whether the colour match was exact/code vs fuzzy). Do **not** write any IDs yet.
2. **Resolution phase.** Group the proposed matches by LS UUID. For each UUID claimed by exactly one AT row, assign it (`OK`). For each UUID claimed by **two or more** AT rows (a *contention*), keep it for the single strongest claimant and reject the others:
   - **Winner** = highest score by this order: exact/code beats fuzzy; then more `passes`; then fewer `conflicts`. Assign the UUID to the winner only.
   - **Losers** do **not** receive that UUID. Each loser is then offered its *next-best unused* LS candidate (re-running the decision rule against only UUIDs not yet claimed). If a valid next-best exists, assign it; otherwise the loser becomes `DUPLICATE` (ID left blank, flagged in `LS Match status`).
   - **Ties** (no clear winner — equal score, both exact, equal passes/conflicts): assign the UUID to **neither**. Mark both rows `AMBIGUOUS` and explain in the note that they contend for the same LS UUID.

After the resolution phase, assert that the set of written UUIDs has no repeats. If a repeat somehow remains, that is a bug — stop and surface it rather than producing a file with a duplicated ID.

**Why conflicts don't block an exact/code match:** colour (or code) + collection together define product identity. Cost (`$/sf`) and box size (`sf/b`) are **mutable fields that legitimately drift** as pricing and packaging change — flag them, don't block. **Species and collection conflicts are stronger** — they may indicate the LS catalogue predates a relabel (e.g. LS says Red Oak, the new list says White Oak), or a cross-era collection rename (e.g. a colour that moved from `7 Diamond` to `8 Diamond` after a thickness upgrade). Accept the colour/code match but flag the conflict prominently so the user can reconcile.

**Step 2d — Record outcome.**

- `OK` → copy LS `id` into Airtable `Lightspeed ID`. If any detail conflicts (even on an exact match), append `WARNING: conflicts: [fields]` to the match note.
- `AMBIGUOUS` → leave ID blank, describe reason in `LS Match notes`.
- `DUPLICATE` → leave ID blank. Note that another AT row was a stronger match for the same LS UUID, and name that other row's SKU so the user can reconcile.
- `NOT_FOUND` → leave ID blank.

The output is a `.csv`, so there is no row highlighting — **`LS Match status` is the flag.** Anything other than `OK` is a row the user must review; say so in the summary and tell them to filter or sort on that column.

> **"Blank" means a genuinely empty cell — never a placeholder.** For any non-`OK` outcome, write nothing into `Lightspeed ID` (leave the cell `None`/empty). **Do not write `0`, an empty string, `N/A`, or any sentinel.** A non-empty-but-invalid value like `0` is worse than blank: it isn't a real UUID, so a later LS upload can't use it as an update target, and it also can't be cleanly recognized as "new." Downstream, the `ls-upload-instructions` skill has a defensive guard that coerces `0`/non-UUID ids back to blank — but that guard is a backstop, not a license to write junk here. The backfill is the source of truth: failed matches leave the cell empty so the row imports as a fresh CREATE.

### Step 3 — Detail confirmation (collection, species, specs)

After a colour/code match, confirm against these fields. Collection and species are categorical (stronger); the four specs are numeric (cost/box are soft, width/thickness are firmer).

| Airtable | LS | Tolerance / rule |
|---|---|---|
| `Collection` | Section token in LS name | Normalized equality, with alias map (e.g. `7 Garnet Collection` ↔ `7 Garnet`; `8 Diamond Collection` ↔ `7 Diamond Collection` for cross-era upgrades) + substring tolerance |
| `Species` | Species word in LS name | Normalized equality (`whiteoak`/`redoak`/`walnut`/…). Mismatch is a strong conflict — flag prominently |
| `Width (in)` | Extracted from LS name (mm → in: mm / 25.4, or explicit inch token) | ±0.3" |
| `Thickness (mm)` | Extracted from LS name | ±0.15mm |
| `Cost ($/sf)` | `supply_price` | ±$0.01 (drifts legitimately — soft) |
| `Box size (sf)` | Extracted from LS name (`sf/b` value) | ±0.1 (drifts legitimately — soft) |

LS name format to parse for specs: `... | [W]" or [L]x[W]x[T]mm ... - [X.XX]sf/b`. Treat `None`/unparseable as "can't verify" — neither a pass nor a conflict. A field that couldn't be extracted doesn't penalize the match.

### Step 4 — Overwrite existing Lightspeed IDs

If a row in the Airtable file already has a Lightspeed ID populated and the color match finds a different UUID, **overwrite with the LS export value**. LS is the source of truth for IDs. No warning, no flag — just overwrite quietly, but track the count for the summary.

### Step 5 — Output file — **CSV, always**

**Decided 2026-09-09 (Albert): the backfill writes a `.csv`, never an `.xlsx`.** This
matches the 2026-09-03 ruling in `bert-airtable-schema` ("every export is a `.csv`") —
one format for every file in the pipeline, so nothing needs converting before the
Airtable import and there is never a question about which file is the real one. The LS
export *arriving* as `.xlsx` is fine; that is input. Nothing this skill writes is.

**Update the Airtable upload file in place** — same path, same filename, same column
order. Do not invent a second `..._with_ls_ids_...` file: a duplicate with a near-identical
name is exactly how the wrong one gets imported. The file the ingest run produced and
attached to the Notion row is the file this skill enriches.

1. **All existing columns preserved** in their original order and content, with
   `Lightspeed ID` now populated on `OK` rows.
2. **Two helper columns appended at the end**, after the existing helpers:
   - `LS Match status` — `OK` / `NOT_FOUND` / `AMBIGUOUS` / `DUPLICATE`, or
     `N/A (accessory)` for rows the LS export does not cover.
   - `LS Match notes` — for `OK` rows, a short confirmation like
     `LS sku <SKU> (exact colour, 3 confirms)`, plus any
     `WARNING: <field> <ls value> vs <at value>`. For non-`OK` rows, the reason.

   These are review aids in the same family as `MatchedRecId` / `MatchStatus` — the
   reviewer deletes all of them before importing to Airtable. Say so in the summary.

**Write the CSV per the four settings in `bert-airtable-schema` → "CSV, not xlsx — how to
write it"**, each of which fails silently if you get it wrong: UTF-8 **no BOM**; minimal
RFC-4180 quoting (match notes contain commas on nearly every row); CRLF line endings
(`newline=''`); and empty string for blanks, never `None`.

**Path.** In the `titan-agents-repo` working copy, the file already lives in
`ingest/YYYY-MM-DD/` — update it there and commit. In a claude.ai session it lives in
`/mnt/user-data/outputs/`.

> **`MatchStatus` and `LS Match status` answer different questions — do not merge them.**
> `MatchStatus` (`new` / `matched` / `ambiguous`) is about **Airtable**: does this row create
> a record or update one? `LS Match status` is about **Lightspeed**: did we find this
> product's UUID? A row can legitimately be `MatchStatus: new` **and** `LS Match status: OK`
> — new to Airtable, already live in Lightspeed. That is the third state in
> `bert-airtable-schema` RULE 0a, and it is common for a supplier Titan has been buying
> from for years but never catalogued. Such a row creates the Airtable record and
> **updates** the existing LS product; shipping it with a blank `id` duplicates that
> product on the POS.

Deliver the file with `SendUserFile` (or `present_files` in a claude.ai session).

### Step 6 — Summary response

Present a concise summary:
- **Total Airtable rows:** N
- **Matched OK:** N (→ LS IDs copied)
- **Not found in LS:** N (listed by SKU, max 10 shown)
- **Ambiguous:** N (listed by SKU with reason, max 10 shown)
- **Duplicate (lost contention for an ID):** N (listed by SKU, naming the winning row, max 10 shown)
- **Overwrites:** N rows where an existing Airtable LS ID was replaced

Also note: LS rows with no corresponding Airtable record are **not** listed or flagged. Those are ignored by design — but an LS row that *should* have matched and did not usually means a duplicate in Lightspeed. Call those out so LS can be cleaned up.

---

## Implementation pattern

Build this as a Python script in the scratchpad directory. Use `openpyxl` to **read** the
LS export when it arrives as `.xlsx`, and the stdlib `csv` module for both reading and
writing the Airtable file. Nothing this skill writes uses `openpyxl`.

> **Never pass `read_only=True` to `load_workbook` on an LS export.** That mode trusts
> the worksheet dimension the file declares, and LS exports declare it wrong: both
> committed exports (`ingest/2026-09-03/grandeur_ls_product_export_2026-09-03.xlsx` and
> `canadian_standard_...`) are 33 columns x 267/311 rows but read back as **1 column and
> 0 data rows** in read-only mode. It fails silently — you get an empty match set, not an
> error. A plain `load_workbook(path, data_only=True)` reads them correctly; the files are
> under 100 KB, so there is nothing to optimise. Found 2026-09-10.

```python
from openpyxl import load_workbook   # LS export only, when it is .xlsx
import csv, re

# 1. Load LS export, extract colors + type + specs for each row
# 2. Load AT file, for each row: extract handle tail + paren colors, derive AT type from SKU prefix
# 3. SCORE PHASE — for each AT row: find all LS candidates by type compatibility + color match,
#    score each (exact/code vs fuzzy, #passes, #conflicts). Record ranked candidate list. Write NO ids yet.
# 4. RESOLUTION PHASE — assign UUIDs one-to-one (see resolve_one_to_one below):
#    each LS id goes to at most one AT row; losers fall back to next-best unused id or become DUPLICATE.
# 5. Write Lightspeed ID + LS Match status (OK / NOT_FOUND / AMBIGUOUS / DUPLICATE) + LS Match notes
# 6. Assert no UUID was written twice, and that every written id is a well-formed UUID
#    (36 chars, 4 hyphens) — never 0/None/'N/A'.
# 7. Rewrite the SAME csv in place: original columns + LS Match status + LS Match notes.
```

### Helper: normalize tokens

```python
def alnum_lower(s):
    if s is None:
        return ""
    return re.sub(r'[^a-zA-Z0-9]', '', str(s)).lower()
```

### Helper: extract LS color candidates

```python
def extract_ls_color(ls_name, ls_handle, ls_sku):
    """Collect color candidates from parens in name, first meaningful handle token, and SKU segments."""
    cands = set()
    if ls_name:
        for m in re.finditer(r'\(([^)]+)\)', str(ls_name)):
            token = alnum_lower(m.group(1))
            if token and len(token) >= 2:
                cands.add(token)
    if ls_handle:
        parts = [p for p in re.split(r'-+', str(ls_handle)) if p]
        for p in parts:
            pl = p.lower()
            if re.match(r'^(pur|purlam|purlvp|purspc|purhwd|pureng|purwpc|purvin)$', pl): continue
            if re.match(r'^pur[svw]\d', pl): continue  # e.g. purs0ban1
            if re.match(r'^\d', pl): continue
            if len(p) < 3: continue
            cands.add(alnum_lower(p))
            break  # first real token is the color
    if ls_sku:
        for p in str(ls_sku).split('.'):
            if len(p) >= 3 and re.match(r'^[A-Za-z]+$', p):
                cands.add(alnum_lower(p))
    return [c for c in cands if c]
```

### Helper: extract AT handle tail + paren colors

```python
def extract_at_color(at_handle, at_name):
    """Return (handle_tail, paren_colors).
       handle_tail is the alphanumeric remainder after stripping PLUX + product-type prefix."""
    tail = ""
    paren = []
    if at_handle:
        h = str(at_handle).upper()
        m = re.match(r'^PLUX(LAM|LVP|LVT|SPC|HWD|ENG|WPC)(.*)$', h)
        tail = alnum_lower(m.group(2)) if m else alnum_lower(h)
    if at_name:
        for m in re.finditer(r'\(([^)]+)\)', str(at_name)):
            t = alnum_lower(m.group(1))
            if len(t) >= 3:
                paren.append(t)
    return tail, paren
```

### Helper: color match with edit-distance tolerance

```python
def levenshtein(a, b):
    if a == b: return 0
    if len(a) < len(b): a, b = b, a
    if not b: return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j+1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[-1]

def color_matches_at(at_tail, at_paren_colors, ls_colors):
    """Returns (matched, is_exact)."""
    for lc in ls_colors:
        if not lc or len(lc) < 3: continue
        # Exact suffix of handle tail
        if at_tail and at_tail.endswith(lc):
            return True, True
        # Exact paren match
        if lc in at_paren_colors:
            return True, True
        # Near-spelling match (edit distance 1) — handles Coronado/Coronada drift
        if at_tail and len(at_tail) >= len(lc) and len(lc) >= 5:
            if levenshtein(at_tail[-len(lc):], lc) <= 1:
                return True, True
        for pc in at_paren_colors:
            if len(lc) >= 5 and len(pc) >= 5 and abs(len(lc) - len(pc)) <= 1:
                if levenshtein(lc, pc) <= 1:
                    return True, True
    # Fuzzy fallbacks
    for lc in ls_colors:
        if not lc or len(lc) < 3: continue
        for pc in at_paren_colors:
            if len(lc) >= 4 and (lc in pc or pc in lc):
                return True, False
    return False, False
```

### Helper: parse specs from LS name

```python
def parse_ls_specs(ls_name):
    out = {"length_mm": None, "width_mm": None, "thickness_mm": None, "sfb": None}
    if not ls_name: return out
    s = str(ls_name)
    # "1215*196*14.3mm" or "1215x196x14.3mm"
    m = re.search(r'(\d+(?:\.\d+)?)\s*[\*x]\s*(\d+(?:\.\d+)?)\s*[\*x]\s*(\d+(?:\.\d+)?)\s*mm', s)
    if m:
        out["length_mm"] = float(m.group(1))
        out["width_mm"] = float(m.group(2))
        out["thickness_mm"] = float(m.group(3))
    m = re.search(r'(\d+(?:\.\d+)?)\s*sf\s*/\s*b', s, re.IGNORECASE)
    if m:
        out["sfb"] = float(m.group(1))
    return out

def num_close(a, b, tol):
    if a is None or b is None or a == "" or b == "": return None
    try: return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError): return None
```

### Type compatibility table

```python
# AT SKU prefix → which LS types (from name) are compatible
TYPE_COMPAT = {
    "LAM": {"LAM"},                         # PURLAM
    "LVP": {"VIN"}, "LVT": {"VIN"},         # PURVIN covers all vinyl
    "SPC": {"VIN"}, "WPC": {"VIN"},
    "HWD": {"HWD"}, "ENG": {"ENG"},
}

def at_type_from_sku(sku):
    m = re.match(r'^([A-Z]{3,4})-', str(sku or "").upper())
    return m.group(1) if m else None

def ls_type_from_name(name):
    u = str(name or "").upper()
    if "PURLAM" in u: return "LAM"
    if "PURVIN" in u: return "VIN"
    if "PURHWD" in u or "PURENG" in u: return "HWD"
    return None
```

### Helper: one-to-one resolution (prevents duplicate IDs)

Run this AFTER scoring. Input: for each AT row, an ordered list of candidate matches
(best first), each a dict with `uuid`, `is_exact` (bool, True for exact/code), `passes` (int),
`conflicts` (int). Output: a `uuid` (or None) and a `status` per AT row, with the guarantee
that no `uuid` is assigned to more than one row.

```python
def _rank_key(c):
    # higher is better: exact/code first, then more passes, then fewer conflicts
    return (1 if c["is_exact"] else 0, c["passes"], -c["conflicts"])

def resolve_one_to_one(at_candidates):
    """at_candidates: dict {at_row_id: [candidate, ...]} ordered best-first.
       Returns {at_row_id: {"uuid": str|None, "status": str, "note": str}}."""
    assigned = {}                      # uuid -> at_row_id (winner)
    result = {rid: None for rid in at_candidates}
    # Pointer into each row's candidate list (its current best *unused* choice)
    ptr = {rid: 0 for rid in at_candidates}

    def current(rid):
        cl = at_candidates[rid]
        while ptr[rid] < len(cl) and cl[ptr[rid]]["uuid"] in assigned:
            ptr[rid] += 1
        return cl[ptr[rid]] if ptr[rid] < len(cl) else None

    pending = [rid for rid in at_candidates if at_candidates[rid]]
    for rid in [r for r in at_candidates if not at_candidates[r]]:
        result[rid] = {"uuid": None, "status": "NOT_FOUND", "note": "No LS candidate"}

    # Iteratively let each row claim its best unused uuid; resolve contention by score.
    changed = True
    while changed:
        changed = False
        claims = {}                    # uuid -> [(rid, candidate)]
        for rid in pending:
            if result[rid]: continue
            c = current(rid)
            if c is None:
                result[rid] = {"uuid": None, "status": "DUPLICATE",
                               "note": "All matching LS UUIDs already claimed by stronger rows"}
                changed = True
                continue
            claims.setdefault(c["uuid"], []).append((rid, c))

        for uuid, claimants in claims.items():
            if uuid in assigned:
                continue
            if len(claimants) == 1:
                rid, c = claimants[0]
                assigned[uuid] = rid
                result[rid] = {"uuid": uuid, "status": "OK",
                               "note": f"exact={c['is_exact']} passes={c['passes']} conflicts={c['conflicts']}"}
                changed = True
            else:
                claimants.sort(key=lambda rc: _rank_key(rc[1]), reverse=True)
                top, second = claimants[0], claimants[1]
                if _rank_key(top[1]) == _rank_key(second[1]):
                    # tie: assign to neither, mark both AMBIGUOUS for this contention
                    for rid, c in claimants:
                        if _rank_key(c) == _rank_key(top[1]):
                            other = [r for r, _ in claimants if r != rid]
                            result[rid] = {"uuid": None, "status": "AMBIGUOUS",
                                           "note": f"Contends for LS {uuid} with {other}"}
                            changed = True
                    assigned[uuid] = None  # block this uuid from reuse
                else:
                    rid, c = top
                    assigned[uuid] = rid
                    result[rid] = {"uuid": uuid, "status": "OK",
                                   "note": f"won contention for {uuid}; "
                                           f"exact={c['is_exact']} passes={c['passes']} conflicts={c['conflicts']}"}
                    changed = True
                    # losers advance to their next-best unused candidate on the next loop
                    for lrid, _ in claimants[1:]:
                        if not result[lrid]:
                            ptr[lrid] += 1
                            changed = True

    # Final guarantee: no uuid written twice.
    written = [v["uuid"] for v in result.values() if v and v["uuid"]]
    assert len(written) == len(set(written)), "duplicate UUID assignment detected"
    return result
```

This is intentionally conservative: when two rows genuinely compete for one UUID and can't be
separated by score, **neither** gets it (both flagged) rather than guessing. The user reviews the
rows flagged in `LS Match status`.

### Edge case: LS has duplicate entries with mismatched identity

Sometimes the LS export contains a row where the SKU, handle, and name disagree internally (e.g. sku=`11344` with handle pointing to `PUR.S.0.Cab.1` but name showing `(KAMATO)`). These are data errors in LS. The suffix-based color matcher naturally avoids them — if the AT handle tail ends in `cabana`, it won't match the "KAMATO" name or the numeric SKU `11344`. No special handling needed, but it's worth flagging these to the user in the summary so LS can be cleaned up.

---

## User input to expect

The user will typically attach TWO files or point to two files in `/mnt/user-data/uploads/`. Verify both are present before running. If only one is uploaded, ask which is which.

Do NOT assume filenames — inspect the headers to identify which file is the Airtable upload (58-col schema, has "Product name" and "LS Handle / Parent ID") and which is the LS export (31-col LS schema, has "id" as column 1 and "handle" as column 2). Match by column signature, not filename.

**Do NOT try to match on SKU.** Airtable SKUs and LS SKUs are different namespaces for this workflow — matching is done via color tokens as described above. If a workflow ever arises where LS SKUs are populated with Airtable SKUs (e.g. after a future data hygiene pass), the user will tell you — default to color matching unless told otherwise.

---

## Output summary format

Present the summary inline as a short, scannable block:

```
Matched 62 rows (57 exact color, 5 with spec warnings; overwrote 0 existing).
3 rows not found in LS (likely new products not yet uploaded):
  - LVP-PLUX-0045 (Journey Luxor)
  - LVP-PLUX-0046 (Journey Venetian)
  - LVP-PLUX-0050 (Journey Mandalay)

0 ambiguous rows.
0 duplicate-contention rows.

Every LS UUID was assigned to at most one row (no ID used twice).
Rows where `LS Match status` is not `OK` need your review — filter on that column.
```

If any OK matches had spec warnings (cost / sf-per-box disagreement on an exact color match), mention them so the user can decide whether to reconcile the data. Example: "4 rows matched on exact color but cost disagreed — LS has $1.99, Airtable has $2.99. Worth reviewing."

Then deliver the file (`SendUserFile`, or `present_files` in a claude.ai session). Keep prose
minimal — the file is the deliverable, not the explanation.

---

## Edge cases

- **Empty Airtable file** (headers only, no data) → tell user the file is empty, nothing to do.
- **LS export missing the `id` column** → stop and tell user the LS export doesn't have the UUID column. No match possible.
- **LS export has `id` column but all values are blank** → tell user the export wasn't fully generated; all rows would be flagged NOT_FOUND. Confirm they want to proceed anyway.
- **AT handle missing or malformed** (doesn't start with `PLUX...`) → the color extractor will fall back to the raw handle. If that doesn't match any LS color, row is flagged NOT_FOUND. Note the handle format issue in the response.
- **LS export has mouldings / accessories mixed in with flooring** → filtered out via the moulding regex (`MOULDING|STAIR SET|RISER|NOSING|REDUCER|T-MOULD`). These rows are ignored by design.
- **Supplier-wide spelling drift** (e.g. "Coronado" vs "Coronada") → handled by edit-distance-1 tolerance on exact color matching (minimum token length 5). Larger spelling differences will not match and the row is flagged NOT_FOUND.
- **LS rows with internally inconsistent data** (handle and name disagree) → the suffix matcher naturally skips these. Mention them in the summary so LS can be cleaned up.
- **Two AT rows match the same LS UUID** (near-identical colours, shared code, or a real LS duplicate) → enforced one-to-one: the stronger-scoring row keeps the ID, the other is given its next-best unused ID or flagged `DUPLICATE`. On a true tie, neither gets the ID and both are flagged `AMBIGUOUS`. A UUID is never written into more than one row.
