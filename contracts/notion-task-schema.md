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
  "types": ["drift"],
  "priority": "high",
  "url": "https://app.gohighlevel.com/v2/location/4BwjVRlyDCR4ZRdcSrFR/contacts/detail/4TzieXflcVqohecIkbEB",
  "thread_url": null,
  "amount_cents": null,
  "sensitivity": "team",
  "assigned_to": "rAMFCiXbAjJOEjtyyvmn",
  "basis": { "file": "ingest/2026-07-27/ghl.json", "item_ids": ["ghl-drift-abandonment_next-c1BQdU8s0TbdEKCX1ktb"] }
}
```

`assigned_to` is carried through unchanged from the source item(s) (`contracts/ingest-schema.md`)
— null when the source had none. See "Reference-only owner line" below for what the sync
does with it; it is never a routing input.

`types` is the set of distinct `item.type` values among everything merged into this
candidate (usually one; see "Collapse to one candidate per contact" for when it's more
than one). It maps to `Tags` — see "Grouping by finding type" below — never to routing
or to `Name`'s `<type>` placeholder, which stays whatever the merge logic already picks
for the title.

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

## Reference-only owner line (`ghl_owner`)

**Added 2026-08-09, Albert.** GHL exposes a raw `assignedTo` user ID on the
contact/opportunity behind most candidates (`contracts/ingest-schema.md`'s
`assigned_to` field, ~93–96% populated per a live sample). There is no MCP tool
that resolves it to a name, and there are only 5 users total on the account, so
resolution is a hand-maintained lookup: `platform-settings/notion-destinations.json`
`people[*].ghl_user_id`.

**This is a reference for whoever triages the board — it is never an
assignment.** It does not touch `Assign To`, does not affect routing (team vs.
private is `sensitivity`-driven only, per Routing above), and is not read by
the sync for any decision. The actions-class rule that assignment is always a
human call is unchanged; this just saves a lookup.

At **create** time only, add one line to the `Notes` footer, after the
`[agent] key=...` line (it is the last line of the footer):

- `assigned_to` resolves to a `people` entry → `ghl_owner: <name>` (the entry's
  `name` field, e.g. `ghl_owner: Pourya`).
- `assigned_to` is present but matches no entry in `people` → `ghl_owner:
  unmapped (<raw id>) — add to notion-destinations.json people table`. Don't
  drop it silently; an unmapped ID is a signal the roster changed.
- `assigned_to` is `null`/absent on every merged item → omit the line
  entirely. Do not write `ghl_owner: unassigned` — that would assert GHL has
  no owner when the truth may just be that this ingest run didn't carry the
  field (e.g. an older ingest file predating this feature).

For a collapsed candidate (multiple items, one contact), use the first
non-null `assigned_to` among the merged items — they should agree, since
assignment lives on the contact and is only mirrored onto opportunities; if
they disagree, that's itself worth a `needs_attention` note from the ingest
side, not something the sync silently picks a winner on.

**Not tracked on update.** The `ghl_owner` line is stamped once, at creation,
as part of the immutable footer. If GHL reassigns the contact later, the sync
does not detect or append an owner-change line in v1 — the update whitelist
(below) still only covers a dated finding line and a `Priority` raise. Revisit
if stale `ghl_owner` lines turn out to cause real confusion.

## Grouping by finding type (`lead` / `message` / `drift` tags)

**Added 2026-08-09, Albert** — wants to group/filter the board by what kind of
GHL finding a row is. `item.type` (`lead`, `message`, or `drift` — `pipeline`
is never a candidate, see above) is added to the existing multi-select `Tags`
property as its own value(s), rather than a new dedicated column: `lead`
(pink), `message` (blue), `drift` (purple) were added as `Tags` options
alongside the pre-existing `ghl` and the board's other unrelated tags
(`@order`, `training`, `price list`, etc.) — no new property, no schema
disruption for non-GHL rows.

- **On create**, `Tags` = `["ghl"]` plus one entry per value in the
  candidate's `types` (usually one; two when items of different types
  collapsed into the same contact, e.g. a `lead` and a `drift` finding on the
  same brand-new contact — both tags go on, the row is genuinely both things).
- **On update**, `Tags` **MAY gain** a type value the row doesn't already
  have, when the day's new finding introduces one (e.g. a row created from a
  `message` item gets a `drift` finding three weeks later — add `drift`,
  keep `message`). `Tags` **MUST NOT** lose a value on update — this is
  additive-only, same spirit as "MAY raise `Priority`, never lower it." The
  `ghl` tag itself is never removed; it's what the dedupe query in "Dedupe
  and update" keys on.
- This is classification, not routing or assignment — it never affects
  `sensitivity`-based routing, never sets `Assign To`, and grouping by it in
  a Notion view is a human choice, same as `ghl_owner` is a human's reference,
  not the sync's decision.

### The `projects` tag (post-sale conversations)

**Added 2026-09-02, Albert.** When the contact's conversation is about a job
we've already won rather than a sale we're chasing, add the **existing**
`projects` tag (lowercase — it is already an option on the board alongside
`ghl`/`lead`/`message`/`drift`; do not create a `Projects` variant). It goes on
in addition to the type tags, never instead of them, and follows the same
additive-only rule: never removed on update.

**Qualifying signal (GHL, ID-based)**: the contact has an opportunity whose
`status` is `won`, or whose stage is `2. *Project Won*` (projects) or
`6a. Closed - Won` (store material). This resolves off the same
`extensions.ghl.opportunities[]` lookup already used for the `[<stage>]`
bracket, so it costs nothing extra.

Applied to the five open won-stage rows on 2026-09-02, and the read was
strongly confirmed: every one turned out to be a post-sale service
conversation — final payment, trim-delivery timing, demo payment, a warranty
noise complaint, a warranty touch-up. None were sales chases. That's the
distinction the tag is for.

**Not yet wired: the Notion half.** Albert also wants a contact to qualify when
a Titan Projects row exists for them within roughly the last 2–3 months, even
absent a won GHL opportunity. That join does not exist today — Notion projects
carry no GHL contact ID, so matching would fall back to contact *name*, which is
exactly the failure mode this system keeps getting bitten by (the vault agent
flagged Silviya Jardany vs. Outlook's "Sylvia" on 2026-09-02 as an unresolvable
name match). Build an ID-based join before adding this half; do not ship
name-matching for it.

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

**Do not write a `thread:` conversation link into `Notes`** (removed 2026-09-02,
Albert). This used to be added for `message`-type items on the theory that it
gave a one-click path to the actual message. It doesn't: a
`/conversations/conversations/<id>` URL does not reliably deep-link in the GHL
UI — it drops you into the conversations inbox on whatever thread happens to be
selected, which reads as the row pointing at a completely unrelated customer.
Verified 2026-09-02: every conversation ID we were emitting resolved to the
**correct** contact via the API, so this was never a record-matching bug, purely
a bad URL form. The row's `url` property already lands on the contact record,
where the conversation is visible anyway. Don't reintroduce it.

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
- **MAY** add a `lead`/`message`/`drift` value to `Tags` if the new finding's
  type isn't already tagged (see "Grouping by finding type" above) — additive
  only, never remove an existing tag.
- **MAY** rewrite the trailing `[<stage>]` suffix on `Name` if the contact's
  current stage differs from what's bracketed (see "Pipeline stage in `Name`"
  below) — this is the one exception to Name being otherwise immutable on
  update; everything before the bracket is untouched.
- **MUST NOT** touch `Status`, `Assign To`, `Due Date`, the non-bracket
  portion of `Name`, or rewrite any existing `Notes` text.

Everything outside the whitelist is human-owned, mirroring the vault's
"append, don't rewrite" rule.

## Pipeline stage in `Name`

**Added 2026-09-02, Albert.** Every `Name` — team and private alike — ends with
the contact's current pipeline stage in square brackets: `<base name> [<stage>]`.
Day-count/staleness detail stays in `Notes` (already gets a fresh dated line every
run) rather than in `Name`, because a day-count goes stale the moment it's written
and `Name` isn't rewritten every run — only the bracket is, and only when the
stage itself has actually changed.

**Deriving the stage**: look up the candidate's already-resolved contact ID in
`extensions.ghl.opportunities[]` (matched on `contact_id`, never on the `contact`
display name — see the ghl-ingest-agent's identity-key rule for why name matching
is unreliable here). Use the matched entry's `stage` field, trimmed of any
trailing whitespace (stage names are emitted byte-exact including trailing spaces
per the ghl-ingest-agent's vault-linking convention; trim for display only, never
for matching). Prefer an `open`-status opportunity; if a contact has more than one,
take the most recently updated. **No opportunity found for the contact** → use the
literal bracket `[no opportunity]` rather than omitting it — the absence is itself
informative (this is Wanda/Karvin-Cheung-shaped: a categorization miss with no
opportunity yet).

**On create**: append `[<stage>]` when constructing `Name`, subject to the
existing ≤80-char cap — trim the base name (never the bracket) with a trailing
`…` if the combined string would exceed it.

**On update**: refresh the bracket only, in place, if the contact's current stage
differs from what's already bracketed. This is a live lookup against the same
`extensions.ghl.opportunities[]` source as create — not a network call to GHL —
so it depends on the ghl-ingest-agent actually emitting `contact_id` on every
opportunity record (see that agent's ID section). If the day's `ghl.json` doesn't
carry an opportunity for a contact that has one bracketed from a prior run, leave
the existing bracket as-is rather than guessing — a stale-but-plausible stage beats
a fabricated one.

## Property mapping (team destination)

Destination: shared "✅ Tactical Tasks List" (Titan Flooring HQ teamspace).

| Candidate field | Notion property | Value |
|---|---|---|
| `title` | `Name` | `GHL <type>: <Entity> — <short detail> [<stage>]`, ≤ 80 chars — see "Pipeline stage in `Name`" below |
| — | `Status` | `Not started` (create only) |
| — | `Tags` | `["ghl"]` plus one entry per distinct `type` among the candidate's merged items — `lead` / `message` / `drift` (create only; see below for the update behavior) |
| `priority` | `Priority` | `high` |
| `url` | `url` | constructed contact URL — see above |
| `summary` + footer | `Notes` | summary, blank line, then:<br>`[agent] key=<key> \| first_seen=<date> \| basis=<file>#<item_id>`<br>`ghl_owner: <name>` (create only, when `assigned_to` resolves — see "Reference-only owner line" above)<br>**No `thread:` line** — see "Constructing the Notion `url`" for why it was removed |
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
| `title` | `Task` | `<Source> <type>: <Entity> — <short detail> [<stage>]`, ≤ 80 chars — see "Pipeline stage in `Name`" below. For non-GHL sources (bookkeeper/outlook/meta-ads) there is no pipeline stage; omit the bracket entirely rather than writing `[no opportunity]`, which is GHL-specific phrasing |
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
