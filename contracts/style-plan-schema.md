# Style Plan Contract — style-plan-1

The reviewable diff between what a catalogue record's specs and images say about its
look and the blank style fields on that record. One file per scope per run:

```
plans/YYYY-MM-DD/style-plan-<scope>.json
```

Produced by `scripts/style_tag_plan.py` from the candidates file
(`scripts/style_tag_pull.py`), the judgement file (below) and any reviewer answers.
Overwritten on re-run, never appended to — like an ingest file, and unlike
`actions-log.json`.

Mirrors `contracts/catalog-plan-schema.md` deliberately — same envelope shape, same
stable ids, same "absence of an approval file means nothing is approved". Read that
one first if this is unfamiliar; only the differences are explained here. Ids, option
strings, thresholds and rule tables live in `platform-settings/style-tags.json`, never
here and never in a prompt. Method and rubric: `methods/style-tags.md`.

## What this is for

Five fields — `Undertone`, `Tone depth`, `Texture`, `Style`, `Busyness` — that Bert's
recommendation layer (the `Design Rules` table) will key on, filled on records where
they are blank, marked `AI suggested`, and left for staff to confirm. The plan makes
every suggestion explicit and reviewable before anything reaches the base: which
value, how sure, from which source, and the one line of evidence behind it.

## The approval boundary

Identical in force to the catalogue plan:

- The planner **never** creates, edits or pre-populates the approval file on its own;
  it writes one only when asked to (`--write-approval`) **and** the registry's
  `write_mode` is `write`.
- **Absence of an approval file means nothing is approved.** Not "approve everything",
  not "ask again later".
- `airtable-actions-agent` may execute an action **only** if its `id` appears in
  `plans/YYYY-MM-DD/style-approval-<scope>.json` with `status: "approved"`.
- Plans expire at end of day. A stale plan is re-derived, never re-approved.
- **`held` rows carry no `id`** and are unapprovable by construction. Unlike the
  catalogue plan's pricing carve-outs there is nothing for a person to approve by hand:
  a held row is resolved through the `Action` column (which supplies a value — see
  `contracts/troubled-tags-schema.md`) or by fixing the cause (add a swatch, fill the
  spec, extend the rule table), then re-running. Keeping the approval file policy-only
  is what keeps it small enough to test exhaustively.

## The approval file — style-approval-1

`plans/YYYY-MM-DD/style-approval-<scope>.json`. Written by `/style-tag` under the
policy below, never by a person's hand in v1 and never while `write_mode` is
`plan_only`.

```json
{
  "contract_version": "style-approval-1",
  "scope": "faw",
  "plan": "plans/2026-09-26/style-plan-faw.json",
  "approved_by": "policy: style-tags auto-approval (v1 rubric)",
  "decisions": [
    {"id": "sty-3f1c9a0e7b22", "status": "approved", "at": "2026-09-26T10:20:00-04:00"}
  ]
}
```

| Field | Notes |
|---|---|
| `plan` | Path of the plan these decisions belong to. A writer must check it matches the plan it was handed |
| `decisions[].id` | An action `id` from that plan |
| `decisions[].status` | `approved`. Anything else is not an approval |

Every actions-log entry an approval leads to sets `"approved_by"` to the policy
string in the registry (`policy.approved_by`) — never a person's name, so the log
never overstates who looked at what.

### Policy auto-approval (2026-09-26, Albert — "go with the recommendations")

A tag is **approved** only if **all** of the following hold:

1. The target field is **blank** in the snapshot — and blank again at write time
   (`airtable-actions-agent` re-reads the record; see "What a write may set").
2. `Style tags status` is not **`Staff confirmed`** — checked at pull, at plan, and
   again at write. A `Staff confirmed` record is never a candidate, whatever is blank.
3. `confidence >= min_confidence` (0.7, registry) after the caps: `spec_only_style_cap`
   for `Style` on a record with no swatch or room scene; `hint_confidence` for supplier
   colour words and `Colour / tone`, which never write alone.
4. **No conflict**: where a spec rule and an image observation both exist for the
   field and both are `>= min_confidence`, they name the same value. Disagreement
   holds the field — never the higher score, never an average.
5. The value is a live option string (the run pre-flights every option in the registry
   against a fresh `get_table_schema` read and stops if one is missing), and for
   `Tone depth` an integer 1–5.

Two independent sources naming the same value earn `agreement_bonus` (0.1, capped at
1.0) and `source: both`.

**Which source may decide which field** — Albert, 2026-09-26, verbatim: *"Colour tags
(Undertone, Tone depth) come from Swatch images only; never from Room scene images
(room lighting skews colour). Style uses swatch + room scenes. Texture uses specs +
Detail images. No swatch → hold colour tags for review."*

| Field | Decides | Confirms or conflicts | Never |
|---|---|---|---|
| `Texture` | spec rule over `Finish type` | a `Detail images` close-up | a swatch or room scene alone |
| `Busyness` | spec rule over `Grade` + modifiers | any image (conflict check only) | image alone |
| `Undertone` | a `Swatch images` attachment the model read | colour words in the product name | `Room scene images`, `Detail images`, spec alone |
| `Tone depth` | a `Swatch images` attachment the model read | `Colour / tone`, light/dark words | `Room scene images`, `Detail images`, spec alone |
| `Style` | the model over specs + swatch + room scenes | — | `Detail images`; spec alone (capped below threshold) |
| a reviewer's `Action` answer | any field, confidence 1.0, `source: reviewer` | | |

The image's **field is what decides**, not the model's impression: an attachment in
`Room scene images` cannot reach `Undertone` at any confidence, structurally. The
model's `looks_like` on each image is a sanity check that can only *withhold* an image
(`image_misfiled`), never promote one.

### Held reasons

Fixed vocabulary; the script's `_held(...)` calls are tested against the registry's
`held_reasons`. A row is `held` (nothing written for that SKU × field) unless marked
`wrote_flagged`.

| Reason | Meaning | Disposition |
|---|---|---|
| `low_confidence` | Best candidate below `min_confidence`; `proposed` carries it so a reviewer can just say yes | `held` |
| `spec_image_conflict` | Spec rule and image disagree at `>= min_confidence` each; `proposed` names both, `spec\|image` | `held` |
| `no_swatch` | A colour field on a record with nothing usable in `Swatch images` — room scenes and detail images do not count | `held` |
| `image_host_blocked` | Swatches exist but the environment refused the download (proxy CONNECT 403 on the attachment host) | `held` |
| `image_format_unsupported` | The only swatches are in a format the reader cannot decode (HEIC) | `held` |
| `spec_unmapped` | `Finish type` / `Grade` not in the rule table, or absent while an image proposes a value it cannot decide alone | `held` |
| `needs_image` | `Style` proposed from specs alone (D4) | `held` |
| `answer_unparsed` | A reviewer's `Action` cell could not be read as `Field: Value` | `held` |
| `image_misfiled` | A `Swatch images` attachment the model says is a room scene or other non-swatch; nothing was read from it. One row per image, `field: Swatch images` | `held` |
| `reviewer_skipped` | The reviewer wrote `skip`; not proposed again, carried so the decision stays visible | `held` |
| `spec_rule_provisional` | Written from a rule the registry marks provisional (BCDE grade, embossed finishes) | `wrote_flagged` |

A blank field with **no information at all** — no spec value, no image, no judgement —
produces no row; it is counted in `summary.no_information`. The colour fields are the
exception: a blank `Undertone` or `Tone depth` always gets a row, because "no swatch
→ hold for review" is the instruction. Without that exception a report over 1,200 LVP
records with no `Finish type` would be 1,200 rows saying nothing.

## Envelope

| Field | Notes |
|---|---|
| `contract_version` | `"style-plan-1"` |
| `scope` | The scope slug (`faw`), which names every file of the run |
| `supplier` | Airtable `Supplier` value, verbatim |
| `run_at` | ISO 8601, America/Toronto |
| `write_mode` | The registry's `write_mode.mode` at plan time — `plan_only` or `write` |
| `approved_by` | The policy string an approval of this plan will carry |
| `inputs` | `[{file}]` — the candidates, judgements, answers and options files |
| `summary` | `records_in`, `actions_total`, `tags_total`, `tags_by_field`, `held`, `held_by_reason`, `flagged`, `no_information`, `images_status`, `answers_applied`, `answers_unmatched` |
| `actions` | ordered; one per record; each independently executable and idempotent |
| `held` | rows that must not be written, with the reason. Never carry an `id` |
| `flagged` | rows that were written carrying something worth knowing |

## Action

One per record, carrying every tag approved for it — because the write also sets the
status and appends the evidence, and those happen once per record.

| Field | Notes |
|---|---|
| `id` | `sty-<sha1[:12]>` over sku + `airtable` + `update_style_tags` + the sorted field names written. **Stable across re-runs** for the same logical write; a different field set is a different write |
| `seq` | Execution order. Ascending, gapless |
| `target_system` | `airtable` |
| `op` | `update_style_tags` |
| `record_id` | The Airtable record id — the write is by id, never an upsert |
| `sku` · `product_name` · `supplier` | For the reader; the SKU is never in the payload |
| `fields` | `{field: value}` — exactly what the agent writes to the tag fields. `Style` is a list; `Tone depth` an int |
| `tags` | `{field: {value, confidence, source, evidence, image, provisional, rule}}` — the reasoning behind each entry of `fields` |
| `status_write` | `"AI suggested"` when the record's status is blank, else `null` (leave it) |
| `evidence_append` | The block to append to `Style tags evidence`: a header line naming this plan, then one line per written tag |
| `flags` | `["spec_rule_provisional"]` where applicable |

`tags[].source` is one of `spec | image | both | reviewer`.

## The judgement file — style-judgements-1

`ingest/YYYY-MM-DD/style-judgements-<scope>.json`. Written by the session model in
`/style-tag` step 3 (D6) after reading each candidate's downscaled images and its
specs; committed, because it is the audit trail of what the model saw. The plan script
decides what each observation is worth — the model never writes a tag.

```json
{
  "contract_version": "style-judgements-1",
  "scope": "faw",
  "judged_at": "2026-09-26T10:05:00-04:00",
  "records": [
    {
      "sku": "ENG-FAWK-0060",
      "images": [
        {"attachment_id": "attXXXX", "looks_like": "swatch", "usable_for_colour": true,
         "note": "flat supplier swatch, neutral white border"}
      ],
      "undertone":     {"value": "Warm", "confidence": 0.82, "from": "attXXXX",
                        "evidence": "golden-brown cast on the swatch, no grey"},
      "tone_depth":    {"value": 3, "confidence": 0.78, "from": "attXXXX",
                        "evidence": "mid-brown; lighter than the walnut siblings"},
      "texture_seen":  {"value": "Brushed", "confidence": 0.7, "from": "attYYYY",
                        "evidence": "open grain lines across the close-up"},
      "busyness_seen": {"value": "Moderate", "confidence": 0.75, "from": "attXXXX",
                        "evidence": "a few small knots, mild colour shift"},
      "style": {"values": ["Modern", "Scandinavian"], "confidence": 0.7,
                "evidence": "light neutral oak, long plank, low knot count"}
    }
  ]
}
```

Rules the plan script enforces, so a judgement cannot smuggle a room scene into a
colour tag:

- `from` must name an attachment on the candidate's manifest. `undertone` and
  `tone_depth` count only when it is in `Swatch images`, downloaded, not `looks_like`
  something else, and not `usable_for_colour: false`. `texture_seen` counts only from
  `Detail images`. `busyness_seen` from a swatch or a detail image, conflict check only.
- `looks_like` is `swatch | room | detail | spec_sheet | other`. A swatch attachment
  with any other `looks_like` is `image_misfiled`.
- `style.values` are live option strings; non-options are dropped and noted. `style`
  writes only when the record has a usable swatch or room scene; otherwise it is held
  `needs_image` at `spec_only_style_cap`.
- A record with no images may still carry `style` (from specs) — it will be held. It
  may not carry `undertone` or `tone_depth` at all; if it does, they are ignored.

## What a write may set

`airtable_update_style_tags` — the one action type this plan produces — writes, by
record id, only: the five tag fields named in `fields`, `Style tags status` (to
`AI suggested`, only when blank), and `Style tags evidence` (append). Nothing else,
ever: not `Colour / tone`, not the image fields, not `Salesperson notes`. The full rules
are in `.claude/agents/airtable-actions-agent.md`; the registry's `targets`,
`status_field` and `evidence_field` are the closed list.

**Read before write.** The snapshot can be hours old and a staff member may have
confirmed the record in between. The agent re-fetches each record and drops any field
that is no longer blank (`stale_not_blank`) or refuses the record outright if it is now
`Staff confirmed` (`stale_staff_confirmed`). The plan's blank-only promise is only true
at write time if it is checked at write time.

A record whose every candidate is held gets **no write at all** — not even the status.
`AI suggested` is set only when at least one tag lands.

## An action only exists if it changes something

Same rule as the catalogue plan. A record with nothing approved has no action; a
re-run after the writes landed finds the fields filled and plans nothing for them.
That is what makes "run it again" the resume procedure, with the actions log's
`raw_ref_action_id` skip as the only state.
