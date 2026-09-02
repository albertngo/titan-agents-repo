# Titan Flooring — Canonical Context Reference

This file is the lookup reference for the `project-status-meeting-processor` skill. It answers two questions during transcript processing: **"Is this name a person or a project?"** and **"Which Notion database do I query?"**

---

## 1. Recurring people (NEVER treat these as projects)

### Meeting participants (speakers in transcripts)

| Name | Role | Notes |
|------|------|-------|
| **Albert Ngo** | Owner/operator | Runs the meeting; announces section transitions verbally |
| **Pourya Lalee Faz** | PM / sales & operations lead | Client relationships, follow-ups, deliveries; core in-room presence |
| **Michael Tran** ("Mike") | Remote strategic advisor / business partner | Financial performance, marketing ROI, quarterly reporting; usually joins remotely |

### Subcontractors and crew (mentioned in discussion, not projects)

| Name | Role | Notes |
|------|------|-------|
| **Roy** | Primary installation subcontractor (stairs/handrails) | Receives modified QE docs; his cost rates set pricing benchmarks; reducing Roy-dependence is an active CII |
| **Ricardo** | Subcontractor, moved to backup status | Recurring bottleneck in deficiency discussions |
| **Anthony** | New staircase subcontractor being trialed | ⚠️ AMBIGUOUS — see §3 below; "Anthony" has also been a **client/project** name |
| **David** (David Singh) | Subcontractor/installer | Source of the "David plumbing situation" playbook lesson; started ~Jun 2026 |
| **Joey** | Materials & logistics staff | Pickups, deliveries |
| **Lynn** | Installer | |
| **Tony** | Subcontractor | |
| **Fung** | Subcontractor | |
| **Jimmy** | Crew member | NOT a project (confirmed May 19/26 run — was initially mis-flagged) |

### One-off people (context mentions, never projects)

- **Allison** — Facebook QA contact (6" baseboards inquiry, closed May 19/26)
- Suppliers, neighbors, family members mentioned in passing — do not create project entries for these.

---

## 2. Notion databases

**IDs, template ids, and property names all live in
`platform-settings/notion-destinations.json` under
`project_status_meeting_processor` — never hardcoded here or in SKILL.md.**
Re-verify that file against the live schema (`notion-fetch` on the
`data_source` url) whenever a write starts erroring on an unknown
property/option; it goes stale silently if a database is renamed or a
property is added/removed in Notion.

Quick map of what lives where (see the settings file for the actual ids):

| Database | Key in `project_status_meeting_processor` | Title property | Key notes |
|----------|---|----------------|-----------|
| **Project Status Meetings** | `project_status_meetings` | `Name of Meeting` | Page titles follow `Project Status — [Mon D/YY]` (e.g. `Project Status — May 19/26`). Has `Tactical Associated`, `CII Associated`, `Meeting Summary` (URL), `Short Synopsis on Meeting` (leave EMPTY), `Date of Meeting` (date) |
| **Meeting page template** | `project_status_meetings.template_id` | — | Template instantiation OVERRIDES `properties` passed at creation — always re-apply title + date via `update_properties` afterward |
| **Tactical Tasks** | `tactical_tasks` | `Name` | Short-horizon, atomic, one-sitting work. Same underlying database as `notion-destinations.json`'s `destinations.team` (the GHL sync's shared Tactical Tasks List) — reuse those property names (`Status`, `Priority`, `Tags`, `url`, `Notes`, `Verification`) for anything also used by that sync. CAN link to meeting page (`Tactical Associated`) and to a CII (`Project`, per this skill's `extra_properties`) |
| **CII (Continuous Improvement Initiatives)** | `cii` | `Stage/Task` (NOT `Name`) | `Initiative Name` select: Marketing / Funnel-Sales / Inventory Improvement / Operations / Reporting-Analytics. `Priority`: High / Medium / Low. **NEVER link a CII to an individual meeting page** |
| **Titan Projects (master)** | `titan_projects` | — | Query by client name; bias toward projects from the last 60 days. Read-only for this skill |
| **Project Financials** | `project_financials` | — | Row titles: `PP-XXX_ClientName \| City (Financials)`. Search by client name + "Financials", not PP-ID alone. Read-only for this skill |

### Query tips

- `notion-search` scoped with `data_source_url` to a specific collection is more reliable than global search.
- Semantic/keyword search outperforms date/name search for the CII and Tactical databases.
- SQL via `notion-query-data-sources` is NOT available on the current plan — all lookups are row-by-row search + fetch.
- Common first names (Salih, Glenn, Mike, Stephanie) return multiple Financials candidates — compare the `Project` relation field against the master page ID to disambiguate.

---

## 3. Name-disambiguation rules

1. **Speakers are never projects.** Albert, Pourya, Michael/Mike appear constantly — always people.
2. **Subcontractor names in an install/deficiency/payment context are people** ("Roy quoted", "waiting on Ricardo", "David's $200").
3. **"Anthony" is genuinely ambiguous.** It has been both a trialed staircase subcontractor AND a client project (e.g. "Anthony CO + David touch-up"). Resolve by context: change orders, billing, deficiencies at a client site → project; installing, quoting, being trialed, being paid a rate → subcontractor. If still unclear, mark "needs match" and flag it.
4. **Possessive-of-a-possessive is context only.** "Marisa's neighbor Nasser" → only Nasser is a project candidate.
5. **When a raw-transcript name looks garbled, check near-matches before searching.** Confirmed example: transcript autocorrect produced "Marissa"/"Mamuna" for the actual client **Marica**.

---

## 4. Recurring patterns and shorthand (for Risk Items / Playbook / CII detection)

| Shorthand | Meaning |
|-----------|---------|
| **Mamuna-pattern** | Client disputes/withholds a balance late in the project, often citing a walkthrough or deficiency issue. Any "client hasn't paid the missing balance" discussion should be checked against this pattern |
| **Deficiency backlog** | Chronic theme: open deficiencies pile up because Roy/Ricardo are unresponsive. Surfaced May 12, May 19, and onward. Lives as a High-priority Operations CII — new deficiency discussions usually roll up under it, not into new items |
| **Roy-dependence** | Strategic thread: too much stair/handrail work flows through one sub. Diversification (Anthony trial, Ricardo backup) is an active CII |
| **Prep-quality issues** | Recurring installer/site-prep quality pattern — candidate for Playbook entries when it resurfaces |
| **David plumbing situation** | Canonical "critical risk nearly caused damage" playbook example |
| **Quote high then walk down** | Current pricing strategy; mobile-quote rate rebuild completed |
| **Stale-lead CRM workflow** | 30-day nudge + Lost-Reason capture rules established; recurring Funnel-Sales thread |

---

## 5. Meeting rhythm facts

- Weekly, typically **Tuesdays**; next-week draft page defaults to **+7 days**.
- Transcript source: primarily the live Microsoft Teams meeting transcript, fetched via Graph (`meeting-transcript:///events/...`, resolved from the calendar event's `meetingTranscriptUrl`) — see SKILL.md Step 1. A manually-provided `.docx` Teams export is a supported fallback when the live transcript isn't available or a past meeting is being backfilled.
- Teams transcripts are ~50–60% filler — always clean before extraction (`scripts/clean_transcript.py`), regardless of source format.
- Albert verbally announces sections ("alright, on to our projects", "work orders", "sales touch point", "to-do items would be", "before we end").
- Off-topic chatter (e.g. personal trip planning) is dropped entirely from all outputs.
