# Titan Agents

Multi-agent system for Titan Flooring. This file holds the rules every session needs.
The detail, history and reasons behind them are in **`methods/system-reference.md`** (the
full CLAUDE.md as it stood on 2026-10-30). **Read the matching section there before you
change a pipeline, an agent, a contract, a registry policy or a write mode.** Older files
that cite "CLAUDE.md, <section>" mean that file's section of the same name.

## Architecture rule (do not break)

**Agents coordinate through data, not conversation.** Every ingester writes
`/ingest/YYYY-MM-DD/<source>.json` conforming to `contracts/ingest-schema.md`. The
orchestrator only reads those files. No ingester reads another ingester's raw platform data.

The flow is always **ingest → decide → act**. No agent does all three steps.

## Agents

| Agent | Source | Output file |
|---|---|---|
| `ghl-ingest-agent` | GoHighLevel (leads, SMS, pipeline, call transcripts) | `ghl.json` |
| `outlook-ingest-agent` | Outlook / M365 | `outlook.json` |
| `bookkeeper-ingest-agent` | QuickBooks / receipts | `bookkeeper.json` |
| `notion-ingest-agent` | Notion (projects, work orders, payments, meetings) | `notion.json` |
| `meta-ads-ingest-agent` | Meta Ads (spend, leads, CPL, delivery health) | `meta-ads.json` |
| `content-ingest-agent` | Notion content calendar + Google Drive media | `content.json` |
| `wechat-ingest-agent` | WeChat, via the private WeChat Archive in Notion | `wechat.json` |
| `whatsapp-ingest-agent` | WhatsApp via 2Chat (business + personal numbers) | `whatsapp.json` |

| Actions agent | May write | Output |
|---|---|---|
| `ghl-actions-agent` | GoHighLevel: replies, stages, tags; mark-read only via `/ghl-triage` | appends to `actions-log.json` |
| `lightspeed-actions-agent` | Lightspeed Retail X-Series: product create/update ONLY | appends to `actions-log.json` |
| `airtable-actions-agent` | Airtable catalogue: upsert, LS-ID backfill, price history, blank-only style tags and images | appends to `actions-log.json` |
| `social-actions-agent` | Metricool: schedule posts, move a still-scheduled one. Never edits or deletes a live post, never replies | appends to `actions-log.json` |
| `vault-writer-agent` | titan-vault, bound to its whitelist (see Vault) | vault notes |

Adding an agent means one file in `.claude/agents/` that conforms to the matching contract
(`ingest-schema.md` or `actions-log-schema.md`), plus a row above. Nothing else changes.

## Agent class rules

| | `*-ingest` | `*-actions` |
|---|---|---|
| Platform access | Read-only, always | Write, whitelist of action types only |
| Trigger | Scheduled or manual | Explicit instruction + approval gate only |
| Autonomy | Decides what's noteworthy | Zero — executes exact instructions, never originates |
| Output | Overwrites `<source>.json` (idempotent) | Appends to `actions-log.json` (audit trail) |
| Failure mode | Writes `status: "error"`, never blocks siblings | Stops the batch, logs, reports |

A third class, `*-lead`, is the decide step: `tools: Read, Write` only, reads contract
files, writes exactly one plan, originates no platform write.

**The approval gate.** An `*-actions` agent executes only an id that appears `approved` in
an approval file, and never originates a write. A person's yes always satisfies it. Policy
satisfies it only in these dated exceptions:

- **Catalogue (2026-09-11, widened 2026-09-12, Albert).** `lightspeed-actions-agent` and
  `airtable-actions-agent`, via `/catalog-sync` only, under "Policy auto-approval" in
  `contracts/catalog-plan-schema.md`. Three carve-outs are always held: `blocked` entries,
  rows flagged `Ambiguous Pricing`, and every action on a plan whose `cost_basis` is `null`.
  `/style-tag` and `/image-fill` use the same policy shape for `airtable-actions-agent`,
  each behind its own registry `write_mode`.
- **Second narrow exception (2026-10-10, Albert).** `ghl-actions-agent` may execute a
  policy-approved `mark_conversation_read` — that type only, via `/ghl-triage` only, through
  `scripts/ghl_mark_read.py` only, on an approval file `scripts/ghl_unread_plan.py` wrote
  that run. At most 25 per run, all-or-nothing. Vault
  `05_decisions/2026-10-10-ghl-triage-write-mode.md`.

Every other action (GHL replies, stages, tags; social posts; private Notion tasks) needs a
person's approval, always. Flipping a `write_mode` or a policy switch is a dated vault
decision, never an edit made to get a run through.

## Files that can write to a platform

- **Lightspeed:** only `scripts/lightspeed_write.py` and `scripts/lightspeed_push.py`. The
  read path has no write verb, and a test enforces it. Deactivating or deleting a product
  is a person's call only; policy can never approve a delete.
- **GHL, from this repo:** only `scripts/ghl_mark_read.py`, and it does one thing
  (`PUT /conversations/<id>` `{locationId, unreadCount: 0}`). Make writes GHL outside the
  gate (call notes and comments, scenario 4951497; Website Inquiry Ingester; Stage
  scenarios). Do not edit 4951497 in Make without re-snapshotting it and re-running
  `tests/test_ghl_calls.py`.
- **WeChat Archive (Notion):** only `scripts/wechat_archive.py`, insert-only, on Albert's Mac.

**The repo is public.** No customer text, phone numbers, prices, costs or account numbers
in committed files (ingest outputs, logs, registries).

## Workflows

Each flow's procedure lives in its command or method file. Read it before running or
changing the flow.

| Flow | Entry point | Read first |
|---|---|---|
| Daily brief | `/daily-ingest` | `.claude/commands/daily-ingest.md` |
| Price lists | Make 4381438 → `/process-price-list` → `/catalog-sync`; daily `/price-list-sweep` (with promo lane) | `.claude/commands/catalog-sync.md`, `methods/pricelist-pipeline-routine-prompt.md` |
| Style tags | `/style-tag <SUPPLIER>` | `methods/style-tags.md` |
| Product images | `/image-fill <SUPPLIER>` | `methods/image-fill.md` |
| GHL unread triage | `/ghl-triage` (hourly routine) | `methods/ghl-unread-triage.md` |
| Call transcripts | `ghl-ingest-agent` step 0, `scripts/ghl_calls_pull.py` | `methods/ghl-call-transcripts.md` |
| WeChat | `scripts/wechat_archive.py` (Mac) → `wechat-ingest-agent` | `methods/wechat-archive.md` |
| Content | `/content-schedule`, `/content-sweep`, `/content-feedback` | those command files |
| Departments | `/route` | `methods/departments.md` |

Rules from those flows that a session could break without opening the file:

- **Catalogue.** Lightspeed is written before Airtable (the create mints the UUID). An
  `Action` cell in the troubled report is prose, never an approval, and cannot clear a
  pricing carve-out. A list whose `Effective Date` is after today is staged: extract, write
  nothing, and the sweep applies it on the day. `Effective Date` is the price-list date.
  Ids live in `platform-settings/`, never in a prompt. The "New Price Lists" routine is
  enabled (2026-09-27); never disable it or change its schedule on a session's own initiative.
- **Style tags.** Never touch a record whose `Style tags status` is `Staff confirmed`; never
  write `Staff confirmed`; colour tags come from `Swatch images` only, and no swatch means hold.
- **Images.** Sources in order: official site, then The Floor Box and Word of Mouth Floors,
  then Speers. `Supplier product page` is never Speers. A bot challenge is reported, never
  worked around.
- **GHL triage.** The log branch **`claude/ghl-triage-log`** is never merged or PR'd; only
  `scripts/ghl_triage_log.py` pushes to it. `NEEDS_RESPONSE`, `ACTION` and `FYI` are never
  marked read.
- **Content.** Notion is the source of truth for `Post Date`; a reschedule is a proposal
  through the plan and approval file. `/content-sweep` is not wired into `/daily-ingest`
  (Albert's call).
- **Departments.** Ownership keys on source, never platform (`platform-settings/departments.json`).
  A lead's `dispatch[]` names only read-only specialists. No cross-department ranking. A
  `private` item is never returned to a `staff`-tier requester.

## Orchestration

`/daily-ingest` spawns every ingester in parallel, waits, writes
`/ingest/YYYY-MM-DD/DAILY-BRIEF.md`, then hands off to `vault-writer-agent` and
`.claude/commands/notion-sync.md`. Both run every time, unattended runs included, and
neither can affect the brief. The catalogue pipeline, the departments layer and every other
flow are separate and never touch the brief.

## Analyses

Structure is earned by re-runs: one-off → vault `09_analyses/` note + raw output in
`analysis/output/` (default); asked twice → `methods/<slug>.md` + `analysis/<slug>.py`;
re-run with traps → a command (`won-analysis` is the example); agent + contract only when it
joins the daily flow. Findings always land in the vault.

## Vault (albertngo/titan-vault, branch `main-vault`)

- **Load it:** use an attached checkout (`git pull` on `main-vault`); otherwise `add_repo`
  (`access: "push"`, or `"read"`), `git clone --depth 1 <clone_url> /workspace/titan-vault`,
  `register_repo_root`.
- **Read before designing a build:** `04_goals/`, recent `05_decisions/` and `09_analyses/`,
  and the notes on what the build touches. Name them, and flag any contradiction.
- **The vault's `CONVENTIONS.md` governs every write.** `vault-writer-agent` writes only its
  whitelist. Anything else is propose-and-stop: draft → show Albert → he approves → write →
  commit → push. That covers: an agent or contract change, a platform quirk, analysis
  findings, a decision (with `serves:`), and any vault note a repo file cites (write it in
  the same session).
- Commit `vault: <what> YYYY-MM-DD` to `main-vault`. In a cloud session, commit **and push**
  in the same step. If only a session branch can be pushed, open a PR into `main-vault` and
  say so.
- Earned relevance: never bulk-import a platform's history into the vault.
- Run **`/wrap-up`** before ending a session that built, decided or analysed something.

## Notion writes

`notion-sync` (end of `/daily-ingest`) auto-writes team-visible GHL findings to the Tactical
Tasks List: unassigned, `Needs Verification`, deduped on the contact-detail URL. Albert's
private to-do database is always propose-and-wait. Contract `contracts/notion-task-schema.md`;
ids in `platform-settings/notion-destinations.json`; every write logged to `actions-log.json`.

## Failure policy

- One ingester failing must NOT block the others or the brief.
- A failed source appears in the brief under "Sources missing today", never silently omitted.
- Ingesters write `status: "error"` records rather than crashing.

## Conventions

- Dates `YYYY-MM-DD`, timezone America/Toronto. Money in integer cents, CAD unless stated.
- Brand colour for rendered output: RiderBlue #1e6fff.
- Briefs: terse, PARA (Point, Action, Result, Ask) where a decision is needed.

## Git workflow

`main-agents` is the default branch and the PR target; `main` is legacy. Work on a session
branch, open the PR against `main-agents`. Exception: `claude/ghl-triage-log` (above).

## Secrets

No secrets in this repo; `.env.example` lists what each environment must provide.
Credentials must come from `.env`, never a same-named cloud env var directly. In cloud
sessions `.claude/hooks/session-start.sh` copies documented keys from the environment into
`.env` without overwriting. If a credential is still missing after that, report the
variable name and stop.
