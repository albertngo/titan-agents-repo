# Style tags — `/style-tag` method

> **STATUS: BUILT 2026-09-26, `write_mode: plan_only`.** Albert approved the plan the
> same day ("Go with the recommendations on D1–D6, build it"). This file is now the
> method the command points to: §0 records what exists and what was decided, §4–§6
> are the rules the scripts implement, §14 is the rubric the model judges by. The
> blockers **B1–B3** are still live and are what the first real runs will meet.
>
> **Amended 2026-09-26, same day (Albert):** `Images` is now **`Swatch images`** (same
> id), and **`Room scene images`** and **`Detail images`** exist beside it, each with a
> description telling staff what belongs in it. §4 carries his brief line verbatim and
> every `Images` reference below was updated to match. Image kind is now a fact from
> the source field, not something the model guesses.

AI-suggested style tags for the Master Flooring Catalogue: fill the blank style
fields on a record from its specs and its product images, mark the record
`AI suggested`, and leave staff to confirm. Same three-step shape as every other
flow here — **pull → decide → act** — and the same gate: an actions agent writes
only an id that appears `approved` in an approval file.

---

## 0. What exists, and what was decided

**Built 2026-09-26 (8 files, plus the edits below):**

| File | Role |
|---|---|
| `.claude/commands/style-tag.md` | The command. Catalogue department, `kind: command`, like `/catalog-sync` |
| `contracts/style-plan-schema.md` | `style-plan-1` (the diff), `style-approval-1` (the gate), the policy rubric, the judgement file |
| `contracts/troubled-tags-schema.md` | The per-SKU-per-field exception report. Sibling of `troubled-skus-schema.md`, inherits its `Action` column rules by reference |
| `platform-settings/style-tags.json` | Field ids, option strings, thresholds, image-kind caps, spec rule tables, `write_mode`, Notion row defaults, output names |
| `scripts/style_tag_pull.py` | Pull, read-only: eligible records from a saved Airtable snapshot, image manifest, image download (soft-fails when the host is blocked) |
| `scripts/style_tag_plan.py` | Decide, read-only: spec rules + the model's judgement file + reviewer answers → the plan. No platform, no credentials |
| `tests/test_style_tags.py` | Contract, policy, conflict, spec-only, registry ↔ live-schema, answer parsing |
| `methods/style-tags.md` | This file: the method, the decisions, and the rubric (§14) |

Edits made: `.claude/agents/airtable-actions-agent.md` (the `airtable_update_style_tags`
type), `contracts/actions-log-schema.md` (type vocabulary), `platform-settings/departments.json`
(Catalogue `owns.commands` + route keywords), `CLAUDE.md` (a paragraph under the catalogue
pipeline), `.gitignore` (`ingest/*/style-images/`). No new agent. No Airtable schema change —
the fields already exist (§2). No Notion database. No routine. Not done: the
`Effective Date` rename in `airtable-master-catalogue-fields.json` (§13).

**Decisions — all six taken as recommended (Albert, 2026-09-26, "go with the recommendations"):**

- **D1 — Which Notion row carries `Troubled Files`.** One standing row per scope in the
  existing Price Lists database, tagged `Style Tags`, `Extraction Status = Not Needed`,
  overwritten each run. (Alternative not taken: a "Style Tag Runs" database.) §6.
- **D2 — v1 category scope.** Flooring only (Engineered hardwood, Solid hardwood, LVP,
  LVT, Laminate). Tile / Stone (4,036 active records) opts in later. §1.
- **D3 — Troubled report shape.** A sibling contract (`troubled-tags-1`) with a `field`
  column, one row per SKU × field, rather than stretching the price-list file. §6.
- **D4 — `Style` on a spec-only record.** Held (`needs_image`) until images exist; Style
  depends on tone and undertone, which specs cannot give. §4.
- **D5 — What a reviewer's `Action` answer writes.** The answered tag is written with
  `Style tags status = AI suggested` still, evidence naming the reviewer; a person flips
  to `Staff confirmed` in Airtable. The run never writes `Staff confirmed`. §6.
- **D6 — Who looks at the images.** The session model (the same pattern as the image
  price-list transcription in `/process-price-list` 2.3), writing a structured judgement
  file. A script calling the Claude API is the later scale path, not built. §3.

**Blockers, still live:**

- **B1 — No record has an image yet.** `Swatch images` (the renamed `Images`, same id) is
  empty on all 8,253 records (checked live 2026-09-26, two filters), and `Room scene
  images` and `Detail images` were created empty the same day. v1 as built today is
  spec-only: Texture and Busyness write; Undertone, Tone depth and Style hold. The image
  path is built and tested against fixtures, and starts working the day swatches land.
- **B2 — The cloud environment cannot reach Airtable's attachment host.** `CONNECT
  v5.airtableusercontent.com:443` returns 403 from the session proxy (so do
  `dl.airtable.com` and `api.airtable.com`; `api.notion.com` is allowed). Image
  originals cannot be downloaded from a cloud session until the environment's Network
  access allows that host, or the run happens on Albert's Mac. The pull step must fail
  soft on this — colour tags hold as `image_host_blocked`, spec tags still proceed.
- **B3 — HEIC.** All three image fields accept HEIC; vendored Pillow 12.2 cannot decode it and the
  session's image reader will not either. Vendor `pillow-heif` (one-time pypi
  allowlist, per `vendor/wheels/README.md`) or hold HEIC-only records as
  `image_format_unsupported`. Recommend the hold for v1, the wheel when it bites.

---

## 1. What the live base says today (2026-09-26)

Read-only checks through the Airtable MCP, all against `tblfLXD3zkSdNQGbS`.

| Fact | Value |
|---|---|
| Records | 8,253 (7,852 `Active`) |
| Records with anything in `Swatch images` (checked as `Images`, same id, before the rename) | **0** |
| `Room scene images` / `Detail images` | created 2026-09-26, empty |
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
≠ `Staff confirmed`, at least one of the seven style fields blank, and (any of the three image fields
non-empty OR any of `Finish type` / `Grade` / `Species` / `Colour / tone` set). Accessory, STONE and
Carpet excluded. Tile / Stone excluded from v1 because its finishes (polished, honed,
glazed, splitface) need their own texture mapping and its "busyness" is veining, not
grain — a second rule table, added when asked for.

## 2. The fields — live, verified

All seven exist in Airtable already, after the three image fields, with descriptions
that name `/style-tag`. Ids go in the registry, never in prose that runs.

| Field | Id | Type | Live options / config |
|---|---|---|---|
| `Swatch images` | `fldbRlqkxa7hp7quH` | multipleAttachments | Renamed from `Images` 2026-09-26, same id. "Clean product swatch/plank photos only — the hero image and the source for colour tags (undertone, tone depth). Supplier swatches preferred. Room photos go in Room scene images; close-ups in Detail images; spec sheets in Attachments. JPEG/PNG/HEIC, long edge ≥1600px. Synced to Supabase by titan-desk." |
| `Room scene images` | `fldcB1MQVqcPf6lKY` | multipleAttachments | Added 2026-09-26. "Installed / lifestyle photos showing the floor in a room. Used for style tags and website galleries. Not used for colour tags (room lighting skews undertone)." |
| `Detail images` | `fldRH7GrND9w10KWH` | multipleAttachments | Added 2026-09-26. "Close-ups: texture, edge/click profile, bevel, finish, cross-section, packaging. Used for texture tags and product detail pages." |
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

Steps 0–4 write no platform. `write_mode` in the registry is `plan_only`: the command
runs steps 0–4 and 7 with no approval file and no writes, until the value is flipped
by a dated decision — the same staged rollout as `social-destinations.json`. The
authoritative step-by-step is `.claude/commands/style-tag.md`; what follows is the
shape and the reasoning.

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
blank, and an image manifest (`field` — `swatch` | `room` | `detail`, from the Airtable field the
attachment sits in — `attachment_id`, `filename`, `type`, `size`, `width`, `height`,
local path). With `--download` it fetches each original (`url`, never `thumbnails.*` —
thumbnails are re-encoded and can shift colour) to
`ingest/<date>/style-images/<sku>/<field>/<attachment_id>-<filename>` (gitignored) and writes
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
    {"attachment_id": "att…", "field": "swatch", "looks_like": "swatch",
     "usable_for_colour": true, "note": "flat supplier swatch, neutral white border"}
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

`field` is where the attachment sits in Airtable and is what decides what the image may
inform (§4); `looks_like` is the model's sanity check on it — `swatch | room | detail |
spec_sheet | other`. A `Swatch images` attachment that looks like a room scene or a
phone photo of an installed floor is **not** `usable_for_colour`, and is reported as
`image_misfiled` so staff can move it. `texture_seen` from a `Detail images` close-up is
a secondary source for Texture; from any other field it, like `busyness_seen`, is an
observation used **only for conflict detection** against the spec rules. No images →
the image keys are absent and `style.confidence` is capped by `spec_only_style_cap`
(D4).

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

Albert's brief line, 2026-09-26, verbatim — the rule the table below implements:

> Colour tags (Undertone, Tone depth) come from Swatch images only; never from Room
> scene images (room lighting skews colour). Style uses swatch + room scenes. Texture
> uses specs + Detail images. No swatch → hold colour tags for review.

| Field | Primary | Secondary | Never |
|---|---|---|---|
| `Texture` | spec: `Finish type` (rule table) | `Detail images` (`texture_seen` from a close-up; agreement → `both`); `Grade` (Distressed Grade → Rustic) | a swatch or room scene alone |
| `Busyness` | spec: `Grade` (rule table) + finish modifiers | `Colour / tone = Multi` → +1 step | image alone |
| `Undertone` | **`Swatch images` only** | supplier colour words in `Product name` / `Collection` (`golden`, `honey`, `ash`, `smoke`, `grey`…) | `Room scene images` (lighting), `Detail images`, spec alone |
| `Tone depth` | **`Swatch images` only** | `Colour / tone` (Light/Medium/Dark → 1–2 / 3 / 4–5, conf 0.5); colour words (`white`, `natural`, `espresso`) | `Room scene images`, `Detail images`, spec alone |
| `Style` | both: model judgement over specs + `Swatch images` + `Room scene images`, thresholded | — | `Detail images`; spec alone (D4: `spec_only_style_cap = 0.65`, below threshold) |

**No swatch → the colour tags hold** (`no_swatch`), whatever else the record carries.

`source` on every tag is one of `spec | image | both | reviewer`. `both` means two
independent sources agreed; agreement raises confidence by `agreement_bonus` (0.1,
capped at 1.0); disagreement is a conflict, not an average (§5).

**Image kind is the source field, not a guess.** Which field an attachment sits in
decides what it may inform — registry `image_sources`: `swatch_images` → colour and
style; `room_scene_images` → style only; `detail_images` → texture only. There are no
per-kind confidence caps: a room scene never reaches the colour tags at any
confidence, which is the rule the earlier `showroom 0.75` cap was approximating. The
model's `looks_like` is a sanity check only — it can *withhold* a misfiled image
(`image_misfiled`), never promote one. Among several swatches the largest wins; the
others are named in evidence.

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
3. `confidence ≥ min_confidence` (0.7, registry) after the spec-only cap.
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
| `no_swatch` | Colour field on a record with nothing usable in `Swatch images` — room scenes and detail images do not count | `held` |
| `image_misfiled` | An attachment whose `looks_like` contradicts its field (a room scene sitting in `Swatch images`); nothing was read from it. One row per image — a TODO to move the file | `held` |
| `image_host_blocked` | B2: images exist but could not be downloaded from this environment | `held` |
| `image_format_unsupported` | B3: only HEIC (or undecodable) images | `held` |
| `spec_unmapped` | `Finish type` / `Grade` value not in the rule table | `held` |
| `needs_image` | D4: `Style` on a spec-only record | `held` |
| `answer_unparsed` | A reviewer's `Action` cell could not be read as `Field: Value` | `held` |
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
- **Closed field list**: only the seven ids in §2. Never `Colour / tone`, never any of
  the three image fields, never anything else. `typecast` off — an option name that does not match live fails
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

## 8. Registry — `platform-settings/style-tags.json`

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
  "inputs": {"swatch_images": "fldbRlqkxa7hp7quH",
             "room_scene_images": "fldcB1MQVqcPf6lKY",
             "detail_images": "fldRH7GrND9w10KWH",
             "Finish type": "fldo6Em81uoydl9Jj", "Grade": "fld42aGNM67nKH2hp",
             "Species": "fldvWLfeSvsMnd1vL", "Colour / tone": "fldNTc3qponIjsNLV", "Salesperson notes": "fldm06jdSIM9o3PXI"},
  "eligible_categories": ["Engineered hardwood", "Solid hardwood", "LVP", "LVT", "Laminate"],
  "policy": {"min_confidence": 0.7, "agreement_bonus": 0.1, "spec_only_style_cap": 0.65},
  "image_sources": {"swatch_images": ["colour", "style"], "room_scene_images": ["style"], "detail_images": ["texture"]},
  "source_rules": {"Texture": ["spec", "detail_images"], "Busyness": ["spec"], "Undertone": ["swatch_images"],
                   "Tone depth": ["swatch_images"], "Style": ["spec", "swatch_images", "room_scene_images"]},
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

The sketch above is what was planned; the file itself is longer (full rule tables,
`notion_row`, `outputs`, the reason vocabularies) and is the one that counts.
Thresholds and rule tables live there (architecture rule of thumb: a value you might
change next month → `platform-settings/`); what the values *mean* lives here, §14.

## 9. Tests — `tests/test_style_tags.py` (stdlib unittest)

Inline fixtures, never live. The cases, as built (the numbering below is the plan's;
the file groups them by class):

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
   `Undertone` and `Tone depth` held `no_swatch`; `Style` held `needs_image`.
6. **Threshold boundary**: 0.7 writes, 0.699 holds `low_confidence` with `proposed`.
7. **Image sources**: a record with only a `Room scene images` attachment holds
   `Undertone` and `Tone depth` as `no_swatch` even at model confidence 0.9, while the
   same image informs `Style`; a `Detail images` close-up agreeing with the spec rule
   lifts `Texture` to `source: both` and never touches colour; a `Swatch images`
   attachment with `looks_like: room` is `image_misfiled`, read for nothing, colour held.
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

1. ~~Albert approves this plan~~ — done 2026-09-26, recommendations taken.
2. ~~Implementation~~ — done 2026-09-26 on branch `claude/style-tags-flooring-catalogue-8uymcs`,
   tests green, vault decision note `05_decisions/2026-09-26-style-tags.md`.
3. First run, `write_mode: plan_only`, one supplier with dense specs (VIDAR or FLOORS
   AT WORK engineered hardwood). Albert reads `style-plan-<scope>.json` and the
   troubled CSV. Rule tables adjusted from what it held.
4. Flip `write_mode` to `write` — a dated decision, vault note updated. Same supplier,
   real writes, `AI suggested` on the records, staff confirm in Airtable.
5. Colour tags switch on by themselves once (a) swatches land in `Swatch images` and (b) the
   environment allows `v5.airtableusercontent.com`, or the run happens on the Mac.
6. Calibration, tier 0: after a few hundred `Staff confirmed` records exist, one
   analysis compares `AI suggested` values to what staff kept or changed, per field and
   per source, and moves `min_confidence` and the caps on evidence rather than taste.

## 11. Later triggers (v2, not built)

- **After `/catalog-sync` creates products**: a final step in that command runs
  `/style-tag <SUPPLIER> --sku <created SKUs>` on the same session. New rows carry
  specs, rarely images, so this is the spec-only path.
- **When `Swatch images` changes**: an Airtable automation on `Swatch images` → Make
  webhook → a routine firing `{"supplier": …, "sku": …}`, or a periodic sweep over
  `Swatch images is not empty AND Style tags status is empty`. The sweep is the simpler and safer of the two
  (no per-edit fire storms while someone uploads 40 swatches), and is a natural fit
  for the not-yet-wired backstop sweep pattern.

Both are manual-command-only until v1 has run clean end to end; nothing here
re-enables anything scheduled.

## 12. Out of scope, deliberately

- No change to `/catalog-sync`, `catalog_reconcile.py` or the catalogue contracts.
- No write to `Colour / tone`, any of the three image fields, `Attachments` or any
  non-style field.
- No `Staff confirmed` ever written by a run; no deletion or clearing of a style field.
- No Tile / Stone in v1 (D2); no Design Rules rows written (that table is the consumer,
  owner-edited).
- No API credential added; no routine created or re-enabled.

## 13. Side findings from the live read (not fixed here)

- `platform-settings/airtable-master-catalogue-fields.json` (captured 2026-09-23) was
  stale: the ten new fields (three image, seven style) were absent, and
  `fld67650y8QClqoMc` is now named **`Effective Date`**, not `Last price update`. The
  ten new ids were **added 2026-09-26** with this amendment — that is where the three
  image ids live in `platform-settings/` until `style-tags.json` exists. The rename is
  deliberately **not** applied: `catalog_export.py` resolves upload-CSV columns by
  name, so renaming the map entry would make every CSV's `Last price update` column
  read as unknown. That rename belongs with the change that updates the canonical CSV
  column list in bert-airtable-schema.
- The test suite baseline is red on one pre-existing case:
  `test_social_registry.test_write_mode_is_draft_until_deliberately_changed` fails
  because commit `c5f5969` flipped `social-destinations.json` `write_mode.mode` to
  `live` without updating the guard. Worth a one-line fix in its own change; it is
  also the cautionary example for test 12 above (a `write_mode` guard must be updated
  in the same commit as the flip).
- `Finish type` and `Grade` both carry placeholder options named after the field
  (`Finish type`, `Grade`) and many spelling variants — the normalising match in §4
  exists because of this, and both placeholders are ignored.

## 14. The rubric — what the model judges by (step 3)

The plan script decides what an observation is worth; this section is what the
observation should mean. Read it before writing a judgement file. Confidence is a
statement about *you*: 0.9+ means you would be surprised to be wrong; 0.7 means
probable; below 0.7 means a guess worth showing a reviewer, not writing.

**Undertone** — the colour cast under the brown, judged on a swatch only. Compare the
swatch to the neutral white or grey border most supplier swatches carry; if there is
none, compare to the image's own lightest region.

| Value | Looks like | Typical supplier words |
|---|---|---|
| `Warm` | golden, honey, amber, red-brown, orange cast | honey, caramel, cognac, toffee, chestnut, copper |
| `Neutral` | true brown or tan, no obvious cast either way; most "natural" oaks | natural, sand, beige, taupe, driftwood, greige |
| `Cool` | grey, ashy, taupe-grey, silver, blue-grey cast; smoked and fumed woods | grey, ash, smoke, silver, slate, fog, mist |

A whitewashed or grey-washed oak is `Cool` even when the base wood is warm; a fumed
or smoked oak is `Cool` or `Neutral`, rarely `Warm`. A phone photo under warm
tungsten light would read `Warm` for any floor — which is why only swatches count.

**Tone depth** — how light or dark, 1 to 5, on a swatch only:

| 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|
| white, ivory, bleached, very pale ash | light blonde oak, natural maple, pale grey | mid oak, honey, natural walnut sapwood | dark honey, mid-brown walnut, smoked oak | espresso, ebony, black, very dark walnut |

Judge the field of the plank, not the knots. `Colour / tone` (`Light` / `Medium` /
`Dark`) and the product name are hints only — the script treats them at 0.5.

**Texture** — decided by the spec rule over `Finish type` (§4); a `Detail images`
close-up confirms or conflicts. When you record `texture_seen` from a close-up:
`Smooth` = no relief, a flat coated face; `Brushed` = open grain lines you could feel,
from any wire-brushing; `Rustic` = scraping, distressing, saw marks, deliberate
roughness. Grain *print* on vinyl or laminate (EIR) is the open ruling below — record
what you see and let the rule decide.

**Busyness** — how much visual variation across a box, decided by the grade rule;
you record `busyness_seen` for the conflict check. `Calm` = uniform colour, few or no
knots, straight grain (Select & Better, Select). `Moderate` = some knots and colour
shift, character without drama (Character, ABC). `Busy` = many knots, mineral
streaks, strong colour variation, distressing (Rustic, ABCD, Distressed Grade).

**Style** — which interiors the floor suits; more than one is normal, none is fine.
Judged over specs + swatch + room scenes, never a detail image alone.

| Style | Says yes when | Says no when |
|---|---|---|
| `Modern` | clean, calm, long plank or large format, neutral or cool, matte | heavy distressing, strong red-brown |
| `Rustic` | busy, distressed, hand-scraped, knotty, wide plank | uniform pale floors |
| `Scandinavian` | pale (tone 1–2), neutral or cool, calm, matte, often wide oak | dark or warm-red floors |
| `Coastal` | pale to mid, whitewashed or sandy, relaxed grain, often wider planks | dark, formal, glossy |
| `Traditional` | mid to dark, warm, narrower planks, satin or semi-gloss, classic species (oak, walnut, maple) | pale grey, extreme widths |

A record with no swatch and no room scene may still carry a `Style` judgement from
its specs; it is held `needs_image` for a reviewer.

**The one thing not to do**: infer a colour from a name alone at high confidence.
"Honey Oak" from three suppliers spans `Warm` and `Neutral` and tone 2 to 4. Names
are hints; the script already treats them as such.

## 15. Open rulings — held until Albert answers

Held on purpose; each writes `spec_rule_provisional` or holds `low_confidence` until a
line here changes and the registry with it.

- **EIR / embossed / textured vinyl and laminate → `Texture`.** Grain embossing is
  neither a coated smooth face nor brushed wood. The registry maps it to `Brushed` at
  0.6 (held) so the rows surface. Options: `Brushed` (it reads as texture at the
  counter), `Smooth` (it is a print), or a fourth value, which is an Airtable change.
- **`BCDE` → `Busyness`.** A letter grade bert-airtable-schema does not map. Mapped to
  `Busy` at 0.7, provisional (writes `wrote_flagged`).
- **Tile / Stone** (D2). Its own `texture_from_finish` table (polished / honed /
  glazed → `Smooth`; textured / splitface / tumbled → `Rustic`) and a busyness notion
  for veining. Add `Tile / Stone` to `eligible_categories` only with that table.
