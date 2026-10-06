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
[3] Notion snapshot via MCP   -> ingest/<date>/notion-finance.json   read only
[4] scripts/project_costs_sync.py -> plans/<date>/costs-plan.json    read only
[5] write_mode = write only: apply `write` actions, write suggestion fields   Notion write
[6] run ledger line; commit; push
```

Authoritative: `contracts/costs-plan-schema.md`, `contracts/ls-sales-schema.md`,
`contracts/ls-orders-schema.md`, `platform-settings/notion-finance.json`,
`platform-settings/payout-policy.json`, `methods/payouts.md`.

## 0. Before you start — stop on the first failure

1. `write_mode.project_costs_sync` in `payout-policy.json`. `plan_only` → steps 0–4
   and 6 only. Do not raise it; flipping is a dated vault decision.
2. Lightspeed credentials are in `.env` (`LIGHTSPEED_DOMAIN_PREFIX`,
   `LIGHTSPEED_PERSONAL_TOKEN` — see CLAUDE.md "Secrets"). Missing → report the name
   and stop.
3. Notion is reachable through the Notion MCP.

## 1–2. Lightspeed — read only

```bash
python3 scripts/ls_sales_pull.py
python3 scripts/ls_orders_pull.py
```

Both are GET-only (`tests/test_lightspeed.py` fails if a write verb appears). The
sales pull walks the product catalogue once a day (cached under `analysis/cache/`).
Note the summary lines — `@pack without PP` is a staff-habit count for the report.

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
    --ls-sales ingest/<date>/ls-sales.json --ls-orders ingest/<date>/ls-orders.json
```

## 5. Apply — only when `write_mode.project_costs_sync` is `write`

For each action, in file order, skipping any `id` already `executed` in today's
`actions-log.json`:

- `mode: write` → `notion-update-page` on `target_url` with `fields`. Read the row
  first; if its `Cost source` is now a hand-entered value, **skip and log
  `refused`** (someone typed a number since the snapshot).
- `mode: suggest` → write only the suggestion fields in `fields`. Never `Cost`,
  never `Projects`.
- A `to_add` property that does not exist yet → skip that field, note it once in the
  report.

Log every call per `contracts/actions-log-schema.md`: agent
`.claude/commands/project-costs-sync.md`, type `notion_update_page`,
`approved_by: "policy: project-costs-sync <mode>"`, `raw_ref_action_id` = action id.
Stop the batch on a Notion error (house rule for writers), log, report.

## 6. Report

Append `{"date", "project_costs_sync": "ok" | "error", "counts"}` to
`ingest/<date>/run-ledger.json` — `/payout-run` checks it on the 1st. Commit
`ingest/<date>/ls-*.json`, the snapshot and the plan as
`project-costs-sync: <date>`, push. In chat, only: suggestions waiting, `@pack`
sales without a PP number, notes.
