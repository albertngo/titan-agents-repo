# Bookkeeper plan — unblocking Finance

Written 2026-10-07, one week after the FY2026 year-end (Sep 30). A plan, not a build:
nothing below has been executed, and every step that touches an agent definition,
a contract, Make or QBO waits for Albert's yes (CLAUDE.md, "Ask Albert / propose-and-stop").
If this drifts from `CLAUDE.md`, `CLAUDE.md` wins.

---

## Where things stand

### The ingest has never produced a number

`bookkeeper-ingest-agent` is told to "use the Intuit QuickBooks MCP connector". No such
server is in `.mcp.json`, so every run writes `status: "error"`: 38 `error` and 1 `missing`
in `ingest/run-ledger.json`, and the vault's daily notes record the same failure through
2026-10-07. Finance is `blocked` in `departments.json` for exactly this reason.

Two smaller defects ride along:

- The error file still writes `payments_received_cents: 0` etc. Every vault note then has
  to say "zeros are placeholders". An error file should carry `metrics: {}`.
- `departments.json` → `blocked_reason` names the missing MCP server as the blocker. The
  real blockers are the two below.

### A working QBO path already exists, in Make

| Make object | What it is | State |
|---|---|---|
| Connection **4820024** "QBO Connection" | OAuth to *Titan Flooring Inc. (CA)*, scope `com.intuit.quickbooks.accounting` (**read and write**) | **Expires 2026-11-01** per Make |
| Scenario 4822446 "Sync Chart of Accounts" | `select * from account` → datastore 88653 | on-demand, read-only |
| Scenario 4822687 "Pull P&L Report" | `GET /reports/ProfitAndLoss` (dates hard-coded 2026-01-01 → 07-13) → chunked into datastore 88661 | on-demand, read-only |
| Scenario 4824058 "Create New CoA Accounts (one-time)" | Despite the name, now a single `GetAccount 173` → datastore | on-demand, read-only |
| Scenario 4824368 "Register Closure Watchdog" | Counts QBO invoices → WhatsApp + Notion to-do | on-demand, **still on its test query** (`CreateTime > '2027-01-01'`, which is always 0, so it would always alarm) |
| Scenario 4841468 "Outlook INVOICE → QBO Receipts" | Forwards mail with attachments to `titanflooring@qbodocs.com`, moves it | on-demand |

The datastore chunking in 4822687 was a workaround for reading results back out. A
webhook that answers with the response body removes the need for it.

The expiry date fits Intuit's 100-day rolling refresh window measured from the last use,
around 2026-07-24. Using the connection should roll it forward. If it lapses, only Albert
can re-authorize it, in Make.

### The environment can't reach either host today

From this cloud environment, `hook.us1.make.com`, `us1.make.com`,
`quickbooks.api.intuit.com` and `oauth.platform.intuit.com` all fail with a CONNECT 403
from the network policy. `graph.microsoft.com` and `services.leadconnectorhq.com` pass.
Whatever path is chosen, its host has to be added under the environment's **Network
access → Allowed domains** (https://code.claude.com/docs/en/cloud-environments#network-access).

### The books themselves (QBO-LS Fix Log / Task Queue in Notion)

- FY2026 = Oct 2025 – Sep 2026, now closed. HST is filed annually.
- Hien Nguyen, CPA (Dang & Associates) took on review and reconciliation for Jan–Sep at
  $400/mo, working against the rulebook. Her corrections are meant to train the "Titan
  Bookkeeper skill", which lives outside this repo.
- Decision D2 (07-15): Dext no longer publishes bills, so **QBO has no A/P by design**.
- The 2026 P&L is "unusable for margin analysis" until the inventory count and COGS true-up.
- **The QBO-LS Task Queue has 33 open rows**, all added 07-15 → 07-20. Several carried
  "before Sep 30" deadlines:
  - Amica ring-in ($60,398.50)
  - cleanup sequencing against year-end
  - the year-boundary closure journal for #394/#441

  One has a hard deadline still ahead: the HoldCo HST registration and the Mar–Jul rent
  invoices ($57,000) must exist **before the annual HST return, around Dec 2026**. The
  queue may simply be stale after the July–Aug catch-up. Only Albert can tell.

### What the QBO API can and cannot see

This sets what the ingest can promise:

- **It cannot see bank-feed "For Review" lines.** The 355 BMO card lines, the EMT
  backlog and anything else waiting in Banking are invisible to the Accounting API.
  `uncategorized_txns` therefore cannot mean "the review queue". It can only mean
  *posted* lines sitting in the holding accounts: Uncategorized Expense/Income/Asset,
  Ask My Accountant, Suspense.
- It can see posted entities through `query` and through `cdc`, which returns everything
  changed since a timestamp, up to 30 days back. That makes `cdc` the natural "last 24h"
  call.
- It can see reports: `ProfitAndLoss`, `BalanceSheet`, `AgedReceivables`, `TrialBalance`,
  `TransactionList`, `GeneralLedger`.
- It can see account balances (`Account.CurrentBalance`). The Undeposited Funds tank was
  $436,418 on 07-13.
- Sales arrive from Lightspeed register closures. The watchdog counts `Invoice`; the
  first live pull should confirm whether closures land as `Invoice` or `SalesReceipt`
  before any rule depends on it.

---

## Recommended pull path: a read-only Make webhook bridge

```
scripts/bookkeeper_pull.py ──POST {path, params} + secret──► Make webhook (new scenario)
   (via scripts/qbo_client.py)                                 │ filter: secret matches AND
                                                               │         path in allowlist
                                                               ▼
                                              QuickBooks "Make an API call", method = GET (literal)
                                                               │
                                                               ▼
                                                 Webhook response ◄── QBO JSON body
```

**Why Make.** The OAuth problem is already solved there. A direct Intuit app would rotate
its refresh token on every refresh, and an ephemeral container has nowhere to keep the
new one. Albert would also need an Intuit developer app with production keys.

**Why not the claude.ai Intuit QuickBooks connector.** It failed to connect in this session.
It is also session-attached, so it dies on scheduled runs; that is why Outlook moved to
`scripts/outlook_pull.py` (architecture.md). And it carries write tools, which an
`*-ingest` agent must not hold.

**Why a webhook, not the Make API "run scenario".** The webhook URL plus its secret can
reach one scenario and nothing else. A Make API token sitting in `.env` could reach every
scenario in the team.

**Read-only is structural, not trusted.** The QBO connection has full accounting scope,
the same situation as Lightspeed's unscopable personal token. So the guarantee lives in
the shape of the code, and tests check that shape:

1. **Bridge scenario.** Only three modules: webhook, `quickbooks:MakeApiCall` with
   `method` set to the literal `GET`, and the webhook response. Its filter allows only
   these paths: `/query`, `/cdc`, `/reports/*`, `/companyinfo/*`, `/preferences`.
2. **Blueprint snapshot.** Lands at `platform-settings/blueprints/qbo-read-bridge-<id>.json`.
   `tests/test_bookkeeper.py` pins the literal GET, the allowlist, the secret check, and
   "no other QuickBooks module". This is the same pattern `tests/test_ghl_calls.py` uses
   for scenario 4951497.
3. **Client.** `scripts/qbo_client.py` has no write verb and refuses any path outside the
   same allowlist. `bookkeeper_pull.py` reaches QBO only through it.
4. **Credentials.** `.env.example` gains `QBO_BRIDGE_URL` and `QBO_BRIDGE_SECRET`. Together
   they read the entire ledger, so they are handled like the Lightspeed token: `.env` only.

---

## The plan

### Phase 0 — Albert, before any build (≈ this week)

| # | What | Why now |
|---|---|---|
| 0.1 | Approve or redirect the pull path above | Everything below depends on it |
| 0.2 | Add `hook.us1.make.com` to the environment's Allowed domains | Denied today |
| 0.3 | Note the **2026-11-01** QBO connection expiry | Phase 1 landing before then keeps it alive; after, it needs re-authorizing |
| 0.4 | Triage the QBO-LS Task Queue: close what the July–Aug catch-up finished, re-date what is left | 33 rows, untouched since 07-20 |
| 0.5 | Decide the accountant's FY2026 year-end scope; the Jan–Sep engagement has run out | Year-end journals (#394/#441, 7788/TD merge, payroll repoint) sit with her |
| 0.6 | Put the HoldCo HST registration + backdated invoices on a dated track | Hard deadline: before the HST return, ~Dec 2026 |

### Phase 1 — make the source work (one PR, target before 2026-11-01)

1. **Bridge scenario.** Built in Make, either by Albert from a committed blueprint or by a
   session through the Make MCP on his explicit yes. It reuses connection 4820024.
2. **Code.** `scripts/qbo_client.py` + `scripts/bookkeeper_pull.py` + `tests/test_bookkeeper.py`.
3. **Registry.** New `platform-settings/bookkeeper.json`. Account ids live here, never in a
   prompt:
   - Undeposited Funds; Uncategorized Expense/Income/Asset; Ask My Accountant; Suspense
   - the dead "Product Sales" account; 7788; BMO chequing; Due to/from Titan Holdings

   Thresholds: expense > $500, closure gap ≥ 3 days. Fiscal year starts in October.
   The first pull fills the ids from `select * from Account`, the same query 4822446 runs.
4. **Agent v2.** `bookkeeper-ingest-agent` drops the MCP instruction and runs the pull
   script as step 0, like `ghl-ingest-agent`. Its `type` vocabulary becomes:

   | type | Fires on | Grounded in |
   |---|---|---|
   | `closure_gap` | No Lightspeed sale posted to QBO in ≥ 3 days; or a sale posted after Oct 1 with a prior-fiscal-year `TxnDate` | CPA Q2.1 "close daily"; the #394/#441 year-boundary finding |
   | `payment` | A/R payments received in the window | `payments_received_cents` |
   | `invoice` | Commercial A/R crossing overdue (`AgedReceivables`) | `overdue_invoices` |
   | `expense` | New Purchase > $500 | v1 scope |
   | `flag` | Postings to a holding account, to dead "Product Sales", or payroll to 7788 after the repoint | Fix Log traps |

   - Metrics: `payments_received_cents`, `overdue_invoices`, `uncategorized_txns` (posted
     holding-account lines, as defined above), `days_since_last_closure` and
     `uf_balance_cents`.
   - Error files carry `metrics: {}`.
   - No margin or P&L metric until Albert says the inventory true-up is done.
   - Sensitivity default stays `private`.
5. **Docs, same PR.**
   - CLAUDE.md agent table row
   - `departments.json` `blocked_reason`
   - `methods/architecture.md` "Still open"
   - `.env.example`

   The vault decision note is proposed, not written (off-whitelist).

### Phase 2 — prove it, then un-block Finance

The unblock rule in `departments.json` is unchanged: **three consecutive
`bookkeeper: "ok"` entries** in `run-ledger.json`. After that, write
`finance-lead-agent` (Read/Write only, `contracts/dept-plan-schema.md`) with a rule table
taken from those three real days, not from this document. Candidate rules, to be
confirmed or dropped against the real days:

- closure gap → "close the register"
- holding-account balance rising day over day
- commercial A/R past 30 days
- dated tax deadlines (HoldCo invoices, HST return)

### Phase 3 — the closure watchdog

Recommend finishing it **in Make**, which is the Task Queue item owned by "Claude Code"
since 07-15:

- Replace the test query with a rolling 3-day window.
- Confirm the WhatsApp number.
- Schedule it daily.

It should stay outside the agent system for the same reason as the GHL comment alarm: it
has to fire even when no Claude session runs. The ingest's `closure_gap` adds the same
fact to the brief, which gives two signals for one condition, on purpose. This changes a
live Make scenario, so it needs Albert's yes.

### Not planned

- **No agent writes to QBO.** There is no `qbo-actions-agent`. Categorization, journals and
  reconciliation stay with Albert and the accountant.
- No bank-feed (For Review) automation; the API can't see it.
- The Titan Bookkeeper skill's training pass on the accountant's corrections is a separate
  track and does not live in this repo.

---

## Open questions for Albert

1. Make webhook bridge as the pull path: yes or no?
2. Should a session build the bridge scenario through the Make MCP, or will you build it
   from a committed blueprint?
3. Should the watchdog be fixed and scheduled in Make, or retired in favour of the ingest flag alone?
4. Is the accountant engaged for the FY2026 year-end, and from what date?
