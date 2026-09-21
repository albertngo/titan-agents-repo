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
