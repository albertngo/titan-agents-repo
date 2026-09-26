# /price-list-sweep

Apply every **staged** price list whose day has come. No argument.

A list that arrives before it takes effect is extracted straight away — CSVs built,
committed and attached, the row set to `Extracted [Needs Review]` — but
`/catalog-sync` step 0a stops before writing, because its `Effective Date` is in the
future (Albert, 2026-09-25). This command is what finishes it on the day.

## 1. Find what is due — read only

Query the Price Lists data source (`price_lists.data_source` *(registry)*) for rows
where **all** of:

- `Effective Date` is on or before today in Toronto (`TZ=America/Toronto date +%F`),
- `Airtable Sync` is `Pending` or `Partial`,
- `Extraction Status` is `Extracted [Needs Review]` (the row was extracted and not
  closed; `[Error]` rows need a person, not a sweep),
- `Extracted Files` is not empty.

Oldest `Effective Date` first; within a date, lowest `ID` first — so when two lists
from one company fall due together, the older lands first and the newer one's date is
the one the catalogue keeps.

Rows whose `Effective Date` is still in the future are **not due**: list them in the
report ("staged: PL-382 Triforest, 2026-10-01") and touch nothing.

## 2. Run `/catalog-sync <notionID>` on each due row, one at a time

Each run is the full command — fresh Lightspeed pull, live Airtable snapshot,
reconcile, policy approval, Lightspeed then Airtable writes, CSV re-render, trackers,
troubled CSV. Step 0a now lets it through. Nothing is replayed from an earlier plan.

One row failing never stops the next: record the failure and move on.

## 3. Report

Rows applied (PL, company, effective date, writes by system), rows still staged with
their dates, and rows that failed with the step they failed at. Push a notification
only when something failed or was held.

## Scheduling

Runs as the **scheduled fire of the "New Price Lists" routine** (Albert, 2026-09-25):
a fire with a `notionID` is Make's webhook and extracts that row; a fire without one
is this sweep. Meant for once each morning (Toronto), so a list dated the 1st is live
on the 1st. See `methods/pricelist-pipeline-routine-prompt.md`. Runnable by hand at
any time too.
