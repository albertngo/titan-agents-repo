# Routine prompt — "Titan Price List Pipeline" (merged, then collapsed to one flow)

**Decided 2026-09-11 (Albert, in chat, after the first real run of the "two trigger
shapes" version hit a hard blocker — see Still open).** Extraction and sync no longer
wait on separate triggers. Every fire carries a `notionID`; one session runs both
stages on that one row, back to back, and a clean established-supplier action clears
its own approval gate instead of waiting for Albert to review it.

| Payload | Runs |
|---|---|
| `{"notionID": "<page id>"}` | `/process-price-list <notionID>`, then immediately `/catalog-sync <notionID>` — same session |
| `{}` / no `notionID` | Nothing wired up yet — see "Backstop sweep, not wired up" below |

Both stages still point at their command files, not a copy of their procedures —
same pointer rationale as always (2026-09-03: a routine that carries a copy of a
procedure can fall behind it silently; a pointer cannot). `.claude/commands/process-price-list.md`
and `.claude/commands/catalog-sync.md` are the authoritative procedures for their
stage; `contracts/catalog-plan-schema.md` is authoritative for the auto-approval
rubric. Change any of those there, not here.

**What this changes from the previous (2026-09-11 morning) version of this file:**
extraction no longer stops and waits for Albert to set `Extracted [Ready to
Upload]` before sync runs — sync runs immediately, same session, on whatever
extraction just produced. And sync no longer stops unconditionally at its approval
gate — an established supplier's clean, unflagged, non-blocked actions write
themselves through in that same session; only a New Supplier plan, a `blocked`
entry, or a row still carrying an unresolved `Review Reason` waits for Albert.

**What this still does not change:** a New Supplier plan (zero prior Airtable rows
for that company) never auto-approves, any row at all — 2a's reasoning holds exactly
as before. `blocked` entries never get an id, ever, by policy or by a person.
`*-actions` agents still execute only an id that appears `approved` in the approval
file — nothing about that check changed, only that `/catalog-sync` itself may now
write that file for the narrow slice the rubric covers. Neither Lightspeed nor
Airtable has a delete/deactivate action type, and this change adds no path to one.

---

## Pointer prompt — the live routine's stored text

```
**Title**
Titan Price List Pipeline — Extract and Sync

**Role & stance**
You run unattended. No human is watching, so verify before writing, and report
honestly rather than marking work complete that isn't. If you cannot complete a
step, say so plainly and say which step — never imply a stage ran that didn't, and
never imply policy approved something it didn't actually clear.

**This routine requires a notionID.** The fire payload is {"notionID": "<page id>"}.
If it carries no notionID, stop and report that — there is no sweep wired up yet to
fall back to (see the repo file's "Backstop sweep, not wired up"). Never guess a
notionID, never invent one, never proceed without it.

---

Step 1 — Extract

Fetch the Price Lists row named by notionID. If Extraction Status is already past
"Not started" (Needs Review, Error, Ready to Upload, All Uploaded, or Not Needed),
this row has already been through extraction — do nothing, report that, and stop.
Do not re-extract it.

Otherwise, run /process-price-list with that notionID. If the slash command does
not resolve in this session, read .claude/commands/process-price-list.md from the
titan-agents-repo checkout and follow it exactly, start to finish — it is the
authoritative procedure. Do not improvise, and do not work from memory of how price
lists were handled before.

It downloads the PDF, assigns Company and Tags, extracts against the live Airtable
catalogue, produces the Airtable and Lightspeed upload CSVs, commits them to
ingest/YYYY-MM-DD/ in the same step (load-bearing now — step 2 reads them from the
repo, never from Notion), attaches them to the row, and sets Extraction Status to
Extracted [Needs Review] (or Extracted [Error] on failure). Follow that command's
pricing, tagging, and Review Reason rules exactly as written there. Do not restate
them here, do not apply a remembered version of them, and if this file and that
command ever seem to disagree, the command wins, always.

If step 1 ends in Extracted [Error], or produced no CSVs (the documented "not a
price list at all, no content" exception), stop here — there is nothing for step 2
to sync. Report and, if anything needs Albert, notify.

---

Step 2 — Sync, immediately, same session

Run /catalog-sync with the same notionID, all the way through — steps 1-6, not just
1-3. If the slash command does not resolve in this session, read
.claude/commands/catalog-sync.md from the titan-agents-repo checkout and follow it
exactly, start to finish — it is the authoritative procedure, including its pricing
defaults (step 2), its flagging rules (step 2a, which also covers a new supplier),
and its policy auto-approval rubric (step 3, pointing at
contracts/catalog-plan-schema.md). Do not restate any of those rules here and do not
apply a remembered version of them — if this file and that command ever seem to
disagree, the command wins, always.

Read the two CSVs from where step 1 just committed them in this repo. Do not attempt
to download them from the Notion row's Extracted Files property — that path does not
work across a session boundary (confirmed 2026-09-11: the only available download
tool serves files this session's own integration uploaded, and these were not), and
inside one session you already have them on disk from step 1 regardless.

Apply the auto-approval rubric exactly as contracts/catalog-plan-schema.md states it:

- Plan's Review Reason includes New Supplier → nothing on this plan auto-approves.
  Report the plan, stop, same as the gate always has.
- Otherwise, an action auto-approves if it is not blocked and its sku carries no
  Review Reason this run added or left uncleared. Write those ids into the approval
  file yourself, execute steps 4-6 for them in this same session, and set every
  resulting actions-log approved_by to
  "policy: high-confidence auto-approval (2026-09-11 routine)" — never a person's
  name.
- Everything else — blocked entries, flagged rows, the whole of any New Supplier
  plan — gets no id from you. Report it exactly as the gate always has: summary
  counts, every blocked reason, before/after on price moves. That is this run's
  successful, complete outcome for those rows, not a stall — a person approves them
  later, the same way they always could.

Set the Notion trackers to match what actually happened: Partial where some of a
supplier's actions wrote and others are still waiting on a person, the completion
values where nothing is left outstanding. Leave Extraction Status at
Extracted [Needs Review] rather than advancing it while anything on the plan is
still waiting on a person.

If the Lightspeed host is unreachable or a credential is missing, follow that
command's "Before you start" section: report the exact host or variable name and
stop. Never route around a blocked host, never disable TLS verification, never
treat a cloud/session env var as satisfying that check in place of .env.

---

Report and notify

Report honestly, one run covering both steps: what extraction produced, what policy
auto-approved and actually wrote (by supplier, with action counts), and what is
still sitting at the gate waiting on Albert (by supplier, with blocked/flagged
reasons). Never describe a policy-cleared write as if a person reviewed it, and
never describe a gate-held row as if it were written.

Send a PushNotification whenever this run needs Albert: anything still at the gate,
anything escalated, any step that could not complete, or new products created that
still need attention (a Lightspeed ID backfill, for instance, though the sync step
mostly closes that loop itself now). Stay silent only if the run completed cleanly —
extraction produced files, sync ran, everything on the plan either wrote
successfully by policy or there was nothing left to hold back.
```

Six deliberate inclusions:

1. **The routine no longer branches.** One shape, one flow, keyed on the notionID
   every fire is expected to carry. There is no payload-shape decision left to get
   wrong.
2. **The fallback file path, for both stages** — a slash command may not resolve
   inside a scheduled fire, and this works either way.
3. **"Do not improvise an alternative"** — carried over from every predecessor
   routine; the 2026-09-03 extraction failure was confident completion on a partial
   instruction set, not refusal.
4. **Step 2 reads the repo, never Notion, for the CSVs.** This is the direct fix for
   the 2026-09-11 failed run below — the mirroring step 1 already did (per
   `process-price-list.md`) is now load-bearing, not incidental.
5. **The auto-approval rubric is quoted only by reference, never restated as
   business logic** — same reasoning as the pricing/tagging/flagging pointers below
   it. `contracts/catalog-plan-schema.md` is where "what counts as high confidence"
   is allowed to live; a second copy here is exactly the drift risk the whole
   pointer-not-copy design exists to prevent.
6. **No business rules restated in-line** — pricing, tagging, flagging, Review
   Reason, the new-supplier check, the blocked-host message, the auto-approval
   rubric. Every one of those lives only in `/process-price-list`, `/catalog-sync`,
   or `catalog-plan-schema.md`, and this file points at them instead of quoting them.

## Backstop sweep, not wired up

A periodic no-`notionID` fire could, in principle, sweep for rows where `Airtable
Sync` is still `Pending` or `Partial` well after their own extraction fire should
have carried them through sync — an interrupted run, a Lightspeed outage mid-session,
anything that left a row short of where step 2 above should have taken it. Nothing
currently fires that payload shape, and nothing in this file handles it yet. Add it
only once a row is actually observed stuck in that state — not preemptively, and not
by resurrecting the old always-on sweep, which existed to discover *unreviewed* rows
a person hadn't gotten to yet, a problem this merged flow no longer has.

## Wiring this outside the repo

This file only controls what the routine *does* once it fires. What fires it — Make
4381438's webhook — has to actually post a `notionID` on every fire for the table
above to hold; confirm that at the trigger side, not in this repo.

## Still open

**The first real run under the two-trigger-shape version of this routine (2026-09-11,
this session) did not complete.** It found two eligible rows (HOMESPRO, IMPRESSIVE)
correctly, but could not retrieve either row's CSVs — they were native Notion
attachments from a prior session's extraction, and the only download tool available
serves files this session's own integration uploaded, not files a different session
attached. No plan was produced, nothing was written, and the run reported the
blocker rather than guessing. That failure is exactly why extraction now commits its
CSVs to the repo as a load-bearing step and sync now reads them from there instead of
from Notion (see above) — it should not recur under this version.

**The auto-approval path itself has never run, at all, on a real plan.** Everything
in this file about it is design, not a verified behavior. The first real run under it
should be watched closely — read what it actually auto-approved and wrote, not just
whether it reported success — before trusting it to run fully unattended on a
schedule.

**HOMESPRO and IMPRESSIVE are still stuck.** Their CSVs exist only as Notion
attachments this session cannot read and were never committed to the repo (they
predate this fix, or were never produced by an actual repo-tracked run). Re-running
`/process-price-list` on both notionIDs would regenerate and properly commit them,
but that discards whatever review already put them at `Extracted [Ready to Upload]`
— get Albert's confirmation before doing that rather than assuming it.

## Relationship to the predecessor files

`methods/pricelist-routine-prompt.md` and `methods/catalog-sync-routine-prompt.md`
are no longer the live routine text — this file is, and has been since the first
2026-09-11 merge. They're kept for their changelogs and rationale (the 2026-09-03
pointer-not-copy lesson, the 2026-09-10 missing-status-option incident, the
2026-09-11 batch-approval decision) and because `/process-price-list` and
`/catalog-sync` — the commands each step still points to — are documented there in
full. Change a step's procedure in its command file, as always; change this file
only when the flow itself or the stored text needs to change.

## Changelog

- **2026-09-11 (Albert, in chat).** Collapsed the two-trigger-shape version below
  back into one always-notionID flow, and removed the human pause between extraction
  and sync for actions that clear the new auto-approval rubric
  (`contracts/catalog-plan-schema.md`, "Policy auto-approval"). Reason: the
  two-trigger-shape version's first real attempt (same day, this session) never got
  past a tooling blocker retrieving cross-session Notion attachments, which prompted
  fixing the CSV hand-off (commit in extraction, read from the repo in sync) at the
  same time as this policy change. New Supplier plans, `blocked` entries, and any
  row carrying an unresolved Review Reason are unaffected — those still wait for
  Albert exactly as before.
- **2026-09-11 (Albert)** — Removed the inlined pricing default, the Review Reason /
  new-supplier reporting language, and the blocked-host message from both stages'
  stored text; each is now a pointer to the command section that already states it.
  Albert's objection: a business rule quoted into the prompt is a second copy of
  something the repo already states once, and a second copy is exactly what this
  file's own pointer-not-copy design is supposed to prevent — it can drift out from
  under the command file it's supposed to mirror without anything catching it.
- **2026-09-11 (Albert)** — Created. Merges the two prior routines into one,
  branching on the fire payload's shape rather than maintaining two stored prompts
  that were always going to be triggered in lockstep with each other's outputs.
