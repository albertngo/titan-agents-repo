# Architecture Cheatsheet

How this repo is organized, what reads what, and where new work goes.
Written 2026-07-26. If this drifts from `CLAUDE.md`, `CLAUDE.md` wins.

---

## The three lanes

|  | **1. Ingest** | **2. Analysis** | **3. Decide & act** |
|---|---|---|---|
| Cadence | Daily, unattended | On demand, one-off | Per decision |
| Trigger | `/daily-ingest` | `/won-analysis` | `/manager-dashboard` → approval |
| Who works | subagents | Python script | `ghl-actions-agent` |
| Writes to | `ingest/<date>/` | `analysis/output/` + `ingest/analysis/` | `plans/<date>/`, `actions-log.json` |
| Governed by | `contracts/ingest-schema.md` | `methods/*-framework.md` | `contracts/plan-schema.md` |
| Re-runnable? | Yes — overwrites | Yes — cached | **No** — appends (audit trail) |

Flow is always **ingest → decide → act**. No agent does all three.

---

## Folder map

```
.claude/commands/     the trigger + the steps      "what to do"       (fixed path)
.claude/agents/       the workers                  "who does it"      (fixed path)
contracts/            output shape, binding        "what it must look like"
methods/              metric definitions, method   "what the numbers mean"
platform-settings/    mirror of live GHL settings  "what GHL is set to"
analysis/             heavy compute (Python)       "code too big for a prompt"
  ├─ cache/           raw API pulls                (gitignored — regenerable)
  └─ output/          machine artifacts            (COMMITTED — build phase)
ingest/               output of every run
  ├─ <date>/          daily contract output        (COMMITTED — build phase)
  ├─ SAMPLE/          reference structure, [FILL:] placeholders
  └─ analysis/        one-off reports + PII records
plans/<date>/         proposed actions + your approvals
```

The map is ordered roughly as you'd read it to understand the system — define
the shape, define the meaning, mirror the settings, write the code, produce
runs, plan actions. **That is reading order, not execution order.**
`contracts/`, `methods/`, and `platform-settings/` are reference material
consulted *during* a run, sometimes repeatedly, not steps that fire once each.

**`.claude/commands/` and `.claude/agents/` cannot be renamed or moved.** Claude
Code resolves slash commands and subagents from those exact paths. They are
conceptually steps 1 and 2, which is why they sit at the top of this map.

Two folder names are deliberate and worth keeping: `platform-settings/` (rather
than `config/`) says it **mirrors** an external system, so a stale value there is
a correctness bug, not a preference. `methods/` (rather than `docs/`) says it
holds **definitions**, not documentation.

### The four reference folders, disambiguated

| Folder | Answers | Binding? | Goes stale → |
|---|---|---|---|
| `contracts/` | "What shape must output take?" | Machine-checkable | Consumers break **loudly** |
| `methods/` | "What does this number mean, and why?" | Human judgment | Numbers stop being comparable |
| `platform-settings/` | "What is GHL set to right now?" | Tunable values | Findings look authoritative and are **wrong** |
| `.claude/agents/` | "How do I do the work?" | Prompt | Agent misbehaves |

**Rule of thumb when specing something new:** a threshold you might change next
month → `platform-settings/`. A definition you'd have to defend to your accountant →
`methods/`. A field another command will read → `contracts/`.

---

## What happens on `/daily-ingest`

```
/daily-ingest  (.claude/commands/daily-ingest.md)   ← the steps live HERE
  1. compute date (America/Toronto), mkdir ingest/<date>/
  2. spawn IN PARALLEL, resolved by `name:` frontmatter:
       ghl-ingest-agent ──┐
       outlook-ingest-agent ├─ each re-reads contracts/ingest-schema.md EVERY run
       bookkeeper-ingest-agent ┘  ghl also reads platform-settings/ghl-workflow.json
  3. each writes ONE file → ingest/<date>/<source>.json
  4. orchestrator reads every *.json in the day folder
  5. writes ingest/<date>/DAILY-BRIEF.md
```

**The invariant:** agents never talk to each other, they only leave files.
Step 4 reads step 3's *output*, never its conversation. That's why you can
re-run one ingester without touching the others.

**Commands don't always use agents.** Only `/daily-ingest` spawns any.
`/manager-dashboard` just reads files and prints. `/won-analysis` runs a script.

---

## Folder shape — date first, always

```
✅  ingest/2026-07-26/ghl.json
❌  ingest/ghl/2026-07-26.json
```

Three things depend on date-first:
- `/daily-ingest` step 4 reads **every** `*.json` in the day folder — that's what
  makes adding a source zero-config.
- `/manager-dashboard` walks `ingest/<D>/ghl.json` across 7 prior days for trends.
- `contracts/ingest-schema.md` states the path literally.

One day = one folder = everything that happened that day, side by side.
The folder is created for you on every run — don't hand-make it.

---

## Adding something new — decision tree

**1. Recurring daily, feeds the brief?**
→ New `*-ingest-agent` in `.claude/agents/`, conform to `ingest-schema.md`,
  add to the spawn list in `daily-ingest.md` + the table in `CLAUDE.md`. Done.

**2. One-off / periodic deep dive?**
→ New command in `.claude/commands/`. Then add only what you actually need:

| Add | Only when |
|---|---|
| `analysis/<name>.py` | It pages hundreds of API records (needs a cache) |
| `methods/<name>-framework.md` | A metric could reasonably be defined two ways |
| `contracts/<name>-schema.md` | Another command will read the output |
| `platform-settings/<name>.json` | It has thresholds that drift with the outside world |

A light analysis is **just the command file**. Four of the five are optional.

**3. Just reshaping files you already have?**
→ Command only. No agent, no script, no new storage. (`/manager-dashboard`.)

### Worked example — supplier margin analysis
```
.claude/commands/supplier-margin.md          the command you type
methods/supplier-margin-framework.md            what "margin" means, edge cases
analysis/supplier_margin.py                  pull + compute, caches to analysis/cache/
analysis/output/supplier_rows.csv            machine output
ingest/analysis/supplier-margin-<date>.md    the readable report
```

---

## Naming conventions

| Kind | Pattern | Example |
|---|---|---|
| Agent | `<thing>-agent` | `ghl-ingest-agent` |
| Command | plain, no suffix | `daily-ingest` → `/daily-ingest` |
| Contract | `<thing>-schema.md` | `ingest-schema.md` |
| Method doc | `<thing>-framework.md` | `ghl-analysis-framework.md` |
| Daily output | date **folder** | `ingest/2026-07-26/ghl.json` |
| One-off report | date **suffix** | `won-analysis-2026-07-26.md` |

Agent output filenames come from the **contract** (`source: "ghl"` → `ghl.json`),
not from the agent's name. Renaming an agent never changes its output.

---

## Hard rules

- Ingesters are **read-only** on every platform. Always.
- Ingesters write **only** their own `ingest/<date>/<source>.json`. Nowhere else.
- `*-actions` agents never originate actions — explicit instruction + per-batch
  approval, or nothing. Approval is never standing.
- One ingester failing must not block the others; it writes `status: "error"` and
  appears under "Sources missing today."
- Analysis must not write to `ingest/<date>/` — that namespace is the daily flow's.
- Counts come from `reporting`, never from counting `items` (50-item cap + rollup).
- Project pipeline and STORE pipeline are **separate businesses**. Never summed.
- Two tokens, two blast radii: read-only PIT for ingest, separate write PIT for
  actions. Never widen the read token.

---

## Gotchas

- **Stage names are byte-exact**, trailing spaces included (`"1b. Postponed "`,
  `"2. *Project Won* "`). Ingest emits them raw; **trim before comparing**.
- **`duration_days` ≠ `cycle_days`.** Lead age vs sales cycle. Differ by *months*
  for repeat customers. Always say which one a report used.
- **`value_cad` → `value_cents` is × 100.** Copying straight understates every
  deal 100-fold.
- **`visit_type` is classified two ways that can disagree** — the daily path reads
  `appt-home`/`appt-store` **tags**; the analysis script reads the `Visit:`/`Store:`
  **body prefix**. State which method produced a record.
- **`repeat_customer` is a judgment call**, not a GHL field (`> 30 days`, set by
  `REPEAT_GAP_DAYS` in the script). Changing it changes every repeat figure.
- **Meeting-stage threshold counts from stage entry, not the appointment.** An
  appointment booked far out eats the follow-up window.
- **`.mcp.json` reads env vars at startup**, not from `.env` on disk. Export first:
  `set -a && source .env && set +a && claude`

---

## Open items (as of 2026-07-26)

**Settled 2026-07-26 — public repo, committed corpus.** `ingest/<date>/`,
`ingest/analysis/`, and `analysis/output/` are all tracked so we accumulate real
runs to develop against, and the repo stays public. Customer PII is in git
history as a deliberate, accepted tradeoff for the build phase. `analysis/cache/`
remains ignored — it is a regenerable network cache, not analysis. **Revisit all
of this when the agents and contracts mature.**

Still open:
- **`outlook-ingest-agent` and `bookkeeper-ingest-agent` cannot run.** Their
  frontmatter `tools:` lists no MCP tools, so they can't reach any connector —
  they will write `status: "error"` every run regardless of credentials.
- **`planner-agent` and `vault-writer-agent` are parked.** Specs, not behavior.
  Un-parking criteria are at the bottom of each file.
