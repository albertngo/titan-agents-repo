# Routine prompt — "Sync Approved Price Lists to Airtable and Lightspeed"

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
Process at most 3 rows per run, oldest first.

**Task**
Run /catalog-sync with that row's notionID, stopping at step 3.

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
that maps to nothing, a supplier quirk with no recorded subsection. Record each
one in the plan and in the notification, naming the SKUs. Never invent a mapping
to avoid flagging.

**A NEW supplier is always flagged.** Zero existing Airtable rows for that
supplier means every field on every row is unverified and nothing has been
reviewed against a live record. Say "NEW SUPPLIER — every detail needs a human
check before upload" in the notification, in those words, and say it first.
A new supplier's row carries only ONE CSV, so it falls outside your scope
anyway (see Scope) — report it, do not plan it.

If the Lightspeed host is unreachable or a credential is missing, report the exact
host or variable name and stop. Never route around a blocked host, never disable
TLS verification.

**Finish**
Commit and push the plan and the Airtable snapshot to the repo.

Send a PushNotification summarising, per row: the supplier, the action counts, and
the blocked count with reasons. Say plainly that the plan awaits approval and that
nothing has been written. Stay silent only if there were no rows to process.
```

Four deliberate inclusions:

1. **The read-only fence, stated three ways.** An unattended agent that finds an
   approval gate will otherwise try to be helpful and get past it. "A run that ends at
   the approval gate has SUCCEEDED" is there to remove the incentive.
2. **The fallback file path** — a slash command may not resolve inside a scheduled
   fire, and this works either way.
3. **"Do not improvise an alternative"** — the 09-03 failure was not refusal. It was
   confident completion on a partial instruction set.
4. **A row cap and a status filter.** `Extracted [Needs Review]` means a human has not
   looked at the extraction yet; planning writes off unreviewed data inverts the
   pipeline's whole order. Three rows keeps one bad run small.

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

- **2026-09-10** — Created, alongside `.claude/commands/catalog-sync.md`, on the merge
  of the Airtable ↔ Lightspeed sync (PR #38). The pipeline's downstream half was five
  manual file operations before this; the API returns a product's UUID at create time,
  so the export → match → re-import round trip collapses into the same run that
  creates the product.
