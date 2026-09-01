# Supplier Price List Extraction

Repeatable method for turning a supplier price list PDF into verified Airtable
pricing. Runs as the "Process New Pricing Files from OneDrive" routine, fired by
Make with a payload of `{"notionID": "<page id>"}` and nothing else — every other
input comes off the Notion row.

Fetch helper: `scripts/pricelist_fetch.py`. Extraction itself is the
`pricelist-processor` agent (carries the `bert-airtable-schema` and
`ls-upload-instructions` skills preloaded).

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

## Airtable is an UPDATE, not an import

The single most expensive trap here. Most suppliers already have their whole
catalogue in Airtable (`appWHOVZ0QCS0xQ3M` / `tblfLXD3zkSdNQGbS`, Master Flooring
Catalogue). A price list is a **price change against existing rows.**

- **Match on `Supplier SKU`** (`fldLOrMqh4aBftjtu`) — the supplier's own code
  (`WB1361`, `SP2801`). **Never match on the `SKU` column**: the extraction skill
  renumbers those per-run (it emitted `LVP-GRNT-0001…0010` where Airtable holds
  `LVP-GRNT-0073…0082`), so matching on it silently duplicates the entire catalogue.
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

## Known blockers (as of 2026-09-01)

- **Make scenario 4382120** maps companies via ~38 hardcoded router branches, not a
  data store. Its blueprint is ~500KB minified / ~1.9MB pretty, and
  `scenarios_update` takes the whole blueprint inline — over this environment's
  limits. **Do not attempt a full blueprint replace**; report the branch that needs
  adding for a human to apply in the Make UI. There is also an orphaned,
  disconnected `greentouch` branch (module id 14) matching on `sender_email`, which
  can never fire: all mail arrives from `info@titanfloors.ca`. Match `email_subject`.
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
