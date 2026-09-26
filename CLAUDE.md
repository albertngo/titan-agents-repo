# Titan Agents

Multi-agent system for Titan Flooring, split into two agent classes:

- **`*-ingest` agents** — read-only. Pull from one platform each, normalize to the
  shared contract, write dated output files. Safe to run unattended on a schedule.
- **`*-actions` agents** — write. Execute explicit, pre-approved actions on a platform
  and append to the daily actions log. Never scheduled, never autonomous — except a
  narrow, dated 2026-09-11 exception for `lightspeed-actions-agent` and
  `airtable-actions-agent` via `/catalog-sync`'s policy auto-approval; see Agent class
  rules below.

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
| `content-ingest-agent` | Notion content calendar + Google Drive media | `content.json` |

| `ghl-actions-agent` | GoHighLevel (write: replies, stages, tags) | appends to `actions-log.json` |
| `lightspeed-actions-agent` | Lightspeed Retail X-Series (write: product create/update ONLY) | appends to `actions-log.json` |
| `airtable-actions-agent` | Airtable catalogue (write: upsert, LS-ID backfill, price history) | appends to `actions-log.json` |
| `social-actions-agent` | Metricool (write: schedule posts, and move a still-scheduled one to a new date — never edits or deletes a LIVE post, never replies) | appends to `actions-log.json` |
| `vault-writer-agent` | titan-vault Obsidian repo (write) | vault notes per its CONVENTIONS.md — runs automatically in `/daily-ingest`, bound to its whitelist. See Vault writes. |

`.claude/commands/notion-sync.md` runs automatically at the end of `/daily-ingest` too,
but is a command, not an agent — see Notion writes below for why.

### The price-list / catalogue pipeline

Not part of `/daily-ingest`. Triggered per price list, and it is the only flow that
writes to two platforms:

```
Make 4381438  ->  Notion Price Lists row  ->  /process-price-list  (produces 2 CSVs, commits them, writes no platform)
                                                     |
                                   /catalog-sync <notionID>  — steps 1-6, same session
                                                     |
              scripts/lightspeed_pull.py  ------>  scripts/catalog_reconcile.py
              (read-only catalogue pull)          (one reviewable diff, writes no platform)
                                                     |
                      [ policy auto-approves what qualifies; a person approves the rest ]
                                                     |
                      lightspeed-actions-agent  +  airtable-actions-agent
```

**`/catalog-sync` is the entry point** (`.claude/commands/catalog-sync.md` — the
authoritative procedure; `methods/pricelist-pipeline-routine-prompt.md` holds the
merged routine's stored text and its rationale).

**`/catalog-sync` runs all six steps in one unattended session (2026-09-11, widened
2026-09-12 — both Albert), immediately after `/process-price-list` on the same
notionID.** Policy approves and executes everything except three carve-outs in
`contracts/catalog-plan-schema.md` ("Policy auto-approval"):

1. `blocked` entries — structural; no `id` exists to approve.
2. Rows flagged `Ambiguous Pricing`.
3. Every action on a plan whose `cost_basis` is `null`.

`New Supplier` no longer holds a write (2026-09-12, reversing the previous day's
rule). Neither do `Ambiguous Naming`, `Unmapped Grade`, `Unmapped Category` or
`Spec Gap` — those write and are reported. The two pricing carve-outs remain because
a wrong cost is the one error that is silent *and* monetary: it doesn't look broken,
it just sells at the wrong margin, and a later correction doesn't recover the
difference.

`*-actions` agents still execute **only** an id that appears `approved` in the
approval file; what changed is who writes that file.

**The human checkpoint is now a report, not a gate.** Everything held, plus
everything written carrying a flag, lands in a per-SKU CSV
(`contracts/troubled-skus-schema.md`) attached to the row's **`Troubled Files`**
property, with a mandatory PushNotification behind it.
`Troubled Files is not empty` is the worklist. This is a deliberately weaker control
than stopping — a wrong spec can go live and be found after — and that trade is
recorded in `methods/pricelist-pipeline-routine-prompt.md` rather than left implicit.

**The report answers back (2026-09-21, Albert).** The CSV carries a twelfth column,
`Action`, and the run renders the same rows as a table in the Notion page body —
a file property cannot be edited in place, so that table is where a reviewer replies.
`/catalog-sync` step 0 reads those cells back before it plans, and step 6a carries
them across the overwrite. **An `Action` cell is prose, never an approval**: it can
resolve an ambiguity, but the resulting id still has to appear `approved` in the
approval file, and it cannot clear either pricing carve-out — a cost decision belongs
in bert-airtable-schema's `#### Cost column`, where the next run reads it. Albert
invented this column by hand on PL-377 before it existed anywhere in the repo.

**Lightspeed is written before Airtable** — the reverse of `forced_downstream_order` in
`pricelist-sources.json`, which describes the manual CSV flow. `POST /api/2.0/products`
returns the new UUID, so the Lightspeed create is what mints the id the Airtable write
needs.

Contracts: `catalog-plan-schema.md` (the diff and the approval file),
`actions-log-schema.md` (every write). Ids live in `platform-settings/lightspeed.json`,
`airtable-destinations.json` and `pricelist-sources.json` — never in a prompt.

The Notion row carries the state. `Extraction Status` says *that* a human must look;
**`Review Reason`** (multi-select) says *why* — `New Supplier`, `Ambiguous Pricing`,
`Ambiguous Naming`, `Unmapped Category`, `Unmapped Grade`, `Spec Gap` — written
additively by both runs and cleared only by the reviewer. `Airtable Sync`, `LS Upload`
and `UUID Backfill` are stage indicators for **whoever ran the stage**: the manual CSV
path stays available and writes the same fields the sync does.

**Not every attachment is a price list (2026-09-11, Albert).** Stage 1 no longer just
stops on a non-price-list file. If it has real content (a catalogue, spec sheet,
marketing material), Stage 1 tags it freely — a gray, open-ended tag, never `Regular
List`/`Promo` — and records what it shows about the company in
`platform-settings/company-profiles.md`, the repo's new memory of what each company
sells beyond its price lists. If it has no content at all (a bare logo, a blank
file), and only on an untouched row, Stage 1 may archive the Notion page —
Notion's own reversible soft-delete, never anything harder, and always reported.
Full procedure: `methods/pricelist-extraction.md`, "When the file is not a price
list at all."

**The human gate became a human report (2026-09-12, Albert — superseding both
same-day-2026-09-11 notes above and below this one).** Policy clears everything but
the three carve-outs; what it holds is reported per SKU in `Troubled Files` and
pushed, not queued behind a stop. `/catalog-sync` step 3a still exists for clearing
that residue in one reply, but on an unattended run it is a digest, not a wait.
Nothing changed about an action needing an id in the approval file before an
`*-actions` agent touches it.

> **⚠️ Scheduling status (2026-09-23).** The policy path has now run on real plans:
> FAW PL-377 and PL-380, and IMPRESSIVE PL-381 (unattended on 09-22, finished by hand
> on 09-23). **No unattended fire has yet completed both systems on one row.** The
> routine trigger is **disabled, and stays that way** (Albert, 2026-09-23: "Not yet.
> I'll do manual"). Make keeps creating rows, and price lists are run by hand. Do not
> re-enable it on a session's own initiative. Detail:
> `methods/pricelist-pipeline-routine-prompt.md`, Routine environment and Still open.

**Only two files can change the POS**: `scripts/lightspeed_write.py` and
`scripts/lightspeed_push.py` (the promo lane's planner, `promo_sweep.py`, only writes a plan). The read path contains no write verb and a test
enforces that. Removing a product the supplier's newest list no longer carries is a person's call only
(Albert, 2026-09-24): **deactivate** is an ordinary update of Lightspeed `is_active` / Airtable `Active` that the
reconciler never plans, and a guarded **delete** exists that policy can never approve. First use: FAW's old T&G
Toffee / Warm Honey, set inactive, not deleted.

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

**"Explicit instruction + approval gate only" (2026-09-11 exception, Albert, widened
2026-09-12):** for `lightspeed-actions-agent` and `airtable-actions-agent`
specifically, invoked only via `/catalog-sync`, "approval" now includes the policy
auto-approval in `contracts/catalog-plan-schema.md` as well as a person's yes — and
since 2026-09-12 that policy clears everything but three carve-outs, so in practice
most catalogue writes now happen with no person in the loop at all. The gate itself —
an actions agent executes only an id that appears `approved` in an approval file,
never originates a write on its own — did not move; only who satisfies it. Every
other `*-actions` agent (`ghl-actions-agent` included) is unchanged: explicit
instruction and a person's approval, still, always.

The flow is always: **ingest → decide (Albert, a department lead, policy for the
narrow catalogue slice above, or the orchestrator) → act**. No agent does all three
steps.

A third class, `*-lead`, occupies the decide step: read-only against contract
files (`tools: Read, Write`, no `Bash`, no `mcp__*`), writes exactly one plan,
originates no platform write. See Departments below.

## Orchestration

Run `/daily-ingest` (see `.claude/commands/daily-ingest.md`).
It spawns each ingester as a subagent in parallel, waits, then synthesizes
`/ingest/YYYY-MM-DD/DAILY-BRIEF.md`. After the brief is written, it hands off to:

1. `vault-writer-agent` — writes/updates vault notes per its whitelist (Vault writes, below).
2. `.claude/commands/notion-sync.md` — auto-creates/updates team-visible GHL tasks in
   Notion, proposes-and-stops for anything private/sensitive (Notion writes, below).

Both run every time `/daily-ingest` runs, including unattended/scheduled runs. Neither
can affect `DAILY-BRIEF.md` — it's already written before either starts.

**The catalogue pipeline is separate and has its own routine** — not part of
`/daily-ingest`, and it never touches the brief.

**One routine, one shape, always keyed on a notionID** (re-merged 2026-09-11, Albert —
collapses what was briefly "two stages branching on the fire payload" into a single
continuous run per row):

Every fire carries `{"notionID": …}` (Make 4381438, the moment a new price list
lands). One session, in order, on that one row:

1. **Extract.** Runs `/process-price-list`. Downloads the PDF, assigns `Company` and
   `Tags`, extracts against the live Airtable catalogue, produces and **commits** the
   two upload CSVs to `ingest/YYYY-MM-DD/`, attaches them to the row, sets
   `Extraction Status` to `Extracted [Needs Review]` (or `[Error]`). Writes no
   platform.
2. **Check the effective date (2026-09-25).** If the row's `Effective Date` is after
   today the list is staged: no sync now; the routine's scheduled sweep runs it on
   the day. Otherwise go on.
3. **Sync, same session.** Runs `/catalog-sync` on the same notionID,
   reading the CSVs the previous step just committed — never a Notion re-download,
   which is why the commit in step 1 is load-bearing now, not just tidy. Pulls
   Lightspeed, reconciles, produces the plan, then applies policy auto-approval
   (`contracts/catalog-plan-schema.md`) and writes everything but the three
   carve-outs. Held rows and flagged writes go to the troubled CSV on `Troubled
   Files`, and the run pushes a notification naming the counts.

`Extracted [Ready to Upload]` is no longer a precondition this routine waits for —
sync no longer waits on Albert manually promoting a row before it runs. The status
still exists for the manual CSV path (whoever runs a stage by hand still uses it),
per "all three trackers are kept" below.

**Lists received before they take effect are staged (2026-09-25, Albert).** The row's
`Effective Date` (Notion) is the list's date; when it is after today, extraction runs
but `/catalog-sync` writes nothing and `catalog_reconcile.py` blocks every row
`not_yet_effective`. `/price-list-sweep` applies due lists on the day, against a fresh
pull. Staged = `Effective Date` in the future with `Airtable Sync: Pending`. The sweep
is the "New Price Lists" routine's **scheduled** fire: a fire with a `notionID` extracts
that row, a fire without one sweeps (Albert, 2026-09-25 — one routine, not two). The
sweep runs each row's next skill: `Ready to Upload` (a person answered) → sync;
`Effective Date` arrived → sync; a `Not started` row from the last 14 days the webhook
missed → extract + sync. At most 5 rows a morning; held `Partial` rows, errors and the
older backlog wait for a person. `/catalog-sync` refuses a list older than one already
applied for the same company.

**Promos come and go in Lightspeed with the sweep (2026-09-26, Albert).** Every
`/price-list-sweep` runs a promo lane (`scripts/promo_sweep.py`): from Airtable's
`Promo cost` / `Promo end date` — kept forever, never cleared — it puts the
`(P YYYY-MM-DD)` name prefix and the promo cost on a standalone Lightspeed product
while the promo runs and takes both off the morning after it ends. A verbal extension
is one Airtable edit (move the end date). **Every promo has an end date** (2026-09-26):
printed, else the last day of its Promo row's month, else of its list's month — the
earlier when unsure; an undated one counts as over. Policy approves a morning of ≤50 changes;
more waits for a person. The report lists promos ended in the last 14 days with their
`Promo List URL` ("ask the rep"). Variant members get the price only; no `PROMO` tag.

**A periodic no-`notionID` sweep can still exist as a backstop**, not the primary
path: it would pick up any row where `Airtable Sync` is still `Pending`/`Partial`
after its own fire should have cleared it (an interrupted run, a Lightspeed outage
mid-session) and re-run `/catalog-sync` on it. Not wired up as of this edit — add it
only if rows are actually observed getting stuck, not preemptively.

Canonical text: `methods/pricelist-pipeline-routine-prompt.md`. It stores a *pointer*
to `/process-price-list` and `/catalog-sync` rather than a copy of either procedure —
same reason as always: on 2026-09-03 the (then-separate) extraction routine fired
carrying a procedure that had gone stale on 09-01 and reported success against an
instruction set missing five of its seven steps. A pointer has nothing in it to fall
behind. The predecessor files (`methods/pricelist-routine-prompt.md`,
`methods/catalog-sync-routine-prompt.md`) are superseded but kept for their
changelogs.

## Departments

A third layer sits between ingest and act: `/route` takes a request from wherever
it arrives, decides which department owns it, and spawns that department's lead.
The lead reads its own sources and writes ONE plan — it proposes, it never
executes. Full shape in `methods/departments.md`; ownership is data in
`platform-settings/departments.json`.

| Department | Owns | Lead | Status |
|---|---|---|---|
| Sales | `ghl` | `planner-agent` | active — the reference build |
| Operations | `notion` (5 sub-sources) | — | spec: source live, no rule table yet |
| Catalogue | Airtable · Lightspeed · price lists | `/catalog-sync` | active — complete before this layer existed |
| Marketing | `meta-ads` · `content` | `/content-schedule` | active — content posting built (draft mode), never run end to end; ad reporting still needs a framework doc |
| Finance | `bookkeeper` | — | **blocked — the source has never worked** |
| General | `outlook` | — (`/route` answers inline) | active — the fallback lane |

**A lead cannot spawn a subagent** (harness constraint), so it names specialists
in its plan's `dispatch[]` and `/route` runs them. `dispatch[]` may name only
read-only specialists; an `*-actions` agent is reachable solely through an
approval file naming exact action ids — enforced by
`tests/test_departments_registry.py` and by `contracts/dept-plan-schema.md`.

**Ownership keys on source, never platform.** `owns.sources[]` must be a
partition of the ingest sources in the table above: owned twice routes
non-deterministically, owned by nobody falls silently to General.

**A department is not a sensitivity boundary** — provenance decides (Albert,
2026-08-02). The layer adds no routing axis; the one new rule is a filter, that a
`private` item is never returned to a `staff`-tier requester
(`platform-settings/requesters.json`).

**Cross-department ranking is banned.** Plans render side by side in the
registry's `escalation_order`; there is no company-wide priority number, for the
same reason project and STORE pipelines are never summed.

`/daily-ingest` is unchanged and stays that way — the layer is additive, and a
department failing must never touch `DAILY-BRIEF.md`.

**The content pipeline needs a daily `/content-sweep`** (`.claude/commands/content-sweep.md`).
`getScheduledPosts` returns only posts that have NOT published, so a post leaves the
one endpoint this repo queries at the moment it succeeds — nothing else can ever set
`Post Status = Posted`, and without the sweep every row sits at `Scheduled`
permanently. It infers publication from a uuid's absence, which is ambiguous, so it
demands absence **and** a passed due time **and** a wide enough query window **and**
`write_mode.mode` not being `draft` before writing `Posted`. In draft mode it marks
nothing posted at all — a draft does not publish, so a vanished one was deleted by a
person. **Not wired into `/daily-ingest`**: that would add a platform write to the
orchestrator, which is Albert's call, so it runs by hand for now.

**Publication is then CONFIRMED against analytics, not inferred** (2026-09-14).
`scripts/social_publish_reconcile.py` matches each candidate to a real published post
via `getAnalyticsDataByMetrics`, which is also the only source for `Live URL`,
`Posted Caption` and `Posted At` — a published post is gone from `getScheduledPosts`
entirely. Per-surface metric ids are data in `social-destinations.json` → `analytics`,
captured live. Three things that are limits rather than gaps: YouTube exposes a title
and no description, so `Posted Caption` stays blank there; Google Business Profile
exposes no permalink, so `Live URL` stays blank there; and the join is by surface and
time-proximity, not by id, because Metricool's planner uuid and a network's own post id
never map to each other. Two candidates in one window are refused, never guessed.

**Notion is the source of truth for `Post Date`** (Albert, 2026-09-14). Drift between
the two systems is therefore resolvable, and the sweep emits a `social_reschedule_post`
**proposal** — which still goes through the plan, approval file and actions log like any
other platform write. It withholds the proposal when Notion's date is in the past or
when either side fires imminently. Captions are the other way round: they may be edited
in Metricool (better previews) and are read back afterwards. `Caption` is a per-row
TEXT field copied from the idea at row creation (2026-09-14, Albert — it was a rollup;
`Caption Override` is gone as redundant), so per-platform captions are the default
rather than an escape hatch. That matters because "link in bio" and hashtag blocks do
not travel between Instagram, YouTube and a Google listing — and because a live rollup
would retroactively rewrite what already-posted rows appear to have said.

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

## Secrets

No secrets in this repo. See `.env.example` for what each environment must provide.
Cloud environment env vars are not a secrets store — treat anything there as visible.

**Check this every run, not just at setup (2026-09-11).** Before using any credential
`.env.example` documents, confirm it actually comes from `.env` — never accept a
same-named cloud/session env var as satisfying that requirement, even if it would
work functionally (a script reading `os.environ` can't tell the difference; you have
to). If a required credential is only present as a cloud env var, treat it as
missing: report the exact variable name and stop, per the consuming command's
"Before you start" section (e.g. `/catalog-sync`'s Lightspeed check) — never fall
back to the cloud var to get past it.

**Superseded for cloud/VM sessions (2026-09-11, Albert).** `.claude/hooks/session-start.sh`
runs on every `SessionStart` (remote only, gated on `$CLAUDE_CODE_REMOTE`) and copies any
`.env.example`-documented key from the environment's own env vars into `.env`, whenever
`.env` doesn't already hold a non-empty value for that key — it never overwrites a value
someone set deliberately. This is a conscious, explicit trade against the paragraph above:
Albert decided the friction of re-confirming a cloud-provisioned credential every run
wasn't earning its keep, and chose to have the environment provision `.env` automatically
instead of stopping to ask each time. The check above ("confirm it actually comes from
`.env`") still holds literally — by the time any command or agent runs, the value really is
in `.env` — but the human-in-the-loop step it used to force is now a one-time decision made
here, not a per-run one. If a credential still reads as missing after this hook has run,
it is genuinely absent from the environment (not just cloud-only) — report the variable name
and stop, same as before.
