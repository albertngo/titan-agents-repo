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
        → bert-airtable-schema → extract
        → match live catalogue → SKU + LS Handle + Lightspeed ID into the sheet
        → airtable_upload.xlsx
        → ls-upload-instructions (reads THAT file) → ls_upload.xlsx
        → both attached to Notion "Extracted Files"
        → Status: Extracted [Pending Review] → human imports both
```

The LS file is downstream of the reconciled Airtable file, never parallel to it — see
"Order of operations" below.

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

## The routine writes no platform — it exports two files

**Decided 2026-09-03 (Albert).** The routine does not write to Airtable, and
Lightspeed has no API here anyway. Every run ends with **two .xlsx files attached to
the Notion row's `Extracted Files`** — the Airtable upload and the LS upload — and
`Status = Extracted [Pending Review]`. A person does both imports.

`Extracted Files` is a Notion **`file`** property, so the files are uploaded natively
(`create-file-upload` → POST bytes → `update-page` with a `file_upload` reference).
An earlier draft of step 7 said to paste a OneDrive share link into it; that does not
match the schema.

### The upload recipe (two traps, both resolved 2026-09-03)

Verified working end-to-end from a cloud session. Both hurdles below were hit on the
first attempt, so expect them.

**1. `api.notion.com` must be allowed by the environment's egress policy.** The Notion
MCP tools reach Notion over the MCP transport, but `create-file-upload` hands back an
`api.notion.com` URL the run must POST the bytes to *directly*. Without that host
allowed, the proxy denies the CONNECT before the request reaches Notion:

```
curl: (56) CONNECT tunnel failed, response 403
status → connect_rejected  host: api.notion.com:443
```

Added to the environment's network policy on 2026-09-03 and the denial is gone. If it
returns, `curl -sS "$HTTPS_PROXY/__agentproxy/status"` names the blocked host — do not
route around a policy denial, report it.

**2. Send the correct MIME type on the multipart part.** curl labels a `-F` file part
`application/octet-stream` by default, and Notion rejects that against the content
type registered at `create-file-upload`:

```
400 validation_error — Current file content type of `application/octet-stream`
does not match the original content type of `application/vnd...spreadsheetml.sheet`
```

Append `;type=<mime>` to the `-F` argument:

```bash
XLSX="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
curl -sS -X POST "<upload_url>" -H "authorization: Bearer <token>" \
     -F "file=@<name>.xlsx;type=$XLSX"
```

A `200` with `"status":"uploaded"` is the success signal. Then pass each
`file_upload_id` to `update-page`:

```
"Extracted Files": [{"type":"file_upload","file_upload":{"id":"<id>"}}, …]
```

The upload URL is short-lived (~10 min) and single-part uploads cap at 20 MiB —
neither binds for these files (~49 KB and ~34 KB). Re-fetch the row afterwards and
confirm the attachments are present before setting `Status`.

Not writing does **not** remove the need to read the catalogue first — see below.

## Check the supplier exists first

Query the Master Flooring Catalogue (`appWHOVZ0QCS0xQ3M` / `tblfLXD3zkSdNQGbS`)
filtered to that supplier. The answer decides what the exported file *is*:

- **Rows returned** → the file is an **update sheet** and must carry the existing
  SKUs. See the cascade below.
- **No rows** → the file is a fresh import sheet. The supplier's select option, SKU
  suffix, cost column and markup overrides have to be settled first — see the skill's
  new-supplier onboarding checklist.

## Order of operations — reconcile before you build anything

**Decided 2026-09-03 (Albert).** Matching comes first, and the identity fields are
written into the Airtable schema file before the LS file exists:

1. Extract into the 57-column schema (`Length` joined it at column 17 on 2026-09-03).
2. Match every row against the live catalogue (cascade below).
3. For each matched row, copy from the live record **verbatim**: `SKU`,
   `LS Handle / Parent ID`, `Lightspeed ID`. New rows mint a SKU and handle and leave
   `Lightspeed ID` blank — LS assigns it on import.
4. Build the LS file from that enriched sheet, copying `id` / `handle` / `sku` out of
   it.

Both defects on the 2026-09-03 Grandeur run come from skipping step 3: the SKUs were
generated rather than read back (231 rows matching nothing), and the LS file was built
with `id` blank on all 231 rows, which would have duplicated 212 live LS products.
Each one is silent — the file looks complete and imports without error.

**A matched row with a blank `Lightspeed ID`, or a handle that differs from the stored
one, means step 3 did not run.** Both are cheap to assert; assert them.

### The three identity fields are born in different places

`SKU` and `LS Handle / Parent ID` are **ours** — we mint both for a new product, and
the handle is uploaded to Lightspeed, which adopts it. `Lightspeed ID` is
**Lightspeed's** — it does not exist until LS generates it on import, so a new
product's id is *correctly* blank, and judged by `MatchStatus`, never by the cell
being empty.

**Step 5 — reverse-populate the generated ids, batched.** A new product is finished
when its id is back in Airtable, not when the import succeeds. Skip it and a later run
reads a blank id for a product that now exists in LS and duplicates it — the same
silent failure, one cycle later.

**Decided 2026-09-03 (Albert): the backfill is batched, not per-price-list.** One
Lightspeed product export covers many lists' new products at once, so it runs
periodically (`ls-id-backfill` — export from LS, match on `SKU`, write the UUIDs in).

Batching means the debt outlives the run that created it, so it is tracked on the
Notion row rather than remembered. See the full state model below.

## Row state — what is still owed after a run

A run produces files; it does not change Airtable or Lightspeed. Everything downstream
is tracked on the row, because it happens later and (for now) by hand.

| Property | Written by | Values |
|---|---|---|
| `Status` | run, then whoever finishes it | `Extracted [Pending Review]` after the files land; `Done` only when everything below is resolved |
| ~~`Extracted`~~ | — | **Removed from the data source 2026-09-03.** It duplicated `Status = Extracted [Pending Review]`. Writing it now fails the whole `update-page` call with a `validation_error`, so do not reintroduce it. |
| `New Products` | the run | count of `MatchStatus = new` rows, `0` if none |
| `Airtable Sync` | run, then importer | `Pending` · `Done` · `Not needed` |
| `POS` (checkbox) | whoever uploads to Lightspeed | checked = the LS file has been pushed to the POS |
| `LS Backfill` | run, then backfill | `Pending` · `Done` · `Not needed` |

**The run always leaves `Airtable Sync = Pending`** — it has produced a file Airtable
does not yet reflect. It sets `LS Backfill = Pending` when it minted ≥1 new product,
else `Not needed`. **A run never writes `Done` to either, and never touches `POS`** —
it does not upload anything.

### The three actions happen in this order, and the order is forced

```
Airtable Sync: Done  →  POS ✅  →  LS Backfill: Done
   import the file      push LS file    export from LS, write
   into Airtable        to the POS      the UUIDs back
```

Not a convention — a dependency:

- The LS file's identity fields come from the Airtable-synced state, so importing
  second would push Lightspeed values Airtable does not yet agree with.
- **A new product has no Lightspeed ID until the POS upload creates it.** So there is
  nothing to back-fill until `POS` is checked.

That last point sharpens the backfill worklist: **`LS Backfill is Pending` AND
`POS` is checked** is the actionable set. A `Pending` row whose `POS` is unchecked is
not waiting on you to run the backfill — it is waiting to be uploaded. Filtering
without the `POS` condition sends you looking for UUIDs that do not exist yet.

Two worklists, then:

- `Airtable Sync is Pending` — files attached, Airtable not yet updated to match.
- `LS Backfill is Pending` **and** `POS` checked — products live in LS whose ids are
  not back yet.

`New Products` is the cross-check on the backfill: it states how many UUIDs that row
should yield, so a partial backfill shows up instead of passing silently.

### `Airtable Sync` can go backwards — that is the point

`Airtable Sync = Done` means **Airtable currently mirrors the file attached to this
row**. It is a statement about agreement between two things, not a step that was once
completed.

So: **edit the upload file and re-attach it, and the row goes back to `Pending`.** A
reviewed-and-corrected file is a new pending change; leaving it `Done` because it was
imported once is exactly how Airtable silently drifts from what the row claims. This is
also why the import is *not* a `Status` value — `Status` moves forward, this does not.

`Not needed` covers a file reviewed and deliberately not imported (rejected, or the
list turned out to hold no real changes).

**If a re-attached file also changes what Lightspeed should hold, uncheck `POS` as
well** — the same reasoning applies one step downstream. A corrected file that only
touches Airtable-side fields leaves `POS` alone.

Set `Status = Done` only when `Airtable Sync` is `Done`/`Not needed`, `LS Backfill` is
`Done`/`Not needed`, and any LS upload the row needed has happened. Until then the row
still owes something.

### When the agent takes this over

Both trackers are written by whoever performs the action — today a person, later the
agent once it is trusted to import to Airtable and upload to Lightspeed itself. The
fields do not change when that happens; the writer does. That is the reason to record
state on the row now rather than rely on memory: the handover needs no rework, and an
autonomous run is auditable against the same two filters.

Once a record holds an id and a handle, Airtable owns both. No automation overwrites
them; only an explicit instruction from Albert to swap in a specific matching set
does. Full statement: RULE 0a in the `bert-airtable-schema` skill.

## RULE 0 — the Airtable SKU never changes

The stored `SKU` (`fldx3byCOht5HbKmH`) is **immutable and the source of truth**.
Every export, upload file, Lightspeed record and downstream system matches **to** it;
nothing matches the other way, and no process writes it on an existing record. A SKU
that looks wrong is escalated, never edited — changing one orphans the LS record and
every Price History Log v2 row pointing at it. Full statement: RULE 0 at the top of
the `bert-airtable-schema` skill. It has no exceptions.

## For an existing supplier, the export is an UPDATE sheet, not an import

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

**Never ship a SKU generated during the run for a product that already exists.**
Tier 1 means the stored SKU, looked up live. Extraction renumbers per run, so a
generated SKU duplicates the catalogue instead of updating it. Two runs have now hit
this:

| Run | Extraction emitted | Airtable actually holds |
|---|---|---|
| GreenTouch 2026-09-01 | `LVP-GRNT-0001…0010` | `LVP-GRNT-0073…0082` |
| Grandeur 2026-09-03 | `GRNDENG-0001`, `GRNDLVP-0001` | `ENG-GRAN-####`, `SPC-GRAN-####` |

GreenTouch resolved at tier 2 (sequential supplier codes). **Grandeur could not** —
only 10 of its 239 records carry a `Supplier SKU` — so it resolved at tier 3 on
`Product name`, which uses the same convention on both sides
(`Grandeur 7.5" EWO — Moonfrost (ABCD)`). Expect tier 3 to be the normal path for
suppliers who publish no codes.

The Grandeur case was worse than a renumbering: the skill's Grandeur subsection
documented the wrong SKU *format* (`GRND` prefix), so no generated SKU could ever
have matched. **Verify a supplier's documented SKU format against the live base
before trusting it** — the skill is not authoritative about what is actually stored.

- Carry the matched record's existing SKU verbatim into the export, and record
  `MatchedRecId` + `MatchStatus` (`matched` / `new` / `ambiguous`) as helper columns
  the reviewer deletes before import.
- New products continue the live numbering for their category prefix — never restart
  at 0001, never reuse a number already present.
- Note the base can carry **legacy prefixes** the current schema no longer issues
  (Grandeur holds `SPC-GRAN-####` / `WPC-GRAN-####` vinyl; the schema now issues
  LVP/LVT). Match against what is stored; issue new SKUs per the current rule.
- Fields that changed, `Last price update`, `Price last changed by` = **`Cowork`**,
  and the Price History Log v2 rows are all still the *reviewer's* import job — the
  routine no longer performs them. Keep the values correct in the exported sheet.
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
several rows, and they are tagged per attachment: 24 subjects in the database carry
*both* tags across 55 rows (Vidar's "…price list and monthly promotion price list"
pattern, Tosca's "NEW Price List and July Clearance List", Floordi, Weiss, Lee,
Impressive). The payload hands you one `notionID` = one file. Classify that file.

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
