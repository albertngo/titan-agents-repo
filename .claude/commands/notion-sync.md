---
description: Turn today's high-priority GHL findings into Notion tasks. Team-visible items auto-write; sensitive items are proposed for approval.
---

Sync today's ingest findings into Notion, per `contracts/notion-task-schema.md`.
Runs automatically as step 7 of `/daily-ingest` (wired in 2026-07-27), always
after `DAILY-BRIEF.md` is already written. Can also be run standalone against
any past date's `/ingest/<date>/` folder to catch up or re-check a day.

Read `platform-settings/notion-destinations.json` and
`contracts/notion-task-schema.md` in full before doing anything below —
they hold the ids, property names, and rules this command must not
re-derive or guess.

## Steps

1. **Resolve today's date** `YYYY-MM-DD` in America/Toronto. Read every
   `/ingest/<date>/<source>.json`. Skip any file that is missing or whose
   `status != "ok"` — log the skip, do not treat it as zero findings.

2. **Select candidates**, per `notion-task-schema.md`'s selection rule:
   `priority == "high"`, `type` in `{lead, message, drift}`, not a rollup,
   and a platform contact ID is derivable from the item.

   **Apply the Outlook mailbox exclusion FIRST**, before any other test: drop
   every `outlook` item whose `raw_ref` mailbox is not in
   `notion_task_eligible_mailboxes` (`platform-settings/outlook-ingest-sources.json`
   — currently `info@titanfloors.ca` only). Fail closed when the mailbox can't
   be read. This is a hard rule per `notion-task-schema.md`; it is not
   overridable by priority, sensitivity, or an approval in chat. Log each drop
   with its mailbox so the exclusion is auditable.

   For GHL specifically,
   derive the contact ID by parsing `item.link`, falling back to
   `extensions.ghl.conversations[].contact_id` for message items. Skip and
   log anything a contact ID can't be resolved for.

   Also resolve each GHL candidate's current pipeline **stage** for the
   `Name` bracket (`contracts/notion-task-schema.md`'s "Pipeline stage in
   `Name`" section): match the resolved contact ID against
   `extensions.ghl.opportunities[].contact_id` in the same file, take the
   `stage` field (trimmed), preferring an `open`-status, most-recently-updated
   entry if more than one matches. No match → `[no opportunity]`.

3. **Collapse to one candidate per contact.** Multiple items for the same
   contact in one run merge into a single task candidate (combine titles/
   summaries; keep the highest priority and all `basis` item ids). Carry
   forward `assigned_to` too: take the first non-null value among the merged
   items (see `notion-task-schema.md`'s Reference-only owner line section for
   why they should agree and what to do if they don't). Also collect `types`:
   the set of distinct `item.type` values among the merged items (see
   "Grouping by finding type" in that same contract).

4. **Route each candidate** using `notion-destinations.json`
   (`source_defaults`, then the item's own `sensitivity` field if set,
   escalation-only: `team → private`, never the reverse).

5. **Team destination (`write_policy: "auto"`)**:
   a. Query the Tactical Tasks List data source for open rows where `Tags`
      contains `"ghl"` and `Status` is not `Done`/`Dropped`.
   b. For each team-routed candidate, construct its `url`
      (`https://app.gohighlevel.com/v2/location/<ghl_location_id>/contacts/detail/<contactId>`
      — never copy `item.link` verbatim) and match by exact equality
      against the queried rows' `url`.
   c. No match → create, using the team property mapping table in
      `notion-task-schema.md`, including the `ghl_owner:` Notes line resolved
      from `notion-destinations.json`'s `people` table per that contract's
      Reference-only owner line section, `Tags` = `["ghl"]` plus each
      value in the candidate's `types`, and `Name` ending in the resolved
      `[<stage>]` bracket.
   d. Match found → update per the whitelist only (append a dated `Notes`
      line, raise `Priority` on escalation, add any `types` value not
      already in the row's `Tags` — never remove one, rewrite the `[<stage>]`
      bracket on `Name` if the resolved stage differs from what's currently
      bracketed). Never touch `Status`, `Assign To`, `Due Date`, the
      non-bracket portion of `Name`, or existing `Notes` text.
   e. If the dedupe query in (a) fails, stop before writing anything for
      this destination — do not create rows without it.
   f. If a single row create/update fails, log it and stop the rest of the
      team batch. Re-running later is safe — dedupe is query-based.
   g. Append one `contracts/actions-log-schema.md` entry per row
      (`type: "notion_create_task"` or `"notion_update_task"`), with
      `approved_by: "auto: notion-task-schema.md team routing, policy approved by Albert 2026-07-27"`.

6. **Private destination (`write_policy: "approval_required"`)**: never
   auto-write. List every private-routed candidate in chat — title,
   source, routing reason (source default vs. item-level `sensitivity`
   escalation), constructed url, summary. Ask Albert which to write. Only
   after an explicit yes, write the approved ones using the private
   property mapping table (dedupe query scoped to `Source` in
   `["bookkeeper","outlook","ghl-escalated","other"]`, matched the same way
   as the team destination), including the same `ghl_owner:` Notes line as
   the team destination when `assigned_to` resolves. Log with the real
   approval as `approved_by`, not the auto-write string.

7. **Report** in chat: a table of created / updated / skipped_duplicate /
   failed rows for the team destination, then the private proposal list
   and what was actually written after approval.

## Rules

- Never write anywhere except the two destinations named in
  `notion-destinations.json`.
- Never set `Assign To` / `Assignee` or `Due Date`. Assignment and due
  dates are Albert's calls, not the sync's. `ghl_owner:` in `Notes` is a
  reference line for whoever triages the board — it is informational only
  and must never be used to set `Assign To` or to route team vs. private.
- Never infer `sensitivity` from item content (keyword matching, etc.).
  Routing is a lookup against `notion-destinations.json` and the item's own
  declared field — never an inference this command makes on its own.
- Never rewrite or delete existing Notes text, and never touch a row's
  `Status` on update — those are human-owned once a row exists.
- A Notion connector failure must never touch `DAILY-BRIEF.md` — that file
  is already written before this command runs.
- If the connector is unavailable at all, write nothing, log one `failed`
  actions-log entry per destination attempted, and report the outage in
  chat. Do not fabricate task rows.
