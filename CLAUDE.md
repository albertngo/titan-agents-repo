# Titan Agents

Multi-agent system for Titan Flooring, split into two agent classes:

- **`*-ingest` agents** — read-only. Pull from one platform each, normalize to the
  shared contract, write dated output files. Safe to run unattended on a schedule.
- **`*-actions` agents** — write. Execute explicit, pre-approved actions on a platform
  and append to the daily actions log. Never scheduled, never autonomous.

A daily orchestrator spawns the ingesters, reads their outputs, produces the daily
brief, then hands off to `vault-writer-agent` (vault) and `.claude/commands/notion-sync.md`
(Notion) — see Orchestration below.

## Architecture rule (do not break)

**Agents coordinate through data, not conversation.**
Every ingester writes to `/ingest/YYYY-MM-DD/<source>.json` conforming to
`contracts/ingest-schema.md`. The orchestrator only reads those files.
No ingester reads another ingester's raw platform data.

## Agents

| Agent | Source | Output file |
|---|---|---|
| `ghl-ingest-agent` | GoHighLevel (leads, SMS, pipeline) | `ghl.json` |
| `outlook-ingest-agent` | Outlook / M365 | `outlook.json` |
| `bookkeeper-ingest-agent` | QuickBooks / receipts | `bookkeeper.json` |
| `notion-ingest-agent` | Notion (projects, work orders, payments, meetings) | `notion.json` |
| `meta-ads-ingest-agent` | Meta Ads (spend, leads, CPL, delivery health) | `meta-ads.json` |

| `ghl-actions-agent` | GoHighLevel (write: replies, stages, tags) | appends to `actions-log.json` |
| `vault-writer-agent` | titan-vault Obsidian repo (write) | vault notes per its CONVENTIONS.md — runs automatically in `/daily-ingest`, bound to its whitelist. See Vault writes. |

`.claude/commands/notion-sync.md` runs automatically at the end of `/daily-ingest` too,
but is a command, not an agent — see Notion writes below for why.

Add a new agent = add one file in `.claude/agents/` + conform to the matching contract
(`ingest-schema.md` for ingesters, `actions-log-schema.md` for actions agents).
Nothing else changes.

## Agent class rules

| | `*-ingest` | `*-actions` |
|---|---|---|
| Platform access | Read-only, always | Write, whitelist of action types only |
| Trigger | Scheduled or manual | Explicit instruction + approval gate only |
| Autonomy | Decides what's noteworthy | Zero — executes exact instructions, never originates |
| Output | Overwrites `<source>.json` (idempotent) | Appends to `actions-log.json` (audit trail) |
| Failure mode | Writes `status: "error"`, never blocks siblings | Stops the batch, logs, reports |

The flow is always: **ingest → decide (Albert or orchestrator) → act**. No agent
does all three steps.

## Orchestration

Run `/daily-ingest` (see `.claude/commands/daily-ingest.md`).
It spawns each ingester as a subagent in parallel, waits, then synthesizes
`/ingest/YYYY-MM-DD/DAILY-BRIEF.md`. After the brief is written, it hands off to:

1. `vault-writer-agent` — writes/updates vault notes per its whitelist (Vault writes, below).
2. `.claude/commands/notion-sync.md` — auto-creates/updates team-visible GHL tasks in
   Notion, proposes-and-stops for anything private/sensitive (Notion writes, below).

Both run every time `/daily-ingest` runs, including unattended/scheduled runs. Neither
can affect `DAILY-BRIEF.md` — it's already written before either starts.

## Analyses

An analysis earns structure by being re-run, not by being interesting. The ladder:

| Tier | What exists | When |
|---|---|---|
| 0 — inline | Findings note in vault `09_analyses/YYYY-MM-DD-slug.md` + raw artifact in `analysis/output/` | Any one-off question. **Default.** |
| 1 — method + script | `methods/<slug>.md` + `analysis/<slug>.py` | Second time the same question is asked (rule of two), or first time if the pull needs caching |
| 2 — command | `.claude/commands/<slug>.md` wrapping the script | Re-run on demand AND has traps that must not be re-derived (field mappings, unit conversions, exclusion rules). Reference example: `won-analysis` |
| 3 — agent + contract | `.claude/agents/` + `contracts/` | Only when it joins the scheduled daily flow. High bar — `planner-agent` is parked at exactly this boundary |

Promotion triggers (any one suffices): asked twice; painful-to-get-right method;
output feeds other automation; expensive pull needing a cache. Not triggers:
"interesting," "might be useful later." Findings always land in the vault
regardless of tier; the repo holds data and method, the vault holds conclusions.

## Companion repo: titan-vault

The vault (`albertngo/titan-vault`) is a **separate repo**. A cloud session clones one
repo, so the vault is NOT present at session start — load it before any vault work:

1. `add_repo` — `albertngo/titan-vault`, `access: "push"` (use `"read"` when only reading).
2. Clone once, inline, generous timeout: `git clone --depth 1 <clone_url> /workspace/titan-vault`.
3. `register_repo_root` so the vault's `CONVENTIONS.md` loads into context.

## Vault writes

`vault-writer-agent` runs automatically at the end of `/daily-ingest` (**un-parked
2026-07-27**, on Albert's explicit instruction, ahead of its own originally-stated
"three clean sessions" bar — see the note in its definition). It may ONLY write in
the 5 whitelisted patterns there: daily note, entity-note Log appends, new entity
notes (ID-matched), decision notes on explicit record, platform notes on explicit
instruction. Anything else, it proposes and stops — same as a manual write always did.

The vault's `CONVENTIONS.md` still governs every write, automatic or manual:

- Append, don't rewrite. Prose above a note's `## Log` is Albert's.
- Never delete or rename a note. Never edit `goals/`. Never touch `.obsidian/`.
- **Visibility tagging** (CONVENTIONS v2.0, 2026-08-02): every note carries
  `visibility: staff | admin`; on staff-floor entity notes, admin-grade Log
  bullets carry a trailing `#admin`. Ingest `sensitivity` maps `team → staff`,
  `private → admin`; anything missing or unknown reads as admin. The vault
  CONVENTIONS Visibility section is canonical; the tag is advisory until a
  staff-facing export is built.
- Commit as `vault: <what> YYYY-MM-DD`. Vault commits go to `main-vault` (the vault
  repo's actual default branch, confirmed with Albert 2026-07-27) — no review step.
- **Push rule depends on where the session runs** (Albert, 2026-07-28):
  - **Albert's Mac** (vault at `~/Documents/claude/titan-vault`): the file edit
    itself is durable — the Obsidian git plugin auto-commits and pushes every
    ~10 min, sweeping up anything a session left uncommitted. Make the
    descriptive commit when git cooperates, but never block on it. Manual push
    only if `$VAULT_AUTOPUSH=true` (currently `false`).
  - **Cloud/VM session** (vault cloned to `/workspace/titan-vault`): the sandbox
    is ephemeral and there is no Obsidian to sweep up after you — **commit AND
    push are mandatory**, in the same step as the write. `$VAULT_AUTOPUSH` does
    not apply here; an unpushed vault commit in a VM is a lost write.
- **Earned relevance, not bulk import** (CONVENTIONS.md note rule 4 + "Scaling to
  more sources"): a vault note is created when something durable happens to an
  entity — a win, a `needs_attention` hit, an analysis touching it — never by a
  proactive bulk or windowed pull of a platform's history, GHL or otherwise. This is
  exactly why the whitelist excludes routine drift findings: most days, most GHL
  activity produces no vault write at all. Read that section before proposing any
  backfill.

**Ask Albert / propose-and-stop** for anything off-whitelist. Don't batch to the end
of a session, and never write outside the whitelist unprompted:

- An agent is added, or its definition/contract changes.
- A platform quirk, trap, or ID surfaces that `platforms/<Platform>.md` doesn't already have.
- An analysis produces findings worth keeping (e.g. the GHL win-timeline) →
  `09_analyses/YYYY-MM-DD-slug.md` per the vault's `templates/analysis.md`.
- A decision gets made → `decisions/YYYY-MM-DD-slug.md`.
- A contract in `contracts/` changes.

Checkpoint flow for off-whitelist writes: draft the change → show it in chat → Albert
approves → write → commit → push.

## Notion writes

`.claude/commands/notion-sync.md` runs automatically at the end of `/daily-ingest`
(wired in 2026-07-27, on Albert's explicit instruction). Governed by
`contracts/notion-task-schema.md`; all ids/property names/routing live in
`platform-settings/notion-destinations.json`, never hardcoded in the command.

Separately, `notion-ingest-agent` READS Notion daily (read-side registry:
`platform-settings/notion-ingest-sources.json`) — including the same Tactical
Tasks List this sync writes to. That coexistence is deliberate: the ingester is
strictly read-only and excludes rows the sync created the same day.

Two destinations, different trust levels:

- **Team** — the shared "✅ Tactical Tasks List" (Titan Flooring HQ teamspace).
  Auto-write: high-priority GHL findings become task rows, deduped by an exact
  match on a constructed contact-detail URL (never `item.id` — see the contract for
  why that's not cross-day stable). Rows are always created unassigned and
  `Verification: Needs Verification` — the sync never assigns a person or a due date.
- **Private** — Albert's personal "to-do" database (to-do list (personal), PERSONAL
  section). Always approval-gated: candidates are proposed in chat with their routing
  reason, written only on explicit yes. Bookkeeper/Outlook findings default here;
  a GHL item can escalate `team → private` via its own `sensitivity` field, never
  the reverse.

Every write is logged to `actions-log.json` per `contracts/actions-log-schema.md`
(`notion_create_task` / `notion_update_task`). A Notion outage never blocks or
retroactively affects `DAILY-BRIEF.md` — the sync runs after the brief is already
written.

## Failure policy

- One ingester failing must NOT block the others or the brief.
- A failed source appears in the brief under "Sources missing today" — never silently omitted.
- Ingesters write `status: "error"` records rather than crashing when a platform is unreachable.

## Conventions

- Dates: `YYYY-MM-DD`, timezone America/Toronto.
- Money: cents as integers, CAD unless stated.
- Brand color for any rendered output: RiderBlue #1e6fff.
- Response style for briefs: terse, PARA (Point, Action, Result, Ask) where a decision is needed.

## Git workflow

`main-agents` is this repo's actual default branch on GitHub (verify with
`gh repo view --json defaultBranchRef` if unsure — don't trust a stale session
hint). `main` is a separate, older branch that predates active work here; treat
it as legacy, not the PR target.

Work on a session-named branch off `main-agents` (e.g. `session/2026-07-27-notion-sync`),
open the PR against `main-agents`, merge there. Decided 2026-07-27 after a PR
was accidentally opened against `main` instead.

**Exception — `ingest/` commits go straight to `main-agents`, no PR** (Albert,
2026-08-23). Ingest output is data, not code; review adds nothing and demonstrably
lost eight days (2026-08-15 through 2026-08-22 sat complete on eight unmerged
branches while every brief reported them as "no run at all"). `daily-ingest` step 6
commits and pushes them as part of the run. Everything else — agents, commands,
contracts, scripts — still goes through a session branch and a PR.

## Secrets

No secrets in this repo. See `.env.example` for what each environment must provide.
Cloud environment env vars are not a secrets store — treat anything there as visible.
