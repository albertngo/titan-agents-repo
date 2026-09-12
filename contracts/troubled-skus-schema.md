# Troubled SKUs Contract — troubled-skus-1

The exception report for one price-list row. One CSV per supplier per run:

```
ingest/YYYY-MM-DD/<supplier_slug>_troubled_YYYY-MM-DD.csv
```

Committed to the repo, and attached to the Notion row's **`Troubled Files`**
property (`price_lists.write_properties.troubled_files` *(registry)*).

## What this is for

**Decided 2026-09-12 (Albert).** The pipeline no longer stops and asks before it
writes. That trades a human gate for a human *report*, and this file is that report —
the durable, per-SKU record of everything the run could not do cleanly.

It is the only place a person can see what went wrong on an unattended run, so it is
load-bearing, not decoration. `Review Reason` says a row has problems; this says
which products and what.

Its predecessor was a chat digest nobody read on a run with no human present.

## When it is written

- **Written whenever the run produced at least one troubled SKU** — held or flagged,
  either stage.
- **Not written at all on a clean run.** No headers-only file, no empty attachment.
  An empty `Troubled Files` property means nothing went wrong, which is what makes
  `Troubled Files is not empty` a usable worklist filter.
- **Overwritten on re-run**, like an ingest file and like the plan — never appended
  to. The current file describes the current state of that row, not its history.
  (`actions-log.json` remains the append-only record of what was actually written.)
- Both stages write into the **same** file for a given run. Stage 1 opens it, stage 2
  appends its own rows before the file is attached. One row, one file, both stages.

## Columns

| Column | Notes |
|---|---|
| `supplier` | Airtable `Supplier` value, verbatim and mixed-case. Present so files from several suppliers can be concatenated and stay valid |
| `sku` | Airtable `SKU`. The join key back to the upload CSV, the plan and the catalogue. Blank only for `sku_missing`, where there isn't one yet |
| `product_name` | Airtable `Product name`, so the row is legible without a second lookup |
| `stage` | `extract` \| `sync` — which half of the run raised it |
| `reason` | From the vocabulary below. **Never free prose** |
| `disposition` | `held` \| `wrote_flagged` — see below. The column that decides whether this is a TODO or an FYI |
| `detail` | One line of human specifics: which columns as printed, which value was taken, which SKU the UUID really belongs to |
| `action_id` | The plan action `id` this row corresponds to, where one exists. Blank on `blocked` rows, which carry no id by construction |
| `source_row` | 1-based row number in the supplier's upload CSV, so the row can be found in the source file without searching |
| `col_printed` | For pricing ambiguity: the candidate columns as printed on the sheet, `|`-separated. Blank otherwise |
| `value_used` | For pricing ambiguity: the number actually taken as cost. Blank otherwise |

`col_printed` and `value_used` are pricing-specific and blank on most rows. They earn
their place because a wrong cost is the one error that is silent *and* monetary — it
does not look broken, it just sells at the wrong margin — so the two facts a reviewer
needs to adjudicate it belong in the file rather than one hop away.

## `disposition`

The most important column, and the reason this is one file rather than two.

| Value | Meaning | What it is to a reviewer |
|---|---|---|
| `held` | Nothing was written for this SKU, in either system | **A TODO.** It is not live and will not be until someone acts |
| `wrote_flagged` | It was written, and it carries something worth knowing | **An FYI.** It is already live; verify when convenient |

Sorting on this column puts the actual work at the top. Mixing the two without
distinguishing them is what makes an exception report get ignored: a list where most
entries need no action trains a reader to skip all of them.

## `reason` vocabulary

Fixed. A run picks from these, and adds a new one only by editing this contract —
the same discipline as `blocked` reasons and `Review Reason` options, and for the
same purpose: a reader learns to recognise a fixed set, and never has to interpret a
sentence a run improvised.

### Stage `extract`

| Reason | Meaning |
|---|---|
| `ambiguous_pricing` | More than one candidate cost column, or a number whose role is not printed. `col_printed` / `value_used` carry the specifics |
| `cost_basis_unconfirmed` | The cost basis was assumed rather than recorded — no supplier subsection states it. Distinct from `ambiguous_pricing`: there the sheet is ambiguous, here the sheet is clear and the *convention* is unrecorded |
| `ambiguous_naming` | `MatchStatus: ambiguous` — did not resolve 1:1 against the live catalogue |
| `unmapped_category` | The `Category` corresponds to no Lightspeed leaf on its own |
| `unmapped_grade` | Supplier grade shorthand with no canonical mapping. `Grade` left blank, supplier wording preserved |
| `spec_gap` | A flooring row missing something the upload cannot invent — most often a blank `Box size (sf)` |
| `sku_format_mismatch` | The supplier's documented SKU format disagrees with the live base. The skill has been wrong about this before (Grandeur, 2026-09-03) — never silently reconciled |
| `new_supplier` | Zero existing Airtable rows for this supplier. Row-level, so every SKU on the file carries it |
| `pdf_tooling_unavailable` | `pdfplumber` could not be imported, so the price list could not be read by the only sanctioned method (Albert, 2026-09-12). **File-level, not SKU-level** — see below |

### Stage `sync`

Mirrors `catalog-plan-schema.md` exactly — every `blocked` reason, plus the one
warning that is SKU-scoped.

| Reason | Meaning |
|---|---|
| `uuid_collision` | The same `Lightspeed ID` appears on more than one row of this upload |
| `uuid_belongs_to_other_sku` | Lightspeed holds that UUID against a **different** SKU |
| `uuid_not_in_lightspeed` | The row carries a UUID Lightspeed does not know |
| `handle_collision_on_create` | A create whose handle is already held by a different SKU |
| `ambiguous_match` | `MatchStatus: ambiguous`, or `LS Match status: AMBIGUOUS` / `DUPLICATE` |
| `sku_missing` | No SKU. Under RULE 0 no automated process may mint one |
| `sfb_not_exposed` | The row's `Box size (sf)` would be unreadable in Lightspeed |
| `ls_payload_unavailable` | New to Lightspeed with no skill-built LS upload row to create it from |
| `category_unresolved` | Carried over from the plan's `warnings`. Always `wrote_flagged` — a warning never withheld a write, before this file existed or after |

`airtable_side_not_planned` is deliberately **not** here. It is plan-level, not
SKU-level — it means the plan contains no Airtable actions at all — so it belongs in
`Notes`, not in a file whose unit is one SKU.

### `pdf_tooling_unavailable` — the one file-level row

This reason is the exception to "one row per SKU", because when it fires there are no
SKUs: nothing was read, so nothing was extracted. Write **exactly one row** with
`sku` and `product_name` blank, `stage: extract`, `disposition: held`, and `detail`
naming the concrete failure (`ModuleNotFoundError: pdfplumber`, or
`host_not_allowed: pypi.org` if an install was attempted).

That single row is the whole file, and it is the only case where the troubled CSV is
written while `Extracted Files` stays empty — there are no upload CSVs to attach,
by design. `Extraction Status` is `Extracted [Error]`, and `/catalog-sync` does not
run: a sync needs an upload file, and inventing one is the failure this exists to
prevent.

**Never** resolve this reason by extracting the PDF some other way. See
`/process-price-list` step 2.0 for the prohibited substitutes and why the list is
explicit.

## Which reasons hold, and which write anyway

This is the auto-approval rubric in `catalog-plan-schema.md`, expressed as it lands
in this file. The rubric there is authoritative; this table is the reader's view of it.

| Reason | Disposition | Why |
|---|---|---|
| Every stage-`sync` `blocked` reason | `held` | Structural. The reconciler emits no action and no id, so there is nothing that *could* be written |
| `ambiguous_pricing` | `held` | A wrong cost is silent and monetary. The one flag worth stopping for |
| `cost_basis_unconfirmed` | `held` | Same failure, one step earlier: if nobody has said what the printed numbers mean, every price on the file is a guess |
| `ambiguous_naming` | `wrote_flagged` | Visible and correctable by a follow-up diff |
| `unmapped_grade`, `unmapped_category`, `spec_gap`, `sku_format_mismatch` | `wrote_flagged` | Annoying, visible, not monetary |
| `new_supplier` | `wrote_flagged` | **Reversed 2026-09-12 (Albert)** — see below |

### The `new_supplier` reversal, stated plainly

`/catalog-sync` 2a says a new supplier's every row needs a human check before upload,
because nothing on the file has been reconciled against a live record. **That is no
longer enforced by stopping.** Albert's decision, 2026-09-12: a new supplier's rows
write, and the check happens after the fact, from this file.

The residual risk is real and worth stating rather than burying: a new supplier's
specs have never been verified against anything, so a wrong spec now goes live and
is found later, or not at all. What remains in place against that is narrow — the two
pricing reasons above still hold, so a new supplier whose cost basis is unrecorded
still writes nothing at all, which is the case that would otherwise be most expensive.

Anyone reconsidering this should read 2a first, not this table.

## Resolving a `held` row

The loop is: fix the cause, re-run `/catalog-sync <notionID>`, and the row stops
being held.

- `ambiguous_pricing` / `cost_basis_unconfirmed` → record the decision in that
  supplier's `#### Cost column` subsection in **bert-airtable-schema**, exactly as
  `/process-price-list` step 5 already prescribes. The next reconcile reads it, the
  row is no longer ambiguous, and it auto-writes.
- Every `blocked` reason → fix the underlying data (the upload CSV in
  `ingest/<date>/`, or the live catalogue) and re-run. **Never by editing the plan** —
  a blocked row has no id to approve and adding one by hand defeats the check.
- Or approve it manually: name the ids in
  `plans/YYYY-MM-DD/catalog-approval-<supplier-slug>.json` and re-run. Blocked rows
  cannot be cleared this way; nothing can approve a row that has no id.

## Notification

A run that produces this file **sends a PushNotification**, always, naming the
supplier and the `held` / `wrote_flagged` counts. A file is passive; without the ping
the trouble is durable but silent, which is the failure this whole design exists to
prevent.

A clean run — no file — stays silent.
