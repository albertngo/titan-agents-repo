# Finance Period Contract — finance-period-1

`/finance-close` writes exactly one file per accounting period:

```
finance/periods/YYYY-MM.json
```

Re-runs over the same period **overwrite** it. The file is rebuilt from source
every time and is never accumulated by adding a delta to a previous balance — one
missed ingest day would otherwise corrupt every period after it, silently.

Method: `methods/finance-reconciliation.md`. Ids, mappings and thresholds:
`platform-settings/finance.json`.

## What this contract is, and what it defers to

This is the **period-state** counterpart to `contracts/ingest-schema.md`, which
is a 24-hour delta contract. A balance is a position, not a sum of events, so it
needs its own artifact — see the method doc's "grain problem".

It **cites rather than redefines**. Where this file and one it cites disagree,
the cited file wins:

| For | Read |
|---|---|
| The Action object, in full | `contracts/plan-schema.md` § Action |
| The approval file's shape and rules | `contracts/catalog-plan-schema.md` § approval |
| Daily item shape, `sensitivity`, `priority` | `contracts/ingest-schema.md` |
| Every write that actually executes | `contracts/actions-log-schema.md` |
| The reconciliation identity and variance types | `methods/finance-reconciliation.md` |

## Sensitivity — the whole file is admin

Every period file draws on QBO and Notion Project Financials, both admin-only
surfaces. **The file as a whole is `private` provenance.** There is no per-item
sensitivity field here and there must not be one: a mixed file would invite a
partial staff render, and `platform-settings/requesters.json` already says a
`private` item is never returned to a `staff`-tier requester.

A staff-facing finance view, if ever built, is a separate artifact computed from
team-provenance sources — never this file with sections deleted.

## Money

Integer **cents, CAD**, everywhere, per `CLAUDE.md` conventions. **No float
arithmetic anywhere in the pipeline** — not in intermediate sums, not in the
coverage ratio's numerator or denominator. `coverage.ratio` is the single
exception and is a rounded display value, never an input to anything.

## Envelope

```json
{
  "contract_version": "finance-period-1",
  "period": "2026-08",
  "fiscal_year": "FY2026",
  "fiscal_quarter": "FY2026-Q4",
  "calendar_quarter": "2026-Q3",
  "status": "provisional",
  "built_at": "2026-09-11T09:00:00-04:00",
  "error": null,
  "inputs": [],
  "company": {},
  "business_lines": {},
  "cash": {},
  "opex": {},
  "reconciliation": {},
  "projects": [],
  "proposed_entries": [],
  "needs_attention": []
}
```

| Field | Rules |
|---|---|
| `contract_version` | Always `"finance-period-1"`. A breaking change is a new version with a migration note here; consumers tolerate n and n-1. |
| `period` | `YYYY-MM`. The atom. Quarters are derived, never stored as their own file. |
| `fiscal_year` | `FY<YYYY>`, where the year is the one the period's **September 30 year end falls in**. August 2026 is in FY2026; October 2026 is in FY2027. |
| `fiscal_quarter` | `FY<YYYY>-Q<n>`. Q1 = Oct–Dec, Q2 = Jan–Mar, Q3 = Apr–Jun, Q4 = Jul–Sep. |
| `calendar_quarter` | `<YYYY>-Q<n>`, ordinary calendar quarters. Carried so a renderer can offer the calendar view without recomputing it. |
| `status` | `open` \| `provisional` \| `closed` \| `error`. See below. |
| `built_at` | ISO timestamp, America/Toronto offset. |
| `error` | Human-readable string when `status` is `error`, else null. |
| `inputs` | `{ file, run_at }` per source file actually read. **Non-empty figures with empty `inputs` is invalid** — a number with no readable input is a fabrication. Same rule as `dept-plan-schema.md`. |
| `needs_attention` | Array of strings. Same semantics as ingest. Every `unexplained` variance and every `on_account_edit_drift` produces one. |

### `status`

| Value | Meaning |
|---|---|
| `open` | The period has not ended. Figures are running totals and will change. |
| `provisional` | The period has ended and reconciled, but has not been tied to QBO's own P&L. **This is the normal resting state.** |
| `closed` | Tied to QBO's P&L for the same range and bank-reconciled. Only a human sets this. |
| `error` | Inputs missing or unreadable. All figure blocks are `null` — never zero. |

**A figure block is `null` when unknown, never `0`.** Zero is a measurement;
absence is not. The greyed "bookkeeper offline" tile exists in
`/exec-dashboard` precisely because a zero there would have read as "no money
moved" for sixteen consecutive days.

## `company`

Company-level totals. The only place a net profit figure exists.

```json
"company": {
  "revenue_cents": 48211900,
  "cogs_cents": 31337700,
  "gross_margin_cents": 16874200,
  "opex_cents": 9120400,
  "net_profit_cents": 7753800
}
```

Computed from company-level revenue and cost — **never by summing or averaging
the business lines' margins.**

## `business_lines`

```json
"business_lines": {
  "project": {
    "revenue_cents": 28400000, "cost_cents": 19880000,
    "gross_margin_cents": 8520000, "gross_margin_pct": 30.0,
    "basis": "notion:project_financials", "project_count": 11
  },
  "store": {
    "revenue_cents": 19811900, "cost_cents": 11457700,
    "gross_margin_cents": 8354200, "gross_margin_pct": 42.2,
    "basis": "lightspeed:sales", "excluded_project_sales": 14
  },
  "other": { "...": "..." }
}
```

| Rule | |
|---|---|
| `basis` | **Required.** Names the authority the figures came from. Two lines computed from different systems must not look alike on a dashboard without saying so — the same move `dept-plan-schema.md` makes with `rank_basis`. |
| `excluded_project_sales` | On `store` only. Count of LS sales removed by the Poreus exclusion rule. **A sudden drop to 0 means the rule stopped matching**, not that project work stopped — surface it. |
| Never summed | Lines are rendered side by side. `company` is computed independently, not from these. |
| No opex | Operating expenses are **not** allocated to lines. See the method doc's refusal. A line therefore has a gross margin and no net profit, deliberately. |

## `cash`

```json
"cash": {
  "bank_balance_cents": 21400500, "bank_balance_as_of": "2026-08-31",
  "ar_lightspeed_cents": 3420000,
  "ar_qbo_cents": 2890000,
  "ar_variance_cents": 530000,
  "layaway_liability_cents": 1265000,
  "ap_cents": 4110000
}
```

`ar_lightspeed_cents` is authoritative — see Gap B in the method doc.
`ar_qbo_cents` is the mirror, carried so the drift is visible rather than
resolved. **Never average them, never publish one as "AR" unqualified.**

`layaway_liability_cents` exists in no platform. It is computed from open LS
layaways and is the clearest single reason this contract has to exist.

## `opex`

```json
"opex": {
  "total_cents": 9120400,
  "by_category": { "Rent": 850000, "Vehicle": 412300 },
  "uncategorized_cents": 88200,
  "uncategorized_count": 7,
  "basis": "qbo"
}
```

`uncategorized_*` is a data-quality signal, not a category. It is the number that
says how much the opex total can be trusted, and it belongs in
`needs_attention` above a threshold set in `platform-settings/finance.json`.

## `reconciliation`

```json
"reconciliation": {
  "closeouts": [
    {
      "date": "2026-08-14", "register_id": "…",
      "ls_total_cents": 1842300, "qbo_total_cents": 1791300,
      "explained_cents": 51000, "residual_cents": 0,
      "variance_ids": ["fv-2026-08-14-a1b2"]
    }
  ],
  "variances": [],
  "coverage": {}
}
```

A closeout whose `residual_cents` is non-zero produces an `unexplained` variance
of that amount. `explained_cents + residual_cents` must equal
`ls_total_cents − qbo_total_cents` exactly — the identity in the method doc,
asserted rather than assumed. **A closeout where it does not balance is a bug in
the pipeline, not a finding about the business**, and must raise, not report.

### Variance

```json
{
  "id": "fv-2026-08-14-a1b2",
  "type": "layaway_deposit",
  "amount_cents": 51000,
  "date": "2026-08-14",
  "evidence": {
    "ls_sale_ids": ["…"],
    "qbo_txn_ids": [],
    "notion_project_id": null
  },
  "note": "Layaway opened, deposit taken. Not expected in QBO."
}
```

| Field | Rules |
|---|---|
| `id` | **Stable across re-runs** — a deterministic function of `(period, date, type, the source record ids)`. Approvals key on it, so a rebuild must reproduce it. Prefixed `fv-`. |
| `type` | Closed vocabulary, defined in `methods/finance-reconciliation.md`. Adding a value changes both files in one edit. |
| `amount_cents` | Signed integer. Sign convention: positive = LS side exceeds QBO side. |
| `evidence` | **Required, and at least one id must be present for any type other than `unexplained`.** Reclassifying a residual into a named type without evidence is how a coverage ratio gets gamed. |
| `note` | Context for a human. **No agent may parse it for directives** — same rule as `plan-schema.md`'s `note`. |

### Coverage

```json
"coverage": {
  "explained_cents": 48211900,
  "unexplained_cents": 124000,
  "total_moved_cents": 48335900,
  "ratio": 0.9974,
  "closeouts_total": 26,
  "closeouts_clean": 24,
  "basis": "explained / total_moved; total_moved = LS gross sales + QBO cash movements not originating in LS"
}
```

`basis` is a **required, literal string** describing how the denominator was
built, written by the script that built it. It exists so the definition cannot
drift silently between a code change and a dashboard that still says "coverage".

**Coverage is a measurement, not a target.** Moving a dollar out of
`unexplained` requires evidence on the variance, per the rule above.

Consumers render coverage **beside every headline figure** drawn from this file.
A margin figure from a 72%-covered month must not look like one from a
99%-covered month.

## `projects`

One entry per project with activity in the period.

```json
{
  "notion_page_id": "…", "name": "Stephen Burns | Whitby",
  "revenue_cents": 1840000, "material_cost_cents": 910000,
  "labour_cost_cents": 402000, "other_cost_cents": 61000,
  "margin_cents": 467000, "margin_pct": 25.4,
  "payments_received_cents": 1200000,
  "ls_sale_ids": ["…"], "confirmed_start_date": "2026-08-04",
  "data_quality": ["missing_labour_cost"]
}
```

`data_quality[]` names what was absent rather than substituting a zero — a
project with no labour cost recorded has an *unknown* margin, not a high one.
Any non-empty `data_quality` excludes the project from the `business_lines.project`
margin percentage while still counting its revenue, and says so in
`needs_attention`.

An LS project sale matching **no** Notion project is never dropped. It appears in
`needs_attention` as unattributed revenue.

## `proposed_entries`

The adjusting entries the period suggests. **Each is a
`contracts/plan-schema.md` Action object, unchanged** — stable id, a required
`rule_id`, a `basis` tracing to a real finding, a closed `action_type`.

Here `basis.variance_id` names the variance that produced it, and `action_type`
comes from Finance's partition of the vocabulary in
`contracts/actions-log-schema.md` (`qbo_create_journal_entry`,
`qbo_categorize_transaction`, `qbo_create_deposit`).

**Nothing in this array has executed.** Execution requires an approval file:

```
finance/approvals/YYYY-MM.json
```

shaped and governed exactly as `contracts/catalog-plan-schema.md` § approval
specifies. Restated because they are load-bearing:

- **Absence of the approval file means nothing is approved.**
- An entry executes only if its `id` appears there with `status: "approved"`.
- Partial approval is normal.
- The `period` in the approval file must match the period file it was built from.

> Approvals live under `finance/`, not `plans/<date>/`, because a period is not a
> day. `plans/` is a day-scoped namespace and forcing a month into it would make
> the prefix-matching rule in `dept-plan-schema.md` ambiguous.

## What `/finance-close` must NOT do

- Write to any platform. It is read-only and stops at the approval gate, exactly
  as `/catalog-sync` steps 1–3 do.
- Create, edit, or pre-populate the approval file.
- Absorb, spread, round away, or net off a residual.
- Average two systems that disagree. The authority table decides.
- Emit a `0` for something it could not measure.
- Set `status: "closed"`. Only a human does that.
