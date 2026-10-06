---
description: Build the month-end payout run (contractor labor, disposal, commission) from a read-only Notion snapshot + Lightspeed. Proposes; Albert approves and pays. plan_only until deliberately flipped.
---

# /payout-run [`YYYY-MM`]

Build the month-end payout run: who gets paid what, what is held and why, what
blocks a payment. `YYYY-MM` is the month being paid (default: last month). Run on the
1st, after that day's `/project-costs-sync`.

```
[0] preflight: write_mode, Notion reachable, today's sync done          read only
[1] Notion snapshot via MCP -> ingest/<date>/notion-finance.json         read only
[2] (optional) outgoing Interac notices -> ingest/<date>/bank-notices.json read only
[3] scripts/payout_run.py -> plans/<date>/payout-run-<run>.{json,md}     read only
[4] write_mode = write only: Payout Batches rows + run summary page      Notion write
[5] PushNotification; commit; push
```

Authoritative files: `contracts/payout-run-schema.md` (input snapshot and output),
`platform-settings/notion-finance.json` (every id and property name),
`platform-settings/payout-policy.json` and `commissions.json` (every rule),
`methods/payouts.md` (why). Nothing below restates a value that lives there.

**This command never pays anyone and never marks anything paid.** Albert ticks
`Approved` on a batch, sends the money his way (Pay method on Titan Team), then ticks
`Paid` and types the reference. The next `/project-costs-sync` stamps the cost rows.

## 0. Before you start — stop on the first failure

1. Read `write_mode.payout_run` in `payout-policy.json`. `plan_only` → run steps 0–3
   and 5 only; write nothing to Notion. Do not raise it — flipping is a dated vault
   decision.
2. Notion is reachable: `notion-fetch` on `project_costs.data_source` returns a schema.
3. **Today's sync finished** (`cadence.sync_must_finish_first`): today's
   `ingest/<date>/ls-sales.json` exists. If not, run `/project-costs-sync` first.

## 1. Snapshot — read only

With `notion-query-data-sources` (SQL mode; one query at a time — parallel queries
429; 100-row cap, so page by date or id range until a query returns fewer than 100):

1. `project_costs`: every row where `Paid Out Date (2/3)` is empty AND
   `Paid Reference (3/3)` is empty; plus Category = Labor rows paid in the last 12
   months (the band).
2. `project_financials`: every row where `Commission Paid Out` is not checked OR
   `Commission Paid Date` is empty, from the last 12 months.
3. `titan_projects`, `qa_work_orders`, `master_payments_log`, `titan_team`: the rows
   referenced by (1) and (2) — projects by url, work orders and payments by project.

Select every column named in `notion-finance.json` for that table (live and
`to_add` — a missing column simply comes back absent). Save the raw rows, untouched,
under the table keys in `contracts/payout-run-schema.md` with `"contract":
"notion-finance-1"` and `taken_at`. Copy MCP output into the file; never retype rows.

**Personal data:** the snapshot carries names and addresses. It lives under `ingest/`
like every other ingest file, but nothing from the Payments Log `Message` column is
selected.

## 2. Bank notices — optional, read only

If `scripts/outlook_pull.py` can read albert@, collect this month's outgoing Interac
notices matching `bank_cross_check.subject_patterns` into
`ingest/<date>/bank-notices.json` as `{"notices": [{date, recipient, amount,
reference}]}`. Skip silently if unavailable — the cross-check is information only.

## 3. Build — read only

```bash
python3 scripts/payout_run.py --snapshot ingest/<date>/notion-finance.json --run <YYYY-MM> \
    --ls-sales ingest/<date>/ls-sales.json [--bank ingest/<date>/bank-notices.json]
```

Read the summary line and open the `.md`. Before anything else, sanity-check: every
`days_held` is plausible, no payee is a placeholder, totals are not zero.

## 4. Write the batches — only when `write_mode.payout_run` is `write`

One `Payout Batches` row per payee (data source in `notion-finance.json` →
`payout_batches`): Run, Payee, Lines (the cost rows), Commission lines, Total, Flags
(one line per flagged item), Bank cross-check, `Approved` and `Paid` unticked. Then
one private summary page "Payout Run — <run>" under Albert's Notion Directory with the
`.md` text. Relate each cost row's `Payout Batch`. Log each create as
`notion_create_page` in `ingest/<date>/actions-log.json` with `approved_by: "policy:
payout-run (proposal only, nothing paid)"`. Re-running the same run updates the open
batch rows instead of duplicating them; a batch Albert already marked `Paid` is never
touched.

## 5. Report

PushNotification: `Payout run <run>: <payees> payees, $<total>, <flagged> to review,
<held> held, <blockers> blockers`. Commit `plans/<date>/payout-run-*` and the
snapshot as `payout-run: <run> <date>`, push. In chat: the per-payee totals, then only
the flagged lines, held items and blockers — PARA where Albert must decide.
