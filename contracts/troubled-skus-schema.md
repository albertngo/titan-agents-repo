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
  **One exception: the `Action` column is carried forward, never regenerated** — see
  "The `Action` column" below.
- **Accompanied by a table in the Notion page body**, rendered from the same rows.
  That table is where a reviewer answers; the attachment is not editable in place.
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
| `Action` | **The reviewer's column.** Always present, always written blank by a run, never read as an instruction. See "The `Action` column" below |

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

## The `Action` column

**Keep the page table small enough to answer (2026-09-25).** PL-372's table held all 337 rows, about 180K characters. Albert answered it, but had to paste his answers back in pieces, and fetching the page overflows a tool read. From now on the page table renders only rows a reviewer might act on: every `held` row, plus `wrote_flagged` rows whose reason is not purely routine. `category_unresolved` and `new_supplier` are routine; they stay in the attached CSV, and the table says how many were left out. Notion's API also caps a single rich-text run at 2,000 characters and an append at 100 blocks, so keep `detail` short.

**Added 2026-09-21 (Albert), after it was invented by hand.** On PL-377 he pasted the
troubled CSV into the Notion page as a table, added a twelfth column called `Action`,
and answered all five rows in it. That worked, and nothing in this repo knew about it:
no column, no read-back, no step in either command. This section makes it the
supported loop rather than a thing that happened to work once.

### The rules

1. **A run always emits the column, and always emits it blank.** Even when every row
   is `wrote_flagged` and nothing needs an answer. A column that appears only when a
   run predicts it will be needed is a column a reviewer cannot rely on finding.
2. **A run never writes into an `Action` cell, and never clears one.** It is the one
   column owned by a person. A run that has nothing to put there is correct; a run
   that puts its own reasoning there has taken the reviewer's only channel and
   started talking to itself.
3. **An `Action` cell is prose, and prose is not an approval.** This is the important
   one. Read it as *input to a decision*, never as authorisation to write. Whatever
   an answer resolves, the resulting action still has to appear `approved` in
   `plans/YYYY-MM-DD/catalog-approval-<supplier-slug>.json` before an `*-actions`
   agent touches it. That invariant is the whole reason this pipeline can run
   unattended, and a free-text cell on a Notion page is exactly the kind of thing
   that would quietly dissolve it.
4. **It does not move the carve-outs.** `ambiguous_pricing` and a null `cost_basis`
   still hold, whatever the cell says, because the durable home for a cost decision
   is that supplier's `#### Cost column` subsection in **bert-airtable-schema** — the
   place the *next* run reads. An answer here prompts that edit; it does not
   substitute for it. Anything else and the same question gets re-answered every
   time the list arrives.
5. **Answers survive a re-run.** See below — this is the one exception to the
   overwrite rule.

### Where it is answered

The CSV on `Troubled Files` is not editable in place, so the answering surface is a
**table in the Notion page body**, rendered from the same rows. The run writes that
table; the reviewer fills in `Action` cells; the next run reads them back.

**Never render a literal `|` into a cell of that table.** `col_printed` is
`|`-separated in the CSV (above), and a pipe inside a Markdown table cell splits the
row — Notion then widens the whole table to the longest row and every column after the
split is off by one on the rows that contain it. Escaping it as `\|` does **not**
survive; the escape reaches Notion as a literal backslash and the cell still splits.
Substitute a separator when rendering — ` · ` reads correctly — and leave the CSV's
`|` alone, since that is what the contract specifies and what a re-read parses.
Observed on PL-377, 2026-09-22: two `ambiguous_pricing` rows turned a 12-column table
into 13.

The attachment stays the durable artifact and the property stays the worklist filter.
The table is the working surface, and the two are generated from one source, so they
cannot disagree about anything except the `Action` column — which only ever exists on
the table.

### Carrying answers forward

"Overwritten on re-run, never appended to" (above) still governs every other column.
`Action` is exempt, and has to be:

- **Before writing the file or the table, read the existing page table.** Match each
  prior row to a current one and carry its `Action` value across unchanged.
- **Match on `sku`.** Where `sku` is blank — a `sku_missing` row, or a row held out of
  the upload entirely — match on `source_row` instead.
- **If a key matches zero or more than one current row, carry nothing and say so.**
  Never guess which row an answer belonged to. Same rule as two publication
  candidates in one window, and for the same reason: a wrong join here silently
  applies a person's decision to a product they were not looking at.
- **Never delete or overwrite a non-empty `Action` cell**, under any instruction.

A run that drops an answer has done the one thing this column exists to prevent,
and it does it invisibly — the reviewer sees a table, answers it, and watches the
answer not take effect with nothing to indicate why.

### When the CSV is clean but the table is not

A clean run writes no CSV and attaches nothing, per the rule above. It also
**leaves any existing page table alone** — it does not delete it, and it does not
delete the answers on it. The table can therefore outlive the file that produced
it. That is deliberate: `Troubled Files is not empty` remains the worklist filter, and
a stale table beside an empty property means the work was finished, not that the
signal is broken. Removing a person's annotations to tidy up is not a run's call.

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
| `cross_check_failed` | `scripts/pricelist_extract.py` exited 1: pdfplumber extracted a monetary value that pypdfium2/PDFium cannot see anywhere in the document. Two independent engines disagree on a figure, so the extraction is void. **File-level** — see below |

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
| `brand_missing` | The row's Lightspeed `create` needs a Brand with no live entity. Brand creation is a person's decision, never automated (Albert, 2026-09-13, after a duplicate "Home's Pro" supplier was created without checking first) — `lightspeed_push.py` refuses rather than mint one. Added 2026-09-14 (IMPRESSIVE), the first supplier to reach a Lightspeed create whose brand had no live match |
| `supplier_option_missing` | The row's Airtable write names a `Supplier` value with no live select-option match. `airtable-actions-agent` refuses rather than silently mint one — see "Creating a select option" in bert-airtable-schema. Added 2026-09-14 (IMPRESSIVE), the first supplier whose Airtable side reached execution before its Supplier value was confirmed |
| `select_option_missing` | Pre-flight (2026-09-23). An Airtable select value other than `Supplier` has no live option. Held on both systems, same as `supplier_option_missing` |
| `ls_supplier_missing` | The row's live Lightspeed product has no supplier, so its cost cannot be written (`lightspeed_write.py` refuses to invent a purchasing relationship). Held on both systems until a person sets the supplier in Lightspeed. Added 2026-09-24 (PL-170 Baltic, EHDP-003 — created 2025-08-26 with no supplier) |
| `not_yet_effective` | The list takes effect after today (its `Effective Date`, Albert 2026-09-25). `catalog_reconcile.py` blocks every row, so nothing is written to either system; `/price-list-sweep` applies the list on the day against a fresh pull of both. `held`, but not a TODO for a person: it clears itself when the date arrives |
| `absent_from_list` | A live Airtable record for this supplier that the new price list does not print at all. Nothing is written — neither system has a delete or deactivate action type, deliberately — so the product stays live at its last price until a person decides whether it is discontinued. `held`: a TODO, since the price it sells at is no longer backed by any current list. Added 2026-09-24 (PL-376 Weiss: the 6mm 12 mil line, 3 colours, is gone from the Sept 21 2026 list) |

`airtable_side_not_planned` is deliberately **not** here. It is plan-level, not
SKU-level — it means the plan contains no Airtable actions at all — so it belongs in
`Notes`, not in a file whose unit is one SKU.

### `cross_check_failed` — also file-level

Same shape as `pdf_tooling_unavailable` below: one row, `sku` and `product_name`
blank, `stage: extract`, `disposition: held`, `detail` listing the values the two
engines disagreed on.

A figure that only one of two independent engines can see is a parse defect, and
a parse defect invalidates the whole sheet — not just the row it appeared on,
because nothing establishes that the rest parsed correctly either. So the
extraction produces no upload CSVs, `Extraction Status` is `Extracted [Error]`,
and `/catalog-sync` does not run.

**Never resolve this by choosing the more plausible value.** The point of running
two engines is that neither gets a casting vote. Fix the input or the parse.

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
| `absent_from_list` | `held` | Nothing to write — there is no deactivate action — but the product still sells at a price no current list supports |
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

- **Answer the `Action` cell on the page table** → the next run reads it back and
  uses it to resolve the row. This is the normal route, and the only one that does
  not require touching the repo. It still does not approve anything: the resolved
  row goes through the plan and the approval file like any other, and the two
  pricing reasons below are explicitly not resolvable this way.
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
