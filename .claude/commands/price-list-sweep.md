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

## 4. Report, then publish

One line per row run (PL, company, lane, result, writes per system), then counts
for: held (waiting on a person), staged (with dates), queued for tomorrow, errors,
backlog. Then the routine's publish step. **Push a notification only when something
was written, held or failed** — a quiet morning stays quiet.
