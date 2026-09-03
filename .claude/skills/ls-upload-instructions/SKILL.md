---
name: ls-upload-instructions
description: "Lightspeed Retail X product upload instructions for Titan Flooring. Use this skill whenever generating a Lightspeed import file, transforming Airtable product data into Lightspeed format, building LS upload spreadsheets, mapping source sheet columns to LS fields, constructing LS product names, setting up variant grouping by grade, or troubleshooting Lightspeed import issues. Also trigger when the user mentions Lightspeed upload, LS import, LS handle, LS name format, variant grouping, or any task that involves converting flooring product data into a Lightspeed-ready .xlsx or .csv file. This skill works alongside the bert-airtable-schema skill — the Airtable schema defines the source data, and this skill defines how to transform it for Lightspeed."
---

# Lightspeed Retail X — Product Upload Instructions

Last updated: August 2026 | Applies to ALL flooring brands using the standard source sheet schema

## Purpose

This document defines how to transform product data from any brand's source sheet (following the standard column schema) into a Lightspeed Retail X import-ready file. Follow these rules exactly to ensure every upload is consistent regardless of brand.

> **Note:** This schema is for Lightspeed Retail X (not R-Series). Import file = .xlsx or .csv.

---

## ⚠️ STOP — do not build an LS file from unreconciled data

**Before any LS file is built, the source sheet must already carry, for every row that
matches an existing product: the live `SKU`, the live `LS Handle / Parent ID`, and the
live `Lightspeed ID`.** LS columns 1–3 (`id`, `handle`, `sku`) are identity fields
owned by Airtable — this skill copies them, it never derives them.

The order is fixed:

```
extract → match against the live catalogue → write SKU + handle + Lightspeed ID
into the Airtable schema file → THEN build the LS file from that file
```

Building the LS file first, or in parallel, produces blank ids and regenerated
handles. That is not cosmetic: **a blank `id` makes LS create a duplicate instead of
updating**, and a regenerated handle breaks the variant grouping LS already has.

Check before you start: does the source sheet have `Lightspeed ID` populated on rows
that exist in LS, and handles that match what LS already holds? If not, stop and
reconcile — do not "fill them in later".

### Existing product vs new product — the id column differs, the handle does not

| | `id` (column 1) | `handle` (column 2) | `sku` (column 3) |
|---|---|---|---|
| **Matched** (already in LS) | The stored `Lightspeed ID`. **Required** — blank duplicates it. | The stored handle, copied as-is. Never regenerated. | The stored SKU, verbatim. |
| **New** (not yet in LS) | **Blank, correctly** — Lightspeed generates the UUID on import. | **Minted by us** from the handle-generating schema, then uploaded. LS adopts it. | Minted by us from the price list. |

A blank `id` is a defect on a matched row and the correct value on a new row. Decide
by `MatchStatus`, never by whether the cell happens to be empty.

### After the import: reverse-populate the new ids (batched)

**An upload containing new products is not finished when the import succeeds.**
Lightspeed has just generated UUIDs that Airtable does not have yet. Export the
products from LS, match on `SKU`, and write the `Lightspeed ID`s back into Airtable —
the `ls-id-backfill` skill exists for exactly this.

**This is batched deliberately** (Albert, 2026-09-03): one LS export can cover several
price lists' worth of new products, so the backfill runs periodically rather than after
every upload. What keeps that safe is the tracking on the Notion Price Lists row —
`New Products` (count), `POS` (checkbox: the LS file has been pushed) and `LS Backfill`
(`Pending` / `Done` / `Not needed`).

**Check `POS` on the row when you push its file to Lightspeed.** That is what makes the
backfill queue meaningful: a new product has no UUID until the upload creates one, so
the actionable set is `LS Backfill is Pending` **and** `POS` checked. Filter on
`Pending` alone and you will chase ids for products that were never uploaded. Flip each
covered row to `Done` after writing the UUIDs back.

Skip it and a later price list run sees a blank `Lightspeed ID` on a product that now
exists in LS, and duplicates it. Batching changes when the loop closes, not whether.

## ⚠️ RULE 0 — Airtable owns the SKU; Lightspeed matches to it

**The Airtable `SKU` is immutable and is the source of truth.** Column 3 (`sku`) is
copied from the source sheet **verbatim** and is never regenerated, reformatted or
"improved" on the way into Lightspeed. When LS and Airtable disagree about a SKU,
**Airtable is right** and the LS record is what gets corrected — never the reverse.

An LS import must never be the reason an Airtable SKU changes. If a SKU cannot be
loaded into LS as stored, that is escalated, not silently rewritten on both sides.

The one sanctioned transformation is the **Olympia comma→dot** replacement below, and
it is applied **when the record is first created** so Airtable stores the dotted form
from the outset — it is a minting rule, not permission to edit existing SKUs.

Full statement: RULE 0 at the top of the `bert-airtable-schema` skill.

---

## ⚠️ Load-bearing rule — every SKU must carry a readable sf/b

**Box size (sf/b) is the key factor used for quantity analysis.** Staff and reporting convert between boxes and square feet using it constantly. A SKU that reaches Lightspeed without a visible sf/b cannot be quantity-analyzed at the POS, and the gap is invisible until someone needs the number and can't find it.

**The invariant: every row that has a `Box size (sf)` value in Airtable must expose that value somewhere human-readable in Lightspeed.** Prefer the **name** wherever LS allows it — the name travels with the line item everywhere (receipts, order lines, exports, search), while a variant value only surfaces at the point of selection. Use column 11 only where the name cannot carry it.

| Row type | Where sf/b lives | Format |
|---|---|---|
| **Single-grade / no-grade product** (1 row per handle) | In the **name** | `… - 24.18sf/b` (before the grade suffix, if any) |
| **Variant group, uniform box size** (all rows share one `Box size (sf)`) | In the **name** — names stay identical, so LS is satisfied | `… - 24.18sf/b`; column 11 = grade alone (`Character`) |
| **Variant group, mixed box sizes** (2+ distinct values in the group) | In **column 11**, `variant_option_one_value` | `Character - 24.18sf/b` |
| **Per-piece item** (accessories, STONE, mosaics — `Box size (sf)` legitimately blank) | Exempt from **name / column 11** only — the **description still states `Sold per piece`** | n/a |

**Uniform is the common case.** Grades of the same product almost always box the same — across the entire Vidar catalogue only one handle group carries mixed box sizes. So most variant groups keep sf/b in the name and leave column 11 as a clean grade picker, which is what staff expect the dropdown to be.

**Why the mixed case is different:** LS requires every row in a variant group to share an identical `name`. When box sizes differ across the group, putting sf/b in the name makes the names differ and LS rejects the group. Column 11 is per-row, so it can carry a value that varies. This is the same mechanism tile uses for size (see *Size dropdown value — includes sf/b*).

**Compute uniform vs mixed per handle group at build time — it is a property of the data, not of the brand, and it can change.** A supplier revising one grade's box size flips a group from uniform to mixed. When that happens, sf/b must move out of the name and into column 11 for *every* row in the group, and all the names must be updated together — otherwise the group either carries a stale number or fails name identity.

**Do not put sf/b in both the name AND column 11.** One placement per group — that choice is forced by LS's name-identity constraint, and doing both breaks the variant group.

> **This does not apply to the description.** Per the strict rule under *Description rules (column 8)*, `Box size (sf)` goes in the description on **every** product regardless of where it lives here, plus `Pieces per box` when present, plus `Sold per piece` / `Sold per sq ft` for items that genuinely have no box. All copies are generated from the same Airtable field on each build, so they cannot drift — provided the file is regenerated rather than hand-edited.

**Blank `Box size (sf)` on a flooring row is a data defect, not an exemption.** Per-piece accessories and STONE are legitimately blank. A plank/tile flooring SKU with no box size must be flagged and fixed in Airtable before upload — the LS file cannot invent it.

---

## Brand configuration

Before generating an upload, identify these brand-specific values from the source data sheet. Every rule below uses these variables.

| Variable | Description / How to determine |
|----------|-------------------------------|
| `[BRAND]` | The brand name as it appears in the source sheet "Brand" column. Used for brand_name and supplier_name fields. Examples: "VIDAR", "SUNSHINY", "WODEN". |
| `[NAME_PREFIX]` | The product name prefix used in Lightspeed. Convention: **[3–4 char brand abbreviation] + [3 char product type abbreviation]**. The brand abbreviation is always 3–4 uppercase letters. The product type abbreviation is always 3 uppercase letters. A single brand may have multiple prefixes if it spans multiple product types. Examples: "VIDENG" (Vidar Engineered), "GRNDENG" (Grandeur Engineered), "GRNDSPC" (Grandeur SPC), "GRNDLAM" (Grandeur Laminate). Confirm with user if a new brand. **Exception — transitions, mouldings, stair components, and sundries do NOT use an abbreviated prefix.** They lead with the full brand name spelled out (`Vidar - Transition \| …`) so the family is searchable by supplier. See *Accessories — transitions and mouldings*. |
| `[HANDLE_PREFIX]` | **Descriptive only — do NOT enforce.** This is just what the first few characters of the brand's existing Airtable handles happen to look like. Handle format varies by brand and is set in Airtable; the LS upload copies handles as-is with no transformation. Only recorded here as a reference for recognizing which handles belong to which brand. Examples: Vidar handles start with "VIDR", Grandeur with "GRND", FAW/NAF handles start with the category (LVP/ENG/LAM/LVT/HWD). |
| `[SKU_PREFIX]` | The prefix pattern in the source sheet's SKU column. Read from the data — don't assume. Examples: "ENG-VIDR-" (Vidar), "ENG-SUN-" (Sunshiny). |
| `[SOURCE_SHEET]` | The name of the source data sheet in the workbook. Examples: "Vidar Engineered Hardwood", "Sunshiny Engineered", "Woden Products". |
| `[CATEGORY]` | The Lightspeed product category. All caps, space-slash-space separator. Vinyl products use a construction-based leaf subcategory: `FLOORING / VINYL / SPC`, `FLOORING / VINYL / WPC`, `FLOORING / VINYL / LOOSE LAY` (loose-lay vinyl), or `FLOORING / VINYL / GLUE DOWN` (dry-back / glue-down vinyl). **Exact leaf names confirmed from the Lightspeed category tree (Jul 2026): GLUE DOWN, LOOSE LAY, SPC, WPC.** **LS requires a LEAF category — never assign a product to `FLOORING / VINYL` itself (or any parent node); the import rejects it with "A product can only be assigned to a leaf category" (learned from the Grandeur Jul 2026 import, 42 rows rejected).** When core is ambiguous (e.g. Grandeur Inov8 'engineered vinyl'), default to `FLOORING / VINYL / SPC` — avoid `FLOORING / VINYL / ENGINEERED` as it conflicts with the engineered hardwood category name. Matching name prefixes for non-SPC/WPC vinyl: `[BRAND]LVP-LL` (loose lay), `[BRAND]LVP-DB` (glue down / dry-back). Ambiguous-core vinyl uses `[BRAND]LVP-SPC` and `FLOORING / VINYL / SPC`. All other flooring types follow the two-level pattern: `FLOORING / ENGINEERED HARDWOOD`, `FLOORING / SOLID HARDWOOD`, `FLOORING / LAMINATE`, `FLOORING / TILE`. The LVP vs LVT format distinction is tracked in Airtable (Category field) — it does not create a separate LS category. **Exception: accessories use the standalone category `ACCESSORIES` — not nested under FLOORING.** This applies to transitions, mouldings, stair treads/risers, underlay, glue, and any other non-flooring product items. |

### Brand configuration examples

| Variable | Vidar | Sunshiny | Grandeur | NAF (FAW) |
|----------|-------|----------|----------|----------------------|
| `[BRAND]` | VIDAR | SUNSHINY | Grandeur | NAF |
| `[NAME_PREFIX]` | VIDENG | SUNENG | GRNDENG / GRNDHWD / GRNDLVP-SPC / GRNDLVP-WPC / GRNDLVT-SPC / GRNDLVT-WPC / GRNDLAM | NAFENG / NAFHWD / NAFLVP-SPC / NAFLVP-WPC / NAFLVT-SPC / NAFLVT-WPC / NAFLAM |
| `[HANDLE_PREFIX]` (descriptive only — see note) | VIDR | SUNY | GRND | category-first: LVP / ENG / LAM / LVT / HWD |
| `[SKU_PREFIX]` | ENG-VIDR- | ENG-SUN- | ENG-GRAN- / HWD-GRAN- / LVP-GRAN- / LVT-GRAN- / LAM-GRAN- | ENG-FAWK- / HWD-FAWK- / LVP-FAWK- / LVT-FAWK- / LAM-FAWK- |
| `[SOURCE_SHEET]` | Vidar Engineered Hardwood | Sunshiny Engineered | Grandeur Products | Master Flooring Catalogue |
| `[CATEGORY]` | `FLOORING / ENGINEERED HARDWOOD` | `FLOORING / ENGINEERED HARDWOOD` | varies by product type — `FLOORING / VINYL / SPC`, `FLOORING / VINYL / WPC`, `FLOORING / ENGINEERED HARDWOOD`, etc. | varies by product type — routing follows the standard Category + Material type logic |
| Supplier | VIDAR | SUNSHINY | Grandeur | FAW |

> **Note on supplier name for FAW:** The supplier name written to Airtable's `Supplier` field and to LS column 24 (`supplier_name`) is **FAW** — not "Floors At Work". This is the canonical short form used across both systems. Albert will manually align the Airtable supplier single-select to match.

> **Note on supplier name for Bella Flooring Plus:** The `supplier_name` (column 24) for all Bella Flooring Plus products must be set to **BELLA** — regardless of whether the brand is Northernest or Wickham. `brand_name` (column 23) uses the actual brand as normal (e.g. "Northernest", "Wickham"). Do not use "Bella Flooring Plus" in the supplier_name column.

> **Grandeur handle regeneration (Jul 2026):** All 239 Grandeur handles in Airtable were regenerated to a deterministic convention: `GRND` + the Product name with the leading "Grandeur " and the trailing grade parenthetical removed, uppercased, non-alphanumerics stripped. Examples: `Grandeur 7.5" EWO — Moraine (ABCD)` → `GRND75EWOMORAINE`; `Grandeur 7" Pacific — Canterbury` → `GRND7PACIFICCANTERBURY`; `Grandeur 12mm Aquamate — Sydney` → `GRND12MMAQUAMATESYDNEY`. This replaced the legacy mix of slugified LS names (hyphenated), UUIDs pasted in the handle column, and shared numeric handles (e.g. 55546911 spanning Barossa 6"/7.5"/HB). One handle per product — the legacy cross-size numeric sharing was intentionally split. LS product identity was preserved via the `id` (Lightspeed UUID) column on update. Audit file: `grandeur_handle_map.csv`.

> **Floordi brand config (added Jul 2026):** `[BRAND]` = Floordi (brand_name = supplier_name = "Floordi"). `[NAME_PREFIX]` = `FLRDLVP-SPC` (AVO-ROX vinyl) / `FLRDACC` (accessories). `[SKU_PREFIX]` = `LVP-FLRD-` / `ACC-FLRD-` (Floordi code verbatim as suffix, e.g. `LVP-FLRD-AVR651`). `[CATEGORY]` = `FLOORING / VINYL / SPC` for all AVO-ROX lines; `ACCESSORIES` for mouldings. `[HANDLE_PREFIX]` descriptive = FLRD, brand-first: `FLRD65[COLOUR]` (EASE 6.5mm), `FLRD8[COLOUR]` (GRAND 8mm); accessories = FLRD + Floordi code with hyphens stripped (`FLRDATAVR65`). No grades → no variant groups; one row per product, box size in the name, columns 10–11 blank. Accessory names: **superseded (Aug 2026)** — Floordi mouldings now follow `Floordi - Transition | [Type] | [Material] | [Dimensions]` per *Accessories — transitions and mouldings*, not the old `FLRDACC - …` form. Still priced per piece via Cost/unit / Retail price/unit as normal.

> **Note on `[HANDLE_PREFIX]`:** For a product that **already exists**, these values are descriptive, not rules to enforce — the stored handle flows through to LS unchanged. Never transform, prepend, or normalize an existing handle to match another brand's convention. Whatever is in the "LS Handle / Parent ID" column of Airtable is what goes to Lightspeed.
>
> **For a genuinely new product there is no stored handle, so we mint one** from the brand's handle-generating schema — `[HANDLE_PREFIX][SizePrefix][SpeciesAbbrev][COLOUR]`, uppercase, alphanumeric only, **never truncated**. That minted handle is written into Airtable *and* uploaded to LS, which adopts it. This is the one case where the prefix pattern is generative rather than descriptive; see RULE 0a in the bert-airtable-schema skill.

### Product type abbreviations

| Abbreviation | Product Type |
|-------------|-------------|
| ENG | Engineered Hardwood |
| HWD | Solid Hardwood |
| LVP-SPC | Luxury Vinyl Plank, SPC core |
| LVP-WPC | Luxury Vinyl Plank, WPC core |
| LVT-SPC | Luxury Vinyl Tile, SPC core |
| LVT-WPC | Luxury Vinyl Tile, WPC core |
| LAM | Laminate |

> **Vinyl name prefix rule:** Always combine format + core in the prefix: `LVP-SPC`, `LVP-WPC`, `LVT-SPC`, or `LVT-WPC`. This lets staff distinguish core construction at a glance when comparing products side by side on the POS — without needing to open the record. The LS category (`FLOORING / VINYL / SPC` or `FLOORING / VINYL / WPC`) is still driven by core only. Example: `GRNDLVP-SPC - Continental (Pennsylvania) Click | 7" x 6mm x RL - 23.62sf/b`

**Example name:** `VIDENG - 6 American White Oak (Silver Stone) T&G | 6" x 18mm x RL - 2mm top - 21.32sf/b`
**Multi-type example:** `GRNDSPC - Continental (Pennsylvania) Click | 7" x 6mm x RL - 23.62sf/b`

---

## Lightspeed upload schema (31 columns)

| Column | Mapping / Rule |
|--------|---------------|
| **1. id** | **= Source column "id", copied as-is.** Airtable's `id` column holds the Lightspeed UUID that was assigned when the product was first uploaded. If populated → LS treats this as an UPDATE to an existing product. If blank → LS treats this as a NEW product and auto-generates a UUID on import (which should then be written back to Airtable's `id` column for future updates). **Never leave this blank for products that already exist in LS** — doing so creates a duplicate product rather than updating the existing one. Always check and copy the Airtable value first. |
| **2. handle** | = Source column "LS Handle / Parent ID", copied as-is. Lightspeed handles can ONLY contain letters and numbers — the Airtable field stores them in this format already. This is the VARIANT GROUPING KEY. Products sharing the same handle appear as variants of one parent product. Format: `[HANDLE_PREFIX][size prefix][species abbrev][COLORNAME]`. All uppercase, no separators. |
| **3. sku** | = Source column "SKU". Each row gets a UNIQUE sku even within a variant group. Copied directly from the source sheet. |
| **4–6. composite fields** | Leave ALL BLANK. Not used. |
| **7. name ⭐** | CRITICAL — see Name construction rules below. |
| **8. description ⭐** | POPULATED WITH ALL UNMAPPED SOURCE DATA — see Description rules below. |
| **9. product_category** | = `[CATEGORY]`. All caps, space-slash-space separator. Full reference: `FLOORING / ENGINEERED HARDWOOD`, `FLOORING / SOLID HARDWOOD`, `FLOORING / VINYL / SPC`, `FLOORING / VINYL / WPC`, `FLOORING / LAMINATE`, `FLOORING / TILE`, `ACCESSORIES`. Vinyl subcategory is determined by the product's core (SPC or WPC), not its format (LVP or LVT). **Accessories (transitions, mouldings, stair treads/risers, underlay, glue, etc.) use the standalone `ACCESSORIES` category — not nested under FLOORING.** |
| **10. variant_option_one_name ⭐** | **Conditional on variant group.** If 2+ rows share the same handle with different grades (true variant group) → "Grade". Otherwise (single-grade product, even if Grade has a value) → leave BLANK. |
| **11. variant_option_one_value ⭐** | **Conditional on variant group, then on box-size uniformity.** Single-grade product → leave BLANK (grade and sf/b both go in the NAME). Variant group where all rows share one box size → grade AS-IS, nothing appended: "Character", "Select & Better", "Rustic" (sf/b sits in the shared name). Variant group with mixed box sizes → `[Grade] - [sfb]sf/b` using **this row's own** box size ("Select - 20.18sf/b" vs "Select & Better - 18.19sf/b"), formatted to two decimals. See *Load-bearing rule — every SKU must carry a readable sf/b*. |
| **12–15. variant options 2 & 3** | Leave ALL BLANK. Not used. |
| **16. tags** | Leave BLANK. |
| **17. supply_price** | = Source **"Cost/unit"** column. Numeric only (no $ signs, no commas). See *Pricing field reflection rule* below. |
| **18. retail_price** | = Source **"Retail price/unit"** column. Numeric only. See *Pricing field reflection rule* below. |
| **19–22. loyalty & account codes** | Leave ALL BLANK. |
| **23. brand_name** | = `[BRAND]`. Read from source sheet "Brand" column. |
| **24. supplier_name** | = `[BRAND]`. Same as brand_name. If supplier differs from brand, use source "Supplier" column. |
| **25. supplier_code** | Leave BLANK. |
| **26. active** | Always: "1" (active). Set to "0" to deactivate. |
| **27. track_inventory** | Always: "1". |
| **28. outlet_tax_[OutletName]** | Always: "Default Tax". Column name suffix must match your Lightspeed outlet name exactly. |
| **29–31. inventory / reorder / restock** | Leave ALL BLANK for new products. |

### Pricing field reflection rule

**Always populate LS `supply_price` (col 17) and `retail_price` (col 18) from the Airtable source fields `Cost/unit` and `Retail price/unit` respectively — on EVERY upload, for EVERY product type.**

This is a deliberate one-to-one reflection:

- `supply_price` ← `Cost/unit` (always)
- `retail_price` ← `Retail price/unit` (always)

Why this rule exists: Airtable previously held two cost/price concepts — a per-sf cost/retail pair (`Cost ($/sf)` / `Retail price ($/sf)`) AND a separate `Price per piece ($)` field for tile, stone, and accessories. That per-piece field has been **eliminated**. `Cost/unit` and `Retail price/unit` are now the single source for ALL pricing regardless of how the product is sold:

- **Flooring** → the unit is per sq ft; `Cost/unit` / `Retail price/unit` hold the per-sf values.
- **Tile, stone, accessories, mouldings, stair treads/risers** → the unit is per piece; `Cost/unit` / `Retail price/unit` hold the per-piece values.

LS does not care which unit the number represents — it stores whatever is in `Cost/unit` as supply_price and whatever is in `Retail price/unit` as retail_price. Do not look for, expect, or map any `Price per piece ($)` column — it no longer exists in the source. If you encounter an old source sheet that still has a `Price per piece ($)` column, treat it as legacy: fold any value there into `Cost/unit`/`Retail price/unit` per the bert-airtable-schema rules before mapping, and flag it.

This mapping is unconditional. There is never a case where supply_price/retail_price are sourced from any column other than `Cost/unit`/`Retail price/unit`, and there is never a case where they are left blank because a product is "priced per piece" — per-piece products carry their price in the same two fields now.

### Name construction rules (column 7)

Built from multiple source columns using this exact format:

```
[NAME_PREFIX] - [Collection] [Species] ([Color]) [Install] | [Width]" x [Thickness]mm x [Length] - [Veneer]mm top - [BoxSize]sf/b[ - [Grade]]
```

Components:

- `[Collection]` = source "Collection" minus " Collection" suffix
- `[Species]` = source "Species" AS-IS
- `[Color]` = text between "—" and "(" in source "Product name"
- `[Install]` = "T&G" or "Click" from "Install profile"
- `[Width]` = source "Width (in)" + "
- `[Thickness]` = source "Thickness (mm)" + "mm"
- `[Length]` = source **`Length`** (schema column 17) AS-IS — `RL`, `48"`, `1520mm`,
  `20" - 83"`. **Length stays in the LS name exactly as it always has** (Albert,
  2026-09-03); the only change is that it is now *read from the `Length` field*
  rather than re-parsed out of the price list or assumed. Fall back to `RL` when
  the field is blank — random length is the overwhelming default for plank goods,
  and every pre-existing LS name uses it. Copy the field verbatim, including its
  unit; do not normalize `1520mm` to inches or `RL` to a measurement.
- `[Veneer]` = source "Veneer / top layer (mm)" + "mm top" (only if non-empty)
- `[BoxSize]` = source "Box size (sf)" + "sf/b". Include for single-grade and no-grade products, **and for variant groups where every row shares the same box size** — the name stays identical across the group, so LS is satisfied. Omit **only** for variant groups with mixed box sizes; on those rows sf/b moves to **column 11** alongside the grade (`Character - 24.18sf/b`). Never omit it from both.
- `[Grade]` = source "Grade" AS-IS, appended at the end after " - " — **ONLY for single-grade products** (products NOT part of a variant group). Omit entirely if the row is part of a variant group OR if Grade is empty.

### Name deduplication rule

Some brands bake the species or install profile into the collection name (e.g. FAW's "White Oak Click Collection" where the collection already contains a species root and the install). Left alone, this produces redundant LS names like `NAFENG - White Oak Click American White Oak (Autumn) Click | ...` — species repeats and "Click" repeats.

**Rule: when assembling the middle section of the name, skip the Species or Install components if they are already represented in the Collection.** Apply both checks independently on the same pass:

**Species dedup — skip the Species component if the Collection contains the trailing tokens of the Species as a contiguous whole-word substring (case-insensitive).**

The check tries the species tokens from longest trailing substring down to single last word:

- Species "American White Oak" (tokens: American / White / Oak)
  - Try "American White Oak" → not in "White Oak Click"
  - Try "White Oak" → ✓ found in "White Oak Click" → **drop species**
- Species "American Black Walnut" (tokens: American / Black / Walnut)
  - Try "American Black Walnut" → not in "Handscraped Exotic Walnut"
  - Try "Black Walnut" → not found
  - Try "Walnut" → ✓ found → **drop species**
- Species "American White Oak" + Collection "Regal" → no match at any level → **keep species**

**Install dedup — skip the Install component if the Collection ends with the Install profile (case-insensitive, whole-word end match).**

- Collection "White Oak Click" ends with "Click" → **drop install**
- Collection "White Oak T&G" ends with "T&G" → **drop install**
- Collection "Designer" does not end with "T&G" → **keep install**

**Implementation order:** apply dedup at the COMPONENT level when assembling the middle section — do NOT assemble first and then string-replace, as that risks stripping matches from within the Collection text itself.

**Correct pseudocode:**
```
middle = [Collection]
if Species AND NOT should_drop_species(Collection, Species): middle += Species
middle += f"({Color})"
if Install AND NOT should_drop_install(Collection, Install): middle += Install
```

**Do NOT:**
- Strip species/install from the assembled name with a regex — this corrupts collections that contain the species root (e.g. "Hickory Engineered" loses its own "Hickory")
- Apply this to Color — even if Color text appears in Collection, colors stay in the name (they're the distinguishing identifier between SKUs under the same collection)
- Drop the Collection itself — Collection always stays

**Worked examples:**

| Collection | Species | Install | Final name middle section |
|-----------|---------|---------|--------------------------|
| White Oak Click | American White Oak | Click | `White Oak Click (Color)` |
| White Oak T&G | American White Oak | T&G | `White Oak T&G (Color)` |
| Hickory Engineered | Hickory | T&G | `Hickory Engineered (Color) T&G` (species dropped, install kept) |
| Handscraped Exotic Walnut | American Black Walnut | T&G | `Handscraped Exotic Walnut (Color) T&G` (species dropped via "Walnut" trailing match) |
| Handscraped Maple | Maple | T&G | `Handscraped Maple (Color) T&G` |
| Designer | European White Oak | T&G | `Designer European White Oak (Color) T&G` (no dedup) |
| Regal | American White Oak | T&G | `Regal American White Oak (Color) T&G` (no dedup) |
| Continental | Pennsylvania | Click | `Continental (Pennsylvania) Click` (no dedup — Species field is empty for vinyl) |



> **Grade and box size placement:**
> - **Variant group, uniform box size (the common case):** Grade goes in `variant_option_one_value` (column 11) alone. Box size stays in the NAME — every row has the same one, so the names remain identical and LS is satisfied. Grade is not in the name.
> - **Variant group, mixed box sizes:** Box size cannot sit in the name without breaking name identity, so grade and box size go together in column 11 as `[Grade] - [sfb]sf/b`. Neither appears in the name.
> - **Single-grade product (only 1 row per handle):** Grade goes at the END of the name after the box size. Box size is in the name. Columns 10–11 are BLANK.
> - **No-grade product (Grade is empty):** Grade is nowhere. Box size is in the name. Columns 10–11 are BLANK.
>
> In every case sf/b ends up readable in Lightspeed. If a build produces a row where sf/b appears in neither the name nor column 11, that row is wrong — see the load-bearing rule above.

**Examples:**

- Variant group, uniform box size — sf/b in the shared name, grade alone in column 11: `GRNTENG - Elegance White Oak (Lecce) T&G | 6" x 19mm x RL - 3mm top - 28.42sf/b`
  - …with column 11 across the group: `Character`, `Select`, `Select & Better`
- Variant group, mixed box sizes — sf/b out of the name, into column 11: `VIDENG - HB 5 American White Oak (Macaroon) T&G | 5" x 18mm x RL - 3mm top`
  - …with column 11 across the group: `Select - 20.18sf/b`, `Select - 18.19sf/b`, `Select & Better - 18.19sf/b`
- Single-grade product (sf/b then grade at end): `GRNDENG - Continental European White Oak (Pennsylvania) Click | 7" x 6mm x RL - 23.62sf/b - ABCD`
- No-grade product (sf/b at end, no grade): `GRNDLAM - Continental (Pennsylvania) Click | 7" x 6mm x RL - 23.62sf/b`

> **Side effect in the mixed case — a class of duplicate-variant rejection resolves itself.** Two rows sharing a handle and a grade produce identical column 11 values and are rejected by LS as *Duplicate Variants*. In a mixed-box-size group, appending sf/b makes them unique (`Select - 20.18sf/b` vs `Select - 18.19sf/b`) and the group imports. Treat this as a signal, not a fix: two rows with the same handle and grade but different box sizes are usually two different products sharing a handle by mistake. In a uniform group the same collision cannot resolve this way — grade AND box size both match, so it is real duplicate data and must be fixed in Airtable.

### Description rules (column 8)

Populated with ALL unmapped source data. Format: `Field: Value | Field: Value | ...`

Contains every source column NOT already used in other LS fields (e.g. Product type, Category, Material type, Colour/tone, Layout pattern, Finish type, Install method, Locking system, Certifications, IIC/STC ratings, Volume pricing notes, Warranty, Traffic rating, Stock status, etc.). Empty and false fields are excluded. This ensures no product data is lost from the source sheet.

**Unmapped** = all source columns EXCEPT: id, SKU, Brand, Supplier, Product name, LS Handle, Collection, Species, Grade, Width, Thickness, Veneer, Install profile, Cost, Retail, Product type, Category, Material type.

### ⚠️ STRICT RULE — `Box size (sf)` is ALWAYS in the description

**Albert, 2026-09-03. Every product, without exception, carries its square feet per box in the description. If it also has `Pieces per box`, that goes in too.**

This is unconditional and overrides the "empty and false fields are excluded" default above, and it applies **regardless of where else sf/b appears**:

| Row | Description must contain |
|---|---|
| sf/b in the **name** (singletons, no-grade, uniform variant groups) | `Box size (sf): 24.18` — **still include it**, even though the name already says it |
| sf/b in **column 11** (mixed-box-size variant groups) | `Box size (sf): 24.18` |
| Has `Pieces per box` | `Pieces per box: 8` — always, alongside the box size |
| **Genuine per-piece item** (trims, thresholds, STONE, mosaics — `Box size (sf)` legitimately blank) | `Sold per piece` — state the unit explicitly. Never silently omit, and never invent a box size. |
| Per-**square-foot** item (e.g. underpad priced $/sf) | `Sold per sq ft` |

**This supersedes the previous rule**, which excluded box size from the description whenever it was already in the name. It is no longer conditional on placement.

**Why the duplication is safe here.** The load-bearing rule says "do not put sf/b in both places" — that is about **name vs column 11**, where the choice is forced by LS's name-identity constraint on variant groups, and picking both breaks the group. The description is a third, always-present location, and every one of them is generated from the same Airtable `Box size (sf)` field on each build. They cannot drift apart as long as the file is **regenerated** rather than hand-patched. Hand-editing one copy of a generated file is what makes duplicates go stale — so don't do that; rebuild.

**Why it is worth the duplication.** The description is the searchable, always-visible field at the POS. The name can be truncated in some views, a column-11 variant value only surfaces at the point of selection, and neither is guaranteed to be where a staff member is looking when they need to convert boxes to square feet. The description is the one place that is always there.

---

## Variant grouping rules

**Core principle:** Variants exist to signal a choice. Only group rows as variants when the customer/staff has an actual choice to make between grades of the same product. A variant group with only one option is noise, not structure.

**When to use a variant group (columns 10–11 populated):** 2+ rows share the SAME handle with DIFFERENT grade values. Same collection + same species + same color + same width + multiple grades = one parent product with grade as the variant dimension.

**When NOT to use a variant group:**
- **Only one row per handle** (even if it has a grade) — single-grade product. Leave columns 10–11 BLANK and append the grade to the end of the name after the box size.
- **Grade is empty/missing** — no-grade product. Leave columns 10–11 BLANK and don't put grade anywhere.
- **Different widths, species, collections, or colors** — these are separate parent products (different handles), not variants of each other.

**Decision table:**

| Scenario | Columns 10–11 | Grade in name? | sf/b lives in |
|----------|---------------|----------------|---------------|
| 2+ rows share handle, different grades, **same box size** | "Grade" / `[Grade]` | NO | **name** |
| 2+ rows share handle, different grades, **different box sizes** | "Grade" / `[Grade] - [sfb]sf/b` | NO | **column 11** |
| 1 row per handle, has a grade | BLANK | YES (at end after box size) | **name** |
| 1 row per handle, no grade | BLANK | NO | **name** |

**Sorting:** Sort all rows by handle (A→Z), then by grade (A→Z) within each handle group. Single-row handles sort by handle only.

### Handling future grade additions

If a single-grade product later gets a second grade added (converting it from a standalone product into a variant group), this is handled **manually, case-by-case** rather than through automated migration:

1. Compare the new grade's box size to the existing row's.
2. Rename the existing product to strip the trailing ` - [Grade]` from the name. **If the two box sizes match, leave the box size in the name.** If they differ, strip ` - [BoxSize]sf/b` as well — it now has to move into column 11 on both rows.
3. Populate columns 10–11 on the existing row (`variant_option_one_name` = "Grade", `variant_option_one_value` = `[Grade]`, or `[Grade] - [sfb]sf/b` in the mixed case).
4. Add the new grade as a second row sharing the same handle, following the same placement.
5. Re-upload both rows together. Lightspeed will merge them into a variant group under the existing handle.

Step 2 is the easy one to get wrong: leaving a box size in the name when the two grades box differently breaks name identity and LS rejects the second row.

This is expected to be rare. The name-embedded approach optimizes for the common case (one grade per handle) at the cost of a small rename operation when a second grade is eventually added.

---

## Accessories — transitions and mouldings

Transitions and mouldings must be **findable by supplier in one search**. Typing `Vidar Transition` into LS product search should return every T-moulding, reducer, and nosing Vidar sells — and nothing else. That requirement drives the format below.

### Name format

```
[Brand] - Transition | [Type] | [Material] | [Dimensions]
```

- `[Brand]` — the **full brand name, spelled out** (`Vidar`, `Grandeur`, `Floordi`). This is the search anchor and it **replaces the `[BRAND]ACC` name prefix** for this family. LS search does not match `Vidar` against `VIDACC`, so the abbreviated prefix defeats the entire purpose here.
- `Transition` — literal constant token, on every row in the family. This is what makes them searchable as a set.
- `[Type]` — canonical token from the controlled list below. Never free-text, never the supplier's spelling.
- `[Material]` — **which floor this transition matches.** See the source order below. Omit the segment if genuinely unknown — do not guess.
- `[Dimensions]` — length and profile detail: `94.5"`, `70.86" Square`, or `Cut Order` for made-to-order items. Omit if not in the source.

**The name is driven by product TYPE, not by LS category.** A nosing stays a nosing whether it lands in `ACCESSORIES` or in a vinyl category (see the Olympia routing table, where LVP nosings/reducers sit under `FLOORING / VINYL / SPC`). Category routing is unchanged by this rule.

### The `[Material]` segment — source order

A transition is bought to match a floor, so this segment must answer *"which floor?"*. No single Airtable field answers that for every product type, so resolve in this order and take the first that yields a useful token:

| Order | Source | Transform | Example |
|---|---|---|---|
| 1 | `Material type` | drop the word "core" | `SPC core` → `SPC`, `WPC core` → `WPC`, `HDF core` → `HDF` |
| 2 | `Category` | use as-is, shortened | `Laminate` → `Laminate`, `Engineered hardwood` → `Engineered` |
| 3 | `Species` | supplier's species code or full name | `AWO`, `European Oak`, `Ash` |

**`Hardwood plywood` is never used as the material token.** It is the literal `Material type` on every hardwood transition, but it describes the core of a plank rather than the floor being matched — no one searches for it. Fall through to Species instead: a stair nosing that matches American White Oak reads `AWO`, not `Hardwood plywood`.

**Deduplication — do not emit the token twice.** Skip the `[Material]` segment if the same token already appears in `[Type]` or `[Dimensions]` (case-insensitive, whole word). When restructuring an existing free-text name that already embeds the material — `Vidar SPC Nosing` — **extract** it into the `[Material]` slot rather than leaving it in place and appending a second copy. Correct: `Vidar - Transition | Nosing | SPC`. Wrong: `Vidar - Transition | SPC Nosing | SPC`.

> **Material type is currently blank on every accessory record.** Neither `Category` nor `Material type` is populated on Vidar's 20 accessories — the material exists only inside the free-text `Product name`. Populating these two fields on accessory records makes this segment deterministic instead of parsed, and has the side benefit of making accessories filterable in Bert, which they are not today.

### Controlled type tokens

| Token | Covers |
|---|---|
| `T-Moulding` | T-mould, T-molding, transition strip between equal-height floors |
| `Reducer` | reducer, carpet reducer, height transition |
| `Nosing` | flush / edge nosing |
| `Stair Nosing` | stair-edge nosing |
| `End Cap` | end cap, square nose |
| `Threshold` | doorway / threshold strip |
| `Quarter Round` | quarter round, shoe moulding |

**Spelling is load-bearing.** `T-Moulding`, `T-Molding`, and `T-Mould` are three different search results. Take the token from this table verbatim on every row — whatever the supplier price list calls it does not carry through.

### Worked examples (Vidar)

| Airtable Product name (current) | LS name | `[Material]` from |
|---|---|---|
| Vidar AWO Stair Nosing — 94.5" Square | `Vidar - Transition \| Stair Nosing \| AWO \| 94.5" Square` | Species (order 3) |
| Vidar European Oak Stair Nosing — 70.86" Square | `Vidar - Transition \| Stair Nosing \| European Oak \| 70.86" Square` | Species (order 3) |
| Vidar SPC T-Molding — Cut Order | `Vidar - Transition \| T-Moulding \| SPC \| Cut Order` | Material type (order 1) |
| Vidar SPC Reducer — Cut Order | `Vidar - Transition \| Reducer \| SPC \| Cut Order` | Material type (order 1) |
| Vidar SPC Nosing | `Vidar - Transition \| Nosing \| SPC` — material extracted, not duplicated; no length in source | Material type (order 1) |
| Vidar Laminate Nosing | `Vidar - Transition \| Nosing \| Laminate` — no length in source | Category (order 2) |

### What is NOT a transition

Only the controlled types carry the `Transition` token. Diluting it defeats the search. Adjacent families follow the same shape with their own anchor, so `Vidar Stair` and `Vidar Sundry` work as searches too:

- **Stair components** (stairboards, stair treads, stair risers) → `[Brand] - Stair | [Type] | [Material] | [Dimensions]`
- **Sundries** (underlay, underpad, glue, floor protection, vents) → `[Brand] - Sundry | [Type] | [Dimensions]` — no material segment; a bucket of glue does not match a floor

### Source data limitation — why the Airtable mirror matters

Accessory records carry **no structured type, profile, or dimension fields**. `Product type` is just `Accessory`, `Collection` is just `Accessories`, and there is no length or width. Everything is embedded in the free-text Airtable `Product name`. Building the LS name therefore means parsing that string, which is fragile and will drift.

**Mirror this format into the Airtable `Product name` itself.** Once Airtable holds `Vidar - Transition | T-Moulding | SPC | 94.5"`, the LS name is that same string and no parsing is needed — the transform becomes a copy. This is the Airtable-first principle applied to accessories: restructure at source, then generate. Until that happens, treat any parsed accessory name as provisional and eyeball the output.

### Renaming existing accessories

Adopting this format renames every existing accessory in Lightspeed. That is an UPDATE, not a re-create:

- **Column 1 `id` MUST be populated** from Airtable's Lightspeed ID on every row. A blank `id` on a renamed product creates a duplicate instead of renaming the original. Vidar's 20 accessory records already carry LS UUIDs, so this is available.
- **Handles do not change.** `VIDACCSPCNOSING` stays exactly as it is. The rename touches column 7 only — no handle churn, no variant-group impact.

---

The rules above (Variant grouping, Name construction, Description) were written for flooring — engineered hardwood, vinyl, laminate. Tile and STONE products follow the same column schema but with three structural differences. Read this section before generating any tile or STONE upload.

> **⚠️ Load-bearing principle — Lightspeed identifies a product by its NAME, not by its handle.**
> When LS imports, it groups rows into products **by the `name` field**. Two rows with the same `name` are treated as the same product — regardless of whether their handles differ. This drives three hard rules:
> 1. **Every row sharing a `name` must share one handle.** If the same name appears under two different handles, LS errors.
> 2. **Within a name, each `variant_option_one_value` must be unique.** Two rows with the same name AND the same variant value = *Duplicate Variants* rejection. Giving them different handles does **not** help — LS already merged them by name.
> 3. **Two genuinely different products must have different names.** If a collection+colour exists in two finishes, or two rows differ only by an edge/profile code, the distinguishing detail must appear in the `name` (or, for same-name same-size rows, in the variant value) — otherwise LS sees an incomplete or duplicate variant.
>
> Handle splitting alone never resolves a name collision. Always reconcile at the **name** level: unify the handle within a name-group, then make every variant value unique and non-empty. See the Olympia subsection for the worked failure modes.


### Differences from flooring at a glance

| Aspect | Flooring (ENG/HWD/LVP/LVT/LAM) | Tile (`Tile / Stone`) | STONE (`STONE`) |
|---|---|---|---|
| Variant dimension | Grade | **Size** | **Size** |
| LS product_category | `FLOORING / ENGINEERED HARDWOOD` etc. | `FLOORING / TILE` | `ACCESSORIES` |
| `[NAME_PREFIX]` example for CIF | n/a | `CIFDTIL` | `CIFDSTN` |
| Source unit | per sq ft | per sq ft (tiles) / per piece (mosaics, decor) | per piece |
| Box size (sf) | present | present for tile, blank for per-piece items | always blank |

### Name prefix

Follows the same `[brand abbrev][product type abbrev]` convention as flooring:

- **`[BRAND]TIL`** — all rows where Airtable Category = `Tile / Stone` (includes mosaics, field tile, large-format slabs, wall tile)
- **`[BRAND]STN`** — all rows where Airtable Category = `STONE` (marble/quartz thresholds, shower jambs, benches)

Example brand prefixes:

| Brand | Tile prefix | STONE prefix |
|---|---|---|
| CIF Distributors | `CIFDTIL` | `CIFDSTN` |

### Category routing

| Airtable Category | LS product_category |
|---|---|
| `Tile / Stone` | `FLOORING / TILE` |
| `STONE` | `ACCESSORIES` |

The `STONE` Airtable category maps to LS `ACCESSORIES` (same as mouldings, stair treads, underlay) — not to a new LS category. STONE items are accessories to a tile installation from the POS perspective: staff ring them up alongside the tile they go with, not as a separate flooring category.

### Variant dimension = Size

For tile and STONE, **Size is the variant dimension** — analogous to how Grade works for engineered hardwood. The decision table:

| Scenario | Columns 10–11 | Size in name? |
|----------|---------------|----------------|
| 2+ rows share handle, different sizes | `Size` / size-with-sfb value | NO |
| 1 row per handle (single-size product) | BLANK | YES (in name) |

When 2+ tile rows share an LS Handle with different sizes, they form a variant group. Names are identical across all rows in the group (LS requirement). Size goes in column 11.

### Size dropdown value — includes sf/b

For tile variant rows, `variant_option_one_value` (column 11) carries **both the size AND the box size**, formatted as `[size] - [sfb]sf/b`. This puts the box-size info at point of selection in the POS so staff can see it without drilling into the product.

> Tile variant groups are always the "mixed" case by definition — the variant dimension *is* size, so box sizes differ across the group and the shared name cannot carry sf/b. Flooring variant groups reach column 11 only when their box sizes genuinely differ; when every grade boxes the same, sf/b stays in the name. Same principle, different frequency. See *Load-bearing rule — every SKU must carry a readable sf/b*.

| Source row | LS column 11 value |
|---|---|
| Aldo Bianco 12 x 24 (sf/b = 15.52) | `12 x 24 - 15.52sf/b` |
| Aldo Bianco 32 x 32 (sf/b = 21.33) | `32 x 32 - 21.33sf/b` |
| Subway White 3 x 6 (sf/b = 17.00) | `3 x 6 - 17.00sf/b` |
| Threshold Bianco Cararra 1.5 x 36 x 3/8 (no sf/b — per piece) | `1.5 x 36 x 3/8` |

Format the sf/b number with two decimals. If `Box size (sf)` is blank (per-piece items: mosaic decor, thresholds, jambs, benches), include just the size with no ` - [sfb]sf/b` suffix.

### Name format — tile

For tile rows specifically:

**Variant rows (2+ rows share handle):**
```
[NAME_PREFIX] - [Collection] ([Colour])
```
No size, no finish, no sf/b — those would break the identical-name rule. Size and sf/b live in column 11 (`variant_option_one_value`). Finish lives in the description.

**Singletons (1 row per handle):**
```
[NAME_PREFIX] - [Collection] ([Colour]) | [Size] | [Finish] - [sfb]sf/b
```
All four components present when source data has them. The `| [Size]` segment is omitted only if size is unparsable; `| [Finish]` is omitted only if Airtable Finish type is blank; `- [sfb]sf/b` is omitted only if Box size (sf) is blank (per-piece items).

Examples:

| Row type | LS Name |
|---|---|
| Variant (Alma Light, polished, 5 sizes share handle) | `CIFDTIL - Alma (Light)` (identical across all 5 rows) |
| Variant (Buckingham Azul, 2 sizes, mixed finishes: floor porcelain + ceramic wall) | `CIFDTIL - Buckingham (Azul)` (identical across both rows — finish varies and goes in description) |
| Singleton (8098 Travertine Silver) | `CIFDTIL - 8098 (Travertine Silver) \| 12 x 24 \| Polished - 16.00sf/b` |
| Singleton, no finish in source (Cristalli Pencil) | `CIFDTIL - Cristalli Pencil (Bianco) \| 1 x 5` |
| Singleton, no finish + no sf/b (per-piece decor) | `CIFDTIL - Boemia Single Decor (Ecru) \| 5 x 5` |

**Critical: finish is in the name for singletons ONLY.** For variant rows, the name is just `[NAME_PREFIX] - [Collection] ([Colour])` — no finish, no size, no sf/b. Finish often varies across sizes in a variant group (e.g. Buckingham Azul has a 13×13 floor porcelain in "Glazed matte" and an 8×20 ceramic wall in "Glazed glossy"), and LS requires every row in a variant group to share an identical Name. If finish is in the variant Name, the names differ across the group and LS rejects subsequent rows with *"Handle already exists"* — interpreting them as conflicting products trying to claim the same handle.

### Name format — STONE

For STONE rows (per-piece fabricated marble/quartz):

```
[NAME_PREFIX] - [Item type] [Colour] [| Size]
```

Item type is parsed from Airtable Product name (the first em-dash-separated segment for STONE rows): `Threshold`, `Shower Jamb`, or `Bench`.

Examples:

| Row type | LS Name |
|---|---|
| Variant (Bianco Cararra threshold, 5 sizes) | `CIFDSTN - Threshold Bianco Cararra` (identical across all 5) |
| Singleton (Bianco Cararra bench) | `CIFDSTN - Bench Bianco Cararra \| 48 x 16 x 5/8` |

STONE rows never carry sf/b — they're per-piece items by definition.

### Source sheet parsing — tile Product name format

Tile rows in Airtable use a four-segment em-dash-separated `Product name`:

```
[Collection] — [Colour] — [Size] ([Finish])
```

The LS upload parses this with a regex split on `\s+—\s+`. **Critical**: the Colour segment must always be present, even when Colour equals Collection (e.g. `Artico — Artico — 11.5 x 23.3 (Matte)`). Without the second segment, the splitter sees only three parts and the size parser collapses to the parens-only finish, leaving Size empty — which produces `variant_option_one_name = "Size"` with a blank value, which LS rejects with *"Name or value for option 1 of this variant is missing"*.

If you encounter a 3-segment tile Product name during parsing, fall back: when `parts[-1]` is purely a parenthesized expression that strips to empty, use `parts[-2]` as the size. This is a defensive fallback for legacy or malformed Airtable rows — the proper fix is to repair the Airtable Product name so colour is always its own segment.

### STONE handle generation

If the source sheet has `STONE` rows with a blank `LS Handle / Parent ID`, generate handles in-line during the LS upload build using the schema-documented pattern:

```
[BRAND_PREFIX]STN[ITEMTYPE_TOKEN][COLOUR_TOKEN]
```

Where:
- `[BRAND_PREFIX]STN` is the brand's STONE prefix (e.g. `CIFDSTN`)
- `[ITEMTYPE_TOKEN]` is `THRESHOLD`, `JAMB`, or `BENCH` (parsed from the first em-dash segment)
- `[COLOUR_TOKEN]` is the Colour / tone value with all non-alphanumeric characters stripped, uppercased

The proper fix is to populate Airtable `LS Handle / Parent ID` for all STONE rows at ingest time per the bert-airtable-schema CIF section — the LS-upload-side generation is a fallback.

### Description for tile and STONE

Same rule as flooring: include all unmapped source fields as pipe-delimited text. For tile and STONE the most useful fields to include in the description are:

`Tile format | Finish type | Material type | Colour / tone | Box size (sf) | Pieces per box | Layout pattern | Salesperson notes`

Box size goes in the description for **both variant and singleton rows** — this is the same strict rule that now applies to every product (see *Description rules (column 8)*), not a tile-specific allowance. Tile is simply where the practice started.

Per-piece tile and STONE (thresholds, jambs, benches, listellos, pencils, decors) genuinely have no box size: the description states **`Sold per piece`** and carries `Pieces per box` where the supplier gives one. Never leave the question unanswered, and never invent a box size.

---

### Olympia Tile — supplier-specific LS rules

Olympia Tile is a tile/stone/vinyl supplier whose Zone AT catalogue produces ~3,028 LS rows across three product families. Its source `Product name` format (from the bert-airtable-schema Olympia ingest) is `Collection — Colour (Finish) — Size`. Three Olympia quirks broke the standard LS build and must be handled — all three trace back to the **name-identity principle** above.

#### Family routing

| Airtable Category | Product type | LS product_category | Name prefix |
|---|---|---|---|
| `Tile / Stone` | Flooring | `FLOORING / TILE` | `OLYMTIL` |
| `Tile / Stone` | Moulding (ceramic trims) | `ACCESSORIES` | `OLYMTIL` |
| `LVP` / `LVT` | Flooring | `FLOORING / VINYL / SPC` | `OLYMLVP-SPC` / `OLYMLVT-SPC` |
| `LVP` / `LVT` | Moulding (nosing/reducer) | `FLOORING / VINYL / SPC` | `OLYMLVP-SPC` / `OLYMLVT-SPC` |
| `STONE` | Flooring | `ACCESSORIES` | `OLYMSTN` |

#### Quirk 1 — Commas in SKUs (LS rejects)

Olympia uses European decimal commas in ~109 stock codes (e.g. `LW.AL.SIL.0,8X1,8.BD`, `IO.ANG.BUT.0,48X0,48`). LS permits `. - _ /` in the `sku` field but **rejects commas** ("SKU codes can only have letters, numbers and …"). 

**Rule:** replace every `,` → `.` in the SKU before writing the LS file (`LW.AL.SIL.0,8X1,8.BD` → `LW.AL.SIL.0.8X1.8.BD`). Apply the same replacement to Airtable's `SKU`/`Supplier SKU` **at ingest, when the record is first created**, so both systems store the dotted form from the outset (see the bert-airtable-schema Olympia note).

> **Not a licence to rewrite existing SKUs.** This is a minting rule for new records.
> If comma-form SKUs are already stored in Airtable, changing them is a human-approved
> migration that updates LS and Price History Log v2 together — never an in-place edit
> and never something an upload run does on its own. See RULE 0.

#### Quirk 2 — Finish-spanning collections (finish must go in the NAME)

The standard tile rule keeps finish *out* of the variant name (finish lives in the description, names stay identical within a handle group). That holds **only within one handle group**. Olympia frequently sells the same collection+colour in **two finishes** (e.g. Colour And Dimension *Arctic White* in Bright and Matte; Metropolis *White* in Gloss and Matte). These are two separate products (two handles), but the standard name omits finish → both get the identical name `OLYMTIL - Colour And Dimension (ARCTIC WHITE)` → LS merges them by name and sees duplicate sizes.

**Rule:** for tile rows, if a `(prefix, collection, colour)` combo spans **more than one finish**, append the finish to the name: `OLYMTIL - Colour And Dimension (ARCTIC WHITE) Bright` vs `… Matte`. When the combo has only one finish, follow the standard rule (finish stays out of the variant name, goes to description).

#### Quirk 3 — Edge/profile suffix codes (same name + same size collisions)

Olympia appends edge/profile codes to otherwise-identical stock codes:
- `.RD` vs `.VR` — edge treatments (e.g. `ES.AC.ALM.0416.RD` / `.VR`), same colour/size/finish.
- `.32` / `.33` / `.34` / `.35` — trim-profile pieces (round-edge long side, corners) carrying the same nominal size as the field tile.
- `.MT` vs `.MT.DC` — plain vs decor at the same size.

After Quirk-2 naming, these still produce **same name + same size value** → *Duplicate Variants*. They are genuinely distinct products, not size-variants of each other.

**Rule (name-group reconciliation — run as a final pass over all built rows):**
1. Group all output rows by their final `name`.
2. For each name-group with 2+ rows: force a single shared `handle` (use the most common handle in the group), set `variant_option_one_name = "Size"` for every row.
3. Give every row a **unique, non-empty** `variant_option_one_value`. Seed it from the parsed size + sf/b (e.g. `2.95 x 11.81 x 0.31 - 12.16sf/b`). If two rows still share a value, append the shortest distinguishing trailing SKU token in parens: `… - 12.16sf/b (0312.MT.33)`. If trailing tokens can't disambiguate (difference is a leading token, e.g. `KV`/`MKV`, or the known `HV`/`THV` typo), fall back to the full alphanumeric SKU.
4. A name-group of exactly one row stays a standalone product (variant columns blank for tile singletons).

This pass makes the file satisfy all three LS identity rules simultaneously: one name → one handle, unique non-empty variant values, no duplicate (name, value) pairs.

#### Known Olympia source typo

Three Chimewood glue-down codes are misprinted with a leading `T`: `THV.CW.ICE.0748.GLUE`, `THV.CW.LBW.0748.GLUE`, `THV.CW.TPE.0748.GLUE`. Preserved verbatim (matching Airtable); they surface as leading-token collisions handled by the reconciliation fallback. Flag for Olympia to correct at source.

#### STONE retail

Olympia STONE rows (thresholds, shower jambs) carry `Retail price/unit = 0` pending Albert's markup decision — they import with retail 0 until set. Not an LS error.


---

## Handle format

> **CRITICAL — Lightspeed restriction:** Handles can ONLY contain letters and numbers. No hyphens, spaces, dots, underscores, or any other symbols. Lightspeed will reject the import if handles contain non-alphanumeric characters. **The Airtable "LS Handle / Parent ID" field stores handles in LS-ready format (alphanumeric only), so the LS upload copies the value straight through with no transformation.**

**The rule:** Read `LS Handle / Parent ID` from Airtable. Copy it into LS column 2 as-is. Do not transform, prefix, suffix, reformat, or "normalize" the handle in any way. Whatever is in Airtable is what goes to Lightspeed.

Do NOT build handles from scratch. Do NOT try to reconcile one brand's handle format against another's. If a handle in Airtable doesn't match the descriptive pattern of another brand, that is not a problem to fix — handle format is per-brand and set at the Airtable level.

**The only exception** is if a handle contains non-alphanumeric characters (hyphens, dots, spaces, etc.) — that is malformed Airtable data and must be corrected at the source before upload. The LS upload process itself never edits handles.

**Observed patterns** (descriptive — for recognizing which brand a handle belongs to, NOT for enforcement):

| Handle | Brand | Breakdown |
|--------|-------|-----------|
| VIDR6AWOSILVERSTONE | Vidar | VIDR + 6 + AWO + SILVERSTONE |
| VIDRHB5AWOMACAROON | Vidar | VIDR + HB5 + AWO + MACAROON |
| VIDRLAMSD25 | Vidar | VIDR + LAM + SD25 |
| LVP71LAMMISTYGREY | NAF/FAW | LVP + 71 + LAM + MISTYGREY (category-first, no brand code) |
| ENG65HICBRONZE | NAF/FAW | ENG + 65 + HIC + BRONZE |

Different brands use different conventions. Both Vidar's brand-first pattern and FAW's category-first pattern are valid — the rule is only that the handle is alphanumeric and matches between Airtable and LS.

**Species abbreviations** (used when reading handles for pattern recognition; not used for building them):

| Abbreviation | Species |
|-------------|---------|
| AWO | American White Oak |
| EWO | European White Oak |
| EWA | European White Ash |
| BW | Black Walnut |
| AH | American Hickory |
| HIC | Hickory |
| MAP | Maple |
| WAL | Walnut |
| OAK | Oak (generic) |

---

## Source sheet schema (required columns)

The source data sheet (any brand) MUST contain these columns:

| Source Column | Maps To / Used For |
|--------------|-------------------|
| id | LS column 1 (id). Copy as-is. Blank = new product, populated = update existing. |
| SKU | LS column 3 (sku). Unique per row. |
| Brand | LS columns 23 & 24 (brand_name, supplier_name). |
| Product name | Color extraction: text between "—" and "(". |
| LS Handle / Parent ID | LS column 2 (handle). Variant grouping key. |
| Collection | LS name. Remove " Collection" suffix. |
| Species | LS name. Full name, not abbreviation. |
| Grade | LS column 11 (variant_option_one_value) for variant groups — alone when the group's box size is uniform, or as `[Grade] - [sfb]sf/b` when it is mixed — OR appended to LS name for single-grade products. See Variant grouping rules. |
| Width (in) | LS name. Append ". |
| Thickness (mm) | LS name. Append "mm". |
| Veneer / top layer (mm) | LS name. Only if non-empty. Append "mm top". |
| Install profile | LS name. "T&G" or "Click". |
| Cost/unit | LS column 17 (supply_price). Always. See Pricing field reflection rule. |
| Retail price/unit | LS column 18 (retail_price). Always. See Pricing field reflection rule. |
| Box size (sf) | LS name (singletons and uniform-box-size variant groups) or LS column 11 with the grade (mixed-box-size variant groups only). Append "sf/b". **Mandatory for all flooring** — see the load-bearing rule. |
| All other columns | LS column 8 (description). Pipe-delimited: "Field: Value | Field: Value". Excludes empty/false values. |

---

## Pre-upload checklist

- ☐ **Every row for a product that already exists in Lightspeed carries its
  `Lightspeed ID` in column 1 (`id`).** A blank `id` on an existing product makes LS
  **create a duplicate instead of updating it**. Populate from Airtable's
  `Lightspeed ID` (`fldQhbI35Ng2ZxNKL`) for every matched row; leave blank *only* for
  genuinely new products, where LS assigns the UUID on import. This is the LS-side
  twin of the SKU-duplication trap — the 2026-09-03 Grandeur file was built with all
  231 ids blank, which would have duplicated 212 live products.
- ☐ Every row has a unique SKU (column 3)
- ☐ **Handles contain ONLY letters and numbers** — no hyphens, dots, spaces, or symbols (strip from source before upload)
- ☐ **SKUs contain only letters, numbers and `. - _ /`** — NO commas or spaces (LS rejects commas; replace `,`→`.` — see Olympia subsection)
- ☐ **Name-identity rules satisfied** — every shared `name` maps to one handle; each variant value within a name is unique and non-empty; no two products share an identical name without being a variant group (see the name-identity principle in Tile and STONE products)
- ☐ **Variant groups only when 2+ rows share a handle with different grades** — never create a one-option variant
- ☐ Within a true variant group: rows share identical names but have different grades in column 11
- ☐ **No duplicate variants** — within a handle group, every column 11 value must be unique. Two rows matching on BOTH grade and box size are real duplicate data — flag as a data issue, don't disambiguate artificially
- ☐ **Grade placement is correct:**
  - Variant group, uniform box size → `[Grade]` alone in column 11, NOT in name
  - Variant group, mixed box sizes → `[Grade] - [sfb]sf/b` in column 11, NOT in name
  - Single-grade product (1 row, has grade) → grade at END of name after sf/b, columns 10–11 BLANK
  - No-grade product (1 row, no grade) → grade nowhere, columns 10–11 BLANK
- ☐ **EVERY row with a `Box size (sf)` value exposes sf/b somewhere readable in LS** — in the name (singletons, no-grade products, uniform-box-size variant groups) or in column 11 (mixed-box-size variant groups). A row with sf/b in neither is a build error. Per-piece items (accessories, STONE, mosaics) with genuinely blank box size are exempt.
- ☐ **No flooring row has a blank `Box size (sf)`** — plank/tile flooring with no box size is an Airtable data defect; flag and fix at source before upload rather than shipping the row without it
- ☐ **Box-size uniformity computed per handle group** — distinct `Box size (sf)` values counted across each group *before* names are built; placement follows from that count
- ☐ **Box size (sf/b) placement is correct:**
  - Single-grade / no-grade product → sf/b in name (before grade suffix)
  - Variant group, uniform box size → sf/b in the shared name; column 11 = grade alone
  - Variant group, mixed box sizes → sf/b OMITTED from name, carried in column 11 as `[Grade] - [sfb]sf/b`, and echoed in description for POS search
  - sf/b formatted to two decimals wherever it appears in column 11
- ☐ variant_option_one_name AND variant_option_one_value are BLANK for every single-row handle (regardless of whether grade is present)
- ☐ **Transitions/mouldings follow the searchable name format** — `[Brand] - Transition | [Type] | [Material] | [Dimensions]`, full brand name spelled out, `Transition` token present, type token taken verbatim from the controlled list
- ☐ **Renamed accessories carry their `id`** — every accessory row whose name changed has the Lightspeed UUID in column 1, or the import creates duplicates instead of renaming
- ☐ **Name dedup applied** — if Collection contains Species, Species dropped from name; if Collection ends with Install, Install dropped from name
- ☐ **supply_price ← `Cost/unit` and retail_price ← `Retail price/unit`** for every row (the only valid source for these two columns; never blank for priced products, including per-piece accessories)
- ☐ supply_price and retail_price are numeric (no $ signs, no commas)
- ☐ active = 1 for all new products
- ☐ outlet_tax column header suffix matches your Lightspeed outlet name
- ☐ Rows sorted by handle (A→Z), then grade (A→Z)
- ☐ Veneer in name only when source has a value
- ☐ **id column copied from Airtable source** — populated rows will UPDATE existing LS products; blank rows will CREATE new ones. Never leave blank for products that already have an LS UUID in Airtable.
- ☐ brand_name and supplier_name match the source Brand/Supplier columns
- ☐ description contains all unmapped source fields as pipe-delimited text
- ☐ **EVERY row's description states its square feet per box** — `Box size (sf): <n>` where the product has one, or `Sold per piece` / `Sold per sq ft` where it genuinely does not. No exceptions, including rows whose name or column 11 already carries sf/b. Assert this over the whole file, not by spot-check: a row with neither is a defect.
- ☐ **`Pieces per box` is in the description on every row that has one**

---

## Notes

- The LS product name is for POS/internal use only. Website names managed separately.
- If a new brand is introduced, confirm `[NAME_PREFIX]` and `[HANDLE_PREFIX]` with user first.
- SPC and Laminate follow a different schema — not covered here.
- Source sheet column names must match the schema above. Map different column names first.