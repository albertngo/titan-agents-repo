---
name: bert-airtable-schema
description: "The master reference for Titan Flooring's Airtable database schema — covering every field in the Master Flooring Catalogue and Price History Log tables. Use this skill whenever working with Titan's product data, including: entering or importing products into Airtable, processing supplier price lists (extracting pricing, handling SALE items, applying promo cost logic, assigning stock status), generating Airtable-ready spreadsheets or CSVs, building Lightspeed upload files, answering questions about field meanings or data entry rules, creating or updating product records, validating data against the schema, debugging Cowork automation issues, or any task involving SKUs, pricing markup rules, promo flows, or the Master Flooring Catalogue structure. Also trigger when the user mentions Bert, Cowork, Lightspeed import, supplier price lists, flooring product data, Floors At Work, FAW, or Airtable fields by name."
---

# Bert — Airtable Schema Guide

Master Flooring Catalogue + Price History Log | Titan Flooring Inc. | Internal Use Only

> ### ⚠️ Two formatting rules that protect the prices in this file — do not "tidy" them
>
> **1. This is a reference document. Never invoke it with arguments.** To process a
> price list, use **`/process-price-list <notionID>`**, which loads this file as a
> reference.
>
> **2. Single-digit dollar amounts are written `$ 1.00`, with a space.** That space is
> load-bearing. A dollar sign immediately followed by a single digit (1 through 9) is a
> slash-command **positional-argument token**: invoke this file with an argument and
> every such price is silently rewritten to that argument, keeping only the decimals.
> On 2026-09-03 a `/bert-airtable-schema <url>` invocation turned the global markup
> rule into `Retail = Cost + https://…notion.so/….00`, in all 45 places it appears,
> plus 28 more single-digit prices. Nothing errors; the document just states wrong
> prices. (This note deliberately never writes the token itself, so the warning
> survives the very substitution it describes.)
>
> Multi-digit amounts (`$20`, `$15.00`) are safe and stay tight — the mismatch is
> deliberate. Closing the gap in `$ 1.00` reintroduces the bug.

## Purpose

This guide explains every field in the Bert Airtable base — what it is, how to fill it in, and why it matters. It is the reference document for anyone entering products, updating pricing, or building automation on top of this data.

The base has two tables: **Master Flooring Catalogue** (the product database) and **Price History Log** (the append-only pricing audit trail).

---

## How the base works

### RULE 0 — the Airtable SKU is immutable and is the source of truth

**This rule overrides everything else in this document, every supplier subsection,
every method file, and every routine. There is no exception and no supplier-specific
override.**

1. **Once a record exists in the Master Flooring Catalogue, its `SKU`
   (`fldx3byCOht5HbKmH`) never changes.** Not renamed, not re-cased, not re-numbered,
   not re-formatted, not "tidied", not migrated to a newer convention, not corrected
   for a typo. A SKU is created exactly once and is then permanent for the life of the
   record.
2. **The Airtable SKU is the single source of truth.** Lightspeed, Notion, Make,
   every export, every upload file and every downstream system **matches to it**.
   Nothing matches the other way. If Airtable and another system disagree about a
   SKU, **Airtable is right by definition** and the other system is what gets fixed.
3. **No automated process may ever write the `SKU` field on an existing record.**
   Upserts merge *on* SKU (`fieldIdsToMergeOn: ['fldx3byCOht5HbKmH']`); SKU is never
   itself in the payload of fields being updated. An update that would change a SKU is
   a bug — stop the batch and escalate, do not "fix" it.
4. **A newly generated SKU is valid only for a product that genuinely does not exist
   yet**, and only after the matching cascade has failed to find it. Extraction
   renumbers per run, so a generated SKU is never evidence that a product is new — it
   is a value awaiting confirmation.
5. **A SKU that looks wrong is escalated, never edited.** Changing one orphans the
   Lightspeed record, every Price History Log v2 row, and any relation pointing at it.
   If a legacy or malformed SKU genuinely has to change, that is a deliberate,
   human-approved migration that updates every dependent system together — never an
   in-place edit, and never something a routine does on its own.

Legacy prefixes that predate the current format (e.g. Grandeur's `SPC-`/`WPC-` vinyl,
Olympia's dotted stock codes) are **correct by virtue of existing**. Match against
them as they are stored. Apply current formatting rules only when minting a SKU for a
genuinely new product.

### RULE 0a — the three identity fields and where each one is born

`SKU`, `LS Handle / Parent ID` and `Lightspeed ID` are **all three source-of-truth on
Airtable**. They differ only in *who creates them and when*, and confusing that is
what produces duplicates.

| Field | Created by | Created when | On a new product |
|---|---|---|---|
| `SKU` | **Titan** | Record creation | Minted from the price list. Permanent from that moment (RULE 0). |
| `LS Handle / Parent ID` | **Titan** | Record creation | **We mint it ourselves** using the handle-generating schema (`[HANDLE_PREFIX][SizePrefix][SpeciesAbbrev][COLOUR]`, alphanumeric only). It is uploaded to Lightspeed, and Lightspeed adopts it. |
| `Lightspeed ID` | **Lightspeed** | On import into LS | **Blank — and correctly blank.** LS generates the UUID. It must then be **reverse-populated back into Airtable**. |

**The asymmetry that matters:** a handle is ours to create and push *out* to
Lightspeed. An LS ID can only come back *in* from Lightspeed. So a new product is
uploaded with a handle and no id; LS assigns the id; that id is written back to
Airtable.

`SKU` remains the matching factor throughout — it is what ties an Airtable record to
its Lightspeed product in both directions, and it is how the returning UUID finds its
home.

#### Closing the loop is mandatory — but it is batched, not per-run

The generated `Lightspeed ID`s must come back into Airtable. **The cadence is Albert's
choice and is deliberately batched** (decided 2026-09-03): one LS product export can
cover many price lists at once, so the backfill runs periodically rather than after
every list. Use the `ls-id-backfill` skill — export the products from LS, match on
`SKU`, write the UUIDs back.

Because the backfill lags the runs that created the products, **the outstanding work
is tracked on the Notion Price Lists row**, not in anyone's head:

| Property | Set by | Meaning |
|---|---|---|
| `New Products` (number) | the price list run | how many new SKUs it minted — `0` when none |
| `Airtable Sync` (select) | run, then importer | `Pending` = Airtable does not yet mirror the attached file · `Done` = it does · `Not needed` = reviewed, deliberately not imported |
| `LS Upload` (select) | whoever uploads to Lightspeed | `Pending` = the LS file has not been pushed to the POS yet · `Done` = it has · `Not needed` = no LS file for this run |
| `UUID Backfill` (select) | run, then backfill | `Pending` = new products awaiting UUIDs · `Done` = backfilled · `Not needed` = the run created none |

A run leaves `Airtable Sync = Pending` always, and `UUID Backfill = Pending` whenever it
minted ≥1 new product (`Not needed` otherwise). **A run never writes `Done`, and never
touches `LS Upload`** — the person or agent that performs the import, the upload or the
backfill does.

**The order is forced:** `Airtable Sync: Done` → `LS Upload: Done` → `UUID Backfill: Done`. A new
product has no Lightspeed ID until the POS upload creates one, so nothing can be
back-filled before `LS Upload` is `Done`. The actionable backfill set is therefore
`UUID Backfill is Pending` **and** `LS Upload: Done` — a `Pending` row with `LS Upload` not yet `Done`
is waiting to be uploaded, not waiting for you to backfill it.

#### Resolving a duplicate-record collision — the tie-break rule

**Ruling (Albert, 2026-09-10):** when two Airtable records appear to describe the same
product and a backfill or matching pass can't tell which one is live, **the record that
already carries both a `SKU` and a `Lightspeed ID` is the correct one.** A record missing
either — most often a broken record with a blank `SKU` — is the duplicate, not a second
real product, and gets deleted once the correct sibling is confirmed. Applied 2026-09-10
to a broken null-SKU Biyork record (`reciBkT8xnBBshiZr`) colliding with the properly-SKU'd
`ENG-BIYK-BYKN5AOEM`, which already held the right Lightspeed ID from a prior upload — the
broken record was deleted. This is a tie-break for an already-ambiguous collision, not
permission to delete a record just because a match failed; RULE 0's "escalate, don't
guess" still governs every case that isn't this clean-cut.

`New Products` is the check on the backfill: it says how many UUIDs that row should
have produced, so a short count is visible rather than silent.

#### Property names on the Price Lists row — renamed 2026-09-03

**These were renamed in Notion and a run using the old names fails outright** — a
`update-page` call with an unknown property returns `400 validation_error` and writes
nothing, so the whole state update is lost, not just that field. Verified against the
live data source on 2026-09-03:

| Old | Current | Type |
|---|---|---|
| `LS Backfill` | **`UUID Backfill`** | select — `Pending` / `Done` / `Not needed` |
| `POS` (checkbox) | **`LS Upload`** | select — `Pending` / `Done` / `Not needed` |
| `Status` | **`Extraction Status`** — write this key, not `Status` | status — `Not started` / `Extracting` / `Extracted [Needs Review]` / `Extracted [Ready to Upload]` / `Extracted [Error]` / `Extracted [All Uploaded]` / `Not Needed` |
| `Wordpress` | **removed** | — |

Two things worth knowing:

- **`LS Upload` is a select now, not a checkbox.** "Check `POS`" became
  "set `LS Upload = Done`", and `Not needed` is a real third state — a promo run that
  produces no LS file should say so rather than sit at `Pending` forever.
- **The status property's key IS `Extraction Status`, and so are its option names.**
  Corrected 2026-09-09: an earlier note here said page updates took the key `Status` and
  listed options (`Extracted [Pending Review]`, `Error: Needs attention`, a bare `Done`)
  that **do not exist on the live data source**. Writing an option a status property does
  not have is rejected, and the whole `update_properties` call fails with it. The live
  option set, read off `collection://e2dc37bc-63da-42e9-b6c0-63ff48d72e6b` and written
  successfully the same day. Confirmed from the other direction too — writing the key
  `Status` returns `400 validation_error`: *"Property \"Status\" not found in the data
  source"*, followed by the full list of editable keys. That error message is the fastest
  way to re-derive this table if it ever drifts again:

  | Option | Who sets it |
  |---|---|
  | `Not started` | the row's default before a run |
  | `Extracting` | in-flight only — **never the state a run ends in** |
  | `Extracted [Needs Review]` | **the run**, when files are attached |
  | `Extracted [Ready to Upload]` | the reviewer, once the file is cleared for import |
  | `Extracted [Error]` | **the run**, when it could not finish |
  | `Extracted [All Uploaded]` | whoever closes out the imports |
  | `Not Needed` | a human, for a row that will never be extracted |

  **A run only ever writes `Extracted [Needs Review]` or `Extracted [Error]`.** The three
  downstream states belong to the person doing the import, the same way `Airtable Sync`,
  `LS Upload` and `UUID Backfill` never receive `Done` from a run.

#### `Notes` — the row's own flag line (Albert, 2026-09-03)

**Every run writes `Notes` when it has something the reviewer must know, and leaves it
empty when it does not.** An empty `Notes` is a real signal — "this run found nothing
worth stopping for" — so never fill it with a summary of what went right.

It exists because the other escalation paths are all *off* the row: a Tactical Task, a
push notification, a chat report. None of them are visible to someone scanning the Price
Lists database, which is where the decision to import actually gets made. `Notes` is the
row-local pointer; it does not replace the task or the push for anything actionable.

**What earns a line, in priority order:**

1. **Anything that blocks or invalidates the import** — a cost basis assumed rather than
   confirmed, a placeholder price, a schema field the base does not have yet.
2. **An assumption a human must verify** — specs copied from a sibling record, a core
   type inferred, a supplier typo corrected.
3. **A conflict with stored data** — a collection or spec that disagrees with the
   catalogue, especially where an immutable field (handle, SKU) encodes the old value.

**What does not:** row counts, match rates, "no price changes", or anything already
visible in `New Products` and the three trackers.

**Format.** Terse, one line per issue, most severe first, each naming the affected rows
or SKUs so it can be acted on without opening the file. Lead with the run date, because
a re-run overwrites this field and a stale note is worse than none:

```
2026-09-03: 12 rows have Cost/unit set to the PROMO price as a placeholder
(no regular cost known) — verify with Vidar before import. SKUs ENG-VIDR-0193…0204.
```

**Overwrite, don't append.** It describes the current state of the row, not its history —
the repo commits and `Salesperson notes` carry the history.

#### `Extracted [Error]` — the status that pairs with `Notes`

**Added on Albert's instruction 2026-09-03; renamed to the live option name 2026-09-09.**
A run that cannot finish sets **`Extraction Status = Extracted [Error]`** and puts the
reason in **`Notes`**. The two always travel together: the status makes the row findable
in a view, `Notes` says what happened.

| Outcome | `Extraction Status` | `Notes` |
|---|---|---|
| Ran, files attached, nothing blocking | `Extracted [Needs Review]` | empty |
| Ran, files attached, caveats a reviewer must clear | `Extracted [Needs Review]` | the flag lines |
| **Could not finish** | **`Extracted [Error]`** | **what failed, at which step, and what it needs** |

Both completed-run outcomes are `Extracted [Needs Review]`; only `Notes` distinguishes
them, and neither is ever `Extracted [Ready to Upload]` — that is the reviewer's to set
once the file is cleared for import.

`Extracted [Error]` is for a run that did not produce what it was meant to:
the download failed, the file is not a parseable price document, `Company` or `Tags`
could not be determined, the attachment upload failed, a write was rejected. It is
**not** for a completed run carrying assumptions — that is
`Extracted [Needs Review]` with a populated `Notes`.

This replaces the older "leave the status at `Extracting` and say why" rule, which left a
failed run indistinguishable from one still in flight. **A row must never sit at
`Extracting` after a run ends.**

The error note names the step, so it can be resumed rather than re-run blind:

```
2026-09-03: FAILED at step 2 — SharePoint returned 403 on the share link
(cookie jar set, ?download=1 present). No file retrieved, nothing extracted.
Re-share the file or check the link has not expired.
```

Escalating still applies on top: the Tactical Task and the push are what reach a human
who is not looking at the database.

**Read the data source schema when a write fails rather than guessing the new name.**
The 400's message lists every editable key, which is how these were found.

**`Airtable Sync = Done` is a claim about agreement, not a completed step:** it means
Airtable *currently* mirrors the file attached to that row. Edit the file and re-attach
it and the row returns to `Pending` — a corrected file is a new pending change, and
leaving it `Done` is how the base drifts from what the row claims. `Extraction Status = Extracted [All Uploaded]` only
once both trackers read `Done` or `Not needed`.

Until a row reaches `Done` its products are incomplete, and the failure is delayed and
silent: a later run reads a blank `Lightspeed ID`, ships an LS file with a blank `id`
for a product that now exists in LS, and **duplicates it**. A new product is not
finished when it is uploaded — it is finished when its id is back in Airtable. Batching
changes *when* that happens, never *whether*.

#### Once populated, they are authoritative

**Once a record carries a `Lightspeed ID` and a handle, Airtable is the source of
truth for them and no automated process overwrites either.** Not a regenerated handle,
not an id from a stale export, not a "corrected" value.

They may be replaced only on an **explicit instruction from Albert to swap in a
specific matching set of data** — a deliberate, named operation, never a routine's own
judgement and never a side effect of a price list run.

### Three layers of data

Every product record in the Master Flooring Catalogue serves three consumers simultaneously:

- **Bert** (the AI tool) — reads product specs, pricing, and suitability fields to answer customer and staff queries
- **Cowork** (the automation agent) — reads Supplier SKU to match incoming price lists, writes to pricing fields, and logs changes to the Price History Log
- **Lightspeed** (the POS system) — receives product data via import; Lightspeed ID and LS Handle / Parent ID are populated after upload

### Pricing rule

All products follow a single flat markup:

**Retail price/unit = Cost/unit + $ 1.00**

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

**Rule (Albert, 2026-09-08): always check the live Airtable for matching products before
deciding a promo/price-list item is "new" — for every list, not just when something looks
ambiguous.** A promo sheet routinely lists only colour + grade + price, with no box size,
thickness, or veneer — that is a gap in the *document*, not proof the product is absent
from the catalogue. The Vidar Sept 2026 promo run first marked 12 grade/colour combos as
new-with-unknown-specs; checking the live base found that 8 of them had the same
colour+width+species (and veneer, where the sheet differentiates by veneer thickness) as
an existing record at a *different* grade, or the width+species collection was uniform
enough across every other colour to use as a default. Only 4 were genuinely absent from
the catalogue at any grade or veneer.

**Match cascade before creating anything new**, in order:

1. **Exact colour + width + species + grade already exists** → this isn't new at all,
   it's a tier-3 match (see the matching cascade above) that the initial pass missed.
   Route it through the normal matched-row path, not creation.
2. **Same colour + width + species, matching veneer where the sheet states one** (a
   sheet that prints "(2mm)"/"(3mm)" per colour is telling you veneer is a distinguishing
   spec, not a footnote — a 3mm sibling is not a safe template for a 2mm promo line) →
   copy box size, thickness, veneer, collection, install profile/method, finish type,
   certifications, warranty, and radiant-heat/suitability flags from that sibling
   verbatim. This is the common case — most promo colours are grade variants of a plank
   Titan already stocks in some other grade.
3. **No colour match, but every other record of that width + species (+ veneer, if the
   sheet differentiates) shares one box size / thickness / veneer value** → that's a
   collection-level default, not a guess. Safe to copy.
4. **No width + species precedent exists at all** (nothing else in the catalogue shares
   the width and species, at any colour or veneer) → this is the only case that is
   genuinely new-with-unknown-specs. Leave Box size / Thickness / Veneer blank, flag to
   the team, and stop there — do not invent a spec by analogy across species or width.

Whichever tier resolves it:

- **Do not apply the promo cost to an incorrect grade** (e.g. do not put a Character promo on a Select record)
- Set **Cost/unit = Promo cost ($/sf)** — since no original cost is available, the promo cost is used as a placeholder per the Sale item pricing logic rule 3
- Set **Retail price/unit = Cost + $ 1.00**
- Set **Promo cost ($/sf)** and **Promo end date** as per the promo sheet
- **Colour / tone is aesthetic, not a spec** — leave it blank rather than guessing from the colour name, even when every other field copied cleanly from a sibling
- Flag the new record's cost basis to the team (placeholder, not a confirmed dealer cost) even when the specs themselves are fully verified — spec confidence and cost confidence are separate questions

### Sale item pricing logic

When processing a supplier price list, some products are marked as SALE items with a reduced cost. These are promotional prices and should be handled differently from regular pricing. Follow this priority order to determine the original (non-promo) cost:

1. **Same collection, same section** — if the SALE item sits within a collection that also lists a regular (non-SALE) price for the same product specs, use that regular price as the original Cost/unit. The SALE cost goes into Promo cost ($/sf).

2. **Previous price list** — if no regular price exists in the current price list, check the most recent previous price list from the same supplier. Use that cost as the original Cost/unit. The SALE cost goes into Promo cost ($/sf).

3. **Use promo cost as original** — if neither source provides an original cost, use the SALE cost as Cost/unit. Retail price/unit = SALE cost + $ 1.00. The SALE cost still goes into Promo cost ($/sf) as well. When Cost and Promo cost show the same value, this signals that the original cost was not available and the promo cost was used as a placeholder.

In all cases, Promo cost ($/sf) = the supplier's SALE cost as-is. The regular Retail price/unit = Cost + $ 1.00. Retail adjustment during a promo is done manually.

### Length extraction — always attempt it

**Added 2026-09-03 (Albert).** `Length` is column 17 of the canonical list. Every ingest
attempts to populate it; leave it blank only when the supplier genuinely never states a
length.

**It is a text field on purpose.** Length is not reliably a number:

| Supplier states | Store | Why text |
|---|---|---|
| Random length | `RL` | A real product fact, not missing data — the dominant value on engineered and solid hardwood |
| A fixed length | `48"`, `1520mm`, `94.5"` | Units vary by supplier; keep the unit with the value |
| A range | `20" - 83"` | Common on wide-plank and XL lines |
| Random within a range | `RL (16" - 75")` | Both facts matter |
| Nothing | blank | Never invent one |

A number column would force discarding `RL`, ranges, and the unit — which is most of the
data. Store what the supplier printed.

**Where to find it.** Length is usually the third element of a printed dimension string:
`6½" x ¾" x RL` → `RL`; `9.29" x 59.76"` → `59.76"`; `(6+2mm x 9" x 60"RL)` → `60"RL`.
Watch for it in section headers rather than per-row — most suppliers state the size once
per collection and list only colours beneath.

**Do not confuse it with thickness or veneer.** In `5" x 12.7mm x RL` the middle value is
thickness. Where a supplier appends veneer to the same string (`RL - 2.5mm top`), the
length is `RL` and the veneer belongs in `Veneer / top layer (mm)`.

**Lightspeed is unchanged** — length keeps living in the LS `name` spec segment as it
always has. The new field is the source it reads from, rather than something re-parsed
out of the product name.

#### Why Length is text while Width and Thickness are numbers

**Confirmed by Albert 2026-09-03. This asymmetry is deliberate — do not "harmonize" the
three dimension fields to one type.**

| Field | Type | Why |
|---|---|---|
| `Width (in)` | Number | Always exactly one stated measurement; unit fixed by the field name. Fractions (`5 ¾"`) convert cleanly to `5.75`. |
| `Thickness (mm)` | Number | Same. |
| `Length` | **Text** | Frequently not a measurement at all. |

Width and thickness stay numeric because Bert's filters depend on it — "7-inch or wider",
"12mm and up". As text, `9` sorts before `12` and range filters break outright.

Length cannot be numeric without discarding most of the real data. One supplier, one run
(Canadian Standard, 2026-09-03) produced: `RL`, `RL (16"-75")`, `RL (20" - 83")`,
`1285mm`, `50.87"`, `48"` — random-length dominates, ranges are common, and metric and
imperial appear in the same supplier's sheet.

**Sortability is a known, accepted trade.** You cannot filter "planks over 48 inches" off
a text field. **Deferred (Albert, 2026-09-03):** if that need becomes real, add companion
numeric `Length min (in)` / `Length max (in)` fields **alongside** the text — never
convert it. Both are needed: a numeric field alone cannot express "random". Do not add
them speculatively; nothing quotes on length today.

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
| **SKU** | Single line text | Internal product code. Primary key — unique across all records. Format: CAT-SUPP-0001 e.g. ENG-VIDR-0042 | LS · Bert — **immutable and the source of truth; see RULE 0. Never written on an existing record by any process.** |
| **Product name** | Single line text | Human-readable name including colour and grade. e.g. Vidar 7.5" AWO — Macaroon (Character) | LS · Bert |
| **Brand** | Single line text | The product brand. May differ from Supplier — e.g. BOEN sold by Canadian Standard | LS |
| **Supplier** | Single select | Which supplier this product is ordered from. Choose from the controlled list. | Bert |
| **Supplier SKU** | Single line text | Supplier's own product code if they use one. Leave blank if supplier does not assign codes. Cowork uses this for price list matching. | Auto — blank if no supplier code |
| **Lightspeed ID** | Single line text | Lightspeed's internal record ID. **Generated by Lightspeed on import, never by us** — blank is the correct state for a product not yet uploaded. After an upload it must be **reverse-populated back into Airtable** (`ls-id-backfill`), matching on SKU; skipping that duplicates the product on the next run. Once populated, Airtable is source of truth and no automation overwrites it. See RULE 0a. | LS — populated post-upload |
| **LS Handle / Parent ID** | Single line text | Groups grade variants under one parent in Lightspeed. Shared by all grades of the same colour and width. **Must contain only letters and numbers — no hyphens, dots, spaces, or symbols.** This value is copied directly into Lightspeed on upload; LS rejects non-alphanumeric handles. **We create it ourselves** for a new product, from the handle-generating schema `[HANDLE_PREFIX][SizePrefix][SpeciesAbbrev][COLOR]` (e.g. VIDR6AWOSILVERSTONE) — never truncate the colour/collection token. Once stored it is authoritative: copied as-is on every later upload, never regenerated. See RULE 0a. | LS |
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
| **Length** | Single line text | Plank, tile or piece length **as the supplier states it**. Deliberately text, not a number — see *Length extraction* below. `RL` for random length, a measurement with its unit (`48"`, `1520mm`, `94.5"`), or a range (`20" - 83"`). **Always attempt to populate it** (Albert, 2026-09-03). | LS · Bert |
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
| **Retail price/unit** | Currency | Selling price per unit (same unit as Cost/unit — per sq ft for flooring, per piece for tile/stone/accessories). Default = Cost + $ 1.00 for flooring; accessory markups vary (see supplier sections). This is what Bert quotes. | LS · Bert |
| **MAP price ($/sf)** | Currency | **Holds either a MAP or an MSRP** (Albert, 2026-09-03 — one field for both, no separate MSRP field). A **MAP** is a contractual Minimum Advertised Price the supplier enforces (Grandeur); an **MSRP** is the supplier's advisory suggested retail (Biyork). Populated only when the price list actually publishes one — most suppliers publish neither, and a list price is never an MSRP. Bert will not quote below this value whichever it is, so a stored MSRP acts as a soft floor. | |
| **Pallet price ($/sf)** | Currency | Full skid / pallet price per sq ft where supplier offers a volume discount. | Auto |
| **Promo cost ($/sf)** | Currency | Active promotional cost per sq ft from the supplier. When populated, Bert flags this product as having an active promo. Retail price is adjusted manually — not auto-calculated. Cleared automatically when promo ends. | Bert · Auto |
| **Promo end date** | Date | When the promotional price expires. Cowork clears Promo cost automatically on this date. | Auto |
| **Volume pricing notes** | Long text | Tiered pricing rules. e.g. Vidar: Cut order $ 1.39 / 1-5 skids $ 1.34 / 6-20 skids $ 1.29 | |
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

### CSV file rules

- Column headers must match Airtable field names exactly
- All columns must be present even if blank
- Checkbox fields: use TRUE or FALSE (text)
- Currency fields: numbers only, no $ sign (e.g. 4.79 not $ 4.79)
- Date fields: YYYY-MM-DD format
- Multi-select fields: separate values with a semicolon (e.g. Kitchen; Bedroom; Living room)

### CSV, not xlsx — how to write it

**Decided 2026-09-03 (Albert): every export is a `.csv`.** One format for both the
Airtable and the Lightspeed upload, so there is nothing to convert before importing and
no question about which file is which.

> **Reaffirmed and widened 2026-09-09 (Albert): "make sure Notion files are csv always."**
> The rule is about **every file attached to a Notion row's `Extracted Files`**, not only
> the two upload files. `.xlsx` never goes on a row — not as a second copy, not as a
> "review copy," not alongside the CSV.
>
> **This is the loophole that produced the violation, so it is worth naming.** The rule
> above says "every *export*"; the 2026-09-09 Gracious backfill attached a `.xlsx`
> *review* copy beside each CSV, reasoning that a review artifact was not an export and
> that the yellow highlighting justified it. It was still a file on the row, and it still
> made "which file is which" a question. **A second format is not a second opinion.**
>
> **This binds the backfill too**, which is where it was broken: write the
> `ls-id-backfill` output as CSV like everything else. Nothing is lost that matters —
> the match-status and match-notes columns are real columns and survive the CSV; only
> the row highlighting does not, and a reviewer filters or sorts on the status column
> instead. `ls-id-backfill` now says the same thing in its own words, so the two agree;
> if they ever drift, this rule is the one that governs what goes on a Notion row.
>
> An LS export *arriving* as `.xlsx` is fine — that is input, and Lightspeed exports a
> workbook. The rule is about what we write and what we attach.

Four settings, each of which fails silently if you get it wrong:

| Setting | Value | Why |
|---|---|---|
| Encoding | **UTF-8, no BOM** | Product names carry `—`, `½`, `¾`, `×`, `"`. A BOM would make the first header read `\ufeffSKU` and the import would not find the SKU column. |
| Quoting | **minimal, RFC 4180** | `Salesperson notes` contains commas on essentially every row, and embedded `"` from quoted LS product names. Let the CSV writer quote and double-escape; never hand-roll it. |
| Line endings | **CRLF** (`newline=''` in Python) | RFC 4180, and what Excel expects if anyone opens the file to eyeball it. |
| Empty cells | **empty string, not `None`** | `None` stringifies to the literal text `None` and lands in the field. |

```python
with open(out, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
    for row in rows:
        w.writerow(['' if c is None else c for c in row])
```

**Verify the round-trip before attaching.** Read the CSV back and compare cell-for-cell
against the source rows — commas and unicode are exactly the cases that look fine in a
spot-check and are wrong in bulk.

The Notion upload MIME type changes with it: `text/csv`, not the spreadsheetml type.
Sending the wrong one is rejected with a `400 validation_error`.

### Canonical column list — ALWAYS use this exact order

**Every Airtable upload file must contain exactly these 57 columns in this order.** Do not infer columns from the schema description — use this list verbatim. Columns not applicable to a product are left blank (None), never omitted.

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
| 17 | Length |
| 18 | Thickness (mm) |
| 19 | Wear layer (mil) |
| 20 | Veneer / top layer (mm) |
| 21 | Veneer cut type |
| 22 | AC rating |
| 23 | Finish type |
| 24 | Install profile |
| 25 | Install method |
| 26 | Locking system |
| 27 | Underpad included |
| 28 | Underpad type |
| 29 | IIC rating |
| 30 | STC rating |
| 31 | Tile format |
| 32 | Weight per piece (kg) |
| 33 | Certifications |
| 34 | Cost/unit |
| 35 | Retail price/unit |
| 36 | MAP price ($/sf) |
| 37 | Pallet price ($/sf) |
| 38 | Promo cost ($/sf) |
| 39 | Promo end date |
| 40 | Volume pricing notes |
| 41 | Last price update |
| 42 | Price last changed by |
| 43 | Box size (sf) |
| 44 | Pieces per box |
| 45 | Boxes per skid |
| 46 | Pieces per pallet |
| 47 | Stock status |
| 48 | Active |
| 49 | Waterproof |
| 50 | Pet friendly |
| 51 | Radiant heat compatible |
| 52 | Traffic rating |
| 53 | Suitable rooms |
| 54 | Residential warranty (yrs) |
| 55 | Commercial warranty (yrs) |
| 56 | Salesperson notes |
| 57 | Pairs well with |

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
  Bert schema CSV export instead — the canonical column list above, in that exact
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

> **"Stop there" means stop before importing — still produce the file.** Clarified
> 2026-09-03 after a run read it the other way and produced nothing for Canadian
> Standard. A missing supplier subsection means *invent no supplier-specific rules*, not
> *extract nothing*: apply the global rules, and record every choice the document forced
> as an explicit assumption in `Salesperson notes` and in the run summary — the **cost
> basis** first, since dealer-cost-vs-suggested-retail changes every row and precedent
> runs both ways (CIF ×0.60, Olympia ×0.564, Biyork prints MSRP beside a dealer price).
> The checklist gates the import; the file makes the checklist *answerable*, because the
> reviewer can see the actual columns while deciding. Withholding it leaves them nothing.
>
> A new supplier also gets **no Lightspeed file** — LS columns 1–3 are copied from the
> Airtable state, which does not exist until the import happens.

### Step 2 — the matching cascade

> Everything below resolves **which existing SKU a row belongs to**. It never
> produces a reason to change one. Per RULE 0, the stored SKU wins every
> disagreement — a mismatch means the incoming row is wrong about the product, not
> that the record needs renaming.

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

- **Never the `SKU` field** (RULE 0). It is the merge key, not a payload field.
  Upsert with `fieldIdsToMergeOn: ['fldx3byCOht5HbKmH']` and omit SKU from the
  written fields. If a diff ever shows a SKU change, the match is wrong — stop and
  escalate rather than writing it.
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

- **SKU** — every record must have one, and it **never changes after creation** (RULE 0). It is the source of truth every other system matches to.
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

- **SKU — never edited by anyone, human or automated, once the record exists (RULE 0).
  Not a "prefer not to": there is no workflow in which editing a SKU in place is
  correct. Escalate instead.**
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
4. Generate an Airtable-ready CSV file with all 57 schema fields as columns
5. Spot-check a sample covering every edge case before committing to import

---

### ⚠️ Cost basis — default to the printed price, flag the exceptions

**Rule (Albert, 2026-09-10 — supersedes the blocking version of 2026-09-03).** There is
now a **default**, and it applies unless a supplier's subsection says otherwise:

> **The price list's printed prices are the COST.** `Retail price/unit = Cost/unit + $ 1.00`.
> A column printed as **MSRP**, suggested retail or suggested price goes to
> **`MAP price ($/sf)`** and never touches `Cost/unit`.

Apply it and keep going. **Do not stop to ask which number is the cost.** The old rule
made this a blocking question on every new supplier, which held whole files behind one
answer; the default settles the common case, and the exceptions get flagged instead.

**Flag for human review — do not stop, and never guess — when:**

1. **The supplier is new.** Flag the whole file: there is no subsection to inherit from,
   nothing has been reconciled against a live record, and **every detail needs a human
   check before upload**. Spec confidence and cost confidence are separate questions and
   neither is earned yet.
2. **The sheet has more than one candidate cost column**, or a number whose role is not
   stated, on *any* supplier — a second price beside the first, an "MSRP"/"list"/"retail"
   column, a promo price beside a regular one, or a per-piece figure next to a per-sq-ft
   one. Ambiguity on an existing supplier means the *format changed*; the stored note may
   no longer describe the file in front of you.

Flag concretely: name the columns as printed, say which one you took as cost under the
default, and name the SKUs affected. Extraction proceeds; the **import** is what waits on
the human. An ambiguity absorbed silently is the one failure nothing downstream detects.

**Then write the answer into the supplier's subsection under a `#### Cost column`
heading.** That is what makes it a one-time cost. A future run reads the subsection,
finds the basis already settled, and proceeds without asking again. An answer left only
in a chat log or in `Salesperson notes` is an answer that gets re-litigated every quarter.

Record all four of: which printed column is `Cost/unit`, any multiplier applied, whether
the supplier publishes an MSRP / suggested-price column at all, and how they mark promo
pricing. "No MSRP column" is a real finding worth stating, not an omission — it is what
stops the next run hunting for one.

#### Which printed number feeds which field

**Set by Albert 2026-09-03.** A price list's numbers sort into exactly three destinations.
Getting this wrong is what overstates cost, so it is worth being literal about:

| Printed as | Feeds | Rule |
|---|---|---|
| **List price**, **cost per unit**, **cost per sq ft**, **cost per piece** | **`Cost/unit`** | These are the **cost-side inputs**. Take the one the supplier prices in, apply the supplier's discount multiplier if their terms give one, and store the result. |
| **MSRP**, **suggested retail**, **suggested price**, or a similarly-named column | **`MAP price ($/sf)`** | Advisory — a notification of what the supplier suggests we retail at. **Never touches `Cost/unit`.** Shares the MAP field by ruling; see *MSRP goes into `MAP price ($/sf)`* below. |
| **Promo price**, **sale price**, **promotional cost** | **`Promo cost ($/sf)`** | A cost, not a selling price — see *Promo and sale costs* below. |

**MSRP is populated only when the price list actually publishes one** — an MSRP column, a
suggested-price column, or an equivalently named field. **No such column means no MSRP,
full stop.** Do not derive, infer or back-compute one, and do not treat a terms-page
remark about retail pricing as a substitute for a column.

**"List price" is a cost-side input, not an MSRP.** This is the distinction that matters
in practice. CIF and Olympia both print a list price and grant Titan a discount off it;
that list is the base the multiplier is written against, so it belongs to the cost side.
Neither supplier publishes an MSRP column, so **neither gets an MSRP value.**

| The sheet prints | Supplier | `Cost/unit` | MSRP |
|---|---|---|---|
| One price, already our cost | Canadian Standard | Printed price as-is | None published |
| A list price, discount in the terms | CIF, Olympia | List × discount (CIF ×0.60; Olympia ×0.60×0.94 = ×0.564) | None published |
| A dealer price **and** an MSRP column | Biyork (`Your Price` + `MSRP/SF`) | `Your Price` | `MSRP/SF` → `MAP price ($/sf)`. The one supplier that has one |

**Read the terms page, not just the column header.** CIF heads its column "Cost Per Sq
Ft" while page 3 grants 40% off. Taking the header at its word would overstate every CIF
cost by 67%. The header tells you the supplier's word for the number; the terms tell you
whether a multiplier applies.

**`Retail = Cost + $ 1.00` is the default and stays the default.** A multiplier is a
supplier-specific override that exists only where the supplier's own sheet forces it —
never a house adjustment applied on top of a confirmed dealer cost.

#### Promo and sale costs — a third destination

A promotional or sale price from the supplier is a **cost**, not a selling price, and it
has its own field. It never overwrites `Cost/unit`.

| Field | Holds |
|---|---|
| `Cost/unit` | The **regular** cost. Stays put through a promo — it is what the price reverts to. |
| `Promo cost ($/sf)` | The supplier's promotional / sale cost. Populated → Bert flags an active promo. |
| `Promo end date` | The printed expiry. Cowork clears `Promo cost` on this date. |

- A sheet printing **paired Promotion / Regular columns** puts Regular in `Cost/unit` and
  Promotion in `Promo cost ($/sf)` — never the promo price into `Cost/unit`, which would
  make a temporary discount look like a permanent cost drop and lose the reversion price.
- `Retail price/unit` is **not** auto-recalculated from a promo cost; retail during a
  promo is adjusted manually (see *Promo pricing flow*).
- A supplier discount multiplier and a promo are independent: apply the multiplier to
  both the regular and the promo price where the supplier's terms cover both.

#### MSRP goes into `MAP price ($/sf)` — settled

**Ruling (Albert, 2026-09-03): MSRP is stored in `MAP price ($/sf)`. One field carries
both instruments — no separate MSRP field.**

So the field holds, depending on the supplier:

| Supplier publishes | Stored in `MAP price ($/sf)` | Nature |
|---|---|---|
| A contractual MAP | The MAP | Binding — advertising below it risks the dealership |
| An MSRP / suggested price | The MSRP | Advisory — the supplier's recommendation |
| Neither | Blank | Most suppliers |

**Practical effect, stated so it is not a surprise later:** Bert's floor logic reads this
one field, so it will not quote below a stored MSRP any more than below a stored MAP. In
Titan's case that is a margin-protective default rather than a problem — but it does mean
a stored MSRP behaves as a soft floor in practice. If Bert should ever be free to quote
under an MSRP while still respecting a true MAP, that needs a distinguishing flag; it does
not today.

**Verified 2026-09-03.** `MAP price` is populated on 399 records — Grandeur (true MAP) and
Biyork (MSRP). Zero CIF or Olympia records, which is **correct**: neither publishes an
MSRP or suggested-price column, and their printed list price is a cost-side input.

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

- **Flooring products**: standard `Retail = Cost + $ 1.00` (global rule).
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

Example from Feb 23 2026 list: Designer 7.5" regular colours (Monet, Dali) @ $ 4.99 pallet; SALE colours (Da Vinci, Picasso) @ $ 3.99 pallet → Cost=$ 4.99, Retail=$ 5.99, Promo cost=$ 3.99, Promo end date blank.

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

Oak Riser has dual pricing (Pallet $ 2.99 / Piece $ 3.99). Use $ 3.99 as `Cost/unit` (per-piece).

#### Known issues / soft spots

When processing a new FAW list, double-check these recurring ambiguities:

- **Wear layer not always listed** — the 5mm Aqua Commercial plank (Mars, Pluto, Mercury, Earth, Saturn, Venus) doesn't state wear layer; 3mm and 5mm tile variants in the same line say 0.5mm. If missing, leave blank and flag.
- **Tobermory duplicate** — appears in two size variants. Confirm both exist by asking the rep before deduplicating.
- **Colourway reuse across collections** — "Westminster" appears in both Aquaplus Platinum (9mm) and Royal (8mm). "Windsor" appears in both Royal and 6.5mm SPC. Create separate records; differentiate in LS Handle with a collection suffix.
- **Effective date** — every FAW list is headed "Effective [date] — price subject to change due to fluctuating ocean freight charges." Record the effective date in `Price list reference` when logging to Price History Log.

#### FAW ingest output format

Always produce a CSV file with all 54 schema fields as columns (header row), records starting on row 2. File naming convention: `faw_airtable_upload_[YYYY-MM-DD].csv`. Save to `/mnt/user-data/outputs/`.

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
- Standard markup applies: `Retail = Cost + $ 1.00`.

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

Produce a CSV file with all 58 schema fields as columns (header row), records starting on row 2. File naming: `toucan_triforest_airtable_upload_[YYYY-MM-DD].csv`. Save to `/mnt/user-data/outputs/`.

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

Purelux lists **Price/SF** and **Price/Box** columns. Use Price/SF as `Cost/unit`. Standard markup applies: `Retail = Cost + $ 1.00`.

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

Purelux marks clearance items with red "On Sale" text in the price column. Known pattern from Feb 2025 list: **5 WPC Series colours (Arctic Mist, Mocha Glow, Natural Essence, Nimbus Gray, Whispering Breeze) on sale at $ 1.99/sf** while other colours in the same series are $ 2.99/sf.

**Sale pricing flow**:
- If a sale colour has a **regular-price equivalent in the same series** (same structure, same spec sheet), set `Cost` = regular equivalent price, `Retail` = Cost + $ 1.00, `Promo cost ($/sf)` = sale price.
- If a sale item has **no regular equivalent**, set `Cost` = sale price, `Retail` = Cost + $ 1.00, `Promo cost ($/sf)` = sale price (clearance-only product).
- **Promo end date** = blank (Purelux does not publish end dates).
- Flag in Salesperson notes: "ON SALE. Regular price $X.XX/sf assumed (same structure as series). Confirm with Purelux."

#### Effective date quirk

The Feb 2025 PDF shows conflicting date information — filename "Feb 2025", cover page "2025", but every page footer says "Effective Oct 1, 2022." Use the **most recent date inferable from the filename or cover** as `Last price update`. Flag the discrepancy in response but proceed.

#### Purelux ingest output format

Produce a CSV file with all 58 schema fields as columns, records starting on row 2. File naming: `purelux_airtable_upload_[YYYY-MM-DD].csv`. Save to `/mnt/user-data/outputs/`.

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

Evergreen lists `Price / Sq.ft` per tier. Standard markup: `Retail = Cost + $ 1.00`.

**Clearance pricing nuance** — Evergreen marks clearance items with asterisks on the code AND yellow highlighting on the row AND a "*Clearance" label in the header. Pricing logic:

- **If the clearance item has a regular-price equivalent** (same thickness/dimensions in another tier): `Cost` = regular equivalent price, `Retail` = Cost + $ 1.00, `Promo cost ($/sf)` = clearance price.
  - Example: `2020*` at $ 1.69 has a regular equivalent at $ 1.79 in the same 48"×7.7"×12mm tier. Cost = $ 1.79, Retail = $ 2.79, Promo = $ 1.69.
- **If the clearance item has no regular equivalent** (unique thickness): `Cost` = clearance price, `Retail` = Cost + $ 1.00, `Promo cost ($/sf)` = clearance price.
  - Example: 10mm tier has no non-clearance equivalent. Cost = $ 1.49, Retail = $ 2.49, Promo = $ 1.49.
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
| Water Resistant 14mm, 60"×9.4" + 2mm pad, $ 1.69/sf | `Water Resistant 14mm` |
| Waterproof 10mm clearance, 60"×9.4", $ 1.49/sf | `Waterproof Drop Lock 10mm (Clearance)` |
| Waterproof 12mm clearance, 48"×7.7", $ 1.69/sf (`2020*`) | `Waterproof Drop Lock 12mm Short Plank` (same collection as the regular tier; stock status distinguishes it) |
| Waterproof 12mm regular, 48"×7.7", $ 1.79/sf | `Waterproof Drop Lock 12mm Short Plank` |
| Waterproof 12mm, 60"×9.4", $ 1.89/sf | `Waterproof Drop Lock 12mm Standard Plank` |
| Waterproof 12mm Large Board, 72"×9.4", $ 1.99/sf | `Waterproof Drop Lock 12mm Large Board` |

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

Produce a CSV file with all 58 schema fields as columns, records starting on row 2. Highlight clearance rows with yellow fill (`FFF3B0`) for visual scanning. File naming: `evergreen_airtable_upload_[YYYY-MM-DD].csv` (use effective-date start). Save to `/mnt/user-data/outputs/`.

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

- **All flooring products** (engineered hardwood and SPC vinyl): standard `Retail = Cost + $ 1.00` (global rule).
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

File naming convention: `greentouch_airtable_upload_[YYYY-MM-DD].csv`. Save to `/mnt/user-data/outputs/`.

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

Example: `Vidar: Cut order $ 1.39 / 1-5 skids $ 1.34 / 6-20 skids $ 1.29`

Standard markup applies: `Retail = Cost + $ 1.00`.

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

File naming convention: `vidar_airtable_upload_[YYYY-MM-DD].csv`. Save to `/mnt/user-data/outputs/`.

---

### Grandeur

Grandeur is supplier and brand (single entity). Multi-category supplier: engineered hardwood, solid hardwood, SPC/WPC LVP, laminate, and specialty products. Price list is issued as a multi-page PDF organized by product category. Grandeur enforces MAP pricing — **never quote Cost to customers; only Retail price is customer-facing**.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Grandeur` |
| **Brand** | `Grandeur` |
| **SKU supplier code** | `GRAN` — 4-char suffix, canonical format |
| **Internal SKU format** | `[CAT]-GRAN-####` — the canonical format, e.g. `ENG-GRAN-0030`, `SPC-GRAN-0015`. **`GRND` is the Lightspeed name prefix, NOT the Airtable SKU prefix** — see the correction note below. |
| **Supplier SKU** | Mostly **blank**. Despite an earlier note that Grandeur publishes codes, only **10 of 239** live records carry a `Supplier SKU`. Populate it when a code is genuinely printed; do not invent one. Expect price-list matching to fall to tier 3 (specifications / `Product name`). |

#### SKU prefix by product type

`GRND…` is the **Lightspeed** name prefix. The **Airtable** SKU is `[CAT]-GRAN-####`.
Do not use the LS prefix as an Airtable SKU.

| Category | LS Name prefix | Airtable SKU format | Live count (2026-09-03) |
|---|---|---|---|
| Engineered hardwood | `GRNDENG` | `ENG-GRAN-####` | 102 |
| Solid hardwood | `GRNDHWD` | `HWD-GRAN-####` | 6 |
| LVP | `GRNDLVP` | `LVP-GRAN-####` | 36 |
| SPC (rigid core) — **legacy** | `GRNDSPC` | `SPC-GRAN-####` | 45 |
| WPC — **legacy** | `GRNDWPC` | `WPC-GRAN-####` | 20 |
| Laminate | `GRNDLAM` | `LAM-GRAN-####` | 30 |

> **Correction, 2026-09-03.** This subsection previously stated the internal SKU
> prefix was `GRND` (`GRNDENG-0001`). That is wrong and was never what the base held.
> The 2026-09-03 routine run generated 231 rows of `GRNDENG-####` / `GRNDLVP-####`
> SKUs that matched **none** of the 239 existing Grandeur records; importing that file
> would have duplicated the whole Grandeur catalogue. Verified against
> `appWHOVZ0QCS0xQ3M` / `tblfLXD3zkSdNQGbS`. `SPC-`/`WPC-` are legacy prefixes still
> present in the base — match against them, but issue new vinyl SKUs as `LVP-`/`LVT-`
> per the global SKU format reference.

#### Cost column

Grandeur lists a single price column per product. Use that value as `Cost/unit`. Standard markup applies: `Retail = Cost + $ 1.00`.

**MAP pricing** — Grandeur enforces Minimum Advertised Price on some lines. When MAP is listed:
- Store MAP in `MAP price ($/sf)` field.
- Bert will not quote below MAP — it uses `MAP price` as the floor when present.
- Standard `Retail = Cost + $ 1.00` still applies for internal cost tracking.

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

#### Product name — the tier-3 matching key

Grandeur rarely carries a `Supplier SKU`, so `Product name` is what an update run
matches on. The live base and the extraction agree on this shape, and it must not
drift:

```
Grandeur [width]" [SpeciesAbbrev] — [Colour] ([LetterGrade])
```

**The species abbreviations are a hard contract, not a preference.** The 2026-09-03
run had to normalise 56 rows because the extraction invented its own; a mismatch here
means a product silently reads as new and gets a duplicate SKU.

| Use | Never | Species |
|---|---|---|
| `EWO` | | European White Oak |
| `AO` / `WO` | | American Oak / White Oak |
| `NAH` | `HIC` | North American Hickory |
| `HM` | `MPL` | Hard Maple |
| `NARO` | `RO` | North American Red Oak |

Vinyl/laminate rows use the collection in place of the species —
`Grandeur 7" Pacific — Canterbury`.

**No redundant parentheticals.** The width is already in the name, so
`Sandbar (ABC)` — never `Sandbar (7.5") (ABC)`. No thickness parenthetical either:
`Connecticut`, not `Connecticut (7.0mm)`. Collection names drop a trailing
"Collection": `12mm XXL — …`, not `12mm XXL Collection — …`.

**The grade in parentheses is the supplier's letter grade verbatim** (`(ABCD)`,
`(ABC)`, `(AB)`) — *not* the mapped canonical word. The mapped value goes in the
`Grade` field; the name keeps the letters. Examples from the live base:
`Grandeur 7.5" EWO — Moonfrost (ABCD)`, `Grandeur 7.5" AO — Honeycomb (AB)`.
**Exception — solid hardwood** uses the word form without "Grade": `(Select)`, never
`(Select Grade)`.

#### LS Handle convention

`GRND` + the Product name minus the leading `Grandeur ` and minus the trailing grade
parenthetical, uppercased, all non-alphanumerics stripped. Examples verified against
the live base: `GRND75EWOMORAINE`, `GRND7PACIFICCANTERBURY`, `GRND12MMAQUAMATESYDNEY`.

**Never truncate the colour or collection token** — the same rule as CIF and Olympia.
The 2026-09-03 run truncated collections to 12 characters and produced collisions
(`GRNDESSENTIAALGONQUIN`, `GRND12COLLECARLESNATURAL`), and also left dots in
(`GRND6.5EWOBARBADOS`) which LS rejects outright. Strip to alphanumeric, keep the
whole token, however long it gets.

**For a matched row, take the handle from the live record rather than regenerating
it** — the stored handle is what Lightspeed already groups on.

#### Upload stats (reference)

Live catalogue as of **2026-09-03**: **239 Grandeur records** (ENG 102, SPC 45,
LVP 36, LAM 30, WPC 20, HWD 6), only 10 of which carry a `Supplier SKU`.

Matching resolves at **tier 3 (specifications / `Product name`)** for 229 of 239 rows,
because only 10 carry a `Supplier SKU`. Use the matching cascade under "Updating
existing products from a price list"; do not upsert on a SKU the extraction generated.

> An earlier version of this block cited a `performUpsert` on
> `fieldIdsToMergeOn: ['fldx3byCOht5HbKmH']` against 238 extracted products. Merging
> on a **run-generated** SKU is exactly the failure the 2026-09-01 changelog entry
> forbids and the 2026-09-03 run reproduced. Merge only on a SKU read back from the
> base for that specific product.

**Every LS upload row for an existing product needs its `Lightspeed ID`** in column 1
of the LS file. All 239 live Grandeur records carry one (`fldQhbI35Ng2ZxNKL`). A blank
`id` on an existing product makes Lightspeed **create a duplicate instead of
updating** — the 2026-09-03 LS file was built with all 231 ids blank and had to be
backfilled before it was safe to import. Leave `id` blank only for genuinely new
products.

#### Grandeur ingest output format

Two files per price list, both attached to the Notion Price Lists row's
`Extracted Files` (see `methods/pricelist-routine-prompt.md` step 7):
`grandeur_airtable_upload_[YYYY-MM-DD].csv` and
`grandeur_ls_upload_[YYYY-MM-DD].csv`. In this repo they are written to
`ingest/YYYY-MM-DD/`, not `/mnt/user-data/outputs/` (that path is for claude.ai
sessions).

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

Standard markup applies: `Retail = Cost + $ 1.00` for all flooring.

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

File naming convention: `sunshiny_airtable_upload_[YYYY-MM-DD].csv`. Save to `/mnt/user-data/outputs/`.

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

Woden prints a single per-sf price per collection (sometimes two/three price tags where promo tiers exist). That price is the **cost**. Standard markup applies: `Retail = Cost + $ 1.00`. Accessories and underpad are priced per piece and are also costs (see below).

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

**Lumine** lists the same colours in both AB and ABC at different prices (AB @ $ 5.49, ABC @ $ 4.99) — split into two records per colour, one per grade, with the grade in the Product name suffix (` — Snowhaze AB` / ` — Snowhaze ABC`).

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

- **"Clearance / while stock last"** (7 Diamond Collection) → `Stock status = Clearance` **and** apply Sale pricing. No regular price exists on the list for 7 Diamond, so **Sale rule 3**: `Cost = SALE price`, `Retail = Cost + $ 1.00`, `Promo cost = SALE price`. Cost = Promo cost signals original cost unavailable. Note "while stock last; final sale" and the 8 Diamond replacement.
- **"(promotion)"** (Vermont Charcoal @ $ 2.50; Grand Chateau Natural/Coyote @ $ 2.50; and effectively the lower in-collection price tiers) → `Stock status` stays **blank**; `Promo cost = promo price`; `Cost` = the in-collection regular price (Sale rule 1). For Grand Chateau Natural/Coyote no separate regular price is printed → use the nearest in-collection regular tier ($ 3.29) as Cost and flag to confirm.
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
| Riser (sold separately) | $ 8 | +$15 | $23 |
| 2mm Blue Underpad w/ vapour barrier (200 sf) | $ 6 | +$20 | $26 |
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

Produce a CSV file with all 57 schema columns. File naming: `woden_airtable_upload_[YYYY-MM-DD].csv` using the list's Effective date. Save to `/mnt/user-data/outputs/`.

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

**This means every printed cost column on the price list is list price (the retailer's suggested retail to end customers), not Titan's actual cost — despite the column being headed "Cost Per Sq Ft".** Taking it at its label overstates cost by 67%. Apply a single ×0.60 multiplier to convert to Titan's cost before pasting into `Cost/unit`:

```
Cost/unit = printed "Cost Per Sq Ft" (or "Cost per piece") × 0.60
```

Round to two decimals. Apply this exactly once — do not double-discount. The pages labelled "Net Cost" (pp. 40–41) are a separate qty-discount tier (10+ pieces) and are out of scope for the standard ingest; do not use those numbers as the regular cost.

**The printed list price is a cost-side input, not an MSRP.** CIF publishes no MSRP or suggested-price column, so no MSRP value is stored for CIF — see *Which printed number feeds which field*.

#### Markup overrides — CIF only

CIF breaks the standard `Retail = Cost + $ 1.00` rule. Three distinct markup tiers apply:

| Product type | Markup | Notes |
|---|---|---|
| Tile (porcelain, ceramic field tile, slabs) | `Retail = Cost + $ 2.00` | Applies to floor and wall tile, regardless of size or material |
| Mosaic (anything `Tile format = Mosaic`, including hex mosaics, listellos, pencils, decors) | `Retail = Cost + $ 5.00` | Higher markup reflects accent-product positioning |
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
- Apply mosaic markup `Retail = Cost + $ 5.00`
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

Produce a CSV file with all 57 schema columns. File naming: `cif_airtable_upload_[YYYY-MM-DD].csv` using the list's Effective date (the date printed on the Terms letter, page 3). Save to `/mnt/user-data/outputs/`.

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

Round to two decimals. Apply the 0.564 multiplier exactly once. Example: `$ 9.11/sf` list → `9.11 × 0.564 = $ 5.14/sf` cost.

**The printed list price is a cost-side input, not an MSRP.** Olympia publishes no MSRP or suggested-price column, so no MSRP value is stored for Olympia — see *Which printed number feeds which field*.

Use the **`$/SqFt`** figure as `Cost/unit` for anything sold by area (tile, stone, vinyl). Use the **per-piece** figure (`$/Pcs.`, `$/Lin.Ft`, `$/Set`) as `Cost/unit` for per-piece-only items (thresholds, jambs, trims, vinyl nosing/reducer) — those have no meaningful `$/SqFt`.

#### Markup overrides — Olympia (CIF-style tiers)

Olympia breaks the standard `Retail = Cost + $ 1.00` rule, using the same tier structure agreed for CIF:

| Product type | Markup | Applies to |
|---|---|---|
| Field tile (porcelain, ceramic, granite, marble, limestone, quartzite, travertine, slate field tile, agglomerated slabs) | `Retail = Cost + $ 2.00` | `Category = Tile / Stone`, `Tile format` ≠ Mosaic |
| Mosaic (anything `Tile format = Mosaic` — glazed porcelain mosaics, mother of pearl, metal/aluminum mosaic, riverstone, sheet-format glass) | `Retail = Cost + $ 5.00` | `Tile format = Mosaic` |
| Ceramic Trims (bullnose, cove base, pencil, listello — the Trims section) | `Retail = Cost + $10.00` | `Product type = Moulding`, `Category = Tile / Stone` |
| SPC / LVT vinyl flooring (Chimestone, Chimewood) | `Retail = Cost + $ 1.00` | `Category = LVP / LVT`, `Product type = Flooring` |
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

Produce a CSV file with all 57 schema columns. File naming: `olympia_full_airtable_upload_[YYYY-MM-DD].csv` using the list's effective date (foot of page, e.g. 2026-01-26). Save to `/mnt/user-data/outputs/`. A typical full Zone AT ingest produces ~3,000 rows across the 20 in-scope sections.


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

#### Lightspeed name prefix — CONFIRMED 2026-09-10 against the live export

Verified against a full live Biyork Lightspeed export (416 products). The PL-325 build's derived prefixes were checked and are **correct as built** — no renaming was needed, this section exists so the next run doesn't have to re-derive them:

| Product type | Prefix / convention | Live example |
|---|---|---|
| Engineered hardwood | `BIYKENG` | `BIYKENG - Nouveau 5 American Oak (Abode) \| 5" x 19.05mm x RL up to 6ft - 25.08sf/b` |
| LVP (vinyl plank) | `BIYKLVP-SPC` | `BIYKLVP-SPC - Hydrogen 5 (Cashmere) \| 7" x 5mm x 48" - 26.43sf/b` |
| LVT (vinyl tile) | `BIYKLVT-SPC` | `BIYKLVT-SPC - Hydrogen 6 Tile (Bourbon) Click \| 24" x 6mm x RL - 19.38sf/b` |
| Laminate | `BIYKLAM` | `BIYKLAM - Riptide (Black Pearl) \| 7.5" x 12mm x 48" - 15.39sf/b` |
| **Accessories** | **Not** the generic cross-supplier `[Supplier] - Transition \| ...` format, and **not** an abbreviated `BIYKACC` prefix (that pattern exists on ~33 older records but is legacy, not current). Current convention (191 live records) is the full spelled-out `Biyork [Collection] [Type] — [Colour]`, which is exactly what Airtable's `Product name` already stores for Biyork accessories — copy it verbatim, same as the Weiss/Vizion accessory rule. | `Biyork Hydrogen 5 Reducer — Cashmere`, `Biyork Riptide Overlap Stairnose — Black Pearl`, `Biyork Hydrogen 6 Tile Stairnose — Combed Cotton` |

A handful of legacy Nouveau 6/7/8 European Oak records (7 total) use an older `BIYENG` (no K) prefix with a different `#code` name format — that's historical, not the convention for new imports.

#### Re-code quirk — Biyork periodically reprints the same colour under a new internal code

**Ruling (Albert, 2026-09-10):** when a later Biyork price list shows a colour/collection that already exists live under a different Biyork product code, **the old SKU stays the live product — do not create a new one.** The two price lists this has now been seen on (May 22 2026 and July 15 2026, both for Hydrogen 6 Plank/Tile colours: Lily Canvas, Midday Sunrise, Raw, Dusty, Chalk, Combed Cotton + their T-Moulding/Stairnose accessories) showed no real product change — the "new" entry differs from the old live record's name at most cosmetically (e.g. `Biyork Hydrogen 6 Plank 7.0" — Lily Canvas` → `Biyork Hydrogen 6 Plank — Lily Canvas`, dropping the width token that's already captured in `Width (in)`); the 3 accessory pairs checked had **identical** names already.

**Handling:** flag these `MatchStatus: ambiguous` at extraction time as before (never silently treat as `new`), but once confirmed a re-print rather than a real change, do not create a parallel Airtable record — the PL-325 run's 9 such rows were deleted 2026-09-10 after this confirmation, since the corresponding old SKUs (`LVP-BIYK-BYKHY6HP50LC/MS/50RA/50DU`, `LVT-BIYK-BYKRCET50CH`, `LVT-BIYK-BYKHY6HT50CO`, `ACC-BIYK-BYKH6TISTCC/STCH/TITMCH`) were already live and correct. Only update the old record's `Product name`/description if the later list actually adds real information — a dropped width digit is not that.

#### Cost column

Biyork prints **`MSRP/SF`** and **`Your Price`**.

- **Use `Your Price` as `Cost/unit`.**
- Put `MSRP/SF` in the `MAP price ($/sf)` field — correct per the 2026-09-03 ruling that one field carries both MAP and MSRP. Biyork is currently the only supplier publishing an MSRP at all.
- Standard markup applies to flooring: `Retail = Cost + $ 1.00`.

#### Markup overrides (accessories)

Accessories are priced per piece (Biyork gives a real per-piece `Your Price`). Apply the global accessory markup standards on top of the per-piece cost:

- **T-Molding** / **T-Mould** → Cost + $10
- **Reducer** → Cost + $10
- **Stairnose** / **Overlap Stairnose** → Cost + $15
- **Vents** (Nouveau wood vents, per-piece) → Cost + $10

#### Scope of ingest

In scope: **ENG** (Nouveau lines), **LVP/LVT** (Hydrogen + Traktion), **LAM** (Riptide), and all **mouldings/accessories** (T-Mould, Reducer, Stairnose, Overlap Stairnose, Nouveau wood vents). Out of scope unless requested: **Underlayment** (p.18) and **Adhesive** (p.19) — jobsite consumables.

#### Collections (use verbatim)

Engineered hardwood (Nouveau): `Nouveau 5 American Oak` (new on the May 22 2026 list), `Nouveau 6`, `Nouveau 6 American Oak`, `Nouveau 6 Clic`, `Nouveau 7 Prelude`, `Nouveau 7`, `Nouveau 7 Bespoke (Plank)`, `Nouveau 7 Bespoke (Herringbone)`, `Nouveau 8`.
Vinyl: `Hydrogen PRO 2mm`, `Hydrogen PRO Tile 2mm`, `Hydrogen PRO 3mm`, `Hydrogen PRO Tile 3mm`, `Hydrogen 5`, `Hydrogen 6 Plank`, `Hydrogen 6 Tile`, `Hydrogen 7`, `Hydrogen 7 Angle & Angle` (new on the May 22 2026 list; 9" × 60" × 7mm, Angle/Angle — a separate collection from `Hydrogen 7`), `Hydrogen 8`, `Traktion`.
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

- **⚠️ Recurring defect — blocks of rows where `Your Price` ≥ `MSRP/SF`.** Biyork's sheet
  intermittently ships a block with the dealer column filled from the MSRP column, or higher.
  **Titan's real discount runs 33-57% of MSRP on every other line**, so the test is arithmetic,
  not judgement: compute `Your Price / MSRP` per price block and flag any block ≥ 1.0. Ingest as
  printed (Cost = `Your Price`) per flag-don't-block, tag in `Salesperson notes`, and confirm with
  the rep before the import.
  - **Jul 2025 list:** Hydrogen 8 plank ($ 6.63 vs MSRP $ 6.34) and Hydrogen 8 accessories
    (`Your Price` = MSRP exactly). **Both corrected on the May 22 2026 list** — H8 plank is now
    $ 3.22 (ratio 0.508) and its accessories $23.27 / $37.05.
  - **May 22 2026 list:** three fresh blocks, 30 flooring SKUs — Nouveau 6 Clic ($ 8.20 vs MSRP
    $ 7.89, ratio 1.039, against a stored cost of $ 4.12), Hydrogen 7 ($ 6.29 vs $ 5.71,
    ratio 1.102, stored $ 3.04) and Nouveau 7 Bespoke Plank + Herringbone ($14.65 = MSRP exactly,
    stored $ 7.84). Each is roughly double the stored cost with the MSRP unchanged — the
    signature of a mis-filled dealer column, not a real increase.
- **Biyork re-codes products without renaming them.** On the May 22 2026 list Hydrogen 6 Plank
  shortened `BYKHY6HP50xx` / `BYKRCEH50xx` → `BYKHY6Pxx`; Hydrogen 6 Tile changed Chalk `CH` → `CK`
  and moved Combed Cotton from `BYKHY6HT50CO` → `BYKRCET50CO`; the Hydrogen 6 Tile stairnose codes
  gained an `86` suffix. Tiers 1 and 2 both miss, so these resolve at **tier 3 (collection +
  colour)**. Mark them `MatchStatus: ambiguous` and have a human confirm — never let them fall
  through to `new`, which duplicates a live product in both Airtable and Lightspeed.
- **Multi-size groups under one header:** Nouveau 7 splits Hickory into Wirebrush vs Handscraped finishes (different finish, same price). Hydrogen 6 Plank had two size groups (7"×48" box 23.64 and 7"×60" box 23.25) on the Jul 2025 list; the May 22 2026 list collapses it to one 7" × 60" group at box 23.64. Create records for every sub-group with its specific box size/finish.
- **Tile lines inside vinyl collections:** Hydrogen PRO Tile and Hydrogen 6 Tile are vinyl tile (`LVT`), not porcelain — keep `Material type = SPC core`.
- **Nouveau 6 Clic** is engineered hardwood with a Uniclic float system → `Install profile = Click`, `Locking system = Uniclic`, thickness 1/2" (12.7mm).

#### Stock status & promo

Leave `Stock status` blank for all Biyork rows; set `Active = TRUE`. The regular pricelist carries no SALE/promo pricing — never populate `Promo cost ($/sf)` / `Promo end date` from a standard Biyork ingest. If a future list adds promos, fall back to the global promo logic.

#### LS name prefix — derived, NOT yet confirmed by Albert

`ls-upload-instructions` carries no Biyork brand-config row, so the 2026-09-09 run derived the
prefix from the documented convention (`[4-char supplier abbrev][3-char type abbrev]`):
`BIYKENG` / `BIYKLVP-SPC` / `BIYKLVT-SPC` / `BIYKLAM`, with mouldings on the spelled-out
`Biyork - Transition | …` / `Biyork - Sundry | …` accessory format.

**Confirm it against a Lightspeed product export before importing any Biyork LS file.** If the
live products carry a different prefix, the file renames every existing Biyork product on the
POS. The `id` is populated, so it is an update rather than a duplicate — but a visible rename of
~276 products is not something to discover after the fact. Record the confirmed prefix here and
in the LS skill's brand-config table.

#### Biyork ingest output format

Produce a CSV file with all 57 schema columns. File naming: `biyork_full_airtable_upload_[YYYY-MM-DD].csv` using the list date (e.g. 2025-07-07). Save to `/mnt/user-data/outputs/`. A full flooring + accessories ingest produces ~324 rows (154 flooring, 170 mouldings/accessories).


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
- Standard markup on flooring: `Retail = Cost + $ 1.00`.

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

`floordi_full_airtable_upload_[YYYY-MM-DD].csv` using the "Last updated" date on the list (e.g. 2025-09-03), all 57 schema columns, saved to `/mnt/user-data/outputs/`. Record the effective date in `Price list reference` when logging future price changes to Price History Log v2.

---

### Canadian Standard

Canadian Standard is a **distributor, not a brand** — Titan's first. One supplier
reselling eleven brands: its own house line plus BOEN, EGGER, Inhaus, SONO, Antikkwood,
Nestwood, Unikkwood, Handcraft, Brand Surfaces and Brand Coverings. The list arrives as
the "Product Guide", a multi-page PDF organised by brand and collection.

**Supplier is not brand here, and the distinction is load-bearing.** `Supplier` is
`Canadian Standard` on every row; `Brand` carries the actual maker. The Lightspeed name
prefix derives from the **supplier** (`CANSENG`, `CANSLVP-SPC`, …), never the brand — see
*Supplier, not brand, drives the name prefix* in the ls-upload-instructions skill.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Canadian Standard` |
| **Brand** | The actual maker, verbatim — `Canadian Standard`, `BOEN`, `EGGER`, `Inhaus`, `SONO`, `Antikkwood`, `Nestwood`, `Unikkwood`, `Handcraft`, `Brand Surfaces`, `Brand Coverings` |
| **SKU supplier code** | `CANS` — 4-char suffix |
| **Internal SKU format** | `[CAT]-CANS-####` — sequential, since the guide prints no per-product codes |
| **Supplier SKU** | Leave blank. The Product Guide carries no product codes, for flooring or trims. |

#### Cost column

**Canadian Standard prints ONE price, and it is Titan's cost per unit. There is no MSRP
and no multiplier.** (Confirmed by Albert, 2026-09-03 — the Aug 31 2026 Product Guide
prints a single unlabelled price, which was ambiguous on first ingest.)

- Printed price → `Cost/unit` **as-is**. Never apply a multiplier.
- `Retail = Cost + $ 1.00` — the schema default, unmodified.
- **Do not look for an MSRP column; there isn't one.** If a future guide ever prints a
  second price column, that is a format change: stop and re-confirm before ingesting.

Accessories keep the standard cross-supplier trim markup: T-Moulding / Reducer `Cost + $ 10`,
Stair Nose `Cost + $ 15`.

#### Promo convention

The guide prints paired **Promotion / Regular** prices under a printed validity window
("Promotion Valid until October 31, 2026"). `Cost/unit` = Regular, `Promo cost ($/sf)` =
Promotion, `Promo end date` = the printed date. The document as a whole is still a
`Regular List` — a catalogue containing a promo section is not a promo sheet.

#### Trims

Trims are listed per collection, but priced identically across the house lines
($18 T-Moulding/Reducer, $22 Stair Nose). **One SKU per physically distinct trim —
collection alone does not earn a SKU**; see the trim rule in ls-upload-instructions.
VANNTETT PLUS and VANNTETTPRO trims are the same part and are listed once.

#### Parsing quirks

- **`Origins` names two different programmes** on different pages with different specs.
  Keep the collection as printed and distinguish by species / width / finish.
- Species is often printed bare (`Oak`, no origin) — store verbatim, do not enrich.
- The guide contains supplier typos (`Amercian Hickory`); keep the corrected spelling in
  `Species` and note the source spelling.
- SONO and several other brands leave `Material type` unstated. Unlabelled rigid vinyl
  defaults to `SPC core` per the global rule — it is **not** a reason to emit `LVP` as a
  material.

---

### Dragona (Dragona Flooring, house brand Falcon Floors)

Dragona is a **new supplier** onboarded 2026-09-08 from the "Dragona Flooring Pricing
Program — Store Program" (Aug 1 2026), a 15-page PDF spanning flooring, tile, carpet,
underlayment, and building materials.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Dragona` |
| **Brand** | `Dragona` for its own lines; `Falcon Floors` for the house-brand laminate/vinyl |
| **SKU supplier code** | `DRAG` — 4-char suffix |
| **Internal SKU format** | `[CAT]-DRAG-####` — sequential, since the sheet prints no per-product codes for flooring |

#### Cost column

**CONFIRMED 2026-09-09 by Albert: STORE PRICING is Titan's dealer cost, as printed, no
multiplier.** The sheet prints exactly one price column, headed "STORE PRICING" — this
was genuinely ambiguous on first ingest (could have read as Dragona's own retail shelf
price) and was escalated via Tactical Task before any Lightspeed write. Do not ask again.

- Printed STORE PRICING → `Cost/unit` **as-is**. Never apply a multiplier.
- Where the sheet prints two tiers (flooring), CUT ORDER → `Cost/unit`, SKID ORDER →
  `Pallet price ($/sf)`, both tiers noted in `Volume pricing notes`.
- `Retail = Cost + $ 1.00` — the schema default — **except** where noted below under
  Parsing quirks; several pricing units have no markup rule yet and are intentionally
  left blank pending Albert (carpet per sqyd/per linear yard, per-linear-foot unfinished
  hardwood mouldings, per-piece stair parts and registers). Do not guess a markup for
  these; ask before writing one.

#### Parsing quirks

- **Rolls (underlayment) are converted to per-roll cost** from the printed per-SF price
  (e.g. $0.13/SF × 200 SF roll → $26.00/roll), so the +$20 underlayment markup applies on
  the same basis as other suppliers' roll pricing (Woden precedent).
- **Carpet is priced per SQYD (tile) or per linear YRD (roll on a 12 ft width)**, not per
  sf. `Cost/unit` holds the as-printed per-sqyd/per-linear-yard figure; `Box size (sf)`
  for carpet tile is converted from the printed SQYD box size. No carpet markup rule
  exists yet — `Retail price/unit` stays blank until Albert sets one.
- **Unfinished hardwood mouldings are priced per linear foot** on random-length stock;
  the standard +$10/+$15 per-piece accessory tiers do not transfer to a per-linear-foot
  cost — `Retail price/unit` stays blank until Albert sets a rule.
- **Hardwood/register stair parts are priced per piece**, not per sq ft — matches the FAW
  precedent for stair treads: store the per-piece cost, leave retail blank until a
  hardwood-stair markup is set.
- **Core construction is unstated for rigid vinyl** — defaults to SPC per the global
  rule. Underpad material is unstated — IXPE assumed; verify with Dragona if it matters.
- **Pro-7mm vinyl click prices below the standard 7mm line** despite an identical printed
  construction (5.5mm + 1.5mm condo pad, 18.9 sf/box) — flagged on the affected rows as a
  possible sheet error, not corrected.
- **Subway tile (3x6/4x12/4x16 white) is stored as Porcelain**, following the printed
  section header, though this format is normally ceramic wall tile — confirm with
  Dragona if it matters.
- Building materials (drywall, framing, insulation, doors, plumbing, lumber, MDF/pine
  millwork, tile edge, lighting, consumables) — roughly half the document — are **excluded**
  from the catalogue.

---

### Weiss

Weiss is a **new supplier** onboarded 2026-09-08/09 from the Weiss price list valid
from Aug 1 2026, covering engineered hardwood, vinyl plank, laminate, and accessories
(transitions, stairnoses, underlay rolls).

#### Cost column

**CONFIRMED 2026-09-10 by Albert: the list's single "Price / SF" column is Titan's
dealer cost, as printed, no multiplier.** This was the working assumption used during
extraction (62 rows) — it is now confirmed. Do not ask again.

- Printed "Price / SF" → `Cost/unit` **as-is**. Never apply a multiplier.
- Retail markup is category-specific, already applied per row and recorded in each
  record's `Salesperson notes`: vinyl stairboard sets use the FAW vinyl stair-step
  markup (+$20); stairnoses and most other per-piece accessories use the cross-supplier
  accessory markup (+$15); underlay rolls use the cross-supplier underlayment markup
  (+$20/roll). Flooring (engineered, vinyl plank, laminate) uses the schema default
  `Retail = Cost + $1.00` unless a row's notes say otherwise.
- Rigid vinyl core construction is unstated on the list; defaults to SPC per the global
  rule. Underpad material is unstated on the attached-pad vinyl lines; IXPE assumed —
  verify with Weiss if it matters.
- "Select Plus" (used on some Oak colourways) is Weiss's own grade wording, stored
  verbatim per the grade translation rule — it sits between Select and Select & Better
  on their sheet but is not formally mapped to either; confirm the equivalence with
  Weiss if it becomes load-bearing.

---

### Vizion (Vizion Floor)

Vizion Floor (toronto@vizionfloor.com, 647-802-6868, 1195 Clark Blvd, Brampton ON L6T 3W4
— vizionfloor.com) is both the supplier and the brand. The price list is a short
multi-page PDF (6 pages on the 2026/07/01 list) with a cover page, then one collection
per page: a header bar, a two-column item/colour table, a single spec block, a single
price, and a per-page accessory strip beneath. **First ingested 2026-09-09 from the
2026/07/01 list — 52 rows (41 flooring, 11 accessories). Not yet imported.**

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Vizion` — **does not exist in the Airtable select yet**; it is created on first import |
| **Brand** | `Vizion` (supplier is the brand; Marvelous and Epic are collection names, not brands) |
| **SKU supplier code** | `VIZN` — 4-char suffix. **Proposed on the first run, not yet confirmed by Albert.** |
| **Internal SKU format** | `[CAT]-VIZN-[Vizion code]` — the code used **verbatim** as the suffix, per the per-product unique-code pattern (like Biyork and Triforest). e.g. `LVP-VIZN-V7001`, `LAM-VIZN-LV321`, `LVP-VIZN-VL501`. |
| **Supplier SKU** | Always populated with the Vizion code on its own (`V7001`, `V8001`, `VL501`, `LV321`, `LV221`). Verified unique across the whole list. |

Accessories carry no codes → sequential `ACC-VIZN-0001`, `Supplier SKU` blank.

#### Cost column

**CONFIRMED 2026-09-10 by Albert: the printed price is Titan's dealer cost, as-is, no
multiplier.** The sheet prints exactly one unlabelled "> PRICE" column with no terms
page, no stated discount, and no MSRP column — genuinely ambiguous on first ingest
(precedent runs three ways across other suppliers), so it was escalated via Tactical
Task before any import. This was the working assumption used during extraction
(52 rows) — it is now confirmed. Do not ask again.

- Printed "> PRICE" → `Cost/unit` **as-is**. Never apply a multiplier.
- `Retail = Cost + $1.00` — the schema default, applied uniformly.
- Core construction is unstated for the vinyl lines; SPC assumed per the global rule
  for unlabelled rigid vinyl.
- SKU supplier code: `VIZN` — Vizion's own product codes are unique per product and are
  used verbatim as the 4-char suffix (e.g. `LVP-VIZN-V7001`).
- Stair/accessory items are priced per piece (Stair Board per set); dimensions as
  printed go in the accessory name's `[Dimensions]` segment per the transitions format.

#### Markup overrides (accessories)

Accessories are per piece (stair boards per set). Standard cross-supplier markups:
Reducer and T-Moulding `Cost + $10`; any nosing `Cost + $15`. **Stair Board sets have no
dedicated standard** — the Stair Nose/Tread `+$15` rule was applied as the closest match,
the same call made for the Woden square-return set; confirm with Albert.

#### Scope of ingest

In scope: **LVP** (Marvelous 7MM, 8MM, and 5MM Loose Lay) and **LAM** (Epic 120 HR at
both thicknesses), plus their trims.

**Out of scope: Adhesive Zeromono 2GL (12KG pail, $68.00/pail, p.4)** — excluded as a
jobsite consumable, matching how Biyork and Olympia adhesives are treated. Flagged to
Albert; revisit if he wants consumables catalogued.

#### Collections

Use verbatim: `Marvelous 7MM Luxury Vinyl`, `Marvelous 8MM Luxury Vinyl`,
`Marvelous 5MM Loose Lay`.

**The two laminate groups print the identical collection name at different specs**, so
the thickness is appended to disambiguate (the Evergreen precedent for tier-named
collections): `Epic 120 HR Water Resistant Laminate With Underlayment (14.3mm)` and
`... (12.3mm)`. Their colour sets are disjoint (Whistler/Aspen/… vs Nile/Yangtze/…), so
nothing collides beyond the name itself.

| Collection | Spec | Box | Boxes/pallet | Printed price |
|---|---|---|---|---|
| Marvelous 7MM Luxury Vinyl | 7.2" × 60.8" × 7mm | 24.35 sf | 50 | $ 1.69 |
| Marvelous 8MM Luxury Vinyl | 7.2" × 60.8" × 8mm | 21.31 sf | 45 | $ 1.89 |
| Marvelous 5MM Loose Lay | 9.14" × 60.32" × 5mm | 30.61 sf | 40 | $ 2.39 |
| Epic 120 HR … (14.3mm) | 7.7" × 60.8" × 14.3mm | 19.28 sf | 55 | $ 1.89 |
| Epic 120 HR … (12.3mm) | 7.7" × 48" × 12.3mm | 20.48 sf | 50 | $ 1.69 |

#### Category / Material type mapping

- **Marvelous 7MM / 8MM** → `LVP`. **The core is never stated** — `SPC core` assumed per
  the global rule for unlabelled rigid vinyl. Re-confirm if a future line looks flexible
  or glue-down.
- **Marvelous 5MM Loose Lay** → `LVP` + `Loose-lay vinyl`, `Install profile` and
  `Install method` = `Loose lay` (stated). Do **not** collapse this to `SPC core`.
- **Epic 120 HR** → `Laminate` + `Water-Resistant Core`. `Waterproof = FALSE` — 120 HR
  water-*resistant* is not waterproof (the Purelux Betten / Evergreen distinction).
  "With Underlayment" is in the collection name → `Underpad included = TRUE`,
  `Underpad type` blank (material not stated), exactly as FAW's Waterproof Laminate Pro.

#### LS Handle format

Brand-first, alphanumeric only, colour never truncated:
`VIZN[LVP7|LVP8|LVPLL5|LAM143|LAM123][COLOUR]` — e.g. `VIZNLVP7ACADIA`,
`VIZNLAM143WHISTLER`. Accessories append the printed dimensions, because two vinyl
nosings differ **only** by size and collide otherwise:
`VIZNACC[TYPE][MATERIAL][DIMS]`.

Note `Revelstoke` appears twice on the list — as `VL501` (5mm loose lay) and `LV330`
(14.3mm laminate). Different products; the category token keeps the handles apart.

#### Fields Vizion does not provide

**Wear layer, AC rating, install profile and locking system (except Loose Lay), veneer,
species, grade, finish type, colour/tone, IIC/STC, certifications, warranty, pieces per
box, trim material.** None appear anywhere in the document — leave all blank. Spec
coverage is thin; request a full spec sheet from the rep if Bert lookups need it.

Provides: item code, colour name, plank size (W × L × T), sf/box, boxes/pallet, one
price per collection, and accessory dimensions.

#### Known soft spots

- **Laminate Reducer and T-Moulding are printed twice at conflicting prices** —
  $ 8.00/pc in the 14.3mm section (p.5) and $12.00/pc in the 12.3mm section (p.6), with
  **identical dimensions** (`15 × 45 × 2400 mm` and `12 × 45 × 2400 mm`). Either the
  dimension string is reused sloppily across two real parts, or one price is a typo.
  The first run kept **both rows** so neither price is lost — merge to one SKU if Vizion
  confirms one part. The Stair Board is printed in both sections at the same $28.00 and
  is correctly one row.
- **One price per collection, not per row.** The price token sits vertically centred
  beside the colour block, so a naive row-wise parse will orphan it. Verified
  positionally on the first run.
- **The vinyl accessory strip repeats identically** under both the 7MM and 8MM sections
  at the same prices — one SKU each, not two (the Canadian Standard trim rule).
- **Colour names are place names** (Acadia, Banff, Whistler, Nile…) and carry no tone
  information — `Colour / tone` stays blank.

#### Vizion ingest output format

`vizion_airtable_upload_[YYYY-MM-DD].csv`, all 57 schema columns (plus helper columns
58–59 on a routine run), written to `ingest/YYYY-MM-DD/`. **No Lightspeed file until the
Airtable import happens** — Vizion has no LS presence, so there are no ids or handles to
copy from.

---

### Lee Flooring (Lee Flooring Canada)

Lee Flooring Canada (145 Gibson Dr, Markham ON L3R 3K7 — 289-378-8888 —
info@leeflooring.ca) is both the supplier and the brand. The price list arrives as a
**multi-tab `.xlsx`, not a PDF** — four tabs (`LANINATE `, `VINYL`, `ENG WOOD`,
`SOILD & 3mm`; the typos are Lee's and the laminate tab name has a trailing space).
First ingested 2026-09-09 from the 2026-06-12 list: 84 rows (79 flooring, 5 accessories).

#### Cost column

**Settled by Albert 2026-09-09. Do not ask again.**

Lee prints **exactly one price column, headed `PRICE/SQ.FT`** (column G on every tab;
there is nothing beyond column G). **That printed price IS Titan's dealer cost — take it
as-is, no multiplier** — and `Retail = Cost + $ 1.00`, the schema default.

| | |
|---|---|
| `Cost/unit` | the printed `PRICE/SQ.FT`, verbatim |
| `Retail price/unit` | `Cost + $ 1.00` (flooring); accessories per the cross-supplier markups below |
| `MAP price ($/sf)` | **blank — Lee publishes no MSRP or suggested-retail column at all** |
| `Pallet price ($/sf)` | blank — Lee gives a boxes-per-skid *count*, not a per-sf pallet rate |

There is **no terms page and no discount off list** anywhere in the workbook; the only
commercial terms printed are a 30-day return window, a 25% restocking fee, and "All
Promoted Orders are Final Sales and COD." So Lee is the Canadian Standard shape (dealer
cost printed directly), **not** the CIF/Olympia shape (list price with the discount in
the terms). If a future Lee list ever prints a second price column, that is a format
change — stop and re-confirm rather than assuming which is cost.

The price cell carries its own label: `SALE: $ 1.39`, `PRICE: $ 2.99`, or a bare `1.19`.
**`PRICE:` is just a label on the regular cost — it is not a promo marker.** Only `SALE:`
means promo.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Lee Flooring` — **proposed on the first run, not yet confirmed**; the option does not exist in Airtable yet |
| **Brand** | `Lee Flooring` (supplier is the brand) |
| **SKU supplier code** | `LEEF` — **proposed, not yet confirmed** |
| **Notion `Company`** | `LEE` (ALL CAPS, per the per-system casing rule — do not "fix" either side) |

**Lee assigns product codes on laminate only.** `T01`–`T10` (72-hour), `R01`–`R09`+`R11`
(24-hour) and `98001`–`98013` (SOHO) are unique across the whole list; vinyl, engineered,
solid and accessories carry no codes at all. The first run therefore used the code
verbatim as the SKU suffix on laminate (`LAM-LEEF-T01`) and sequential numbering
elsewhere (`LVP-LEEF-0001`, `ENG-LEEF-0001`, `HWD-LEEF-0001`, `ACC-LEEF-0001`), with
`Supplier SKU` populated on laminate and blank everywhere else. **That split is proposed,
not confirmed — settle it before the first import, because RULE 0 makes it permanent.**

#### Lee is already in Lightspeed

**36 Lee products were live in Lightspeed before Lee existed in Airtable** — the RULE 0a
third state. A Lee ingest is therefore `MatchStatus: new` on every row (it creates
Airtable records) while a large share also carry a `Lightspeed ID` and must **update**
rather than create on the POS. Always run `ls-id-backfill` against an LS export before
building any Lee LS file.

**Lee's LS skus are its own product codes**, so the laminate rows join exactly on
`Supplier SKU` ↔ LS `sku` (`98001`, `T01`…). That is a stronger bridge than colour
matching and should be tried first for Lee. The legacy LS names are inconsistent
(`LEE ENG - Color: BRENTON`, `LEEENG - 7' 3mm Veneer - Hickory (Barnwood)`,
`LEELAM - 7 Series - ()`), and the LS catalogue predates the current list, so expect
cost and width to disagree — the price list is authoritative.

Two known duplicates to clean up in Lightspeed: `LEE.T03` duplicates `T03`, and
`LEE.E.H.Bar.7` (Barnwood 7" / 26.2 sf) is superseded by `11237` (6.5" / 27.5 sf).

#### Collections (use verbatim)

Laminate: `72 Hours Water-Resistant Laminate`, `24 Hours Water-Resistant Laminate`,
`SOHO Laminate`. Vinyl: `7mm SPC`. Engineered: `Heritage Hills` (American Oak),
`Solvara` (European Oak), `Hybrid`, `3mm Veneer Engineered`. Solid: `Solid Handscraped`.

#### Category / Material type

| Section | Category | Material type |
|---|---|---|
| 72HR / 24HR laminate | `Laminate` | `Water-Resistant Core` |
| SOHO laminate | `Laminate` | `HDF core` (no water-resistance claimed) |
| 7mm SPC | `LVP` | `SPC core` |
| Heritage Hills / Solvara / Hybrid / 3mm Veneer | `Engineered hardwood` | `Hardwood plywood` |
| Solid Handscraped | `Solid hardwood` | *(blank)* |

`Waterproof = TRUE` on the SPC only — the laminates are water-**resistant**, not
waterproof. `Pet friendly = TRUE` on the SPC (22 mil ≥ 20). `Radiant heat compatible`
blank throughout; Lee states nothing.

#### Grade

`SELECT & BETTER` (Heritage Hills) → `Select & Better`; `SELECT GRADE` (Solvara) →
`Select`. Nothing else states a grade — Hybrid, vinyl and laminate stay blank.
**`HANDSCRAPED` on the solid tab is a finish, not a grade** — `Grade` blank,
`Finish type = Hand scraped`.

#### Parsing quirks — the workbook is merge-driven

**Read the merged-cell ranges; do not forward-fill by eye.** Lee states dimensions,
sf/box, packaging and price **once per group** and merges the cell down the rows it
covers, and the group boundaries **do not line up between columns**. On the 72HR tab
`E8:E13` (sf/box 20.8) and `F13:F17` (40 boxes/skid) split one row apart, so `T06` is
20.8 sf at 40/skid — correct, and invisible to a naive fill.

- **Multi-spec groups under one header.** Hybrid runs 7¾"/20.97 sf, 7¾"/23.98 sf and
  9½"/26.08 sf under a single heading, with the price merged across a different span again.
- **Sequence gaps are real**: `R10` and `98010` are absent, and the accessory rows
  contradict themselves about the range (`R01-R10` vs `R01-R11`). Extract what is printed.
- **`WARM EMBER (WALNUT)`** sits inside the American Oak collection at $ 4.49 against
  $ 2.99 — set `Species = Walnut`. Confirm whether it is American Black Walnut; if so
  `Radiant heat compatible = FALSE` per the global rule.
- **Length** is in the description, not the dimension string: `UP TO 6 FOOT` →
  `RL (up to 6')`, `UP TO 4 FOOT` → `RL (up to 4')`. Laminate and vinyl are a fixed `48"`.
- **`5 + 2 MM EVA`** on the vinyl = 5mm SPC + 2mm EVA pad, 7mm total, `Underpad
  included = TRUE`, `Underpad type = EVA` (Lee names the material, so no assumption).
  The tab header's `ICC 74` is a typo for `IIC 74`.

#### Fields Lee does not provide

Install profile, install method, locking system, AC rating, certifications, warranties,
traffic rating, pieces per box, colour/tone, veneer cut type, and STC. Leave all blank —
`Click`/`Float` was assumed on laminate and vinyl per the Evergreen precedent and left
blank on all 48 hardwood rows. Request a spec sheet from the rep if Bert lookups need them.

#### SALE items

Lee marks promos as `SALE:` in the price cell and **prints no end dates** — apply the
global month-end default (the list's own month), and note that a Lee list can arrive
months stale, in which case its promos are already expired on receipt.

Both laminate collections are wholly on sale with no regular price printed anywhere, so
they fall to **Sale rule 3** (`Cost = Promo = SALE price`, a placeholder). Hybrid is the
instructive one: it prints three regular colours at $ 2.99 and seven at `SALE: $ 2.55`
across two widths. The four 7¾" sale colours share specs exactly with the regular 7¾"
Chicago, so **rule 1** applies (`Cost` $ 2.99, `Promo` $ 2.55); the three 9½" colours have
no same-spec regular price and fall to **rule 3**. Match specs, not just the collection.

#### Accessories

Priced per piece / per roll on the laminate tab. Standard cross-supplier markups:
T-Moulding and Reducer `Cost + $10`, Stair Nosing `Cost + $15`, Underlayment `Cost + $20`.
Lee gives no trim material or profile detail beyond the matching-colour list.

#### Lee ingest output format

`lee_airtable_upload_[YYYY-MM-DD].csv`, all 57 schema columns plus helpers, written to
`ingest/YYYY-MM-DD/`. No Lightspeed file until the Airtable import happens and LS ids are
reconciled in — see *Lee is already in Lightspeed* above.

---

### Gracious (trading as "Amazing Flooring")

Gracious is both the supplier and the brand. Contact on file is `sammygracious18@gmail.com`;
the price lists arrive as a set of untitled "Fwd: PRICE LIST" emails, one PDF per range
rather than one combined book. **First ingested 2026-09-09 from three PDFs emailed
2026-06-30 — 248 rows (244 tile, 4 vinyl/laminate). Not yet imported.**

**Amazing = Gracious** (Albert, 2026-09-09). The vinyl/laminate sheet's own header reads
`AMAZING FLOORING`; the supplier of record is `Gracious`. Whether *Amazing* is a distinct
**brand** on that range is still open — the first run set `Brand = Gracious` on every row
and flagged it.

#### Identity

| Field | Value |
|---|---|
| **Supplier** (single-select) | `Gracious` — **does not exist in the Airtable select yet**; created on first import |
| **Brand** | `Gracious` — **unconfirmed on the vinyl/laminate range**, whose sheet is headed `AMAZING FLOORING` |
| **SKU supplier code** | `GRAC` — 4-char suffix. **Proposed on the first run, not yet confirmed by Albert.** |
| **Internal SKU format** | Sequential per category: `TIL-GRAC-####`, `LVP-GRAC-####`, `LAM-GRAC-####`. Gracious publishes no product codes on the tile lists — the "names" there (`EUT-33`, `AWT-01`, `TOPGL-005`) are colour identifiers within a range, not standalone product codes. |
| **Supplier SKU** | Leave blank. See above — do not promote a colour identifier to a product code. |
| **Notion `Company`** | `GRACIOUS` (ALL CAPS, already an option) |

#### Cost column

**SETTLED (Albert, 2026-09-09): the single printed price is Titan's dealer cost. No
multiplier, on any of the three ranges.**

The vinyl/laminate sheet heads its price column **`STORE PRICE`** and Albert's ruling
was literally *"Store Price is Dealer Cost"*. The two tile sheets print one price column
with no usable header at all (`Column2`, or nothing), and the same basis applies.

- Printed price → `Cost/unit` **as-is**.
- **No MSRP, no suggested-retail, no list price and no terms page anywhere in the three
  documents.** `MAP price ($/sf)` stays blank. That absence is a finding, not an
  omission — do not go hunting for a second column on the next list. If one ever
  appears, that is a format change: stop and re-confirm.
- `Pallet price ($/sf)` blank — no pallet rate is printed.

#### Markup — the tile tier is OPEN

Flooring takes the schema default `Retail = Cost + $ 1.00`, applied on the vinyl and
laminate rows.

**The tile rows also carry `Cost + $ 1.00`, and that is the unconfirmed part.** Both
other tile suppliers in the base run a supplier-specific tier (CIF `+$ 2.00` field tile /
`+$ 5.00` mosaic; Olympia the same), and both subsections say explicitly that those
overrides do **not** generalize. So the default was applied rather than a borrowed tier —
but on a $ 1.29/sf tile a flat +$ 1.00 is a very different business than +$ 2.00, and
Albert has not ruled. **Escalated 2026-09-09; replace this block with the settled tier
when he answers.**

No accessories, trims or consumables appear on any of the three sheets, so the
cross-supplier accessory markups do not come into play yet.

#### Scope of ingest

Everything the three sheets contain: **TIL** (porcelain/ceramic field tile) and **LVP** +
**LAM**. There are no mosaics, no stone, no trims and no adhesives on the current lists.

#### Collections

The tile sheets have almost no series naming — the section headers are mostly a size and
a finish. Collections were therefore kept minimal so that **size variants of one colour
group under a single LS handle** (the CIF convention):

| Sheet | Printed section header | Collection |
|---|---|---|
| Tiles (named colours) | `TILES - 12*24` / `TILES - (24*24 POLISHED)` / `TILES - (24*48 POLISHED)` | `Tiles` |
| " | `TILES 24*24 - ITALIAN SERIES(GLOSSY)` / `TILES 24*48 - ITALIAN SERIES(GLOSSY)` | `Italian Series` |
| " | `TILES 24*48 - DESIGNER SERIES` | `Designer Series` |
| Tiles (coded colours) | `TILES 24*24 -` / `TILES - (24*48 POLISHED CHINA)` / `MATTE FINISH 248*48` | `Tiles` |
| Vinyl / laminate | `CS/DE SERIES 6.8MM`, `GS SERIES 7.8MM`, `NP SERIES 8.6MM` | `KS/DE Series`, `GS Series`, `NP Series` |
| " | `WATERPROOF LAMINIATE 8mm+3.5mm` | `Waterproof Laminate 72HR` |

**The size stays out of the collection name deliberately** — it lives in the `Size`
segment of `Product name` and in `Width (in)` / `Length`, which is what lets one colour
carry several sizes as LS variants.

#### Product name

Tile follows the CIF four-segment em-dash contract verbatim — **including the redundant
colour segment**, since breaking it silently produces blank LS variant sizes:

```
[Collection] — [Colour] — [Size] ([Finish])
```

e.g. `Tiles — Amaretto Grey Matt — 12 x 24 (Matte)`, `Italian Series — VSK-02 Matt — 24 x 48 (Matte)`.
The finish parenthetical is dropped only where neither the row nor its section states one.

Vinyl and laminate have **no colours at all** on the sheet, so each series is one record:
`Gracious 6.8mm KS/DE Series SPC Vinyl`, `Gracious 11.5mm Waterproof Laminate 9.37" (72HR)`.

#### LS Handle format

`GRAC` + alnum(Collection) + alnum(Colour) + alnum(Finish), uppercase, **colour never
truncated** (the CIF/Olympia rule — truncation collides `TOPGL-003` with `TOPGL-004`).
e.g. `GRACTILESAMARETTOGREYMATTMATTE`, `GRACITALIANSERIESVSK02MATTMATTE`, `GRACLVPKSDESERIES`.

Finish is part of the handle, so the same colour code at a stated finish and at an unknown
one lands in two groups — see the truncated-header quirk below.

#### Category / Material type

- **Tile** → `Tile / Stone`. **`Material type` is left BLANK on all 244 tile rows** — the
  lists never say porcelain or ceramic, and neither does any header. Do not infer it from
  the format; large-format polished is *probably* porcelain and probably is not good
  enough. `Tile format` also blank (defaults to floor); no mosaics on these lists.
- **KS/DE, GS, NP series** → `LVP` + `SPC core`. The sheet does not name the core;
  `SPC core` is the global default for unlabelled rigid vinyl. `Waterproof = TRUE`.
- **Waterproof Laminate 72HR** → `Laminate` + `Water-Resistant Core`, `Waterproof = TRUE`
  per the Triforest precedent for hour-rated waterproof laminate (72HR/120HR). Note this
  differs from Purelux Betten and Vizion Epic, which are printed as *water-resistant* and
  are FALSE.

#### Vinyl thickness is core + pad + wear layer

The series headline thickness reconciles only when the wear layer is included, which is
worth knowing before anyone "corrects" it:

| Series | Printed composition | Headline | Check |
|---|---|---|---|
| KS/DE | `5+1.5mm` core+pad, `0.3` / 12 mil wear | 6.8mm | 5 + 1.5 + 0.3 = 6.8 ✓ |
| GS | `5.5+2mm`, `0.3` / 12 mil | 7.8mm | 5.5 + 2 + 0.3 = 7.8 ✓ |
| NP | `6+2mm`, `0.5` / 20 mil | 8.6mm | 6 + 2 + 0.5 = 8.5 — 0.1mm unaccounted for |

Store the headline value. Attached pad is present on all three (`Underpad included = TRUE`)
but **never named — `IXPE` assumed** per the global SPC default; flag it. The laminate's
3.5mm pad is left with a blank `Underpad type`.

`Pet friendly` follows the global ≥ 20 mil rule: FALSE on KS/DE and GS (12 mil), TRUE on NP.

#### Fields Gracious does not provide

**Tile:** material type, thickness, box size, pieces per box, sf/piece, country of origin,
certifications, warranty, IIC/STC, traffic rating, slip rating, suitability of any kind.
The tile sheets are literally two columns — a name and a price.

**Vinyl / laminate:** colour names, colour codes, plank width and length (except the
laminate's `1515*238`), locking system, install profile, certifications, warranty,
IIC/STC, radiant heat.

Provides: colour identifier, price, and — on the vinyl/laminate sheet only — sf/box,
thickness composition, wear layer, and the EIR/embossed finish.

#### Parsing quirks / known soft spots

- **Blank name cells beside a real price.** Four rows across the two tile sheets have an
  empty name cell with a price ($ 1.69 ×2 and $ 2.19 on the named sheet, $ 1.89 on the
  coded sheet). They are genuinely empty in the source, not an extraction dropout —
  verified against `extract_tables()`. Dropped and flagged; ask the rep what belongs there.
- **A price on the `NAME` header row.** On the Designer Series page the column header
  carries `$ 2.19`. It is a header, not a product — drop it.
- **`TILES 24*24 -` is truncated in the source**, ending at the dash with no series name
  and no finish. Those rows therefore carry a blank `Finish type`, which puts the same
  colour code in a different LS handle group from its 24*48 twin (`EUT-33/34/35/47`,
  `AWT-01/02/03`). Blank is the honest value — the section demonstrably mixes finishes
  (`GL-005` glossy sits beside `GL-008 MATT`) — but confirm the finish before an LS upload.
- **`MATTE FINISH 248*48`** — read as a typo for `24*48`; the $ 1.89 prices match the
  24*48 group exactly.
- **Sizes stated per row override the section size.** `EUT-02 12*24` inside the 24*24
  section, `TOPGL-003 32*32`, `AWT 24*24-01`. Strip the size out of the colour token —
  `AWT 24*24-01` becomes colour `AWT-01` at size `24 x 24`, not `AWT -01`.
- **`(SUGAR FINISH)`** is a finish, not part of the colour — moves to `Finish type = Sugar`.
- **Duplicate rows.** `UNICORN 5 GL` is printed twice at $ 1.39 in the same 24*24 section.
  Deduped to one record.
- **Suspected source typos, kept verbatim** (escalate, never silently edit): `IM6482D`
  where every sibling is `JX`/`JM`/`JBM`-prefixed; `JM10482D-36` in a `-36` group that
  otherwise mirrors the 24*24 codes; `CS/DE SERIES` in a header whose product row says
  `KS/DE SERIES`; `WATERPROOF LAMINIATE`; `pianted` for painted; `syco` for sync.
- **Colour casing.** The sheets are ALL CAPS. Title-case only words of 4+ letters —
  short all-caps tokens are abbreviations (`SS 3633`, `XL Grey`, `Thasos White POL`,
  `Atlanta WT`, `Unicorn 5 GL`) and anything containing a digit is a code, both left
  exactly as printed.
- **No effective date anywhere on any of the three PDFs.** Use the email date
  (2026-06-30 on the first set) as `Last price update`, and record it in
  `Price list reference` when logging to Price History Log v2.

#### Stock status & promo

Leave `Stock status` blank; `Active = TRUE`. None of the three sheets carries SALE,
promo, clearance or expiry language, and there is no second price column — all three rows
are `Regular List`. Never populate `Promo cost ($/sf)` / `Promo end date` from these
lists; if a future one adds promos, fall back to the global promo logic.

#### Gracious ingest output format

One file per emailed PDF, since each arrives on its own Notion row — all 57 schema columns
plus helper columns 58–59, written to `ingest/YYYY-MM-DD/`:
`gracious_tiles_named_airtable_upload_[YYYY-MM-DD].csv`,
`gracious_tiles_coded_airtable_upload_[YYYY-MM-DD].csv`,
`gracious_vinyl_laminate_airtable_upload_[YYYY-MM-DD].csv`.

**No Lightspeed file until the Airtable import happens** — the LS `id`/`handle`/`sku` columns
are copied from the Airtable state, and no Gracious record exists in the catalogue yet. But that
is a statement about *Airtable*, not about Lightspeed — see below.

#### Gracious IS already live in Lightspeed — the third state

> **Corrected 2026-09-09**, same day, from a `GRACIOUS` LS product export Albert supplied.
> The first run concluded "Gracious has no Lightspeed presence" by inferring it from the
> **absence of Gracious records in Airtable**. That inference was wrong. **Lightspeed holds
> 207 Gracious products** — 110 tile, 42 laminate, 39 vinyl, plus shower niches, wall panels
> and two hardwood lines.

This is exactly the **third state** documented under RULE 0a: *new to Airtable, already live in
Lightspeed* (the Canadian Standard pattern, 292 of 336 rows). Such rows are legitimately
`MatchStatus: new` **and** carry a `Lightspeed ID`.

**The general lesson: an empty catalogue query tells you nothing about Lightspeed.** The two
systems are populated independently, and a supplier that has been selling for years can be
absent from Airtable and fully present in the POS. Ask for an LS export before declaring a
supplier LS-absent.

**LS name format for Gracious** — worth knowing, because it carries facts the price lists don't:

```
[(P) ]GRACTIL -  - [Porcelain|Ceramic] ([Colour][ (Finish)])  | #[code] |  - [1224|2424|2448] - pc/b - [N]sf/b
GRACLAM - [Series] -  ([Colour])  | #[code] | AC[N] - [L]x[W]x[T]mm ([W]") - [N]sf/b
GRACVIN -  -  ()  | #[code] | SPC - [T]mm x [L]" x [W]" - [N]sf/b
```

- Name prefixes: `GRACTIL` / `GRACLAM` / `GRACVIN` / `GRAENG-`. A leading **`(P)` marks a
  promo row**, not a colour — skip it when parsing.
- **The LS name is the authority for `Material type`** (`Porcelain` vs `Ceramic`), which the
  price lists never state. The 2026-09-09 backfill filled it on all 35 matched rows (all
  Porcelain) from this field.
- Size is the bare `1224` / `2424` / `2448` token — map to `12 x 24` / `24 x 24` / `24 x 48`.
- LS tile colours carry their own spelling: `Satuvario` (vs the list's `Satvario`),
  `Antartica Ice`, `Diana Antic Light` (vs `Diana Antique Light`), `Marquiry`. Match through
  the drift; **never "correct" either side**.

**Backfill matching** — the bridge is **colour + size**, never SKU (LS SKUs are `20026`,
`GRA.T.P.RodBia.1224`, `5012` — a different namespace from `TIL-GRAC-####`):

- Strip the finish token from both sides before comparing (`Unicorn 5 GL` ↔ `Unicorn 5 Glossy`),
  then use finish only as a confirming detail.
- **Digits inside a colour token are identity and must be identical for a spelling-drift
  match.** `Unicorn 3` and `Unicorn 5` are one edit apart and are different products; so are
  `Tropical Grey` and `Tropical Grey 2`. A drift matcher without this rule silently collapses
  them — it did, on the first pass of the 2026-09-09 backfill, and produced a false contention
  for one UUID.
- A **size mismatch disqualifies** a tile candidate outright: the same colour genuinely exists
  at several sizes as separate LS products, and the right one for that size usually also exists.
- **Cost disagreement is expected and is not a conflict worth blocking on.** Every matched row
  showed the new list *below* the LS supply price ($1.29 vs $1.39, $1.39 vs $1.49, $1.69 vs
  $2.29) — that is the price drop the list exists to deliver. Flag it in the note; it actually
  confirms the match direction.

**The SPC colour range is in Lightspeed** — this answers the open question the first run raised.
LS carries the vinyl as individual colour SKUs where the price sheet gives only a series:
`KS-01`…`KS-13` + `KS-20`, `GS-01`…`GS-13` + `GS-20`, `TS01`…`TS10` (a series not on the new
list), and a single `Vinyl Code NP8-13 | 8.6mm`. **So the three series-level Airtable records
are the wrong shape** — each should become per-colour records keyed on those LS codes, after
which the backfill resolves them one-to-one. Until then they stay `NOT_FOUND` with a blank
`Lightspeed ID`; one record cannot hold fourteen UUIDs.

---

### New supplier onboarding — checklist

When a new supplier is added, gather this information before processing their first price list, and add a subsection above following the FAW template:

1. **Supplier name** (exact string for Airtable single-select)
2. **Brand(s)** — is the supplier also the brand, or do they distribute multiple brands?
3. **4-char SKU suffix** (e.g. FAWK, VIDR, GRAN)
4. **Cost basis — apply the default, flag if the sheet is ambiguous.** The printed
   price is the cost and `Retail = Cost + $ 1.00` unless the sheet gives you more than
   one candidate cost column or a number whose role is not stated — then flag it,
   naming the columns and which one you took. See *Cost basis — default to the printed
   price, flag the exceptions* at the top of this section, and **write what you applied
   into the new subsection under `#### Cost column`** so the next run inherits it rather
   than re-deriving it.
5. **Does the supplier assign product codes?** If yes, populate Supplier SKU. If no, leave blank.
6. **Categories in scope** (ENG, LVP, LVT, HWD, LAM, TIL, CAR, ACC)
7. **Markup overrides** — any category where `Retail = Cost + $ 1` doesn't apply (e.g. stair products, accessories, clearance)
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

- **2026-09-09** — **"Gracious has no Lightspeed presence" was wrong, and the way it was
  reached is the reusable lesson.** The first Gracious run queried the Master Flooring
  Catalogue, found no Gracious records, and inferred from that empty result that the supplier
  was absent from Lightspeed too. An LS product export Albert supplied the same day shows
  **207 live Gracious products**. Airtable and Lightspeed are populated independently — an
  empty catalogue query is evidence about Airtable only, and a supplier selling for years can
  be absent from one and complete in the other. **Ask for an LS export before declaring a
  supplier LS-absent.** The backfill that followed matched 35 of 248 rows on colour + size and
  also recovered `Material type` (Porcelain) for those rows from the LS name, a field the price
  lists never state. Recorded in the Gracious subsection: the LS name format, the `(P)` promo
  prefix, the LS-side colour spellings, and the rule that **digits inside a colour token are
  identity and may not change across a spelling-drift match** — without it `Unicorn 3` and
  `Unicorn 5` collapse into one product, which they did on the first pass.

- **2026-09-09** — Added the **Gracious** supplier subsection from three PDFs emailed
  2026-06-30 (248 rows: 156 + 88 tile, 4 vinyl/laminate; first ingest, not yet imported).
  Its `#### Cost column` is **settled on arrival** — Albert supplied the basis with the
  request (*"Store Price is Dealer Cost"*, and *Amazing = Gracious as the supplier*), so
  the one question that normally blocks a new supplier never had to be asked. What is
  **open** instead is the **tile markup tier**: `Retail = Cost + $ 1.00` (the global
  default) was applied, deliberately *not* the CIF/Olympia `+$ 2.00` field-tile tier,
  because both of those subsections state their overrides do not generalize — but a flat
  `+$ 1.00` on a $ 1.29/sf tile is a materially different business and Albert has not
  ruled. Also open: whether *Amazing* is a distinct `Brand` on the vinyl/laminate range.
  Recorded from the run: the tile sheets are two columns wide (name + price) and state no
  material, so `Material type` is blank on all 244 tile rows rather than inferred; four
  rows have a genuinely empty name cell beside a real price and were dropped; and the
  vinyl series' headline thickness only reconciles once the wear layer is added to the
  core+pad figure.
- **2026-09-09** — **Lee Flooring onboarded, and its cost basis settled on the first
  run.** Albert confirmed the printed `PRICE/SQ.FT` is Titan's dealer cost as-is, no
  multiplier, `Retail = Cost + $ 1.00`, and that Lee publishes no MSRP — recorded under
  Lee's `#### Cost column` so it is never asked again. Two things this supplier teaches
  that generalize: (1) a price list can arrive as a **multi-tab .xlsx** whose specs are
  **merged-cell groups that do not align between columns**, so the merge ranges must be
  read rather than forward-filled by eye; (2) a supplier can be **absent from Airtable
  while already live in Lightspeed** — 36 Lee products were — which is RULE 0a's third
  state and means `ls-id-backfill` must run before any LS file is built. Lee's LS skus
  are its own product codes, so laminate joins exactly on `Supplier SKU` ↔ LS `sku`,
  a stronger bridge than colour matching. Supplier option `Lee Flooring`, suffix `LEEF`
  and the laminate-code-as-SKU-suffix split remain **proposed, not confirmed**.

- **2026-09-09** — **Price Lists status option names corrected against the live data
  source.** The documented values `Extracted [Pending Review]`, `Error: Needs attention`
  and a bare `Done` do not exist; the real ones are `Extracted [Needs Review]`,
  `Extracted [Error]` and `Extracted [All Uploaded]`, and the write key is
  `Extraction Status`, not `Status`. Because a status property rejects an unknown option
  and takes the whole `update_properties` call down with it, every run following the old
  names would have lost its entire state write — the same failure mode as the renamed
  properties above. Fixed here, in `.claude/commands/process-price-list.md`, and in both
  `methods/pricelist-*.md`. Also recorded: the three downstream states
  (`Extracted [Ready to Upload]`, `Extracted [All Uploaded]`, `Not Needed`) belong to the
  reviewer, never to a run. Found on the Biyork 2026-09-09 run.
- **2026-09-09** — Added the **Vizion** supplier subsection from the 2026/07/01 list
  (52 rows, first ingest, not yet imported). Its `#### Cost column` is deliberately
  **open**: the sheet prints one unlabelled price column with no terms page and no MSRP,
  so the basis was escalated to Albert rather than inferred, under the blocking rule in
  force at the time (superseded 2026-09-10 — a sheet like this now takes the printed
  price as cost and is flagged, not held).
  Found independently on the Vizion run, alongside the status-name defect above.
- **2026-09-08** — **Promo/new-product matching strengthened.** "Promo product not
  found in catalogue" now requires checking the live base for a same-colour+width+
  species(+veneer) sibling, or a uniform width+species collection default, before
  treating a promo line as new-with-unknown-specs. Vidar's Sept 2026 promo run had
  flagged 12 grade/colour combos this way; live-base checking resolved specs for 8
  of them (only 4 were genuinely new). A promo sheet omitting box size/thickness is
  a document gap, not evidence the product is missing from Airtable.
- **2026-09-03** — **Grandeur SKU format corrected.** The subsection claimed the
  internal SKU prefix was `GRND` (`GRNDENG-0001`); the base actually holds
  `[CAT]-GRAN-####` (`ENG-GRAN-0030`, `SPC-GRAN-0015`). `GRND…` is the *Lightspeed*
  name prefix only. The scheduled run that day generated 231 rows of `GRND`-prefixed
  SKUs matching none of the 239 live Grandeur records — an import would have
  duplicated the catalogue. Also recorded: Grandeur's `Supplier SKU` is blank on 229
  of 239 records (so matching falls to `Product name`), the letter grade stays
  verbatim in `Product name`, and legacy `SPC-`/`WPC-` prefixes are still present.
  **General lesson: verify a supplier's documented SKU format against the live base
  before generating SKUs from it.**
- **2026-09-03** — Price list runs export **two** files (Airtable + Lightspeed) and
  attach them to the Notion row; the routine no longer writes to Airtable. See
  `methods/pricelist-routine-prompt.md`.
- **2026-09-03** — Same run surfaced two more Grandeur defects, both now documented
  above: LS handles were generated with dots retained and collections truncated to 12
  chars (collisions LS rejects), and the LS file was built with **column 1 `id` blank
  on all 231 rows**, which would have duplicated 212 existing Lightspeed products
  rather than updating them. Added the handle convention, the "take the handle from
  the live record when matched" rule, the species-abbreviation contract
  (`NAH`/`HM`/`NARO`, no redundant size or thickness parenthetical) that 56 rows had
  to be normalised against, and the `Lightspeed ID` requirement — mirrored into the
  `ls-upload-instructions` pre-upload checklist.
- **2026-09-01** — Added "Updating existing products from a price list", after the
  GreenTouch 2026-09-01 run surfaced that the extraction step renumbers internal
  SKUs per run and would have duplicated all 83 existing records. Two rules
  (Albert): a price list for a supplier **not** already in the catalogue never
  creates records through the API — it produces the Bert schema CSV export for
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