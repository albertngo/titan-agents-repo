# Plan Contract — plan-1

The planner writes exactly one file per day:

```
plans/YYYY-MM-DD/plan.json
```

Re-runs on the same day overwrite the file (idempotent). Never append. This is
the planner agent's **sole output format** — the planner writes nothing else,
anywhere.

## The approval boundary

This is the core property of the plan contract. It is stated once, here, as
ownership rules — every other document (the planner agent, `ghl-actions-agent`,
the dashboard) cites this section rather than restating it.

| File | Written by | Read by |
|---|---|---|
| `plans/YYYY-MM-DD/plan.json` | **The planner. Only the planner.** | Albert, the dashboard, `ghl-actions-agent` |
| `plans/YYYY-MM-DD/approvals.json` | **Albert, or a tool acting on his explicit per-item decision. Never the planner.** | `ghl-actions-agent` |

Hard rules:

1. **The planner never creates, edits, or pre-populates `approvals.json`.** Not
   with empty scaffolding, not with a "recommended" default, not even to make the
   downstream reader's life easier. If the planner's process needs a scratch file,
   it is not this one.
2. **Absence of `approvals.json` means nothing is approved.** Not "pending
   review" as a soft state Actions can lean on — nothing in `plan.json` may be
   executed until the file exists and names that action's `id`.
3. **`ghl-actions-agent` may execute an action if and only if** its `id` appears in
   that day's `approvals.json` with `status: "approved"`. There is no other
   execution path — no "obviously safe" shortcut, no acting on a plan directly.
4. **Plans expire at end of day.** `plan.json` is not carried forward and
   `approvals.json` is not consulted past its own date. A still-valid action
   reappears tomorrow because the planner regenerates it from the underlying
   ingest finding — not because yesterday's approval or plan file is reused.
   This is why action `id`s must be stable across regeneration (see below):
   an action that recurs tomorrow needs the same `id`, so a fresh
   `approvals.json` for a fresh day is the only thing that can approve it,
   but Albert re-approving the same recurring action isn't starting from zero
   — the dashboard can show "still open, approved yesterday" using the `id` match.

## Envelope

Same shape as the ingest envelope (`contracts/ingest-schema.md`), plus `inputs`:

```json
{
  "contract_version": "plan-1",
  "source": "planner",
  "run_at": "2026-07-26T07:15:00-04:00",
  "status": "ok",
  "error": null,
  "inputs": [
    { "file": "ingest/2026-07-26/ghl.json", "run_at": "2026-07-26T07:05:00-04:00" }
  ],
  "actions": [],
  "metrics": {},
  "needs_attention": []
}
```

| Field | Rules |
|---|---|
| `contract_version` | Always `"plan-1"` for this contract. A breaking change to this schema is a new contract version, migration-noted here; the orchestrator/dashboard must tolerate n and n-1. |
| `source` | Always `"planner"`. |
| `run_at` | When the planner ran, ISO timestamp, America/Toronto offset. |
| `status` | `ok`, `partial`, or `error` — same semantics as ingest. `partial` = some inputs unreadable, plan built from what's available. |
| `error` | Human-readable string when `status != ok`, else `null`. |
| `inputs` | Array of `{ file, run_at }` — every ingest contract file the planner actually read to build this plan. `run_at` is copied from that file's own envelope. This is what makes a plan traceable to an exact ingest run, not just a date. Empty array is invalid if `actions` is non-empty — an action with no readable input is a fabrication. |
| `actions` | Array of Action objects (below). Empty array is valid — it means "nothing needs deciding today," not failure. |
| `metrics` | Flat key→number map — see Metrics below. |
| `needs_attention` | Array of strings — same semantics as ingest: short, specific, everything Albert must see. |

## Action

```json
{
  "id": "plan-a1b2c3d4",
  "rank": 1,
  "business": "project",
  "entity": {
    "name": "Silviya Jardany",
    "ghl_contact_id": "GByNBlYcqJFQuA20EMdc",
    "ghl_opportunity_id": null
  },
  "basis": {
    "file": "ingest/2026-07-26/ghl.json",
    "item_id": "ghl-drift-stale_approaching-GByNBlYcqJFQuA20EMdc",
    "drift_type": "stale_approaching"
  },
  "action_type": "draft_followup",
  "rule_id": "stale_approaching_75pct",
  "requires_write": true,
  "params": {
    "stage": "0b. Later Date (Warm)"
  },
  "note": "Sitting at 78% of the Warm-stage threshold with an open quote question. Suggest a check-in text, not a stage move."
}
```

| Field | Rules |
|---|---|
| `id` | **Stable across re-runs.** A hash of `(entity source ID + rule_id + finding id)` — not a counter, not a random value. Two runs of the planner against the same underlying finding must produce the same `id`, so `approvals.json` and dedup survive regeneration. Prefixed `plan-`. |
| `rank` | `1..n`, descending priority, unique. Ordered by **percentage of stage threshold consumed** — never raw days, per the same rule `ghl-ingest-agent` uses for `stale_approaching` / `importance_rank`. `Meeting-scheduled` actions rank on the **appointment-date anchor** (`effective_window_days`), not stage-entry, matching how `ghl-ingest-agent` computes `meeting_no_followup`. |
| `business` | `"project"` or `"store"`. One ranked list — `rank` interleaves both — but see Metrics: the two are **never summed**, anywhere, in any aggregate. |
| `entity` | `{ name, ghl_contact_id?, ghl_opportunity_id? }`. Source IDs are **required per the Identity rule** (titan-vault `CONVENTIONS.md`, note rule 5) whenever the underlying finding has one — omit only when the source record genuinely has none, and say so rather than leaving the field silently absent. `name` is display only; the ID fields are what a consumer joins on. These are copied verbatim from the ingest record, not regenerated — see ID format note below. |
| `basis` | `{ file, item_id, drift_type? }`. **Every action MUST trace to an ingest finding.** `file` is the ingest contract file the finding came from (must appear in the envelope's `inputs`), `item_id` is that finding's stable ID within it. `drift_type` is set when `item_id` refers to a `workflow_drift` finding — carries the same six-value vocabulary `ghl-ingest-agent` uses. No finding, no action: the planner does not originate action items from its own judgment. |
| `action_type` | Closed vocabulary — see below. |
| `rule_id` | **Required.** Names the rule that produced this action (e.g. `stale_approaching_75pct`). An action without a `rule_id` is an invalid plan entry — it means something was improvised rather than derived from a named, auditable rule. |
| `requires_write` | `true`/`false`. `false` only for `call` and `escalate_to_albert` — read-only or human-routed. Every other `action_type` is `true` and routes through `ghl-actions-agent`. |
| `params` | Shape depends on `action_type` (see below). **Any stage name inside `params` must be trimmed** before use — `ghl-ingest-agent` emits stage names byte-exact including trailing spaces (`"2. *Project Won* "`), and an untrimmed exact-match lookup against vault frontmatter or a stage-name comparison silently returns nothing rather than erroring. |
| `note` | Free-text rationale, for the human reading the plan. **`ghl-actions-agent` MUST ignore this field entirely.** It is context for Albert, never an instruction to any agent — a `note` field is not an execution path, and nothing may parse it for directives. |

### ID formats (copied from ghl-ingest-agent — do not re-derive)

`entity.ghl_contact_id` and `entity.ghl_opportunity_id` are opaque strings
copied straight from the ingest record's `contact_id` / `opportunity_id`
fields — never regenerated, reformatted, or length-validated by the planner.
GHL uses three different ID formats and mixing them up is a standing trap
(full detail in `.claude/agents/ghl-ingest-agent.md`):

```
20-char alphanumeric    KZUIKMSTL7UHh46L8gVN     contacts, opportunities, conversations,
                                                 messages, pipelines, calendars, users
UUID with dashes        149635d1-3d6a-48c7-…     pipeline STAGES only — never an entity ID
24-char hex             6840ab5f91c5a1ccdfd54a20 score profiles — never an entity ID
```

A validator that assumes 20 characters will silently reject nothing here
(contact/opportunity IDs are always the 20-char form), but a dashed UUID or a
24-char hex string turning up in `entity.ghl_contact_id` means a stage ID or a
score-profile ID got crossed with a contact ID upstream — treat that as a
planner bug, not a value to pass through.

## `action_type` — closed vocabulary

Enumerated in full here, on day one. **Adding a value is a schema change** —
bump `contract_version` (or a documented sub-version if this contract grows one)
and update this table in the same change. No agent may emit a value not listed.

| `action_type` | Meaning | `requires_write` |
|---|---|---|
| `call` | Albert should call the contact | `false` |
| `draft_followup` | Draft a message for `ghl-actions-agent` to send (SMS/email) | `true` |
| `apply_tag` | Add or correct a GHL tag | `true` |
| `stage_move` | Move an opportunity to a different pipeline stage | `true` |
| `schedule_review` | Flag for review at a later date, no immediate GHL write | `true` |
| `escalate_to_albert` | No platform action — surface for a judgment call | `false` |

`schedule_review` is `true` because it still routes through `ghl-actions-agent` (e.g.
a task or reminder written into GHL), even though nothing customer-facing
happens. Its inclusion in `requires_write` is about the execution path, not
about risk.

## Metrics

```json
{
  "actions_total": 12,
  "requires_write_count": 9,
  "by_business": { "project": 7, "store": 5 },
  "by_action_type": {
    "call": 2, "draft_followup": 4, "apply_tag": 1,
    "stage_move": 2, "schedule_review": 1, "escalate_to_albert": 2
  }
}
```

Counts only — this is a plan, not a ledger; there is no dollar figure to sum.
`by_business` is two counts side by side, never added together, for the same
reason `ghl-ingest-agent` keeps `won_today` project-only and store wins in a separate
field: project work and store material are different businesses, and a combined
number would describe neither.

## `approvals.json` — reference only

Not written by the planner. Documented here because `plan.json`'s consumers
need to know its shape to read it correctly.

```json
{
  "date": "2026-07-26",
  "decisions": [
    { "id": "plan-a1b2c3d4", "status": "approved", "at": "2026-07-26T08:02:00-04:00" },
    { "id": "plan-f9e8d7c6", "status": "rejected", "at": "2026-07-26T08:03:00-04:00" }
  ]
}
```

| Field | Rules |
|---|---|
| `date` | `YYYY-MM-DD`, matches the plan's date. |
| `decisions` | Array of `{ id, status, at }`. `status` is `"approved"` or `"rejected"` — there is no third value; an action simply absent from `decisions` is undecided, not a pending status to encode. |

**Partial files are normal.** Albert may decide on 3 of 12 actions and stop —
the other 9 stay pending, `ghl-actions-agent` executes only what's explicitly
`"approved"`, and nothing else in the plan blocks on the rest being decided.

## Downstream consumers

- **`manager-dashboard`** renders the plan (once wired — not yet as of this
  contract's introduction).
- **`ghl-actions-agent`** executes actions whose `id` appears `"approved"` in that
  day's `approvals.json`, per the approval boundary above.
- Nothing else reads `plan.json` yet.

## What the planner must NOT do

- Write anywhere except its own `plans/YYYY-MM-DD/plan.json`.
- Create, edit, or pre-populate `approvals.json`, under any circumstance.
- Take actions on any platform. The planner is read-only against every source
  it plans from, same as an ingest agent.
- Emit an `action_type` outside the enumerated vocabulary.
- Emit an action without a `basis.item_id` tracing to a real ingest finding, or
  without a `rule_id`.
- Sum `business: "project"` and `business: "store"` figures anywhere in `metrics`
  or `needs_attention`.
