# Style tags — `/style-tag` plan

> **STATUS: PROPOSED 2026-09-26. Nothing below is built.** This file is the plan
> Albert asked for ("Plan first, don't implement until approved"). On approval it
> becomes the method doc the command points to; until then it changes nothing that
> runs. Decisions the plan needs are marked **D1–D6**; blockers **B1–B3**.

AI-suggested style tags for the Master Flooring Catalogue: fill the blank style
fields on a record from its specs and its product images, mark the record
`AI suggested`, and leave staff to confirm. Same three-step shape as every other
flow here — **pull → decide → act** — and the same gate: an actions agent writes
only an id that appears `approved` in an approval file.

---

## 0. The short version

**Build (8 files, plus 4 edits):**

| File | Role |
|---|---|
| `.claude/commands/style-tag.md` | The command. Catalogue department, `kind: command`, like `/catalog-sync` |
| `contracts/style-plan-schema.md` | `style-plan-1` (the diff), `style-approval-1` (the gate), the policy rubric, the judgement file |
| `contracts/troubled-tags-schema.md` | The per-SKU-per-field exception report. Sibling of `troubled-skus-schema.md`, inherits its `Action` column rules by reference |
| `platform-settings/style-tags.json` | Field ids, option strings, thresholds, image-kind caps, spec rule tables, `write_mode`, Notion row defaults, output names |
| `scripts/style_tag_pull.py` | Pull, read-only: eligible records from a saved Airtable snapshot, image manifest, image download (soft-fails when the host is blocked) |
| `scripts/style_tag_plan.py` | Decide, read-only: spec rules + the model's judgement file + reviewer answers → the plan. No platform, no credentials |
| `tests/test_style_tags.py` | Contract, policy, conflict, spec-only, registry ↔ live-schema, answer parsing |
| `methods/style-tags.md` | This file, rewritten as the rubric (what Warm means, tone-depth anchors, busyness ladder) |

Edits: `.claude/agents/airtable-actions-agent.md` (one new action type),
`contracts/actions-log-schema.md` (type vocabulary), `platform-settings/departments.json`
(Catalogue `owns.commands` + route keywords), `platform-settings/airtable-master-catalogue-fields.json`
(refresh — see Side findings), `CLAUDE.md` (a paragraph under the catalogue pipeline),
`.gitignore` (`ingest/*/style-images/`). No new agent. No Airtable schema change — the
fields already exist (§2). No Notion database. No routine.

**Decisions needed before building:**

- **D1 — Which Notion row carries `Troubled Files`.** Recommend one standing row per
  scope in the existing Price Lists database, tagged `Style Tags`, `Extraction Status =
  Not Needed`, overwritten each run. Alternative: a new "Style Tag Runs" database. §6.
- **D2 — v1 category scope.** Recommend flooring only (Engineered hardwood, Solid
  hardwood, LVP, LVT, Laminate). Tile / Stone (4,036 active records) opts in later. §1.
- **D3 — Troubled report shape.** Recommend a sibling contract with a `field` column,
  one row per SKU × field, rather than stretching the 12-column price-list file. §6.
- **D4 — `Style` on a spec-only record.** Recommend hold (`needs_image`) until images
  exist; Style depends on tone and undertone, which specs cannot give. §4.
- **D5 — What a reviewer's `Action` answer writes.** Recommend the answered tag is
  written with `Style tags status = AI suggested` still, evidence naming the reviewer;
  a person flips to `Staff confirmed` in Airtable. The run never writes `Staff confirmed`. §6.
- **D6 — Who looks at the images.** Recommend the session model (the same pattern as
  the image price-list transcription in `/process-price-list` 2.3), writing a structured
  judgement file. Alternative: a script calling the Claude API with a new credential. §3.

**Blockers found while planning:**

- **B1 — No record has an image yet.** `Images` is empty on all 8,253 records (checked
  live 2026-09-26, two filters). v1 as built today is spec-only: Texture and Busyness
  write; Undertone, Tone depth and Style hold. The image path is built and tested against
  fixtures, and starts working the day images land.
- **B2 — The cloud environment cannot reach Airtable's attachment host.** `CONNECT
  v5.airtableusercontent.com:443` returns 403 from the session proxy (so do
  `dl.airtable.com` and `api.airtable.com`; `api.notion.com` is allowed). Image
  originals cannot be downloaded from a cloud session until the environment's Network
  access allows that host, or the run happens on Albert's Mac. The pull step must fail
  soft on this — colour tags hold as `image_host_blocked`, spec tags still proceed.
- **B3 — HEIC.** `Images` accepts HEIC; vendored Pillow 12.2 cannot decode it and the
  session's image reader will not either. Vendor `pillow-heif` (one-time pypi
  allowlist, per `vendor/wheels/README.md`) or hold HEIC-only records as
  `image_format_unsupported`. Recommend the hold for v1, the wheel when it bites.

---

## 1. What the live base says today (2026-09-26)

Read-only checks through the Airtable MCP, all against `tblfLXD3zkSdNQGbS`.

| Fact | Value |
|---|---|
| Records | 8,253 (7,852 `Active`) |
| Records with anything in `Images` | **0** |
| Records with `Style tags status` set | 0 (no `AI suggested`, no `Staff confirmed`) |
| Records with any style field set | 0 |
| Active flooring (non-tile) | 3,304 |
| …with `Finish type` or `Grade` | 1,575 (Engineered hardwood 1,058 of 1,239; Solid 227 of 287; LVP 207 of 1,234; Laminate 81 of 439; LVT 2 of 92) |
| …with `Finish type` | 1,450 |
| …with `Grade` | 821 |
| …with `Colour / tone` | 301 (and the option list carries ~130 supplier colour codes beside the 7 canonical values) |
| Active Tile / Stone + STONE | 4,255, of which 3,774 carry a `Finish type` |
| `Design Rules` table (`tblKJNVM4T9LfKwIs`) | exists, 0 rows — the consumer of these tags ("Tone depth 2–3; Undertone Warm") |

So the first real run is spec-only on engineered hardwood, where the specs are
densest, and the colour tags wait on images (B1) and egress (B2). That is not a
reason to defer: the spec half is the half with deterministic, testable rules, and the
reviewer loop is the same either way.

**v1 eligibility (D2):** `Active` ✓, `Category` in the flooring set, `Style tags status`
≠ `Staff confirmed`, at least one of the seven style fields blank, and (Images non-empty
OR any of `Finish type` / `Grade` / `Species` / `Colour / tone` set). Accessory, STONE and
Carpet excluded. Tile / Stone excluded from v1 because its finishes (polished, honed,
glazed, splitface) need their own texture mapping and its "busyness" is veining, not
grain — a second rule table, added when asked for.

## 2. The fields — live, verified

All seven exist in Airtable already, after `Images`, with descriptions that name
`/style-tag`. Ids go in the registry, never in prose that runs.

| Field | Id | Type | Live options / config |
|---|---|---|---|
| `Images` | `fldbRlqkxa7hp7quH` | multipleAttachments | "Product photos only… Supplier swatches preferred. JPEG/PNG/HEIC, long edge ≥1600px. Synced to Supabase by titan-desk." |
| `Undertone` | `fldrOvSEzOoxyNSpC` | singleSelect | `Warm` · `Neutral` · `Cool` |
| `Tone depth` | `fldjlGQSOwPGJfEcA` | **rating**, max 5 | integer 1–5 (1 very light, 5 very dark). A rating, not a number field — write an int |
| `Texture` | `fldCH08dVkm48BoiD` | singleSelect | `Smooth` · `Brushed` · `Rustic` |
| `Style` | `fldMN7qErzn39NFcY` | multipleSelects | `Modern` · `Rustic` · `Scandinavian` · `Coastal` · `Traditional` |
| `Busyness` | `fldRMUIPEXOxvp7Xk` | singleSelect | `Calm` · `Moderate` · `Busy` |
| `Style tags status` | `fldFEZIuna04JLFCr` | singleSelect | `AI suggested` · `Staff confirmed` |
| `Style tags evidence` | `flduKhIN0PBEmnOMJ` | multilineText | — |

Inputs read, never written: `Finish type` (`fldo6Em81uoydl9Jj`, ~130 options with
spelling variants — `Wire brushed` / `Wirebrushed` / `Wirebrush` / `Wire Brushed` all
live), `Grade` (`fld42aGNM67nKH2hp`), `Species` (`fldvWLfeSvsMnd1vL`), `Colour / tone`
(`fldNTc3qponIjsNLV`, only the 7 canonical values are read; the supplier codes are
ignored), `Product name`, `Collection`, `Salesperson notes`, `Category`, `Active`.

**`Colour / tone` stays untouched.** bert-airtable-schema already rules "Colour / tone
is aesthetic, not a spec — leave it blank rather than guessing from the colour name."
This flow does not overturn that: it writes the seven new fields only, and reads
`Colour / tone` as weak secondary evidence for `Tone depth` (Light → 1–2, Medium → 3,
Dark → 4–5, at confidence 0.5 — never enough to write on its own).

## 3. The flow

```
[0] read back reviewer answers (Notion page table)            read only
[1] Airtable snapshot + option pre-flight  (MCP, saved JSON)   read only
[2] scripts/style_tag_pull.py  -> candidates + image manifest  read only
                               -> image originals to disk      (soft-fails on B2)
[3] the model reads each candidate: images + specs -> judgement file
[4] scripts/style_tag_plan.py  -> plans/<date>/style-plan-<scope>.json
[5] POLICY approves every action; everything else is held     (approval file)
[6] airtable-actions-agent writes approved tags                (actions log)
[7] troubled CSV -> Troubled Files -> page table -> PushNotification; commit; PR
```

Steps 0–4 write no platform. `write_mode` in the registry starts at `plan_only`:
the command stops after step 7's report with no approval file and no writes, until
the value is flipped by a dated decision — the same staged rollout as
`social-destinations.json`.

### `/style-tag <SUPPLIER> [--sku SKU,SKU…] [--plan-only]`

`<SUPPLIER>` is the Airtable `Supplier` option string (`FLOORS AT WORK`, `VIDAR`);
the scope slug names every output file. `--sku` narrows to named records for a spot
run. Per-supplier scope because image conventions and colour naming are per supplier,
and because a 300-record run is a session; a 3,300-record one is not.

**Step 0 — read back answers.** Find the scope's standing Notion row (D1), read the
page-body table, take every non-empty `Action` cell keyed on `sku` + `field`. Same
rules as `/catalog-sync` step 0: an answer is input, not authorisation; a key that
matches zero or many rows carries nothing and is reported. Grammar in §6.

**Step 1 — snapshot.** `list_records_for_table` for the supplier with every field in
§2 (inputs and targets), saved raw as `ingest/<date>/<scope>_style_snapshot.json`.
`get_table_schema` for the seven target fields, saved as
`<scope>_style_options.json`. Pre-flight, same as `/catalog-sync` 2026-09-23: if any
option string the registry expects is missing live (someone renamed `Warm`), the run
stops before planning and names it. Never add the option.

**Step 2 — pull.** `style_tag_pull.py --snapshot … --options … [--download]` writes
`ingest/<date>/style-candidates-<scope>.json`: one entry per eligible record with
`record_id`, `sku`, the input specs flattened to option names, which target fields are
blank, and an image manifest (`attachment_id`, `filename`, `type`, `size`, `width`,
`height`, local path). With `--download` it fetches each original (`url`, never
`thumbnails.*` — thumbnails are re-encoded and can shift colour) to
`ingest/<date>/style-images/<sku>/<attachment_id>-<filename>` (gitignored) and writes
a downscaled ≤1568px sibling for the model read. Attachment URLs expire within hours,
so the download happens in the same step as the snapshot and the manifest stores ids
and filenames, never URLs. A 403 from the proxy sets `images.status = host_blocked`
on the candidates file and the run continues spec-only (B2).

**Step 3 — judgement (D6).** For each candidate the model reads its images (the
downscaled copies) and its specs, and writes one entry to
`ingest/<date>/style-judgements-<scope>.json` — committed, because it is the audit
trail of what the model saw:

```json
{
  "sku": "ENG-FAWK-0060",
  "images": [
    {"attachment_id": "att…", "kind": "swatch", "usable_for_colour": true,
     "note": "flat supplier swatch, neutral white border"}
  ],
  "undertone":  {"value": "Warm",   "confidence": 0.82, "from": "att…",
                 "evidence": "golden-brown cast on the swatch, no grey"},
  "tone_depth": {"value": 3,        "confidence": 0.78, "from": "att…",
                 "evidence": "mid-brown; lighter than the walnut siblings"},
  "texture_seen":  {"value": "Brushed",  "confidence": 0.7},
  "busyness_seen": {"value": "Moderate", "confidence": 0.75},
  "style": {"values": ["Modern", "Scandinavian"], "confidence": 0.7,
            "evidence": "light neutral oak, long plank, low knot count"}
}
```

`kind` is one of `swatch | showroom | phone | spec_sheet | other`; only `swatch` and
`showroom` may be `usable_for_colour`. `texture_seen` and `busyness_seen` are
observations used **only for conflict detection** against the spec rules — the image
never writes those two fields by itself (source rules, §4). No images → the image
keys are absent and `style.confidence` is capped by `spec_only_style_cap` (D4).

The precedent is `/process-price-list` 2.3: the model transcribes an image into
structured JSON, a script checks it. Option (b) — `scripts/style_tag_judge.py`
calling the Claude API — is the scale path if a supplier run exceeds a few hundred
images; it needs a new credential in `.env.example` and a read of the `claude-api`
skill before it is written, so it is not v1.

**Step 4 — plan.** `style_tag_plan.py --candidates … --judgements … --answers … --options …`
is deterministic and fully tested. Per record, per blank target field it resolves a
`{value, confidence, source, evidence}` (§4), applies policy (§5), and emits either an
`actions[]` entry (one per record, carrying every approved tag) or `held[]` rows (one
per SKU × field). Output `plans/<date>/style-plan-<scope>.json`, `style-plan-1`.

**Step 5 — policy.** The command writes `plans/<date>/style-approval-<scope>.json`,
`style-approval-1`, every `actions[].id` as `approved`, `approved_by:
"policy: style-tags auto-approval (v1 rubric)"`. Held rows have no id (§5). Skipped
entirely while `write_mode` is `plan_only`.

**Step 6 — act.** `airtable-actions-agent` with the plan + approval file, new action
type `airtable_update_style_tags` (§7). It re-reads each record before writing and
drops any field that is no longer blank or any record that became `Staff confirmed`
since the snapshot. One actions-log entry per record.

**Step 7 — report.** Troubled CSV (§6) committed and attached to the scope row's
`Troubled Files`; the same rows rendered as the page-body table, carrying every
`Action` value forward; `Last Agent Activity Date` stamped; a PushNotification naming
the scope and the written / held counts — always when the file exists, never on a
clean run. Then `scripts/publish_run.py` opens the run's PR against `main-agents`,
because a run whose files sit on a session branch is invisible to the next run.

## 4. Source rules — what may decide each field

| Field | Primary | Secondary | Never |
|---|---|---|---|
| `Texture` | spec: `Finish type` (rule table) | `Grade` (Distressed Grade → Rustic) | image alone |
| `Busyness` | spec: `Grade` (rule table) + finish modifiers | `Colour / tone = Multi` → +1 step | image alone |
| `Undertone` | image: the best `usable_for_colour` image | supplier colour words in `Product name` / `Collection` (`golden`, `honey`, `ash`, `smoke`, `grey`…) | spec alone |
| `Tone depth` | image | `Colour / tone` (Light/Medium/Dark → 1–2 / 3 / 4–5, conf 0.5); colour words (`white`, `natural`, `espresso`) | spec alone |
| `Style` | both: model judgement over specs + images, thresholded | — | spec alone (D4: `spec_only_style_cap = 0.65`, below threshold) |

`source` on every tag is one of `spec | image | both | reviewer`. `both` means two
independent sources agreed; agreement raises confidence by `agreement_bonus` (0.1,
capped at 1.0); disagreement is a conflict, not an average (§5).

**Image preference.** When a record has several usable images, the best one wins in
this order: `swatch` > `showroom`; within a kind, the largest. Confidence from an
image is capped by its kind — registry `image_kind_caps`: `swatch 1.0`, `showroom
0.75`, `phone 0.6`, others `0`. A phone photo alone can therefore never clear the
0.7 threshold: it always lands with the reviewer, which is the point ("lighting skews
undertone").

**Spec rule tables — initial proposal, Albert edits them.** Matching normalises the
option string (lowercase, letters only) because the live `Finish type` list carries a
dozen spellings of wire-brushed. Anything not matched is `spec_unmapped`, held, and
named in the troubled CSV so the table grows from real rows rather than guesses.

Texture from `Finish type` (first match wins, top to bottom):

| Normalised finish contains | Texture | Confidence |
|---|---|---|
| `handscraped`, `hand scraped`, `distressed`, `sawmark`, `saw marked`, `arc saw`, `tumbled`, `splitface` | `Rustic` | 0.85 |
| `wirebrush`, `wire brush`, `brushed`, `smoked & wirebrushed` | `Brushed` | 0.85 |
| `smooth`, `matte uv`, `uv lacquer`, `semi gloss`, `gloss`, `polished`, `honed`, `matte`, `satin` (and no brush/scrape word) | `Smooth` | 0.8 |
| `eir`, `embossed in register`, `embossed`, `registered embossing`, `textured` | **provisional** `Brushed` | 0.6 → held until Albert rules (vinyl/laminate grain emboss is neither smooth nor brushed wood; see D-list in the rubric) |

Busyness from `Grade`, then finish modifiers:

| Grade (canonical after bert-airtable-schema's letter mapping) | Busyness | Confidence |
|---|---|---|
| `Select & Better`, `Select`, `Select Plus`, `AB`, `Prime`/`Prestige Grade`/`Excel Grade` | `Calm` | 0.85 (verbatim supplier grades 0.7 — the schema skill says these are "not formally mapped") |
| `Character`, `ABC` | `Moderate` | 0.85 |
| `Rustic`, `ABCD`, `BCDE`, `Distressed Grade` | `Busy` | 0.85 |
| blank | — | image only; spec-only record holds `spec_unmapped` |

Modifiers: a `Rustic` texture or a `distressed` / `smoked` / `reactive` finish moves
Busyness one step busier (never past `Busy`); `Colour / tone = Multi` likewise.
`Species = Hickory` or `Acacia` is a known busy grain — one step busier at 0.7. All in
the registry, all tunable, none inferred at run time.

## 5. Policy — what writes, what holds

Mirrors `catalog-plan-schema.md`'s "Policy auto-approval" in shape. A tag is
**approved** only if all of:

1. The target field is **blank** in the snapshot — and blank again at write time (§7).
2. `Style tags status` ≠ `Staff confirmed` — checked at pull, at plan, and at write.
3. `confidence ≥ min_confidence` (0.7, registry) after image-kind caps and the
   spec-only cap.
4. **No conflict**: where both a spec rule and an image observation exist for the
   field and both are ≥ 0.7, they name the same value. Disagreement holds the field
   as `spec_image_conflict` with both candidates in the row — never the higher score.
5. The value is a live option string (pre-flight, step 1), and for `Tone depth` an
   integer 1–5.

Everything else is **held**, per SKU × field, with a reason from the fixed vocabulary:

| Reason | Meaning | Disposition |
|---|---|---|
| `low_confidence` | Best candidate below 0.7; `proposed` carries it so the reviewer can just say yes | `held` |
| `spec_image_conflict` | Spec rule and image disagree at ≥ 0.7 each; both named | `held` |
| `no_usable_image` | Colour field on a record with no image, or images all `phone`/`spec_sheet`/`other` | `held` |
| `image_host_blocked` | B2: images exist but could not be downloaded from this environment | `held` |
| `image_format_unsupported` | B3: only HEIC (or undecodable) images | `held` |
| `spec_unmapped` | `Finish type` / `Grade` value not in the rule table | `held` |
| `needs_image` | D4: `Style` on a spec-only record | `held` |
| `answer_unparsed` | A reviewer's `Action` cell could not be read as `Field: Value` | `held` |
| `image_not_swatch` | Written from a `showroom` image (≥ 0.7 after the cap) — verify when convenient | `wrote_flagged` |
| `spec_rule_provisional` | Written from a rule marked provisional in the registry | `wrote_flagged` |

Held rows carry **no id** — like `held` in `social-plan-schema.md`, and unlike the
pricing carve-outs in the catalogue plan. There is nothing for a person to approve by
hand: the resolution path is the `Action` cell (which supplies a value) or fixing the
cause (add an image, fill the spec, extend the rule table), then re-run. Keeping the
approval file policy-only is what keeps it simple enough to test exhaustively.

A record whose every candidate is held gets **no write at all** — not even the
status. `Style tags status = AI suggested` is set only when at least one tag lands.

Ids: `sty-<sha1[:12]>` over `sku + "airtable" + "update_style_tags" + sorted(fields written)`.
Stable across re-runs for the same logical write, so the actions-log resume rule
(skip an id already `executed` today) works unchanged; a different field set is a
different write and gets a different id.

## 6. The reviewer loop

**The report (D3).** `ingest/<date>/<scope>_style_troubled_<date>.csv`, contract
`troubled-tags-1`, one row per SKU × field:

```
supplier · sku · product_name · field · reason · disposition · proposed · confidence · source · detail · action_id · Action
```

`Action` last, always emitted, always blank by a run, never read as authorisation —
the rules in `troubled-skus-schema.md` "The `Action` column" apply verbatim, by
reference, and the same carry-forward rule: match on `sku` + `field`, carry nothing on
zero or many matches, never overwrite a non-empty cell. The `|` rendering trap applies
too (`proposed` on a conflict row is ` · `-joined in the table, `|`-joined in the CSV).

Written only when at least one row exists; never a headers-only file. A clean run
attaches nothing and leaves any existing table alone.

**The row (D1).** One standing Notion row per scope in the Price Lists database
(`pricelist-sources.json` → `price_lists.data_source`), found by title
`Style tags — <SUPPLIER>` and created on the first run: `Company` = the supplier's
Notion option where one exists (else blank), `Tags` = `Style Tags` (gray, coined under
the 2026-09-11 open-ended-tag rule, never `Regular List`/`Promo`), `Extraction Status =
Not Needed`, `Airtable Sync` / `LS Upload` / `UUID Backfill` = `Not needed` so no
present or future sweep mistakes it for a price list, `Notes` = one counts line, `Last
Agent Activity Date` stamped on every write. Each run replaces `Troubled Files` and the
page table (Action cells carried forward). Logged as `notion_create_page` (first run),
`notion_write_troubled_table`, `notion_update_page`.

Why reuse the database: `Troubled Files is not empty` is already the worklist people
open, the `Action` table loop already exists there, and it costs no new registry. Why
one row per scope rather than per run: the report describes the current state of that
supplier's tags, not its history (the CSV is overwritten, like an ingest file), and a
row per run would leave answers scattered across pages. The alternative — a "Style Tag
Runs" database with `Supplier`, `Run date`, `Written`, `Held` properties — is cleaner
to filter on and worth it if style runs become frequent; not for v1.

**The answer grammar.** An `Action` cell is prose, and a run reads it narrowly:

- `Undertone: Warm` — sets that field's value for that SKU as `source: reviewer`,
  confidence 1.0, which then passes policy like any other tag (**D5**: written as
  `AI suggested`, evidence line `reviewer answer, <row>, <date>`; the run never writes
  `Staff confirmed`, which is a person's click in Airtable).
- Several: `Undertone: Warm; Tone depth: 3`. The `field` on the row is the default when
  the cell holds a bare option name (`Warm`) and that value is unambiguous for exactly
  one target field; `Rustic` is not (Texture and Style both have it) and is
  `answer_unparsed`.
- `skip` — the run stops proposing that field for that SKU; the row stays, dispositioned
  `reviewer_skipped`, and is carried forward so the decision is visible.
- Anything else → `answer_unparsed`, carried forward, reported. Never fuzzy-matched.
- A value must be a live option string, case-insensitively; `Tone depth` an integer 1–5.

## 7. The actions agent — one new type

`airtable-actions-agent` gains `airtable_update_style_tags`, alongside the two live
types. Rules, to be written into the agent file and enforced by prose tests:

- **Update by record id, never upsert.** No merge key means no record can be created.
- **Closed field list**: only the seven ids in §2. Never `Colour / tone`, never `Images`,
  never anything else. `typecast` off — an option name that does not match live fails
  loudly rather than minting a choice.
- **Read before write, every record.** Re-fetch it; if `Style tags status` is
  `Staff confirmed` → `refused` (`stale_staff_confirmed`), nothing written; drop any
  target field that is no longer blank (`stale_not_blank`); if nothing is left →
  `skipped`. The snapshot can be hours old and a staff member may have confirmed the
  record in between — the plan's blank-only promise is only true at write time if it
  is checked at write time.
- **`Style tags status`**: set to `AI suggested` only if blank. Leave `AI suggested`
  as is.
- **`Style tags evidence`**: append, never replace — current text + `\n` + this run's
  block. Block format: a header line `AI suggested <date> — <plan path>` then one line
  per written tag, `Field: Value (confidence, source[: image filename]) — evidence`.
  No tag is written without an evidence line; a test asserts it.
- Batch cap 50. Stop the batch on failure. One actions-log entry per record,
  `raw_ref` = record id, `raw_ref_action_id` = the `sty-` id, `approved_by` = the
  policy string, `content_summary` naming the fields written.
- Everything not on this list stays refused, exactly as today (delete, SKU edits,
  option creation, other tables, formula fields).

`contracts/actions-log-schema.md` type table gains the value under
`airtable-actions-agent`.

## 8. Registry — `platform-settings/style-tags.json` (sketch)

```json
{
  "config_version": "1",
  "base_id": "appWHOVZ0QCS0xQ3M",
  "table_id": "tblfLXD3zkSdNQGbS",
  "write_mode": {"mode": "plan_only", "_flip": "dated decision, recorded in the vault"},
  "targets": {
    "Undertone":  {"id": "fldrOvSEzOoxyNSpC", "type": "singleSelect", "options": ["Warm", "Neutral", "Cool"]},
    "Tone depth": {"id": "fldjlGQSOwPGJfEcA", "type": "rating", "min": 1, "max": 5},
    "Texture":    {"id": "fldCH08dVkm48BoiD", "type": "singleSelect", "options": ["Smooth", "Brushed", "Rustic"]},
    "Style":      {"id": "fldMN7qErzn39NFcY", "type": "multipleSelects", "options": ["Modern", "Rustic", "Scandinavian", "Coastal", "Traditional"]},
    "Busyness":   {"id": "fldRMUIPEXOxvp7Xk", "type": "singleSelect", "options": ["Calm", "Moderate", "Busy"]},
    "Style tags status":   {"id": "fldFEZIuna04JLFCr", "options": ["AI suggested", "Staff confirmed"], "run_writes": "AI suggested"},
    "Style tags evidence": {"id": "flduKhIN0PBEmnOMJ"}
  },
  "inputs": {"Images": "fldbRlqkxa7hp7quH", "Finish type": "fldo6Em81uoydl9Jj", "Grade": "fld42aGNM67nKH2hp",
             "Species": "fldvWLfeSvsMnd1vL", "Colour / tone": "fldNTc3qponIjsNLV", "Salesperson notes": "fldm06jdSIM9o3PXI"},
  "eligible_categories": ["Engineered hardwood", "Solid hardwood", "LVP", "LVT", "Laminate"],
  "policy": {"min_confidence": 0.7, "agreement_bonus": 0.1, "spec_only_style_cap": 0.65,
             "image_kind_caps": {"swatch": 1.0, "showroom": 0.75, "phone": 0.6, "spec_sheet": 0, "other": 0}},
  "source_rules": {"Texture": ["spec"], "Busyness": ["spec"], "Undertone": ["image"], "Tone depth": ["image"], "Style": ["both"]},
  "spec_rules": {"texture_from_finish": [...], "busyness_from_grade": {...}, "busyness_modifiers": [...],
                 "tone_depth_from_colour_tone": {"Light": [1, 2], "Medium": [3], "Dark": [4, 5]}},
  "notion_row": {"title_format": "Style tags — {supplier}", "tag": "Style Tags",
                 "extraction_status": "Not Needed", "trackers": "Not needed"},
  "outputs": {"snapshot": "{scope}_style_snapshot.json", "candidates": "style-candidates-{scope}.json",
              "judgements": "style-judgements-{scope}.json", "images_dir": "style-images/",
              "plan": "plans/{date}/style-plan-{scope}.json", "approval": "plans/{date}/style-approval-{scope}.json",
              "troubled": "{scope}_style_troubled_{date}.csv"}
}
```

Thresholds and rule tables live here (architecture rule of thumb: a value you might
change next month → `platform-settings/`); what the values *mean* lives in this file
once it is the rubric.

## 9. Tests — `tests/test_style_tags.py` (stdlib unittest)

Against fixtures under `tests/fixtures/style/` (a small snapshot, an options file, a
judgement file), never live:

1. **Contract**: plan envelope has `contract_version: style-plan-1`, `scope`, `run_at`,
   `inputs`, `write_mode`, `summary`, `actions`, `held`; every tag is
   `{value, confidence, source, evidence}` with `source ∈ {spec, image, both, reviewer}`;
   ids are `sty-` + 12 hex and identical on two runs over the same input.
2. **Never overwrites**: a record with `Undertone` already set gets no `Undertone` in
   any action, whatever the judgement says.
3. **Never touches Staff confirmed**: a `Staff confirmed` record with every style field
   blank and a perfect swatch produces neither an action nor a held row.
4. **Conflict → held**: spec `Wire brushed` (Brushed 0.85) vs `texture_seen: Smooth 0.8`
   → `Texture` held `spec_image_conflict`, both candidates in `proposed`, no action.
5. **Spec-only fills texture/busyness, holds colour**: `Finish type: Wire brushed`,
   `Grade: Character`, no images → action with `Texture: Brushed`, `Busyness: Moderate`;
   `Undertone` and `Tone depth` held `no_usable_image`; `Style` held `needs_image`.
6. **Threshold boundary**: 0.7 writes, 0.699 holds `low_confidence` with `proposed`.
7. **Image-kind caps**: a phone-only record's `Undertone` at model confidence 0.9 is
   capped to 0.6 and held; a showroom image at 0.9 → 0.75, written `wrote_flagged`
   `image_not_swatch`.
8. **Host blocked**: candidates with `images.status: host_blocked` hold colour fields
   `image_host_blocked` and still write spec fields.
9. **All held → no write**: a record with only held candidates has no action, so no
   status flip.
10. **Answers**: `Undertone: Warm` → reviewer tag, written; `Rustic` bare on a `Texture`
    row → `answer_unparsed`; `skip` → `reviewer_skipped`, carried forward; a cell
    matching two rows carries nothing.
11. **Evidence**: every written tag has an evidence line naming source and confidence.
12. **Registry ↔ schema**: every field id in `style-tags.json` exists in the refreshed
    `airtable-master-catalogue-fields.json` with the recorded type; option lists match
    the live options file fixture; `write_mode.mode` is `plan_only` until a dated flip
    (the same guard `test_social_registry.py` has — see Side findings for how that one
    went stale).
13. **Troubled-tags contract prose**: `Action` is the last column, "never writes into",
    "prose is not an approval", carry-forward keys `sku` + `field`; the agent file names
    `airtable_update_style_tags`, "Read before write", "never upsert"; the actions-log
    vocabulary lists the type; `departments.json` Catalogue owns `style-tag` (the
    existing registry test then checks the command file exists).
14. **Read-only guard**: `style_tag_pull.py` and `style_tag_plan.py` contain no Airtable
    write verb (`update_records`, `create_records`), same shape as
    `tests/test_lightspeed.py`.

## 10. Rollout

1. Albert approves this plan (with D1–D6 answered or defaulted to the recommendations).
2. Implementation PR against `main-agents`: the 8 files + 4 edits, tests green, plus a
   vault decision note `decisions/2026-09-26-style-tags.md` (committed and pushed from
   the cloud session, per Vault writes).
3. First run, `write_mode: plan_only`, one supplier with dense specs (VIDAR or FLOORS
   AT WORK engineered hardwood). Albert reads `style-plan-<scope>.json` and the
   troubled CSV. Rule tables adjusted from what it held.
4. Flip `write_mode` to `write` — a dated decision, vault note updated. Same supplier,
   real writes, `AI suggested` on the records, staff confirm in Airtable.
5. Colour tags switch on by themselves once (a) images land in `Images` and (b) the
   environment allows `v5.airtableusercontent.com`, or the run happens on the Mac.
6. Calibration, tier 0: after a few hundred `Staff confirmed` records exist, one
   analysis compares `AI suggested` values to what staff kept or changed, per field and
   per source, and moves `min_confidence` and the caps on evidence rather than taste.

## 11. Later triggers (v2, not built)

- **After `/catalog-sync` creates products**: a final step in that command runs
  `/style-tag <SUPPLIER> --sku <created SKUs>` on the same session. New rows carry
  specs, rarely images, so this is the spec-only path.
- **When `Images` changes**: an Airtable automation on `Images` → Make webhook → a
  routine firing `{"supplier": …, "sku": …}`, or a periodic sweep over `Images is not
  empty AND Style tags status is empty`. The sweep is the simpler and safer of the two
  (no per-edit fire storms while someone uploads 40 swatches), and is a natural fit
  for the not-yet-wired backstop sweep pattern.

Both are manual-command-only until v1 has run clean end to end; nothing here
re-enables anything scheduled.

## 12. Out of scope, deliberately

- No change to `/catalog-sync`, `catalog_reconcile.py` or the catalogue contracts.
- No write to `Colour / tone`, `Images`, `Attachments` or any non-style field.
- No `Staff confirmed` ever written by a run; no deletion or clearing of a style field.
- No Tile / Stone in v1 (D2); no Design Rules rows written (that table is the consumer,
  owner-edited).
- No API credential added; no routine created or re-enabled.

## 13. Side findings from the live read (not fixed here)

- `platform-settings/airtable-master-catalogue-fields.json` (captured 2026-09-23) is
  stale: the eight new fields are absent and `fld67650y8QClqoMc` is now named
  **`Effective Date`**, not `Last price update`. `catalog_export.py` keys by id so it
  still works, but the map should be refreshed in the implementation PR since the
  style flow needs the new ids in it anyway.
- The test suite baseline is red on one pre-existing case:
  `test_social_registry.test_write_mode_is_draft_until_deliberately_changed` fails
  because commit `c5f5969` flipped `social-destinations.json` `write_mode.mode` to
  `live` without updating the guard. Worth a one-line fix in its own change; it is
  also the cautionary example for test 12 above (a `write_mode` guard must be updated
  in the same commit as the flip).
- `Finish type` and `Grade` both carry placeholder options named after the field
  (`Finish type`, `Grade`) and many spelling variants — the normalising match in §4
  exists because of this, and both placeholders are ignored.
