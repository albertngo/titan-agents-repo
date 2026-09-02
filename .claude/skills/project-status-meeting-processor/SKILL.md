---
name: project-status-meeting-processor
description: Ingest Albert's weekly Project Status meeting transcript for Titan Flooring — the live Teams transcript by default, or a manually-uploaded .docx export as a fallback — and produce a structured markdown summary for Notion. Trigger whenever the user asks to process, ingest, or summarize "this week's" / "today's" / "the latest" Project Status meeting, uploads a transcript and asks the same, or asks to build next week's agenda. Phrases like "process this transcript," "summarize the status meeting," "build next week's agenda," or any uploaded .docx with "Project Status" or "Meeting Recording" in the filename should activate it. Output maps to Albert's Notion template sections (Action Items, Project Updates, Process/Marketing, Risk Items, Playbook Candidates, Key Takeaways, Next Week Topics) and is saved as inline markdown plus a downloadable file. Also reconciles new action items against tactical tasks already linked to the meeting page — appending notes directly to existing tasks via Notion MCP (append-only, never modifying fields), and creating missing Tactical Tasks and CIIs directly (owner/due-date set only when explicitly and unambiguously stated in the transcript). All Notion writes are logged to the meeting date's actions-log.json.
---

# Project Status Meeting Processor (Titan Flooring)

This skill ingests Albert's weekly Project Status meeting transcripts and produces structured markdown for the corresponding sections of his Notion meeting template. It writes directly to Notion in specific, bounded ways: appending notes to existing linked tasks, creating missing Tactical Tasks/CIIs, creating the Transcript and Meeting Summary sub-pages, and creating next week's draft meeting page. Everything it writes is either append-only, a brand-new record with a narrow property set, or logged for audit — see "What this skill does NOT do" at the bottom for the actual boundaries.

Read `platform-settings/notion-destinations.json`'s `project_status_meeting_processor` block and `references/titan_context.md` in full before doing anything below — they hold the database ids, template id, and property names this skill must not re-derive or guess. Nothing in this file should ever contain a literal Notion collection/database id; if you find yourself about to type one, it belongs in `notion-destinations.json` instead.

## When this skill applies

Trigger when:
- Albert asks to process "this week's" / "today's" / "the latest" Project Status meeting, with no file attached — fetch the live transcript per Step 1.
- Albert uploads a transcript (`.docx` from Teams export, with timestamped speaker turns like `**Albert Ngo   **5:22`) and wants it processed.
- Common phrases: "process this transcript," "here's this week's meeting," "summarize the status meeting," "build next week's agenda."

The skill is opinionated for **Titan Flooring's specific context**:
- Recurring participants: Albert Ngo (owner), Pourya Lalee Faz (PM/sales), Michael Tran (operations advisor), occasionally others
- Project domain: Flooring installation, staircase work, retail, contractor management
- Notion target structure: Specific section headers detailed below

## Core workflow

Follow these steps in order. Don't skip ahead.

### Step 1: Get and clean the transcript

**Primary path — live Teams transcript (default).** When Albert asks to process "this week's" / "today's" / "the latest" meeting without attaching a file:

1. Find the meeting: search the Outlook calendar for the "Project Status Meeting" event (ask which one if more than one plausibly matches), then read the event to get its `meetingTranscriptUrl`.
2. Fetch it: `read_resource` on that `meeting-transcript:///events/...` URI. This returns WebVTT — a `WEBVTT` header, timed cues, Teams-style `<v Speaker Name>text</v>` tags.
3. Save the raw content to `/home/claude/transcript_raw.vtt`.

If the fetch fails (e.g. `GraphAccessToTranscriptsDisabled`, or the meeting has no transcript yet), say so plainly — don't retry silently or fabricate content — and offer the fallback below instead.

**Fallback path — manual `.docx` upload.** When Albert uploads a `.docx` transcript directly, or the live fetch isn't available:

```bash
extract-text /path/to/transcript.docx > /home/claude/transcript_raw.md
```

**Either path, then clean:**

```bash
python /path/to/skill/scripts/clean_transcript.py /home/claude/transcript_raw.{vtt,md} /home/claude/transcript_clean.md
```

The script auto-detects VTT vs. the docx-export format and normalizes both to the same `**Speaker** · *mm:ss*` turn format used throughout the rest of this skill — nothing downstream needs to know which source it came from. It strips filler either way: Teams transcripts are ~50-60% noise ("Yeah," "Okay," "Mhm," "The."), partial utterances, cross-talk.

If the script isn't available, do the cleaning inline by filtering out turns shorter than 4 words AND consisting only of filler tokens. Preserve the speaker labels and timestamps for citation purposes.

### Step 2: Identify section markers in the transcript

Albert tends to verbally announce section transitions. Watch for phrases like:
- "alright, on to our projects" / "let's go through" — project status section
- "work orders" / "deficiencies" — work orders section
- "sales touch point" / "let's talk marketing" / "the new ad..." — process/marketing section
- "to-do items would be" / "alright, two things from this" — wrap-up / new action items
- "before we end" / "anything else" — closing

These are anchors. Tag the transcript mentally into rough sections. The skill output is organized into these sections regardless of how cleanly they appear in the transcript.

### Step 3: Extract structured data

Build five internal data structures before drafting the output. Don't write the output until all five are populated.

**A) Action items reviewed (from last meeting)**

These are typically discussed at the start of the meeting. Albert often says "for me, I was supposed to..." or "we'll loop back into [last week's items]." For each action item discussed, capture:
- Original item description (paraphrased — concise)
- Proposed status: `Done`, `Done + Needs Verification`, `In progress`, `On Hold`, `Dropped`, or `Not Started`
- Reasoning citation (a brief quote or paraphrase from the transcript showing why)
- Owner

**Status assignment rules — strict:**
- `Done` — explicit completion with no hedge ("I added it in," "it's all clean," "we finished it")
- `Done + Needs Verification` — completion language WITH hedge words ("I think it's clean," "should be done," "assuming that's the case")
- `In progress` — work happened but explicitly not complete ("still working on it," "halfway there")
- `On Hold` — waiting on external party with no current action ("waiting for them to pay," "blocked on supplier")
- `Dropped` — explicitly killed ("we don't need to do that anymore," "scrap that")
- `Not Started` — no movement at all

Be conservative. If in doubt between `Done` and `Done + Needs Verification`, pick the latter. Albert specifically wants the skill to flag soft completions, not auto-close them.

**B) New action items (this meeting)**

Watch for first-person commitments and assignments. Examples from past transcripts:
- "I'll pick a route after, I'll pick a day" → owner = Albert, item = pick yard sign inspection route
- "I'll take it on notion to the project" → owner = Pourya
- "we'll catch her on that after" → owner = whoever was previously assigned to that customer

For each, capture: owner, item description, due date (only if explicitly stated — don't infer), proposed Notion tag (e.g., `project status`, `meeting`, `parked`), source quote.

If owner is genuinely ambiguous, mark as "TBD — needs confirmation" rather than guessing. This distinction matters beyond the recap table now — Step 4.6.4b uses it directly to decide whether a newly-created Notion task gets an `Assign To` value or is left blank.

**C) Project status digest**

The transcript mentions projects by client name (Nasser, Anthony, Devindra, Sebastian, Marisa, etc.). For each named project:
- Match to Titan Projects DB using the lookup script (see Step 4)
- Capture the discussion: one-line status summary
- Categorize as Upcoming / In Progress / Open Work Order

Don't include every off-hand mention. If a project is named only as context ("Marisa's neighbor"), don't create an entry for Marisa.

**D) Risk items and open discussions**

Conversations that didn't fully resolve, especially involving:
- Subcontractor quality issues
- Payment collection problems
- Recurring patterns (Mamuna-pattern, prep-quality issues)
- Safety concerns
- Process gaps

These items are often the same ones that become Playbook candidates. Flag them in both places when appropriate.

**E) Process & marketing updates**

Discussion of: marketing channels, CRM/tools changes, operational processes, product/inventory decisions. Sub-categorize as Marketing / CRM-Tools / Operations.

### Step 4: Match project names to Titan Projects

Scan the cleaned transcript and identify every project mentioned. Project names usually appear as:
- Possessives: "Nasser's project," "Sebastian's house," "Marisa's neighbor"
- Direct references: "for Anthony," "with Devindra," "at Nusha"
- Standalone: "Nasser, that's new" (sentence-initial introduction)

Distinguish projects from people: speakers in the transcript (Albert, Pourya, Michael), subcontractors (Roy, David, Joey, Tony, Ricardo, Lynn, Fung), and one-off mentions of unrelated people. Refer to `references/titan_context.md` for the canonical list of non-project names.

For each candidate project name, query the Titan Projects database via MCP. Use `notion-search` with the `data_source` url from `notion-destinations.json`'s `project_status_meeting_processor.titan_projects`.

Search using the client name. If MCP isn't available, mark the project as "needs match" and include the raw name from the transcript so Albert can link it manually.

For each match, capture:
- Notion page URL (if matched with confidence)
- "needs match" (if no clear match found in Titan Projects)
- Multiple candidates (if there's ambiguity — present them to Albert)

Bias toward recent projects (last 60 days) for best match accuracy — older projects are unlikely to be discussed in current meetings.

Never invent project names. If the transcript says "Marisa's neighbor Nasser" and only Nasser is a real project, only include Nasser.

### Step 4.5: Classify each action item — Tactical Task or CII?

Before reconciling against existing tasks, classify every item from the draft New Action Items list. Albert runs two separate task databases that must not be mixed (ids in `notion-destinations.json`'s `project_status_meeting_processor.tactical_tasks` / `.cii`):

**Tactical Tasks** — short-horizon, executable work
- Concrete, atomic actions with a clear definition of done
- Completable in one sitting (minutes to a few hours)
- Has an obvious owner who can just do it
- One-and-done; not addressing a recurring pattern
- Examples: "Send Janet bin removal email", "Nudge Ricardo for date", "Pick up Vidar materials"

**Continuous Improvement Initiatives (CII)** — longer-horizon, system-level work
- Process changes, SOPs, training programs, workflow redesigns, tooling builds
- Spans days/weeks/months; usually spawns multiple Tactical Tasks
- Addresses recurring patterns, not one-off issues
- Initiative Name (select): Marketing / Funnel-Sales / Inventory Improvement / Operations / Reporting-Analytics
- Title field is `Stage/Task` (NOT `Name`)
- Priority (select): High / Medium / Low
- Examples: "Build stair-project SOP checklist", "Implement monthly LightSpeed→QBO reconciliation", "Codify deficiency intake workflow"

**Decision rule when classifying:** Ask *"Is this one thing the owner will do, or is this a change to how Titan operates?"*
- One thing → **Tactical**
- A change to how things work → **CII**
- Recurring issue surfacing 3+ times across meetings → **CII** (and the immediate next action becomes a Tactical sub-item under it)
- Playbook candidates that involve a workflow shift → typically have a paired CII

**Important — DO NOT mix up the databases:**
- Putting a CII into Tactical clutters Albert's daily action view.
- Putting a Tactical into CII buries it under strategic noise.
- When in doubt between the two, lean Tactical. CIIs require the recurring-pattern signal — don't elevate a one-off task just because it sounds strategic.

**Cross-linking rules (per Albert's directive):**
- Tactical Tasks CAN link to the Project Status meeting page (via `Tactical Associated`).
- Tactical Tasks CAN link to a CII (rolls up under that initiative).
- **CIIs are NOT linked to individual meetings** — they live above that level. Even though the CII DB has a `Project Status Meetings` relation property, leave it empty when creating or updating a CII. Albert wants CIIs scoped above any single meeting.

Tag each item from the draft list as **TACTICAL** or **CII** before moving on.

### Step 4.6: Reconcile against existing tasks, and create missing ones (REQUIRED before drafting output)

The split: **directly append context to existing tasks; directly create brand-new Tactical Tasks and CIIs for anything missing.** Both are live Notion writes via the Notion MCP. Every create or update is logged to that meeting date's `ingest/<date>/actions-log.json` per `contracts/actions-log-schema.md` (`type: "notion_create_task"` or `"notion_update_task"` — reusing `contracts/notion-task-schema.md`'s existing type names; `notion_create_task` covers both a new Tactical Task and a new CII, since a CII is the same kind of record at a different altitude).

- For EXISTING tasks (in either DB): append notes directly to the task page. Append-only. Never replace existing fields. Never change titles, assignees, due dates, project links, or status.
- For MISSING tasks: create the page directly (Step 4.6.4b). `Assign To` / `Due Date` are set only when Step 3B captured them as explicit and unambiguous — otherwise leave blank. Report every creation in the response so Albert can review it.

**Step 4.6.1 — Find this week's Project Status page in Notion.**

Search the Project Status Meetings data source (`project_status_meeting_processor.project_status_meetings.data_source` in `notion-destinations.json`) for the meeting page matching this transcript's date:

```
query: "Project Status — [Mon D/YY]"  (e.g., "Project Status — May 19/26")
```

If found, fetch the page. It will have a `Tactical Associated` property listing all currently-linked tactical task URLs. (The page also has a `CII Associated` property — capture it too, but per Albert's rule above, do not add new CIIs to it.) If not found, note "No Project Status page yet for this meeting — all new tasks/CIIs are net-new, unlinked to a meeting page" and skip to 4.6.4a/4.6.4b as applicable.

**Step 4.6.2 — Fetch each linked task.**

For each URL in `Tactical Associated` (and any in `CII Associated`), call `notion-fetch` to retrieve the task's full record. Capture:
- Title (`Name` for Tactical, `Stage/Task` for CII)
- Assignee
- Due Date
- Status
- Project link (Tactical only)
- Initiative Name (CII only)
- Existing Notes / page content
- Page URL

Also check last week's Project Status page for tasks still open and contextually relevant.

Optionally, also search the CII DB directly for any open initiative that overlaps with a draft item, even if it's not linked to this week's meeting page (since CIIs intentionally aren't linked):

```
data_source: project_status_meeting_processor.cii.data_source (notion-destinations.json)
query: [keywords from the draft item]
```

This catches the case where Albert already has a CII running on a topic (e.g., "deficiency workflow") and the meeting just generated a new Tactical that belongs under it.

**Step 4.6.3 — Map each draft item to existing tasks.**

For every action item drafted in Step 3B, check whether an existing Tactical OR CII already covers it. Matching is by **intent**, not exact title.

Mark each draft item as:
- **EXISTS-TACTICAL** — already covered by a linked Tactical Task. Action: append notes to that task page (4.6.4a).
- **EXISTS-CII** — already covered by an existing CII. Action: append notes to the CII page (4.6.4a) — carefully, since CIIs are higher-level: the note should add strategic context, not granular meeting chatter.
- **MISSING-TACTICAL** — new Tactical needed. Action: create it directly (4.6.4b).
- **MISSING-CII** — new CII needed. Action: create it directly (4.6.4b).

**When matching is uncertain, prefer MISSING over EXISTS.** A false MISSING costs Albert a duplicate to merge by hand later; a false EXISTS costs him your notes landing on an unrelated task. The former is the recoverable mistake.

**Step 4.6.4a — Append notes to existing tasks (via Notion MCP).**

For each EXISTS item (Tactical or CII), use `notion-update-page` with `command: "insert_content"` and `position: {"type": "end"}` to APPEND to the task page. Never use `replace_content` and never modify properties.

Use this exact append-block format (markdown):

```markdown
---

### Notes from [Mon D/YY] meeting

**Source:** *"[exact quote from cleaned transcript]"* — [Speaker], [timestamp]

**Context:** [1-3 sentences covering relevant context, decisions, connections to other tasks, or key numbers. If there's a downstream pairing — e.g., this task pairs with another, or this connects to a Playbook candidate — call it out.]

[Optional sub-sections: "Numbers reference", "Strategy / tone", "Connect this to", "Pattern flag", "Title nitpick" — only when warranted.]
```

**Hard rules for the append:**
- Always start with the `---` separator and `### Notes from [Mon D/YY] meeting` heading so prior weeks remain visually distinct.
- Use exact transcript quotes with timestamps. Paraphrase only when the original is too cluttered with cross-talk.
- If the task title or scope is materially wrong (e.g., "3 boxes" when the transcript said 10+ boards), include a "Title nitpick" note — but do NOT rename the task. Albert decides.
- If the task already has body content (e.g., a draft email body), the append goes BELOW it, separated by the `---`. Original content is preserved exactly.
- For CII appends: keep the note higher-level. Don't dump every transcript quote about the topic — pick the one or two strategic signals. The CII page is for tracking the pattern, not the meeting minutiae.
- Never write to Notion until the meeting has been fully processed through Steps 1–4.6.3. No partial updates mid-extraction.
- After each successful append, log one `notion_update_task` entry per the format in 4.6.4b.

**Step 4.6.4b — Create missing tasks and CIIs directly (via Notion MCP).**

For each **MISSING-TACTICAL** item, create a new row in the Tactical Tasks database (`project_status_meeting_processor.tactical_tasks` in `notion-destinations.json`) via `notion-create-pages`:

| Field | Notion property | Value |
|---|---|---|
| title | `Name` | concise, action-verb-first, ≤ 80 chars |
| — | `Status` | `Not started` |
| — | `Tags` | `["project status"]` plus `meeting` / `parked` if they apply |
| — | `Verification` | `Needs Verification` |
| — | `Tactical Associated` | this meeting's page URL (omit if no meeting page exists yet, per 4.6.1) |
| — | `Project` | the matched Titan Projects page from Step 4, if any — omit if "needs match" |
| — | `Notes` | description + source quote: `**Source:** "[quote]" — [Speaker], [timestamp]`, footer `[skill] project-status-meeting-processor \| meeting=[Mon D/YY]` |
| — | `Assign To` | see "Setting Assign To / Due Date" below |
| — | `Due Date` | see "Setting Assign To / Due Date" below |

For each **MISSING-CII** item, create a new row in the CII database (`project_status_meeting_processor.cii` in `notion-destinations.json`) via `notion-create-pages`:

| Field | Notion property | Value |
|---|---|---|
| title | `Stage/Task` | describes the initiative, not a single task |
| — | `Initiative Name` | from the approved list |
| — | `Priority` | High / Medium / Low, per severity & recurrence |
| — | `Project Status Meetings` | **leave empty** — never link a CII to a meeting |
| — | `Assignee` (if present on the CII DB) | see "Setting Assign To / Due Date" below |

**Setting Assign To / Due Date.** This is a deliberate, narrow exception to `contracts/notion-task-schema.md`'s rule that the GHL sync never sets these — that rule exists because the sync's `assigned_to` is *inferred* from GHL data. Here, an owner is a live, explicit decision made by Albert or a teammate in the meeting itself. So:

- Set `Assign To` / `Due Date` only when Step 3B captured them as **explicit and unambiguous** — not "TBD — needs confirmation," and not a group/hedge like "Albert (with Pourya input)."
- When in doubt, leave blank. Same conservative bias as every other judgment call in this skill.
- This exception is scoped to this skill's own creates. It does not reopen or loosen the GHL sync's rule — don't generalize it elsewhere.

**Logging.** After each create or append succeeds, append one entry to that meeting's `ingest/<meeting-date>/actions-log.json` (`contracts/actions-log-schema.md` — create the file with an empty `entries` array first if it doesn't exist yet; append-only, never rewrite prior entries):

```json
{
  "logged_at": "<ISO timestamp, now>",
  "agent": "project-status-meeting-processor",
  "type": "notion_create_task",
  "target": "Tactical Tasks List: <title>",
  "content_summary": "<one sentence>",
  "approved_by": "auto: Albert 2026-09-02, project-status-meeting-processor auto-create",
  "result": "executed",
  "error": null,
  "raw_ref": "<new or updated Notion page URL>"
}
```

(`type: "notion_update_task"` for an append; `target` prefixed `CII:` instead of `Tactical Tasks List:` for a CII row.)

If a single create or append fails, log it with `result: "failed"` and `error` set, keep processing the rest of the batch — unlike the GHL sync's same-batch-stop rule, a single failed row here doesn't justify withholding the whole meeting recap — and surface it plainly in both the Reconciliation section (4.6.5) and Skill Notes so it isn't silently lost.

**Step 4.6.5 — Format the response section.**

Place this AFTER the standard meeting recap, before "Skill Notes":

```markdown
---

## 🔄 Task Reconciliation 🔄

### ✅ Existing Tasks — Notes Appended

**Tactical Tasks updated:**
1. **[Task title]** — [link to task] · Due [date] · Assignee: [name]
   *Appended:* [1-line summary of what was added]

[repeat for each Tactical task that got updated]

**CIIs updated:**
1. **[CII Stage/Task]** — [link to CII] · Initiative: [Marketing / Operations / etc.]
   *Appended:* [1-line summary]

[repeat — or note "None this week" if no CIIs got notes]

### ✨ New Tasks — Created

These came up in the meeting and weren't covered by anything existing, so
they were created directly in Notion. Review each — owner/due date are only
set when explicitly stated in the transcript.

#### 🔧 New Tactical Tasks

##### A. [Task title — concise, action-verb-first] — [Notion link]
- **Assign:** [name, or "unset — not explicit in transcript"]
- **Due:** [date, or "unset — not explicit in transcript"]
- **Tag:** [project status / meeting / parked]
- **Project link:** [Notion project name + URL if applicable]
- **Notes:** [Short description + source quote]

[repeat with letters A, B, C...]

#### 📈 New CIIs

##### CII-1. [Stage/Task title — describe the initiative, not the task] — [Notion link]
- **Initiative Name:** [Marketing / Funnel-Sales / Inventory Improvement / Operations / Reporting-Analytics]
- **Priority:** [High / Medium / Low — based on severity & recurrence]
- **Assignee:** [name, or "unset — not explicit in transcript"]
- **Why this is a CII (not Tactical):** [1 sentence — what's the recurring pattern or system change]
- **First Tactical sub-tasks to consider creating under it:** [bulleted list — these may overlap with the Tactical items above; flag the overlap]
- **Source:** [quote + timestamp]

[repeat with CII-2, CII-3...]

### ⚠️ Failed writes (only if any occurred)

- **[Item title]** — [create/append] to [Tactical/CII] failed: [error]. Not reflected in Notion — retry manually or ask the skill to retry next run.

### Quick Cross-Reference: Last Week's Open Items

[Bullet list of any tasks from the prior meeting's tactical list that are still open AND came up in this meeting's discussion. Note "Still open" or "Marked Done" with completion date.]
```

**Step 4.6.6 — Rules summary.**

- ✅ Append notes to existing Tactical AND CII tasks via Notion MCP (insert_content, end position).
- ✅ Create missing Tactical Tasks AND CIIs directly via Notion MCP (`notion-create-pages`) when Step 4.6.3 marks them MISSING.
- ❌ Never replace existing fields on an EXISTS item, never rename it, never change its assignee/due/status/initiative on append.
- ✅ On a newly-CREATED item only, `Assign To`/`Due Date` MAY be set — and only when explicit and unambiguous per "Setting Assign To / Due Date" above.
- ✅ Preserve existing body content on appends (email drafts, prior notes) — append below the separator.
- ✅ Quote precision matters: exact transcript quotes with timestamps.
- ✅ Classify deliberately. When unsure, lean Tactical. Only elevate to CII when there's a clear recurring-pattern or systemic-change signal.
- ✅ CIIs are NEVER linked to a specific meeting page — leave the meeting relation blank, on create or append.
- ✅ If a new Tactical naturally rolls up under an existing CII, link it (`Project`/relation, per the property table) and note the connection in its response entry.
- ✅ Log every create and append to that meeting date's `actions-log.json`.
- ✅ When Step 4.6.3's match is uncertain, create a new row rather than appending to a possibly-wrong existing one.

### Step 5: Identify Playbook candidates

A Playbook candidate is a lesson that meets at least one of these criteria:
- A recurring pattern flagged in the meeting (e.g., "this keeps happening")
- A critical risk that nearly caused damage (e.g., the David plumbing situation)
- A new process decision made in response to a problem
- A statement of "we should change X" or "from now on, we will Y"

For each candidate, draft a Playbook entry:
- **Lesson** (title): One-sentence summary of the lesson
- **Category** (from: Subcontractor Management, Prep/Walkthrough, Client Communication, Pricing, Materials Sourcing, Marketing, Internal Process, Safety/Risk, Payment Collection)
- **Severity** (Critical / Important / Minor)
- **Trigger Pattern**: What recurring signal would surface this lesson again
- **Action Taken**: Blank (Albert fills in during review)

Do NOT mark Playbook candidates as final entries. Output them as drafts for Albert's review — this skill does not write to the Lessons Learnt (Playbook) database.

### Step 6: Draft "Today's Key Takeaways"

3-5 bullet points covering the highest-impact items from the meeting. These are the things Albert would want to remember a month from now. Examples from past meetings:
- Major decisions made
- Critical risks identified
- Big wins (e.g., first flyer convert)
- Significant strategic shifts (e.g., Facebook targeting overhaul)

Not status updates. Not minor tasks. The highlights.

### Step 7: Draft "Next Week Discussion Topics"

Anything that surfaced but didn't resolve. Examples:
- Unresolved subcontractor issues
- Strategy decisions deferred
- Items where someone said "let's revisit" or "we'll see"
- Action items where the outcome will need follow-up next week

### Step 7.6: Create a Transcript sub-page on the meeting page

Create a child page titled "📄 Transcript — [Mon D/YY]" under the meeting page, paste the cleaned transcript into it, and link to it at the top of the meeting page. This replaces the older approach of uploading a docx to the Files field — the transcript lives natively in Notion, is searchable, and one click away.

**Step 7.6.1 — Build the markdown transcript.**

Take the cleaned transcript from Step 1 (`/home/claude/transcript_clean.md`) and reformat each speaker turn as:

```
**Speaker Name** · *mm:ss*
Body text on a single line (collapse the internal newlines from the cleaning script).
```

Add a header block at the top:

```markdown
**Meeting:** Project Status — [Mon D/YY]
**Duration:** [duration]
**Source:** [live Teams transcript | original .docx filename]
**Note:** Cleaned transcript — filler/single-word affirmations removed.

---
```

Drop empty turns (speakers whose entire contribution was filler removed by the cleaning step).

**Step 7.6.2 — Create the sub-page.**

Use `notion-create-pages` with:
- `parent`: `{"page_id": "<meeting page ID from Step 4.6.1>", "type": "page_id"}`
- `properties.title`: `"Transcript — [Mon D/YY]"` (plain text, NO emoji prefix)
- `icon`: `"📄"` (the icon is set separately — Notion renders both the title and the icon, so including the emoji in the title produces a doubled emoji like "📄 📄 Transcript — ...")
- `content`: the full markdown transcript built in 7.6.1

**Page-link display:** When this sub-page is linked at the top of the meeting page (Step 7.6.3), Notion renders it as `<icon> <title>` automatically — so the page-mention will show as "📄 Transcript — [Mon D/YY]" even though the title itself has no emoji.

Notion page content has a generous size limit — a typical Project Status transcript (~50KB cleaned) fits in a single page. If a meeting transcript exceeds ~100KB after cleaning, split into "Transcript Part 1" and "Transcript Part 2" sub-pages and link both.

**Step 7.6.3 — Link the sub-page at the top of the meeting page.**

Use `notion-update-page` with `command: "insert_content"` and `position: {"type": "start"}` to PREPEND a page-mention to the meeting page. The content should be a single line:

```
<page url="<sub-page URL from 7.6.2>">📄 Transcript — [Mon D/YY]</page>
```

This puts the transcript link as the very first block on the meeting page, above all H2 sections.

**Hard rules:**
- Never paste the raw uncleaned transcript — always use the cleaned version.
- Never overwrite an existing transcript sub-page. If a Transcript sub-page already exists under this meeting (search the meeting page's children), surface it in the response and ask before creating another.
- The link goes at the TOP of the meeting page (position: "start"), not the bottom.
- After creating, note it in the response: "✅ Transcript sub-page created and linked at top of meeting page."

### Step 7.7: Create the Meeting Summary sub-page and link it at the top of the meeting page

Create a child page titled "📝 Meeting Summary — [Mon D/YY]" under the meeting page, paste the FULL recap into it, link it via the `Meeting Summary` URL property, and add a link to it at the TOP of the meeting page (right below the Transcript link).

**Design intent:**
- The meeting page itself stays scannable (the existing linked-DB views handle the operational content).
- The deep detail lives in the Meeting Summary sub-page, one click away from the top of the meeting page.
- Albert's existing **📝 New Action Items** linked database on the meeting page is already a multi-source view that mirrors both the Tactical Tasks and CII databases, filtered to this meeting. **Do not create new view databases on the summary page** — just reference the existing meeting page's view from inside the summary.
- The synopsis lives at the top of the summary sub-page, NOT in the `Short Synopsis on Meeting` property. Leave that property empty.

**Step 7.7.1 — Confirm the `Meeting Summary` URL property exists on the Project Status Meetings database.**

Fetch the `project_status_meetings.data_source` (from `notion-destinations.json`) and look for a property named `Meeting Summary` with type `url`. If it doesn't exist, add it:

```
notion-update-data-source
  data_source_id: <project_status_meetings.data_source id, notion-destinations.json>
  statements: ADD COLUMN "Meeting Summary" URL
```

**Step 7.7.2 — Build the summary page content.**

Include all sections in this order:

1. Attendees / Duration / Transcript source line (no top-level title — the page title serves as that)
2. `## 📝 Meeting Synopsis` (the 2-3 sentence sentiment-style synopsis as italic prose)
3. `## 🚧 Project Status Updates 🚧` — Upcoming / In Progress / Open Work Orders prose lists
4. `## 💰 Ready to Submit & Payments Pending 💰`
5. `## ⚠️ Risk Items / Open Discussions ⚠️`
6. `## 💬 Process and Marketing Updates 💬` — Marketing / CRM-Tools / Operations sub-sections
7. `## 📒 Playbook Candidates 📒` — 1-4 candidates as draft entries
8. `## 🔄 Task Reconciliation 🔄` (per Step 4.6.5 — Existing Tasks Updated, New Tasks Created, any Failed writes, Quick Cross-Reference). In the "Existing" sub-section, reference the meeting page's existing linked-DB view instead of duplicating views: **"The N tactical tasks linked to this meeting have been updated directly in Notion with append-only notes. They live in the 📝 New Action Items linked database on the [parent meeting page](URL) — that view already mirrors both the Tactical Tasks and CII databases, filtered to this meeting. Open any card to see appended notes."** followed by a numbered list of the existing tasks with URLs, due dates, and assignees. The "New Tasks — Created" sub-section lists what was created directly, with links.
9. `## 📌 Today's Key Takeaways 📌` (3-5 bullets)
10. `## 🗓️ Suggested Next Week Discussion Topics 🗓️` (bulleted list)
11. `## ⚙️ Skill Notes` — operational notes (synopsis at top of this page, transcript link at top of meeting page, N tactical tasks updated, M tasks/CIIs created, any failed writes, low-confidence project matches, etc.)

**Step 7.7.3 — Create the sub-page.**

Use `notion-create-pages` with:
- `parent`: `{"page_id": "<meeting page ID>", "type": "page_id"}`
- `properties.title`: `"Meeting Summary — [Mon D/YY]"` (plain text, NO emoji prefix)
- `icon`: `"📝"` (the icon is set separately — Notion renders both the title and the icon, so including the emoji in the title produces a doubled emoji like "📝 📝 Meeting Summary — ...")
- `content`: the full markdown summary from 7.7.2

**Page-link display:** When this sub-page is linked at the top of the meeting page (Step 7.7.5), Notion renders it as `<icon> <title>` automatically — so the page-mention will show as "📝 Meeting Summary — [Mon D/YY]" even though the title itself has no emoji.

**Step 7.7.4 — Set the `Meeting Summary` URL property on the meeting page.**

```
notion-update-page
  page_id: <meeting page ID>
  command: update_properties
  properties: {"Meeting Summary": "<sub-page URL from 7.7.3>"}
```

**IMPORTANT property-name quirk:** The property is literally called `Meeting Summary`, not `url` or `URL` — so do NOT prefix it with `userDefined:`. The `userDefined:` prefix is only for properties whose name itself is the literal word "url" or "id".

**Step 7.7.5 — Add the Meeting Summary link at the TOP of the meeting page (right below the Transcript link).**

The Transcript link from Step 7.6 was prepended at position `start`. The Meeting Summary link should sit immediately below it. Use `notion-update-page` with `command: "update_content"` to find the transcript-link line and append the summary link right after it:

```
old_str:
<page url="<transcript URL>">📄 Transcript — [Mon D/YY]</page>

new_str:
<page url="<transcript URL>">📄 Transcript — [Mon D/YY]</page>

<page url="<summary URL>">📝 Meeting Summary — [Mon D/YY]</page>
```

The two links should sit at the very top, in this order (Transcript first, Summary second), followed by a horizontal rule that the original template provides. The Key Takeaways and Next Week sections are NOT inlined on the meeting page anymore — they live exclusively inside the Meeting Summary sub-page. The meeting page stays clean: just the two top links and Albert's existing template structure (linked DBs + toggles).

**Step 7.7.6 — Verify the `Short Synopsis on Meeting` property is empty.**

The synopsis no longer goes in that property — it goes in the summary sub-page. If the property currently has content (e.g. from a previous run), clear it:

```
notion-update-page
  page_id: <meeting page ID>
  command: update_properties
  properties: {"Short Synopsis on Meeting": null}
```

**Hard rules:**
- Never overwrite an existing summary sub-page. If a Meeting Summary sub-page already exists under this meeting (or the `Meeting Summary` property is non-empty), surface it in the response and ask before creating another.
- The summary link goes at the TOP of the meeting page (below the transcript link), NOT the bottom.
- Do NOT inline Today's Key Takeaways or Suggested Next Week sections on the meeting page anymore. Those live exclusively in the summary sub-page.
- Do NOT create new linked-DB view blocks on the summary page. The Task Reconciliation section references the meeting page's existing 📝 New Action Items DB instead.
- Do NOT write the synopsis to the `Short Synopsis on Meeting` property. The synopsis lives at the top of the summary sub-page.
- After creating + linking, note it in the response:
  - "✅ Meeting Summary sub-page created."
  - "✅ Meeting Summary URL property set."
  - "✅ Summary link added at top of meeting page (below Transcript link)."
  - "✅ Short Synopsis on Meeting property cleared." (only if it had content previously)

### Step 7.8: Create next week's draft Project Status page with Suggested Topics

After the current week's recap is fully written, create a draft Project Status page for next week (default: the Tuesday 7 days after this meeting). The page is created from the database template so it inherits the standard structure (Action Items From Last Meetings linked DB, New Action Items linked DB, etc.). The skill then prepends ONE section at the very top of that page: **📋 Suggested Topics for This Meeting** — a simple bulleted list to give a quick read-in based on last meeting's carryover and the bigger picture.

**Design intent:**
- Light pre-meeting prep, not a full pre-built agenda
- Bullets only — no headers, no tables, no narrative
- Combines two kinds of items: (a) carryover from this week's "Suggested Next Week" list, and (b) bigger-picture items that aren't tasks but deserve a few minutes (recurring themes, CIIs being tracked, strategic threads still open)
- Albert can edit/delete freely before the meeting — this is a starting draft

**Step 7.8.1 — Determine next meeting date.**

Default: 7 days after the current meeting's date. If this meeting was Tuesday May 19, next is Tuesday May 26. The page title format follows existing convention: `Project Status — [Mon D/YY]` (e.g. `Project Status — May 26/26`).

**Step 7.8.2 — Check if next week's page already exists.**

Query the Project Status Meetings data source for a page with `Date of Meeting` = next-meeting-date. If one exists, do NOT create a duplicate. Surface the existing page in the response and ask Albert if he wants the Suggested Topics section added to it instead.

**Step 7.8.3 — Build the Suggested Topics bullet list.**

Two parts, combined into one flat bullet list (don't add sub-headers — keep it simple):

1. **Direct carryover** — every bullet from this week's "Suggested Next Week Discussion Topics" section, copied verbatim. These are the most concrete items.
2. **Bigger picture** — 2-4 bullets surfacing recurring themes, parked CIIs, or strategic threads that won't show up in the live task DB. Examples:
   - Open CIIs that have been sitting without movement for 2+ weeks
   - Recurring patterns flagged across meetings (e.g., "deficiency backlog still has no structural answer")
   - Strategic decisions deferred more than once
   - Cross-cutting themes from the Risk Items section that aren't single tasks

Keep the total list under ~10 bullets. If it's longer, the meeting is overloaded — trim to the 8-10 highest-signal items.

**Format each bullet as a single line.** Optional context after an em-dash. No nested bullets. No bold-prefixed headers. Just:

```markdown
## 📋 Suggested Topics for This Meeting

- Reno fix date — did Ricardo respond?
- Ray Nicolini — which option did he pick?
- May & Jason follow-up — email sent? Deduction accepted? David's $200?
- Anthony CO + David touch-up — $300 billed? Wall touch-up done?
- Marica missing-balance inquiry — did she pay?
- Jim ($12k) — payment received or still stuck in AP?
- Janet final — walkthrough done? Bin removal triggered?
- Deficiency backlog plan — structural question still unanswered (3rd meeting in a row)
- New deficiency intake workflow — first live test run this week?
```

**Step 7.8.4 — Create the page from the database template.**

Use `notion-create-pages` with the database's default template so the inherited structure (linked DBs etc.) lands automatically:

```
parent: {"data_source_id": "<project_status_meetings.data_source id, notion-destinations.json>", "type": "data_source_id"}
pages: [{
  "template_id": "<project_status_meetings.template_id, notion-destinations.json>",
  "properties": {
    "Name of Meeting": "Project Status — [Mon D/YY]",
    "date:Date of Meeting:start": "[next Tuesday's date in YYYY-MM-DD]",
    "date:Date of Meeting:is_datetime": 0
  }
}]
```

**⚠️ KNOWN ISSUE: Template instantiation OVERRIDES the `properties` block.** When you create a page with `template_id`, the template's own default `Name of Meeting` (which is the parent meeting's title) and date will replace the values you passed. The properties block above is effectively ignored at creation time for the title and date. To work around this:

**Step 7.8.4b — Immediately re-apply the title and date via `update_properties`.**

After the create call returns the new page ID, call `notion-update-page` with `command: "update_properties"` to set the correct title and date:

```
notion-update-page
  page_id: <new page ID>
  command: update_properties
  properties: {
    "Name of Meeting": "Project Status — [Mon D/YY]",
    "date:Date of Meeting:start": "[next Tuesday's date in YYYY-MM-DD]",
    "date:Date of Meeting:is_datetime": 0
  }
```

Verify by fetching the page once more to confirm both title and date now show the correct next-meeting values. If either is still wrong, re-apply.

**Do NOT add "(DRAFT)" or any suffix to the title.** Albert explicitly does not want this. The page lives alongside completed meeting pages in the database — that's fine.

**Step 7.8.5 — Prepend the Suggested Topics section.**

The template instantiation is asynchronous, so wait briefly (a few seconds via a fetch on the new page to confirm content has rendered) before inserting. Use `notion-update-page` with `command: "insert_content"` and `position: {"type": "start"}`:

```
content: ## 📋 Suggested Topics for This Meeting

- [bullet 1]
- [bullet 2]
- ...
```

This puts the section at the very top of the page, above the template's Action Items From Last Meetings linked DB.

**Hard rules:**
- Never overwrite an existing page for the same date. If a page with the next meeting's date exists, surface it and ask before doing anything.
- Bullets only in the Suggested Topics section — no headers, no tables, no nested lists.
- Keep total bullets under 10. Trim ruthlessly.
- Do NOT use a "(DRAFT)" or any suffix in the new page title. Just `Project Status — [Mon D/YY]`.
- After creating with `template_id`, ALWAYS follow up with `update_properties` to re-apply the title and date — the template instantiation overrides these values at creation time.
- Don't link tasks to next week's page automatically — that happens organically as items come up in the meeting.
- After creating + verifying, note it in the response:
  - "✅ Next week's page created for [Mon D/YY] meeting."
  - "✅ Title and date corrected after template override."
  - "✅ Suggested Topics section prepended (N bullets)."
  - Include the new page URL.

### Step 8: Assemble the final output

Use the exact section structure below. This maps 1:1 to Albert's Notion meeting template. Output in markdown, ready to paste.

## Output structure

ALWAYS use this exact template:

```markdown
# Project Status — [Meeting Date in "MMM D/YY" format]

**Attendees:** [List]
**Duration:** [duration]
**Transcript source:** [live Teams transcript | uploaded filename]

---

## ✅ Action Items From Last Meeting (Review First) ✅

| Item | Owner | Proposed Status | Verification | Source quote / reasoning |
|------|-------|-----------------|--------------|--------------------------|
| [item description] | [name] | [status] | [Needs Verification / blank] | [brief quote or paraphrase] |

---

## 📝 New Action Items (This Meeting) 📝

| Item | Owner | Due Date | Tag | Source quote |
|------|-------|----------|-----|--------------|
| [description] | [name] | [date or "—"] | [project status / meeting / parked / etc.] | [brief quote] |

---

## 🚧 Project Status Updates 🚧

### Upcoming
- **[Client name]** — [Notion link or "needs match"] — [one-line summary]

### In Progress
- **[Client name]** — [Notion link or "needs match"] — [one-line summary]

### Open Work Orders / Deficiencies
- **[Client name]** — [Notion link or "needs match"] — [one-line summary]

---

## 💰 Ready to Submit & Payments Pending 💰

- **[Client name]** — [amount if mentioned] — [status / context]

---

## ⚠️ Risk Items / Open Discussions ⚠️

- **[Short title]** — [1-3 sentence description of the issue, what was discussed, what's unresolved]

---

## 💬 Process and Marketing Updates 💬

### Marketing
- [Update with context]

### CRM / Tools
- [Update with context]

### Operations
- [Update with context]

---

## 📒 Playbook Candidates 📒

> Review and decide which (if any) to add to the Lessons Learnt (Playbook) database.

### Candidate 1
- **Lesson:** [one-sentence summary]
- **Category:** [from approved list]
- **Severity:** [Critical / Important / Minor]
- **Trigger Pattern:** [what signal would make this apply]
- **Source Meeting:** [this meeting date]
- **Action Taken:** _(to be filled in by Albert)_

---

## 📌 Today's Key Takeaways 📌

- [3-5 bullets of the highest-impact items]

---

## 🗓️ Suggested Next Week Discussion Topics 🗓️

- [Items that didn't resolve, with brief context]

---

## ⚙️ Skill Notes (for Albert's reference)

- Items flagged "Needs Verification" should be confirmed before marking as Done
- Project name matches with low confidence are flagged "needs match"
- Playbook candidates are drafts — none are auto-published
- N tactical tasks updated (append-only), M new tasks/CIIs created directly — see Task Reconciliation
- Any failed Notion writes are listed here and in Task Reconciliation, not silently dropped
```

## Quality bar

Before delivering the output, sanity-check:

1. **Action items have owners.** Every item must have an owner OR be explicitly marked "TBD — needs confirmation."
2. **No invented data.** If something isn't in the transcript, leave the field blank or mark "needs confirmation." Never fill gaps with plausible-sounding inferences.
3. **Status assignments are conservative.** When in doubt, escalate to "Needs Verification" rather than auto-closing.
4. **Project matches are explicit about confidence.** Don't link a project unless the name match is unambiguous.
5. **Filler is gone.** No "yeah, yeah," "mhm," cross-talk, China trip planning, or other off-topic content appears in the output.
6. **The output is paste-ready.** Markdown renders cleanly in Notion. Section emojis match Albert's template exactly.
7. **Task Reconciliation completed across BOTH databases, and every write logged.** Every item in the New Action Items table is first classified as Tactical or CII (Step 4.5), then mapped to either EXISTS (notes appended) or MISSING (created directly) — Step 4.6.3. No item is silently dropped, and no item is silently created without appearing in the response. CIIs are never linked to the meeting page. `Assign To`/`Due Date` on a newly-created item are set only when explicit and unambiguous in the transcript. Every create/append has a corresponding `actions-log.json` entry; any failure is surfaced, not swallowed.
8. **Synopsis lives in the summary sub-page, not the property.** The `Short Synopsis on Meeting` property on the meeting page is left EMPTY (or cleared if it had stale content). The synopsis appears at the top of the Meeting Summary sub-page as italic prose.
9. **Transcript sub-page created and linked at top** (Step 7.6). A child page exists under the meeting page with title `Transcript — [Mon D/YY]` (plain text, no emoji in title) and icon `📄` set separately. A page-link to it sits at the top of the meeting page above all H2 sections — when rendered it shows as "📄 Transcript — [Mon D/YY]". Confirmed in the response. **Verify the rendered title in the page-link does NOT show a doubled emoji like "📄 📄 Transcript — ...".**
10. **Meeting Summary sub-page created, property set, and linked at top** (Step 7.7). A child page exists with title `Meeting Summary — [Mon D/YY]` (plain text, no emoji in title) and icon `📝` set separately. The page contains the full recap (synopsis → status → payments → risks → process/marketing → playbook → reconciliation → takeaways → next week → skill notes). The `Meeting Summary` URL property points to it. A page-link to it sits at the top of the meeting page, immediately below the Transcript link — when rendered it shows as "📝 Meeting Summary — [Mon D/YY]". NO Takeaways or Next Week sections appear inline on the meeting page — they live exclusively in the summary sub-page. NO new linked-DB view blocks are created on the summary page — the Task Reconciliation section references the meeting page's existing 📝 New Action Items DB. Confirmed in the response. **Verify the rendered title in the page-link does NOT show a doubled emoji like "📝 📝 Meeting Summary — ...".**
11. **Next week's draft Project Status page created with Suggested Topics** (Step 7.8). A page titled `Project Status — [next Mon D/YY]` (NO "(DRAFT)" suffix) exists in the Project Status Meetings DB with date set to next Tuesday. The page was instantiated from the database template (so linked DBs inherit), and the title + date were re-applied via `update_properties` after creation to overcome the template instantiation override. A `## 📋 Suggested Topics for This Meeting` section is prepended at the top with a flat bullet list (≤10 bullets) combining this week's Suggested Next Week items and 2-4 bigger-picture themes. NO duplicate page exists for the same date. Confirmed in the response with the new page URL.

## Output delivery

After drafting the structured markdown:

1. **Save to file**: Write to `/mnt/user-data/outputs/project-status-[YYYY-MM-DD].md`
2. **Display inline**: Paste the full markdown into the chat response so Albert can skim it
3. **Use `present_files`** to surface the .md file for download

Both inline display and downloadable file. Albert's preference is to see it in the chat AND have a file backup.

## What this skill does NOT do

- Process audio or video — text transcript only (live VTT or uploaded `.docx`)
- Auto-publish Playbook entries — always drafts, never writes to the Lessons Learnt database
- Make decisions Albert needs to make (e.g., whether to mark something Done after a "Needs Verification" flag)
- Track patterns across meetings (a future skill could; this one only processes one transcript at a time)
- Set `Assign To` / `Due Date` on a new Tactical Task or CII unless the transcript states it explicitly and unambiguously (Step 4.6.4b) — no inferring an owner from context
- Rename, delete, or change the `Status` of an existing task or CII — appends are strictly additive
- Create a duplicate Tactical Task/CII, next week's meeting page, or a Transcript/Meeting Summary sub-page when one already exists for the same meeting/date — always surface and ask first (Steps 4.6.3, 7.6, 7.7, 7.8)
- Link a CII to an individual meeting page, ever, even though the property exists

## Reference files

- `references/titan_context.md` — Key people, project structure, name-disambiguation rules, recurring patterns. Notion database ids live in `platform-settings/notion-destinations.json`, not here.
- `references/example_output.md` — A worked example using the May 12, 2026 meeting transcript
- `scripts/clean_transcript.py` — Normalizes and strips filler from either a live WebVTT transcript or a Teams `.docx` export
- `platform-settings/notion-destinations.json` (repo root, shared with `.claude/commands/notion-sync.md`) — the `project_status_meeting_processor` block holds every Notion id, template id, and property name this skill uses
- `contracts/actions-log-schema.md`, `contracts/notion-task-schema.md` (repo root) — the audit-log format and the type-value conventions this skill's Notion writes reuse
