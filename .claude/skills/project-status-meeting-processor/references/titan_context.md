# Titan Context — reference for `project-status-meeting-processor`

Canonical people, database IDs, and recurring patterns for the weekly Project
Status meeting. Extracted from SKILL.md so the main file can stay procedural.

> **Maintenance note:** everything below was reconstructed from what SKILL.md
> already asserts. Sections marked **[EXPAND]** are known to be incomplete —
> SKILL.md gives examples rather than a full list. Fill them in as they come up.

---

## 1. People — the canonical non-project name list

Step 4 matches project names against the Titan Projects DB. These names are
**people, not projects** — never create a project entry for them.

### Meeting participants
| Name | Role |
|---|---|
| Albert Ngo | Owner |
| Pourya Lalee Faz | Project manager / sales |
| Michael Tran | Operations advisor |

### Subcontractors and crew
Roy · David · Joey · Tony · Ricardo · Lynn · Fung

**[EXPAND]** — add new subs here as they appear, otherwise the matcher will try
to open a project for them.

### Ownership shorthand
- "I'll take it on notion to the project" → owner = **Pourya**

### Ambiguous cases
Some names are *both* — a sub who is also a client, or a client referred to only
through someone else. Rules:
- "Marisa's neighbour Nasser" → only **Nasser** is a project. Marisa is context.
- A name mentioned once, with no work attached → context, not a project.
- Same first name as a sub but clearly a client in context → project; note the
  collision here so it isn't re-litigated every week. **[EXPAND]**

---

## 2. Notion databases

| Purpose | Data source URL |
|---|---|
| Titan Projects | `collection://1b4596a4-505f-81ca-b1d5-000bb73ecbe1` |
| Tactical Tasks | `collection://238596a4-505f-8137-af13-000bde205213` |
| Continuous Improvement Initiatives (CII) | `collection://365596a4-505f-81b2-8eb7-000b068f506c` |
| Project Status Meetings | `collection://24d596a4-505f-803a-9797-000b3f8f5a68` |

**Project Status Meetings template ID:** `24d596a4505f80d184c8e7d455c4f7c6`

### Field gotchas
- CII title field is **`Stage/Task`**, not `Name`.
- CII `Initiative Name` (select): Marketing / Funnel-Sales / Inventory
  Improvement / Operations / Reporting-Analytics
- CII `Priority` (select): High / Medium / Low
- Project Status Meetings needs a `Meeting Summary` property of type `url` —
  create it if absent (Step 7.7).
- Meeting page relations to read: `Tactical Associated`, `CII Associated`.

### Linking rules
- Tactical Tasks **may** link to the meeting page (`Tactical Associated`).
- Tactical Tasks **may** roll up under a CII.
- CIIs are **never** linked to a specific meeting — leave the meeting relation
  blank even though the property exists. CIIs live above the meeting level.

---

## 3. Tactical vs CII — the classification cheat sheet

The decision question: *"Is this one thing the owner will do, or is this a
change to how Titan operates?"*

| Signal | Tactical | CII |
|---|---|---|
| Horizon | One sitting | Days to months |
| Shape | Atomic, clear done | Process / SOP / tooling |
| Trigger | One-off | Recurring pattern |
| Spawns sub-work | No | Usually yes |

- Recurring issue surfacing **3+ times** across meetings → CII, with the
  immediate next action as a Tactical under it.
- When genuinely torn → **lean Tactical**. CII requires the recurring signal.

**Tactical examples:** Send Janet bin removal email · Nudge Ricardo for date ·
Pick up Vidar materials
**CII examples:** Build stair-project SOP checklist · Implement monthly
LightSpeed→QBO reconciliation · Codify deficiency intake workflow

---

## 4. Playbook categories

Fixed select list — do not invent new ones without updating SKILL.md too:

Subcontractor Management · Prep/Walkthrough · Client Communication · Pricing ·
Materials Sourcing · Marketing · Internal Process · Safety/Risk ·
Payment Collection

**Severity:** Critical / Important / Minor
**Action Taken:** always left blank for Albert to fill during review.

---

## 5. Recurring patterns

Named patterns that recur across meetings. When one surfaces, flag it in both
Risk Items and Playbook Candidates.

| Pattern | What it looks like |
|---|---|
| **Mamuna-pattern** | **[EXPAND]** — SKILL.md names it but doesn't define it. Write the one-line definition here so the classifier can actually detect it. |
| **Prep-quality issues** | Site not ready / subfloor or prep shortcuts surfacing as deficiencies after install |
| **The David plumbing situation** | Reference case for "critical risk that nearly caused damage" — the severity benchmark for Playbook entries |

Other recurring risk surfaces: subcontractor quality, payment collection, safety
concerns, process gaps.

---

## 6. Section-transition cues

Albert verbally announces transitions. Anchors for Step 2:

| Cue phrase | Section |
|---|---|
| "alright, on to our projects" / "let's go through" | Project status |
| "work orders" / "deficiencies" | Work orders |
| "sales touch point" / "let's talk marketing" / "the new ad…" | Process & marketing |
| "to-do items would be" / "alright, two things from this" | Wrap-up / new action items |
| "before we end" / "anything else" | Closing |

---

## 7. Off-topic content to strip

Recurring non-meeting chatter that must not reach the output: travel and trip
planning, personal scheduling, and general cross-talk. **[EXPAND]** as new
tangents become habitual.

---

## 8. Transcript format

Teams `.docx` export, speaker turns like `**Albert Ngo   **5:22`.
Roughly 50–60% of turns are filler. `scripts/clean_transcript.py` handles the
strip; the fallback rule is *drop turns under 4 words that are **only** filler
tokens*, preserving speaker labels and timestamps for citation.
