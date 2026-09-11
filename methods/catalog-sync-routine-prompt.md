# Routine prompt — "Sync Approved Price Lists to Airtable and Lightspeed"

> **⚠️ Superseded 2026-09-11.** This is no longer the live routine text. Stage 2 of
> `methods/pricelist-pipeline-routine-prompt.md` replaced it, merging this routine
> and `pricelist-routine-prompt.md`'s into one identity that branches on whether the
> fire payload carries a `notionID` (absent = this stage). Kept here for its
> changelog, the batch-approval design, and rationale; `/catalog-sync`
> (`.claude/commands/catalog-sync.md`) is still the authoritative procedure Stage 2
> points to and is unaffected by the merge.

The canonical text for the catalogue-sync routine. Kept here so it is versioned and
diffable; the live copy is in the routine itself.

This is the **second** routine in the price-list pipeline, and it does not replace the
first. `methods/pricelist-routine-prompt.md` ("Process New Pricing Files from
OneDrive") is unchanged: it still fires on `{"notionID": "<page id>"}` from Make
4381438, still produces two CSVs, and still writes no platform. This routine picks up
the rows that one leaves owing.

| File | Role |
|---|---|
| `.claude/commands/catalog-sync.md` | the procedure — **authoritative** |
| `methods/catalog-sync-routine-prompt.md` | this file — the routine's stored prompt |
| `contracts/catalog-plan-schema.md` | the plan and the approval file |

---

## The routine is read-only. That is the whole design.

**It pulls, reconciles, produces a plan, and stops.** It never writes to Airtable or
Lightspeed, because `*-actions` agents are *never scheduled, never autonomous*
(`CLAUDE.md`, agent class rules) — they execute pre-approved ids and originate
nothing.

So the routine automates the expensive, error-prone half — walking a 14,611-product
catalogue, joining it on SKU, catching the identity collisions a person cannot see —
and hands Albert the one thing only he can supply: the yes.

**A run that produces a plan and notifies has succeeded.** It has not failed, stalled,
or been blocked. The writes are a separate, human-triggered step, run with
`/catalog-sync` in an interactive session.

This is the direct lesson of Grandeur, 2026-09-03: a backfill matched on colour alone,
gave 7 UUIDs to 16 rows, and Lightspeed rejected 9 products. Nothing about that was
caught by a human reading a CSV, and nothing about it would have been caught by
writing faster. It is caught by joining on SKU against the live catalogue and routing
every ambiguity to `blocked` — which is exactly what the unattended half now does,
every time, before anyone is asked to approve anything.

## Why a pointer, not a copy

The 2026-09-03 extraction failure: the live routine carried a procedure that had
stopped mid-code-block on 09-01, and two later decisions were written into the method
files but never copied into the routine. The run reported success against an
instruction set missing five of its seven steps.

A pointer cannot drift, because there is nothing in it to fall behind. Updating
`.claude/commands/catalog-sync.md` updates what the routine does, with no copy-paste
step between them.

---

## Pointer prompt — the live routine's stored text

```
**Title**
Sync Approved Price Lists to Airtable and Lightspeed

**Role & stance**
You run unattended. No human is watching, so verify before writing, and report
honestly rather than marking work complete that isn't. If you cannot complete a
step, say so plainly and say which step — never imply a stage ran that didn't.

**You are running the READ-ONLY half of this pipeline, steps 1-3 only.**
You produce a plan and you stop. You do NOT write to Airtable or Lightspeed, do NOT
create an approval file, and do NOT invoke lightspeed-actions-agent or
airtable-actions-agent. Absence of an approval file means nothing is approved. A run
that ends at the approval gate has SUCCEEDED — say so plainly, do not apologise for
it, and do not look for a way to finish the writes.

**Scope**
Find Price Lists rows where Airtable Sync is Pending and Extraction Status is
Extracted [Ready to Upload], with two CSVs in Extracted Files. Those are yours.
A row still at Extracted [Needs Review] has not been reviewed — skip it.
No cap on row count — steps 1-3 write nothing, so there is no blast radius to limit
by throttling the sweep. Process every eligible row, oldest first.

**Task**
For every eligible row, run /catalog-sync with that row's notionID, stopping at step
3. Do this for all of them before reporting — do not stop and notify after the first.

If the slash command does not resolve in this session, read
.claude/commands/catalog-sync.md from the titan-agents-repo checkout and follow
steps 1-3 exactly. That file is the authoritative procedure — do not improvise an
alternative, and do not work from memory of how price lists were handled before.

It covers: pulling the live Lightspeed catalogue read-only; taking a live Airtable
snapshot for the supplier; reconciling both against the two CSVs into one plan at
plans/YYYY-MM-DD/catalog-plan-<supplier>.json; and stopping.

**Pricing — assume, do not stop.** Take the price list's printed prices as the
COST. Retail price/unit = Cost/unit + $ 1.00. A column printed as MSRP,
suggested retail or suggested price goes to MAP price ($/sf) and never touches
Cost/unit. Apply these defaults and keep going; they are the rule, not a guess.

**Flag, do not stop, for anything the defaults do not cover** — more than one
candidate cost column, a number whose role is not printed, a grade or category
that maps to nothing, a supplier quirk with no recorded subsection.

Flag in three places: the plan, the Notion row's Review Reason multi-select, and
Notes. Take the Review Reason options from price_lists.status_values.review_reason
in platform-settings/pricelist-sources.json — never type one that is not listed, a
rejected option fails the whole update-page call. ADD to Review Reason; never
clear it, and never remove an option another run set. Notes carries the specifics
— which SKUs, which columns as printed, which value you took as cost.
Never invent a mapping to avoid flagging.

**A NEW supplier is always flagged.** Zero existing Airtable rows for that
supplier means every field on every row is unverified and nothing has been
reviewed against a live record. Set Review Reason to include New Supplier, and
say "NEW SUPPLIER — every detail needs a human check before upload" in the
notification, in those words, and say it first. A new supplier's row carries only
ONE CSV, so it falls outside your scope anyway (see Scope) — report it, do not
plan it.

If the Lightspeed host is unreachable or a credential is missing, report the exact
host or variable name and stop. Never route around a blocked host, never disable
TLS verification.

**Finish**
Commit and push every plan and Airtable snapshot produced this run to the repo.

Send **one** PushNotification covering the whole run, not one per row: total rows
processed, then per supplier — the action counts and the blocked count with reasons.
Say plainly that every plan awaits approval and that nothing has been written. This
digest is what a batch approval (see /catalog-sync step 3a) is given against — one
explicit reply, in a session where the digest is reviewed, can approve across every
plan in it. Stay silent only if there were no rows to process.
```

Four deliberate inclusions:

1. **The read-only fence, stated three ways.** An unattended agent that finds an
   approval gate will otherwise try to be helpful and get past it. "A run that ends at
   the approval gate has SUCCEEDED" is there to remove the incentive.
2. **The fallback file path** — a slash command may not resolve inside a scheduled
   fire, and this works either way.
3. **"Do not improvise an alternative"** — the 09-03 failure was not refusal. It was
   confident completion on a partial instruction set.
4. **A status filter, no row cap.** `Extracted [Needs Review]` means a human has not
   looked at the extraction yet; planning writes off unreviewed data inverts the
   pipeline's whole order. The row cap this section once described (three per run) is
   gone as of 2026-09-11 — see Changelog — because steps 1-3 never write, so a wider
   sweep costs nothing a narrower one didn't already risk.
5. **Batch approval, not batch writing.** The digest lets one reply clear every plan
   in a run; it does not let the run clear itself. See `/catalog-sync` step 3a.

## ⚠️ Scheduling status

**`Extracted [Ready to Upload]` was missing from the live `Extraction Status` property
from 2026-09-10 until sometime before 2026-09-11**, verified absent on 09-10 and
verified **restored** on 09-11 (live Notion MCP check, same day this file's batch
changes were made). While it was missing, the Scope filter above matched zero rows,
silently, forever — the failure mode this repo has already been bitten by twice.
Nothing in the repo removed it; the only schema statements run in that window were
`ADD COLUMN "Review Reason"` and `ALTER COLUMN` on the three select trackers, neither
of which touches `Extraction Status`. Most likely it was removed and restored in the
Notion UI. If it goes missing again: loosening the filter to `Airtable Sync is
Pending` alone is **not** the fix — that sweeps in rows nobody has reviewed, which
inverts the pipeline's whole order. Restore the option or name a replacement signal.

**Separately, still open as of 2026-09-11: `/catalog-sync` has not been run end to end
in a recorded, verified interactive session.** CLAUDE.md's pipeline section asks for
one such run before this routine is scheduled unattended. The batch-approval design in
this file and in `/catalog-sync` step 3a is written and ready, but has not itself been
exercised against a live approval yet. Run one interactively — ideally the first batch,
so the digest and batch-approval flow gets validated at the same time — before relying
on this routine on a schedule.

## Schedule

Daily is enough, and the pull caches per day. The rows this drains are created by the
extraction routine at whatever rate suppliers send price lists — a handful a month.
There is no value in a tighter interval, and each run walks the full catalogue.

## What this routine deliberately does not do

- **Write anything to Airtable or Lightspeed.** Steps 4–6 of the command are run by a
  person, in an interactive session, after reading the plan.
- **Create or edit an approval file.** Only a person does, on an explicit yes.
- **Unblock a blocked row.** Unblocking means fixing the underlying data and
  re-running the reconcile — never editing the plan.
- **Touch `LS Upload` or any Notion completion tracker.** Those record work that
  actually happened; this routine's work is a proposal.
- **Stop on a pricing question.** Superseded 2026-09-10 (Albert). The printed price
  is the cost, `Retail = Cost + $ 1.00`, MSRP → `MAP price ($/sf)`. The old rule
  blocked the whole run on a question; this one produces the work and flags it.
- **Silently absorb an ambiguity.** Anything the defaults do not cover is flagged
  with its SKUs — never resolved by inventing a mapping.

## Changelog

- **2026-09-11 (Albert)** — Batch approval. Albert wanted per-row approval sessions
  removed; the alternative landed instead keeps the human decision but batches it: the
  routine now sweeps every eligible row in one run (row cap removed — steps 1-3 never
  write, so nothing was gained by throttling them), reports one consolidated digest
  instead of a per-row notification, and `/catalog-sync` step 3a lets one explicit
  reply approve across every plan in that digest. Steps 4-6 are unchanged and still
  never run without an approval file naming exact ids. Same day, verified live that
  `Extracted [Ready to Upload]` is back on the Notion property (see Scheduling status)
  — the second scheduling blocker (no recorded interactive end-to-end run) is still
  open.
- **2026-09-10** — Created, alongside `.claude/commands/catalog-sync.md`, on the merge
  of the Airtable ↔ Lightspeed sync (PR #38). The pipeline's downstream half was five
  manual file operations before this; the API returns a product's UUID at create time,
  so the export → match → re-import round trip collapses into the same run that
  creates the product.
