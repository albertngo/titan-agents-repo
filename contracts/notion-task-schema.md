# Notion Task Sync Contract — notion-task-1

Governs `.claude/commands/notion-sync.md`: how ingest items become rows in
Notion. Registry (database ids, property names, vocabulary) lives in
`platform-settings/notion-destinations.json`, not here — this file is the
rules, that file is the data.

This is a write mapping to an external platform, not an observation contract,
so it is its own file rather than an extension of `ingest-schema.md`.

## Task candidate

The intermediate shape between an ingest item and a Notion row:

```json
{
  "key": "ghl:contact:4TzieXflcVqohecIkbEB",
  "title": "GHL drift: Ryan Langen — one cycle from abandonment",
  "summary": "Score 12, mobile quote sent, already stale_lead-tagged, no appointment booked.",
  "entity": { "name": "Ryan Langen", "ghl_contact_id": "4TzieXflcVqohecIkbEB" },
  "priority": "high",
  "url": "https://app.gohighlevel.com/v2/location/4BwjVRlyDCR4ZRdcSrFR/contacts/detail/4TzieXflcVqohecIkbEB",
  "thread_url": null,
  "amount_cents": null,
  "sensitivity": "team",
  "basis": { "file": "ingest/2026-07-27/ghl.json", "item_ids": ["ghl-drift-abandonment_next-c1BQdU8s0TbdEKCX1ktb"] }
}
```

This shape is deliberately a strict subset of `contracts/plan-schema.md`'s
Action object (`entity`, `basis`, `rule_id` all line up). When planner-agent
un-parks, the sync's *input* changes from ingest items to `plan.json` actions;
everything below this point — dedupe, routing, selection, mapping — does not
change.

## Selecting candidates from an ingest file

```
priority == "high"
AND type ∈ {lead, message, drift}
AND type != "rollup" AND id does not contain "-rollup-"
AND a GHL contact ID is derivable (see below)
```

### Outlook: mailbox exclusion (hard rule, Albert 2026-08-02)

**A task is NEVER created from an Outlook item that did not arrive in
`info@titanfloors.ca`.** No exceptions — not at `priority: "high"`, not with an
approval, not to the private destination, not if a future edit adds Outlook
types to the selection rule above.

```
IF source == "outlook" AND mailbox != "info@titanfloors.ca"  ⇒  never a candidate
```

The mailbox is read from `raw_ref` (`outlook:<mailbox>:message:<id>`). **Fail
closed**: if `raw_ref` doesn't carry a mailbox, or carries one not in
`notion_task_eligible_mailboxes` in `platform-settings/outlook-ingest-sources.json`,
the item is excluded. Never fall back to parsing the summary or guessing from
the sender.

Why it's here and not left to `sensitivity`: `sensitivity: "private"` only forces
an approval prompt, and an approval can be given by mistake.

**The real reason is that staff mail has no correct destination yet.** Only two
destinations exist (the team board and Albert's private database), and a task
built from `pourya@`'s mail belongs in neither: the team board is wrong because
it's personal mail, and Albert's private database is wrong because it's *Pourya's*
task — filing it there both misattributes the work and drops Pourya's
correspondence into someone else's inbox. With no right answer available, the
only correct action is none. `info@` is the company inbox; mail sent there is
already addressed to the business, so it has a valid destination today.

This rule is about **provenance, not content** — the same principle as the vault
visibility rule. Widening it means editing this block, and the eligible-mailbox
list is data in the settings file, not a judgment the sync makes per item.

**Intended direction (Albert, 2026-08-03): per-staff private destinations.** Each
staff member gets their own private Notion database, and their mailbox's findings
route there — not to Albert's. That is a destinations change first
(`notion-destinations.json` gains one entry per staff member, each
`write_policy: "approval_required"` and owned by that person), and only then a
one-line widening of `notion_task_eligible_mailboxes`. Do not widen the mailbox
list before the destination exists — that is precisely the misfiling this rule
prevents.

No daily cap. `priority == "high"` is already the ingest agent's own
judgment call about what deserves attention today — a second, arbitrary
ceiling on top of it would defer real obligations for no defensible reason.
If an ingest run ever produces an implausibly large high-priority batch,
that is a signal to fix the ingest agent's priority judgment, not to
silently truncate the sync.

`type: "pipeline"` is excluded even at `priority: "high"` — a stage move is
news, not an obligation; nobody owes an action because of it.

`needs_attention[]` is **not** a candidate source. It is prose with no ids
or links — there is no dedupe key in it, so every entry would duplicate
daily. The entities it names are already covered as high-priority items.

Rollups are excluded by both `type` and an `id` substring check. Their ids
embed the run date (`ghl-drift-untagged_in_queue-rollup-2026-07-27`) and
`link` is null — a single miss creates one duplicate row per day forever.

### Deriving the GHL contact ID

Never parse from `item.id`, `item.raw_ref`, or the extensions' `ref` field —
these are conversation/opportunity IDs and are **not stable across days**
(see "Why item.id is not a dedupe key" below).

1. Parse `item.link` for `/contacts/detail/([A-Za-z0-9]{15,25})`. Covers
   `lead` and `drift` items.
2. Else parse `/conversations/conversations/([A-Za-z0-9]{15,25})` and look
   it up in `extensions.ghl.conversations[].contact_id` (match on
   `conversation_id`). Covers `message` items.
3. Neither resolves → **skip this item**, log it in the sync's report. Do
   not write a row with a missing/guessed contact ID.

Verified against `ingest/2026-07-27/ghl.json`: 10 high-priority items → 8
direct via (1), 2 via (2), 0 unresolvable.

### Why `item.id` is not a dedupe key

`contracts/ingest-schema.md` states item `id` is "stable across re-runs so
the funnel can dedupe." That is true within a single day's file and false
across days — confirmed against real data:

| Day | item id for the same person | contact ID in `link` |
|---|---|---|
| 2026-07-26 | `ghl-drift-meeting_no_followup-4TzieXflcVqohecIkbEB` | `4TzieXflcVqohecIkbEB` |
| 2026-07-27 | `ghl-drift-abandonment_next-c1BQdU8s0TbdEKCX1ktb` | `4TzieXflcVqohecIkbEB` |

Only 2 of 26/30 item ids overlapped between those two days; zero drift ids
overlapped. As a lead's drift type changes (e.g. `meeting_no_followup` →
`abandonment_next`), the id changes with it, and the id's embedded ref
switches between contact/opportunity/conversation IDs. The **contact ID
parsed from `link`** is the only value that stayed constant. Anything
built on `item.id` for cross-day dedupe will create a fresh duplicate row
every morning for every unresolved lead.

## Routing (team vs. private)

Two layers, evaluated in order:

1. **Source default** — `platform-settings/notion-destinations.json`
   `source_defaults`. A new `*-ingest` source needs one line there; the
   sync's logic never changes.
2. **Per-item override** — an optional `sensitivity: "team" | "private"`
   field on the ingest Item, set by the *ingest* agent, which is the only
   component with full context to judge it (e.g. a GHL item that is a
   liability/complaint rather than a sales matter).

**Escalation-only: `team → private` is allowed; `private → team` is not.**
A missing or wrong `sensitivity` value then fails safe — worst case a
routine item lands in the private queue for Albert to re-route, never a
sensitive finding landing in the shared team database.

Routing is a table lookup, never inferred from item content (no keyword
matching on the summary). Content-based inference is unauditable and is the
sync originating a decision, which the actions-class rules forbid.

`write_policy` per destination (from `notion-destinations.json`) governs
execution: `"auto"` writes immediately; `"approval_required"` always
proposes-and-stops for Albert's explicit yes, regardless of anything else in
this file.

## Constructing the Notion `url` property

**Always constructed, never copied from `item.link`:**

```
https://app.gohighlevel.com/v2/location/<ghl_location_id>/contacts/detail/<contactId>
```

using `ghl_location_id` from `notion-destinations.json` and the contact ID
derived above. This matters for three reasons:

- **Uniformity** — `message` items link to `/conversations/conversations/…`;
  copying `item.link` verbatim would give some rows a contact URL and others
  a conversation URL. Every row lands on the contact record.
- **Exact-match dedupe** — because `url` is a deterministic function of the
  contact ID, matching an existing open row is a plain equality check on the
  `url` property. No substring search, no extra schema property needed on
  the shared database.
- **Precedent** — mirrors the existing Lightspeed automation pattern already
  in Tactical Tasks List, where `url` holds the canonical deep link.

For `message`-type items, the conversation thread link is not lost — it goes
into `Notes` as `thread: <conversation_url>`, so the row still gives a
one-click path to the actual message.

## Dedupe and update

**One open row per GHL contact.** Different drift findings for the same
person (e.g. `meeting_no_followup` today, `abandonment_next` tomorrow) are
one human obligation, not two rows. Two ingest items for the same contact
within a single run (e.g. a `lead` and a `message` for the same new caller)
also collapse to one row.

At the start of every sync run, query the destination data source for open
rows the sync itself manages, then match by exact `url` equality against
each candidate's constructed URL. "Managed by the sync" is filtered
per-destination, since the two destinations don't share a schema:
- **team**: `Tags` contains `"ghl"` AND `Status` not in `closed_statuses`
- **private**: `Source` is one of `["bookkeeper", "outlook", "ghl-escalated", "other"]`
  AND `Status` not in `closed_statuses` — this scopes the query to
  agent-created rows only, so Albert's own hand-entered personal to-dos
  (which leave `Source` empty) are never touched or matched against.

- **No match found** → create.
- **Match found** → update per the whitelist below.

Dedupe state lives in Notion itself, not a local file in this repo. Notion
is where the true state is — Albert marking a row Done must be visible to
the very next run, and a repo-side ledger would diverge the first time that
happens. It also makes the sync self-healing: a run that fails after
writing 3 of 8 rows leaves 3 correct rows; the next run's query sees the
other 5 missing and creates them. No separate repair path is needed.

### Update whitelist

On a match, the sync:

- **MAY** append one dated line to `Notes`.
- **MAY** raise `Priority` if the new finding is more severe than the
  existing value.
- **MUST NOT** touch `Status`, `Assign To`, `Due Date`, `Name`, or rewrite
  any existing `Notes` text.

Everything outside the whitelist is human-owned, mirroring the vault's
"append, don't rewrite" rule.

## Property mapping (team destination)

Destination: shared "✅ Tactical Tasks List" (Titan Flooring HQ teamspace).

| Candidate field | Notion property | Value |
|---|---|---|
| `title` | `Name` | `GHL <type>: <Entity> — <short detail>`, ≤ 80 chars |
| — | `Status` | `Not started` (create only) |
| — | `Tags` | `["ghl"]` |
| `priority` | `Priority` | `high` |
| `url` | `url` | constructed contact URL — see above |
| `summary` + footer | `Notes` | summary, blank line, then:<br>`[agent] key=<key> \| first_seen=<date> \| basis=<file>#<item_id>`<br>`thread: <conversation_url>` (message items only) |
| — | `Verification` | `Needs Verification` (create only) |
| — | `Assign To` | **always empty** |
| — | `Due Date` | **always empty** |

`Assign To` and `Due Date` are never set by the sync. Assignment is a
decision the actions-class rules reserve for a human; a due date is a
commitment, not an observation. Leaving `Assign To` blank also means every
created row appears only in the "All Tasks" / "Agent Inbox" views — none of
the per-person filtered views — so nothing lands unvetted in a teammate's
daily list.

## Property mapping (private destination)

Destination: Albert's existing personal "to-do" database (under "to-do list
(personal)", Albert's Notion Directory → PERSONAL), filtered by its
existing "Private To Do" view. This is **not** a separate new database —
`Notes`, `url`, and `Source` were added to it 2026-07-27 specifically to
support this mapping; `Task`, `Status`, `tags`, `Priority`, `Assignee`,
`Due Date` already existed for Albert's own to-dos and are unchanged in
meaning.

| Candidate field | Notion property | Value |
|---|---|---|
| `title` | `Task` | `<Source> <type>: <Entity> — <short detail>`, ≤ 80 chars |
| — | `Status` | `Not started` (create only) |
| source | `Source` | `bookkeeper` / `outlook` / `ghl-escalated` / `other` |
| — | `tags` | add `"GHL"` only when `Source == "ghl-escalated"`; otherwise untouched |
| `priority` | `Priority` | `high` |
| `url` | `url` | constructed deep link (contact URL for GHL-sourced items; platform-specific for others) |
| `summary` + footer | `Notes` | same footer convention as the team mapping |
| — | `Assignee` | **always empty** — this is Albert's private queue, but the sync still never assigns; leaving it blank keeps the "Private To Do" view's own `Assignee = Albert` filter meaningful as a manual triage signal, not an automated one |
| — | `Due Date` | **always empty** |

Every write to this destination goes through the propose-and-stop flow
(`write_policy: "approval_required"` in `notion-destinations.json`) —
never auto-write, regardless of source.

## Failure policy

The sync runs manually, after `/daily-ingest` has already written
`DAILY-BRIEF.md` — Notion failures can never affect the brief.

| Failure | Behavior |
|---|---|
| Notion connector unavailable / auth failure | Write nothing. One `actions-log.json` entry, `result: "failed"`. Report in chat. |
| Dedupe query fails | Stop before any writes. Creating rows without a successful dedupe query is the one path that produces duplicates. |
| A single row create/update fails | Log `result: "failed"` for that row, stop the rest of the batch (matches the actions-class failure mode in `CLAUDE.md`). Re-running is safe and free under query-based dedupe. |
| Ingest file missing, or `status != "ok"` | Emit nothing for that source, log a skip. |

## Audit trail

Reuses `contracts/actions-log-schema.md` unchanged — a Notion write is an
action, and that schema already fits: `result` includes `skipped_duplicate`,
which is exactly the dedupe-match outcome. New `type` values for this
contract: `notion_create_task`, `notion_update_task`.

For auto-written rows, `approved_by` records that the *policy* was
approved, not the individual row:
`"auto: notion-task-schema.md team routing, policy approved by Albert <date>"`.
For approval-gated (private) rows, `approved_by` records the actual
in-chat approval.
