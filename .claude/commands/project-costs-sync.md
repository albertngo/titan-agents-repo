---
description: Daily payout-flow sync. Pulls Lightspeed sales + purchase orders (read only), snapshots Notion finance tables, plans cost / payment suggestions. plan_only until deliberately flipped.
---

# /project-costs-sync

Keep the Notion cost rows filled so the month-end `/payout-run` has nothing to type.
Daily, 09:00 Toronto — after Make 4280466 drops the morning's e-transfers into the
Payments Log at 08:00. Not part of `/daily-ingest`.

```
[0] preflight                                                       read only
[1] scripts/ls_sales_pull.py  -> ingest/<date>/ls-sales.json         read only
[2] scripts/ls_orders_pull.py -> ingest/<date>/ls-orders.json        read only
[2b] scripts/supplier_docs_pull.py -> ingest/<date>/supplier-docs.json  read only
[3] Notion snapshot via MCP   -> ingest/<date>/notion-finance.json   read only
[4] scripts/project_costs_sync.py -> plans/<date>/costs-plan.json    read only
[5] write_mode = write only: apply `write` actions, write suggestion fields   Notion write
[6] run ledger line; commit; push
```

Authoritative: `contracts/costs-plan-schema.md`, `contracts/ls-sales-schema.md`,
`contracts/ls-orders-schema.md`, `contracts/supplier-docs-schema.md`,
`platform-settings/supplier-docs.json`, `platform-settings/notion-finance.json`,
`platform-settings/payout-policy.json`, `methods/payouts.md`.

## 0. Before you start — stop on the first failure

1. `write_mode.project_costs_sync` in `payout-policy.json`. `plan_only` → steps 0–4
   and 6 only. Do not raise it; flipping is a dated vault decision.
2. Lightspeed credentials are in `.env` (`LIGHTSPEED_DOMAIN_PREFIX`,
   `LIGHTSPEED_PERSONAL_TOKEN` — see CLAUDE.md "Secrets"). Missing → report the name
   and stop.
3. Notion is reachable through the Notion MCP.
4. `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` are in `.env` and
   `pdftotext` is installed. Missing → skip step 2b, say so in the report, and run
   step 4 without `--supplier-docs` (flooring lines then stop at the PO stage).

## 1–2. Lightspeed — read only

```bash
python3 scripts/ls_sales_pull.py
python3 scripts/ls_orders_pull.py
```

Both are GET-only (`tests/test_lightspeed.py` fails if a write verb appears). The
sales pull walks the product catalogue once a day (cached under `analysis/cache/`).
Note the summary lines — `@pack without PP` is a staff-habit count for the report.

## 2b. Supplier documents — read only

```bash
python3 scripts/supplier_docs_pull.py
```

Reads the supplier's order confirmations, invoices and credit memos, and AP
Disposal's bin invoices, where staff file them in info@ (`platform-settings/supplier-docs.json`), app-only Graph GETs, nothing
moved or marked read. The invoice net of credits is the final flooring cost
(Decision 18). Report `errors` and `unattributed_credits` counts.

## 3. Notion snapshot — read only

Same procedure as `/payout-run` step 1, narrowed to what a day needs: unpaid cost
rows; Financials rows with `Costs Complete` unticked or commission unpaid; the
projects they reference plus every project with a PP-tagged sale in `ls-sales.json`;
the Payments Log rows with **no `Projects` relation** from the last 30 days, **with**
the `Message` column (the matcher reads it; nothing writes it out); and `Payout
Batches` rows marked `Paid` whose cost rows are not yet stamped (once that database
exists). Save as `ingest/<date>/notion-finance.json`.

## 4. Plan — read only

```bash
python3 scripts/project_costs_sync.py --snapshot ingest/<date>/notion-finance.json \
    --ls-sales ingest/<date>/ls-sales.json --ls-orders ingest/<date>/ls-orders.json \
    --supplier-docs ingest/<date>/supplier-docs.json
```

For disposal matching the snapshot's projects must carry `Street Address` and
`Assign Disposal`, and must include every project whose `Project End Date` is in the
last 120 days or empty (out-of-scope ones too: they stop a September invoice being
pinned on the wrong job), plus their Disposal cost rows. The street is read for
matching and never written out.

The snapshot must include the in-scope projects' **Flooring Line Items** (`Floor SKU`,
`Sqft Sold`, `Cost Rate`, `Sold At Rate`, `Quote Rate`, the four cost-rate columns,
`Cost Locked`, `Project`).

## 5. Apply — only when `write_mode.project_costs_sync` is `write`

For each action, in file order, skipping any `id` already `executed` in today's
`actions-log.json`:

- `mode: write` → `notion-update-page` on `target_url` with `fields`. Read the row
  first; if its `Cost source` is now a hand-entered value, **skip and log
  `refused`** (someone typed a number since the snapshot).
- `mode: suggest` → write only the suggestion fields in `fields`. Never `Cost`,
  never `Projects`.
- `flooring_line` → `op: create` is `notion-create-pages` in Flooring Line Items with
  `fields`; `op: update` is `notion-update-page` on the line. A `suggest` flooring
  action writes nothing to the line: it is listed in the report for the PM (rename to
  the ordered product, or a rate a person typed before the invoice arrived). The
  rate's tax basis (`notion-finance.json → flooring_line_items._tax_basis_open`) must
  be settled before the first write.
- A `to_add` property that does not exist yet → skip that field, note it once in the
  report.

Log every call per `contracts/actions-log-schema.md`: agent
`.claude/commands/project-costs-sync.md`, type `notion_update_page`,
`approved_by: "policy: project-costs-sync <mode>"`, `raw_ref_action_id` = action id.
Stop the batch on a Notion error (house rule for writers), log, report.

## 6. Report

Append `{"date", "project_costs_sync": "ok" | "error", "counts"}` to
`ingest/<date>/run-ledger.json` — `/payout-run` checks it on the 1st. Commit
`ingest/<date>/ls-*.json` as `project-costs-sync: <date>` and push. The snapshot,
`supplier-docs.json` and `costs-plan.json` are gitignored (private financials) — never commit them. In chat, only: suggestions waiting, `@pack`
sales without a PP number, flooring flags by kind (PM entry mistakes, POs not
received in Lightspeed, confirmed but not invoiced, quantity gaps), disposal invoices
unmatched or re-issued, notes.
