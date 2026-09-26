---
description: Suggest style tags (Undertone, Tone depth, Texture, Style, Busyness) for one supplier's catalogue records from specs and images. Builds a plan, applies policy, writes only what is approved, marks records AI suggested for staff review. plan_only until deliberately flipped.
---

# /style-tag `<SUPPLIER>` [`--sku SKU,SKU…`]

Fill the blank style fields on Master Flooring Catalogue records for one supplier,
from their specs and their images, as `AI suggested` — never touching a record staff
have confirmed. Same shape as `/catalog-sync`: pull → decide → act, with a policy
approval file, a per-item troubled report on a Notion row, and the `Action` column
loop.

```
[0] read back reviewer answers (Notion page table)               read only
[1] Airtable snapshot + option pre-flight  (MCP, saved as JSON)    read only
[2] scripts/style_tag_pull.py   -> candidates + image manifest     read only
                                -> image originals to disk         (fails soft)
[3] the model reads each candidate: images + specs -> judgement file
[4] scripts/style_tag_plan.py   -> plans/<date>/style-plan-<scope>.json + troubled CSV
[5] POLICY approves every action; everything else is held          (approval file)
[6] airtable-actions-agent writes approved tags                    (actions log)
[7] troubled CSV -> Troubled Files -> page table -> PushNotification; commit; PR
```

`<SUPPLIER>` is the Airtable `Supplier` option string, exactly (`FLOORS AT WORK`,
`VIDAR`). Its slug is the **scope** and names every file of the run. `--sku` narrows to
named records for a spot run.

Authoritative procedure. `contracts/style-plan-schema.md` defines the plan, the
approval file, the policy and the judgement file; `contracts/troubled-tags-schema.md`
the report; `platform-settings/style-tags.json` every id, option string, threshold and
rule table; `methods/style-tags.md` the rubric the model judges by. Nothing below
restates a value that lives in one of those.

## Before you start

Check in order and **stop on the first failure**:

1. **`write_mode`** in `platform-settings/style-tags.json`. While it is `plan_only`
   this command runs steps 0–4 and 7 and writes **no approval file and no Airtable
   record**. Do not raise it. Flipping it is a dated decision recorded in the vault.
2. **Airtable is reachable** through the `mcp__Airtable__*` tools — `get_table_schema`
   on the base in the registry returns fields. There is deliberately no API token.
3. **The supplier exists** as a live `Supplier` option (its choice id is what step 1
   filters on). A name that matches nothing is a typo, not a new supplier — stop.
4. **Egress note.** Image originals live on `v5.airtableusercontent.com`, which the
   cloud proxy refused on 2026-09-26. Step 2 fails soft on that; say so in the report
   rather than routing around it. Allow the host in the environment's Network access,
   or run the image steps on Albert's Mac.

## 0. Read back the reviewer's answers — read only

Find the scope's **standing row** in the Price Lists database
(`pricelist-sources.json` → `price_lists.data_source`): the page whose title
(`read_properties.title`) is the registry's `notion_row.title_format` with this
supplier. None yet → nothing to read; step 7 creates it.

If it exists, fetch the page and read the **troubled table in the page body**. Write
every row that has a non-empty `Action` cell to
`ingest/<date>/<scope>_style_answers.json` as `[{"sku", "field", "action"}]`, the cell
text verbatim.

This runs **first** because an answer changes what the plan contains
(`/catalog-sync` step 0 says why). The rules, per `contracts/troubled-tags-schema.md`:

- An answer is **input, not authorisation**. `Undertone: Warm` supplies a value that
  the plan then treats as a reviewer-sourced tag; it still has to appear `approved` in
  the approval file before anything is written, and under `plan_only` nothing is.
- The plan script parses the grammar; you do not. Copy the cell, do not interpret it.
- Match keys are `sku` + `field`. The script reports any answer that matches no
  current row; carry nothing by hand.

## 1. Snapshot and option pre-flight — read only

1. `get_table_schema` for the seven style fields and the `Supplier` field (ids in the
   registry). Save the raw result as `ingest/<date>/<scope>_style_options.json`. Take
   the supplier's choice id from it.
2. `list_records_for_table` on the base and table in the registry, filtered
   `Supplier = <choice id>` **and** `Active = true`, `fieldIds` = every id under the
   registry's `inputs`, `targets`, `status_field` and `evidence_field`, `pageSize`
   2000; follow `nextCursor` until exhausted. Save each raw page as
   `ingest/<date>/<scope>_style_snapshot.json` (`_p2.json`, … for later pages). A
   large result lands in a file — copy that file; never retype records.

**Take every field listed.** A target field missing from the snapshot reads as blank,
and blank is what this command writes into — a narrowed snapshot turns "blank only"
into "overwrite". `style_tag_pull.py` keys cells by field id, so a renamed field still
resolves; a *missing* one does not.

## 2. Pull — read only

```bash
python3 scripts/style_tag_pull.py --snapshot ingest/<date>/<scope>_style_snapshot.json \
    --scope <scope> --download [--sku SKU,SKU]
```

Writes `ingest/<date>/style-candidates-<scope>.json`: the eligible records (active,
flooring category, not `Staff confirmed`, at least one style field blank, some
signal), their specs, which fields are blank, and an image manifest whose `field`
says which Airtable field each attachment sits in — `swatch`, `room` or `detail`.
**That field is the image's kind.** It is a fact, not a guess, and it is what decides
what the image may inform.

`--download` fetches every original to `ingest/<date>/style-images/<sku>/<kind>/`
(gitignored) and writes a `-read.jpg` beside each for step 3. Read the summary line:
`images … host_blocked` means the proxy refused the attachment host — the run
continues spec-only and the plan holds the colour tags as `image_host_blocked`. Say
so in the report. Never work around it.

## 3. Judge — the model's read of each candidate

For every candidate, read its `read_path` images and its specs and write one entry to
`ingest/<date>/style-judgements-<scope>.json`, per `contracts/style-plan-schema.md`
"The judgement file". Batch as many records as fit comfortably; the file is committed
as the audit trail of what you saw. The rubric — what `Warm` means, the tone-depth
anchors, the busyness ladder, what each `Style` implies — is `methods/style-tags.md`.

Discipline, because the plan script will enforce it anyway:

- `attachment_id` in `from` is one from the manifest. Never invent one.
- `undertone` and `tone_depth` cite a **swatch** attachment. If the record has no
  usable swatch, omit them — a room scene's colour is the room's lighting.
- `texture_seen` cites a **detail** close-up. `busyness_seen` a swatch or a detail.
- For every image you looked at, record `looks_like` honestly. A room photo somebody
  uploaded into `Swatch images` is `looks_like: room`; the plan then reports it as
  `image_misfiled` and reads nothing from it.
- `style` may be proposed from specs alone on a record with no images; it will be held
  `needs_image`. Do it when the specs genuinely say something; skip when they do not.
- Confidence is yours to state and the threshold is 0.7; 0.9+ means you would be
  surprised to be wrong. Do not inflate to clear the bar — a held row with a good
  `proposed` value is one click for a reviewer; a wrong tag written is a wrong tag.

A record with no images and nothing to say about `Style` needs no entry.

## 4. Plan — read only

```bash
python3 scripts/style_tag_plan.py \
  --candidates ingest/<date>/style-candidates-<scope>.json \
  --judgements ingest/<date>/style-judgements-<scope>.json \
  --answers    ingest/<date>/<scope>_style_answers.json \
  --options    ingest/<date>/<scope>_style_options.json \
  --troubled-out ingest/<date>/<scope>_style_troubled_<date>.csv
```

Omit `--judgements` / `--answers` when there are none. **Exit 3** means the registry
names an option the base does not have: stop, report the names, and never add the
option yourself. Otherwise read the plan — `summary` first, then every `held` row and
every action's `tags` — and the printed summary. Output:
`plans/<date>/style-plan-<scope>.json`, and the troubled CSV only if rows exist.

Everything the policy decides is in the script and the registry; there is nothing
for you to approve or hold by judgement here. If a row looks wrong, the fix is a rule
table or a rubric edit, made in a separate change, never a hand edit of the plan.

## 5. Policy — the approval file

**Under `write_mode: plan_only`, skip to step 7.** No approval file exists, nothing
executes, and the report says so.

Under `write_mode: write`, re-run step 4's command with `--write-approval`. It writes
`plans/<date>/style-approval-<scope>.json` naming every `actions[].id` as `approved`
by the registry's `policy.approved_by` string. Held rows have no id and cannot be
approved by anyone; the resolution path is the `Action` column or fixing the cause.

## 6. Act — `airtable-actions-agent`

Hand the plan and the approval file to **`airtable-actions-agent`**, action type
`airtable_update_style_tags`. Its rules are in its own file; the ones that matter here:

- It **re-reads every record before writing** and drops any field no longer blank,
  and refuses any record that has become `Staff confirmed` since the snapshot.
- It writes only the tag fields in `fields`, sets `Style tags status` per
  `status_write`, and **appends** `evidence_append` to `Style tags evidence`.
- One actions-log entry per record, `approved_by` = the policy string,
  `raw_ref_action_id` = the `sty-` id. Interrupted → run the agent again; executed ids
  are skipped.

## 7. Report — the troubled file, the row, the ping

**Stamp `Last Agent Activity Date` on every write to the row**, same rule and same
keys as `/catalog-sync` step 6.

1. **The standing row.** First run for this supplier: create it in the Price Lists
   data source with the title from `notion_row.title_format`, `Company` = the
   supplier's Notion option where one exists (else blank), `Tags` = `notion_row.tag`
   (a new gray option — colour that one option only, per the 2026-09-11 open-ended-tag
   rule; never touch `Regular List` / `Promo`), and every `properties_on_create` value.
   Log it `notion_create_page`. Later runs reuse the row.
2. **The troubled CSV**, if step 4 wrote one: commit it, then attach it to
   `Troubled Files`, replacing the previous file — same upload recipe as
   `/process-price-list` step 6 (`;type=text/csv`). No file → attach nothing, and
   leave any existing page table alone.
3. **The page table**: render the CSV's rows as a table in the page body, replacing
   the previous run's table, ` · ` in place of any `|` in a cell. The `Action` column
   already carries every prior answer the script matched; the reviewer's cells are
   theirs. Log it `notion_write_troubled_table`.
4. **`Notes`** = the registry's `notes_format` line. Log the property writes
   `notion_update_page`.
5. **PushNotification** — always when the CSV exists — naming the scope, `write_mode`,
   and the written / held / flagged counts. A file nobody is told about is not a
   checkpoint.
6. **Commit** the run's files (snapshot, options, answers, candidates, judgements,
   plan, approval, CSV, actions-log) and open the run's PR with
   `python3 scripts/publish_run.py`. Images are gitignored and stay local.

## Done means

- Steps 0–4 ran and their files are committed; the plan's `summary` is in the report.
- Under `plan_only`: **nothing was written to Airtable**, and the report says so
  plainly. Under `write`: every approved action executed or explicitly logged as
  failed, one actions-log entry per record with the policy string.
- Every held and flagged row is in the CSV, on `Troubled Files`, in the page table,
  and notified — or the run was clean and none of that exists.
- No record that was `Staff confirmed` was touched; no field that was non-blank was
  written. If the agent refused or dropped anything at write time, the report names it.
- The host-blocked case, if it happened, is reported as an environment limit, not as
  "no images".

Report honestly. If a step did not run, say which. Never mark a stage complete that
isn't.
