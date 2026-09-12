# /catalog-sync `<notionID>`

Take one processed Price Lists row from two attached CSVs to a mirrored catalogue:
Airtable and Lightspeed holding the same products with the same ids.

Picks up exactly where `/process-price-list` stops — automatically, same session,
same notionID. That command produces files and writes no platform; this one writes
both.

```
/process-price-list  ->  2 CSVs on the Notion row, committed   (writes nothing)
                              |
        [1] pull  ->  [2] reconcile  ->  one plan              (writes nothing)
                              |
     [3] POLICY APPROVES everything except 3 carve-outs; the rest is HELD
                              |
        [4] Lightspeed writes  ->  [5] Airtable writes  ->  [6] Notion trackers
                              |
              troubled CSV  ->  Troubled Files  ->  PushNotification
```

**The whole command runs unattended, end to end.** Steps 1–2 are read-only. Steps
4–6 execute for everything the auto-approval rubric in
`contracts/catalog-plan-schema.md` clears — which, since 2026-09-12, is everything
except three carve-outs: `blocked` entries, `Ambiguous Pricing` rows, and any plan
whose `cost_basis` is `null`.

Actions agents still execute **only** an id that appears `approved` in the approval
file — that invariant did not move. What changed is who writes that file.

Everything held lands in the run's troubled-SKUs CSV
(`contracts/troubled-skus-schema.md`) and triggers a PushNotification. That file is
the human checkpoint now — the run does not stop and wait for one.

## Before you start

Required in `.env` (never a cloud env var — a personal token is admin-equivalent and
not scopable):

```
LIGHTSPEED_DOMAIN_PREFIX=flooru
LIGHTSPEED_PERSONAL_TOKEN=lsxs_pt_...
```

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

Read the Notion row for the supplier, and the two CSVs from where `/process-price-list`
committed them in this repo at `ingest/YYYY-MM-DD/` — **read the repo copy, never the
Notion attachment.** A cross-session download of a Notion-hosted attachment is not
reliably possible (confirmed 2026-09-11: the only download tool available serves
files the current session's own integration uploaded, not a prior session's), which
is exactly why the commit in `/process-price-list` is load-bearing now. If the repo
copy is genuinely missing, that is a broken hand-off, not something to route around
by attempting a Notion download — report it and stop. Then take a **live** Airtable
snapshot of that supplier's records — `list_records_for_table` against
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

  **Where "assume, do not stop" does NOT reach (2026-09-12).** That decision covers a
  sheet with one obvious cost column. It was never meant to cover a **new supplier
  with no recorded `#### Cost column` subsection**, where precedent genuinely runs
  three ways — dealer-cost-only (Canadian Standard), MSRP × multiplier (CIF ×0.60,
  Olympia ×0.564), both columns printed (Biyork) — and the choice changes every
  price on the file. In that case pass **no** `--cost-basis`, leave it `null`, and
  carve-out 3 holds the whole plan until someone records the answer.

  This distinction is load-bearing now. Defaulting to `printed-as-cost` on a new
  supplier would set `cost_basis` on every plan, so carve-out 3 would never fire and
  a wrong cost basis would write 200 wrong prices unchallenged.

## 2a. New supplier, and anything the defaults do not cover

**A supplier with zero existing Airtable rows is a NEW SUPPLIER, and every detail on
every row is unverified.** Say it in those words, first, in whatever you report.
Nothing on that file has been reconciled against a live record, so spec confidence and
cost confidence are both unearned — a plausible-looking row is not a verified one.

**This no longer stops the run (2026-09-12, Albert).** It used to: a new supplier was
a two-pass flow and this command reported and halted. Policy now writes these rows,
and the unverified-ness is reported through the troubled CSV as `new_supplier` /
`wrote_flagged` instead of being prevented. The paragraph above still describes the
real risk — read it before widening this further, and see
`contracts/troubled-skus-schema.md`, "The `new_supplier` reversal".

What still holds structurally, independent of policy:

- A new supplier **new to Lightspeed too** gets **no Lightspeed file** — LS columns
  1–3 are copied from Airtable state that does not exist yet, so the row carries
  **one** CSV, not two. Its LS rows block as `ls_payload_unavailable` by
  construction, which no policy can approve past. That case is still effectively a
  two-pass flow; it just reaches that outcome by being blocked rather than by this
  command stopping.
- The **third state — new to Airtable, already live in Lightspeed** (Canadian
  Standard 2026-09-03; HOMESPRO and IMPRESSIVE both) — carries two CSVs and is *not*
  structurally blocked. Those rows write. This is the case the reversal actually
  changes.
- `cost_basis: null` still holds the entire plan, new supplier or not. A new supplier
  whose cost basis nobody has recorded therefore still writes nothing at all.

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

## 3. Approve by policy, hold the carve-outs

**2026-09-11 (Albert), widened 2026-09-12.** Apply the "Policy auto-approval" rubric
in `contracts/catalog-plan-schema.md`. It is authoritative; what follows is how to
run it.

Write every action that is **not** carved out into
`plans/YYYY-MM-DD/catalog-approval-<supplier-slug>.json` yourself, `"status":
"approved"`, and carry it through steps 4–6 in this same session. Every actions-log
entry sets `"approved_by": "policy: auto-approval (2026-09-12 rubric)"`.

**Hold — do not approve — only these three:**

1. Any `blocked` entry. Structural: no `id` exists to approve.
2. Any action whose `sku` carries `Ambiguous Pricing` — this run's or a prior run's
   not yet cleared.
3. Every action on the plan, if `cost_basis` is `null`.

`New Supplier` no longer holds anything (2026-09-12, reversing 2a's stop). Neither
does `Ambiguous Naming`, `Unmapped Grade`, `Unmapped Category`, `Spec Gap`, or any
`warnings` entry — those write, and are reported as `wrote_flagged`.

Everything held goes into the troubled CSV per `contracts/troubled-skus-schema.md`,
`disposition: held`, with its reason and enough detail to act on. That file — not a
chat message — is how a person finds this work. Write the `wrote_flagged` rows too:
what went live carrying a flag matters as much as what didn't go live at all.

The gate's mechanics are unchanged underneath:

- **An action with no id in the approval file is still not approved.** Policy
  approving most things does not make absence mean approval.
- `blocked` entries carry no `id` and cannot be approved even by mistake. Unblocking
  means fixing the data and re-running step 2 — never editing the plan.
- Plans expire at end of day. A stale plan is re-derived, never re-approved. Ids are
  stable across re-runs by design, so a writer compares `plan` paths, not ids.
- A person can still approve anything held, the old way — naming ids in the same
  file, next to whatever policy wrote. Re-run after, and the resolution loop in the
  troubled-SKUs contract applies.

## 3a. Batch approval — for the held residue only

**Decided 2026-09-11 (Albert), narrowed 2026-09-12.** After step 3, what's left is
only the three carve-outs — blocked rows and pricing-ambiguous ones. That residue is
normally small. When several rows carry some, present it all as one digest rather
than one at a time: total counts first, then each supplier's `summary`, every
`blocked` entry with its reason, and price `before`/`after` on anything held.

This is now a *report* in an unattended run, not a wait — the writes already
happened for everything policy cleared. The digest exists so a person reviewing later
(or in a live session) can clear the residue in one reply instead of per supplier.

- **One explicit reply can cover the whole digest** — "approve all," or naming
  exceptions ("approve all except Biyork," "skip the 4 blocked Grandeur rows"). This
  replaces running `/catalog-sync` once per supplier to get to the same decision; it
  does not replace the decision itself.
- Nothing about the gate changes per plan: absence of an approval file still means
  that plan is not approved, partial approval within a supplier's plan is still
  normal, `blocked` entries still carry no `id`, and a stale plan (past end of day)
  is still re-derived rather than re-approved.
- On the batch yes, write one `plans/YYYY-MM-DD/catalog-approval-<supplier-slug>.json`
  per approved plan, in the same step. A supplier left out of the reply gets no
  approval file — silence excludes, same as it always has.
- Steps 4–6 then run per approved plan, each in the existing forced order
  (Lightspeed → Airtable → Notion trackers). One supplier's write failing does not
  block another's — log it and continue, same as any other run.

This changes *how many plans reach this residual gate together and how many replies
it takes to clear it* — it does not touch step 3's policy auto-approval, and it does
not reopen New Supplier plans to anything but a person's yes. This command still
never invokes an actions agent without an approval file naming exact ids — policy's
ids and a person's ids are both real ids in that file, and that's the only thing
either kind of writer ever checks.

## 4. Lightspeed writes — this changes the live POS

**Dry run first, every time — this is a self-check the run performs, not a second
human pause.** Whether the approval file was written by policy or by a person, run
the dry run, read its own output for anything that looks wrong (a price move that
doesn't match the plan, a row that shouldn't be here), and only then drop
`--dry-run` in the same session. Treat a dry-run output you did not actually read as
equivalent to not having run it — the flag doesn't buy safety by itself:

```bash
python3 scripts/lightspeed_push.py --plan plans/<date>/catalog-plan-<slug>.json \
    --approval plans/<date>/catalog-approval-<slug>.json --dry-run
```

That prints every request and sends nothing.

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

**Policy auto-approval routinely leaves a row partially written** — most actions
executed this session, a held row or two still needing a person. That is exactly
what `Done: Updated`/`Done: New List UUID` vs `Partial` already distinguish (added
2026-09-10 for this same shape of outcome) — use `Partial` on `Airtable Sync` /
`LS Upload` / `UUID Backfill` whenever this run wrote some of a supplier's actions
and held others, and leave `Extraction Status` at `Extracted [Needs Review]` rather
than advancing it. Only write `Extracted [All Uploaded]` once nothing on that plan is
held.

## 6a. Write and attach the troubled CSV

Per `contracts/troubled-skus-schema.md` — the contract is authoritative for columns,
`reason` vocabulary and `disposition`.

Collect every troubled SKU from **both** stages — `/process-price-list` opened this
file earlier in the session with its `stage: extract` rows; append this command's
`stage: sync` rows to the same file. Write it to
`ingest/YYYY-MM-DD/<supplier_slug>_troubled_YYYY-MM-DD.csv`
(`outputs.troubled` *(registry)*), commit it, and attach it natively to
**`Troubled Files`** (`write_properties.troubled_files` *(registry)*) — the same
upload recipe as `Extracted Files` in `/process-price-list` step 6, `;type=text/csv`
and all.

- **Not `Extracted Files`.** That property holds the import artifacts; this is the
  exception report, and keeping them apart is what makes `Troubled Files is not
  empty` a usable worklist filter.
- **No troubled SKUs → no file, and nothing attached.** Never a headers-only CSV; an
  empty property is the signal that the run was clean.
- **Then send a PushNotification**, naming the supplier and the `held` /
  `wrote_flagged` counts. Always, whenever the file exists. A file nobody is told
  about is not a checkpoint.

## Done means

- Every approved action — policy's or a person's — executed or explicitly logged as
  failed.
- One `actions-log.json` entry per write, with `approved_by` populated (naming the
  policy string on an auto-approved entry, never a person's name for one) and
  `raw_ref_action_id` set.
- Every new product carries a `Lightspeed ID` in Airtable.
- The Notion trackers reflect reality, `Partial` included where that's what happened.
- **Every troubled SKU is in the CSV, attached to `Troubled Files`, and notified** —
  `held` rows and `wrote_flagged` rows both. A held row that reaches nobody is the
  one failure this design cannot detect later, because there is no longer a gate
  standing behind it.
- Nothing reported as cleared by policy that policy did not actually clear.

Report honestly. If a step did not run, say which. Never mark a stage complete that
isn't.
