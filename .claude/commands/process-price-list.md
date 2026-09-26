---
description: Process one supplier price list from a Notion Price Lists row into an Airtable upload file and a Lightspeed upload file, attached back to the row.
argument-hint: <notionID or Notion page URL>
---

Process the supplier price list on Notion Price Lists row: **$ARGUMENTS**

(Accepts a bare page id or a full `notion.so` / `app.notion.com` URL — take the id out
of the URL if given one. If no argument was supplied, stop and ask for the row.)

The full method, with the rationale behind every rule below, is
`methods/pricelist-extraction.md`. The canonical prompt text this command mirrors is
`methods/pricelist-routine-prompt.md` — **change those two and this file together.**

Read `platform-settings/pricelist-sources.json` and
`platform-settings/airtable-destinations.json` in full before doing anything below —
they hold the ids, property names and option strings this command must not re-derive
or guess. Every id referenced as *(registry)* comes from there.

Load the **bert-airtable-schema** skill (supplier rules, 57-column schema, RULE 0/0a)
and, for step 5, the **ls-upload-instructions** skill. Load them as references; never
pass them arguments.

---

## 1. Read the row

Fetch the page. It is a row in the **Price Lists** data source — `price_lists.data_source`
*(registry)*. The registry also records the parent PAGE id under
`_parent_page_not_the_database`, so that mistake is never re-made.

Read the properties named in `price_lists.read_properties` *(registry)*. The
file property is a `file://{...}` URL-encoded JSON envelope — decode it and take
`.source` for the SharePoint share link.

## 2. Download the actual bytes

### 2.0 FIRST — verify pdfplumber, before anything else

**Albert, 2026-09-12: pdfplumber is the only sanctioned way to read a price list.
If it is unusable, flag and stop. Never substitute another method.**

Run this before the download, before touching Notion state, before any extraction:

```bash
python3 -c "import pdfplumber; print(pdfplumber.__version__)"
```

If that fails, **this run is over.** Do all of the following and nothing else:

- Set `Extraction Status` = `Extracted [Error]` (per step 6's write rules).
- `Notes` = the exact failure, naming `pdfplumber` and the reason — a missing
  module, or `host_not_allowed` on `pypi.org` if an install was attempted.
- One row in the troubled CSV, `stage: extract`, `reason: pdf_tooling_unavailable`,
  `disposition: held` — per `contracts/troubled-skus-schema.md`.
- Send a PushNotification saying extraction could not run and why.
- **Produce no upload CSVs. Attach nothing to `Extracted Files`. Do not continue to
  `/catalog-sync`** — there is no input for it, and a sync on invented data is worse
  than no sync.

**Explicitly prohibited as substitutes**, however well any of them appears to work:
reading the rendered PDF visually (a model reading the page image), the
Microsoft-365 connector's `read_resource` text conversion, `pdftotext`/poppler,
an LLM transcription of a screenshot, or retyping figures from the Notion `Notes` of
a previous run. A price that reaches the POS must be traceable to a deterministic
parse of the supplier's own bytes.

**Except when the attachment IS an image (Albert, 2026-09-24)** — a JPEG/PNG/HEIC
photo or scan of a list, not a PDF. Then there are no text bytes to parse, and
step 2.3 below is the sanctioned method. It does not reopen any of the above for a
PDF: a PDF is still read by pdfplumber and nothing else.

**Why this is a hard gate and not a preference.** On 2026-09-01 the pdfplumber method
was written into these docs from a session where it genuinely worked. On 2026-09-02 the
import in `scripts/pricelist_fetch.py` was made lazy — "so fetching works without it
installed" — and from 2026-09-03 to 09-09, 15 `airtable_upload` CSVs were committed by
cloud sessions that had no way to run it, with no `requirements.txt` in the repo and
`pypi.org` off the egress allowlist. The documented method and the executed method had
silently diverged for ten days, and the output looked fine, so nothing caught it. This
check is what makes that divergence impossible rather than merely discouraged.

Dependency is declared in `requirements.txt`; installing it needs `pypi.org` and
`files.pythonhosted.org` on the environment's network allowlist.

### 2.1 Then download

```
python3 scripts/pricelist_fetch.py "<share-link>" /tmp/pricelist.pdf
```

Both halves of that recipe are mandatory: `?download=1` (without it SharePoint returns
viewer HTML that saves happily as a `.pdf`) and a curl cookie jar (`-c/-b`; the
redirect chain sets a `FedAuth` cookie the final hop needs — plain `curl -L` gets 403).

**Do not use the Microsoft-365 connector's `read_resource` for the source file.** It
returns Graph's text conversion rather than bytes, which flattens table geometry. Use
pdfplumber on the downloaded bytes.

### 2.2 Extract via the script — two engines must agree

**Do not call pdfplumber by hand. Run this:**

```bash
python3 scripts/pricelist_extract.py /tmp/pricelist.pdf --json /tmp/extract.json
```

It parses with pdfplumber and **cross-checks every monetary value against
pypdfium2 (PDFium, Google's C library)** — a completely independent engine that
shares no code with pdfminer.six, so the two fail differently. Exit codes:

| Exit | Meaning | What to do |
|---|---|---|
| `0` | Both engines agree on every monetary value | Proceed |
| `1` | **Disagreement** — pdfplumber produced a figure PDFium cannot see | **Stop.** Parse defect, see below |
| `2` | pdfplumber or pypdfium2 missing | Stop, per step 2.0 |

**On exit 1 the extraction is void.** Do not use any of its numbers, do not
"pick the more likely one", and do not fall back to reading the page. Set
`Extraction Status` = `Extracted [Error]`, put the disagreeing values in `Notes`,
write one `cross_check_failed` row to the troubled CSV, notify, and stop.

**Why the check compares value sets rather than rows.** The two engines
legitimately disagree on *reading order* — that is layout, not data. On the
HOMESPRO sheet PDFium places `$13/roll` away from "IXPE Underlay" because that
cell is merged across the trim columns. Halting on that would block a correct
extraction. So the halting condition is narrower and sharper: **every value
pdfplumber extracted must exist somewhere in PDFium's text.** That catches a
misread or manufactured price — which would be absent from the other engine —
while ignoring layout differences. PDFium seeing *extra* values is normal and
never halts; it reads page prose (phone numbers, addresses) that pdfplumber's
table cells exclude.

Verified on HOMESPRO 2026-09-12: 11 distinct values, both engines, full agreement.

### 2.2a What the script handles for you, and why it must

Verified on the HOMESPRO sheet, 2026-09-12, and it is the difference between a clean
parse and a useless one.

- **`extract_text()` can scramble reading order badly** on a designed/marketing-style
  sheet. On HOMESPRO it returned prices detached from their products — `$1.65`
  (Tuscany) and `$1.45` (Milan) landing adjacent, four lines from either name. Never
  read prices from `extract_text()` output.
- **`extract_tables()` uses geometry and got every row right** — product, spec string
  and all four price columns correctly aligned, on a sheet with colour bands instead
  of ruling lines.
- **A whole-page catch-all "table 0" is normal and is junk.** HOMESPRO returned 5
  tables: index 0 was the entire page jumbled into one cell, indices 1–4 were the
  real sections (SPC / glue-down / laminate / underlay). Take the structured ones;
  never parse table 0.
- Expect **side labels to split across columns** — `LONG PLA` + `NK`,
  `HERRINGBO` + `NE`. Cosmetic, and prices are unaffected, but rejoin them rather
  than treating the fragment as data.

Cross-check the two code paths against each other where both produce a figure: they
are independent enough that disagreement is a real signal. That replaces the old
"cross-check against pdfplumber's own text", which compared a parse against itself.

### 2.3 The attachment is an image — two readers, row by row (2026-09-24)

Albert, 2026-09-24, on PL-170 (Baltic Homes, a phone photo of a printed list):
*"jpg (or any image file) should be allowed. BUT it should read the context of the
image, and decide if it is flooring. And if so, process just as pdfplumber does."*

Check the downloaded bytes with `file` before step 2.2 — `pricelist_fetch.py` says
`non-PDF` — and a SharePoint `:i:` share link is the early sign. Then:

1. **Read the image and classify it first.** Is it a price list, and is it flooring?
   Not a price list → step 5's "not a price list" branch, same as a PDF. Out-of-scope
   product only (trim, vanities, doors) → report it and stop, same as a PDF section.
2. **Transcribe it into structured JSON — reader 1.** Zoom the image (crop into
   bands at ~2×) and read every row: code, colour, description, and every printed
   price as printed. Shape: `{"rows": [{"key": <code>, "money": [<prices>], …}]}`,
   saved and **committed** as `ingest/<date>/<supplier>_transcription_<date>.json`
   next to the image itself (`<supplier>_<PL>_source.<ext>`), so every price stays
   traceable to its bytes.
3. **Cross-check it with OCR — reader 2:**
   ```bash
   pip install rapidocr_onnxruntime   # not vendored: ~100 MB with onnxruntime/opencv
   python3 scripts/pricelist_image_check.py <image> <transcription.json> --json <report.json>
   ```
   RapidOCR shares nothing with the model reading the image. Every transcribed price
   must be on the **same row** of the OCR output, and every priced OCR line must be
   claimed by a transcribed row.

| Exit | Meaning | What to do |
|---|---|---|
| `0` | Both readers agree on every price, row by row | Proceed to step 3 with the transcription |
| `1`, rows `disagree` / `not_located` | OCR read a different number, or could not find the row | **Hold those rows** — `ambiguous_pricing`, `held`, the two readings in `col_printed`. The rest proceed. Never pick a reader |
| `1`, `unclaimed priced OCR lines` | OCR saw a priced line the transcription does not have | **Stop.** The transcription dropped a row; fix it and re-run |
| `2` | No OCR engine | Stop, per step 2.0 — never proceed on one reader |

**Why rows are held rather than the whole list voided**, unlike a PDF's exit 1: OCR
on a phone photo misreads characters far more often than a PDF engine does, so an
all-or-nothing rule would make every photographed list unprocessable. A held row
writes nothing, so the pricing carve-out still protects it. On PL-170 OCR read
HD-005's 3.92 as 3.02; the other 31 rows agreed exactly.

**Do not upscale for OCR.** On PL-170 a 2.2× crop introduced four new misreads
(3.43, 3.01, 3.40, 1.93); zoom is for the transcription, not the check.

## 3. Assign `Company` — before checking parseability

Read the `Company` select options live from the data source schema each run; never
hardcode the list. Then, in strict priority order:

1. **The company name printed in the document** — header, footer or contact block. The
   only signal taken from the thing being priced.
2. **The email subject.** Reliable in practice.
3. **The sender domain.** Weakest and often no signal — Titan forwards supplier mail to
   itself, so the sender is usually `info@titanfloors.ca`. Use only when it is genuinely
   a supplier domain.

Set it from subject/sender first, then upgrade to the document-derived value once the
file is open — so a file that turns out not to be a price document still gets tagged.

If none of the three is confident, **leave `Company` blank and escalate (step 7)**. Do
not pick a nearest match: the option list has near-collisions (BALTIC/NORTHWAY,
FLOORDI/UMBRELLAR) and a wrong value looks authoritative.

**`Supplier` is ALL CAPS in Airtable** (Albert, 2026-09-21) — it was mixed case until
then, and was capitalised so Notion, Airtable and Lightspeed mirror each other. So
`GREENTOUCH` in Notion is `GREENTOUCH` in Airtable, not `GreenTouch`. **`Brand` is NOT
capitalised** and keeps its own case (`NAF`, `Toucan`, `Appalachian`) — only `Supplier`
changed.

**Five cases are a different NAME, not a different case** — `FAW` → `FLOORS AT WORK`,
`LEE` → `LEE FLOORING`, `OLYMPIA` → `OLYMPIA TILE`, `CIF (FAOILA)` → `CIF DISTRIBUTORS`,
`BELLA` → `BELLA FLOORING PLUS`. That is the entire reason this stays a lookup: cross the
two with `supplier_aliases` *(registry)*, **never** with `.upper()`, which would silently
produce `FAW` and match nothing. A Notion `Company` with no entry there is the **new
supplier** signal, not an error.

**Never write a `Supplier` value that is not already an option.** Airtable's `typecast`
creates a missing single-select choice silently, so one mixed-case write re-fragments the
column — which is the exact state the 2026-09-21 capitalisation cleaned up.

## 3a. The list's effective date — `Effective Date` on every row

(Albert, 2026-09-25.) `Effective Date` is the date of the **newest list received for
the company** that carries the product — a list that repeats a price still moves it
forward, because the price is confirmed current. Put the same date on every row of
both the create and update sheets, taken in strict priority order:

1. **The date printed in the document** — "Effective …", "Valid from …", a dated
   header or footer. A range → its start date.
2. **A date in the email subject** (`read_properties.title`, `Email Subject`).
3. **The email's received date** (`read_properties.email_date`, `Email Date`).

A date printed as a month only ("SEPTEMBER 2026 PRICE LIST") is the first of that
month. Write it as `YYYY-MM-DD` — the reconciler refuses any other form. Say in `Notes`
which of the three it came from when it was not (1). Never the day the run processed
the list: Baltic PL-170 and IMPRESSIVE PL-381 were created that way.

**Write the same date to the row's `Effective Date` property**
(`write_properties.effective_date` *(registry)*, a Notion date) in step 6's state
write. It is where a person sees when a list takes effect, and what
`/price-list-sweep` reads: a date after today means the list is **staged** — extracted
and attached now, written to Lightspeed and Airtable only on that day.

**Put the list's link beside it, as a `Price List URL` column** after the helper
columns (Albert, 2026-09-25: "each SKU has a verifiable company list to look at with
a click of a button from Airtable"). The value is the SharePoint share link decoded
from the row's `Files & media` (step 1's `.source`) — the same anonymous link the
download used, so it opens for anyone at Titan. Same value on every row. Airtable's
`Price List URL` field is a URL type, and the reconciler writes it together with the
date, so a record always points at the list its `Effective Date` names.

**A promo sheet is the exception** (Tags `Promo`, 2026-09-26, PL-383): it sets only
`Promo cost` and `Promo end date` and confirms nothing about the regular price, so its
rows carry each record's **live** `Effective Date` and `Price List URL`, unchanged.

**Every row that carries a promo gets a `Promo List URL` column** — this list's link,
the same value `Price List URL` would take (Albert, 2026-09-26: a SKU can be priced by
a regular list and put on promo by a separate sheet in the same month, so one link
cannot name both). On a promo sheet that is the only link that changes; on a regular
list that prints promo prices, both columns carry this list. A row without a promo
leaves it blank, and blank never clears a live link: an ended promo keeps pointing at
the sheet that set it, which is how a person finds it to ask the rep about it later.
The row's own `Effective Date` property still gets the promo's start date (it is what
decides whether the promo is in effect yet), and `Promo end date` gets the printed end.

**Every promo row carries a `Promo end date` — never blank (Albert, 2026-09-26).** No
printed end: a Promo sheet for a named month → that month's last day; a promo on a
regular list → the last day of the list's `Effective Date` month. When two readings
disagree, the earlier. Strict on purpose: an end too soon costs a rep call, an end
too late sells at a cost Titan no longer gets. Say in `Notes` which rule dated it.
(`catalog_reconcile.py` fills a missed one the same way and warns `promo_end_inferred`.)

`catalog_reconcile.py` does the rest: a price change writes this date and
`Price last changed by = Agent`; a confirmation moves the date forward only, never
backward, and leaves the author alone.

## 4. Tag the row — `Regular List` or `Promo`

**This step is for a document already confirmed to be a price list.** If it turns
out not to be one at all, don't force it into either tag here — skip to step 5's
classification, which covers what `Tags` gets instead.

For an actual price list, `Tags` has exactly two canonical options. **Classify the
file in front of you, not the email** — one email with several attachments becomes
several rows with different tags.

Tag `Promo` if the document shows any of: its own printed title says PROMOTION / PROMO /
SPECIAL(S) / CLEARANCE / SALE / FLYER / OVERSTOCK / COMBO; two price columns (regular
beside promo); an expiry or validity window ("valid until", "while quantities last", a
named month as the offer period); or subset scope (a few colours rather than the
catalogue).

Otherwise `Regular List`. **A regular list stays `Regular List` even when prices went
down, even when it contains a clearance section, and even when the email carrying it
advertises a sale.** Only a purely promotional document is `Promo`.

Do not decide from the email subject alone (it disagrees with the file about a quarter
of the time), from how a sibling or past row is tagged (the data contains verified
mis-tags both ways), or from keyword counts ("Limited" is a stock marker, not a promo).

Genuinely unclear → leave `Tags` blank and escalate (step 7).

## 5. Extract, reconcile, then build both files — in that order

**RULE 0: the Airtable `SKU` is immutable and the source of truth.** Everything matches
to it. Never regenerate, reformat or "correct" a stored SKU; a SKU that looks wrong is
escalated, never edited.

Confirm the file is a parseable price document — one that states unit prices for
products. If it is, continue below, tagging per step 4.

If it is not a price list at all, classify which case applies — full rationale in
`methods/pricelist-extraction.md`, "When the file is not a price list at all":

- **Has real content** (a catalogue, spec sheet, marketing material, anything
  describing the company's products without pricing) — tag it freely (a short
  descriptive tag, never `Regular List`/`Promo`), coloured gray; log what it shows
  about the company into `platform-settings/company-profiles.md`; set
  `Extraction Status = Extracted [Needs Review]` with `Notes` explaining there's no
  price data and no CSVs are expected (a deliberate exception to the "never leave
  Needs Review with empty Extracted Files" rule below — this is why); leave
  `Airtable Sync` untouched, since a run may only write `Pending` to it and that
  would be false here.
- **Has no content at all** (bare logo, blank, decorative image), and only on a row
  still at `Extraction Status = Not started` — archive the Notion page (soft-delete,
  recoverable, never anything harder). Report this every time, never silently — the
  one outcome here that removes something from Notion.

Default to the first of those two on any doubt.

Otherwise, **in this order — it is a dependency, not a preference**:

1. **Extract** into the 57 canonical columns (exact documented order). **Always attempt
   `Length`** (column 17) — text, so `RL` / `48"` / `20" - 83"` are all valid; blank only
   when the supplier never states one.
2. **Read the live catalogue** (`base_id` / `tables.master_flooring_catalogue.table_id`,
   *(registry)*) filtered to
   that supplier, and match every extracted row: internal `SKU` → `Supplier SKU`
   (partial/fuzzy) → specifications, principally `Product name`. Stop at the first tier
   that resolves cleanly.
   - **Rows returned** → this is an **update sheet**.
   - **No rows** → **new supplier. Still produce the Airtable export** — the canonical
     columns, every row `MatchStatus = new`, `Lightspeed ID` and `MatchedRecId` blank.
     A missing supplier
     subsection means "invent no supplier-specific rules", not "produce nothing": apply
     the global rules and record every choice you had to make as an explicit assumption,
     the **cost basis first — and for that one, ASK rather than assume** (step 7). It
     changes every row and precedent runs three ways: dealer-cost-only (Canadian
     Standard), MSRP needing a multiplier (CIF ×0.60, Olympia ×0.564), or both columns
     printed (Biyork). **Once Albert answers, write it into that supplier's subsection
     in bert-airtable-schema under `#### Cost column`** so the question is never asked
     again.
     **This ask now has teeth (2026-09-12):** until that subsection exists,
     `/catalog-sync` leaves `cost_basis` null, and carve-out 3 holds every action on
     the plan. Flag the row `cost_basis_unconfirmed` in the troubled CSV (5a) so the
     question is visible rather than only implied by nothing having been written.
     **Zero rows in Airtable does not mean zero rows in Lightspeed — check Lightspeed
     before treating `Lightspeed ID` as blank** (Albert, 2026-09-11, after Oakel and
     Golden Choice both turned out to be live at the POS; salvaged 2026-09-23 from
     `7e47544`, whose cost-basis half was superseded on 2026-09-12 and is not taken).
     Run `python3 scripts/lightspeed_pull.py --supplier "<Notion Company value>"`, and
     if it returns nothing, retry with only the first word — Lightspeed's
     `supplier_name` is often shorter (`GOLDEN CHOICE` is stored as `GOLDEN`). Every
     live match is the third state below: `MatchStatus` stays `new`, and `Lightspeed
     ID` / `LS Handle / Parent ID` are copied from the live product.
     **Skip the Lightspeed file** only while the products are new to Lightspeed too —
     if `Lightspeed ID`s have been reconciled in from an LS export, build it. See 5.4.
   - **Verify the supplier's documented SKU format against the base before generating
     any SKU.** The skill has been wrong about this (Grandeur, 2026-09-03).
3. **Write the identity fields into the Airtable sheet**, verbatim from the live record
   for every matched row: `SKU`, `LS Handle / Parent ID`, `Lightspeed ID`. Add helper
   columns 58–59, `MatchedRecId` and `MatchStatus` (`matched` / `new` / `ambiguous`),
   for the reviewer to delete before import.
   - A **new** row gets a minted SKU, a minted handle (handle-generating schema,
     alphanumeric, never truncated) and a **deliberately blank `Lightspeed ID`** — LS
     generates that on import. Never invent or placeholder one.
   - A blank `Lightspeed ID` on a `matched` row is a defect; on a `new` row it is
     correct. Judge the Airtable side by `MatchStatus`, never by the cell.

     **Third state — new to Airtable, already live in Lightspeed.** A supplier can be
     absent from the catalogue while its products already exist in Lightspeed (Canadian
     Standard, 2026-09-03: 292 of 336 rows). Those rows are legitimately
     `MatchStatus: new` *and* carry a `Lightspeed ID`. So the LS `id` column is decided by
     **whether a `Lightspeed ID` exists**, never by `MatchStatus`: copy it wherever it is
     present. Judge by `MatchStatus` only for the Airtable side — whether the row creates
     a record or updates one.
4. **Only now build the Lightspeed file**, per `ls-upload-instructions`, reading `id` /
   `handle` / `sku` straight out of that enriched sheet — never from the raw extraction.
   A matched row shipped with a blank `id` makes Lightspeed **create a duplicate instead
   of updating**.
   - **Exception — a new supplier with no Lightspeed presence gets no LS file.** Those three columns are copied from
     the Airtable state, and for a new supplier that state does not exist yet. The LS file
     follows the Airtable import, per the forced order below. One file, not two.
   - **The row still ends with both (Albert, 2026-09-23).** Whatever extraction could
     build, `/catalog-sync` step 5a re-renders the Airtable CSV and the Lightspeed CSV
     from the live systems after the writes, with every SKU's Lightspeed UUID, and
     re-attaches the pair. Build what you can here; never skip the Airtable file.

Cross-check extracted SKU→price pairs against pdfplumber's own text before attaching.

Write both to `ingest/YYYY-MM-DD/` and commit them:
`<supplier>_airtable_upload_YYYY-MM-DD.csv` and `<supplier>_ls_upload_YYYY-MM-DD.csv`.

**Committing them is load-bearing, not tidiness** (2026-09-12). `/catalog-sync` runs
next in this same session and reads these files from the repo — never by downloading
the Notion attachment back, which does not work across a session boundary. If the
commit does not happen, the sync half of the run has no input.

### 5a. Open the troubled CSV

Every row you flag below also gets a line in
`ingest/YYYY-MM-DD/<supplier_slug>_troubled_YYYY-MM-DD.csv` (`outputs.troubled`
*(registry)*), `stage: extract`, per `contracts/troubled-skus-schema.md` — that
contract is authoritative for columns, `reason` vocabulary and `disposition`.

This command **opens** the file; `/catalog-sync` appends its own `stage: sync` rows
and is what attaches it to `Troubled Files`. Do not attach it here — one file per
row, written by both stages, attached once at the end.

If this run produces no troubled SKUs, write no file at all.

**Always emit the `Action` column, always blank.** It is the reviewer's column and
the twelfth of twelve — never write into it, never leave it off because this run
has nothing to ask.

**On a re-run, read the page table's `Action` cells first.** An answer to an
extract-stage row is only actionable here: a row held out of the upload CSV entirely
(the `ambiguous_naming` case) never reaches `/catalog-sync`, so re-extracting is the
only thing that can clear it. Match on `sku`, or on `source_row` where `sku` is
blank, carry every value forward unchanged, and apply nothing whose key matches zero
or more than one row. An answer is input to your extraction decision, not
authorisation to write anything — see `contracts/troubled-skus-schema.md`, "The
`Action` column".

**This command writes no platform.** It does not touch Airtable or Lightspeed. Never
report either as imported — `/catalog-sync`, running next, is what writes them.

## 6. Attach both files, then set the row's state

**Stamp `Last Agent Activity Date` on every write to the row (Albert, 2026-09-24).**
Every `update-page` this command makes on a Price Lists row — properties, file
attachments, the page-body table — carries, in that same call,
`"date:Last Agent Activity Date:start": "<now, America/Toronto ISO with offset>"` (computed at the moment of the call — `TZ=America/Toronto date -Iseconds` — never typed by hand) and
`"date:Last Agent Activity Date:is_datetime": 1`. A page-body `replace_content` call
cannot set properties, so follow it with a one-property stamp. Never write
`Since Last Agent Edit`; it is the formula that reads this date back as "3 hours ago".
Registry key: `write_properties.last_agent_activity`.

`Extracted Files` is a Notion **`file`** property — upload natively, do not paste a
link.

**Every file on the row is a `.csv`. Always** (Albert, 2026-09-09). No `.xlsx` on a
Notion row — not as a second copy, not as a highlighted "review copy" beside the CSV.
That includes an `ls-id-backfill` output — its match-status and match-notes columns
survive fine as CSV, and only row highlighting is lost. An LS export *arriving* as
`.xlsx` is fine; that is input. Hand a workbook to the person directly if they ask
for one; never attach it to the row.

```bash
# 1. create-file-upload -> gives upload_url + auth header
# 2. POST the bytes, WITH the real MIME type or Notion 400s on a content-type mismatch:
CSV="text/csv"
curl -sS -X POST "<upload_url>" -H "authorization: Bearer <token>" \
     -F "file=@<name>.csv;type=$CSV"
# success = HTTP 200 with "status":"uploaded"
# 3. update-page: "Extracted Files": [{"type":"file_upload","file_upload":{"id":"<id>"}}, ...]
```

`api.notion.com` must be allowed by the environment's egress policy (it is, since
2026-09-03). If the CONNECT is refused, report the blocked host — do not route around it.

**Attach first, re-fetch to confirm both files are present, then set state.** The write
key is **`Extraction Status`**, not `Status`, and the option names below are the live
ones — a status property rejects an option it does not have and takes the whole
`update_properties` call down with it, so a stale name loses the entire state write, not
just that field. Read the option list off the data source if a write is rejected.

- `Extraction Status` = `Extracted [Needs Review]`
- `Airtable Sync` = `Pending` — always; the run produced a file Airtable does not reflect
- `New Products` = count of `MatchStatus = new` (`0` if none)
- `UUID Backfill` = `Pending` if that count ≥ 1, else `Not needed`
- `Review Reason` = **every reason this row needs a human check**, from
  `price_lists.status_values.review_reason`. `Extraction Status` says *that* a review is
  needed; this says *why*, and it is the only one of the two you can filter a worklist
  on. Multi-select — set all that apply, a file routinely trips several:
  - **`New Supplier`** — the catalogue read returned **zero rows** for this supplier.
    Always set it. Nothing on the file has been reconciled against a live record, so
    **every detail needs a human check before upload** — spec confidence and cost
    confidence are separate questions and neither is earned yet.
  - **`Ambiguous Pricing`** — more than one candidate cost column, or a number whose
    role is not printed. The default still applies (printed price = cost,
    `Retail = Cost + $ 1.00`); say in `Notes` which column you took.
  - **`Ambiguous Naming`** — a row that did not resolve 1:1 (`MatchStatus: ambiguous`).
  - **`Unmapped Category`** / **`Unmapped Grade`** / **`Spec Gap`** — no LS leaf maps;
    grade shorthand with no canonical mapping; a flooring row with no `Box size (sf)`.

  **Add, never clear.** The catalogue-sync run adds to this property too, and only the
  reviewer removes an option, as each one is resolved.

  Every reason set here also produces a line in the troubled CSV (5a) naming the
  specific SKUs. `Review Reason` is the filterable category at row level; the CSV is
  the per-SKU detail behind it. Neither replaces the other.
- `Notes` = **the flag line, or leave empty.** Write it only when the reviewer must know
  something before importing: a cost basis assumed rather than confirmed, a placeholder
  price, a schema field the base lacks, specs copied from a sibling, or a conflict with
  stored data. Terse, one line per issue, worst first, naming the affected SKUs, prefixed
  with the run date. **Overwrite it; never append.** An empty `Notes` means "nothing
  blocking" — do not fill it with counts or match rates, those are already in
  `New Products` and the trackers. It does not replace the escalation task (step 7); it
  is the pointer visible when scanning the database.

**Never write a completion value to any of the three trackers, and never touch
`LS Upload`** — the person (later, the agent) who does the import, the upload or the
backfill writes those. The downstream order is forced: `Airtable Sync` completes →
`LS Upload: Done` → `UUID Backfill: Done`, because a new product has no Lightspeed ID
until the POS upload creates one.

**`Airtable Sync` has no plain `Done` option** (verified live 2026-09-10; the prose here
said otherwise until then). Its completion values are `Done: Updated` and
`Done: New List UUID`. Take every tracker's option list from
`price_lists.status_values` *(registry)* rather than from memory — a status or select
property rejects an option it does not have and takes the whole call down with it.

**If the run cannot finish — the download failed, the file is not a parseable price
document, `Company` or `Tags` could not be determined, an attachment upload or a
property write was rejected — set `Extraction Status` = `Extracted [Error]` and put the
reason in `Notes`**, naming the step it failed at and what it needs to proceed. Never
leave a row at `Extracting` after the run ends: that reads as still-in-flight and hides
the failure. Never leave a row reading `Extracted [Needs Review]` with an empty
`Extracted Files` — that claims there is something to review when there is not —
**except the step 5 "not a price list, but has real content" case, where `Notes`
says explicitly why there are no files instead of leaving that silent.**

`Extracted [Error]` is for a run that did not produce what it should have. A run
that finished but carries assumptions stays `Extracted [Needs Review]` with those
assumptions in `Notes`.

**This command writes only those two.** `Extracted [All Uploaded]` is `/catalog-sync`
step 6's to write, once nothing on the plan is held. `Not Needed` stays a person's.

`Extracted [Ready to Upload]` is now **vestigial on this path** (2026-09-12): sync runs
immediately after this command in the same session and no longer waits for anyone to
set it. It remains available for the manual CSV path, where a person running a stage
by hand still marks it.

## 7. Escalate anything you could not determine

(Note the spacing in `$ 1.69` above: a dollar sign immediately followed by a single
digit is consumed as a positional argument when this command runs, and the token is
replaced by the caller's text. Keep a space after every `$` in prose.)

**The cost basis is always one of these on a new supplier, and on any supplier whose
sheet shows more than one candidate cost column.** Do not infer it from the numbers —
a range like $ 1.69–$ 6.99/sf reads equally well as dealer cost or as budget retail. Name the columns
as printed, say which you would otherwise take as cost, and ask Albert to look at the
file. Extraction may proceed; the import waits. Record his answer in the supplier's
`#### Cost column` subsection so the next run inherits it.

Create a row in the **✅ Tactical Tasks List** using `escalation` *(registry)* — its
`data_source`, `assignee_notion_person_id` and `defaults` (`Priority`, `Tags`,
`Verification`) — with `url` pointing at the Price Lists row, and Notes recording what
you tried and what the document showed. Send a PushNotification as well — the task is
the durable record, the push is the alert.

## 8. Report

Row counts by `MatchStatus`; how many matched rows carry a `Lightspeed ID`; how many new
products await one (so whoever imports knows the backfill loop is open); SALE/promo items
and how they were handled; anything flagged for Albert; and anything that did not fit the
supplier's documented rules — report those rather than guessing.

If step 5 classified the row as not a price list: say so plainly, name the tag
applied and the company-profiles.md entry written, or — for the no-content case —
that the Notion page was archived and why. Never fold either outcome into an
otherwise-quiet "nothing outstanding" report; both are always stated.
