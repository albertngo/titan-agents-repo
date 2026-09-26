# Troubled Tags Contract — troubled-tags-1

The exception report for one `/style-tag` run. One CSV per scope per run:

```
ingest/YYYY-MM-DD/<scope>_style_troubled_YYYY-MM-DD.csv
```

Committed to the repo, and attached to the scope's standing Notion row's
**`Troubled Files`** property (`platform-settings/pricelist-sources.json` →
`price_lists.write_properties.troubled_files`; the row itself is described in
`platform-settings/style-tags.json` → `notion_row`).

Sibling of `contracts/troubled-skus-schema.md`, and deliberately a separate contract
(D3, 2026-09-26): the unit here is a **SKU × field**, not a SKU, and the columns a
reviewer needs — which field, what was proposed, how sure, from what — are not the
pricing columns. Everything about the `Action` column is inherited from that
contract by reference and restated below only where the key differs.

## What this is for

Same trade as the price-list report: the run does not stop and ask before it writes.
This file is the per-tag record of everything it could not do cleanly — the colour
tags it held for want of a swatch, the finish it could not map, the spec and the image
that disagreed — and of what it wrote carrying a flag. It is the only place a person
sees what an unattended run declined to guess at, so it is load-bearing.

## When it is written

- **Written by `scripts/style_tag_plan.py --troubled-out`**, not by a model following
  prose — every row comes from the plan's `held` and `flagged` lists, so the file and
  the plan cannot disagree.
- **Written whenever the run produced at least one row.** Not written at all on a
  clean run: no headers-only file, no empty attachment. An empty `Troubled Files`
  means nothing needs a person.
- **Overwritten on re-run**, like the plan. The current file describes the current
  state of that scope's tags, not its history. **One exception: the `Action` column
  is carried forward, never regenerated** — see below.
- **Accompanied by a table in the Notion page body**, rendered from the same rows.
  That table is where a reviewer answers; the attachment is not editable in place.

## Columns

| Column | Notes |
|---|---|
| `supplier` | Airtable `Supplier` value, verbatim |
| `sku` | Airtable `SKU`. Half of the join key |
| `product_name` | Airtable `Product name`, so the row is legible without a lookup |
| `field` | The style field this row is about — `Undertone`, `Tone depth`, `Texture`, `Style`, `Busyness` — or `Swatch images` on an `image_misfiled` row. The other half of the join key |
| `reason` | From the vocabulary in `contracts/style-plan-schema.md`, "Held reasons". **Never free prose** |
| `disposition` | `held` \| `wrote_flagged`. The column that decides whether this is a TODO or an FYI |
| `proposed` | The value the run would have written, if it had one: an option string, an int for `Tone depth`, `\|`-joined for a `Style` list or a `spec\|image` conflict pair. Blank when nothing could be proposed |
| `confidence` | 0–1, two decimals, of `proposed`. Blank when there is none |
| `source` | Where `proposed` came from: `spec`, `image`, `both`, `hint`, `detail_images`, `reviewer` |
| `detail` | One line of human specifics: the finish as stored, which image, what the two sides said |
| `action_id` | The plan action `id` a `wrote_flagged` row belongs to. Blank on `held` rows, which carry no id by construction |
| `Action` | **The reviewer's column.** Always present, always written blank by a run except for values carried forward, never read as an instruction to write |

## `disposition`

| Value | Meaning | To a reviewer |
|---|---|---|
| `held` | Nothing was written for this SKU × field | **A TODO.** Answer it, or fix the cause and re-run |
| `wrote_flagged` | It was written, from a rule marked provisional | **An FYI.** It is live as `AI suggested`; check it when confirming the record |

Held rows sort first.

## The `Action` column

The same column, the same loop, the same five rules as
`contracts/troubled-skus-schema.md` "The `Action` column" — Albert invented it by hand
on PL-377 and it was made the supported channel on 2026-09-21. Restated for this file:

1. **A run always emits the column.** Even when every row is `wrote_flagged`.
2. **A run never writes into an `Action` cell, and never clears one.** It is the one
   column owned by a person; a run that has nothing to put there is correct.
3. **An `Action` cell is prose, and prose is not an approval.** Read it as *input to a
   decision*. What it can do here is narrower and more useful than in the price-list
   loop: it can **supply the value** — `Undertone: Warm` — and the next run then writes
   that tag as `source: reviewer`, confidence 1.0. It still goes through the plan and
   the approval file like any other tag: the id has to appear `approved` in
   `plans/YYYY-MM-DD/style-approval-<scope>.json` before `airtable-actions-agent`
   touches it, and under `write_mode: plan_only` nothing is written at all. A cell
   reading "yes go ahead" supplies no value and is reported `answer_unparsed`.
4. **It never writes `Staff confirmed`** (D5). A reviewer-supplied value lands as
   `AI suggested` with the evidence line naming the reviewer's answer; confirming is a
   person's click in Airtable.
5. **Answers survive a re-run** — the one exception to the overwrite rule.

### The answer grammar

Read narrowly, never fuzzy-matched:

| Cell | Effect |
|---|---|
| `Undertone: Warm` | Sets that field's value for that SKU. Field names and option strings match case-insensitively to the live spelling; `Tone depth` takes an integer 1–5 |
| `Undertone: Warm; Tone depth: 3` | Several, `;`-separated. Each applies to the field it names, for that SKU |
| `Cool` | A bare option name is taken for the row's field when it belongs to exactly one target field. `Rustic` belongs to `Texture` and `Style`, so it is `answer_unparsed` |
| `skip` | Stop proposing this field for this SKU. Reported `reviewer_skipped` and carried forward so the decision stays visible |
| anything else | `answer_unparsed`, carried forward, reported with why |

### Where it is answered

The table in the Notion page body, rendered from these rows by `/style-tag` step 7.
**Never render a literal `|` into a cell** — `proposed` is `|`-joined here and a pipe
splits a Markdown table row in Notion; substitute ` · ` when rendering and leave the
CSV alone (observed on PL-377, 2026-09-22).

### Carrying answers forward

- **Before writing the file or the table, read the existing page table** (`/style-tag`
  step 0) into `ingest/<date>/<scope>_style_answers.json`.
- **Match on `sku` + `field`.** That pair is unique in this file by construction, so a
  key matches one current row or none.
- **If a key matches zero current rows, carry nothing and say so** — the answer is
  listed in the plan's `summary.answers_unmatched` and the run's report, never
  guessed onto another row. A field that was answered *and written* no longer has a
  row (it is not blank any more), which is the normal way an answer leaves the table.
- **Never delete or overwrite a non-empty `Action` cell**, under any instruction.

### When the CSV is clean but the table is not

A clean run writes no CSV and attaches nothing, and **leaves any existing page table
alone**. Removing a person's annotations to tidy up is not a run's call.

## Notification

A run that produces this file **sends a PushNotification**, always, naming the scope,
`write_mode`, and the written / held / flagged counts. A clean run stays silent.
