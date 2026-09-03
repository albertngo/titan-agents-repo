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

Load the **bert-airtable-schema** skill (supplier rules, 57-column schema, RULE 0/0a)
and, for step 5, the **ls-upload-instructions** skill. Load them as references; never
pass them arguments.

---

## 1. Read the row

Fetch the page. It is a row in the **Price Lists** data source
`collection://e2dc37bc-63da-42e9-b6c0-63ff48d72e6b`. (Not
`13b596a4505f80fc816aceefcd0de7c4` — that is the parent PAGE, not the database.)

Take `Files & media`, `Email Subject`, `Sender`, `Email Date`, `Company`, `Tags`. The
file property is a `file://{...}` URL-encoded JSON envelope — decode it and take
`.source` for the SharePoint share link.

## 2. Download the actual bytes

```
python3 scripts/pricelist_fetch.py "<share-link>" /tmp/pricelist.pdf
```

Both halves of that recipe are mandatory: `?download=1` (without it SharePoint returns
viewer HTML that saves happily as a `.pdf`) and a curl cookie jar (`-c/-b`; the
redirect chain sets a `FedAuth` cookie the final hop needs — plain `curl -L` gets 403).

**Do not use the Microsoft-365 connector's `read_resource` for the source file.** It
returns Graph's text conversion rather than bytes, which flattens table geometry. Use
pdfplumber on the downloaded bytes.

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

Casing differs per system and is not to be "fixed": Notion `Company` is ALL CAPS
(`GREENTOUCH`), Airtable `Supplier` keeps its own mixed case (`GreenTouch`).

## 4. Tag the row — `Regular List` or `Promo`

`Tags` has exactly two options. **Classify the file in front of you, not the email** —
one email with several attachments becomes several rows with different tags.

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

Confirm the file is a parseable price document. If not, stop here — `Company` and `Tags`
are already set — and say only that it is not a supported price document.

Otherwise, **in this order — it is a dependency, not a preference**:

1. **Extract** into the 57 canonical columns (exact documented order). **Always attempt
   `Length`** (column 17) — text, so `RL` / `48"` / `20" - 83"` are all valid; blank only
   when the supplier never states one.
2. **Read the live catalogue** (`appWHOVZ0QCS0xQ3M` / `tblfLXD3zkSdNQGbS`) filtered to
   that supplier, and match every extracted row: internal `SKU` → `Supplier SKU`
   (partial/fuzzy) → specifications, principally `Product name`. Stop at the first tier
   that resolves cleanly.
   - **Rows returned** → this is an **update sheet**.
   - **No rows** → **new supplier. Still produce the Airtable export** — the canonical
     columns, every row `MatchStatus = new`, `Lightspeed ID` and `MatchedRecId` blank —
     and stop before any import. The onboarding checklist gates the *import*, not the
     extraction, and it is easier to answer with the data in hand. A missing supplier
     subsection means "invent no supplier-specific rules", not "produce nothing": apply
     the global rules and record every choice you had to make as an explicit assumption,
     the **cost basis first — and for that one, ASK rather than assume** (step 7). It
     changes every row and precedent runs three ways: dealer-cost-only (Canadian
     Standard), MSRP needing a multiplier (CIF ×0.60, Olympia ×0.564), or both columns
     printed (Biyork). **Once Albert answers, write it into that supplier's subsection
     in bert-airtable-schema under `#### Cost column`** so the question is never asked
     again.
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

Cross-check extracted SKU→price pairs against pdfplumber's own text before attaching.

Write both to `ingest/YYYY-MM-DD/` and commit them:
`<supplier>_airtable_upload_YYYY-MM-DD.xlsx` and `<supplier>_ls_upload_YYYY-MM-DD.xlsx`.

**This command writes no platform.** It does not touch Airtable or Lightspeed; a person
does both imports from the attached files. Never report either as imported.

## 6. Attach both files, then set the row's state

`Extracted Files` is a Notion **`file`** property — upload natively, do not paste a
link:

```bash
# 1. create-file-upload -> gives upload_url + auth header
# 2. POST the bytes, WITH the real MIME type or Notion 400s on a content-type mismatch:
XLSX="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
curl -sS -X POST "<upload_url>" -H "authorization: Bearer <token>" \
     -F "file=@<name>.xlsx;type=$XLSX"
# success = HTTP 200 with "status":"uploaded"
# 3. update-page: "Extracted Files": [{"type":"file_upload","file_upload":{"id":"<id>"}}, ...]
```

`api.notion.com` must be allowed by the environment's egress policy (it is, since
2026-09-03). If the CONNECT is refused, report the blocked host — do not route around it.

**Attach first, re-fetch to confirm both files are present, then set state:**

- `Status` = `Extracted [Pending Review]`
- `Airtable Sync` = `Pending` — always; the run produced a file Airtable does not reflect
- `New Products` = count of `MatchStatus = new` (`0` if none)
- `UUID Backfill` = `Pending` if that count ≥ 1, else `Not needed`
- `Notes` = **the flag line, or leave empty.** Write it only when the reviewer must know
  something before importing: a cost basis assumed rather than confirmed, a placeholder
  price, a schema field the base lacks, specs copied from a sibling, or a conflict with
  stored data. Terse, one line per issue, worst first, naming the affected SKUs, prefixed
  with the run date. **Overwrite it; never append.** An empty `Notes` means "nothing
  blocking" — do not fill it with counts or match rates, those are already in
  `New Products` and the trackers. It does not replace the escalation task (step 7); it
  is the pointer visible when scanning the database.

**Never write `Done` to any of the three trackers, and never touch `LS Upload`** — the person (later, the
agent) who does the import, the upload or the backfill writes those. The downstream order
is forced: `Airtable Sync: Done` → `LS Upload: Done` → `UUID Backfill: Done`, because a new product
has no Lightspeed ID until the POS upload creates one.

**If the run cannot finish — the download failed, the file is not a parseable price
document, `Company` or `Tags` could not be determined, an attachment upload or a
property write was rejected — set `Status` = `Error: Needs attention` and put the
reason in `Notes`**, naming the step it failed at and what it needs to proceed. Never
leave a row at `Extracting` after the run ends: that reads as still-in-flight and hides
the failure. Never leave a row reading `Extracted [Pending Review]` with an empty
`Extracted Files` — that claims there is something to review when there is not.

`Error: Needs attention` is for a run that did not produce what it should have. A run
that finished but carries assumptions stays `Extracted [Pending Review]` with those
assumptions in `Notes`.

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

Create a row in the **✅ Tactical Tasks List**
(`collection://238596a4-505f-8137-af13-000bde205213`) assigned to Albert
(`c39aa5d3-c87c-4152-92ef-5ed13d9c4605`), with `Priority: high`,
`Tags: ["price list"]`, `Verification: Needs Verification`, `url` pointing at the Price
Lists row, and Notes recording what you tried and what the document showed. Send a
PushNotification as well — the task is the durable record, the push is the alert.

## 8. Report

Row counts by `MatchStatus`; how many matched rows carry a `Lightspeed ID`; how many new
products await one (so whoever imports knows the backfill loop is open); SALE/promo items
and how they were handled; anything flagged for Albert; and anything that did not fit the
supplier's documented rules — report those rather than guessing.
