# Catalogue Plan Contract — catalog-plan-1

The reviewable diff between a processed price list and the two systems it will
change. One file per supplier per run:

```
plans/YYYY-MM-DD/catalog-plan-<supplier-slug>.json
```

Produced by `scripts/catalog_reconcile.py`. Overwritten on re-run, never appended
to — like an ingest file, and unlike `actions-log.json`.

## What this is for

The pipeline's single approval gate. A person reads one file and answers one
question: *should these changes happen?* Everything downstream executes exactly
what the file says, and nothing else.

That only works if the file is complete and honest about what it does not know,
which is what `blocked` is for.

## The approval boundary

Identical in force to `contracts/plan-schema.md`, and stated again because it is
the whole safety story:

- The reconciler **never** creates, edits or pre-populates the approval file.
- **Absence of an approval file means nothing is approved.** Not "approve
  everything", not "ask again later".
- An actions agent may execute an action **only** if its `id` appears in
  `plans/YYYY-MM-DD/catalog-approval-<supplier-slug>.json` with
  `status: "approved"`.
- Plans expire at end of day. A stale plan is re-derived, never re-approved.
- `blocked` entries carry no `id` and are therefore unapprovable by construction.
  Unblocking means fixing the underlying data and re-running the reconcile.

## Envelope

| Field | Notes |
|---|---|
| `contract_version` | `"catalog-plan-1"` |
| `supplier` | Airtable `Supplier` value, verbatim and mixed-case |
| `run_at` | ISO 8601, America/Toronto |
| `status` | `ok` \| `partial` \| `error`. `partial` whenever `blocked` is non-empty |
| `inputs` | `[{file, run_at}]` — every file the plan was derived from |
| `cost_basis` | `{value, confirmed_by}` or `null`. **Never inferred** — see below |
| `summary` | counts by action kind, plus `blocked` |
| `actions` | ordered; each independently executable and idempotent |
| `blocked` | rows that must not be written, with the reason |
| `warnings` | worth a reader's attention, but not a reason to withhold a write |

`cost_basis` stays `null` until a person answers. A plan for a **new supplier**
with `cost_basis: null` is not approvable — precedent runs three ways
(dealer-cost-only, MSRP × multiplier, both columns printed) and the choice
changes every row.

## Action

| Field | Notes |
|---|---|
| `id` | `cat-<sha1[:12]>` over supplier + sku + target_system + op. **Stable across re-runs** — that is what makes the actions-log idempotency check work |
| `seq` | Execution order. Ascending, gapless |
| `target_system` | `airtable` \| `lightspeed` |
| `op` | `upsert` \| `create` \| `update` \| `backfill_ls_id` |
| `sku` | Airtable `SKU`. The join key across both systems |
| `airtable_rec_id` | `MatchedRecId`, or `null` on a create |
| `ls_id` | The Lightspeed UUID. `null` where Lightspeed will mint one |
| `handle` | `LS Handle / Parent ID` |
| `fields` | What the action writes |
| `before` | Current values for the same keys, where they could be read. `null` on a create |
| `before_unreadable` | Keys in `fields` the live snapshot carried no value for. Present only when non-empty |
| `reason` | Why this action exists — see below |
| `uuid_source` | Where the Lightspeed UUID came from — see below |

`before` and `before_unreadable` are separate on purpose. A reviewer approving a
diff has to be able to tell *"this field was empty"* from *"we could not read this
field"*, and a `null` renders both identically. A key never appears in both.

### `reason` vocabulary

| Value | Meaning |
|---|---|
| `price_change` | Cost or retail moved against the live record |
| `new_product` | Absent from the target system |
| `field_update` | Non-price field changed |
| `uuid_from_create` | Lightspeed will mint the UUID; this action writes it back to Airtable |

### `uuid_source` vocabulary

Kept separate from `reason` because the two are orthogonal: a row can be a routine
price change *and* have had its identity repaired, and a reviewer needs to see both.

| Value | Meaning |
|---|---|
| `upload` | The `Lightspeed ID` came from the upload file and was verified against the live catalogue |
| `recovered_by_sku` | The row's `Lightspeed ID` was **blank**, and the SKU join found the real one. **Repair, not a create** — this is precisely the case that otherwise makes Lightspeed duplicate the product |
| `lightspeed_on_create` | The SKU does not exist in Lightspeed; it will mint the UUID |

`summary.uuid_recovered_by_sku` counts the distinct SKUs repaired this way. It is
worth reading: on the Lee 2026-09-09 file, 50 of 84 rows carry no UUID because the
Lightspeed import that created them happened after the backfill ran. Re-running
that file without this repair would create 50 duplicates.

## Execution order

`seq` follows the forced dependency order, which is not a convention:

1. `airtable` upserts — mint the SKU and handle, and make Airtable the state the
   Lightspeed file is built from.
2. `lightspeed` creates and updates.
3. `airtable` `backfill_ls_id` — a product created in step 2 has no UUID until
   step 2 runs.

## `blocked`

`{sku, reason, detail, rows}`. Never carries an `id`.

| Reason | What it means |
|---|---|
| `uuid_collision` | The same `Lightspeed ID` appears on more than one row of this upload |
| `uuid_belongs_to_other_sku` | Lightspeed holds that UUID against a **different** SKU |
| `uuid_not_in_lightspeed` | The row carries a UUID Lightspeed does not know |
| `handle_collision_on_create` | A create whose handle is already held by a different SKU |
| `ambiguous_match` | `MatchStatus: ambiguous`, or `LS Match status: AMBIGUOUS` / `DUPLICATE` |
| `sku_missing` | No SKU. Nothing can be joined on |

## `warnings`

`{sku, reason, detail}`. Advisory. Warnings never withhold an action.

| Reason | What it means |
|---|---|
| `category_unresolved` | The Airtable `Category` does not correspond to a Lightspeed leaf on its own |

`category_unresolved` is a warning rather than a block because the mapping is
genuinely unsettled, not because it is unimportant. `LVP` and `LVT` name a
**format**, while Lightspeed classifies vinyl by **core and install method** — the
live catalogue holds `SPC`, `WPC`, `GLUE DOWN` and `LOOSE LAY` as separate leaves,
and uses several (`MOULDING`, `HARDWOOD`, `ENGINEERED`) that the documented list
does not cover. Resolving it needs `Material type` and `Install method`, and is
part of the Phase 3 spike. Until then no write path sets a category, so blocking
on it would stop the pipeline for no gain.

### Why these, specifically

On 2026-09-03 a Grandeur backfill matched on colour alone and Lightspeed rejected
9 products with *"handle already exists for your retailer, sku already exists for
your retailer"*. Against the live catalogue, every one of those 9 rows carried a
UUID belonging to a different SKU — `ENG-GRAN-0056` claimed `ENG-GRAN-0050`'s,
`ENG-GRAN-0084` claimed `ENG-GRAN-0076`'s, and so on. Four of them also shared a
UUID with a second row in the same file.

Replaying the broken file against the live catalogue reproduces the incident
exactly as commit `492cb03` recorded it — *"7 UUIDs shared across 16 rows"* — because
each bad UUID collides with the row that legitimately owns it. That is a stronger
result than flagging only the 9 Lightspeed happened to reject: it also catches the
rows whose identity was equally wrong but which Lightspeed processed anyway.

Neither check is possible from the upload file alone; both need the live catalogue
pulled first. `tests/test_catalog_reconcile.py` asserts all of it against the
committed evidence.

**A blocked row never reaches the write phase.** Partial execution is correct and
expected: 222 good rows go, 9 stop, and the 9 come back as a Tactical Task.
