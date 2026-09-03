# Routine prompt — "Process New Pricing Files from OneDrive"

The canonical text for the scheduled routine. Kept here so it is versioned and
diffable; the live copy is in the routine itself. **The payload is unchanged and
must stay unchanged** — Make sends `{"notionID": "<page id>"}` and nothing else.

Method and rationale for every rule below: `methods/pricelist-extraction.md`.
Change that file and this one together.

---

## Prompt text

You are processing one supplier price list. The payload gives you a single Notion
page id: `{"notionID": "<id>"}`. Everything else comes off that Notion row.

**Process only PDF, image, CSV, or Excel files. Do not produce any output for
unsupported or unrelated files beyond the required statement. Do not alter the
original file contents. Preserve all skill names and system identifiers exactly as
given.**

### 1. Read the row

Fetch the page. `<id>` is a page in the **Price Lists** data source
`collection://e2dc37bc-63da-42e9-b6c0-63ff48d72e6b`. (Do not look it up under
`13b596a4505f80fc816aceefcd0de7c4` — that is the parent PAGE, not the database.)

Take `Files & media`, `Email Subject`, `Sender`, `Email Date`, `Company`, `Tags`.
The file property is a `file://{...}` URL-encoded JSON envelope — decode it and
take `.source` for the SharePoint share link.

### 2. Download the actual bytes

```
python3 scripts/pricelist_fetch.py "<share-link>" /tmp/pricelist.pdf
```

Both parts of that recipe are mandatory: `?download=1` (without it SharePoint
returns viewer HTML that saves happily as a `.pdf`) and a curl cookie jar (`-c/-b`;
the redirect chain sets a `FedAuth` cookie the final hop requires — plain `curl -L`
returns 403).

**Do not use the Microsoft-365 connector's `read_resource` for the source file.**
It returns Microsoft Graph's text conversion rather than bytes, so pdfplumber has
nothing to open, and the conversion flattens table geometry. Use pdfplumber on the
downloaded bytes.

### 3. Assign Company — before checking parseability

Read the `Company` select options live from the data source schema each run; never
hardcode the list. Then, in strict priority order:

1. **The company name printed in the document** — header, footer or contact block.
   The best indicator, and the only one taken from the thing being priced.
2. **The email subject.** Reliable in practice; subjects carry the supplier name.
3. **The sender domain.** Weakest and often no signal at all — Titan forwards
   supplier mail to itself, so the sender is usually `info@titanfloors.ca`. Use it
   only when it is genuinely a supplier domain.

Set Company from subject/sender first, then upgrade it to the document-derived
value once the file is open. Doing it in that order means a file that turns out not
to be a price document still gets tagged.

If none of the three is confident, **leave Company blank and escalate (step 6)**.
Do not pick a nearest match — the option list has near-collisions
(BALTIC/NORTHWAY, FLOORDI/UMBRELLAR) and a wrong value looks authoritative.

Casing differs per system and is not to be "fixed": Notion `Company` is ALL CAPS
(`GREENTOUCH`), Airtable `Supplier` keeps its own mixed case (`GreenTouch`).

### 4. Tag the row — Regular List or Promo

`Tags` has exactly two options: `Regular List` and `Promo`.

**Classify the file in front of you, not the email.** One email with several
attachments becomes several rows and they get different tags; the payload hands you
one file.

A **Promo** is a document whose purpose is a temporary discount. Tag `Promo` if the
document shows any of:

1. **Its own printed title** says `PROMOTION`, `PROMO`, `SPECIAL(S)`, `CLEARANCE`,
   `SALE`, `FLYER`, `OVERSTOCK`, `BLOWOUT` or `COMBO`.
2. **Two price columns** — a regular/original price beside a promo/sale/now price.
3. **An expiry or validity window** — "valid until", "offers expire", "while
   quantities last", "good till", a named month as the offer period. A regular list
   carries an effective-from date and no end date.
4. **Subset scope** — a few colours or SKUs rather than the catalogue.

Otherwise tag `Regular List`: the supplier's standing catalogue, organised by
collection, usually multi-page with a contents page, one price per item,
`Effective <date>` with no end, standing order and payment terms.

**A regular list stays `Regular List` even when prices went down, even when it
contains a clearance section, and even when the email carrying it advertises a
sale.** Only a purely promotional document is `Promo`.

Do not decide from the email subject alone (it disagrees with the file about a
quarter of the time), from how a sibling or past row for that supplier is tagged
(the existing data contains verified mis-tags in both directions), or from keyword
counts in the body (stock-status markers like "Limited" are not promotions).

If it is genuinely unclear, **leave `Tags` blank and escalate (step 6)**.

### 5. Extract, verify, write

Confirm the file is a parseable price document. If it is not, stop here — Company
and Tags are already set — and say only that the file is not a supported price
document.

Otherwise extract with the **bert-airtable-schema** skill and produce the
**ls-upload** file. Before writing anything to Airtable, check the supplier already
exists in the Master Flooring Catalogue (`appWHOVZ0QCS0xQ3M` / `tblfLXD3zkSdNQGbS`):

- **Rows returned** → this is an UPDATE, not an import. Match on internal `SKU`
  first, then `Supplier SKU` as a partial/fuzzy match, then specifications as a last
  resort. Never match against a SKU the extraction step generated. Write only fields
  that changed; set `Price last changed by` = `Cowork`, and append one row per cost
  change to Price History Log v2 (`tbly2em2cMuQs9eqK`, `typecast: true`).
- **No rows** → produce the Bert schema Excel export and stop. New suppliers enter
  through Airtable's own importer after human review.

Cross-check the extracted SKU→price pairs against pdfplumber's own text before
writing and again after. Lightspeed has no API here — produce the file, never
report it as imported.

### 6. Escalate anything you could not determine

Create a row in the **✅ Tactical Tasks List**
(`collection://238596a4-505f-8137-af13-000bde205213`) assigned to Albert
(`c39aa5d3-c87c-4152-92ef-5ed13d9c4605`), with `Priority: high`,
`Tags: ["price list"]`, `Verification: Needs Verification`, `url` pointing at the
Price Lists row, and Notes recording what you tried and what the document showed.
Send a PushNotification as well — the task is the durable record, the push is the
alert.

### 7. Finish the Notion row

Create the OneDrive folder `[Company]_[effective price date]_[Promo or Regular]`,
upload the extracted files, generate a shareable link, then check `Extracted` and
paste the link into `Extracted Files`.

---

## Changelog

- **2026-09-03** — Added step 4 (Regular List / Promo classification) and made the
  routine set `Tags` as well as `Company`. Rules derived from the 357 rows already
  in the database and validated against four documents; see
  `methods/pricelist-extraction.md`.
- **2026-09-02** — The routine assigns `Company` itself (step 3). Make scenario
  4382120 no longer owns that field: it matched on `sender_email` in 38 of 40
  conditions, and every price list arrives from `info@titanfloors.ca`.
- **2026-09-01** — Pinned the download recipe (step 2) after a run used Graph's text
  conversion instead of the PDF bytes.
