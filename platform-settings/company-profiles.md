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
