# Supplier Price List Extraction

Repeatable method for turning a supplier price list PDF into verified Airtable
pricing. Runs as the "Process New Pricing Files from OneDrive" routine, fired by
Make with a payload of `{"notionID": "<page id>"}` and nothing else — every other
input comes off the Notion row.

Fetch helper: `scripts/pricelist_fetch.py`. Extraction itself is the
`pricelist-processor` agent (carries the `bert-airtable-schema` and
`ls-upload-instructions` skills preloaded). The routine's own prompt text lives in
`methods/pricelist-routine-prompt.md` — change it and this file together.

## The chain

```
Make scenario 4381438 (Price Lists)
  → Outlook attachment → OneDrive /Price List (Attachments)
  → anonymous share link → Notion "Price Lists" row
        ↓  {"notionID": ...}
  routine → Notion row → share link → curl (cookie jar) → pdfplumber
        → bert-airtable-schema → Airtable update + Price History Log v2
        → ls-upload file → OneDrive company folder → link back to Notion
```

The Notion "Price Lists" database is the index of **every** supplier PDF Titan has
received, tagged by company and Promo/Regular. Any past price list can be pulled
the same way — the routine is just the automated case.

## Getting the actual file (the part that wastes a session if you get it wrong)

```
python3 scripts/pricelist_fetch.py "<share-link>" out.pdf [--text]
```

The share link lives in the Notion row's `Files & media` property, wrapped in a
`file://{...}` JSON envelope — URL-decode it and take `.source`.

Two requirements, both mandatory, neither obvious:

- **`?download=1`** — without it SharePoint serves ~275KB of OneDrive *viewer HTML*
  that will happily save as `out.pdf` and fail confusingly later.
- **a cookie jar** (`curl -c/-b`) — the redirect chain sets a `FedAuth` cookie the
  final hop requires. Plain `curl -L` returns **403 Forbidden**
  (`x-msdavext_error: Access denied`), even though the link is anonymous-scoped.

**Do not use the Microsoft-365 connector's `read_resource` for the source file.**
It returns Microsoft Graph's *text conversion*, not bytes, so pdfplumber has
nothing to open — and Graph's conversion flattens table geometry (it interleaves
stock-status markers mid-row, e.g. `WB1381 Limited LUCCA ABC $4.09`, where
pdfplumber correctly puts `Limited` on its own line). `sharepoint.com` is reachable
from cloud sessions; no network-policy change is needed.

## Check the supplier exists first

**A price list for a supplier not already in the catalogue never creates records
through the API.** Query the Master Flooring Catalogue (`appWHOVZ0QCS0xQ3M` /
`tblfLXD3zkSdNQGbS`) filtered to that supplier before writing anything:

- **Rows returned** → update path, below.
- **No rows** → produce the Bert schema Excel export (canonical column order) and
  stop. New products enter through Airtable's own importer after human review, and
  the supplier's select option, SKU suffix, cost column and markup overrides have to
  be settled first — see the skill's new-supplier onboarding checklist.

## For an existing supplier, Airtable is an UPDATE, not an import

Most suppliers already have their whole catalogue in Airtable. A price list is a
**price change against existing rows.** Match in this cascade, stopping at the first
tier that resolves cleanly:

1. **Internal `SKU`** (`fldx3byCOht5HbKmH`) — the canonical key, as stored in
   Airtable. Resolves deterministically for suppliers whose code is the SKU suffix
   verbatim (Biyork, Triforest, Olympia).
2. **`Supplier SKU`** (`fldLOrMqh4aBftjtu`) — partial/fuzzy on the supplier's own
   code (`WB1361`, `SP2801`). Where sequentially numbered suppliers land.
3. **Specifications** — name, collection, size, grade, colour. Last resort, always
   review.

**Never match against a SKU generated during the run.** Tier 1 means the stored SKU,
looked up live. Extraction renumbers per run — it emitted `LVP-GRNT-0001…0010` where
Airtable holds `LVP-GRNT-0073…0082` — so treating generated values as tier-1 keys
silently duplicates the catalogue. GreenTouch is sequential, so that run correctly
resolved at tier 2.
- Write only fields that actually changed. Set `Last price update` and
  `Price last changed by` = **`Cowork`** (the extraction skill defaults this to
  `Manual` — override it; these runs are not manual).
- Append one row per cost change to **Price History Log v2** (`tbly2em2cMuQs9eqK`):
  entry type, previous/new cost, change date, supplier, `Changed by` = Cowork, and
  the source filename. Its `Supplier` select is sparse — pass `typecast: true` so a
  new supplier option is created rather than erroring.
- Lightspeed has no API in this environment. Produce the ls-upload file; never
  report it as imported.

## Verify before writing, and after

This writes live pricing that Bert quotes to customers, unattended. Cross-check the
extracted values against pdfplumber's own text before pushing, and re-check after:

```
python3 scripts/pricelist_fetch.py "<link>" /tmp/v.pdf
# then diff SKU→price pairs from page_text() against what you're about to write
```

On the 2026-09-01 GreenTouch run this compared 82 of 83 SKUs (the 83rd, the
T-Moulding accessory, has a non-conforming SKU) with **zero mismatches**.

## Name casing differs per system — do not "fix" it

| System | Form | Example |
|---|---|---|
| Notion `Company` select | ALL CAPS | `GREENTOUCH` |
| Make scenario 4382120 | ALL CAPS (must match Notion exactly) | `GREENTOUCH` |
| Airtable `Supplier` select | established mixed case | `GreenTouch` |
| Vault supplier note | title case | `[[Greentouch]]` |

Normalising Airtable to match Notion fragments its select options and orphans
existing rows. Each system's existing convention wins.

## Company assignment belongs to the routine, not to Make

**Decided 2026-09-02 (Albert).** Make scenario 4382120 ("Price Lists (Assign
Company)") is being retired as the owner of the Company field. The routine assigns
it directly on the Notion row instead.

Why: 4382120 matched on `sender_email` in 38 of its 40 conditions, but every price
list arrives from `info@titanfloors.ca` because Titan forwards them to itself — so
it was keying off a field that is nearly always the same value. That is why the
GreenTouch branch never fired, and it means most branches likely never matched
either. It also carried real bugs: `lucky` matched `"jospehren"` (a transposed
typo), `baltic homes` matched `"josephren"` and wrote `NORTHWAY`, `FLOORDI` wrote
`UMBRELLAR`, and there was no catch-all — an unmatched supplier silently no-ops.

The routine has strictly more to work with: it reads the document itself. On the
2026-09-01 run the company came from the PDF footer (`GREEN TOUCH FLOORS /
INFO@GREENTOUCHFLOORS.COM`), which is ground truth rather than a guess from an
envelope.

### The matching cascade

Read the Company select options **live** from the Notion data source schema each
run — never hardcode the list, it drifts. Then, in strict priority order:

1. **The company name printed in the document** (header/footer/contact block) —
   the best indicator, and the only one taken from the thing being priced.
2. **Subject keyword** — reliable in practice; subjects carry the supplier name.
3. **Sender domain** — weakest, and often no signal at all: Titan forwards supplier
   mail to itself, so the sender is usually `info@titanfloors.ca`. Use only when it
   is genuinely a supplier domain.

If none of these is confident, **leave Company blank, flag it, and escalate** (see
below). Do not pick a nearest match. The option list contains near-collisions the
old scenario already got wrong (BALTIC/NORTHWAY, FLOORDI/UMBRELLAR); a wrong value
looks authoritative and mis-routes silently, whereas a blank one is visibly
incomplete.

### Escalation when the company can't be determined

Create a row in the **✅ Tactical Tasks List**
(`collection://238596a4-505f-8137-af13-000bde205213`) assigned to Albert
(`c39aa5d3-c87c-4152-92ef-5ed13d9c4605`), `Priority: high`,
`Tags: ["price list"]`, `Verification: Needs Verification`, `url` pointing at the
Price Lists row, and Notes recording what was tried and what the document showed.
Send a PushNotification as well — the task is the durable record, the push is the
alert. Assigning Albert matches what scenario 4381438 already does for its
"Update POS Price List" tasks; it is not a new convention.

**Assign Company before the parseability check.** The routine terminates early on a
file that is not a price document; if Company is only set after parsing, flyers and
junk attachments lose their tag entirely — worse than the old behaviour. Set it
from subject/sender first, then upgrade to the document-derived value.

### Parent scenario 4381438 depends on the returned value

4381438 feeds `{{20.company_name}}` into a Tactical Tasks title,
`"Update POS Price List - {{company}}"`, created at ingest time — before the routine
has read anything. Retitle that task from the **email subject** (which carries the
supplier name in practice) so the CallSubscenario modules can be dropped; otherwise
the title renders with a blank.

## Tagging the row: Regular List vs Promo

**Decided 2026-09-03 (Albert).** The routine sets `Tags` on the Notion row as well
as `Company`. The two options are exactly `Regular List` and `Promo` — no others.

**The file decides, not the email.** One email with several attachments becomes
several rows — 4381438 aggregates the attachments (`#10`), then iterates them with a
`BasicFeeder` (`#12`), so every module past the feeder runs once per file. 24
subjects in the database carry *both* tags across 55 rows (Vidar's "…price list and
monthly promotion price list" pattern, Tosca's "NEW Price List and July Clearance
List", Floordi, Weiss, Lee, Impressive). The payload hands you one `notionID` = one
file. Classify that file.

**Where the existing tags came from — they are not a human's judgement.** Until
2026-09-03, `Tags` was set by 4381438's router (`#15`) from the **OneDrive
filename**: route 0 hardcoded `Promo` on `promotion|promo|special|clearance|sale|
sales`, route 1 hardcoded `Regular List` on `price list|pricelist|price`, route 2
had no filter and wrote no tag (the source of the 5 untagged rows). So the 24
split-tag subjects are two filenames landing in two keyword buckets, not per-file
judgement — treat historical tags as a weak baseline, and see the mis-tags below.
The `sale` condition is a substring match, so it also fires on **"Whole*sale*"**;
`/Price List (Attachments)` currently holds three such files
(`Wholesale Price List.xlsx.pdf`, `Wholesale Price List.xlsx - Waterproofing (3).pdf`,
`Door Wholesale pricelist (05122025).pdf`).

### The distinction

A **Promo** is a document whose *purpose* is a temporary discount — clearance,
specials, monthly promo, overstock, flyer, blowout, combo, spiff.

A **Regular List** is the supplier's standing catalogue. It stays `Regular List`
even when prices went down, even when it contains a sale or clearance *section*,
and even when the email carrying it is marketing a sale. Only a purely promotional
document is `Promo`.

### Read these, in order

Tag `Promo` if the document shows any of:

1. **Its own title says so** — `PROMOTION`, `PROMO`, `SPECIAL(S)`, `CLEARANCE`,
   `SALE`, `FLYER`, `OVERSTOCK`, `BLOWOUT`, `COMBO`. The title printed on the page,
   not the email subject. (`Oakel City Clearance Price List`; Vidar's page-1
   `PROMOTION / AUGUST`.)
2. **Two price columns** — a regular/original price beside a promo/sale/now price.
   Oakel's clearance sheet is `Original | Promotion` per row. A document that has to
   show you the old price exists to express a discount.
3. **An expiry or validity window** — "valid until", "offers expire", "while
   quantities last", "good till", "must be picked up by promotion ends", or a named
   month as the offer period. This is the cleanest single discriminator: a regular
   list carries an **effective-from** date and no end date; a promo carries an end.
4. **Subset scope** — a handful of colours or SKUs pulled from collections the
   supplier sells far more of, rather than the catalogue.

Otherwise `Regular List`: organised by collection/series, often a contents page and
many pages, one price per item, `Effective <date>` with no end, standing order and
payment terms at the foot.

Worked pair, both from the same email, both verified with pdfplumber
(`Vidar Design Flooring 2026 August New Update price list and monthly promotion
price list`):

| | Regular List file | Promo file |
|---|---|---|
| Pages | 15 | 2 |
| Title | `Price List` | `PROMOTION` |
| Date | `Effective From August 1, 2026` | `Offers are valid and until August 31, 2026` |
| Structure | contents page, 14 collections | one table, subset of colours |
| Terms | standing order/payment terms | "cannot be combined with any other discounts" |

### Signals that do not decide it

- **The email subject.** Treated as the rule it is right 102 times out of 136 —
  34 `Regular List` rows have a promo word in the subject and 11 `Promo` rows have a
  neutral one. Use it only to break a tie the document genuinely leaves open.
- **The tag on a sibling row, or on the supplier's past rows.** The existing data
  contains real mis-tags in both directions, two of them verified here: Oakel's
  `Oakel City Clearance Price List` (dual Original/Promotion columns) is tagged
  `Regular List`, and Vizion's plain 6-page `Vizion Floor Price List` — single price
  column, no promo language — is tagged `Promo`. Classify from the document; do not
  imitate history.
- **Bare keyword counts in the body.** The Vidar regular list contains "Limited" 12
  times (stock-status markers, per the Cautions below) and "sale" twice, with no
  promotional meaning. Look at titles, column headers and terms blocks — not a
  word frequency.

### When it is genuinely unclear

Leave `Tags` blank and escalate on the same path as an unresolvable Company (below).
A blank tag is visibly incomplete; a wrong one silently mis-files the document.
Five rows already sit untagged, so blank is an existing state, not a new one.

## Do not edit large Make blueprints through `scenarios_update`

`scenarios_update` takes the blueprint as an inline parameter, so the whole thing
must be generated as tool output. 4382120's was 488,594 bytes (~140k tokens) —
impossible in one call. 4381438's is larger still.

**Stripping `metadata` to make it fit does not work, and fails silently.** Tried
2026-09-02: `metadata.expect` (the input parameter schema, ~1.8KB per module) and
`metadata.interface` (~9KB) look like regenerable UI cache, and Make does rebuild
them when a module is opened in the designer — but the **runtime needs `expect`**.
Without it the module still matches, still executes, still consumes an operation and
still makes a real Notion API round-trip (~3KB transfer), but the `fields` payload is
dropped and nothing is written. Status comes back `SUCCESS`, no error, no DLQ entry.
Verified in both directions: restoring `expect` on one module made its write land;
firing a different branch with `expect` stripped consumed an operation and wrote
nothing.

Edit Make blueprints in the Make UI. If an API edit is ever unavoidable, keep every
module's `metadata` intact and accept the size limit as a hard stop.
- **OneDrive folder itemId** — `sharepoint_create_folder` / `sharepoint_upload_file`
  need the parent's Graph itemId, and no available tool surfaces it: the drive-root
  listing silently omits `Price List (Attachments)` (though creating it returns
  CONFLICT, proving it is there) and `sharepoint_folder_search` ignores its name
  filter entirely. `sharepoint_search` with `folderName:` **does** scope correctly
  and is the fast way to confirm files. Time-box this; report blocked rather than
  creating a stray folder at the drive root.

## Cautions

- The share link is anonymous-scoped but tenant-served — it works from cloud
  sessions and from Albert's Mac, but it is still a live SharePoint URL, not a
  permanent artifact. Re-fetch rather than caching the URL long-term.
- Stock-status markers (`Limited`, `Discontinued`) sit on their own line in
  pdfplumber's output, *following* the SKU row they qualify. Attach them by
  position, and sanity-check the count against the printed page.
- Where a skill's documented collection/grouping conflicts with the literal printed
  page header, follow the document and flag the skill for correction.
