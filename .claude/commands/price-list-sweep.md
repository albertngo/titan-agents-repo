# /price-list-sweep

Walk the Price Lists rows and run, on each, the one skill it is ready for. No
argument. It is the **scheduled fire of the "New Price Lists" routine** (a fire with
no `notionID`; Albert, 2026-09-25: "the sweep should handle catalogue sync and
effective date and any other 'ready to have the respective skill run'"). Runnable by
hand at any time too.

A row's properties are its state, and the state says which skill is next. The sweep
never decides anything a person should — it only notices a row is ready and runs the
command that row's state calls for, exactly as a person would type it.

## 1. Read the rows — read only

Query `price_lists.data_source` *(registry)* once. Today = `TZ=America/Toronto date +%F`.

## 2. Classify each row into at most one lane, first match wins

| Lane | A row is ready when… | Runs |
|---|---|---|
| **A. Answered** | `Extraction Status = Extracted [Ready to Upload]` — a person answered the troubled table / `Action` cells and asked for a re-run | `/catalog-sync <id>` |
| **B. Effective today** | `Extraction Status = Extracted [Needs Review]` **and** `Airtable Sync = Pending` **and** `Effective Date` is set and ≤ today **and** `Extracted Files` is not empty — a staged list whose day has come, or an extraction whose sync never ran | `/catalog-sync <id>` |
| **C. Missed extraction** | `Extraction Status = Not started` **and** `Files & media` is not empty **and** `Email Date` is within the last **14 days** — a webhook fire that never ran (routine off, fire lost) | `/process-price-list <id>`, then `/catalog-sync <id>` — the same pair a webhook fire runs |

Everything else is left alone and only counted in the report:

- `Airtable Sync = Partial` without `Ready to Upload` — **held rows waiting on a
  person**. Re-running would re-hold the same SKUs and re-send the same push every
  morning. The person sets `Ready to Upload` when they have answered; that is lane A.
- `Effective Date` after today — **staged**; list it with its date.
- `Extracted [Error]` — needs a person, never retried blind.
- `Not started` older than 14 days — the historical backlog (≈200 rows on 2026-09-25).
  Extracting an old list automatically could write old prices over newer ones; a
  person decides those, one by one.
- `Needs Review` + `Pending` with **no** `Effective Date` — rows from before the
  property existed (2026-09-25). A person runs them by hand; the sweep does not guess
  their date.

## 3. Run the lanes — oldest first, one row at a time

Order: lane C, then B, then A; within a lane, oldest `Effective Date` (else `Email
Date`), then lowest `ID`. So two lists from one company land oldest first, and the
catalogue ends on the newest.

- **At most 5 rows per sweep.** Anything beyond is reported as "queued for
  tomorrow". A sweep that tries forty rows is a runaway, not a backstop.
- Each command runs **in full, as written** — its own gates still apply: extraction's
  pdfplumber gate, `/catalog-sync` step 0a (a list not yet in effect stops there;
  a list older than one already applied for the same company stops there too), the
  three pricing carve-outs, the approval file. The sweep adds no permission a manual
  run would not have.
- One row failing never stops the next. Record which step it failed at.

Each command closes its own row as it always does (`/catalog-sync` step 6 moves a
fully written row to `Extracted [All Uploaded]`, or leaves `Needs Review` + `Partial`
when something is held), so a row handled today does not match any lane tomorrow.

## 3P. The promo lane — every sweep, after the rows

Albert, 2026-09-26: the `(P)` marker "goes in when the promo goes in, and leaves when
it goes out. During the sweep." Airtable keeps every promo (`Promo cost`, `Promo end
date`, `Promo List URL`) and never clears it; Lightspeed is derived from it each
morning. Runs after the rows, so a promo list synced this morning is already in
Airtable. Not counted against the 5-row cap.

1. **Fresh pull:** `python3 scripts/lightspeed_pull.py --refresh` (a sync this morning
   changed Lightspeed after the cached walk).
2. **Full Airtable read** of Master Flooring Catalogue, fields by id
   *(`airtable-master-catalogue-fields.json`)*: `SKU`, `Lightspeed ID`, `Cost/unit`,
   `Promo cost ($/sf)`, `Promo end date`, `Promo List URL`, `Supplier`. `pageSize`
   8000 and follow `nextCursor` to the end — **every record**, because a record
   missing from the read looks like "no promo" and would lose its marker. Flatten to
   `{"total_record_count": N, "records": [{id, <field name>: value}]}` at
   `ingest/<today>/airtable-promo-snapshot.json` (gitignored; the plan is the record).
3. `python3 scripts/promo_sweep.py --airtable-raw <every saved MCP page>` (or
   `--airtable ingest/<today>/airtable-promo-snapshot.json` once flattened)
   → `plans/<today>/catalog-plan-promo-sweep.json`. It refuses a partial read.
4. **`status: ready`** → write `catalog-approval-promo-sweep.json` approving every
   action, `approved_by: "policy: promo lane (2026-09-26)"`; `lightspeed_push.py
   --dry-run`, then live. **`status: needs_person`** (over 50 actions) → write
   nothing, report the counts and push. A person approves it by hand or not at all.

What the lane does, per Airtable record with a promo (active = promo cost set and end
date on/after today):

| Lightspeed | Promo active | Promo over |
|---|---|---|
| `supply_price` | the promo cost | back to `Cost/unit` — **only if Lightspeed still holds the promo cost** (any other mismatch is `/catalog-sync`'s) |
| name | `(P YYYY-MM-DD) ` prefix | prefix removed |

A promo with **no end date counts as over** (Albert, 2026-09-26: every promo is dated,
strictly) and is reported `promo_end_missing` — date it in Airtable to turn it on.

Never touched: retail, Airtable, anything but the marker in a name. A variant-family
member gets its price but no marker (the name is family-wide) — `marker_on_variant`.
A `(P)` product that matches no Airtable record is left alone. There is no `PROMO`
tag in the account yet; the lane does not create one.

**A verbal extension** = move `Promo end date` forward in Airtable. The next sweep
re-dates the marker and, if it had come off, restores the promo cost.

## 4. Report, then publish

One line per row run (PL, company, lane, result, writes per system), then counts
for: held (waiting on a person), staged (with dates), queued for tomorrow, errors,
backlog. Then the promo lane: markers on / off, prices on / off, blocked, and
**"Promos ended in the last 14 days — ask the rep"**: one line per SKU from the plan's
`recently_ended` (supplier, promo cost vs regular, end date, `Promo List URL`).

Then the routine's publish step. **Push a notification only when something
was written, held or failed** (the promo lane's writes and a `needs_person` plan
included) — a quiet morning stays quiet.
