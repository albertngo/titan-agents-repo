# /catalog-sync `<notionID>`

Take one processed Price Lists row from two attached CSVs to a mirrored catalogue:
Airtable and Lightspeed holding the same products with the same ids.

Picks up exactly where `/process-price-list` stops. That command produces files and
writes no platform; this one writes both — **behind one approval gate in the middle**.

```
/process-price-list  ->  2 CSVs on the Notion row   (writes nothing)
                              |
        [1] pull  ->  [2] reconcile  ->  one plan   (writes nothing)
                              |
                     [3] A PERSON APPROVES
                              |
        [4] Lightspeed writes  ->  [5] Airtable writes  ->  [6] Notion trackers
```

**Steps 1–2 are safe to run unattended. Steps 4–6 are not, ever.** Actions agents are
never scheduled and never autonomous (`CLAUDE.md`, agent class rules); they execute
approved ids and originate nothing. A run that reaches step 3 with no human present
stops there and notifies. That is a complete, successful run — not a failure.

## Before you start

Required as environment variables — a gitignored `.env` file **or** the cloud
environment's own env vars (Albert, 2026-09-10: this session's environment injects
them directly; `scripts/lightspeed_client.py` reads via `os.environ.get()`, so either
source works identically and neither needs code changes):

```
LIGHTSPEED_DOMAIN_PREFIX=flooru
LIGHTSPEED_PERSONAL_TOKEN=lsxs_pt_...
```

**The token is still admin-equivalent and not scopable — no read-only variant
exists.** That fact doesn't change with where the value is stored. A cloud env var is
visible to anyone with access to this environment's configuration (`CLAUDE.md`'s
Secrets section: "treat anything there as visible") — wider exposure than a
gitignored file most people never open. The mitigations that do still apply
regardless of source: the read scripts (`lightspeed_pull.py`, `lightspeed_client.py`)
contain no write verb and a test enforces that; rotate the token periodically; never
paste its value into a prompt, a committed file, or anywhere else it would be logged
or retained as text.

Egress must allow `flooru.retail.lightspeed.app` and `x-series-api.lightspeedhq.com`.
If either is blocked, **report the blocked host and stop** — never route around it.

Ids, field names and option strings are never in this file. They live in
`platform-settings/lightspeed.json`, `airtable-destinations.json` and
`pricelist-sources.json`.

---

## 1. Pull the live Lightspeed catalogue — read only

```bash
python3 scripts/lightspeed_pull.py            # ingest/<today>/lightspeed-products.json
```

Cached per day; add `--refresh` to re-walk. Neither this script nor
`lightspeed_client.py` contains a write verb, and a test fails if one is added.

First run in a new environment: `--probe` first. One page, no cache, no output file —
it confirms the envelope and names a missing credential plainly.

## 2. Reconcile into one plan — read only

Read the Notion row for the supplier and the two attached CSVs (mirrored in the repo
at `ingest/YYYY-MM-DD/`). Then take a **live** Airtable snapshot of that supplier's
records — `list_records_for_table` against
`tables.master_flooring_catalogue`, filtered to the supplier — and save it as JSON.

```bash
python3 scripts/catalog_reconcile.py \
  --upload        ingest/<date>/<supplier>_airtable_upload_<date>.csv \
  --ls-upload     ingest/<date>/<supplier>_ls_upload_<date>.csv \
  --airtable-existing ingest/<date>/<supplier>_airtable_existing.json \
  --cost-basis    dealer --confirmed-by "Albert 2026-09-10"
```

Three of those are load-bearing:

- **`--airtable-existing` is not optional in practice.** Without it the reconciler
  emits **no** Airtable actions at all — deliberately. Planning Airtable writes off
  the upload CSV overstated the Lee gap as 50 rows against a real 5, because the CSV
  records the base as it stood when the price list was processed, not now.
- **`--ls-upload`** carries the skill-built name and category. A row new to Lightspeed
  cannot be created without it and is blocked `ls_payload_unavailable`.
- **`--cost-basis`** records what was assumed. **Assume, do not stop** (Albert,
  2026-09-10): the price list's printed prices are the **cost**, and
  `Retail price/unit = Cost/unit + $ 1.00`. A column printed as **MSRP**, suggested
  retail or suggested price goes to **`MAP price ($/sf)`** and never touches
  `Cost/unit`. Pass `--cost-basis printed-as-cost` unless a recorded supplier
  subsection says otherwise.

## 2a. New supplier, and anything the defaults do not cover

**A supplier with zero existing Airtable rows is a NEW SUPPLIER, and every detail on
every row needs a human check before upload.** Say it in those words, first, in
whatever you report. Nothing on that file has been reconciled against a live record,
so spec confidence and cost confidence are both unearned — a plausible-looking row is
not a verified one.

Two structural facts make this self-enforcing rather than a matter of discipline:

- A new supplier gets **no Lightspeed file** — LS columns 1–3 are copied from Airtable
  state that does not exist yet. So the row carries **one** CSV, not two.
- This command needs both. A new supplier therefore **cannot reach the write steps**
  until a person has imported the Airtable file and the catalogue read returns rows.

New suppliers are a deliberate two-pass flow. Report the row, say it is new, and stop.

**Everything else the defaults do not cover is flagged, not stopped and not guessed:**

| Situation | Do |
|---|---|
| More than one candidate cost column, or a number whose role is not printed | Flag, naming the columns as printed and which you took as cost |
| Grade shorthand with no canonical mapping (`A`, `BC`, `Prime` with no context) | Leave `Grade` blank, preserve the supplier's wording, flag |
| Category that maps to no Lightspeed leaf | Flag — the reconciler warns `category_unresolved` |
| A supplier quirk with no recorded subsection | Apply the global rules, record the choice as an explicit assumption, flag |
| A flooring row with a blank `Box size (sf)` | Flag as a data defect — the file cannot invent one |

Flagging means three places, every time:

1. **The plan** — as a `blocked` entry or a `warning`.
2. **`Review Reason`** on the Notion row — the multi-select in
   `price_lists.status_values.review_reason`. **Add to it; never clear it.** Both runs
   write it and only the reviewer clears it, one option at a time as each is resolved.
3. **`Notes`** — the specifics: which SKUs, which columns as printed, which value you
   took. `Review Reason` says what kind of problem; `Notes` says which rows.

`Extraction Status` says *that* a human must look. `Review Reason` says *why*, and is
what makes "sit down and check everything" a filterable queue rather than a judgment
made row by row:

```
Extraction Status is Extracted [Needs Review]
  AND Review Reason contains New Supplier
```

**Never invent a mapping to avoid a flag.** An ambiguity absorbed silently is the one
failure this pipeline cannot detect later.

Output: `plans/YYYY-MM-DD/catalog-plan-<supplier-slug>.json`, per
`contracts/catalog-plan-schema.md`.

## 3. The approval gate — stop here

Present the plan in chat: the `summary` counts, every `blocked` entry with its
reason, and the `before`/`after` on anything whose price moves. Then stop.

- The reconciler **never** creates or pre-populates the approval file.
- **Absence of an approval file means nothing is approved** — not "approve
  everything", not "ask again later".
- **Partial approval is normal.** Approving 222 of 231 rows is an ordinary outcome.
- `blocked` entries carry no `id` and cannot be approved even by mistake. Unblocking
  means fixing the data and re-running step 2 — never editing the plan.
- Plans expire at end of day. A stale plan is re-derived, never re-approved. Ids are
  stable across re-runs by design, so a writer compares `plan` paths, not ids.

On an explicit yes, write
`plans/YYYY-MM-DD/catalog-approval-<supplier-slug>.json` naming the approved ids.

## 4. Lightspeed writes — this changes the live POS

**Dry run first, every time:**

```bash
python3 scripts/lightspeed_push.py --plan plans/<date>/catalog-plan-<slug>.json \
    --approval plans/<date>/catalog-approval-<slug>.json --dry-run
```

That prints every request and sends nothing. Read it, then drop `--dry-run`.

`scripts/lightspeed_write.py` and `lightspeed_push.py` are the **only** two files that
can change the POS. There is no delete or deactivate action type in either system, and
none may be added — removing a product is a person's decision in that platform's UI.

An update writes **prices only**. It never writes `name`: Lightspeed holds a
constructed name that is not Airtable's `Product name`, and sending one renames or
merges live products.

Interrupted by a rate limit or a bad row? **Re-run the same command.** Ids already
`executed` in today's `actions-log.json` are skipped. There is no separate state file.

The run writes `plans/<date>/catalog-backfill-<slug>.json` — `sku_to_lightspeed_id`
for every product Lightspeed just created. That file is step 5's input. **Ids are
never paired positionally** with the request order.

## 5. Airtable writes

Hand the plan, the approval file and the backfill file to **`airtable-actions-agent`**.
It writes through MCP — there is no `airtable_write.py`.

- Upserts merge on `fieldIdsToMergeOn` with **SKU never in the payload** (RULE 0 —
  the SKU is the merge key and is immutable).
- Backfills set `Lightspeed ID` only, on records where it is currently empty.
- Batch caps: 50 records, 10 for the Price History Log.

## 6. Close the Notion row

In dependency order — a new product has no Lightspeed ID until the POS upload makes
one:

`Airtable Sync: Done: *` → `LS Upload: Done` → `UUID Backfill: Done`

Take every option string from `price_lists.status_values`; a rejected option fails the
whole `update-page` call and loses every property in that write. `Airtable Sync` has
**no plain `Done`** — it is `Done: Updated` or `Done: New List UUID`. Set
`Extraction Status = Extracted [All Uploaded]` only once both trackers read a
completion value or `Not needed`.

## Done means

- Every approved action executed or explicitly logged as failed.
- One `actions-log.json` entry per write, with `approved_by` populated and
  `raw_ref_action_id` set.
- Every new product carries a `Lightspeed ID` in Airtable.
- The Notion trackers reflect reality.
- Blocked rows reported by SKU and reason — never silently dropped.

Report honestly. If a step did not run, say which. Never mark a stage complete that
isn't.
