# Company profiles

**Decided 2026-09-11 (Albert).** What a company's non-price-list attachments say
about their product lines — the repo did not previously keep this anywhere. Written
by Stage 1 (`/process-price-list`, per `methods/pricelist-extraction.md` — "When the
file is not a price list at all") when a Price Lists row's attachment turns out not
to be a price list but still says something real about what the company sells or
does. Registry pointer: `platform-settings/pricelist-sources.json`,
`price_lists.company_profiles_file`.

**Append, don't rewrite.** Each entry is dated and cites the Price Lists row it came
from. Never delete or edit a prior entry to make room for a new one — a company's
profile is the accumulation of everything learned about them over time, not a single
current snapshot. If a later entry contradicts an earlier one, say so in the later
entry rather than silently overwriting it — that's itself worth knowing.

**This file is not the Company enum.** `Company` (the Notion select property) and
`supplier_aliases` still live in `platform-settings/pricelist-sources.json` /
`airtable-destinations.json`. A company appearing here does not imply it has been
onboarded into Airtable/Lightspeed — this is background knowledge, not a supplier
registry entry. A genuinely new supplier is still handled per the New Supplier rule
in `process-price-list.md`, independent of anything in this file.

**Entry format:**

```
## <COMPANY> (Notion Company value, exact casing)

- **YYYY-MM-DD** — from Price Lists row `<notionID>` (`<Email Subject>`): what the
  document showed. What kind of document it was (per its Tags value), what product
  lines or categories it covered, anything else durable worth remembering. One
  paragraph, plain prose — this is notes, not a schema.
```

## FAW (Notion Company value, exact casing)

- **2026-09-21** — from Price Lists row `3e2596a4-505f-810b-9522-d1b13e9f59e5`
  (`New Price List - Effective September 19, 2026`): a real, structured 4-page price
  list — not flagged blank/no-content — but for bathroom vanities and linen cabinets,
  not flooring. MDF and solid-wood vanity cabinets (24"–72", single/double sink, includes
  quartz countertop + side/backsplash) priced $195–$999 (MDF) and $329–$1,299 (solid
  wood, more for natural-wood finishes), plus matching linen cabinets ($499–$749) and
  door handles/knobs ($3–$6/pc). Order desk `ORDERDESK@FLOORSATWORK.COM`. Tagged
  `Vanity Price List` (new, gray, open-ended per the 2026-09-11 tagging rule) rather
  than `Regular List`/`Promo`, since neither fits a document with zero flooring SKUs.
  Not run through extraction into the Master Flooring Catalogue schema — a vanity has
  none of the 57 flooring columns (no grade, wear layer, box size, etc.) and forcing it
  through would invent meaningless values. This is the first FAW attachment observed to
  carry a non-flooring product line; prior FAW rows in this database are flooring price
  lists. Escalated to Albert (Tactical Tasks List) to confirm the classification and
  decide whether a vanity-specific catalogue/pipeline is worth building, given the
  existing but unrelated `BEST VANITY` Company option already in this same Notion
  database — nothing in this document links FAW to that entity, so no assumption was
  made either way.

## VBK (Notion Company value, exact casing)

- **2026-09-15** — from Price Lists row `3dc596a4-505f-8100-898c-cbbf83399ea4`
  (`VBK: Need 100+ units of 4x10 Black? Reach out for special offer...`): the
  attachment was a 1-page marketing comparison flyer, tagged `Marketing Flyer`
  (a new, gray, open-ended Tags option — not `Regular List`/`Promo`), not a price
  list. It positions "VBK Vents" against cheap generic competitor vents on
  quality: galvanized powder-coated steel, an anti-crush warranty, tight clean
  corners and a consistent finish, versus thin easily-bent metal with inaccurate
  corners and uneven paint on the competing product. No pricing, no SKUs, no
  product catalogue — just a sell sheet. `Company` had no `VBK` option in Notion
  before this row; it was added (confirmed against document header, email
  subject, and sender domain `vbkinc.com`, all agreeing). VBK does not yet
  appear in `airtable-destinations.json`'s `supplier_aliases` — not yet
  onboarded to Airtable/Lightspeed, and this entry does not imply it should be.

## VISTA (Notion Company value, exact casing)

- **2026-09-24** — from Price Lists rows `29f596a4-505f-815c-b44c-f84bb1cc61c7` (PL-145)
  and `29f596a4-505f-817f-86d6-fbf9e03a2b6b` (PL-146) (`TRIM ON SALE~~NEW PRICE LIST`,
  sender `vistastairjoanna@gmail.com`): Vista Stairs, 100 Esna Park Dr., Markham. Both
  attachments are the same 3-page "Primed Trim Price List", effective 2025-07-07 — 43
  primed wood items (baseboard 4"–7¼", casing 2¾"–3½", door jamb, quarter round, door
  stop) — PL-145 priced at "Store Price /pc (≥100 pcs)", PL-146 at the lower "Skid Price
  /pc". Parsed cleanly (both engines agreed), but **Albert set both rows Not Needed**:
  trim is outside the catalogue per the standing moulding exclusion. What Titan actually
  stocks from Vista is stair parts — 142 live Lightspeed products under supplier `VISTA`
  (risers, nosings, treads, spindles, pickets, posts, handrail supports, engineered
  stair pieces) — plus about 4 trims (CWS31-H-08, 11241, 11207, 11242) whose LS costs
  equal the Store Price column. A Vista *stair-parts* list would be a different
  question; this entry does not decide it.
