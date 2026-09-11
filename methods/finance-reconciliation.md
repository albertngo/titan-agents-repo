# Finance Reconciliation

How Titan's money is actually counted, and why no single system can do it.
Written 2026-09-11. If this drifts from `CLAUDE.md`, `CLAUDE.md` wins;
`platform-settings/finance.json` is authoritative for ids, mappings and
thresholds.

Consumed by `scripts/finance_reconcile.py` and `.claude/commands/finance-close.md`.
Output contract: `contracts/finance-period-schema.md`.

---

## The claim this document rests on

**There is no single source of financial truth at Titan, and building one would
make the numbers worse, not better.**

Each system is authoritative for a different fact, and none can answer for
another:

| Fact | Authority | Why nothing else can answer it |
|---|---|---|
| Cash in/out, GL, bank balance, expense category | **QuickBooks** | It is the tax book. The bank feed and bank rules land here, and ~95% of expenses are paid by bank transaction. |
| What sold, to whom, at what price, and its tender state | **Lightspeed** | QBO only ever receives a register-closeout *aggregate*. Per-sale detail does not exist on the QBO side to be queried. |
| Project scope, true material + labour cost, project margin | **Notion** Project Financials | LS project sales are booked cost = revenue deliberately, so LS reports zero margin on them by construction. |
| Money received against a project | **Notion** Master Payments Log + the QBO deposit | Split across both by design; some project money never passes through LS at all. |

So the deliverable is a **reconciliation ledger** — the systems kept side by
side with every difference named — not a merged "one number". This is the same
refusal the repo already makes for project vs STORE pipeline value: two numbers
side by side, never summed, because a combined figure would describe neither
(`methods/departments.md`, "Ranking, and the thing we refuse to compute").

---

## The grain problem

`contracts/ingest-schema.md` is a **24-hour delta** contract. It describes
events: what happened since the last run.

Finance needs **period state**: balances. "Outstanding layaway liability" and
"AR as at month end" are not events and cannot be expressed as a delta, however
many days of deltas you stack up — a balance is a position, and a sequence of
deltas only reconstructs one if you are certain no day is missing. The run
ledger proves days *are* missing.

Hence two artifact classes:

| | Grain | Written by | Contract |
|---|---|---|---|
| `ingest/<date>/<source>.json` | 24h delta | the ingest agents | `contracts/ingest-schema.md` |
| `finance/periods/<YYYY-MM>.json` | period state | `/finance-close` | `contracts/finance-period-schema.md` |

The period file is rebuilt from source each time, idempotently. It is never
accumulated by adding today's delta to yesterday's balance — that would make one
missed run corrupt every subsequent period silently.

---

## The three gaps

Albert named three places the systems provably disagree. Each is modelled as a
**typed variance**, never silently corrected.

### Gap A — Layaway

LS layaway does not sync to QBO at all. A layaway deposit is therefore cash
received that QBO never sees.

Two consequences, both wrong in QBO until adjusted:

- Cash-in is understated for the period the deposit was taken.
- There is no customer-deposit liability on the balance sheet. **A layaway
  deposit is a liability, not revenue** — the goods have not been handed over.
  Recognising it as revenue overstates both income and margin in that period, and
  then double-counts when the layaway completes.

Revenue is recognised at **redemption** (layaway closed, goods out the door), not
at deposit. The deposit moves cash and liability only.

### Gap B — On-account (AR)

Two distinct failures, often conflated:

1. **Non-sync.** An on-account charge sometimes never reaches QBO. QBO's AR
   understates what customers owe.
2. **Edit drift.** When an on-account sale is *changed* in LS, the QBO mirror is
   not updated. This is the nastier one: both systems hold a record, they
   disagree, and nothing signals it. The QBO figure will look plausible forever.

Because of (2), **LS is authoritative for AR** and QBO's AR is treated as a
mirror to be corrected — not as a second opinion to be averaged.

### Gap C — Project accounting

A project sale is rung in LS under the Poreus account against a project-specific
product, with **cost set equal to revenue**. That is deliberate: it keeps the
project's material cost from being double-counted against retail COGS. The
side effect is that LS reports exactly **zero margin** on every project line.

Two things follow:

- **LS project sales must be excluded from retail gross margin.** Otherwise
  zero-margin volume silently dilutes the retail figure — the more project work
  Titan does, the worse retail appears to perform, for no real reason. See the
  exclusion rule below.
- **Project margin is computed from Notion, never from LS.** Project Financials
  already carries the rollups (Total Flooring Material Cost / Revenue / Profit,
  Total Labor Cost, Total Other Costs, Sqft).

There is a third wrinkle: part of a project's money arrives **outside LS
entirely** — cash, or paid externally. That money hits the bank, and therefore
QBO, with no matching LS sale. It is a legitimate difference, typed
`external_project_payment`, not an error.

---

## The reconciliation identity

Asserted per register, per closeout day:

```
  LS closeout total
    − layaway deposits taken        (Gap A: never synced)
    − on-account charges            (Gap B: may not have synced)
    + layaway redemptions
    + on-account payments received
  = QBO sales receipt / journal for that closeout
```

Any residual is **unexplained** and is flagged. Bridging the gap does not mean
forcing the two sides equal — it means every dollar of difference carries a
named type, and what is left over is stated rather than absorbed.

### Why this is mechanical, not heuristic

X-Series carries tender state on the sale record's own `status` field. The
layaway and on-account partitions are therefore a **filter on a field**, not an
inference from amounts or timing.

> **Verify before relying on it.** The status vocabulary (expected to include
> `CLOSED`, `LAYBY`, `ONACCOUNT`, `VOIDED` and closed variants) has **not** been
> confirmed against Titan's live data. Run `lightspeed_sales_pull.py --probe`
> and record what actually comes back in `platform-settings/lightspeed.json`,
> the same discipline `lightspeed_pull.py` applied to the product shape before
> the catalogue sync trusted it. Until then, treat the vocabulary here as a
> hypothesis.

### Variance types — closed vocabulary

Adding a value is a change to this file **and** to
`contracts/finance-period-schema.md`, in the same edit.

| Type | Meaning | Expected? |
|---|---|---|
| `layaway_deposit` | Cash taken on a layaway not yet redeemed | yes |
| `layaway_redemption` | Layaway closed; revenue recognised now | yes |
| `on_account_charge` | AR created in LS, may not be in QBO | yes |
| `on_account_payment` | AR settled in LS | yes |
| `on_account_edit_drift` | LS and QBO both hold the sale and disagree | **no — always flag** |
| `external_project_payment` | Project money that reached the bank without an LS sale | yes |
| `unexplained` | Residual after all of the above | **no — always flag** |

`on_account_edit_drift` and `unexplained` are the two that mean something is
wrong. The rest are the system working as designed and must not read as errors
on the dashboard.

---

## The Poreus exclusion rule

LS sales identified as project sales are excluded from retail gross margin and
matched to their Notion project instead.

Identification is **data, not a literal in a script** —
`platform-settings/finance.json` holds the customer-account identifier and the
project-product SKU pattern. Two independent signals are kept deliberately: a
project sale rung without the account set, or against an ad-hoc product, would
otherwise fall silently into retail.

> **Unverified.** The exact spelling and the LS customer id behind "the Poreus
> account" have not been confirmed against live data, nor has the project-product
> SKU convention. Both must be pinned before the exclusion can be trusted — an
> exclusion rule that matches nothing fails *silently* and inflates retail
> margin, which is exactly the failure mode the catalogue routine's
> `Extraction Status` filter hit on 2026-09-10.

A project sale that matches no Notion project is **not** dropped. It becomes a
flagged item: revenue with nowhere to attribute it is a finding, not a rounding.

---

## Coverage ratio — how accuracy gets stated

100% reconciliation is not achievable and pretending otherwise is the failure
mode. So every period file publishes what it actually achieved:

```
reconciliation_coverage = explained_cents / total_moved_cents
```

alongside raw `unexplained_cents` and the count of closeouts involved.

**The dashboard renders this beside every headline number.** A gross margin
figure drawn from a 72%-covered month must not look like one drawn from a
99%-covered month. A number without its coverage is a number pretending to a
precision it does not have.

Coverage is a *measurement*, never a target to be met by reclassifying residuals
into a named type. Moving a dollar from `unexplained` to a real type requires
evidence — a matching LS sale id, a QBO transaction id — recorded on the variance.

---

## Business lines, and the one thing this method refuses to compute

Gross margin is computed **per business line** (project · store · other), each
from its own authority per the table at the top.

Net profit after opex is computed **at company level only**.

**Operating expenses are not allocated across business lines.** Splitting shared
overhead requires an arbitrary basis, and publishing the result as "project net
profit" would be false precision — a number that looks authoritative and is not.
If allocation is wanted later it needs a stated basis and a visible
`allocated: true` flag on every figure derived from it. Never a silent default.

---

## The reporting spine

Titan's fiscal year ends **September 30**.

Months are the atom. Every month belongs to exactly one fiscal quarter and one
calendar quarter, so both are *derived*, and each period file carries
`fiscal_year`, `fiscal_quarter` and `calendar_quarter`.

| | Fiscal (YE Sep 30) | Calendar |
|---|---|---|
| Q1 | Oct–Dec | Jan–Mar |
| Q2 | **Jan–Mar** | Apr–Jun |
| Q3 | Apr–Jun | Jul–Sep |
| Q4 | Jul–Sep | Oct–Dec |

**Never print a bare "Q1".** It means Oct–Dec fiscally and Jan–Mar
calendrically, and the two are a quarter apart. Always
`FY26 Q2 (Jan–Mar)`.

**Fiscal is the default** for anything that rolls up — YTD, quarters, bonus
pools — because year-end decisions are fiscal-year decisions and QBO's own
fiscal-year setting will agree with it, giving one YTD figure rather than two.
Calendar stays renderable because seasonality reads better on it and external
benchmarks are calendar.

**Month-over-month is the primary lens.** Quarters are a roll-up view, not a
separate computation.

---

## What this method must NOT do

- **Write to any platform.** `/finance-close` is read-only and stops at the
  approval gate, exactly as `/catalog-sync` steps 1–3 do. Adjusting entries are
  proposed with stable ids and executed only from an approval file.
- **Absorb a residual.** An unexplained difference is reported, never spread,
  rounded away, or netted against another variance.
- **Average two systems.** Where LS and QBO disagree, the authority table
  decides which is right and the other is corrected. There is no midpoint.
- **Sum business lines into one margin figure.** Company-level margin is
  computed from company-level revenue and cost, not by averaging line margins.
- **Recognise a layaway deposit as revenue.**
- **Present a Notion payments-log figure as bookkeeping.** It is money received,
  not the book. `departments.json` already records this as a partial-answer
  source and the label survives into every downstream render.
