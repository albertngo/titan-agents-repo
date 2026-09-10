# Departments

The org chart, and what has to be true before a box on it becomes real.
Written 2026-09-10. If this drifts from `CLAUDE.md`, `CLAUDE.md` wins;
`platform-settings/departments.json` is authoritative for who owns what.

---

## The shape

```
  intake            chat · cloud Routine · Notion row · inbound mail · (WhatsApp)
     |                        normalized to contracts/request-schema.md
     v
  ROUTER            /route                      main thread — spawns, never touches a platform
     |                resolve requester -> tier · classify -> department · spawn lead · report
     v
  DEPARTMENT LEAD   <dept>-lead-agent           Read/Write only. Reads its own sources.
     |                writes ONE plan: actions[] + dispatch[]. Proposes. Originates nothing.
     v
  [ A PERSON APPROVES ]   plans/<date>/dept-approval-<dept>.json
     |
     v
  SPECIALISTS       the existing *-ingest (read) and *-actions (write) agents, unchanged
```

This is the same **ingest → decide → act** flow the repo has always had. The
department layer is the *decide* tier, which until now existed only as a parked
spec. Nothing about ingest or act changes.

### Why a lead plans instead of delegating

**A subagent cannot spawn another subagent.** That is a harness constraint, not a
policy, and it is the single fact that shapes the whole layer: a department lead
cannot call in its own specialists.

So a lead does not have subordinates at runtime — it has **a plan naming them**.
It reads contract files, writes one plan with an `actions[]` (what should happen
on a platform, gated by approval) and a `dispatch[]` (which read-only specialists
should run), and the router does the spawning.

That is not a workaround. It is the repo's existing invariant — *agents
coordinate through data, not conversation* — and it is exactly the relationship
`planner-agent` already had to `ghl-actions-agent`, one level up.

Two properties keep it from becoming a spawn-anything hole:

1. **`dispatch[]` may only name read-only specialists.** An `*-actions` agent is
   unreachable from a dispatch by construction — it is reachable only through an
   approval file naming exact action ids. Enforced from both ends:
   `tests/test_departments_registry.py` forbids a writer in a `readonly` list,
   and `contracts/dept-plan-schema.md` makes naming one an *invalid plan*, not a
   permission question.
2. **`actions[]` entries are `contracts/plan-schema.md` Action objects,
   unchanged** — stable ids, a required `basis.item_id` tracing to a real ingest
   finding, a required `rule_id`, a closed `action_type` vocabulary.

Isolation also makes leads affordable. `ghl.json` is 210 KB, `notion.json` 49 KB.
Five leads reading in the main thread would put 400 KB of raw ingest in one
context; five leads reading in their own contexts costs the router four numbers
and a file path each.

---

## The departments

| Department | Owns | Lead | Status |
|---|---|---|---|
| **Sales** | `ghl` | `planner-agent` | active — the reference build |
| **Operations** | `notion` (5 sub-sources) | — | spec: source is live, no rule table yet |
| **Catalogue** | Airtable · Lightspeed · price lists | `/catalog-sync` | active — already complete before this layer existed |
| **Marketing** | `meta-ads` | — | registry_only: Tier 1 work missing |
| **Finance** | `bookkeeper` | — | **blocked: the source has never worked** |
| **General** | `outlook` | — (`/route` answers inline) | active — the fallback lane |

`platform-settings/departments.json` carries the detail: owned sources,
specialists, route keywords, and for every non-active department the criteria
that would change its status.

### Catalogue is the proof, not the exception

Catalogue was a department before the word existed: a lead
(`/catalog-sync` plus `scripts/catalog_reconcile.py`), a plan contract, a
per-action-id approval file, two specialist writers, three registry files, and
its own routines. Its `kind` is `command`, not `agent` — its lead is a command
because its planning step is Python, and expect that to be true of some future
departments too.

It is registered so routing is complete, **not so it can be rebuilt**. Every
other department is that shape with pieces missing. Build toward it.

### Ownership keys on source, never on platform

Notion forces this. `notion-ingest-agent` reads five databases for Operations,
while `/notion-sync` writes GHL-derived rows into the same Tactical Tasks List
for Sales. Platform-level ownership would make Notion ambiguous; source-level
ownership makes it a partition — which is what makes classification
deterministic and testable.

`owns.sources[]` across all departments **must be a partition** of the ingest
sources in `CLAUDE.md`'s table: every source owned exactly once. A source owned
twice routes non-deterministically; a source owned by nobody falls silently to
General. The registry test enforces both.

`outlook` routes to **General**, not to a department of its own, because staff
mail has no correct destination yet — the per-staff private Notion databases
Albert specified on 2026-08-03 are unbuilt, and the sequencing rule in
`contracts/notion-task-schema.md` is destination first, eligibility list second.

---

## What is deliberately not a department

`CLAUDE.md`'s analysis ladder says structure is earned by being re-run, not by
being interesting. Applied here:

- **HR / People, Legal / Compliance** — no data source in this repo at all. Not
  even Tier 0.
- **Customer Care / Warranty** — real work, but `notion.json` already carries
  `work_order_deficiency` and `work_order_warranty` item types inside
  Operations. Splitting it out makes two leads read the same file. Promote on the
  second time warranty needs its own answer, not before.
- **IT / Systems health** — `ingest/run-ledger.json` and the exec dashboard's
  health footer already cover it. It is a *section* of General's output.
- **Finance**, for now — see below. It is registered, because leaving it off the
  chart would hide the problem rather than state it.

### Finance is blocked, not deferred

`bookkeeper-ingest-agent` has written `status: "error"` on **every recorded run
from 2026-07-26 through 2026-09-08** — sixteen consecutive failures. No Intuit
QuickBooks MCP server is configured in `.mcp.json`, and there is no
`scripts/bookkeeper_pull.py` equivalent to `scripts/outlook_pull.py`.

A Finance lead over that source would read an empty file every day and emit an
empty plan. Worse, the department layer would make the outage *less* visible by
giving the failure a tidy org-chart box to sit in.

So Finance carries `status: "blocked"` with its reason and unblock criteria as
data. A finance-shaped request gets the block reason, then whatever the Notion
`master_payments_log` does know, **labelled partial**. A payments-log figure is
not bookkeeping, and GHL `value_cents` is pipeline value, not money received —
neither may be presented as if it answered the question.

Unblock: three consecutive `bookkeeper: "ok"` entries in `run-ledger.json`. Then
write the lead from those three real days.

### Marketing needs Tier 1 before Tier 3

Rule of two is arguably met — `meta-ads` is ingested daily and
`analysis/lead_funnel.py` attributes leads to source — but the *promotion target*
is wrong. `meta-ads` is the only ingest source with no `platform-settings/` file,
and there is no `methods/marketing-framework.md` defining CPL or its baseline. A
lead built today would hardcode the "~$14 7-day CPL baseline" the daily brief
keeps quoting from nowhere.

Build the framework doc and the thresholds registry first. Promote when a second
distinct marketing question arrives.

---

## Routing

Fixed precedence, first match wins, no scoring, no confidence thresholds — the
same discipline `notion-sync.md` uses for sensitivity: **routing is a lookup,
never inferred from content.**

1. **explicit** — the text names a department key or matches a `route_keywords[]`.
2. **command_named** — names a command in some department's `owns.commands[]`.
3. **source_named** — names a source, sub-source, or platform owned by exactly one.
4. **fallback** — General.

More than one match at a step: record all of them and **ask**. Ambiguity is
surfaced, never resolved silently — the same posture as `blocked` entries in a
catalogue plan.

### Requesters and tiers

`platform-settings/requesters.json` maps an identity to a `tier` (`admin` |
`staff`) and the departments it may reach. Fail-closed at every step: an
unregistered identifier is **refused**, never downgraded to staff and never asked
to identify itself — an unregistered identity answering that question is not
evidence.

A tier that may not reach a department is told so, and told which departments it
*can* reach. It is never silently rerouted to General: a staff member asking
Finance a question should learn they cannot, rather than receive a General answer
that looks like the answer.

**The repo is public.** `requesters.json` carries hashed channel identifiers, or
none at all if Make resolves the raw identifier upstream. No phone numbers, no
personal addresses — the registry test checks for both.

### Sensitivity is not a department concept

The layer adds **no routing axis**. Item `sensitivity` stays exactly where it is:
set at ingest per item, defaulted per source in `notion-destinations.json`,
escalation-only `team → private`, unknown reads as private.

**A department is not a sensitivity boundary.** This is the mistake everyone will
make ("Finance = private"). Provenance decides, per Albert 2026-08-02. A `team`
GHL item stays team when it passes through a lead; a `private` bookkeeper item
stays private whatever the department is called.

The one new rule is a *filter*, not an axis: an item marked `private` is never
returned to a `staff`-tier requester, and the count withheld is stated rather
than silently omitted. It applies at reply time, so the plan on disk is identical
regardless of who asked.

`write_policy` is untouched. It lives on the destination being written to, not on
the department doing the writing.

---

## Ranking, and the thing we refuse to compute

Within a department, rank class by class and say which yardstick produced each
rank — that is what `rank_basis` is for. `planner-agent`'s Ranking section works
the rule for GHL, where `pct_of_threshold` exists only on `stale_approaching` and
is genuinely **undefined** for `untagged_in_queue` (the call queue sits before
pipeline entry).

**Across departments, there is no ranking at all.** Not by a lead, not by the
router, not by a dashboard. What is actually needed there is an ordering of
*departments*, and that is the human-set `escalation_order` in the registry, not
a computed score. Plans render side by side in that order.

Same principle the repo already applies to project vs. STORE pipelines: two
numbers side by side, never summed, because a combined figure would describe
neither. A company-wide priority number would be the easiest available way to
make this system authoritative and wrong.

---

## Adding a department

1. Add the entry to `platform-settings/departments.json`. If it cannot be
   `active` yet, give it `spec` / `registry_only` / `blocked` **and the criteria
   that would change that** — a parked box with no criteria is an omission
   wearing a status field.
2. Run `python3 -m unittest discover -s tests` — the registry test will catch a
   source owned twice, a dangling agent name, or a writer in a `readonly` list.
3. When it earns a lead: one file in `.claude/agents/`, `tools: Read, Write` and
   nothing else, conforming to `contracts/dept-plan-schema.md`, with its own rule
   table. No rule table means no lead — a lead that improvises is exactly what
   *"the planner invents nothing"* exists to prevent.
4. `/route` does not change. **If adding a department requires editing
   `route.md` or `dept-plan-schema.md`, the abstraction is wrong** — fix the
   abstraction before adding the department.

`.claude/commands/daily-ingest.md` never changes. The department layer is
additive; the daily brief keeps working exactly as it does today, and a
department failing must never touch it.

---

## Known risks

- **Approval fatigue.** Five departments each emitting approvable plans daily
  produces more gates than anyone reads, and an unread gate gets rubber-stamped —
  which is worse than no gate. Only Sales is anywhere near a schedule, and even
  it is on-demand for now. Put a lead on a schedule when there is evidence its
  plans get read, not before.
- **Ownership drift.** The partition holds only while someone maintains it. The
  registry test is what makes that mechanical rather than a promise.
- **Scope creep on `dispatch[]`.** The likeliest future mistake is adding an
  actions agent to a `readonly` list "just for this one case." Forbidden by test
  and by contract. Keep both.
- **Un-versioned Routine prompts.** The three cloud Routines live outside the
  repo. Two are mirrored in `methods/`; **"Daily Brief" is not.** On 2026-09-03 a
  routine fired carrying a procedure that had gone stale two days earlier and
  reported success against an instruction set missing five of its seven steps.
  The fix already exists — the *pointer prompt* — and any Routine that touches
  this layer must use one.
