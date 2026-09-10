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

## The approval file

`plans/YYYY-MM-DD/catalog-approval-<supplier-slug>.json`. Written by a person (or by
a command on a person's explicit yes), never by the reconciler.

```json
{
  "contract_version": "catalog-approval-1",
  "supplier": "Lee Flooring",
  "plan": "plans/2026-09-10/catalog-plan-lee_flooring.json",
  "approved_by": "Albert",
  "decisions": [
    {"id": "cat-11fa9eeb853e", "status": "approved", "at": "2026-09-10T09:20:00-04:00"},
    {"id": "cat-146ca21a4386", "status": "rejected", "at": "2026-09-10T09:20:00-04:00"}
  ]
}
```

| Field | Notes |
|---|---|
| `plan` | Path of the plan these decisions belong to. A writer must check it matches the plan it was handed |
| `decisions[].id` | An action `id` from that plan |
| `decisions[].status` | `approved` \| `rejected`. Anything else is not an approval |

Rules, and they are absolute:

- **Absence of this file means nothing is approved.** Not "approve everything", not
  "ask again later". A writer with no approval file executes nothing.
- An action executes **only** if its `id` appears here with `status: "approved"`.
  An id missing from `decisions` is not approved.
- **Partial approval is normal**, and a writer must handle it without complaint —
  approving 222 of 231 rows is a perfectly ordinary outcome.
- A `blocked` entry carries no `id`, so it cannot be approved even by mistake.
- Approvals are per-plan and expire with it. A re-run produces a new plan; the old
  approval does not carry over. Action ids are stable across re-runs *by design*,
  so a writer must compare `plan` paths rather than assuming matching ids mean a
  matching plan.

### Why ids are stable, and what that buys

An action `id` is `cat-<sha1[:12]>` over supplier + sku + target_system + op, so the
same logical change gets the same id on every re-run. That is what makes resume work
without new machinery: a writer reads today's `actions-log.json` first and skips any
id already recorded `executed`. A run interrupted by a rate limit resumes by simply
being run again.

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

### `sfb_not_exposed`, and why it blocks

Every row carrying a `Box size (sf)` must expose it somewhere a person can read at the
POS. Staff convert boxes to square feet off that number constantly, and a row that
shows it nowhere is unusable at the counter — but the gap is invisible until someone
needs it and can't find it.

Lightspeed allows one name per variant family, so where it goes depends on the group:

| Row | sf/b lives in |
|---|---|
| Singleton, no-grade, or a grade group whose members all box the same | the shared **name** |
| **Grade** group with **mixed** box sizes | **both** — the combined `18.19/20.18sf/b` in the shared name, and this row's own value in `variant_option_one_value` |
| **Size** group (tile) | **`variant_option_one_value`** only |

The mixed grade case is both, and that is not redundancy — the two hold different
facts (Albert, 2026-09-10). A combined string is identical on every row, so name
identity still holds, and it states that the family boxes two ways: a standing prompt
to confirm with the supplier which one the product really is. Column 11 says which of
the two *this* grade is, which is what a staff member needs to convert the box in
front of them. Dropping the name half loses the flag; dropping the column-11 half
loses the number. Tile is exempt from the name half because there the variant
dimension *is* size — box sizes differ by construction, so there is nothing ambiguous
to raise, and a six-size family would carry six numbers in its name.

The reconciler decides uniform vs mixed by grouping the upload's rows on
`LS Handle / Parent ID`; a row cannot answer it about itself.

**Enforced always, variant groups included** (Albert, 2026-09-10). The rule was
already written in `ls-upload-instructions`; nothing checked it, and
`ENG-VIDR-0038` sat live in Lightspeed named
`… | 7.5" x 3mm x RL` with no sf/b at all. Per-piece items — accessories, STONE,
mosaics — legitimately have no box size and are exempt.

## What a write may set

Narrower than it looks, and deliberately so.

**A Lightspeed `update` writes prices and nothing else** — `supply_price` and
`price_excluding_tax`. The wider payload is destructive:

- `name` is **not** Airtable's `Product name`. Lightspeed holds a constructed name
  (`GRNDENG - Scandinavia European White Oak (Bora Bora) T&G | 6.5" x 19.05mm x RL
  - 1.2mm top - 20.83sf/b - Select`) built by the ls-upload-instructions skill from
  a dozen columns, against Airtable's `Grandeur 6.5" EWO — Bora Bora (ABC)`.
  Writing the Airtable value would rename every product in the POS — and Lightspeed
  identifies products *by name*.
- `supplier_name` is not safe either. Airtable says `Grandeur`, Lightspeed says
  `GRANDEUR`, and the live account already holds 116 supplier names for far fewer
  real suppliers. Writing it risks renaming or forking one.
- `product_category` is unresolved — see `category_unresolved` above.

**A Lightspeed `create` takes its payload from the skill-built LS upload CSV**,
keyed by `sku`, because the name and category cannot be derived from the Airtable
columns. Without that file the row is blocked as `ls_payload_unavailable` rather
than guessed.

### Price mapping

Verified against every row of the Grandeur and Lee uploads present in Lightspeed —
315/315 on both fields, 2026-09-10:

| Airtable | Lightspeed API |
|---|---|
| `Cost/unit` | `supply_price` |
| `Retail price/unit` | `price_excluding_tax` |

There is no `retail_price` field on the API; that name belongs to the CSV importer
alone. Prices are stored **tax-exclusive** — `price_including_tax` equals
`price_excluding_tax` on 100% of the 12,548 active priced products, never 1.13×,
because Ontario HST is applied at checkout by the outlet's Default Tax rule.
**Never write `price_including_tax`.**

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
| `sku_missing` | No SKU. Usually a new product still awaiting one — under RULE 0 Titan mints the SKU at record creation and no automated process may generate it |
| `sfb_not_exposed` | The row's `Box size (sf)` would be unreadable in Lightspeed — nowhere at all, or, on a mixed-box-size grade group, missing from either half of the required name + variant-value pair |
| `ls_payload_unavailable` | The SKU is new to Lightspeed and no skill-built `<supplier>_ls_upload_<date>.csv` row was supplied — see **What a write may set** |

## `warnings`

`{sku, reason, detail}`. Advisory. Warnings never withhold an action.

| Reason | What it means |
|---|---|
| `category_unresolved` | The Airtable `Category` does not correspond to a Lightspeed leaf on its own |
| `airtable_side_not_planned` | No live Airtable snapshot was supplied, so the plan contains no Airtable actions at all |

`airtable_side_not_planned` is not a caveat on the Airtable actions — it means there
are none. The upload CSV records Airtable as it stood when the price list was
processed, not now. On 2026-09-10 planning from it claimed 50 Lee rows needed a
`Lightspeed ID` backfill when the live base was missing exactly 5; the other 45 had
been filled in since. A plan that overstates by 10x on the very case it exists to
catch is worse than no plan, so the reconciler emits nothing for Airtable rather than
emitting a guess with a warning attached.

The Lightspeed side is unaffected — it is reconciled against the live catalogue pull,
not against the CSV. Pass `--airtable-existing` with a snapshot read through the
Airtable MCP tools to plan the Airtable side.

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

**A blocked row never reaches the write phase**, and produces no action at all.
Every row yields actions *or* a block — never both, never neither. That invariant
is easy to break, since an Airtable action can be emitted before a later
Lightspeed check decides the row is unwritable, leaving a half-executed row inside
an approved plan; `TestRowInvariant` asserts the partition holds.

Partial execution is correct and expected: 222 good rows go, 9 stop, and the 9
come back as a Tactical Task.

## An action only exists if it changes something

A Lightspeed update whose prices already match the live product is not emitted. On
the Grandeur file every price already agreed, so the plan proposes 0 Lightspeed
writes and only the Airtable work that is genuinely outstanding. A plan is a list
of changes, not a list of rows.
