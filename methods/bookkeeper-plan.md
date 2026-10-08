# Bookkeeper plan — QBO live access and the Finance department

First written 2026-10-07. Decisions settled 2026-10-08 by Albert, in a grilling session
on his "Titan Bookkeeper — QBO Live Access Plan" (PDF, 2026-10-07).

This is still a plan: nothing below has been built. Every Make, QBO, agent or contract
change waits for its own "go" (CLAUDE.md, "Ask Albert / propose-and-stop"). If this
drifts from `CLAUDE.md`, `CLAUDE.md` wins.

---

## Decisions (Albert, 2026-10-08)

| Area | Decision |
|---|---|
| **Home** | `titan-agents-repo`, as the Finance department. The `titan-bookkeeper` repo is archived and its bank-rules doc moves here. |
| **Rules master** | One rules file, `platform-settings/bookkeeper-rules.yaml` (the "rules ledger"). The QBO-LS Fix Log in Notion becomes history. When Albert or Hien corrects a proposal, it becomes a *suggested* rules change that Albert approves. |
| **Access** | Make, in two scenarios with two secrets. The **read door** allows read calls only and is what scheduled runs use. The **write door** is loaded only by the write agent after approval. The write secret lives only in a **separate cloud environment**; the environment used by the daily routines never holds it. |
| **Who builds Make** | Claude, through the Make connector, on Albert's yes. Both scenarios stay switched off until he has looked at them in Make. |
| **Fallbacks** | Intuit's own MCP server (`intuit/quickbooks-online-mcp-server`) is documented as the fallback but not built. DataGrout is dropped. |
| **Write scope** | Create, update and delete, plus tax-code changes, all behind approval. |
| **Always a person's yes** (never earns autonomy) | Deletes; tax-code changes; anything dated in FY2026 (before 2026-10-01); any single write over **$1,000**. |
| **Periods** | FY2027 is open, behind the gate. FY2026 only in batches Albert has forwarded to Hien and she has OK'd, with the date of her reply recorded. After her year-end sign-off, the QBO closing date moves to 2026-09-30. Nothing before Oct 2025, ever. |
| **Reconciled transactions** | Never touched. They are flagged for Albert or Hien. |
| **Approvals** | A private Notion database with one row per proposal; Albert ticks Approve. The run turns ticked rows into the approval file the write agent obeys. A tick is a structured approval, unlike the catalogue's prose `Action` cells. |
| **Autonomy** | The run counts proposals per rule that were approved unchanged and says when one reaches 20 in a row. The flip is Albert's dated vault decision. Autonomous rules then run on a schedule **in the write environment** and push a digest. |
| **Git** | Commit the audit trail: proposals, approvals and write logs. Raw QBO pulls go in a git-ignored cache. |
| **Daily brief** | The bookkeeper's daily read joins `/daily-ingest` through the read door. It is admin-only (`private`). Three clean days un-block Finance. |
| **Receipts (job 1)** | Read-only. The agent reads the receipt emails at info@titanfloors.ca alongside what QBO has posted, and reports which receipts are still unreviewed in QBO and what each should be. It writes nothing. |
| **First reconciliation** | Decided after a month of receipt read-back. |
| **Third-party skills** | Adapt Receiptor's `receipt-processing`, `bank-reconciliation` and `expense-categorization`: strip the WebFetch pre-grant and the upsell, and add a Canada/Ontario tax pack. Use openaccountant's `month-end-close` and `square-import` (the pattern for Lightspeed closures) as ideas only. Copied code must have a license that allows copying, is read before it lands, reaches the network only through the QBO gateway, and has its source commit recorded. |
| **Make cleanup** | Delete the July TEMP scenarios now. Fix and schedule the closure watchdog in Make. Delete the three older Bookkeeper scenarios (Pull P&L, Sync CoA, "Create New CoA") once the read door has worked for a week. |

These follow from the decisions and were confirmed with them:

1. Every write first saves the record's previous state to the log, so it can be
   reversed. This is required because deletes are allowed.
2. No write agent exists until the read door has had three clean daily runs.
3. Albert allows `hook.us1.make.com` in both cloud environments and creates the write
   environment.
4. The read door lands before the QBO connection expires on 2026-11-01.

---

## Facts the decisions rest on

### Access

- **Make already reaches the Canadian file.**
  - Connection 4820024, "Titan Flooring Inc. (CA)", scope `com.intuit.quickbooks.accounting`.
  - In July it synced 93 accounts in CAD (datastore 88653) and pulled a P&L through
    "Make an API call".
  - Make shows the connection **expiring 2026-11-01**. That fits Intuit's rolling 100-day
    window; use extends it, and the token itself has a 5-year hard cap.
- **This environment can't reach Make or Intuit.**
  - `hook.us1.make.com`, `us1.make.com` and the Intuit hosts are refused by the cloud
    network policy (CONNECT 403). Graph and GHL pass.
  - Fix: environment → Network access → Allowed domains
    (https://code.claude.com/docs/en/cloud-environments#network-access).
- **Cloud Routines don't expire.** "New Price Lists", "Daily Brief" and
  "Project Status" have fired for weeks. The 7-day expiry in the PDF applies only to
  session-scoped `/loop` / CronCreate tasks.
- **Make webhook responses must return in time.** Make's own docs disagree: 40 s in one
  place, 180 s in another. Large pulls must therefore be paged.

### What the QBO API can and cannot do

| Can't | Detail |
|---|---|
| Read bank/card lines still **in For Review** | Only posted Purchase, Deposit, Transfer, JournalEntry and CreditCardPayment, plus the TransactionList report. |
| Read **receipts nobody has reviewed** | After review there is no "came from receipt capture" flag. Images sit on `Attachable`, downloaded through `TempDownloadUri` or `/download/{id}`. Whether a captured image survives review needs a live test. |
| **Void** Purchase, Bill or JournalEntry | Delete only, with Id + SyncToken. Void exists for Invoice, Payment, SalesReceipt and BillPayment. |
| Write **before the closing date** | Rejected with 6200/6210. The API cannot override it. |
| Post a line without a real **TaxCode Id** | `TAX`/`NON` are rejected outside the US. There's no automated sales tax for Canada, and HST on journal-entry lines is poorly supported. |

### Mail and the old repo

- **Receipt emails arrive at info@titanfloors.ca.** That is the folder Make's forwarder
  4841468 reads. The Graph app behind `outlook_pull.py` already covers info@, so job 1
  needs no new mail permission.
- **`titan-bookkeeper` holds only a README and `docs/consolidated-bank-rules.md`**
  (v3, 55 rules). There's no `rules/ledger.yaml` or `SKILL.md` yet. The rule logic
  itself lives in the Notion Fix Log and in `Titan_Bookkeeping_Rulebook.docx`.

### Third-party skills (surveyed 2026-10-08, read only, nothing executed)

- **Receiptor-AI/bookkeeping-skills** (MIT): the useful one. Evidence rules, matching
  tiers, approval limits, and small stdlib scripts with no network calls. Its tax content
  is US-only (Schedule C, 1099); the one Canada line cites T2125, a sole-proprietor form
  and wrong for a corporation.
- **openaccountant/skills** (MIT): prose only. Thin, and US categories throughout.
- **invoice-organizer**: a file renamer with no LICENSE file.
- **alirezarezvani/claude-skills**: finance analytics, the wrong domain.
- **Composio `quickbooks-automation`**: excluded. It sends the QBO login through a
  third-party broker.

### The books (QBO-LS Fix Log / Task Queue)

- **Year and accountant.** FY2026 (Oct 2025 – Sep 2026) is closed, and HST is filed
  annually. Hien Nguyen CPA's Jan–Sep review engagement has ended; FY2026 year-end scope
  is not yet agreed.
- **QBO has no A/P, by design** (Decision D2, Dext publishing off).
- **The 2026 P&L can't be used for margins** until the inventory count and COGS true-up
  are done.
- **33 Task Queue rows are open**, all added 07-15 → 07-20.
- **Hard deadline:** the HoldCo HST registration and the Mar–Jul rent invoices
  ($57,000) must exist before the HST return, around Dec 2026.

---

## Architecture

```
                         ┌── read door (Make) ── read calls only ──┐
 scheduled routines ─────┤   secret: QBO_READ_*  (all environments)│
 (daily-ingest, jobs)    │                                         ▼
                         │                                   QuickBooks Online CA
 write environment ──────┤                                         ▲
 (supervised sessions +  └── write door (Make) ── writes ──────────┘
  autonomous-rule routine)   secret: QBO_WRITE_*  (write env ONLY)
          ▲
          │ approval file  ◄── Notion "QBO Proposals" (Albert ticks)
          │                    FY2026 rows also need Hien's dated OK
   qbo-actions-agent  ──► actions-log.json (with before-image of every record)
```

- **Make stays thin.** Splitting by method is plumbing; every rule, job and threshold
  lives in this repo.
- **Read-only is structural on the read door.** The scenario has a literal GET, a path
  allowlist (`/query`, `/cdc`, `/reports/*`, `/companyinfo/*`, `/preferences`) and a
  secret check. A blueprint snapshot under `platform-settings/blueprints/` is pinned by
  `tests/test_bookkeeper.py`, the same pattern `tests/test_ghl_calls.py` uses for
  scenario 4951497.
- **The write door is pinned the same way**, and only `scripts/qbo_write.py` reads its
  secret.

### Daily read (`bookkeeper-ingest-agent` v2)

The v2 agent drops the "Intuit MCP connector" instruction and runs
`scripts/bookkeeper_pull.py` through `scripts/qbo_client.py` (read door only).

| type | Fires on |
|---|---|
| `closure_gap` | No Lightspeed sale posted to QBO in ≥ 3 days, or a sale posted after Oct 1 carrying a prior-year `TxnDate` (the #394/#441 problem). |
| `payment` | A/R payments received in the window. |
| `invoice` | Commercial A/R crossing overdue (`AgedReceivables`). |
| `expense` | A new Purchase over $500. |
| `flag` | Postings to a holding account (Uncategorized, Ask My Accountant, Suspense), to the dead "Product Sales" account, or payroll posted to 7788. |

**Metrics:**

| Metric | Meaning |
|---|---|
| `payments_received_cents` | A/R payments received in the window |
| `overdue_invoices` | Commercial invoices past due |
| `uncategorized_txns` | **Posted** holding-account lines, never the For Review queue |
| `days_since_last_closure` | Days since a Lightspeed closure last posted to QBO |
| `uf_balance_cents` | Undeposited Funds balance |

- An error file carries `metrics: {}`, never zeros.
- No margin metric until the inventory true-up is done.
- Sensitivity stays `private`.

---

## Build order

### Phase 0 — Albert

- Allow `hook.us1.make.com` in this environment.
- Create the write environment and allow the same host there.
- Triage the QBO-LS Task Queue.
- Agree Hien's FY2026 year-end scope.
- Put the HoldCo invoices on a dated track.

### Phase 1 — read door and daily read (before 2026-11-01)

1. **Make, on Albert's go.**
   - Build the read-door scenario, switched off until he has reviewed it.
   - Delete the TEMP scenarios.
   - Fix the watchdog query (rolling 3-day) and schedule it daily.
2. **Code.**
   - `scripts/qbo_client.py`, `scripts/bookkeeper_pull.py`, `tests/test_bookkeeper.py`.
   - Registry `platform-settings/bookkeeper.json`: account ids, thresholds, fiscal
     start = October.
   - `.env.example` gains `QBO_READ_URL` / `QBO_READ_SECRET`.
3. **Rules file.** Write `platform-settings/bookkeeper-rules.yaml` from three sources:
   the Fix Log, the rulebook .docx, and the bank-rules doc (moved here from
   `titan-bookkeeper`).
4. **Agent and docs.**
   - `bookkeeper-ingest-agent` v2.
   - Update the CLAUDE.md agent table, `departments.json` `blocked_reason`, and
     `methods/architecture.md` "Still open".

### Phase 2 — prove the read path

- **Three consecutive `bookkeeper: "ok"` days** in `run-ledger.json` → Finance
  un-blocked (`departments.json` rule, unchanged).
- **The month of receipt read-back starts**, read-only. It joins the receipt emails at
  info@ to what QBO has posted and reports what is unreviewed.
- **One week after the read door goes live**, delete the three old Bookkeeper scenarios.

### Phase 3 — write door, behind the gate

- **The write-door scenario.** Built on Albert's go, switched off until reviewed, and
  pinned by tests.
- **`qbo-actions-agent`.** It takes the action types and executes only ids that appear
  `approved` in the approval file. Before every update or delete it writes the record's
  previous state to the log.
- **Contract `contracts/bookkeeper-plan-schema.md`.** It covers the proposal, the
  approval file, the Hien batch fields, and the carve-outs as data.
- **A Notion "QBO Proposals" database** (private), and the step that turns ticked rows
  into the approval file.
- **The FY2026 batch file** for Hien. Approval of an FY2026 row requires her dated OK.
- **A CLAUDE.md "Agent class rules" exception** for `qbo-actions-agent`, dated, in the
  same shape as the catalogue's.

### Phase 4 — after the month

- Albert picks the first reconciliation: Lightspeed closures, or bank/card posted lines.
- Adapt the Receiptor skills, with the Canada/Ontario tax pack, under the vetting rules.

### Phase 5 — autonomy, rule by rule

- The 20-in-a-row counter, then Albert's dated vault decision per rule.
- A scheduled routine in the write environment runs only rules with a decision, and
  pushes a digest.
- The four carve-outs never qualify.

---

## Not planned

- No DataGrout, and no Composio or any other third-party broker holding QBO credentials.
- No automation of the For Review queue; the API cannot see it.
- No autonomy for deletes, tax codes, FY2026 or writes over $1,000, whatever the track
  record.
- No write to a reconciled transaction.
