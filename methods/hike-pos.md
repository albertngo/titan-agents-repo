# HikePOS — product import schema and the update method

Albert, 2026-10-07: "This is another POS input schema (HikePOS)… update it to reflect the new
Airtable data… If the product is existing, do not change the SKU, as this would add a product.
But update the details. When adding NEW products and new skus, you can use the Airtable SKU and
details. Please learn the schema as well for future products I want to put into HikePOS."

Script `scripts/hike_update.py` · registry `platform-settings/hike.json` · command
`/hike-update` · tests `tests/test_hike_update.py`. Read-only against every platform: it edits
the Hike export file and writes a report, and a person imports the file into Hike.

## How Hike identifies a product

**Hike has no product id. The SKU is the identity.** An import row whose SKU already exists
updates that product; any other row creates a new one. Hike's own help (*How to Bulk Edit
Product Information in Hike*) adds a second trap: *"Do not edit anything relating to your SKU or
Product Name, as this will create a new product entry once you import it back into Hike."*

So on an existing row, **Name, SKU and Barcode are never changed**, even when the name carries a
stale box size or a typo (`Bemuda`, `Russel Hill`, `(Thomas)`). Those are reported, not fixed;
a rename is done by hand in Hike's product screen, one product at a time.

Import: Hike → Products → IMPORT → upload the file. Hike accepts its own `.xlsx` export
back, which is the safest round trip; it validates headings and mandatory fields and lists
row errors on screen before committing. Hike's help site is behind the cloud environment's
egress block, so these rules come from its search-indexed help text plus the 2026-10-07
export itself.

## The columns (61, from the 2026-10-07 export)

Booleans are the text `TRUE` / `FALSE`. Per-outlet columns are prefixed with the outlet name
(`Flooring Store_…`; one outlet today).

| Column | Meaning | Titan practice |
|---|---|---|
| `Name` | Display name, also an identity per Hike's help | Existing: never touched. New: `(C) FAW{ENG,HAR,LAM,VIN} - NAF - <Lightspeed descriptor> \| #<SKU> \|  - <specs>` |
| `Description` | Free text | `<price date> - <spec> - <install note> / Promotion: $ / <cost+0.70>=70c` (see below) |
| `SKU` | **The identity** | Existing: never touched. New: the Airtable SKU (`ENG-FAWK-0010`) |
| `Barcode` | Scan code | Equals SKU on every row; same rule as SKU |
| `Product type` | Category | `ENGINEERED` / `HARDWOOD` / `LAMINATE` / `VINYL` (+ `MOULDING`, `STAIR SET`) |
| `Product tag` | `;`-separated tags | `Flooring;C` |
| `Brand name`, `Season name` | — | blank |
| `Supplier code`, `Sales code`, `Purchase code` | — | blank |
| `Supplier name` | Supplier | `FAW` |
| `Loyalty`, `Depth`, `Width`, `Height`, `Weight` | numbers | `0` |
| `Visible eCommerce`, `Enable SEO` | flags | `FALSE` |
| `Specification`, `Meta title/description/keywords` | — | blank |
| `Slug` | Hike-generated URL slug | never written |
| `Track inventory` | Stock tracking on | `FALSE` on most rows; a few quick-entry rows are `TRUE` and hold real stock |
| `Allow out of stock` | Sell below zero | `TRUE` |
| `Is variant product` + `Variant option name/value one..three` | Variants | not used (`FALSE`) |
| `Same retail price for all outlets` | One price | `TRUE` |
| `Image URL` | Hike-hosted image | never written (Airtable attachment URLs expire) |
| `Active` | Sellable | follows Airtable `Active` on the primary row only |
| `Custom field`, `Handle`, `Age verification limit` | — | blank |
| `Enable Serial Number`, `Component part…`, `Exclude from all discount`, `Exclude additional loyalty`, `Age verification needed…`, `Enable unit of measure`, `Is composite product`, `Exclude from reorder` | flags | `FALSE` |
| `Composite product1/2_SKU`, `…_Quantity` | Composite parts | not used |
| `<outlet>_Tax` | Tax rule | `Default Tax` |
| `<outlet>_Cost price` | What the store pays | Airtable cost (lowest of Cost/unit, an active promo, an active rep rate) |
| `<outlet>_Retail price` | Shelf price | **cost + $1.40** for flooring (Albert, 2026-10-07: Hike keeps its own markup, not Airtable's +$1.00); an accessory keeps its existing markup |
| `<outlet>_Price Excluding Tax` | Same as retail | kept equal to retail |
| `<outlet>_Average Cost Price` | Hike's running average | never written on existing rows |
| `<outlet>_Stock`, `_Stock on hand` | Hike's stock counts | never written on existing rows (`0` on new) |
| `<outlet>_Reorder level`, `_Reorder value` | Reorder | never written |
| `<outlet>_Outlet visibility` | Shown in outlet | `TRUE` |

**Stock is carried as exported.** Import soon after exporting. A sale made between the export
and the import would be undone by re-importing the older count; if days pass, re-export and
re-run.

## The `=70c` promo floor

Every flooring description ends `Promotion: $ / N=70c`, and on all 199 flooring rows checked
`N = cost + 0.70`: the lowest promo price that still leaves 70¢ a sq ft. When cost moves, N
moves with it, but only where the old N was old cost + 0.70. Mouldings and stair sets carry a
different N (`30=70c` on an $18 T-moulding) and are left alone. The leading date is the price
date and becomes Airtable's `Effective Date`.

## Matching an existing Hike row to Airtable

Hike names follow `(C) FAW<CAT> - … (<Colour>) <Click|T&G> | #<code> |  - <W> x … - <box>sf/b`.
A row matches an Airtable record when:

1. same category (`FAWENG`→ENG, `FAWHAR`→HWD, `FAWLAM`→LAM, `FAWVIN`→LVP/LVT);
2. same colour, normalised (case, punctuation); spelling drift is in the registry's
   `colour_aliases`, never fuzzy-matched (`Dorchester` must not become `Rochester`);
3. nothing contradicts it: the species code in the FAW SKU (`FAW.E.H.` hickory, `.M.` maple,
   `.W.` walnut, `.O.` oak), plank vs tile, width within 0.5" (a 5" product never takes the
   6.5" price);
4. two Airtable records left (Windsor, Westminster, Beijing…) → the nearer box size wins.

Rows whose names do not follow the pattern (quick entries with numeric SKUs like `100332`
"FAWENG - GOLDEN - Click") are read by eye once and recorded in `manual_matches`.

**Hike carries duplicates.** Several Hike rows can be one Airtable product (old and new
packaging, a quick entry beside the structured row). All of them get the new cost and price,
because staff may sell from any of them; only the **primary** row (active, matching box size,
a structured `FAW.` SKU) has `Active` set from Airtable. The report lists every duplicate so
they can be merged or deactivated in Hike by hand.

**Hike-only rows are left exactly as exported** (Albert, 2026-10-07): colours FAW no longer
lists, mouldings, stair sets, the MDF baseboard. They appear in the report as `hike_only`.

## New products

An active Airtable record with no Hike row is appended with the Airtable SKU as `SKU` and
`Barcode`, the name built from its Lightspeed name (minus any `(P …)`/`(R …)` price marker),
cost + $1.40, the description borrowed from a Hike sibling in the same collection (install
notes are collection-level) with the date and floor recomputed. Never added: inactive or
Discontinued records, and the oak stair treads/risers Titan does not carry.

## Run it

```
/hike-update FAW
```

or by hand, after saving the Hike export and pulling the supplier's Airtable records:

```
python3 scripts/hike_update.py --supplier FAW \
  --hike-export ingest/<date>/hike_faw_export_<date>.xlsx \
  --airtable-snapshot ingest/<date>/faw_airtable_snapshot.json \
  --ls-snapshot ingest/<latest>/lightspeed-products.json \
  --out ingest/<date>/hike_faw_products_<date>.xlsx \
  --report ingest/<date>/hike_faw_report_<date>.csv
```

A second supplier needs its own block under `suppliers` in `platform-settings/hike.json`
(Airtable choice id, Hike supplier name, markup, name tokens, aliases).

## Log

- **2026-10-07** — First run, FAW, 417 Hike rows / 241 Airtable records. 192 Hike rows
  matched to 170 Airtable products (20 products have 2-3 Hike rows); 60 new products added;
  225 Hike-only rows left as exported; 9 oak treads and 2 inactive records not added. Albert
  chose Hike's +$1.40 over Airtable's +$1.00, and to leave Hike-only rows alone. Three rows
  go from inactive to active because Airtable carries them: Antique Birch, Cosmic, Jasmine.
