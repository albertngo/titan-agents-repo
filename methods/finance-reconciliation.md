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
- **Project margin is computed from the Notion figures, never from LS.** Project
  Financials already carries the rollups (Total Flooring Material Cost / Revenue
  / Profit, Total Labor Cost, Total Other Costs, Sqft) — but see the constraint
  immediately below, because they cannot be *read* from Notion.

### The constraint that shapes Phase 3: Notion's money is unreadable

**Every money property on Project Financials is a formula or a rollup, and the
Notion MCP returns those as opaque `formulaResult://` / `rollupResult://`
references rather than numbers.** Verified on a live page 2026-09-11; the
`financials-relation-sync` skill documents the same behaviour as `<omitted />`.

So the computed project P&L **cannot be read out of Notion at all**. The
machine-readable copy is the Airtable **Project Log** table
(`appLRen9XOjNdlWyp` / `tblPVbruU6cJmyzIZ`, 416 rows — the same 416 rows as the
Notion table), which carries Revenue, Total Project Profit, Overall Margin,
Labor Cost, NFM Cost, Other Costs, Flooring Material Revenue/Cost and Sqft as
plain numbers, keyed by `PP-###`.

The division of labour is therefore:

| | Read from |
|---|---|
| The **definitions** — what "Service Profit" or "Commission Basis" means | Notion's formula descriptions |
| The **values** | Airtable Project Log |
| The **raw inputs**, if the mirror goes stale | Notion Flooring Line Items (`Sqft Sold`, `Cost Rate`, `Sold At Rate`) and Project Costs (`Cost`, `Category`) — these *are* plain numbers |

> **How Project Log stays in sync with Notion was not established.** No Make
> scenario for it was found. If it is a manual export, its freshness is a
> standing risk: the period file must carry the mirror's own as-of date, not the
> date the pipeline ran.

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

**Verified 2026-09-11** against the live account — a full walk of 55,820 sales
in 56 requests. The vocabulary, with full-history counts, is recorded in
`platform-settings/lightspeed.json`:

| status | count | open? | treatment |
|---|---|---|---|
| `CLOSED` | 51,976 | no | ordinary sale, expected in the closeout |
| `VOIDED` | 1,438 | no | excluded from every revenue figure |
| `SAVED` | 1,020 | yes | parked, not tendered — **neither revenue nor a receivable** |
| `ONACCOUNT_CLOSED` | 843 | no | on-account since settled |
| `LAYBY_CLOSED` | 506 | no | **layaway revenue is recognised here** |
| `ONACCOUNT` | 31 | yes | open receivable — Gap B |
| `LAYBY` | 3 | yes | open layaway — Gap A |
| `PICKED_UP_CLOSED` | 2 | no | rare; treat as `CLOSED` |
| `QUOTE` | 1 | yes | not a sale |

27 `ONACCOUNT` and 3 `LAYBY` sales dated 2026 were open at the walk. **That live
position exists nowhere in QuickBooks.**

### The sync may not be running at all

Two independent observations, both from 2026-09-11:

- **No sale in 55,820 carries a non-null `accounts_transaction_id`**, and
  `has_unsynced_on_account_payments` is `false` on every one. If the
  Lightspeed→QBO accounts integration were running and stamping the sale record,
  something would have been stamped.
- The **QBO P&L for Jan 1 – Jul 13 2026 shows COGS of \$612,778 against income of
  \$587,340** — cost of goods *exceeding* revenue, against a FY2025 that looked
  ordinary. That is the signature of sales not posting, not of selling below cost.

**Not proven** — the sync may post through a channel that never touches the sale
record. Confirm in the Lightspeed admin before treating it as established, and do
not state it as fact in any brief. But it is the first thing to check, because if
it is true then every downstream figure inherits it.

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

## Identifying a project sale

A project sale is excluded from retail gross margin and attributed to its Notion
project instead. The identifier is **data, never a literal in a script** —
`platform-settings/finance.json` holds it.

**The join key is the `PP-###` reference in the Lightspeed sale note.** Verified
2026-09-11: notes read like `@Pack Allen Giancomelli PP-416`, and `PP-###`
resolves to Notion Titan Projects' auto-increment `ID`, mirrored as `Project ID`
on the Airtable Project Log. PP-447 and PP-449 were confirmed present on both
sides, so the join works.

> **It attributes almost no history.** Only **20 sales out of 55,820** carry a
> `PP-###` note — 19 distinct projects, every one dated 2026, nearly all on
> 2026-09-09 and 2026-09-10. **The convention is about two days old.** It is the
> right key going forward and it attributes essentially zero historical project
> revenue. A backfill needs a different method or an accepted, stated gap.

### "The Poreus account" did not survive contact with the data

Albert described project sales being rung "under the Poreus account". Checked
directly:

- **No Lightspeed customer** named Poreus or Porous exists — all 2,779 customers
  were scanned.
- There **is** a Lightspeed *user* **Pourya** (`pourya@titanfloors.ca`, cashier),
  who is also the `Sales Person` on the Airtable project rows — so "Poreus" is
  almost certainly "Pourya".
- But **Pourya has rung 2 sales in the entire 55,820-sale history**, one of them
  on 2026-09-10. As an identifying signal it matches nothing.

So `user_id` is recorded in the registry with `use_as_signal: false`, and the
question goes back to Albert rather than being guessed at. A rule that matches
nothing fails *silently* and inflates the figure it was meant to exclude — the
same failure mode as the catalogue routine's `Extraction Status` filter on
2026-09-10.

**Project sales are not an edge case in this reconciliation — they are most of
it.** Of the twelve most recent PP-tagged sales: four `ONACCOUNT`, one `LAYBY`,
two `LAYBY_CLOSED`, four `CLOSED`, one `SAVED`. They sit squarely in the gaps.

A project sale matching no Notion project is **not** dropped. It becomes
unattributed revenue in `needs_attention`.

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
