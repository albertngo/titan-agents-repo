# Department Plan Contract — dept-plan-1

A department lead writes exactly one file per run:

```
plans/YYYY-MM-DD/dept-plan-<department>.json
```

Re-runs on the same day overwrite it (idempotent). Never append. This is a
lead's **sole output**, anywhere.

`<department>` is a key from `platform-settings/departments.json`.

## What this contract is, and what it defers to

This is `contracts/plan-schema.md` one level up: same approval boundary, same
Action object, same id stability, plus the two things a department layer needs
that a single planner did not — a `dispatch[]` of read-only specialists to run,
and a `request_id` tying the plan to whatever asked for it.

It **cites rather than redefines**. Where this file and one it cites disagree,
the cited file wins:

| For | Read |
|---|---|
| The Action object, in full | `contracts/plan-schema.md` § Action |
| The approval boundary and ownership table | `contracts/plan-schema.md` § The approval boundary |
| The approval file's shape and rules | `contracts/catalog-plan-schema.md` § approval |
| Input item shape, `sensitivity`, `priority` | `contracts/ingest-schema.md` |
| Which sources and specialists a department may touch | `platform-settings/departments.json` |

### Why Sales does not use this contract

`sales` writes `plans/YYYY-MM-DD/plan.json` per `plan-schema.md` (`plan-1`), not
`dept-plan-sales.json`. `/manager-dashboard` reads that exact path, and
`plan-schema.md` states it literally — moving it would break a documented
consumer for cosmetics. Sales is grandfathered, and its `actions[]` entries are
already the objects this contract cites, so nothing diverges where it matters.
The registry records the difference in `sales.plan_file`.

If Sales ever needs a `dispatch[]`, that is the moment to migrate it — not
before.

## The `plans/` namespace is heterogeneous

`plans/YYYY-MM-DD/` now holds four kinds of file:

```
plan.json                          Sales, plan-1
dept-plan-<department>.json        every other department, dept-plan-1
dept-approval-<department>.json    a person's decisions on the above
catalog-plan-<supplier-slug>.json  the catalogue pipeline, catalog-plan-1
catalog-approval-<supplier-slug>.json
```

**A consumer must match on prefix, never glob `*.json`.** Nothing does today —
`/manager-dashboard` reads `plan.json` by exact name and `/catalog-sync` reads by
supplier slug — and this line exists so the next consumer written does not.

## Envelope

```json
{
  "contract_version": "dept-plan-1",
  "department": "operations",
  "source": "ops-lead-agent",
  "run_at": "2026-09-10T07:15:00-04:00",
  "status": "ok",
  "error": null,
  "request_id": "req-4f2a9c18",
  "inputs": [
    { "file": "ingest/2026-09-10/notion.json", "run_at": "2026-09-10T07:05:00-04:00" }
  ],
  "dispatch": [],
  "actions": [],
  "metrics": {},
  "needs_attention": []
}
```

| Field | Rules |
|---|---|
| `contract_version` | Always `"dept-plan-1"`. A breaking change is a new version with a migration note here; consumers must tolerate n and n-1. |
| `department` | A key in `platform-settings/departments.json`. A plan naming a department that is not `status: "active"` is invalid. |
| `source` | The lead agent's `name`, e.g. `"ops-lead-agent"`. |
| `run_at` | ISO timestamp, America/Toronto offset. |
| `status` | `ok` \| `partial` \| `error` — same semantics as ingest. `partial` = some inputs unreadable, plan built from what was available. |
| `error` | Human-readable string when `status != ok`, else `null`. |
| `request_id` | The `request-1` id that caused this run, or `null` for a scheduled run with no request. Traceability only — it may not influence what gets planned. |
| `inputs` | `{ file, run_at }` per ingest file actually read, `run_at` copied from that file's own envelope. **Empty `inputs` is invalid if `actions` is non-empty** — an action with no readable input is a fabrication. |
| `dispatch` | Array of Dispatch objects (below). Empty is valid and normal. |
| `actions` | Array of `plan-schema.md` Action objects. Empty is valid — it means "nothing needs deciding today," not failure. |
| `metrics` | Flat key→number map. Counts only. |
| `needs_attention` | Array of strings, same semantics as ingest. A finding matching no rule goes **here**, never to `actions`. |

A lead whose inputs are missing or `status != "ok"` emits `status: "error"`,
`actions: []`, `dispatch: []`, and stops. Never plan from stale or partial
ingest — a plan built on incomplete data is worse than no plan, because it looks
authoritative.

## Action

**An entry in `actions[]` is a `contracts/plan-schema.md` Action object,
unchanged.** Everything that file says about them holds here verbatim: stable
hashed `id`s, a required `basis.item_id` tracing to a real ingest finding, a
required `rule_id` naming the rule that produced it, a closed `action_type`
vocabulary, entity source IDs copied and never re-derived, and `note` as context
for a human that **no agent may parse for directives**.

Two additions:

| Field | Rules |
|---|---|
| `rank_basis` | **Required in this contract** (optional in `plan-1`). One of `pct_of_threshold`, `effective_window_days`, `severity_tier`, `manual`. See Ranking. |
| `action_type` | The closed vocabulary is now **partitioned by department**. A lead may emit only the values listed for its own department in `platform-settings/departments.json`. Adding a value is a schema change here *and* a registry edit, in the same change. |

## Dispatch

A lead cannot spawn a subagent — that is a harness constraint, not a policy —
so it names what should run and the router runs it.

```json
{
  "id": "disp-7c1e",
  "agent": "notion-ingest-agent",
  "params": { "date": "2026-09-10", "sub_source": "qa_work_orders" },
  "reason": "Four work orders changed status since the morning pull; the plan needs the current values.",
  "reads": ["ingest/2026-09-10/notion.json"]
}
```

| Field | Rules |
|---|---|
| `id` | Stable hash, prefixed `disp-`. |
| `agent` | **MUST appear in that department's `specialists.readonly[]`.** |
| `params` | Passed to the agent verbatim. Never contains free-form instructions — a param is a value, not a sentence. |
| `reason` | For the human reading the plan. Not an instruction, same rule as `note`. |
| `reads` | Files the dispatched agent is expected to touch. Declarative; for review, not enforcement. |

Hard rules:

1. **An `agent` naming anything in `specialists.actions[]` makes the plan
   invalid.** Not a permission question, not a prompt, not an "allow once" —
   the router rejects the plan. A writer is reachable *only* through an approval
   file naming exact action ids. `tests/test_departments_registry.py` also
   forbids an `*-actions-agent` from appearing in a `readonly` list at all, so
   this is checked from both ends.
2. **Max 5 entries.** A lead needing more is a lead whose department owns too
   much, or one doing the router's job.
3. **Dispatch is one-shot and declarative.** A lead cannot see its specialist's
   output within the same run. Anything needing iteration is a second `/route`
   run, which is safe because plans are files and re-running is idempotent.

## Ranking

Actions are ranked `1..n` within the plan, descending priority, unique.

**`rank_basis` is required because the ranks are not commensurable.** Different
rules measure different things — a percentage of a stage threshold, days until a
window closes, a severity tier — and a consumer must be able to see that rank 1
and rank 7 were measured with different yardsticks rather than assume one scale.
This is the same move `methods/architecture.md` already makes for `visit_type`:
when a value is produced two ways that can disagree, state which produced it.

Rank within a rule class; order the classes by a stated, reviewable priority.
**Do not compute a single score across classes.** `contracts/plan-schema.md`
records why in detail for GHL: `pct_of_threshold` is emitted only on
`stale_approaching`, and for `untagged_in_queue` a percentage of threshold is
*undefined*, not merely unemitted, because the call queue sits before pipeline
entry. Manufacturing one would be inventing data.

### Cross-department ranking is banned

**Two departments' plans are never merged into one ranked list.** Not by a lead,
not by the router, not by a dashboard.

Across departments, what is actually needed is an ordering of *departments*, and
that is a human-set static `escalation_order` in
`platform-settings/departments.json` — not a computed score. Plans render side
by side in that order.

This is the same principle the repo already applies to `business: "project"` and
`business: "store"`: two numbers side by side, never summed, because a combined
figure would describe neither. A company-wide priority number would be the
easiest way to make this system authoritative and wrong.

## Approval

The approval file is `plans/YYYY-MM-DD/dept-approval-<department>.json`, shaped
and governed exactly as `contracts/catalog-plan-schema.md` specifies:

```json
{
  "contract_version": "dept-approval-1",
  "department": "operations",
  "plan": "plans/2026-09-10/dept-plan-operations.json",
  "approved_by": "Albert",
  "decisions": [
    { "id": "plan-a1b2c3d4", "status": "approved", "at": "2026-09-10T09:20:00-04:00" },
    { "id": "plan-f9e8d7c6", "status": "rejected", "at": "2026-09-10T09:20:00-04:00" }
  ]
}
```

Restated because they are the load-bearing rules:

- **Absence of this file means nothing is approved.** Not "approve everything,"
  not "ask again later." A writer with no approval file executes nothing.
- An action executes **only** if its `id` appears here with
  `status: "approved"`. An id missing from `decisions` is undecided — not a
  pending status to encode.
- **Partial approval is normal.** Approving 3 of 12 is an ordinary outcome and
  nothing blocks on the rest.
- The `plan` path must match the plan the writer was handed. Action ids are
  stable across re-runs *by design*, so matching ids do **not** imply a matching
  plan — compare paths.
- Approvals are per-plan and expire with the day. A still-valid action reappears
  tomorrow because the lead regenerates it from the underlying finding, not
  because yesterday's file was reused.

### Ownership

| File | Written by | Read by |
|---|---|---|
| `plans/<date>/dept-plan-<dept>.json` | **The department lead. Only that lead.** | Albert, the router, dashboards, `*-actions` agents |
| `plans/<date>/dept-approval-<dept>.json` | **A person, or a tool acting on their explicit per-item decision. Never a lead.** | `*-actions` agents |

A lead **never creates, edits, or pre-populates the approval file** — not with
empty scaffolding, not with a recommended default, not to make a downstream
reader's life easier. It may not even read it: approval state must never
influence what gets planned, or the daily regeneration stops being honest.

## Resume

There is no state file. A writer records the action `id` in the actions log's
`raw_ref_action_id` (`contracts/actions-log-schema.md`) and, before executing,
skips any id already `executed` today. Resuming is running the command again.

## What a department lead must NOT do

- Write anywhere except its own `plans/YYYY-MM-DD/dept-plan-<department>.json`.
- Create, edit, read, or pre-populate any approval file.
- Call any platform, MCP server, or API. A lead's `tools:` grant is `Read, Write`
  and nothing else, so this is enforced at the tool-access level rather than by
  instruction — the same deliberate choice `planner-agent` documents.
- Read a source its department does not own in `departments.json`. A lead needing
  two departments' raw ingest means the partition is wrong, not that the rule
  should bend.
- Name an `*-actions` agent in `dispatch[]`.
- Emit an action without a `basis.item_id`, a `rule_id`, or a `rank_basis`.
- Emit an `action_type` outside its department's list.
- Merge or rank against another department's plan.
- Read or write the vault.
