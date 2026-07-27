# Titan Agents

Multi-agent system for Titan Flooring, split into two agent classes:

- **`*-ingest` agents** — read-only. Pull from one platform each, normalize to the
  shared contract, write dated output files. Safe to run unattended on a schedule.
- **`*-actions` agents** — write. Execute explicit, pre-approved actions on a platform
  and append to the daily actions log. Never scheduled, never autonomous.

A daily orchestrator spawns the ingesters, reads their outputs, and produces the daily brief.

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

| `ghl-actions-agent` | GoHighLevel (write: replies, stages, tags) | appends to `actions-log.json` |
| `vault-writer-agent` | titan-vault Obsidian repo (write) | vault notes per its CONVENTIONS.md — **parked, see Vault writes** |

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
`/ingest/YYYY-MM-DD/DAILY-BRIEF.md`.

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

## Vault writes (build phase)

`vault-writer-agent` is **parked** — see the note in its definition. Spec it once the agent
architecture and the ingest contracts have settled; its whitelist is a list of folders
and contracts, so writing it against a moving target means rewriting it every time one
of them changes.

Until then Claude writes to the vault directly, one change at a time, with Albert's
go-ahead on each. The vault's `CONVENTIONS.md` still governs every write:

- Append, don't rewrite. Prose above a note's `## Log` is Albert's.
- Never delete or rename a note. Never edit `goals/`. Never touch `.obsidian/`.
- Commit as `vault: <what> YYYY-MM-DD`. Vault commits go to `main` — no review step.

**Ask Albert to push to the vault** when any of these happen. Don't batch them to the
end of a session, and never write to the vault unprompted:

- An agent is added, or its definition/contract changes.
- A platform quirk, trap, or ID surfaces that `platforms/<Platform>.md` doesn't already have.
- An analysis produces findings worth keeping (e.g. the GHL win-timeline) →
  `09_analyses/YYYY-MM-DD-slug.md` per the vault's `templates/analysis.md`.
- A decision gets made → `decisions/YYYY-MM-DD-slug.md`.
- A contract in `contracts/` changes.

Checkpoint flow: draft the change → show it in chat → Albert approves → write →
commit → push.

## Failure policy

- One ingester failing must NOT block the others or the brief.
- A failed source appears in the brief under "Sources missing today" — never silently omitted.
- Ingesters write `status: "error"` records rather than crashing when a platform is unreachable.

## Conventions

- Dates: `YYYY-MM-DD`, timezone America/Toronto.
- Money: cents as integers, CAD unless stated.
- Brand color for any rendered output: RiderBlue #1e6fff.
- Response style for briefs: terse, PARA (Point, Action, Result, Ask) where a decision is needed.

## Secrets

No secrets in this repo. See `.env.example` for what each environment must provide.
Cloud environment env vars are not a secrets store — treat anything there as visible.
