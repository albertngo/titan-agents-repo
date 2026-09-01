---
name: bert-airtable-schema
description: "The master reference for Titan Flooring's Airtable database schema — covering every field in the Master Flooring Catalogue and Price History Log tables. Use this skill whenever working with Titan's product data, including: entering or importing products into Airtable, processing supplier price lists (extracting pricing, handling SALE items, applying promo cost logic, assigning stock status), generating Airtable-ready spreadsheets or CSVs, building Lightspeed upload files, answering questions about field meanings or data entry rules, creating or updating product records, validating data against the schema, debugging Cowork automation issues, or any task involving SKUs, pricing markup rules, promo flows, or the Master Flooring Catalogue structure. Also trigger when the user mentions Bert, Cowork, Lightspeed import, supplier price lists, flooring product data, Floors At Work, FAW, or Airtable fields by name."
---

# Bert — Airtable Schema Guide

Master Flooring Catalogue + Price History Log | Titan Flooring Inc. | Internal Use Only

## Purpose

This guide explains every field in the Bert Airtable base — what it is, how to fill it in, and why it matters. It is the reference document for anyone entering products, updating pricing, or building automation on top of this data.

The base has two tables: **Master Flooring Catalogue** (the product database) and **Price History Log** (the append-only pricing audit trail).

---

## How the base works

### Three layers of data

Every product record in the Master Flooring Catalogue serves three consumers simultaneously:

- **Bert** (the AI tool) — reads product specs, pricing, and suitability fields to answer customer and staff queries
- **Cowork** (the automation agent) — reads Supplier SKU to match incoming price lists, writes to pricing fields, and logs changes to the Price History Log
- **Lightspeed** (the POS system) — receives product data via import; Lightspeed ID and LS Handle / Parent ID are populated after upload

### Pricing rule

All products follow a single flat markup:

**Retail price/unit = Cost/unit + $1.00**

This applies to every category.

### Promo pricing flow

When a supplier posts a promotional cost:

- Cowork reads the supplier communication and identifies the SKU, promo cost, and end date
- Cowork writes Promo cost ($/sf) with the supplier's promotional cost, and sets Promo end date
- Bert sees the Promo cost and flags to the team that a promotion is active on this product. The retail price is adjusted manually during the sale — it is not auto-calculated from the promo cost.
- When the end date passes, Cowork clears both fields and Bert reverts to regular pricing

**Promo end date default (global rule, added Jul 2026):** unless the supplier specifies an end date, set `Promo end date` = the **last day of the month** the promo sheet applies to. If a promo is confirmed ongoing past its printed end date without a new date, roll the end date to the last day of the current month and note the extension. Never leave a promo open-ended with a blank end date.

### Promo product not found in catalogue

When scanning a supplier promo sheet, a promoted grade or colour may not exist as a record in the Master Flooring Catalogue. In this case:

- **Do not apply the promo cost to an incorrect grade** (e.g. do not put a Character promo on a Select record)
- **Create a new product record** for the missing grade, copying all available specs from the closest matching record (same colour, same width, different grade)
- Set **Cost/unit = Promo cost ($/sf)** — since no original cost is available, the promo cost is used as a placeholder per the Sale item pricing logic rule 3
- Set **Retail price/unit = Cost + $1.00**
- Set **Promo cost ($/sf)** and **Promo end date** as per the promo sheet
- For fields that cannot be confirmed from existing records (e.g. Collection), **leave blank** rather than guessing — do not copy fields that may differ by grade
- Flag the new record to the team so specs can be verified with the supplier

### Sale item pricing logic

When processing a supplier price list, some products are marked as SALE items with a reduced cost. These are promotional prices and should be handled differently from regular pricing. Follow this priority order to determine the original (non-promo) cost:

1. **Same collection, same section** — if the SALE item sits within a collection that also lists a regular (non-SALE) price for the same product specs, use that regular price as the original Cost/unit. The SALE cost goes into Promo cost ($/sf).

2. **Previous price list** — if no regular price exists in the current price list, check the most recent previous price list from the same supplier. Use that cost as the original Cost/unit. The SALE cost goes into Promo cost ($/sf).

3. **Use promo cost as original** — if neither source provides an original cost, use the SALE cost as Cost/unit. Retail price/unit = SALE cost + $1.00. The SALE cost still goes into Promo cost ($/sf) as well. When Cost and Promo cost show the same value, this signals that the original cost was not available and the promo cost was used as a placeholder.

In all cases, Promo cost ($/sf) = the supplier's SALE cost as-is. The regular Retail price/unit = Cost + $1.00. Retail adjustment during a promo is done manually.

### Stock status assignment rules

When entering products from a supplier price list, Stock status should be assigned as follows:

- **Blank (default)** — most products. Do not assume a product is "In stock" unless explicitly confirmed by the supplier or your own inventory system. Leave blank when the price list does not indicate stock status.
- **Clearance** — use only when the supplier explicitly marks a product as "while stock last," "clearance," "closeout," or similar language indicating the product is being phased out with limited remaining inventory.
- **Discontinued** — use when the supplier confirms the product is no longer being manufactured or restocked.
- **SALE items are NOT Clearance** — a SALE label on a price list indicates a promotional price, not a stock status. SALE items get a Promo cost but their Stock status remains blank unless separately marked as clearance or while-stock-last.

### Grade translation rule

The `Grade` field captures the wood quality tier as stated by the supplier. Four grades are canonical and serve as reference anchors; any other grade a supplier uses is stored **verbatim** as a new single-select option when it unambiguously represents a grade tier.

**Four canonical Grade values (the primary reference points):**

- Select & Better
- Select
- Character
- Rustic

**Letter-grade mapping (always collapses to the canonical 4):**

| Supplier says | Airtable Grade |
|---|---|
| AB | Select & Better |
| ABC | Select |
| ABCD | Character |
| EF | Rustic |

Letter grades (European system) always map to the canonical North American word grades — never stored verbatim as "AB", "ABC", etc.

**Word grades are stored verbatim.** When a supplier explicitly states a grade by name — "Distressed Grade", "Prestige Grade", "Excel Grade", "Royal Grade", "Prime Grade", etc. — store the exact supplier wording in the `Grade` field as a new single-select option. Airtable's `typecast` flag auto-creates the option on first use. Add a note in `Salesperson notes` that conveys the approximate relationship to the canonical 4 if useful (e.g. "Distressed Grade is similar in appearance to Character/Rustic but is not formally mapped").

**"Distressed Grade" is stored verbatim.** This is a common case and needs specific handling:

- Supplier says **"Distressed Grade"** → `Grade = Distressed Grade` (verbatim)
- Supplier says **"Wirebrushed & Distressed Grade"** or **"Handscraped & Distressed Grade"** → strip the finish descriptor (Wirebrushed / Handscraped belongs in `Finish type`), Grade = `Distressed Grade` only
- Supplier says **"Handscraped and Distressed"** or **"Wirebrushed & Distressed"** (without the word "Grade") → this is **finish language, NOT a grade**. Grade = **blank**. Populate `Finish type` with the finish descriptors. Add a note to Salesperson notes clarifying this is finish-only.

The rule for distinguishing grade-from-finish: **the word "Grade" must be present** in the supplier's label (or the context must make it unambiguous that they're naming a quality tier). "Distressed Grade" is a grade. "Handscraped and Distressed" is two finishes. The presence of the word "Grade" is the signal.

**Do not guess.** If a supplier uses shorthand or partial codes without context (e.g. "A" alone, "BC", "B", "Prime" with no "Grade" word and unclear context), do not invent a mapping. Leave `Grade` blank, preserve the supplier's wording in `Salesperson notes`, and flag for supplier clarification.

**How Bert understands the relationships:**

Bert knows the following fuzzy equivalences and can surface related products when a customer asks in natural language:

- "Character" or "character grade" → surface Character, Distressed Grade, and any other character-adjacent grades, with honest labeling of which is formally what
- "Rustic" or "rustic look" → surface Rustic, Distressed Grade, ABCD/Character equivalents
- "Clean" or "minimal character" → surface Select, Select & Better, Prime (if present)
- "Distressed" → surface Distressed Grade (grade) AND products with Handscraped/Wirebrushed-and-Distressed finishes, while making the distinction between grade and finish clear to the customer

Bert never conflates grade with finish when pricing or quoting — if a customer specifically asks for "Distressed Grade", only products with that exact Grade value are quoted; products with merely a "distressed" finish are offered as similar alternatives, labeled as such.

**Summary of decision flow:**

1. Supplier states a grade using the word "Grade" (e.g. "Select", "Distressed Grade", "Prestige Grade") → store verbatim in `Grade` field
2. Supplier uses letter grade (AB, ABC, ABCD, EF) → map to canonical 4
3. Supplier uses grade-adjacent word without "Grade" ("Distressed", "Character-look") → this is **finish or visual description**, leave `Grade` blank, use `Finish type` / Salesperson notes
4. Supplier says nothing about grade → `Grade` blank

---

## Field tags

| Tag | Colour | Meaning |
|-----|--------|---------|
| **LS** | Blue | Maps to a Lightspeed field — used in the LS import file |
| **Bert** | Green | Read by Bert to answer queries — keep accurate and complete |
| **Auto** | Amber | Populated automatically by Cowork — do not edit manually |

---

## Table 1 — Master Flooring Catalogue

The source of truth for all Titan flooring products. Every active product that Bert can recommend or price must have a record here.

### Identity

| Field name | Type | Description | Notes |
|------------|------|-------------|-------|
| **SKU** | Single line text | Internal product code. Primary key — unique across all records. Format: CAT-SUPP-0001 e.g. ENG-VIDR-0042 | LS · Bert — never change after creation |
| **Product name** | Single line text | Human-readable name including colour and grade. e.g. Vidar 7.5" AWO — Macaroon (Character) | LS · Bert |
| **Brand** | Single line text | The product brand. May differ from Supplier — e.g. BOEN sold by Canadian Standard | LS |
| **Supplier** | Single select | Which supplier this product is ordered from. Choose from the controlled list. | Bert |
| **Supplier SKU** | Single line text | Supplier's own product code if they use one. Leave blank if supplier does not assign codes. Cowork uses this for price list matching. | Auto — blank if no supplier code |
| **Lightspeed ID** | Single line text | Lightspeed's internal record ID. Populated after LS upload. Do not fill in manually. | LS — populated post-upload |
| **LS Handle / Parent ID** | Single line text | Groups grade variants under one parent in Lightspeed. Shared by all grades of the same colour and width. **Must contain only letters and numbers — no hyphens, dots, spaces, or symbols.** This value is copied directly into Lightspeed on upload; LS rejects non-alphanumeric handles. Format: `[HANDLE_PREFIX][SizePrefix][SpeciesAbbrev][COLOR]` e.g. VIDR6AWOSILVERSTONE | LS |
| **Collection** | Single line text | Product line or series name. e.g. 6 Collection, 7.5 Collection, Chevron Collection | LS · Bert |
| **Product type** | Single select | Top-level type. Flooring / Accessory / Moulding / Hardware / Adhesive / Underpad | LS · Bert |
| **Category** | Single select | Flooring format/shape category. **LVP** (luxury vinyl plank), **LVT** (luxury vinyl tile), Engineered hardwood, Solid hardwood, Laminate, Tile / Stone, **STONE**, Carpet. `Tile / Stone` is for installed tile, mosaic, and slab products (floor or wall). `STONE` is a separate category reserved for fabricated marble and quartz pieces sold per-piece — thresholds, shower jambs, and benches. Do not mix the two: a 12×24 porcelain field tile is `Tile / Stone`; a 4×48 Bianco Carrara threshold is `STONE`. Note: SPC and WPC are core construction types — they live in Material type, not Category. A product can be "LVP" (category) with "SPC core" (material type) simultaneously. | LS · Bert |
| **Material type** | Single select | Core material / construction type. Vinyl: **SPC core**, **WPC core**. Hardwood: Hardwood plywood. Tile: Porcelain, Ceramic. Stone (under either `Tile / Stone` or `STONE` category): Marble, Quartz, Glass, Mother of pearl, Stainless steel, and mixed-material values (Glass / stone, Marble / stone, Metal / glass, Metal / stone, Porcelain / glass, Glass / mixed) for mosaics and decorative pieces. This is where SPC vs WPC is captured for vinyl products — not in Category. | Bert |
| **Species** | Single select | Wood species. Engineered and solid hardwood only. e.g. American White Oak, European White Ash, American Black Walnut | Bert |
| **Colour / tone** | Single select | General colour tone used for filtering. Light / Medium / Dark / Grey / White / Natural / Multi | Bert |
| **Grade** | Single select | Wood quality tier as stated by the supplier. Four canonical values (Select & Better, Select, Character, Rustic) plus any verbatim supplier-stated grade that uses the word "Grade" (e.g. Distressed Grade, Prestige Grade). Letter grades (AB, ABC, ABCD, EF) collapse to the canonical 4. Finish language alone ("Handscraped and Distressed") is NOT a grade — leave blank. See *Grade translation rule* under "How the base works". | Bert |
| **Layout pattern** | Single select | Standard (default — most planks), Herringbone, Chevron, Versailles, Mosaic. Only fill if non-standard. | Bert |

### Product specs

| Field name | Type | Description | Notes |
|------------|------|-------------|-------|
| **Width (in)** | Number | Plank or tile width in inches. | Bert |
| **Thickness (mm)** | Number | Overall product thickness in mm. | Bert |
| **Wear layer (mil)** | Number | LVP / SPC only. Wear layer in mil. e.g. 12, 20, 22. Leave blank for hardwood. | Bert |
| **Veneer / top layer (mm)** | Number | Engineered hardwood only. Top veneer thickness in mm. e.g. 2, 3, 4. Affects sanding potential. | Bert |
| **Veneer cut type** | Single select | How the veneer is cut. Dry sawn / Sawn mill (SM) / Rotary. | Bert |
| **AC rating** | Single select | Laminate abrasion rating. AC1 (light residential) to AC6 (heavy commercial). Leave blank for non-laminate. | Bert |
| **Finish type** | Single select | Surface finish. e.g. Matte UV, Wire brushed, Hand scraped, Polished, Honed | Bert |
| **Install profile** | Single select | Edge / joint type. T&G (tongue & groove) for nail-down. Click for floating. Glue down / Loose lay for vinyl. | Bert |
| **Install method** | Single select | How the product is physically installed. Nail / staple, Float, Glue down, Nail + glue assist, Loose lay | Bert |
| **Locking system** | Single line | Click lock brand/type. e.g. Valinge 5G, 2G Drop Lock, I4F. Leave blank for T&G products. | Bert |
| **Underpad included** | Checkbox | Check if underpad is pre-attached. If checked, fill in Underpad type. | Bert |
| **Underpad type** | Single select | Type of attached underpad. IXPE, EVA, Cork, Foam, Rubber. Leave blank if not included. | Bert |
| **IIC rating** | Number | Impact Insulation Class. Critical for condo installs. Many buildings require IIC 72 minimum. | Bert |
| **STC rating** | Number | Sound Transmission Class. Paired with IIC for condo and multi-unit buildings. | Bert |
| **Tile format** | Single select | Tile and stone only. Wall / Floor / Wall & floor / Mosaic / Decorative | Bert |
| **Weight per piece (kg)** | Number | Tile and stone only. Per-piece weight in kg. | |
| **Certifications** | Multi-select | Environmental and safety certifications. e.g. Floorscore, CARB II, FSC, CE | Bert |

### Pricing

> **Note:** Never edit Cost or Retail price manually after Cowork is set up. All pricing changes flow through supplier price lists processed by Cowork.

| Field name | Type | Description | Notes |
|------------|------|-------------|-------|
| **Cost/unit** | Currency | Supplier cost per unit. The unit is per sq ft for flooring, and per piece for tile, stone, and accessories. **All supplier costs go here** regardless of pricing unit. Updated by Cowork when a new price list is processed. | LS · Auto |
| **Retail price/unit** | Currency | Selling price per unit (same unit as Cost/unit — per sq ft for flooring, per piece for tile/stone/accessories). Default = Cost + $1.00 for flooring; accessory markups vary (see supplier sections). This is what Bert quotes. | LS · Bert |
| **MAP price ($/sf)** | Currency | Minimum Advertised Price set by supplier. Grandeur and some others enforce this. Bert will not quote below MAP. | |
| **Pallet price ($/sf)** | Currency | Full skid / pallet price per sq ft where supplier offers a volume discount. | Auto |
| **Promo cost ($/sf)** | Currency | Active promotional cost per sq ft from the supplier. When populated, Bert flags this product as having an active promo. Retail price is adjusted manually — not auto-calculated. Cleared automatically when promo ends. | Bert · Auto |
| **Promo end date** | Date | When the promotional price expires. Cowork clears Promo cost automatically on this date. | Auto |
| **Volume pricing notes** | Long text | Tiered pricing rules. e.g. Vidar: Cut order $1.39 / 1-5 skids $1.34 / 6-20 skids $1.29 | |
| **Last price update** | Date | Date cost or retail was last updated. Bert flags records older than 90 days as potentially stale. | Auto |
| **Price last changed by** | Single select | Manual or Cowork. Audit trail. | Auto |

### Packaging & inventory

| Field name | Type | Description | Notes |
|------------|------|-------------|-------|
| **Box size (sf)** | Number | Square footage per box. Used for quote calculations. | LS |
| **Pieces per box** | Number | Planks or tiles per box. | LS |
| **Boxes per skid** | Number | Boxes per pallet. Used for bulk order and minimum order calculations. | LS |
| **Pieces per pallet** | Number | Tile and stone only. Total pieces per pallet. | |
| **Stock status** | Single select | Blank (default) / Low stock / Special order / Discontinued / Clearance. Leave blank unless supplier explicitly indicates stock status. See Stock status assignment rules. Bert never recommends discontinued as primary. | LS · Bert |
| **Active** | Checkbox | Unchecked = archived. Bert only surfaces active products. Cowork unchecks when supplier marks discontinued. | LS |

### Suitability — Bert recommendation filters

These fields are the core of Bert's recommendation engine. Fill them accurately — they determine which products Bert suggests for a given customer situation.

| Field name | Type | Description | Notes |
|------------|------|-------------|-------|
| **Waterproof** | Checkbox | 100% waterproof core. Key filter for kitchens, bathrooms, and basements. | Bert |
| **Pet friendly** | Checkbox | Scratch and claw resistant. Based on wear layer thickness and finish hardness. | Bert |
| **Radiant heat compatible** | Checkbox | Compatible with hydronic radiant heat. Black Walnut and some rustic grades are NOT compatible. | Bert |
| **Traffic rating** | Single select | Light residential / Moderate residential / Heavy residential / Light commercial / Commercial | Bert |
| **Suitable rooms** | Multi-select | Kitchen, Bathroom, Basement, Bedroom, Living room, Commercial, Condo | Bert |

### Warranty

| Field name | Type | Description | Notes |
|------------|------|-------------|-------|
| **Residential warranty (yrs)** | Number | Residential warranty in years. Enter the finish warranty. | Bert |
| **Commercial warranty (yrs)** | Number | Commercial warranty in years. Often shorter. | Bert |

### Bert knowledge

These two fields are Bert's product-level intelligence. Filled from salesperson interviews and store experience — not from supplier data.

| Field name | Type | Description | Notes |
|------------|------|-------------|-------|
| **Salesperson notes** | Long text | Pairing tips, common objections, install quirks, what this product sells best for. | Bert |
| **Pairs well with** | Single line text | SKUs of complementary products. e.g. matching stair nosing, recommended underpad. | Bert |

---

## Table 2 — Price History Log

An append-only audit trail of pricing events. A new row is written for every pricing change. Never edit or delete existing rows.

**Canonical table: `Price History Log v2` (table ID `tbly2em2cMuQs9eqK`).** The original `Price History Log` (`tbl1Af1yC6n2KvL7C`) was never populated and is superseded by v2, which adds the `Entry type` flag, dedicated promo columns, and a `Product name` text field. New logging — manual and Cowork — writes to v2. (The original empty table can be archived; it carries a stray `Entry type` field left over from setup.)

| Field name | Field ID | Type | Description | Notes |
|------------|----------|------|-------------|-------|
| **SKU** | `fldloZ7vUSUkRYXEo` | Single line text | The SKU of the product whose price/promo changed. Primary field. | |
| **Product name** | `fldMZ7i0jTwX71YWl` | Single line text | Human-readable product name (denormalized for quick reading). Optional. | |
| **Entry type** | `fldDOuZeRRadd8PRu` | Single select | `Regular price change` / `Promo applied` / `Promo cleared`. Disambiguates what kind of event the row records. | |
| **Previous cost ($/sf)** | `fldEFgoDQsXQ9C4MI` | Currency | Regular cost per unit before this change. | |
| **New cost ($/sf)** | `fldFLf37Opt6NY9g2` | Currency | Regular cost per unit after this change. | |
| **Promo cost ($/sf)** | `fldbHk8XlG6ecpJrP` | Currency | Promo cost recorded on this row, if any. | |
| **Promo end date** | `fldLVdhTu0NpovGrQ` | Date | Promo expiry recorded on this row, if any. | |
| **Change date** | `fldJlqHXkqBvwqUlr` | Date | When the change was recorded. | |
| **Supplier** | `fldM5b11sIi2IV6pN` | Single select | Which supplier sent the price list. | |
| **Changed by** | `fldEEIkFXiKGC1OPP` | Single select | `Manual` or `Cowork`. | |
| **Price list reference** | `fldQTDIDUStJe6EWW` | Single line text | Filename or identifier of the supplier document. | |
| **Notes** | `fldHkqE47Q1bjGtEi` | Long text | Context about this change. | |

### What gets logged (logging convention)

The log captures **all pricing events, not only regular cost changes**. Use `Entry type` to keep the cost columns analytically clean:

- **`Regular price change`** — `Cost ($/sf)` or `Retail price ($/sf)` moved. `Previous cost`/`New cost` = the before/after regular cost. Leave promo columns blank.
- **`Promo applied`** — a promo cost was set or rolled (incl. end-date-only rolls of an existing promo). `Previous cost` = `New cost` = the **unchanged regular cost** (so cost-trend math is not distorted); the discount lives in `Promo cost ($/sf)` + `Promo end date`. Note explains.
- **`Promo cleared`** — a promo expired or was removed. `Previous cost` = `New cost` = regular cost; promo columns blank; Note records the amount/end-date that was cleared.

**Cost columns always hold the true regular cost.** Never put a promo price in `New cost`/`Previous cost` — that is what `Promo cost ($/sf)` and the `Entry type = Promo applied` flag are for. This lets analysis filter `Entry type` (or read the promo column) rather than parsing free text.

Standard row values: `Change date` = date recorded; `Supplier` = the supplier; `Changed by` = `Manual` for human/Claude-driven runs, `Cowork` for automated; `Price list reference` = the supplier document identifier (e.g. "Vidar Price List A + Promotion A — 2026-06-01"). Batch writes are capped at 10 records per `create_records_for_table` call.

> **Cowork note:** Cowork should populate `Entry type` and the promo columns on every row going forward so manual and automated logging stay consistent. Older Cowork logic that wrote only regular cost changes is superseded by this expanded convention.

---

## Importing products from Excel

### How to import

- Open the Master Flooring Catalogue table in Airtable
- Click the + (Add or import) button → Import data → Upload CSV or spreadsheet
- Airtable will auto-match columns by header name — confirm each mapping
- Click Import. One record per row.

### Excel file rules

- Column headers must match Airtable field names exactly
- All columns must be present even if blank
- Checkbox fields: use TRUE or FALSE (text)
- Currency fields: numbers only, no $ sign (e.g. 4.79 not $4.79)
- Date fields: YYYY-MM-DD format
- Multi-select fields: separate values with a semicolon (e.g. Kitchen; Bedroom; Living room)

### Canonical column list — ALWAYS use this exact order

**Every Airtable upload file must contain exactly these 56 columns in this order.** Do not infer columns from the schema description — use this list verbatim. Columns not applicable to a product are left blank (None), never omitted.

| # | Column header |
|---|---|
| 1 | SKU |
| 2 | Product name |
| 3 | Brand |
| 4 | Supplier |
| 5 | Supplier SKU |
| 6 | Lightspeed ID |
| 7 | LS Handle / Parent ID |
| 8 | Collection |
| 9 | Product type |
| 10 | Category |
| 11 | Material type |
| 12 | Species |
| 13 | Colour / tone |
| 14 | Grade |
| 15 | Layout pattern |
| 16 | Width (in) |
| 17 | Thickness (mm) |
| 18 | Wear layer (mil) |
| 19 | Veneer / top layer (mm) |
| 20 | Veneer cut type |
| 21 | AC rating |
| 22 | Finish type |
| 23 | Install profile |
| 24 | Install method |
| 25 | Locking system |
| 26 | Underpad included |
| 27 | Underpad type |
| 28 | IIC rating |
| 29 | STC rating |
| 30 | Tile format |
| 31 | Weight per piece (kg) |
| 32 | Certifications |
| 33 | Cost/unit |
| 34 | Retail price/unit |
| 35 | MAP price ($/sf) |
| 36 | Pallet price ($/sf) |
| 37 | Promo cost ($/sf) |
| 38 | Promo end date |
| 39 | Volume pricing notes |
| 40 | Last price update |
| 41 | Price last changed by |
| 42 | Box size (sf) |
| 43 | Pieces per box |
| 44 | Boxes per skid |
| 45 | Pieces per pallet |
| 46 | Stock status |
| 47 | Active |
| 48 | Waterproof |
| 49 | Pet friendly |
| 50 | Radiant heat compatible |
| 51 | Traffic rating |
| 52 | Suitable rooms |
| 53 | Residential warranty (yrs) |
| 54 | Commercial warranty (yrs) |
| 55 | Salesperson notes |
| 56 | Pairs well with |

### Before importing a new supplier

- Delete any test or placeholder records for that supplier first
- Confirm the supplier's SKU prefix is correct
- Confirm whether the supplier uses product codes — if not, leave Supplier SKU blank
- Confirm whether grade variants exist — if so, each grade gets its own record with a shared LS Handle

---

## Updating existing products from a price list

**Most price lists are an UPDATE, not an import.** Once a supplier is in the
catalogue, their next price list is a set of price changes against rows that already
exist. Importing it instead of updating creates a duplicate catalogue.

### Step 1 — does this supplier already exist in the catalogue?

Before parsing anything for import, query the Master Flooring Catalogue filtered to
that supplier.

- **Rows returned → update path.** Continue to Step 2.
- **No rows → new supplier. Do not create records through the API.** Produce the
  Bert schema Excel export instead — the canonical column list above, in that exact
  order — and stop there. New products enter the catalogue through Airtable's own
  importer after a human has reviewed the file, never by automated record creation.
  Work the "New supplier onboarding — checklist" and "Before importing a new
  supplier" items first: the supplier's single-select option, 4-char SKU suffix,
  which cost column to use, markup overrides, and parsing quirks all have to be
  settled before the file is worth importing.

This check comes first because the two paths diverge completely, and getting it
wrong in either direction is expensive: importing over an existing supplier
duplicates their catalogue; API-creating a new supplier bypasses the review the
import path exists to provide.

### Step 2 — the matching cascade

Match incoming rows to existing records in this order, stopping at the first tier
that resolves cleanly:

1. **Internal `SKU`** (`fldx3byCOht5HbKmH`) — the canonical key. Supplier SKU is an
   input when the internal SKU is first *created*; once created, the internal SKU is
   the identifier the record is known by. For suppliers whose code is the SKU suffix
   verbatim (Biyork, Triforest, Olympia — see the Supplier SKU policy above) this
   tier resolves deterministically and should always be tried first.
2. **`Supplier SKU`** (`fldLOrMqh4aBftjtu`) — partial / fuzzy match on the
   supplier's own code (`WB1361`, `SP2801`, `VS081`). This is where sequentially
   numbered suppliers land, since a sequence number carries no information that ties
   it to a supplier row.
3. **Specifications** — product name, collection, size, grade, colour. Last resort,
   for suppliers with no codes at all. Always expect these to need review; this is
   the main reason the Supplier SKU policy says never to invent codes.

**Never match against a SKU the extraction step generated.** Tier 1 means the
internal SKU **as stored in Airtable**, looked up live — not a SKU reconstructed in
the current run. Extraction assigns sequence numbers per run and that numbering does
not survive between runs: on the 2026-09-01 GreenTouch list it emitted
`LVP-GRNT-0001…0010` for products the base holds as `LVP-GRNT-0073…0082` (the live
base continues LVP and ACC numbering on from where ENG ends rather than restarting
per category). Treating those generated values as tier-1 keys would have created 83
duplicates of a catalogue that already held all 83 products. GreenTouch is
sequentially numbered, so that run correctly resolved at tier 2.

### What to write

- **Only fields that actually changed.** Compare against current values and build a
  per-record diff; do not blanket-write every field on every row.
- `Last price update` and `Price last changed by` — set these **only when cost or
  retail actually moved**, not when the only change was a stock-status flag.
- `Stock status` / `Active` — set from the supplier's own markers
  (`Discontinued` → `Discontinued` + `Active` unchecked; `Limited` → `Low stock`,
  still active). The enum has no "Limited" value; `Low stock` is the mapping.
- Append one row per **cost** change to `Price History Log v2` per the logging
  convention above. Its `Supplier` select is sparsely populated — pass
  `typecast: true` so a supplier missing from that field's options is added rather
  than erroring the whole batch.
- Airtable caps `update_records_for_table` / `create_records_for_table` at **50
  records per call** — batch accordingly.

### Manual vs Cowork on unattended runs

`Changed by` / `Price last changed by` = `Cowork` for **any unattended run** —
including a scheduled Claude routine with no human watching. `Manual` means a person
or an interactive session made the change. The distinction is whether a human was in
the loop, not whether Claude was involved.

### Name casing differs per system — do not normalise it

| System | Form | Example |
|---|---|---|
| Airtable `Supplier` select | established mixed case | `GreenTouch` |
| Notion `Company` select | ALL CAPS | `GREENTOUCH` |
| Make scenario 4382120 | ALL CAPS, must match Notion exactly | `GREENTOUCH` |

Each system's existing convention wins. "Correcting" Airtable's casing to match
Notion fragments the select options and orphans existing rows.

### Verify against the source document

This writes live pricing that Bert quotes to customers. Cross-check extracted
SKU→price pairs against the source PDF's own text before writing, and again after.
The full download-and-parse recipe (the share link needs `?download=1` **and** a
cookie jar; the Microsoft 365 connector returns Graph's text conversion rather than
file bytes, which flattens table geometry) is in `methods/pricelist-extraction.md`,
with a wrapper at `scripts/pricelist_fetch.py`.

---

## SKU format reference

| Prefix | Category | Example | Format |
|--------|----------|---------|--------|
| ENG | Engineered hardwood | ENG-VIDR-0042 | 3 char category + 4 char supplier + 4 digit sequence |
| LVP | Luxury vinyl plank (any core) | LVP-GRAN-0001 | SKU prefix is format-only; core (SPC/WPC) appears in LS name prefix and Material type |
| LVT | Luxury vinyl tile (any core) | LVT-GRAN-0001 | Same logic as LVP |
| SPC | SPC core — legacy SKUs only | SPC-TOUC-0001 | Do not use for new products; new vinyl uses LVP or LVT prefix |
| WPC | WPC core — legacy SKUs only | WPC-GRAN-0001 | Same as above |
| LAM | Laminate | LAM-VIDR-0001 | |
| TIL | Tile / Stone | TIL-OLYM-0001 | 3 char category + 4 char supplier + 4 digit sequence. **Exception: Olympia Tile uses its own stock code as the SKU verbatim (e.g. `ES.AC.WHT.0416.VR.G`), not this format — see Olympia Tile supplier section.** |
| STN | STONE (marble/quartz thresholds, jambs, benches) | STN-CIFD-0001 | Per-piece fabricated stone pieces only — not installed tile |
| HWD | Solid hardwood | HWD-CANS-0001 | |
| CAR | Carpet | CAR-XXXX-0001 | |
| ACC | Accessory / Moulding | ACC-VIDR-0001 | |

---

## Recommended Airtable views

Views must be created manually — they cannot be built via the API.

### Grid views — Master Flooring Catalogue

| View name | Type | Description |
|-----------|------|-------------|
| All products | Grid | No filters. Sort by Supplier A→Z then SKU A→Z. |
| By supplier | Grid | Group by Supplier field. |
| By category | Grid | Group by Category field. |
| Active only | Grid | Filter: Active = checked. |
| Stale pricing | Grid | Filter: Last price update is before 90 days ago. |
| Bert view | Grid | Show only: SKU, Product name, Supplier, Category, Retail price, Waterproof, Pet friendly, Radiant heat compatible, Suitable rooms, Salesperson notes. |

### Section views for manual data entry

| View name | Fields shown |
|-----------|-------------|
| Identity fields | SKU through Layout pattern |
| Product specs | Width through Certifications |
| Pricing | Cost through Price last changed by |
| Packaging | Box size through Active |
| Suitability | Waterproof through Suitable rooms |
| Warranty + Bert | Residential warranty through Pairs well with |

### Grid views — Price History Log

| View name | Description |
|-----------|-------------|
| All changes | Sort by Change date descending. |
| By supplier | Group by Supplier, sort by Change date descending. |

---

## Quick reference — field rules

### Always fill in

- **SKU** — every record must have one, and it never changes after creation
- **Product name** — include colour and grade in the name. **Exception: transitions, mouldings, stair components, and sundries** follow the searchable accessory format instead — see below.
- **Supplier** — use the controlled list, never free-text
- **Category and Product type** — Bert's primary filters
- **Cost/unit and Retail price/unit** — Bert cannot quote without these
- **Box size (sf)** — needed for quote calculations
- **Stock status** — leave blank by default. Only populate when supplier explicitly indicates Clearance, Discontinued, or similar
- **Active** — Bert will not surface inactive products. Always set to checked unless product is confirmed discontinued
- **Radiant heat compatible** — especially important; Black Walnut and some rustic grades are FALSE

### Product name — accessories (transitions, mouldings, stair, sundries)

Accessory records carry no structured type/profile/dimension fields — `Product type` is just `Accessory` and `Collection` is just `Accessories`. All of that detail lives in `Product name`, so the name has to be structured or it cannot be searched or parsed reliably.

Use these formats verbatim. They mirror the Lightspeed name exactly, so the LS upload becomes a copy rather than a parse (see the `ls-upload-instructions` skill, *Accessories — transitions and mouldings*):

```
[Brand] - Transition | [Type] | [Material] | [Dimensions]
[Brand] - Stair      | [Type] | [Material] | [Dimensions]
[Brand] - Sundry     | [Type] | [Dimensions]
```

- `[Brand]` — full brand name spelled out (`Vidar`, not `VIDR`/`VIDACC`). This is what makes `Vidar Transition` return the whole family in one search.
- `[Type]` — controlled token only: `T-Moulding`, `Reducer`, `Nosing`, `Stair Nosing`, `End Cap`, `Threshold`, `Quarter Round`. Supplier spelling does not carry through — `T-Molding` and `T-Moulding` are different search results.
- `[Material]` — **which floor this transition matches.** Resolve in order, first useful token wins: (1) `Material type` with "core" dropped (`SPC core` → `SPC`); (2) `Category` shortened (`Laminate`, `Engineered hardwood` → `Engineered`); (3) `Species` (`AWO`, `European Oak`, `Ash`). **Never use `Hardwood plywood`** — it describes the plank core, not the floor being matched; fall through to Species. Omit the segment if unknown; never guess.
- `[Dimensions]` — `94.5"`, `70.86" Square`, or `Cut Order`. Omit if the supplier does not state it.

**Do not repeat the material token.** If it already appears in `[Type]`, skip the `[Material]` segment. When restructuring an existing free-text name that embeds it — `Vidar SPC Nosing` — extract it into the `[Material]` slot rather than appending a second copy. Correct: `Vidar - Transition | Nosing | SPC`. Wrong: `Vidar - Transition | SPC Nosing | SPC`.

Examples:
- `Vidar - Transition | Stair Nosing | AWO | 94.5" Square`
- `Vidar - Transition | T-Moulding | SPC | Cut Order`
- `Vidar - Transition | Nosing | Laminate`
- `Vidar - Stair | Stair Riser | AWO | 48"`
- `Vidar - Sundry | Underpad | 3mm IXPE 200sf Roll`

Only the controlled transition types get the `Transition` token — stair treads/risers/stairboards are `Stair`, and underlay/glue/vents/floor protection are `Sundry` (no material segment; a bucket of glue does not match a floor). Diluting the token defeats the search.

> **Populate `Category` and `Material type` on accessory records.** Both are blank on every accessory today, which forces the `[Material]` segment to be parsed out of free text. Filling them makes the name deterministic and makes accessories filterable in Bert, which they currently are not.

### Leave blank if not applicable

- Wear layer (mil) — hardwood only has veneer, not a wear layer
- AC rating — laminate only
- IIC / STC rating — only fill if product has tested ratings
- Tile format and Weight per piece — tile and stone only
- Locking system — T&G products do not have a click system
- Supplier SKU — leave blank if supplier does not use product codes
- Lightspeed ID — populated after Lightspeed upload, never before

### Never edit manually

- Cost/unit — updated by Cowork from supplier price lists
- Promo cost ($/sf) and Promo end date — set and cleared by Cowork
- Last price update and Price last changed by — written by Cowork
- Lightspeed ID — assigned by Lightspeed after upload
- Price History Log records — append-only, never edit existing rows

### Supplier SKU policy

- Fill in only if the supplier assigns codes on their price lists or invoices
- If the supplier has codes, enter them exactly as they appear on the supplier document
- If the supplier has no codes, leave blank — Cowork will match on product name and specs instead
- Do not create fictional codes — this causes Cowork matching errors

#### When the supplier code is unique per product — use it as the SKU suffix verbatim

When a supplier assigns a **unique string/number to every individual product** (one code per colour/size, no collisions), use that code as the verbatim suffix of the internal SKU **and** populate Supplier SKU with the same code:

- **Internal SKU** = `[CAT]-[SUPP]-[supplier code]` — the supplier's code used verbatim as the suffix, not a sequential `0001` number. e.g. `ENG-BIYK-BYKENWA18NA`, `LVP-BIYK-BYKHYDRO7WI`.
- **Supplier SKU** = the same supplier code on its own. e.g. `BYKENWA18NA`, `BYKHYDRO7WI`.

This is the same pattern Triforest (`[CAT]-TRIF-[TF code]`) and Olympia Tile (stock code as SKU verbatim) already use. Benefits: the internal SKU is human-traceable back to the supplier sheet, and Cowork matching is exact.

**Keep the code untouched even if it overlaps the supplier abbreviation.** Biyork codes start with `BYK` and the supplier suffix is `BIYK`, so SKUs read `ENG-BIYK-BYKENWA18NA` with a harmless `BIYK…BYK` overlap — exactly as Triforest's `TRIF…TF` overlaps. Do **not** strip the leading characters to "tidy" it; stripping risks collisions and breaks the verbatim principle.

**Only use this pattern when codes are genuinely unique per product.** If a supplier reuses one code across many colours (e.g. a single "Step + Riser Set" code spanning 40 colours), fall back to the sequential `0001` format and store the shared code in Supplier SKU.

---

## Supplier Ingest Rules

This section captures supplier-specific rules for processing price lists into the Master Flooring Catalogue. Every supplier has quirks — layout conventions, what they do and don't provide, which columns to use for cost, SKU patterns, product-specific markup overrides. Each supplier gets its own subsection below. When ingesting a price list, find the relevant subsection first; if a supplier is not yet documented, follow the "New supplier onboarding" checklist at the end of this section to add them.

The general flow for any supplier ingest:

1. Look up the supplier's subsection below
2. Apply global schema rules (pricing markup, SALE logic, stock status, etc.)
3. Apply supplier-specific overrides from the subsection
4. Generate an Airtable-ready Excel file with all 54 schema fields as columns
5. Spot-check a sample covering every edge case before committing to import

---

### Floors At Work (FAW)

Floors At Work is a Toronto-area distributor of NAF-branded flooring, accessories, doors, mouldings, vanities, and plumbing fixtures. Their price list is issued as a multi-page PDF, typically 8 pages, organized by product category with section-header colour bars.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Floors At Work` |
| **Brand** | `NAF` (all flooring products share this brand) |
| **SKU supplier code** | `FAWK` — 4-char suffix, e.g. `ENG-FAWK-0042` |
| **Supplier SKU** | Usually blank. FAW only assigns codes on a handful of products (e.g. `F6W`, `F6J`, `F6WM` for 6.5mm SPC colourways). Populate only when an explicit code appears on the price list. |

#### Cost column

FAW price lists show three columns after "Size": **Pallet price / sf**, **Box price / sf**, and sometimes dual pricing for accessories.

- **Use the Pallet price column as `Cost/unit`.** Ignore the Box price column for catalogue ingest.
- For products with per-piece pricing (stair treads, risers, accessories), store the supplier's per-piece cost in `Cost/unit` (the unit is per piece for these items) and compute `Retail price/unit` from the applicable accessory markup.

#### Markup overrides

- **Flooring products**: standard `Retail = Cost + $1.00` (global rule).
- **Vinyl stair steps and risers**: `Retail = Cost + $20` per set or per piece. Applies only to SPC/vinyl stair products — not to oak or hardwood stair treads.
- **Oak and hardwood stair treads**: markup rule TBD. Store the supplier per-piece cost in `Cost/unit` and leave `Retail price/unit` blank until a rule is set. Flag in Salesperson notes.

#### Scope of ingest

Currently in scope: ENG, LVP, LVT, HWD, LAM, TIL, and vinyl stair treads/accessories. Out of scope for now: mouldings, baseboards, casings, shoebase, vents, doors, vanities, toilets.

#### Collections naming

FAW organizes vinyl products into named collections — use these verbatim for the `Collection` field:

- `Aquaplus Select` — 7mm with 1.5mm underpad, cottage/Ontario town colourways
- `Aquaplus Gold` — 7mm with 1.5mm underpad, Toronto neighbourhood colourways
- `Aquaplus Gold with Cork` — 7mm with 1.5mm cork, Siberia/Amazon/Shangri-La
- `Aquaplus Platinum` — 9mm with 2mm underpad, zodiac/London colourways
- `Classic` — 7mm with underpad, tropical island colourways
- `Royal` — 8mm with 1.5mm underpad, British royal colourways
- `Aquawood` — 10mm WPC, river colourways
- `Aqualuuuz` — 5mm loose lay, world city colourways
- `Aqua Tile` — 12"×24" SPC tiles
- `Aqua Commercial` — dry back glue-down commercial lines (3mm and 5mm)

Laminate collections: `Handscraped Laminates (Drop Clic)`, `Waterproof Laminate`, `Waterproof Laminate Plus`, `Waterproof Laminate Pro`.

Hardwood collections: `Hickory Engineered`, `White Oak T&G`, `White Oak Click`, `Regal`, `Designer`, `Elegant`, `Handscraped Exotic Walnut`, `Handscraped Maple`.

#### Material type defaults

FAW does not state the core construction explicitly — infer from the section header and product naming:

| FAW section | Material type |
|---|---|
| Regular laminate (e.g. "12mm Handscraped Laminate") | `HDF core` |
| Waterproof laminate (any Waterproof Laminate / Plus / Pro) | `Water-Resistant Core` |
| Aquaplus / Aqualuuuz / Aqua Tile / Aqua Commercial / Royal / Classic | `SPC core` |
| Aquawood | `WPC core` |
| Engineered hardwood (all) | `Hardwood plywood` |
| Solid hardwood | *(leave blank)* |

#### Fields FAW does not provide

FAW price lists generally **omit**:

- **Wear layer (mil)** — stated only for vinyl products as mm (e.g. "0.5mm wear layer" → convert using 1 mm = 39.37 mil, round to whole). Leave blank if not stated.
- **Veneer / top layer (mm)** — stated occasionally for engineered hardwood (e.g. "2mm Veneer", "3mm Veneer"). Leave blank if not stated.
- **Grade** — FAW uses several grade labels and needs attention to the "Grade" word distinction:
  - **"Grade: Select"** / **"Grade: Select & Better"** (European White Oak Designer lines) → store as `Select` / `Select & Better`
  - **"Distressed Grade"** (Solid Handscraped Exotic Walnut) → store as `Distressed Grade` (verbatim)
  - **"Wirebrushed & Distressed Grade"** (Hickory 6.5") → strip finish descriptor, store as `Distressed Grade`
  - **"Handscraped & Distressed Grade"** (Engineered Exotic Walnut 5") → strip finish descriptor, store as `Distressed Grade`
  - **"Handscraped and Distressed"** (Engineered Maple 6.5") → **finish language, NOT a grade**. Leave `Grade` blank. Populate `Finish type` with both "Handscraped" and "Distressed" descriptors. Add a Salesperson note clarifying this is finish-only.
- **IIC / STC ratings** — not provided by FAW on the price list. Leave blank.
- **Certifications** — not listed. Leave blank.
- **Radiant heat compatible** — not stated explicitly. Leave blank *except* for Black Walnut (see below).
- **Warranty (years)** — not listed. Leave blank.

FAW price lists generally **do provide**:

- Overall thickness (mm)
- Plank/tile size in mm and inches
- Box size (sf) and boxes per pallet
- Finish type (handscraped, wirebrushed, distressed)
- Install profile (T&G, Click, Loose lay, Glue down)
- Locking system (Drop Click, Valinge 5G) — stated in section header
- Whether attached underpad is included

#### Suitability defaults

Apply these unless the PDF states otherwise:

- **Waterproof = TRUE** for anything named Waterproof Laminate, Aquaplus, Aqualuuuz, Aqua Tile, Aqua Commercial, Aquawood, or any SPC/WPC vinyl product.
- **Waterproof = FALSE** for regular laminate, engineered hardwood, solid hardwood.
- **Pet friendly = TRUE** only when wear layer ≥ 20 mil (0.5mm). Everything else FALSE.
- **Radiant heat compatible = FALSE** for any Black Walnut product (global schema rule). Leave blank for all other FAW products pending supplier verification.

#### Underpad type inference for Aquaplus lines

FAW states "1.5mm Underpad" or "2mm Underpad" but doesn't name the material. Default assignments:

- **Aquaplus Gold with Cork**: `Cork` (stated explicitly on list)
- **All other Aquaplus lines** (Select, Gold, Platinum, Royal, Classic): `IXPE` (industry default for SPC floors in this price range)
- **Aqua Tile with underpad**: leave blank unless material is stated
- **Waterproof Laminate Pro (14mm)**: attached underpad present, type not stated — leave `Underpad type` blank, set `Underpad included` = TRUE

Flag the IXPE assumption in Salesperson notes if it matters for a quote; verify with FAW rep if building a spec sheet.

#### Product naming convention

Use this format for `Product name`:

```
NAF [thickness][mm] [Collection Name] [width]" — [Colour]
```

Examples:
- `NAF 12mm Waterproof Laminate 7.71" — Harrison`
- `NAF 7mm Aquaplus Gold Vinyl 7.1" — Rosedale`
- `NAF Engineered White Oak Designer 7.5" (Wirebrushed) — Da Vinci`

Include grade or finish descriptors in parentheses after width if they distinguish the product from other variants in the same collection.

#### Layout parsing — what to watch for in the FAW PDF

Each section begins with a coloured header bar naming the collection, followed by a size-spec line (e.g. "Size: 7mm x 182mm x 1524mm") and rows of colours. **Multiple groups can live under a single section header** when box size or boxes-per-pallet differ between sub-groups:

- Aquaplus Platinum has three sub-groups (different box sizes) under one heading — create records for every sub-group with its specific box size.
- Hickory 6.5" has two sub-groups: Distressed Grade colours (box 19.18) and Chestnut alone (box 20.25, Wirebrushed only).
- Aquaplus Select has Tobermory listed twice — once at 183mm and once at 182mm. Create both records; flag in Salesperson notes that two width variants exist.

#### SALE items on FAW lists

FAW marks promo items as "Colors ON SALE: [names]" in yellow highlighting, usually within a collection that also lists regular-priced colourways. Apply the global Sale item pricing logic:

- **Rule 1 applies most often** — regular colours live in the same section, so pull Cost from the regular pallet price and put the SALE pallet price in `Promo cost ($/sf)`.
- **Promo end date** — FAW does not print end dates on SALE items. Per the global month-end default rule (Jul 2026, supersedes the earlier leave-blank convention): set `Promo end date` = last day of the price list's month, and roll it forward month-by-month if the promo is confirmed still running on the next list. Flag in Salesperson notes.

Example from Feb 23 2026 list: Designer 7.5" regular colours (Monet, Dali) @ $4.99 pallet; SALE colours (Da Vinci, Picasso) @ $3.99 pallet → Cost=$4.99, Retail=$5.99, Promo cost=$3.99, Promo end date blank.

#### Coming Soon items

FAW frequently lists "Colors Coming Soon" for not-yet-in-stock colourways. Treatment:

- Create the record now so Cowork can match when stock arrives
- `Active` = TRUE (so the record is live in the system)
- `Stock status` = leave blank (not "Discontinued" or "Clearance")
- `Salesperson notes` = "COMING SOON — not yet in stock." as the first line
- Bert should surface these with the Coming Soon flag rather than hiding them

#### Special case — Vinyl Steps & Risers

FAW sells a single "Step + Riser + Side Return Set" product at $49/set with a long list of compatible colours (Amazon/Maldives, Bay, Bayview, Bora Bora, Buckingham, Chaplin, etc. — typically 40+ colours).

**Do not create one record per colour.** Create a single consolidated record:

- `Product type` = `Accessory`
- `Category` = `LVP` (since they pair with LVP collections)
- `Material type` = `SPC core`
- `Cost/unit` = $49 (supplier per-set cost; the unit is per set/piece here)
- `Retail price/unit` = $69 (Cost $49 + $20 vinyl stair markup)
- List all compatible colours in `Salesperson notes`
- Include dimensions in `Salesperson notes`: Step 8mm × 350mm × 1200mm, Riser 4mm × 200mm × 1200mm, Side Return 400mm with 40mm nose
- Note "Final Sale / No Returns"

#### Oak stair treads and risers (page 7)

Per-piece priced accessories. Store each tread type as a separate `ACC-FAWK-XXXX` record:

- `Category` = `Solid hardwood`
- `Species` = `American White Oak`
- `Product type` = `Accessory`
- `Cost/unit` = listed per-piece cost (unit is per piece for these accessories)
- `Boxes per skid` = pieces per pallet (field is reused for piece count)
- `Salesperson notes` = style description (Two-sided closed / Left-side finished / Right-side finished / One-side closed Pie), full dimensions, and the phrase "Retail markup TBD — FAW stair markup rule covers vinyl steps only"

Oak Riser has dual pricing (Pallet $2.99 / Piece $3.99). Use $3.99 as `Cost/unit` (per-piece).

#### Known issues / soft spots

When processing a new FAW list, double-check these recurring ambiguities:

- **Wear layer not always listed** — the 5mm Aqua Commercial plank (Mars, Pluto, Mercury, Earth, Saturn, Venus) doesn't state wear layer; 3mm and 5mm tile variants in the same line say 0.5mm. If missing, leave blank and flag.
- **Tobermory duplicate** — appears in two size variants. Confirm both exist by asking the rep before deduplicating.
- **Colourway reuse across collections** — "Westminster" appears in both Aquaplus Platinum (9mm) and Royal (8mm). "Windsor" appears in both Royal and 6.5mm SPC. Create separate records; differentiate in LS Handle with a collection suffix.
- **Effective date** — every FAW list is headed "Effective [date] — price subject to change due to fluctuating ocean freight charges." Record the effective date in `Price list reference` when logging to Price History Log.

#### FAW ingest output format

Always produce an Excel file with all 54 schema fields as columns (header row), records starting on row 2. File naming convention: `faw_airtable_upload_[YYYY-MM-DD].xlsx`. Save to `/mnt/user-data/outputs/`.

---

### Triforest (Toucan brand)

Triforest is the supplier/distributor; Toucan is the brand. Their price list is issued as a multi-page PDF (typically 6 pages), organized by product category with section-header green bars. The company also operates under the name "Triforest Flooring" with Markham and Mississauga branches.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Triforest` |
| **Brand** | `Toucan` (all flooring products) |
| **SKU supplier code** | `TRIF` — 4-char suffix |
| **Internal SKU format** | `[CAT]-TRIF-[TF code]` — e.g. `LAM-TRIF-TF8301`, `LVP-TRIF-TFSPC601-F`, `ENG-TRIF-TCN101`. The supplier's TF/FL/TCN product code is used verbatim as the numeric suffix (not a sequential number). |
| **Supplier SKU** | Always populated with the code printed on the price list (`TF8301`, `TFSPC601-F`, `TCN101`, etc.). For the FL2 series the list shows dual codes — use the combined form verbatim (e.g. `FL202 / TF6003W`). |

#### Cost column

Triforest price lists show **Price/SF** and **Price/Box** columns (no separate pallet price column).

- **Use the Price/SF column as `Cost/unit`.**
- Ignore Price/Box (it's derivable from Cost × Box size).
- Standard markup applies: `Retail = Cost + $1.00`.

#### LS Handle format

Brand-first alphanumeric, built as `TRIF[CAT][optional thickness segment][TF code]`, stripped of all non-alphanumeric characters (hyphens, slashes, spaces, dots):

| Pattern | Example |
|---|---|
| `TRIFLAM[code]` | `TRIFLAMTF8301`, `TRIFLAMFL202` |
| `TRIFLVP[thickness][code]` | `TRIFLVP65TFSPC202F`, `TRIFLVP80TFSPC601F`, `TRIFLVP90TFSPC901F` |
| `TRIFLVPLL[code]` | `TRIFLVPLLTFL621` (Looselay) |
| `TRIFENG[code]` | `TRIFENGTCN101` |

The thickness segment for LVP disambiguates series that share the same code prefix across different thicknesses (SPC2=65, SPC3=42, SPC4=70, SPC5=60, SPC6/7=80, SPC9=90). Not used for laminate or engineered.

#### LS Name prefix

| Product type | LS Name prefix |
|---|---|
| Laminate | `TRIFLAM` |
| LVP/SPC (any thickness) | `TRIFLVP-SPC` |
| Looselay | `TRIFLVP-SPC` (SPC core, Loose lay install profile) |
| Engineered hardwood | `TRIFENG` |

#### Scope of ingest

In scope: **LAM, LVP (SPC), ENG**. Out of scope: Accessories (underpads, trims, stair nosings, spindles, adhesive), MDF Trims and Moldings (baseboards, casings, crown, doorstop, chairrail). Stair treads/spindles can be brought into scope later as Accessory records.

#### Collections (use series name verbatim)

**Laminate (36HR water-resistant)**: Matt / Hand Scraped, EIR.
**Waterproof Laminate**: FL2 Series (7.7"×12.3mm 72HR), TF66 Series (7.7"×12.3mm 72HR), TF80 Series (7.7"×72" luxury 12.3mm 72HR), TF83 Series (9.37"×5' 12.3mm 120HR — NEW as of Jan 2026 list).
**Luxury Vinyl (SPC)**: SPC2 (7.2"×6.5mm), SPC3 (7.2"×4.2mm), SPC4 (9"×7mm), SPC4 Series (Cork) (9"×7mm with cork backing), SPC5 (9"×6mm), SPC6 (9"×8mm solid), SPC7 (6"×8mm solid), SPC9 (7"×9mm solid with Genius Edge), Looselay (7.4"×5mm).
**Engineered hardwood**: Studio (6.5"×18mm, 2mm top layer American White Oak, Light Wire Brushed), Towne (7.5"×18mm, 3mm top layer European White Oak, Light Wire Brushed).

#### Material type defaults

| Section | Material type |
|---|---|
| Matt / Hand Scraped, EIR | `HDF core` |
| FL2, TF66, TF80, TF83 | `Water-Resistant Core` |
| SPC2–SPC9, Looselay | `SPC core` |
| Studio, Towne | `Hardwood plywood` |

Triforest does **not** sell WPC core vinyl or solid hardwood on their standard list.

#### Fields Triforest does not provide

- **Color names** on many series (SPC2/3/4/5, Matt/Hand, EIR, TF80, FL2, Looselay TFL605/610 are code-only). **Rule: use the TF code as the color name placeholder. Do not leave Product name without a colour token.** Accept the code as canonical until supplier adds names.
- **Grade** — not stated on any Triforest product. Leave blank across the board.
- **AC rating, IIC/STC, Certifications, Radiant heat, Warranty, Finish type (non-engineered), Locking system brand** — all left blank.
- **Species on vinyl** — colour names sometimes imply species (SPC9 "American Oak"); these are colour names only. Leave `Species` blank for all vinyl.

#### Suitability defaults

- **Waterproof = TRUE** for all WP Laminate (FL2/TF66/TF80/TF83), all SPC (SPC2–SPC9), and Looselay.
- **Waterproof = FALSE** for 36HR laminate (Matt/Hand, EIR) and engineered.
- **Pet friendly = TRUE** when wear layer ≥ 20 mil — applies to SPC2, SPC4, SPC4 Cork, SPC5, SPC6, SPC7, SPC9, Looselay.
- **Pet friendly = FALSE** for SPC3 (12 mil wear), all laminate, and engineered.
- **Radiant heat compatible** = blank pending supplier verification.

#### Underpad type inference for SPC

Triforest shows composite thickness as `[SPC]+[pad]mm` but doesn't name underpad material. Defaults:
- **SPC2, SPC3, SPC4, SPC5**: `IXPE` — flag "Underpad type assumed IXPE; verify with Triforest" in Salesperson notes.
- **SPC4 Cork Backing** (TFSPC421–424): `Cork` (stated in series heading).
- **SPC6, SPC7, SPC9**: no attached underpad stated — leave `Underpad included = FALSE`. Flag "No attached underpad mentioned — confirm before install" in Salesperson notes.
- **Looselay**: no underpad — leave `Underpad included = FALSE`.

#### Layout parsing quirks

- **Missing color names** — extracted PDF text often lists only codes. Use the code verbatim.
- **Dual codes (FL2)** — `FL202 / TF6003W`. Use `FL202` for internal SKU; use combined form for Supplier SKU.
- **Composite thickness** — `5+1.5mm` means 5mm SPC + 1.5mm pad = 6.5mm total. Populate `Thickness (mm)` with total; set `Underpad included = TRUE`.
- **TF83 dimensions** — PDF shows `5' x 9" x 12.3mm` = 5' length × 9.37" width (1520 × 238mm). Width column = 9.37".
- **Looselay sub-groups** — TFL605/610 use 48.2" length (25.03 sf/box); TFL621–628 use 48.3" length (24.86 sf/box).
- **"NEW ARRIVAL" flag** — note in Salesperson notes; does not change field mapping.

#### SALE / promo items

The Jan 2026 list has no explicit SALE items. If future lists add promos, Triforest does not print promo end dates — leave `Promo end date` blank, promo holds until next price list.

#### Triforest ingest output format

Produce an Excel file with all 58 schema fields as columns (header row), records starting on row 2. File naming: `toucan_triforest_airtable_upload_[YYYY-MM-DD].xlsx`. Save to `/mnt/user-data/outputs/`.

---

### Purelux

Purelux Canada Floors Inc. is supplier and brand (single entity, like Vidar or FAW). Based in Mississauga, ON. Price list issued as a multi-page PDF with styled series headers and per-series product specifications blocks below each colour table.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Purelux` |
| **Brand** | `Purelux` |
| **SKU supplier code** | `PLUX` — 4-char suffix |
| **Internal SKU format** | Sequential per category: `LAM-PLUX-0001`, `LVP-PLUX-0001`, `LVT-PLUX-0001`, etc. Purelux does **not** publish product codes on their list. |
| **Supplier SKU** | Leave blank. Purelux does not publish codes; only colour names appear on the PDF. |

#### Cost column

Purelux lists **Price/SF** and **Price/Box** columns. Use Price/SF as `Cost/unit`. Standard markup applies: `Retail = Cost + $1.00`.

#### LS Handle format

Brand-first alphanumeric: `PLUX[CAT][series][colour]`, stripped to alphanumeric only:

| Pattern | Example |
|---|---|
| `PLUXLAM[series][colour]` | `PLUXLAMBETTENGRANDMARAIS` |
| `PLUXLVP[series][colour]` | `PLUXLVPDYN7WYANDOTTE`, `PLUXLVPIMPERSOLANABEACH`, `PLUXLVPWPC9ANNE`, `PLUXLVPJRNYINES` |
| `PLUXLVPLL[colour]` | `PLUXLVPLLWESTIN` (Dynamic Drop looselay) |
| `PLUXLVT[series][colour]` | `PLUXLVTTILEBERWICK` |

Series abbreviations in handles: `BETTEN`, `LL` (Dynamic Drop looselay), `TILE` (Dynamic Tile Drop), `DYN7` (Dynamic 7mm), `IMPER` (Imperlux), `WPC9` (WPC 9" wide), `WPC7` (WPC 7" wide / Earthy Elegance + sale items), `PILLOW` (Pillow Bevel), `JRNY` (Journey).

#### LS Name prefix

| Product type | LS Name prefix |
|---|---|
| Laminate (Betten) | `PLUXLAM` |
| LVP (Dynamic Drop looselay, Dynamic 7mm, Imperlux, Pillow Bevel, Journey) | `PLUXLVP-SPC` |
| LVP (WPC Series) | `PLUXLVP-WPC` |
| LVT (Dynamic Tile Drop, glue-down) | `PLUXLVT-SPC` |

#### Scope of ingest

In scope: all flooring series — Betten (laminate), Dynamic Drop (looselay), Dynamic Tile Drop (glue-down LVT), Dynamic 7mm, Imperlux (cork-backed), WPC Series, Pillow Bevel, Journey.
Out of scope: WPC Stair Treads ($49/set), Transition Trims (T-molding, reducer, stair nosing, flush nosing).

#### Collections (use series name verbatim)

**Laminate**: Betten (14.3mm with 2mm EVA pad, AC4, Drop lock, Floorscore).
**Vinyl**: Dynamic Drop (5mm looselay, 20 mil, painted bevel), Dynamic Tile Drop (5mm glue-down 24" square), Dynamic Series (7mm with 1.5mm pad, 20 mil, 5G drop-lock), Imperlux (7mm with 1.5mm CORK pad, 20 mil, EIR), WPC Series (8mm with 1.5mm pad, 22 mil, painted bevel — two sub-widths 9" and 7"), Pillow Bevel (8mm with 2mm pad, 22 mil, pillow edge), Journey (9mm with 2mm pad, 22 mil, EIR).

#### Material type defaults

| Series | Material type |
|---|---|
| Betten | `HDF core` (water-resistant, not waterproof) |
| Dynamic Drop | `Loose-lay vinyl` |
| Dynamic Tile Drop | `SPC core` |
| Dynamic 7mm, Imperlux, Pillow Bevel, Journey | `SPC core` (default for unlabelled series; PDF does not explicitly state core) |
| WPC Series | `WPC core` (explicitly labelled on PDF) |

**Rule for unspecified core material**: default to `SPC core` unless the PDF explicitly names WPC.

#### Fields Purelux does not provide

- **Product codes** — blank Supplier SKU across the board.
- **Grade** — not stated. Leave blank.
- **Underpad material** — Dynamic 7mm, WPC Series, Pillow Bevel, Journey all state a pad thickness (e.g. "1.5mm pad attached") but not the material. Default to `IXPE`; flag in Salesperson notes. Imperlux is explicit about cork.
- **Species** — not listed. Leave blank.
- **Radiant heat compatible** — not stated. Leave blank.

Purelux **does provide** (usually more thorough than Triforest):
- Colour names on every product (no code-only items).
- Wear layer on vinyl (20 mil or 22 mil).
- AC rating on laminate (AC4 for Betten).
- Locking system (5G Drop Lock on most vinyl; Drop Lock on laminate).
- Finish type (Embossed, EIR, Painted Bevel, Pillow Edge).
- Certifications (Floorscore, Greenguard).
- Residential warranty = 30 years, Commercial warranty = 8 years (standard across all lines).

#### Suitability defaults

- **Waterproof = TRUE** for all vinyl (Dynamic Drop, Dynamic Tile Drop, Dynamic 7mm, Imperlux, WPC, Pillow Bevel, Journey).
- **Waterproof = FALSE** for Betten laminate (it is water-resistant, not waterproof).
- **Pet friendly = TRUE** when wear layer ≥ 20 mil — applies to all Purelux vinyl.
- **Pet friendly = FALSE** for Betten laminate.

#### SALE items

Purelux marks clearance items with red "On Sale" text in the price column. Known pattern from Feb 2025 list: **5 WPC Series colours (Arctic Mist, Mocha Glow, Natural Essence, Nimbus Gray, Whispering Breeze) on sale at $1.99/sf** while other colours in the same series are $2.99/sf.

**Sale pricing flow**:
- If a sale colour has a **regular-price equivalent in the same series** (same structure, same spec sheet), set `Cost` = regular equivalent price, `Retail` = Cost + $1.00, `Promo cost ($/sf)` = sale price.
- If a sale item has **no regular equivalent**, set `Cost` = sale price, `Retail` = Cost + $1.00, `Promo cost ($/sf)` = sale price (clearance-only product).
- **Promo end date** = blank (Purelux does not publish end dates).
- Flag in Salesperson notes: "ON SALE. Regular price $X.XX/sf assumed (same structure as series). Confirm with Purelux."

#### Effective date quirk

The Feb 2025 PDF shows conflicting date information — filename "Feb 2025", cover page "2025", but every page footer says "Effective Oct 1, 2022." Use the **most recent date inferable from the filename or cover** as `Last price update`. Flag the discrepancy in response but proceed.

#### Purelux ingest output format

Produce an Excel file with all 58 schema fields as columns, records starting on row 2. File naming: `purelux_airtable_upload_[YYYY-MM-DD].xlsx`. Save to `/mnt/user-data/outputs/`.

---

### Evergreen

Evergreen Building Materials Ltd. is supplier and brand (single entity). Based in Mississauga, ON. Price list is a single-page PDF organized as one table with rows grouped by price tier and size/thickness combination. **Laminate only** — Evergreen does not sell other categories.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Evergreen` |
| **Brand** | `Evergreen` |
| **SKU supplier code** | `EVGR` — 4-char suffix |
| **Internal SKU format** | Use Evergreen's numeric code as SKU suffix: `LAM-EVGR-[code]` — e.g. `LAM-EVGR-72741`, `LAM-EVGR-2020`, `LAM-EVGR-SH003`. Strip any asterisks (clearance markers) from the code. |
| **SKU disambiguation for duplicate codes** | When the same code appears at two different thicknesses (e.g. `72113` in 14mm and 10mm tiers), append the thickness: `LAM-EVGR-72113` (14mm) vs `LAM-EVGR-72113-10MM` (10mm). These are genuinely different products. |
| **Supplier SKU** | Populate with Evergreen's raw code including any asterisk (e.g. `72102*`, `2020*`, `72741`, `SH003`). The asterisk is Evergreen's clearance marker. |

#### Cost column

Evergreen lists `Price / Sq.ft` per tier. Standard markup: `Retail = Cost + $1.00`.

**Clearance pricing nuance** — Evergreen marks clearance items with asterisks on the code AND yellow highlighting on the row AND a "*Clearance" label in the header. Pricing logic:

- **If the clearance item has a regular-price equivalent** (same thickness/dimensions in another tier): `Cost` = regular equivalent price, `Retail` = Cost + $1.00, `Promo cost ($/sf)` = clearance price.
  - Example: `2020*` at $1.69 has a regular equivalent at $1.79 in the same 48"×7.7"×12mm tier. Cost = $1.79, Retail = $2.79, Promo = $1.69.
- **If the clearance item has no regular equivalent** (unique thickness): `Cost` = clearance price, `Retail` = Cost + $1.00, `Promo cost ($/sf)` = clearance price.
  - Example: 10mm tier has no non-clearance equivalent. Cost = $1.49, Retail = $2.49, Promo = $1.49.
- **Stock status** = `Clearance` on all clearance rows.
- **Promo end date** = blank (Evergreen's price list is monthly — "Effective DD/MM/YYYY-DD/MM/YYYY" — and they don't publish separate promo end dates; the clearance holds while stock lasts).

#### LS Handle format

Brand-first alphanumeric: `EVGRLAM[code]`. Strip asterisks.

| Pattern | Example |
|---|---|
| `EVGRLAM[code]` | `EVGRLAM72741`, `EVGRLAM2020`, `EVGRLAMSH003` |
| `EVGRLAM[code][thickness]MM` (disambiguation) | `EVGRLAM7211314MM` — for the 14mm version when the 10mm version already exists in LS at handle `EVGRLAM72113`. |

**Handle disambiguation rule for duplicate codes**: when the same code appears at two thicknesses, the first one uploaded gets the clean handle; the second one (uploaded later) gets the thickness-disambiguated handle. In practice for the Sep 2025 list, the 10mm clearance items were uploaded first and hold the clean handles; 14mm versions of colliding codes get `[code]14MM` suffix in the handle.

#### LS Name prefix

| Product type | LS Name prefix |
|---|---|
| Laminate (all Evergreen products) | `EVGRLAM` |

#### Scope of ingest

In scope: Laminate flooring only.
Out of scope: Transition trims (T-molding/Reducer $12/pc, Stair Nosing $18/pc).

#### Collections

Evergreen doesn't use named "series" — their tiers are defined by size + thickness + waterproofing level. Use descriptive collection names:

| PDF tier | Collection name |
|---|---|
| Water Resistant 14mm, 60"×9.4" + 2mm pad, $1.69/sf | `Water Resistant 14mm` |
| Waterproof 10mm clearance, 60"×9.4", $1.49/sf | `Waterproof Drop Lock 10mm (Clearance)` |
| Waterproof 12mm clearance, 48"×7.7", $1.69/sf (`2020*`) | `Waterproof Drop Lock 12mm Short Plank` (same collection as the regular tier; stock status distinguishes it) |
| Waterproof 12mm regular, 48"×7.7", $1.79/sf | `Waterproof Drop Lock 12mm Short Plank` |
| Waterproof 12mm, 60"×9.4", $1.89/sf | `Waterproof Drop Lock 12mm Standard Plank` |
| Waterproof 12mm Large Board, 72"×9.4", $1.99/sf | `Waterproof Drop Lock 12mm Large Board` |

#### Material type defaults

| Collection | Material type |
|---|---|
| Water Resistant 14mm | `HDF core` |
| All Waterproof Drop Lock tiers | `Water-Resistant Core` |

Evergreen sells laminate only — no vinyl, no engineered, no solid hardwood.

#### Fields Evergreen does not provide

- **Colour names** — Evergreen publishes only numeric codes (e.g. `72741`, `SH003`, `2020`). **Rule: use the code verbatim as the colour name placeholder in Product name.**
- **Wear layer, AC rating, Finish type, Species, Veneer/top layer, Certifications, IIC/STC ratings, Warranty (residential & commercial), Weight per piece** — none are published. Leave all blank.
- **Underpad material** — only the 14mm Water Resistant tier explicitly says "2mm attached underlayment" (material unspecified; default to `EVA`). Waterproof tiers don't mention an attached pad — leave `Underpad included = FALSE` and `Underpad type` blank.
- **Install profile / locking system** — PDF says "Drop Lock" on waterproof tiers only. Laminate 14mm tier doesn't explicitly state; assume `Click` install profile + leave `Locking system` blank.

#### Suitability defaults

- **Waterproof = TRUE** for all "Waterproof Drop Lock" tiers (10mm, 12mm, 12mm Large Board).
- **Waterproof = FALSE** for Water Resistant 14mm (it is water-resistant, not waterproof).
- **Pet friendly = FALSE** across all Evergreen products — no wear layer or AC rating published to qualify.
- **Radiant heat compatible** = blank.

#### Effective date

Evergreen publishes a **monthly price list** with a date range in the header (e.g. "Effective Date: 2025/09/01-2025/09/30"). Use the **start date of the range** as `Last price update`. The end date is implicitly when the next monthly list supersedes it.

#### Layout parsing quirks

- **Numeric codes only** — no colour names anywhere. Use code as placeholder.
- **Asterisk = clearance marker** — `72102*`, `2020*`. Strip for SKU/handle; keep in Supplier SKU as printed.
- **Yellow highlighting** on the PDF = additional clearance visual. Rows with yellow fill match rows with asterisked codes.
- **Duplicate codes across thicknesses** — code `72113` and `72523` appear in both 14mm (regular) and 10mm (clearance) tiers. Treat as separate products; disambiguate SKU and LS handle.
- **Visual row spans** — occasionally a single code spans two visual rows in the PDF table (e.g. `72161`, `72146`). Treat as one code per instance.

#### Evergreen ingest output format

Produce an Excel file with all 58 schema fields as columns, records starting on row 2. Highlight clearance rows with yellow fill (`FFF3B0`) for visual scanning. File naming: `evergreen_airtable_upload_[YYYY-MM-DD].xlsx` (use effective-date start). Save to `/mnt/user-data/outputs/`.

---

### GreenTouch

GreenTouch Floors is a Toronto-area supplier of engineered hardwood flooring and SPC rigid core vinyl under the GreenTouch brand. Their price list is issued as a multi-page PDF, typically 10 pages, organized by species and collection with a consistent per-page layout: product category header at top, followed by species, veneer/thickness, install profile, plank dimensions, box/pallet specs, then the SKU/Name/Grade/Price table. Every page repeats the standard footer (25 year warranty, CARB II & FloorScore certified, contact info).

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `GreenTouch` |
| **Brand** | `GreenTouch` (supplier = brand; single-brand distributor) |
| **SKU supplier code** | `GRNT` — 4-char suffix, e.g. `ENG-GRNT-0042` |
| **Supplier SKU** | Always populated. GreenTouch assigns explicit codes on every product (e.g. `WB1361`, `AR1301`, `SP2801`). Copy verbatim. The only exception is the T-Moulding accessory which is listed with the descriptive name `T-MOULDING&REDUCER` — use that string as the Supplier SKU. |

#### Cost column

GreenTouch price lists show a **single Price column** per product — no pallet/box split. Use that value directly as `Cost/unit` for all flooring products (per sq ft) and for accessories (per piece — T-moulding/reducer).

#### Markup overrides

- **All flooring products** (engineered hardwood and SPC vinyl): standard `Retail = Cost + $1.00` (global rule).
- **T-Moulding & Reducer accessory**: no $/sf price. Store the listed per-piece cost in `Cost/unit` (unit = per piece) and leave `Retail price/unit` blank. Retail markup rule for accessories is TBD — flag in Salesperson notes.

#### Scope of ingest

Currently in scope: ENG (engineered hardwood), LVP (rigid core vinyl), and one accessory (T-moulding/reducer) — GreenTouch's full catalogue. They do not sell solid hardwood, laminate, tile, or carpet.

#### Collections naming

GreenTouch organizes products into five named collections. Use these verbatim for the `Collection` field:

- `Elegance` — White Oak engineered, 3mm veneer (pages 1–2: 6" and 7.5" widths, ABCD and ABC grades)
- `Purity` — White Oak engineered (page 3: 7.5" / 3mm veneer / ABC; page 4: 6" / 2mm veneer / ABCD)
- `Premium` — American Oak engineered, 7" × 85"RL, AB grade (page 5)
- `Rustic` — Maple (hand scraped) and Hickory (wire brushed) engineered, 7.25" × RL (page 6)
- `Antique` — ½" click products (pages 7–10): Red Oak, Maple, Hickory engineered (all ½" × 5" × RL), PLUS the SPC rigid core vinyl (page 10, 9" × 60"RL). The "Antique" label spans multiple product types — follow the PDF page header rather than trying to re-categorize.

#### Material type defaults

| GreenTouch section | Material type |
|---|---|
| Elegance / Purity / Premium / Rustic / Antique (hardwood pages 7–9) | `Hardwood plywood` |
| Rigid Core Vinyl (page 10, SP28xx) | `SPC core` |

GreenTouch does **not** sell solid hardwood, WPC core vinyl, or laminate on their standard list.

#### Fields GreenTouch does not provide

GreenTouch price lists generally **omit**:

- **Veneer thickness on Premium** (page 5) — not stated in the page header. Leave `Veneer / top layer (mm)` blank. Flag in Salesperson notes if relevant; verify with GreenTouch.
- **Veneer thickness on Rustic** (page 6) — not stated. Leave blank.
- **Finish type on Elegance / Purity / Premium** — not stated. Leave blank (smooth finish assumed but not confirmed).
- **Colour names for Rigid Core Vinyl** (SP2801–SP2810, page 10) — only SKU codes are listed. **Rule: use the SKU as the colour placeholder in Product name (Triforest-style).** Populate as `GreenTouch Rigid Core Vinyl 9" — SP28xx`. Do not invent or guess names. Flag in Salesperson notes: "Colour name not provided — confirm with GreenTouch before customer-facing quoting."
- **Underpad type on SPC vinyl** — page 10 states "Underlayment: 2mm" but does not name the material. Default to `IXPE` (industry standard for SPC at this price point); flag the assumption in Salesperson notes.
- **Radiant heat compatible** — not stated on any page. Leave blank across all products pending supplier verification.
- **IIC / STC ratings** — not provided. Leave blank.
- **Pet friendly on hardwood** — not stated. Leave blank (depends on finish hardness, which isn't specified).

GreenTouch price lists generally **do provide**:

- Supplier SKU (always — populate verbatim)
- Product name / colour (except SP28xx vinyl)
- Grade (always — using letter system, collapse to canonical 4)
- Price ($/sf)
- Plank dimensions (thickness, width, length type — RL or fixed)
- Box size (sf/box) and boxes per pallet
- Veneer thickness — stated for Elegance and Purity in page header ("3mm Veneer", "2mm Veneer")
- Finish type for Rustic and Antique pages (hand scraped, wire brushed, smooth) — stated in sub-section header
- Install profile — stated in page header ("3/4 Tongue & Groove" → T&G; "1/2 CLICK" → Click)
- Wear layer on vinyl — stated in section block ("0.5mm/20 mil") → populate `Wear layer (mil)` = 20
- Certifications and warranty — stated in page footer (CARB II, FloorScore, 25-year residential)

#### Suitability defaults

- **Waterproof = TRUE** for all Rigid Core Vinyl SP28xx products (SPC core).
- **Waterproof = FALSE** for all engineered hardwood (Elegance, Purity, Premium, Rustic, Antique hardwood pages 7–9).
- **Pet friendly = TRUE** for SP28xx vinyl (wear layer 20 mil meets global ≥20 mil threshold).
- **Pet friendly = blank** for hardwood (not stated by supplier; depends on finish hardness).
- **Radiant heat compatible = blank** for all products — not stated by GreenTouch. Verify per-product with supplier when condo/radiant customers ask.

#### Default applied values (every GreenTouch record)

| Field | Value |
|---|---|
| `Certifications` | `CARB II; Floorscore` |
| `Residential warranty (yrs)` | `25` |
| `Active` | `TRUE` |
| `Stock status` | blank (no clearance language observed) |

#### Product naming convention

```
GreenTouch [Collection] [SpeciesAbbrev] [width]" — [Colour] ([GradeAbbrev])
```

Species abbreviations: `WO` (White Oak), `AO` (American Oak), `RO` (Red Oak), `Maple`, `Hickory`. Grade abbreviations in parens: `S&B` (Select & Better), `Sel` (Select), `Char` (Character), `Rus` (Rustic).

Examples:
- `GreenTouch Elegance WO 6" — Lucca (Char)`
- `GreenTouch Premium AO 7" — Natural (S&B)`
- `GreenTouch Antique Hickory 5" — Bayleaf (S&B)`
- `GreenTouch Rigid Core Vinyl 9" — SP2801` (SKU as colour placeholder)
- `GreenTouch T-Moulding & Reducer` (accessory — no colour/grade)

#### LS Handle convention

Format: `GRNT[COLLECTION][SizeSpeciesCode][COLOR]` — uppercase, alphanumeric only, no separators.

Collection codes: `ELEG`, `PURI`, `PREM`, `RUST`, `ANTI`. Size/species codes: `6WO`, `75WO`, `7AO`, `725MP`, `725HK`, `5RO`, `5MP`, `5HK`, `9` (vinyl — width only). Vinyl uses `RCV` in place of a collection code.

Examples:
- `GRNTELEG6WOLUCCA` — Elegance / 6" / White Oak / Lucca
- `GRNTPREM7AONATURAL` — Premium / 7" / American Oak / Natural
- `GRNTRCV9SP2801` — Rigid Core Vinyl / 9" / SP2801
- `GRNTTMRED` — T-Moulding & Reducer accessory

**Grade variants share one handle.** On the Elegance 6" page, Lucca and Lecce each appear as both ABCD (Character) and ABC (Select). Both grade records get the same LS Handle so Lightspeed groups them as variants under one parent.

#### Layout parsing — what to watch for in the GreenTouch PDF

**Multi-box-size sub-groups under one page header** — GreenTouch frequently lists variants with different box sizes on the same page, separated by a `[N] sqft/box, [M] boxes/Pallet` line between groups. Create a separate record per sub-group with the correct box size:

- **Page 1 (Elegance 6")** — main group 28.42 sf / 27 boxes; alt group (Lecce ABC WB1382, Verona ABC WB1383) 29.71 sf / 27 boxes.
- **Page 5 (Premium)** — main group 20.70 sf / 42 boxes at 85"RL; Metal Gray (AR1311) is 22.6 sf at 95"RL (different length AND box size).
- **Page 7 (Antique Red Oak)** — three sub-groups:
  - Black Stone (RO2105), Silver Gray (RO2106) → 25.83 sf / 36 boxes (default from header)
  - Golden (RO2101) → 18.08 sf / 54 boxes
  - Gunstock (RO2102), Veyen (RO2107), Solin (RO2108), Haloak (RO2109), Mistra (RO2110) → 35.52 sf / 32 boxes

**The `35"` annotation on page 7** — next to RO2102, RO2109, RO2110, indicating fixed 35" plank length vs random length. Note in Salesperson notes; does not change any other field.

**Missing SKUs in sequence** — GreenTouch SKU numbering occasionally skips (e.g. Purity 6" goes WB1331, WB1333 — WB1332 missing). Do not create a placeholder; this is likely discontinued or unreleased.

**Page 10 SPC vinyl composite thickness** — `(6+2mm x 9" x 60"RL)` means 6mm SPC core + 2mm attached underpad = 8mm total. Populate `Thickness (mm)` = 8, `Underpad included` = TRUE, `Underpad type` = IXPE. Note the 6+2 split in Salesperson notes.

**Page 10 T-Moulding & Reducer** — single row at the bottom, dimensions `450*18/2+4.7*570`, price $15.00/piece. Create as one `ACC-GRNT-XXXX` record: Product type = Moulding, Category = LVP, `Cost/unit` = 15.00 (per piece).

#### Thickness mapping

| Supplier notation | Thickness (mm) |
|---|---|
| ¾" T&G | 19.05 |
| ½" Click | 12.7 |
| 6+2mm SPC | 8 (total; underpad included = TRUE) |

#### SALE / promo items

The Feb 1, 2026 list has no SALE items. If future lists add promos, apply the global Sale item pricing logic. GreenTouch does not appear to print promo end dates — leave `Promo end date` blank; promo holds until next price list or manual update.

#### Effective date

Every GreenTouch list is headed "Effective date: [date]" on every page. Record the effective date in `Price list reference` when logging to Price History Log.

#### Known ambiguities — confirm with GreenTouch before going live

- **Colour names for SP2801–SP2810** — 10 names needed; SKU placeholders in use.
- **Veneer thickness on Premium and Rustic** — not stated on those pages.
- **Underpad material on SP28xx** — IXPE is a default assumption, not confirmed.
- **Finish type on Elegance / Purity / Premium** — smooth assumed, not stated.
- **Missing WB1332** in Purity 6" sequence — confirm discontinued or unreleased.
- **Radiant heat compatibility** — not stated; verify species-by-species for condo customers.

#### GreenTouch ingest output format

File naming convention: `greentouch_airtable_upload_[YYYY-MM-DD].xlsx`. Save to `/mnt/user-data/outputs/`.

---

### Vidar

Vidar is supplier and brand (single entity). Engineered hardwood specialist with multiple width-based collections. Price list is issued as a multi-page PDF organized by collection (width), with grade variants listed as sub-rows under each colour.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Vidar` |
| **Brand** | `Vidar` |
| **SKU supplier code** | `VIDR` — 4-char suffix, e.g. `ENG-VIDR-0042`, `SPC-VIDR-0003`, `LAM-VIDR-0001`, `ACC-VIDR-0007` |
| **Supplier SKU** | Blank for engineered/laminate/accessories (no codes published). **SPC: Vidar now publishes SPC product codes — populate `Supplier SKU` from them.** |

#### Cost column

Vidar price lists show tiered volume pricing (cut order / 1–5 skids / 6–20 skids). **Use the 1–5 skid price as `Cost/unit`** unless otherwise instructed. Log the full tier schedule in `Volume pricing notes`.

Example: `Vidar: Cut order $1.39 / 1-5 skids $1.34 / 6-20 skids $1.29`

Standard markup applies: `Retail = Cost + $1.00`.

#### LS Handle format

Brand-first alphanumeric, no separators: `VIDR[WIDTH][SPECIES][COLOUR]` — uppercase, letters and numbers only.

| Pattern | Example |
|---|---|
| `VIDR[width][species][colour]` | `VIDR6AWOSILVERSTONE`, `VIDR75AWOMACAROON` |

Width codes: `6` (6"), `75` (7.5"), `9` (9"), `HB5` (herringbone 5"). Species codes: `AWO` (American White Oak), `EWO` (European White Oak), `EWA` (European White Ash), `ABW` (American Black Walnut). Colour is the colour name stripped to alphanumeric only, uppercased.

**Grade variants share one handle.** All grade variants of the same colour and width get the same LS Handle — Lightspeed groups them as variants under one parent.

#### LS Name prefix

| Product type | LS Name prefix |
|---|---|
| Engineered hardwood (all Vidar) | `VIDRENG` |

Full LS name format: `VIDRENG [Width]" [Species] — [Colour] ([GradeAbbrev])`

Grade abbreviations in parens: `S&B` (Select & Better), `Sel` (Select), `Char` (Character), `Rus` (Rustic).

#### Scope of ingest

**Full scope (expanded June 2026):** Engineered hardwood (all collections), **SPC** (`SPC-VIDR-####`), **Laminate** (`LAM-VIDR-####`), and **Accessories** (`ACC-VIDR-####` — stair boards/risers, stair nosings, reducers, T-mouldings, vents, underpads, adhesives). Vidar's price list is now a combined multi-page document covering all of these plus a separate promotion sheet.

Earlier guidance scoped Vidar as engineered-only; that restriction no longer applies.

#### Collections (use series name verbatim)

Engineered collections are named by width/layout:

- `6 Collection` — 6" width
- `7.5 Collection` — 7.5" width
- `9 Collection` — 9" width
- `Herringbone Collection` — 5" herringbone layout
- `Chevron Collection` — chevron layout
- `Versailles Collection` — Versailles panels
- `R&Q Collection` — R&Q herringbone/7" lines
- `Black Walnut Collection` — American Black Walnut (multiple widths)
- `Click Collection` — click-lock engineered

Plus non-engineered lines: `SPC Collection`, `Laminate Collection`, and accessories (no collection / `Accessories`).

#### Material type defaults

| Vidar section | Category | Material type |
|---|---|---|
| All engineered (6/7.5/9/HB/Chevron/Versailles/R&Q/Black Walnut/Click) | `Engineered hardwood` | `Hardwood plywood` |
| SPC | `LVP` | `SPC core` |
| Laminate | `Laminate` | `HDF core` |
| Accessories | match parent product line | `Accessory` (Product type) |

Species codes seen: `AWO` (American White Oak), `EWO` (European White Oak), `EWA` (European White Ash), `ABW` (American Black Walnut).

#### Grade mapping

Vidar uses European letter grades — always collapse to canonical 4:

| Vidar says | Airtable Grade |
|---|---|
| `AB` | `Select & Better` |
| `ABC` | `Select` |
| `ABCD` | `Character` |
| `EF` | `Rustic` |

Each grade of the same colour is a separate Airtable record with a shared LS Handle.

#### Fields Vidar does not provide

- **Supplier SKU** — blank (no codes published).
- **Wear layer, AC rating** — engineered hardwood only; leave blank.
- **IIC / STC ratings** — not provided. Leave blank.
- **Certifications** — not stated on price list. Leave blank.
- **Radiant heat compatible** — **Black Walnut = FALSE** (global schema rule). All other species leave blank pending supplier verification.

Vidar **does provide**:
- Colour names on every product.
- Grade (letter system — always stated).
- Overall thickness (mm) and veneer thickness (mm).
- Width (in) and plank length.
- Box size (sf/box) and boxes per skid.
- Volume pricing tiers.

#### Suitability defaults

- **Waterproof** = **TRUE** for SPC; **FALSE** for engineered hardwood and laminate.
- **Pet friendly** = blank for engineered/laminate (no qualifying wear layer stated); SPC blank unless a wear layer ≥ 20 mil is stated.
- **Radiant heat compatible** = FALSE for Black Walnut. Blank for all other species/lines.

#### Promo handling (Vidar-specific)

Vidar runs an "on-going color" promotion sheet separate from the regular price list, using letter-grade columns (ABCD/EF/ABC/AB) that map to the canonical grades. Observed behaviour: the same promo prices carry forward month to month with only the **end date** changing, so a cycle is usually a **date roll** of existing promo records, not new prices. Workflow:

- Match each promo line to the existing catalogue record **by colour + width + mapped grade** (grade match is strict — never apply a promo to the wrong grade).
- If the promo price is unchanged, only roll `Promo end date`; otherwise update `Promo cost ($/sf)` too.
- Any record carrying a **prior-cycle promo that is not on the new sheet** must have `Promo cost` and `Promo end date` **cleared**.
- A promoted grade with no matching record gets a new record per the global "Promo product not found" rule — but note this is what produced the orphan records below, so prefer matching an existing grade record first.
- **Vents** are handled as `Promo applied` at the clearance price **and** `Stock status = Discontinued` when the sheet marks them discontinued.

Log every applied/cleared promo to `Price History Log v2` with the matching `Entry type`.

#### Known data quality issues (confirm before going live)

- **Duplicate variant on `VIDR9ABWNATURAL`** — two records share the same handle due to a duplicate grade entry. Confirm with supplier which record is correct; delete the duplicate in Airtable.
- **Handle conflict on `VIDRHB5AWOMACAROON`** — handle collision between herringbone and standard collections. Verify handle disambiguation before re-uploading.
- **Macaroon 7" AWO Character duplicate** — `ENG-VIDR-0182` duplicates `ENG-VIDR-0100C` (same 7" AWO Macaroon Character). Both carried the promo; promo logic now targets `0100C`. Archive `0182` after confirming.
- **Mis-graded Ash orphans** — `ENG-VIDR-0189/0190/0191` (7.5" EWA Night Owl / Sunset / Ebony) are stored at **Character** grade, but the June promo for those colours is **Select** (correctly applied to `0073/0074/0076`). These three are leftover "promo grade not found" artifacts at the wrong grade. Archive after confirming.
- **`ENG-VIDR-0183`** (6" EWA Whistler **Select**) is the legitimate Select-grade promo target (the regular 6" EWA Whistler record `0030` is S&B); keep it and roll its promo. This is the correct pattern, in contrast to the orphans above.

#### Vidar ingest output format

File naming convention: `vidar_airtable_upload_[YYYY-MM-DD].xlsx`. Save to `/mnt/user-data/outputs/`.

---

### Grandeur

Grandeur is supplier and brand (single entity). Multi-category supplier: engineered hardwood, solid hardwood, SPC/WPC LVP, laminate, and specialty products. Price list is issued as a multi-page PDF organized by product category. Grandeur enforces MAP pricing — **never quote Cost to customers; only Retail price is customer-facing**.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Grandeur` |
| **Brand** | `Grandeur` |
| **SKU supplier code** | `GRAN` — 4-char suffix for Supplier SKU matching; internal SKU uses `GRND` prefix |
| **Internal SKU prefix** | `GRND` — e.g. `GRNDENG-0001`, `GRNDLVP-0001` |
| **Supplier SKU** | Populate with Grandeur's product code verbatim (they publish codes on their price list). SKU prefix by product type: `GRAN` (general), varies by line — confirm per price list. |

#### SKU prefix by product type

| Category | LS Name prefix | Example SKU |
|---|---|---|
| Engineered hardwood | `GRNDENG` | `GRNDENG-0001` |
| Solid hardwood | `GRNDHWD` | `GRNDHWD-0001` |
| SPC/WPC LVP | `GRNDLVP` or `GRNDWPC` | `GRNDLVP-0001` |
| SPC (rigid core) | `GRNDSPC` | `GRNDSPC-0001` |
| Laminate | `GRNDLAM` | `GRNDLAM-0001` |

#### Cost column

Grandeur lists a single price column per product. Use that value as `Cost/unit`. Standard markup applies: `Retail = Cost + $1.00`.

**MAP pricing** — Grandeur enforces Minimum Advertised Price on some lines. When MAP is listed:
- Store MAP in `MAP price ($/sf)` field.
- Bert will not quote below MAP — it uses `MAP price` as the floor when present.
- Standard `Retail = Cost + $1.00` still applies for internal cost tracking.

#### LS Handle format

Brand-first alphanumeric, no separators: `GRND[PRODTYPE][COLLECTION/COLOUR]` — uppercase, alphanumeric only.

| Pattern | Example |
|---|---|
| `GRNDENG[colour]` | `GRNDENGSILVERSTONE` |
| `GRNDLVP[colour]` | `GRNDLVPMACAROON` |
| `GRNDLAM[colour]` | `GRNDLAMCAFÉMOCHA` → `GRNDLAMCAFEMOCHA` |

Strip accents and special characters. Grade variants share one handle (same colour, different grade = same LS Handle for variant grouping).

#### Scope of ingest

In scope: ENG, HWD, SPC, WPC, LVP, LAM. Out of scope: Accessories (mouldings, stair nosings) unless explicitly brought in scope.

#### Collections

Use collection names verbatim from the Grandeur price list. Grandeur organizes products into named series per product type — confirm collection names from the specific price list being processed.

#### Grade mapping

Grandeur uses standard North American grade terms — store verbatim if they use the word "Grade", or map letter grades to canonical 4 if they use the European system:

| Grandeur says | Airtable Grade |
|---|---|
| `AB` | `Select & Better` |
| `ABC` | `Select` |
| `ABCD` | `Character` |
| `EF` | `Rustic` |
| Named grade (e.g. "Prime Grade") | Store verbatim |

For **European White Ash**: ABC = Select, AB = Select & Better.
For **American/European White Oak**: ABCD = Character, EF = Rustic.

Apply grade mapping **per species** — always confirm the species context before mapping a letter grade.

#### Fields Grandeur does not provide (confirm per price list)

Confirm which fields are omitted on the specific price list being processed. Common omissions:
- **Certifications** — not always stated. Leave blank if not listed.
- **IIC / STC** — not provided. Leave blank.
- **Radiant heat compatible** — not stated explicitly. Black Walnut = FALSE (global rule). Leave blank for others.

#### Suitability defaults

- **Waterproof = TRUE** for all LVP/SPC/WPC vinyl products.
- **Waterproof = FALSE** for engineered hardwood, solid hardwood, laminate.
- **Pet friendly = TRUE** when wear layer ≥ 20 mil.
- **Radiant heat compatible = FALSE** for Black Walnut. Blank for all others.

#### Upload stats (reference)

From the most recent Grandeur LS upload:
- **238 total products** extracted from price list.
- **163 updates** to existing LS records + **75 new products** added.
- Airtable upsert used `performUpsert` with `fieldIdsToMergeOn: ['fldx3byCOht5HbKmH']` (SKU field).

#### Grandeur ingest output format

File naming convention: `grandeur_airtable_upload_[YYYY-MM-DD].xlsx`. Save to `/mnt/user-data/outputs/`.

---

### Sunshiny

Sunshiny is supplier and brand (single entity), and also distributes the **Appalachian** brand (Canadian solid hardwood manufacturer based in Quebec). Their price list is issued as a PDF organized in a clearly visible table layout by product category. Products are identified by 4-digit numeric codes throughout — colour names are only provided for Appalachian solid hardwood.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Sunshiny` |
| **Brand** | `Sunshiny` for ENG, LVP, LAM, ACC; `Appalachian` for solid hardwood (HWD) |
| **SKU supplier code** | `SUNS` — 4-char suffix, e.g. `ENG-SUNS-0001`, `LVP-SUNS-0001` |
| **Supplier SKU** | Always populated. Sunshiny assigns 4-digit numeric codes to every product (e.g. `2806`, `7220`, `6210`). Copy verbatim. |

#### Cost column

Sunshiny price lists show a **single Dealer/Retailer price column** per product. Use that value directly as `Cost/unit` for all flooring products. Ignore any deposit or CAD-column variants if present.

Standard markup applies: `Retail = Cost + $1.00` for all flooring.

#### Markup overrides — accessories (cross-supplier standard)

The following accessory markup rules apply to Sunshiny and **all suppliers** across the catalogue:

| Accessory type | Retail markup | Output field |
|---|---|---|
| Reducer | Cost + $10 | `Retail price/unit` |
| T-Moulding | Cost + $10 | `Retail price/unit` |
| Stair Nose / Nosing | Cost + $15 | `Retail price/unit` |
| Stair Tread (vinyl, no riser) | Cost + $15 | `Retail price/unit` |
| Underlayment | Cost + $20 | `Retail price/unit` |

For accessories, store the supplier's per-piece cost in `Cost/unit` (unit = per piece) and put the marked-up price in `Retail price/unit`. The unit is per piece, not per sq ft.

#### Scope of ingest

In scope: ENG, LVP, HWD, LAM, ACC (PVC accessories: T-Moulding, Reducer, Stair Nose, Stair Tread, Underlayment).
Out of scope: anything else not listed above unless explicitly brought in scope.

#### Collections (use verbatim)

| Collection | Category | Notes |
|---|---|---|
| `European Oak 2mm Veneer` | ENG | 2mm top layer |
| `European Oak 3mm Veneer` | ENG | 3mm top layer, "Character Grade" label |
| `European Oak 4mm Veneer` | ENG | 4mm top layer |
| `Riche` | LVP | All SPC vinyl collections |
| `Signature` | HWD | Appalachian solid hardwood |
| `Toronto` | LAM | Laminate collection |
| `PVC Accessories` | ACC | PVC stair and transition pieces |
| `Underlayment` | ACC | Underpad rolls |

#### Brand split rules

- **ENG, LVP, LAM, ACC** → `Brand = Sunshiny`, `Supplier = Sunshiny`
- **HWD (solid hardwood)** → `Brand = Appalachian`, `Supplier = Sunshiny`
  - Appalachian is a highly regarded Canadian brand (Quebec-based). Flag this to customers as a premium Canadian product.

#### SKU prefix by product type

| Category | Internal SKU prefix | Example |
|---|---|---|
| Engineered hardwood | `ENG-SUNS-` | `ENG-SUNS-0001` |
| LVP (SPC) | `LVP-SUNS-` | `LVP-SUNS-0001` |
| Solid hardwood | `HWD-SUNS-` | `HWD-SUNS-0001` |
| Laminate | `LAM-SUNS-` | `LAM-SUNS-0001` |
| Accessories | `ACC-SUNS-` | `ACC-SUNS-0001` |

Note: Even though Appalachian solid hardwood uses `Brand = Appalachian`, the SKU prefix stays `HWD-SUNS-` since Sunshiny is the supplier.

#### LS Handle format

Brand-first alphanumeric, no separators, uppercase only:

| Pattern | Example |
|---|---|
| ENG: `SUNY[veneer][species][colour]` | `SUNY3MMEOAKNATURAL` |
| LVP: `LVP[width][SPC][code]` | `LVP709SPC7220` |
| HWD: `HWD[width][species][colour]` | `HWD425REDOAKNATURAL` |
| LAM: `LAM[code]` | `LAM8301` |
| ACC: `ACCSUNS[type][code]` | `ACCSUNSREDUC001` |

Grade variants (where they exist) share one handle. Appalachian solid hardwood has named grades (Prestige Grade, Excel Grade) — these are separate records sharing one handle per colour.

#### LS Name prefix

| Product type | LS Name prefix |
|---|---|
| Engineered hardwood | `SUNENG` |
| LVP / SPC | `SUNLVP-SPC` |
| LVP / WPC | `SUNLVP-WPC` |
| Solid hardwood (Appalachian) | `APPHWD` |
| Laminate | `SUNLAM` |
| Accessories | `SUNACC` |

#### Grade mapping

**Engineered hardwood (Sunshiny European Oak):**

| Sunshiny says | Airtable Grade |
|---|---|
| `Character Grade` | `Character` |
| `ABCD Grade` | `Character` |
| Letter grade `ABCD` | `Character` |

**Solid hardwood (Appalachian):**

| Appalachian says | Airtable Grade |
|---|---|
| `Prestige Grade` | `Prestige Grade` (verbatim — new single-select option) |
| `Excel Grade` | `Excel Grade` (verbatim — new single-select option) |

Appalachian grades are proprietary named grades — store verbatim per the grade translation rule. Add a Salesperson note: "Appalachian Prestige Grade is a premium/select tier; Excel Grade is their character/lower tier. Confirm exact equivalence with Sunshiny rep."

**LVP and Laminate:** No grade stated — leave `Grade` blank across the board.

#### Colour names and product identification

- **LVP (SPC) and Laminate**: Products are identified by 4-digit code only — no colour descriptions on the price list. Use the code verbatim as the colour placeholder in Product name (e.g. `Sunshiny SPC 8mm 7.09" — 7220`). Flag in Salesperson notes: "Colour not specified on price list — verify via Sunshiny inventory check."
- **ENG**: Colour names may or may not be stated. If not stated, use the supplier code verbatim as placeholder.
- **HWD (Appalachian)**: Colour names are always provided (e.g. Natural, Amaretto). Use verbatim.

#### Material type defaults

| Section | Material type |
|---|---|
| All ENG | `Hardwood plywood` |
| All LVP / SPC | `SPC core` |
| All LVP / WPC | `WPC core` |
| All HWD | *(leave blank — solid hardwood)* |
| All LAM | `HDF core` (unless stated as waterproof) |

#### Locking systems

Sunshiny uses multiple locking systems depending on collection — stated in the section header or product notes:

- **5G locking** — standard for most engineered and some SPC lines
- **Uniclick / Uniclic** — some engineered lines
- **I4F locking** — some SPC lines
- Populate `Locking system` from what the PDF states per product group. Leave blank if not stated.

#### Underpad

- **SPC with attached pad**: underpad is `IXPE` (industry default for Sunshiny SPC lines unless stated otherwise). Set `Underpad included = TRUE`, `Underpad type = IXPE`. Flag assumption in Salesperson notes.
- **ENG**: no attached underpad — `Underpad included = FALSE`.
- **HWD**: no attached underpad — `Underpad included = FALSE`.

#### IIC / STC ratings

Sunshiny publishes IIC and STC ratings for their SPC lines. Populate from the price list when stated. Typical values: `IIC 73`, `STC 72` — but always confirm from the specific product group rather than assuming.

#### Suitability defaults

- **Waterproof = TRUE** for all LVP/SPC products.
- **Waterproof = FALSE** for ENG, HWD, LAM.
- **Pet friendly = TRUE** when wear layer ≥ 20 mil.
- **Pet friendly = FALSE** for < 20 mil wear layer, hardwood, and laminate.
- **Radiant heat compatible** — not explicitly stated by Sunshiny. Leave blank across all products pending supplier verification.

#### Fields Sunshiny does not provide

- **Colour names on SPC and LAM** — use 4-digit code as placeholder.
- **Grade on LVP and LAM** — leave blank.
- **Certifications** — not listed. Leave blank.
- **Warranty** — not stated on price list. Leave blank.
- **Radiant heat compatibility** — not stated. Leave blank.
- **Veneer cut type** — not stated. Leave blank.
- **Finish type on ENG/HWD** — not always stated. Leave blank unless the PDF specifies.

Sunshiny **does provide**:

- Supplier SKU (4-digit code, always)
- Overall thickness and composite thickness (e.g. 8+2mm)
- Width (in) and plank dimensions
- Box size (sf/box) and boxes per skid
- Wear layer on SPC (stated in section header)
- IIC / STC on SPC (stated in section header)
- Locking system (stated per section)
- Colour names on Appalachian HWD

#### SALE / promo items

Sunshiny does not typically show promos on their standard price list. If a promo appears, it may be marked with a cross (✗) or red highlight. Apply the global Sale item pricing logic. Sunshiny does not publish promo end dates — leave `Promo end date` blank; promo holds until next price list or manual update.

#### Sunshiny ingest output format

File naming convention: `sunshiny_airtable_upload_[YYYY-MM-DD].xlsx`. Save to `/mnt/user-data/outputs/`.

---

### Woden Flooring

Woden Flooring (order@wodenflooring.com, 905-475-0339, wodenflooring.com) is both the supplier and the brand. Their price list is a multi-page PDF organized by category with a price-tag graphic per collection and "identical to" colour cross-references between formats.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Woden` |
| **Brand** | `Woden` (supplier is the brand) |
| **SKU supplier code** | `WODN` — 4-char suffix, e.g. `LVP-WODN-0001`, `ENG-WODN-0042` |
| **Supplier SKU** | Leave blank. Woden's colour codes (601, 101, H01, 1201…) are not standalone product codes — they're folded into Product name / LS Handle, not stored as Supplier SKU. |

#### Cost column

Woden prints a single per-sf price per collection (sometimes two/three price tags where promo tiers exist). That price is the **cost**. Standard markup applies: `Retail = Cost + $1.00`. Accessories and underpad are priced per piece and are also costs (see below).

#### Scope of ingest

In scope: Vinyl SPC plank collections, Vinyl Herringbone, Glue Down, Looselay, Laminate, Engineered hardwood, and Vinyl Accessories + Underpad (page 5). **Out of scope:** MDF Baseboard / Quarter Round / Doorstop (page 7-8) — consistent with the moulding exclusion applied to other suppliers.

#### Collections (use verbatim)

- **SPC plank:** `6 Collection` (6mm), `7 Garnet Collection` (7mm), `8 Diamond Collection` (8mm, NEW), `7 Diamond Collection` (7mm, CLEARANCE), `9 Collection` (9mm), `11 Collection` (11mm)
- **Herringbone:** `Vinyl Herringbone Collection` (7mm, 5"×24")
- **Glue down:** `3mm Glue Down Collection`
- **Looselay:** `5mm Looselay Collection`
- **Laminate:** `12 Collection` (12mm)
- **Engineered:** `Vermont Collection`, `Elite Collection`, `Grand Chateau Collection`, `Timbercraft Collection`, `Monte Rosa Collection`, `Monte Rosa Herringbone Collection`, `6 1/2 Monte Rosa Collection` (NEW), `Lumine Collection`

#### Category & Material type mapping

| Woden section | Category | Material type |
|---|---|---|
| All SPC plank + Herringbone vinyl | `LVP` | `SPC core` |
| 3mm Glue Down (pure vinyl, full-spread adhesive) | `LVP` | `Dry-back vinyl` |
| 5mm Looselay (pure vinyl, friction-backed) | `LVP` | `Loose-lay vinyl` |
| 12 Collection laminate | `Laminate` | `HDF core` |
| All engineered | `Engineered hardwood` | `Hardwood plywood` |

**Dry-back vs Loose-lay are NOT interchangeable.** Dry-back (`Dry-back vinyl`, Install = Glue down) needs full-spread adhesive across the floor. Loose-lay (`Loose-lay vinyl`, Install = Loose lay) is a heavier friction-backed plank installed with little/no adhesive. Use the distinct Material type values — do not collapse to `SPC core`. (Note: legacy FAW Aqualuuuz and Triforest/Toucan loose-lay records are currently mis-stored as `SPC core`; flagged as a future cleanup, do not replicate that error for Woden.)

#### Grade mapping

Woden uses European letter grades on engineered lines plus one word grade:

| Woden says | Airtable Grade |
|---|---|
| `AB Grade` | `Select & Better` |
| `ABC Grade` | `Select` |
| `Character Grade` | `Character` (verbatim — word "Grade" present) |
| (no grade stated — Vermont, all vinyl, laminate) | blank |

**Lumine** lists the same colours in both AB and ABC at different prices (AB @ $5.49, ABC @ $4.99) — split into two records per colour, one per grade, with the grade in the Product name suffix (` — Snowhaze AB` / ` — Snowhaze ABC`).

#### Specs Woden provides / omits

Provides: overall thickness, plank size (in), box size (sf), pieces per box (most lines), SPC core + pad composition, ENG top-layer thickness, ENG species (American/European Oak), ENG finish (wire brushed / smoked / sawmark), ENG full-length %, Looselay wear layer (20 mil), condo-pad IIC/STC.

Omits (leave blank): wear layer on SPC planks (not stated), AC rating on laminate, certifications, warranty, radiant heat compatibility, colour names on code-only vinyl (6/Glue Down/Looselay colours are numeric codes — use code as placeholder, flag to verify).

ENG thickness is printed as ¾" → store `Thickness (mm) = 19.05`. SPC "PAD" layer → `Underpad included = TRUE`, `Underpad type = IXPE` (assumed material, flag in notes). Glue-down and looselay have no attached pad → `Underpad included = FALSE`.

#### Suitability defaults

- **Waterproof = TRUE** for all vinyl (SPC, herringbone, glue down, looselay). **FALSE** for laminate and engineered.
- **Pet friendly = TRUE** only where wear layer ≥ 20 mil → applies to **Looselay only** (SPC planks don't state wear layer → FALSE). Engineered/laminate FALSE.
- **Radiant heat compatible** — not stated. Leave blank.

#### Promo / clearance handling (Woden-specific)

Woden uses two distinct words and they map differently:

- **"Clearance / while stock last"** (7 Diamond Collection) → `Stock status = Clearance` **and** apply Sale pricing. No regular price exists on the list for 7 Diamond, so **Sale rule 3**: `Cost = SALE price`, `Retail = Cost + $1.00`, `Promo cost = SALE price`. Cost = Promo cost signals original cost unavailable. Note "while stock last; final sale" and the 8 Diamond replacement.
- **"(promotion)"** (Vermont Charcoal @ $2.50; Grand Chateau Natural/Coyote @ $2.50; and effectively the lower in-collection price tiers) → `Stock status` stays **blank**; `Promo cost = promo price`; `Cost` = the in-collection regular price (Sale rule 1). For Grand Chateau Natural/Coyote no separate regular price is printed → use the nearest in-collection regular tier ($3.29) as Cost and flag to confirm.
- **No promo end dates** — Woden never prints them. Leave `Promo end date` blank; promo holds until next list or manual update.

Multi-tier collections (Elite 3.79/3.59, Grand Chateau 3.79/3.29/2.50, Timbercraft 5.99/5.49, Lumine 5.49/4.99) are priced per colour at the tier shown — these are different price points, not promos, unless the word "promotion" appears.

#### Accessories & underpad (page 5) — costs, apply standard markups

All per-piece. Woden list prices are **costs** → store in `Cost/unit` (unit = per piece); the marked-up value goes in `Retail price/unit`. Apply the standard accessory markups:

| Item | Cost/unit | Markup | Retail price/unit |
|---|---|---|---|
| Reducer | $15 | +$10 | $25 |
| T-Moulding | $15 | +$10 | $25 |
| Stair Nosing (Round Return) | $18 | +$15 (stair nose) | $33 |
| Stair Board (Square Return) set (1 stair + 1 riser) | $38 | +$15 | $53 |
| Riser (sold separately) | $8 | +$15 | $23 |
| 2mm Blue Underpad w/ vapour barrier (200 sf) | $6 | +$20 | $26 |
| 3mm Black EVA Condo Pad, silver foil, IIC 73/STC 72 (200 sf) | $17 | +$20 | $37 |

Riser-alone and the square-return set both lack a dedicated markup standard — Stair Tread +$15 applied as the closest rule; flag to confirm with rep. Accessories: `Category = LVP`, `Material type = SPC core` (or blank for underpad), `Product type = Accessory`/`Underpad`. The condo pad's IIC 73 / STC 72 go in the IIC/STC fields.

#### "Identical to" colour cross-references

Glue Down, Herringbone, and Looselay colours list "identical to [plank code]" (e.g. Glue Down 301 = plank 702). These are the same visual in a different format — **create separate records per format**, do not merge. Record the equivalence in `Salesperson notes` so Bert can cross-sell formats.

#### Known soft spots

- **6½ Monte Rosa Collection (NEW)** — no price and no box size on the May 20 list. Create records (Active TRUE) with Cost/Retail/Box blank; flag for Woden to confirm before quoting.
- **8 Diamond replaces 7 Diamond** — page-1 note: 7 Diamond (7mm) being upgraded to 8 Diamond (8mm), same colours/pricing tier, 7 Diamond on clearance while stock lasts. Both collections exist as records during the transition.
- **PDF typos** — colour 1108 printed "Wheatfiled" → store as Wheatfield; preserve other names verbatim.
- **Wear layer absent on SPC planks** — leave blank, do not infer; this also forces Pet friendly = FALSE for those lines.

#### Woden ingest output format

Produce an Excel file with all 56 schema columns. File naming: `woden_airtable_upload_[YYYY-MM-DD].xlsx` using the list's Effective date. Save to `/mnt/user-data/outputs/`.

---

### CIF Distributors

CIF Distributors (4700 Dixie Road, Unit 2, Mississauga ON L4W 2R1 — 905-455-0573 / 1-888-579-3009 — orderdesk@cifltd.ca — cifdistributors.ca) is a Mississauga-based tile and stone distributor. They are **not a flooring supplier** in the plank sense — their entire catalogue is ceramic / porcelain field tile, mosaics, large-format slabs, and fabricated marble + quartz pieces (thresholds, shower jambs, benches). The price list is a single multi-page PDF (~70 pages) opening with a Terms & Conditions letter, then mosaics (pp. 2–8), regular tiles A–Z (pp. 9–36), STONE accessories (pp. 37–38), Qty-Discount summary (p. 39), Qty-Discount net pricing (pp. 40–41), and a Clearance section (pp. A1–A29).

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `CIF Distributors` |
| **Brand** | `CIF Distributors` (supplier is also the brand — they distribute Spanish/Italian/Portuguese/Chinese/Turkish/Indian-made tile under their own catalogue) |
| **SKU supplier code** | `CIFD` — 4-char suffix. Two prefixes in use: `TIL-CIFD-####` for tile/mosaic (Category = `Tile / Stone`), `STN-CIFD-####` for marble/quartz thresholds/jambs/benches (Category = `STONE`) |
| **Supplier SKU** | Leave blank. CIF's series codes (B-32, FAOA-2, GPR 662, IDLL4810A, etc.) are colour identifiers within a series — they're folded into Colour / tone and the LS Handle, not stored as Supplier SKU. |

#### Cost column — the 40% discount

The Terms & Conditions letter (page 3 of every list) states: *"As a valued customer we will be offering you a 40% discount off the list price on all items listed unless otherwise stated by your sales representative."* And: *"All product from CIF Distributors contain suggested retail pricing to protect the retailer."*

**This means every printed cost column on the price list is list price (the retailer's suggested retail to end customers), not Titan's actual cost.** Apply a single ×0.60 multiplier to convert to Titan's cost before pasting into `Cost/unit`:

```
Cost/unit = printed "Cost Per Sq Ft" (or "Cost per piece") × 0.60
```

Round to two decimals. Apply this exactly once — do not double-discount. The pages labelled "Net Cost" (pp. 40–41) are a separate qty-discount tier (10+ pieces) and are out of scope for the standard ingest; do not use those numbers as the regular cost.

#### Markup overrides — CIF only

CIF breaks the standard `Retail = Cost + $1.00` rule. Three distinct markup tiers apply:

| Product type | Markup | Notes |
|---|---|---|
| Tile (porcelain, ceramic field tile, slabs) | `Retail = Cost + $2.00` | Applies to floor and wall tile, regardless of size or material |
| Mosaic (anything `Tile format = Mosaic`, including hex mosaics, listellos, pencils, decors) | `Retail = Cost + $5.00` | Higher markup reflects accent-product positioning |
| STONE (marble/quartz thresholds, jambs, benches — Category = `STONE`) | `Retail = 0` (leave at zero) | Markup rule unsettled; leave `Retail price/unit = 0` and flag for Albert to set. Do not infer. |

These overrides are **CIF-specific** and do not generalize to other tile suppliers.

#### Scope of ingest

**In scope:**
- All mosaics (pp. 2–8) — Bamboo Glass, Crackle Glass, Crackle Glass & Stone, Glass, Glass & Stone, Glazed Porcelain mosaics, Irregular Glass, Marble mosaics + chevron, Metal/Glass Mix, Metal & Stone, Mother of Pearl, Porcelain/Glass Mix, Porcelain Hexagons/Planks/Squares/Mosaics, Stainless, Stone mosaics
- All regular tile series (pp. 9–36) — Aldo through Zeus
- STONE accessories (pp. 37–38) — Marble + Quartz thresholds, shower jambs, benches

**Out of scope:**
- **Clearance pages A1–A29** (tile clearance) — skip entirely, do not ingest
- **Page 8 "Clearance (while quantities last)" mini-table** — skip
- **Qty Discount summary (p. 39) and Net Cost tables (pp. 40–41)** — these are a 10pc+ tier, not a separate product set; reference only if a customer is ordering in bulk
- **Terms letter (p. 3)** — reference for pricing rules, not a product

#### Category & Material type mapping

| CIF section | Category | Material type | Tile format | Layout pattern |
|---|---|---|---|---|
| Mosaic — Glass, Glass mixes (Bamboo, Crackle, Glass, Glass & Stone, etc.) | `Tile / Stone` | `Glass`, `Glass / stone`, or `Glass / mixed` | `Mosaic` | `Mosaic` |
| Mosaic — Marble (Carrara, Crema Perla, Oriental White, Chevron) | `Tile / Stone` | `Marble` | `Mosaic` | `Mosaic` (or `Herringbone` / `Chevron` if the layout is the sale point) |
| Mosaic — Porcelain (Glazed Porcelain mosaics, Porcelain Mosaic series, hex mosaics) | `Tile / Stone` | `Porcelain` | `Mosaic` | `Mosaic` (or `Hexagon` for hex) |
| Mosaic — Porcelain / Glass Mix (MT003 series) | `Tile / Stone` | `Porcelain / glass` | `Mosaic` | `Mosaic` |
| Mosaic — Mother of Pearl (LS series) | `Tile / Stone` | `Mother of pearl` | `Mosaic` | `Mosaic` |
| Mosaic — Stainless (FAOS, HS032, YGS015) | `Tile / Stone` | `Stainless steel` | `Mosaic` | `Mosaic` |
| Mosaic — Metal/Glass or Metal & Stone | `Tile / Stone` | `Metal / glass` or `Metal / stone` | `Mosaic` | `Mosaic` |
| Mosaic — Stone (Carrara, Escarp, Crema Marfil mosaics) | `Tile / Stone` | `Marble / stone` | `Mosaic` | `Mosaic` |
| Field tile — Spanish/Italian/Portuguese porcelain (Aldo, Alma, Cementone, Croisette, etc.) | `Tile / Stone` | `Porcelain` | (blank — defaults to floor) | (blank) |
| Field tile — Ceramic wall tile (Subway, Cristalli, Broadway, Monokini, Manhattan glossy 13×24, etc.) | `Tile / Stone` | `Ceramic` | `Wall` | (blank) |
| Large-format porcelain slabs (Onyx Blend, Porcelain Slabs, Pantheon, Trevi) | `Tile / Stone` | `Porcelain` | (blank) | (blank) |
| Threshold (marble or quartz, p. 37–38) | `STONE` | `Marble` or `Quartz` | (blank) | (blank) |
| Shower Jamb (marble or quartz) | `STONE` | `Marble` or `Quartz` | (blank) | (blank) |
| Bench (marble or quartz) | `STONE` | `Marble` or `Quartz` | (blank) | (blank) |

The country of origin printed at each section header (Italy, Spain, Portugal, China, India, Turkey) goes into `Salesperson notes` (`Origin: Italy`) — there is no dedicated country field.

#### Colour and size variants — handle grouping

CIF series typically offer one colour at multiple sizes (e.g. Aldo Bianco at 12×24, 24×24, 32×32 at different prices) and many colours at one size (e.g. Cementone in Dark/Grey/Sand/Smoke at 12×24 and again at 24×24). Each colour × size combination gets its own record. **Size variants of the same colour share an LS Handle / Parent ID**, the same way grade variants share a handle for engineered hardwood. Example:

- Aldo Bianco 12×24 → `LS Handle = CIFDALDOBIANCO`
- Aldo Bianco 24×24 → `LS Handle = CIFDALDOBIANCO` (same)
- Aldo Bianco 32×32 → `LS Handle = CIFDALDOBIANCO` (same)
- Aldo Lander (Gray) 12×24 → `LS Handle = CIFDALDOLANDER` (different colour, different handle)

This means Lightspeed groups all sizes of one colour under a single parent variant.

Different finishes of the same colour (e.g. Glacier Grey polished 12×24 vs. Glacier Grey matte 12×24) get **separate handles** — finish is a meaningful variant: `CIFDGLACIERGREY` (polished) vs. `CIFDGLACIERMATTEGREY` (matte). Same logic for glossy-vs-matte ceramic wall, polished-vs-textured porcelain, etc.

Mosaics get their own handle (suffix `M`) even when sharing a colour with the field tile (e.g. Alma Light field tile = `CIFDALMALIGHT`, Alma Light Mosaic = `CIFDALMALIGHTM`).

#### Per-piece items priced without sf/piece

A handful of mosaic-adjacent items (Artico 2×2 and Hex sheets, Sena 2×2 and Hex, Park Listello, Identity Tetris Listello, Cristalli Pencil, Boemia Dots, Boemia Single Decor, Picnic/Hyde/Decor Pipa listellos) are priced as `Cost per piece` only — CIF lists no sf/piece. For these:

- Apply the same ×0.60 discount to the per-piece cost → store in `Cost/unit`
- Apply mosaic markup `Retail = Cost + $5.00`
- Treat as mosaics (`Tile format = Mosaic`, `Layout pattern = Mosaic`)
- Leave `Box size (sf)` blank — only `Pieces per box` is meaningful
- Flag in Salesperson notes: `Cost listed as per-piece on price list.`

#### Specs CIF provides / omits

**Provides:** Nominal size, Sf/piece, Cost per sf, Cost per piece, Pieces per box, Sheets per box (mosaics), Country of origin per section, finish descriptors in subsection headers (matte, polished, glossy, glazed, textured, rectified, anti-slip, wood look, etc.).

**Omits (leave blank):** Thickness, IIC/STC, certifications, warranties, traffic ratings, water-proof rating, pet-friendliness, radiant heat compatibility, COF/slip rating (except where "anti-slip R-11" or similar is explicitly stated in the subsection header — note in Salesperson notes if so), and any sub-spec not printed.

**Width (in):** Parse the first dimension from the printed size. `"12 x 24"` → 12. Fractional sizes (`"5/8 x 5/8"`) → 0.625. For irregular sizes (`"12.52 x 12.36"`) → 12.52.

**Box size (sf):** Compute as `Sf per piece × Pieces per box`. Leave blank for per-piece-only items.

#### Suitability defaults

CIF's price list does not state suitability — leave the following blank for all CIF products on first ingest, unless the subsection header explicitly says otherwise:

- `Waterproof` — blank (porcelain is inherently water-resistant but CIF doesn't certify; flag for Albert to bulk-set if desired)
- `Pet friendly` — blank
- `Radiant heat compatible` — blank
- `Traffic rating` — blank, except for products explicitly marked "anti-slip R-11" or "anti-slip porc" → note in Salesperson notes

Anti-slip designations that DO appear in CIF subsection headers and should be captured in Salesperson notes: `(anti-slip porc. R-11 exterior)`, `(anti-slip porc.)`, `(anti-slip porc. - interior/exterior)`, `(pillowed edge - non-slip)` — record the wording verbatim.

#### Stock status

Skip all clearance pages entirely. For everything else, leave `Stock status` blank. Set `Active = TRUE` for all records.

#### Promo handling

CIF's price list has no SALE or promo pricing in its regular pages. The clearance pages are out of scope. No `Promo cost ($/sf)` or `Promo end date` should ever be populated from a CIF ingest. If a future CIF list introduces promo pricing, fall back to the standard promo logic in the global rules.

#### Known soft spots

- **Inconsistent finish labelling.** Some subsections print finish in the header (e.g. `(rect. pol. porc.)` = rectified polished porcelain), others embed it in the colour name (`Glacier Hexagon Grey (polished)`), others use suffix notes (`Sena — (glossy)`). Normalize all finish wording into the `Finish type` field — common values: `Polished`, `Matte`, `Glossy`, `Glazed`, `Glazed matte`, `Glazed glossy`, `Semi-polished`, `Polished rectified`, `Matte rectified`, `Textured`, `Wood look glazed rectified`, `Brushed wood look glazed`.
- **PDF page artefacts.** Country of origin sometimes drifts across lines in the OCR (e.g. "Country of Origin:" appearing on a separate line from "Spain"). Cross-check against the section header context, don't assume the literal next line.
- **Coloured terms.** Some series use Spanish/Italian colour names (Cuero, Marfil, Crema, Bianco, Negro, Perla, Antracite) — store verbatim in Colour / tone, do not translate.
- **Decor-only listellos and pencils** with no sf/piece — see "Per-piece items" above. Easy to miss if not specifically flagged.
- **"All mosaics are 12 × 12 sheets unless stated otherwise"** — repeated as a footer on every mosaic page. Several mosaics are NOT 12×12 (Crackle Glass & Stone M1271 is on an 11-sheet box at 5/8×5/8; Marble mosaics ship at 5-sheet boxes; Identity Tetris on 13.11 × 13.11). Use the actual sheet size when printed and the count is given as `Shts per box`.
- **Mosaic-as-mosaic vs mosaic-as-decor distinction.** CIF lists some "mosaics" that are really single decorative pieces (Cristalli Pencil, Boemia Single Decor, Identity Tetris Listello). These are priced per piece, have no sf/piece, and ship in 30+ piece boxes — but they're not mosaic sheets you mortar to a wall as a unit. Set `Tile format = Mosaic` and `Layout pattern = Mosaic` per the "Per-piece items" section, flag the per-piece pricing in Salesperson notes, and accept that LS will lump them with mosaic sheets for staff filtering. Splitting them into a separate decor category isn't worth the schema complication.

#### Product name format — ALWAYS include Colour as a separate segment

**CRITICAL parsing rule.** The Airtable `Product name` field for CIF rows must follow this exact four-segment em-dash pattern, even when the colour name equals the collection name:

```
[Collection] — [Colour / tone] — [Size] ([Finish])
```

If you omit the colour segment when colour equals collection (e.g. writing `Artico — 11.5 x 23.3 — (Matte)` instead of `Artico — Artico — 11.5 x 23.3 (Matte)`), downstream parsers that grab the last em-dash-separated chunk and strip parens will return an empty string for size — breaking the Lightspeed variant import on every affected row.

**Affected CIF series where colour == collection** (always include the redundant colour segment):

| Series | Always write as |
|---|---|
| Artico | `Artico — Artico — [size] ([finish])` |
| Sena | `Sena — Sena — [size] ([finish])` |
| Pietra Dolomite | `Pietra Dolomite — Pietra Dolomite — [size] ([finish])` |
| Dolomite White | `Dolomite White — Dolomite White — [size] ([finish])` |
| Botticelli 360 | `Botticelli 360 — Botticelli 360 — [size] ([finish])` |
| Dali 360, Da Vinci 360, Goya 360 | same pattern |
| Toronto | `Toronto — Toronto — [size] ([finish])` |
| Stagone | `Soft Statuario Stagone — Stagone — [size] ([finish])` |

The four-segment shape is a hard contract with `ls-upload-instructions` — break it and the LS upload silently produces variant rows with blank Size values. The LS validator catches this on import ("Name or value for option 1 of this variant is missing"), but only after the user has tried to import and been kicked back.

#### STONE handle generation

Unlike tile rows, STONE rows (Category = `STONE`) **must have an LS Handle generated at Airtable ingest time** — the LS upload process expects every row to have a handle in alphanumeric format, and there is no automatic fallback.

**Handle format:** `CIFDSTN[ITEMTYPE][COLOUR]`

- `ITEMTYPE` token: `THRESHOLD` (for "Threshold"), `JAMB` (for "Shower Jamb"), `BENCH` (for "Bench")
- `COLOUR` token: strip non-alphanumeric from the Colour / tone value, uppercase

Examples:

| Product | Handle |
|---|---|
| Threshold — Bianco Cararra — 1.5 x 36 x 3/8 | `CIFDSTNTHRESHOLDBIANCOCARARRA` |
| Threshold — Bianco Cararra — 3 x 36 x 3/8 | `CIFDSTNTHRESHOLDBIANCOCARARRA` (same colour + same item type → same handle, different size = different variant) |
| Shower Jamb — Perlato Royal — 6 x 76 x 5/8 | `CIFDSTNJAMBPERLATOROYAL` |
| Bench — Garda — 48 x 16 x 5/8 | `CIFDSTNBENCHGARDA` |

**Variant grouping mirrors tile:** different sizes of the *same* item type + *same* colour share a handle. Different item types (Threshold vs Shower Jamb in the same colour) get different handles — they're separate products, not variants of each other.

#### Colour token in LS Handle — use the FULL alphanumeric colour, never truncate

When constructing `LS Handle / Parent ID` for a tile or mosaic row, the colour-token portion must include the **full alphanumeric value** of the row's Colour / tone. Truncating the colour token (e.g. `colour[:12]`) or reducing it to only the first word (e.g. `colour.split()[0]`) causes genuinely-different products to collapse into the same handle when their colour names share a common prefix or first word.

Concrete failures observed from earlier ingests when truncation was applied:

| Series | Colours | Bad truncation | Result |
|---|---|---|---|
| Glazed Porcelain Mosaic — Big Lantern | DL4310 Black Matte, DL4913 Black Glossy, DL1001 White Glossy, DL1005 White Matte | first 12 chars all = "BigLanternDL" | 4 products → 1 handle |
| Crackle Glass & Stone — Singer series | David, Elton, Mick | first word = "Singer" | 3 products → 1 handle |
| Marble Mosaic — Elongated Hex | Cararra, Blue Wood, Dolomite, Luna Grey | first 12 chars all = "ElongatedHex" | 4 products → 1 handle |
| Porcelain Planks — Albion (Dorset) | Black, White | first 12 chars = "AlbionDorset" exactly | 2 products → 1 handle |
| Marble Mosaic — Chevron Carrara | "Chevron Carrara polished" vs "Chevron Carrara/Oriental Wht polished" | first 12 = "ChevronCarra" | 2 products → 1 handle |

LS rejects the second-and-later rows of every collided handle with *"Handle already exists"* during the import, because the rows have identical handles but different Names — LS interprets this as conflicting parent products. The first row of each collision creates a junk single-variant product; subsequent rows fail.

**The rule:** `colour_token = re.sub(r"[^A-Za-z0-9]", "", colour_value).upper()` — strip non-alphanumeric, uppercase, take the **whole thing**. Verbose handles like `CIFDGPMBIGLANTERNDL4913BLACKGLOSSY` (33 chars) are fine; LS has no practical handle-length limit and human-readability is not the goal — uniqueness is.

If you encounter an Airtable export with truncated colour tokens, the fix is a one-time handle-rewrite update (regenerate handles using the full colour token, push the update back to Airtable). The LS upload build script does this automatically as a defensive pass and emits a separate Airtable update file when collisions are detected.

#### Colour / tone spelling — must be exactly consistent within a variant group

Two rows that should be in the same variant group must have *byte-identical* Colour / tone values. Case differences ("Grafite Grey" vs "Grafite grey") and whitespace drift count as different spellings to the LS Name builder, which uses Colour / tone verbatim. The handle is uppercased so the collision detector won't flag this case as a separate-products issue, but the LS Name builder will produce different names across the group → LS rejects.

The LS upload build script catches this and normalizes the colour spelling to the most-common form within each handle group, emitting the change in the Airtable update file. The proper fix is to repair the typo in Airtable.

#### CIF ingest output format

Produce an Excel file with all 56 schema columns. File naming: `cif_airtable_upload_[YYYY-MM-DD].xlsx` using the list's Effective date (the date printed on the Terms letter, page 3). Save to `/mnt/user-data/outputs/`.

A typical CIF ingest produces ~800 rows: ~190 mosaics, ~570 field tiles, ~50 STONE items.

---

### Olympia Tile (Zone AT)

Olympia Tile (olympiatile.com) is a large national tile and stone distributor. Their price book is the **"Zone AT" Price Book** — a 144-page PDF organized into ~21 material sections, opening with a Table of Contents (p.1), running through tile/stone/vinyl/trims/consumables, and closing with a Terms & Conditions of Sale letter (pp.143–144). The list used for ingest is `AT_ZONE_PRICING.pdf`, effective **26-January-2026** (date printed at the foot of every page).

Unlike CIF, Olympia **assigns real per-colour stock codes** (e.g. `ES.AC.WHT.0416.VR.G`, `QT.CD.ARW.0412.MT`) that uniquely identify each colour×size×finish SKU.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Olympia Tile` |
| **Brand** | `Olympia Tile` (supplier is also the brand) |
| **SKU suffix** | `OLYM` |
| **SKU field — OLYMPIA OVERRIDE** | **For Olympia only, `SKU` = the Olympia stock code verbatim** (e.g. `ES.AC.WHT.0416.VR.G`), NOT the canonical `TIL-OLYM-####` sequential format. The same stock code is also copied into `Supplier SKU`. This is a deliberate, supplier-specific deviation from the canonical SKU rule — confirmed by Albert. Stock codes are globally unique across the whole list (verified: 0 duplicates across 3,028 rows). |
| **Note on dots and commas in SKU** | Olympia stock codes contain dots (`DN.3D.BLC.1648.BR`) and, in ~109 cases, **European decimal commas** (`LW.AL.SIL.0,8X1,8.BD`). Dots are fine everywhere. **Commas are NOT** — Lightspeed permits `. - _ /` in SKUs but rejects commas, so on the LS-upload side every `,` in a SKU is converted to `.` (e.g. `LW.AL.SIL.0,8X1,8.BD` → `LW.AL.SIL.0.8X1.8.BD`). To keep Airtable and LS aligned on the SKU merge key, **apply the same comma→dot replacement to the Airtable `SKU` and `Supplier SKU` at ingest** — store the dotted form in Airtable so both systems match. Neither dots nor commas may ever appear in `LS Handle / Parent ID`, which stays alphanumeric-only (`OLYM…`). |

#### Cost column — the Zone AT discount

The Zone AT price book prints both a `$/SqFt` and a `$/Pcs.` (or `/Box`, `/Sheet`, `/Lin.Ft`, `/Set`) price on every line. **These are LIST prices, not Titan's cost.** Titan's discount off Olympia's Zone AT list is **40% then a further 6%, applied compound**:

```
Cost/unit = printed_price × 0.60 × 0.94 = printed_price × 0.564
```

Round to two decimals. Apply the 0.564 multiplier exactly once. Example: `$9.11/sf` list → `9.11 × 0.564 = $5.14/sf` cost.

Use the **`$/SqFt`** figure as `Cost/unit` for anything sold by area (tile, stone, vinyl). Use the **per-piece** figure (`$/Pcs.`, `$/Lin.Ft`, `$/Set`) as `Cost/unit` for per-piece-only items (thresholds, jambs, trims, vinyl nosing/reducer) — those have no meaningful `$/SqFt`.

#### Markup overrides — Olympia (CIF-style tiers)

Olympia breaks the standard `Retail = Cost + $1.00` rule, using the same tier structure agreed for CIF:

| Product type | Markup | Applies to |
|---|---|---|
| Field tile (porcelain, ceramic, granite, marble, limestone, quartzite, travertine, slate field tile, agglomerated slabs) | `Retail = Cost + $2.00` | `Category = Tile / Stone`, `Tile format` ≠ Mosaic |
| Mosaic (anything `Tile format = Mosaic` — glazed porcelain mosaics, mother of pearl, metal/aluminum mosaic, riverstone, sheet-format glass) | `Retail = Cost + $5.00` | `Tile format = Mosaic` |
| Ceramic Trims (bullnose, cove base, pencil, listello — the Trims section) | `Retail = Cost + $10.00` | `Product type = Moulding`, `Category = Tile / Stone` |
| SPC / LVT vinyl flooring (Chimestone, Chimewood) | `Retail = Cost + $1.00` | `Category = LVP / LVT`, `Product type = Flooring` |
| Vinyl reducer (Chimewood reducer) | `Retail = Cost + $10.00` | cross-supplier accessory markup |
| Vinyl nosing (Chimewood nosing) | `Retail = Cost + $20.00` | cross-supplier accessory markup (stair-step/riser tier) |
| STONE (marble/quartz thresholds, shower jambs, benches — `Category = STONE`) | `Retail = 0` (leave at zero) | Markup unsettled; leave `Retail price/unit = 0` and flag for Albert. Do not infer. |

#### Scope of ingest

**In scope (20 sections, ~3,028 rows):**

| TOC section | Pages | Category | Material type | Notes |
|---|---|---|---|---|
| Glazed Wall | 1–16 | Tile / Stone | Ceramic | `Tile format = Wall` |
| Glazed Vitrified & Monocottura | 17–19 | Tile / Stone | Porcelain | |
| Porcelain Coloured Base | 20–55 | Tile / Stone | Porcelain | largest section (~1,130 rows) |
| Porcelain Unglazed | 56–61 | Tile / Stone | Porcelain | |
| Quarry Tile | 62 | Tile / Stone | Porcelain | |
| Glazed Porcelain | 63–74 | Tile / Stone | Porcelain | |
| Glazed Porcelain Mosaic | 75–76 | Tile / Stone | Porcelain | `Tile format = Mosaic` |
| Glass | 77–80 | Tile / Stone | Glass | sheet-format rows → Mosaic; field glass → field tile |
| SPC Luxury Vinyl | 81–83 | LVP / LVT | SPC core | Chimestone (SPC click), Chimewood (LVT glue / SPC pad) + nosing/reducer |
| Granite | 84 | Tile / Stone | Granite | |
| Marble | 85–92 | Tile / Stone | Marble | p.93 Marble Threshold → STONE |
| Limestone | 93 | Tile / Stone | Limestone | |
| Quartzite | 94 | Tile / Stone | Quartzite | |
| Travertine | 95 | Tile / Stone | Travertine | |
| Slate | 96–97 | Tile / Stone | Slate | |
| Riverstone | 98 | Tile / Stone | Slate | mosaic-format → `Tile format = Mosaic` |
| Mother of Pearl | 99 | Tile / Stone | Mother of pearl | `Tile format = Mosaic` |
| Agglomerated | 100–101 | Tile / Stone | Quartz | Aspen Quartz / Agglomerated Marble slabs; shower jambs + thresholds → STONE |
| Metal | 102 | Tile / Stone | Stainless steel | Aluminum Mosaic → `Tile format = Mosaic` |
| Trims | 103–110 | Tile / Stone | Ceramic | `Product type = Moulding`; sub-collections (Colour & Dimension, Quebec, Ontario, Reeds, Spectra, etc.) |

**Out of scope (skip entirely — confirmed by Albert):**
- **Installation & Accessory** (pp.111–135) — thinset, grout, adhesives, blades, trowels, sponges, suction cups. Jobsite consumables.
- **Bathroom Fixtures** (p.136) — towel bars, soap dishes, paper holders (Vitros-Gilmer).
- **Resilient Flooring / QL Moulding / Johnsonite** (pp.137–142) — metal nosings, cove base, rubber/vinyl base by linear foot, adhesives.

These three sections may be ingested later as a separate accessory pass if needed; they are not flooring products Bert recommends or prices for customers.

#### Variant grouping / LS Handle

Group by **collection + colour + finish**. All sizes of the same colour+finish share one handle; sizes are variants under it. Different finishes of the same colour get different handles.

```
LS Handle = "OLYM" + alnum(Collection) + alnum(Colour) + alnum(Finish)
```

`alnum(x) = re.sub(r"[^A-Za-z0-9]", "", x).upper()` — full value, never truncated (same rule as CIF; truncation causes handle collisions).

#### Category / Material type / Tile format mapping rules

- **Vinyl special-casing (SPC section):** Chimestone = `LVP` + `SPC core` + Click/Float; Chimewood "Glued Down" = `LVT` + `SPC core` + Glue down; Chimewood "pad" = `LVP` + `SPC core`. Set `Waterproof = TRUE` for all vinyl flooring. Nosing/Reducer rows → `Product type = Moulding`.
- **STONE special-casing:** any row whose collection/colour contains "Threshold", "Shower Jamb", "Bench", or "Caddy" (in Marble p.93 and Agglomerated pp.100–101) → `Category = STONE`, `Product type = Flooring`, `Retail = 0` (flag). Material = `Marble` or `Quartz`.
- **Mosaic detection:** sections Glazed Porcelain Mosaic, Mother of Pearl, Metal, Riverstone are all-mosaic → `Tile format = Mosaic`, `Layout pattern = Mosaic`, mosaic markup. In the Glass section, sheet-priced small-format rows are mosaics; large field glass is field tile.

#### Specs Olympia provides / omits

**Provides:** Nominal size (in + cm), `Pcs./SqFt` (or Sheet/SqFt, PC/SqFt), `Pcs./Box`, `SqFt/Box`, `Pcs./Pallett`, `SqFt/Pallet`, per-piece weight (kg + lbs), finish (BRIGHT/GLOSS/MATTE/HONED/POLISHED/etc.), `VARIEGATION: N` shade-variation count.

**Width (in):** first dimension of the printed size (`12.13 X 23.62` → 12.13).
**Thickness (mm):** if the size has a 3rd dimension in inches, convert `× 25.4`. Many wall tiles list only 2 dims → leave thickness blank.
**Box size (sf):** use the printed `SqFt/Box`. Leave blank for per-piece-only items.

**Omits (leave blank):** IIC/STC, certifications, warranties, traffic ratings, waterproof (except vinyl, set TRUE), pet-friendly, radiant heat. Suitability fields are left blank on first ingest (same posture as CIF) for everything except vinyl.

#### Parsing quirks / known soft spots

- **`VARIEGATION: N |` precedes the column header** on the same line as `Finish Stock Code PRICE PER UNIT`. Strip it — never let it become a collection or colour value.
- **Trim sub-headers share a line with the column header** (`Quebec ... Finish Stock Code PRICE PER UNIT`). Capture the prefix as the collection.
- **SPC vinyl rows put pallet/weight metadata inline on the colour row** (not on a separate dimension line). Strip everything from `PC/Pallett:`, `SqFt/Pallet:`, `Weight:` onward out of the colour value.
- **Page footers** appear as both `pN All sales are subject…` and `pN 26-January-2026` — filter both.
- **Source typo — `THV.` prefix:** three Chimewood glue-down codes are misprinted with a leading `T` (`THV.CW.ICE.0748.GLUE`, `THV.CW.LBW.0748.GLUE`, `THV.CW.TPE.0748.GLUE`). Preserved verbatim as the SKU and flagged — confirm correct codes with Olympia rather than silently editing.
- **Colour spelling drift within a handle group:** a few rows differ only by punctuation/spacing (`LT GREY` vs `LT. GREY`, `GRY/BLUE` vs `GRY-BLUE`). The LS build script normalizes to the most-common form per handle; the proper fix is to repair the source spelling in Airtable.
- **`Decor` colour variants:** rows like "White Bowtie Decor" / "White Street Decor" are distinct SKUs at the same size/price — the decor descriptor is kept in the colour value intentionally.

#### Stock status & promo

Leave `Stock status` blank for all Olympia rows; set `Active = TRUE`. The Zone AT list has no SALE/promo pricing in its regular pages — never populate `Promo cost ($/sf)` / `Promo end date` from an Olympia ingest. If a future list adds promos, fall back to the global promo logic.

#### Olympia ingest output format

Produce an Excel file with all 56 schema columns. File naming: `olympia_full_airtable_upload_[YYYY-MM-DD].xlsx` using the list's effective date (foot of page, e.g. 2026-01-26). Save to `/mnt/user-data/outputs/`. A typical full Zone AT ingest produces ~3,000 rows across the 20 in-scope sections.


---

### Biyork (Biyork Materials Canada)

Biyork is both the supplier and the brand. Biyork Materials Canada (Markham, ON) issues an "Official Pricelist" as a multi-page PDF organized by collection, each collection on its own page with a black/coloured header bar. The list shows an `MSRP/SF` column and a `Your Price` column (the dealer cost).

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Biyork` |
| **Brand** | `Biyork` (all products) |
| **SKU supplier code** | `BIYK` — 4-char suffix |
| **Internal SKU format** | `[CAT]-BIYK-[Biyork code]` — the Biyork product code used **verbatim** as the suffix (not a sequential number). e.g. `ENG-BIYK-BYKENWA18NA`, `LVP-BIYK-BYKHYDRO7WI`, `LAM-BIYK-BYKRPTDWP12WP`. Biyork assigns a unique code to every colour, so this is the per-product unique-code pattern (see *Supplier SKU policy → When the supplier code is unique per product*). Keep the `BIYK…BYK` overlap untouched. |
| **Supplier SKU** | Always populated with the Biyork code printed on the price list, on its own (e.g. `BYKENWA18NA`). Same string as the internal SKU's suffix. |

Accessory SKUs follow the same rule: `ACC-BIYK-[Biyork code]`, Supplier SKU = the Biyork code. Nouveau wood accessories ("available in all Nouveau colours") have no per-colour code → use sequential `ACC-BIYK-0001` and leave Supplier SKU blank.

#### Cost column

Biyork prints **`MSRP/SF`** and **`Your Price`**.

- **Use `Your Price` as `Cost/unit`.**
- Put `MSRP/SF` in the `MAP price ($/sf)` reference field.
- Standard markup applies to flooring: `Retail = Cost + $1.00`.

#### Markup overrides (accessories)

Accessories are priced per piece (Biyork gives a real per-piece `Your Price`). Apply the global accessory markup standards on top of the per-piece cost:

- **T-Molding** / **T-Mould** → Cost + $10
- **Reducer** → Cost + $10
- **Stairnose** / **Overlap Stairnose** → Cost + $15
- **Vents** (Nouveau wood vents, per-piece) → Cost + $10

#### Scope of ingest

In scope: **ENG** (Nouveau lines), **LVP/LVT** (Hydrogen + Traktion), **LAM** (Riptide), and all **mouldings/accessories** (T-Mould, Reducer, Stairnose, Overlap Stairnose, Nouveau wood vents). Out of scope unless requested: **Underlayment** (p.18) and **Adhesive** (p.19) — jobsite consumables.

#### Collections (use verbatim)

Engineered hardwood (Nouveau): `Nouveau 6`, `Nouveau 6 American Oak`, `Nouveau 6 Clic`, `Nouveau 7 Prelude`, `Nouveau 7`, `Nouveau 7 Bespoke (Plank)`, `Nouveau 7 Bespoke (Herringbone)`, `Nouveau 8`.
Vinyl: `Hydrogen PRO 2mm`, `Hydrogen PRO Tile 2mm`, `Hydrogen PRO 3mm`, `Hydrogen PRO Tile 3mm`, `Hydrogen 5`, `Hydrogen 6 Plank`, `Hydrogen 6 Tile`, `Hydrogen 7`, `Hydrogen 8`, `Traktion`.
Laminate: `Riptide`.

#### Category / Material type mapping

- **All Nouveau lines** → `Engineered hardwood` + `Hardwood plywood`. Species from the line: `American Walnut`, `Hickory`, `European Oak`, `American Oak`.
- **All Hydrogen + Traktion lines** → vinyl, `Material type = SPC core`, `Waterproof = TRUE`. Plank lines → `LVP`; the tile lines (Hydrogen PRO Tile, Hydrogen 6 Tile) → `LVT` with `Tile format = Floor`.
- **Riptide** → `Laminate` + `Water-Resistant Core`, `AC4`, `Waterproof = FALSE` (antibacterial laminate).
- **Nouveau 7 Bespoke (Herringbone)** → `Layout pattern = Herringbone` (5"×30" block); the Plank variant is Standard layout.

#### Specs Biyork provides / omits

**Provides:** width, overall thickness, veneer thickness (eng), wear layer (vinyl, stated in mm — convert: 0.3mm→12 mil, 0.5mm→20, 0.55mm→22), finish (Wirebrush/Handscraped), SqFt/Carton (→ `Box size (sf)`), Carton/Pallet (→ `Boxes per skid`), locking system (Uniclic, Angle/Angle, I4F, Valinge 5G, Click), warranty, FloorScore cert.

**Suitability rules:**
- `Radiant heat compatible = TRUE` for European Oak / American Oak / American Walnut Nouveau lines and all vinyl **except Traktion loose-lay (FALSE)**. **Hickory is explicitly NOT radiant-compatible (FALSE)** — the list states "Compatible with Radiant Heat System (excluding Hickory)".
- `Pet friendly = TRUE` only when vinyl wear layer ≥ 20 mil (0.5mm). The 0.3mm/12mil lines (Hydrogen PRO 2mm, Hydrogen 5) are FALSE.
- Vinyl with attached pad → `Underpad included = TRUE`, `Underpad type = IXPE` (Hydrogen 5 "UnderTone"; Hydrogen 6/7/8 "infused IXPE"). Flag the IXPE assumption for Hydrogen 5 (list says "UnderTone" without naming the material).

**Omits (leave blank):** IIC/STC, Colour/tone, Traffic rating, Suitable rooms, Pairs well with.

#### Parsing quirks / known soft spots

- **Hydrogen 8 price inversion:** the plank `Your Price` ($6.63) **exceeds** `MSRP/SF` ($6.34), and Hydrogen 8 accessory `Your Price` equals MSRP exactly (no dealer discount). Ingest the values as-is (Cost = `Your Price`) per flag-don't-block, and tag both in `Salesperson notes` for review. Almost certainly a typo on Biyork's sheet — confirm with the rep.
- **Multi-size groups under one header:** Nouveau 7 splits Hickory into Wirebrush vs Handscraped finishes (different finish, same price). Hydrogen 6 Plank has two size groups (7"×48" box 23.64 and 7"×60" box 23.25) under one collection. Create records for every sub-group with its specific box size/finish.
- **Tile lines inside vinyl collections:** Hydrogen PRO Tile and Hydrogen 6 Tile are vinyl tile (`LVT`), not porcelain — keep `Material type = SPC core`.
- **Nouveau 6 Clic** is engineered hardwood with a Uniclic float system → `Install profile = Click`, `Locking system = Uniclic`, thickness 1/2" (12.7mm).

#### Stock status & promo

Leave `Stock status` blank for all Biyork rows; set `Active = TRUE`. The regular pricelist carries no SALE/promo pricing — never populate `Promo cost ($/sf)` / `Promo end date` from a standard Biyork ingest. If a future list adds promos, fall back to the global promo logic.

#### Biyork ingest output format

Produce an Excel file with all 56 schema columns. File naming: `biyork_full_airtable_upload_[YYYY-MM-DD].xlsx` using the list date (e.g. 2025-07-07). Save to `/mnt/user-data/outputs/`. A full flooring + accessories ingest produces ~324 rows (154 flooring, 170 mouldings/accessories).


---

### Floordi (Floordi Canada Inc)

Floordi is both the supplier and the brand. Floordi Canada Inc (Hamilton, ON) issues a "Distribution Price List" PDF covering the Canadian market, headed "effective from [date], until further notice". The table shows `Price/UoM (CAD)`, `Price/Box (CAD)`, and `Price/Pallet (CAD)` columns. First ingested from the Sep 3 2025 list (18 records: 12 vinyl + 6 accessories).

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Floordi` |
| **Brand** | `Floordi` (Avolis / AVO-ROX and Walldi are collection/line names, not brands) |
| **SKU supplier code** | `FLRD` — 4-char suffix |
| **Internal SKU format** | `[CAT]-FLRD-[Floordi code]` — the Floordi product code used **verbatim** as the suffix (per-product unique-code pattern, like Biyork). e.g. `LVP-FLRD-AVR651`, `ACC-FLRD-AT-AVR65`. |
| **Supplier SKU** | Always populated with the Floordi code on its own (e.g. `AVR651`, `AT-AVR65`). |

#### Cost column

- **Use `Price/UoM (CAD)` as `Cost/unit`** (per sqft for flooring, per piece for accessories).
- `Price/Box (CAD)` and `Price/Pallet (CAD)` are extended totals — do not map them. **`Pallet price ($/sf)` stays blank** (Floordi gives a pallet total in CAD, not a per-sf pallet rate).
- Standard markup on flooring: `Retail = Cost + $1.00`.

#### Reduced-price colours are NOT promos

Floordi highlights certain "top-selling" models in red with a cover note that increased production volumes have reduced costs, "effective from [date] until further notice". This is a **regular price reduction, not a promotion** — no end date, no SALE marking. Enter the reduced price straight into `Cost/unit`, leave `Promo cost ($/sf)` / `Promo end date` blank, and add a Salesperson note (e.g. "Sep 3 2025 list: reduced regular price (volume-production cost reduction) — not a promo"). On a future list, a change to these prices logs as `Entry type = Regular price change`.

#### Markup overrides (accessories)

Accessories are priced per piece (94.5" lengths). Global accessory markup standards:

- **T-Moulding** → Cost + $10
- **Reducer** → Cost + $10
- **Flush Stair Nose** → Cost + $15

#### Scope of ingest

In scope: **AVO-ROX vinyl** (EASE + GRAND lines) and their **accessories** (T-Moulding, Reducer, Flush Stair Nose — "available in all colors from the collection", no per-colour records).

**Out of scope: WALLDI HUSH acoustic slat wood wall panels** (WA-prefixed codes). These are wall products with no matching category in the schema — skipped per Albert's decision (2026-07-18). Revisit only if a wall-panel category is created.

#### Collections (use verbatim)

`AVO-ROX EASE` (6.5mm, 48" x 7 3/16", 20 mil, box 19.12 sf, 55 box/pallet, 8 pcs/box) and `AVO-ROX GRAND` (8mm, 61" x 9", 20 mil, box 18.75 sf, 40 box/pallet, 5 pcs/box).

#### Category / Material type mapping

- All AVO-ROX lines → `Category = LVP`, `Material type = SPC core`. **The list does not state the core — SPC was confirmed by Albert (2026-07-18).** If a future Floordi line looks different (e.g. flexible/glue-down), re-confirm.
- `Waterproof = TRUE` (SPC vinyl, global rule). `Pet friendly = TRUE` (20 mil ≥ 20 mil, global rule). `Radiant heat compatible` = blank (not stated).
- Width: EASE 7 3/16" → `7.19`; GRAND → `9`.

#### Product naming convention

- Flooring: `Floordi [thickness]mm [Collection] [width]" — [Colour]` (e.g. `Floordi 6.5mm AVO-ROX EASE 7.19" — Serene Oak`)
- Accessories: `Floordi [Collection] [Type] [thickness]` (e.g. `Floordi AVO-ROX EASE T-Moulding 7mm`)

#### LS handles (assigned at ingest)

Brand-first, all uppercase alphanumeric: `FLRD65[COLOUR]` for EASE (6.5mm), `FLRD8[COLOUR]` for GRAND (8mm) — colour with non-alphanumerics stripped (e.g. `FLRD65SERENEOAK`, `FLRD8AMBERGLOW`). Accessories: `FLRD` + Floordi code with hyphens stripped (e.g. `FLRDATAVR65`). No grades exist → every handle is unique per product; no variant groups.

#### Specs Floordi provides / omits

**Provides:** dimensions (L x W x T), wear layer (in product name, "20mil"), UoM, pcs/box, sf/box, box/pallet.

**Omits (leave blank):** warranty, install profile/method, locking system, underpad, certifications, colour/tone, IIC/STC, traffic rating, species. Spec coverage is thin — request a full spec sheet from the Floordi rep if these matter for Bert lookups.

#### Stock status & promo

Leave `Stock status` blank; `Active = TRUE`. The regular distribution list carries no SALE/promo items (red highlights are regular reductions — see above). Prices exclude GST/HST, delivery, installation; may vary by province.

Floordi issues **separate monthly promotion sheets** (e.g. "JUNE PROMOTION") listing promo `Price/sqft` per model with a printed run window (e.g. 01/06/2026–30/06/2026). Apply the global promo flow: `Promo cost ($/sf)` = the promo price, `Promo end date` = the printed end date, or per the global month-end default if none/extended. Match models by the AVR code in `Supplier SKU`. Promo sheets may include WALLDI tiered volume discounts (5–20% off by box count) — out of scope (WALLDI not in catalogue; tiered volume discounts don't map to a flat promo cost). First applied: June 2026 promo (5 AVO-ROX colours), confirmed ongoing into July, end date rolled to 2026-07-31.

#### Floordi ingest output format

`floordi_full_airtable_upload_[YYYY-MM-DD].xlsx` using the "Last updated" date on the list (e.g. 2025-09-03), all 56 schema columns, saved to `/mnt/user-data/outputs/`. Record the effective date in `Price list reference` when logging future price changes to Price History Log v2.

---

### New supplier onboarding — checklist

When a new supplier is added, gather this information before processing their first price list, and add a subsection above following the FAW template:

1. **Supplier name** (exact string for Airtable single-select)
2. **Brand(s)** — is the supplier also the brand, or do they distribute multiple brands?
3. **4-char SKU suffix** (e.g. FAWK, VIDR, GRAN)
4. **Which of the three cost columns to use** (pallet / box / list / MSRP — varies by supplier)
5. **Does the supplier assign product codes?** If yes, populate Supplier SKU. If no, leave blank.
6. **Categories in scope** (ENG, LVP, LVT, HWD, LAM, TIL, CAR, ACC)
7. **Markup overrides** — any category where `Retail = Cost + $1` doesn't apply (e.g. stair products, accessories, clearance)
8. **Which schema fields the supplier omits** (wear layer, veneer, grade, warranty, certifications, radiant heat compatibility)
9. **Collection naming convention** — which line names to use verbatim
10. **Material type defaults** — what to infer from section headers when not stated
11. **SALE/promo marking convention** — how the supplier flags promos (yellow highlight, "SALE" text, separate promo sheet)
12. **Parsing quirks** — multi-size groups under one header, colourway duplicates across collections, per-piece vs per-sf pricing, Coming Soon treatment

---

## Document maintenance

This document should be updated whenever the schema changes or a new supplier is onboarded. If a field is added, removed, or its purpose changes, update this guide at the same time.

Schema changes should also be reflected in the Bert — Pricing & Promo SOP in Notion. New supplier subsections should be added under Supplier Ingest Rules following the structure of the FAW entry.

### Verifying this document against the live base

The live schema can be exported to a review workbook — every field, type,
description, and select option, plus a Review Flags sheet:

```
python3 scripts/bert_schema_export.py --names names.json --config config.json \
    --out analysis/output/bert-airtable-schema-YYYY-MM-DD.xlsx
```

`names.json` / `config.json` are the raw payloads from the Airtable MCP calls
`list_tables_for_base` and `get_table_schema` — neither is sufficient alone (the
first has names and descriptions but no select options; the second has options but
no names). Latest snapshot committed alongside the workbook in `analysis/output/`.

### Changelog

- **2026-09-01** — Added "Updating existing products from a price list", after the
  GreenTouch 2026-09-01 run surfaced that the extraction step renumbers internal
  SKUs per run and would have duplicated all 83 existing records. Two rules
  (Albert): a price list for a supplier **not** already in the catalogue never
  creates records through the API — it produces the Bert schema Excel export for
  human-reviewed import instead; and matching for an existing supplier cascades
  **internal SKU → Supplier SKU (partial/fuzzy) → specifications**, against the SKU
  as stored in Airtable, never one regenerated during the run. (An earlier draft of
  this section said "match on Supplier SKU, never the SKU column" — wrong as a
  general rule: it breaks the Biyork/Triforest/Olympia pattern where the supplier
  code *is* the internal SKU suffix and tier 1 is the most precise key available.)
  Same section adds the per-system name-casing table, the batch caps, the
  `Low stock` mapping for supplier "Limited" markers, and clarifies `Changed by` =
  `Cowork` for unattended runs (a scheduled Claude routine is automated, not
  `Manual`). Added the schema-export instructions above. Verified against a live
  schema snapshot the same day: Price History Log v2 documentation was already
  accurate; no field-level drift found.