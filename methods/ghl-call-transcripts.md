# Call transcripts and call notes (GHL)

**Why (Albert, 2026-10-01):** add to the daily GHL ingest "the voice calls and the
transcripts at a high level, and attach them to the correct timestamps and the
customer" — download the .wav, run it through a better transcriber than GHL's,
cross-reference customer and message id, and feed it to the ingester. Then: "the
transcription [should be] inputted into the note section of each customer … right
after processing, as the call ends … 1. Summary 2. Next steps 3. The transcription."

Registry: `platform-settings/ghl-calls.json`. Script: `scripts/ghl_calls_pull.py`
(read-only; GHL only through `scripts/ghl_client.py`, which can only GET). Agent:
`.claude/agents/ghl-ingest-agent.md` → "Call recordings". Make draft:
`platform-settings/blueprints/ghl-call-notes-DRAFT.json`. Tests:
`tests/test_ghl_calls.py`.

## Decisions (2026-10-01, Albert, in chat)

| # | Question | Answer |
|---|---|---|
| D1 | Where does transcription run? | **Both.** A Make scenario writes the note on the contact right after the call; the daily script reads that note, and transcribes only what Make missed |
| D2 | Which engine? | **ElevenLabs Scribe v2, locked in 2026-10-02.** Deepgram dropped and no bake-off gate (Albert, 2026-10-02, superseding "Deepgram alternate, decide after a 10-call bake-off") |
| D3 | What does the ingester extract? | Sales and lead insight, commitments and follow-ups, quote and order details, and staff call-quality notes |
| D4 | What if transcription fails? | `ghl.json` stays `status: "ok"`; `reporting.calls.status` says `error` and one `needs_attention` line says why |
| D8 | The contact note | Summary, then Next steps, then the transcript, written right after processing |
| D5 | Ownership (confirmed 2026-10-02) | After a connected call, `next_response_owner` is `us` only if a commitment by us is still open |
| D6 | Sensitivity (confirmed 2026-10-02) | Provenance rule unchanged: team-level; `private` only for `intent: personal` |
| D7 | Coaching notes (confirmed 2026-10-02) | `extensions.ghl.call_quality` (private), rubric + one neutral sentence, never in items, needs_attention or the GHL note |

## How a call flows

```
call ends
 ├─ Make "GHL Call -> Note" (real time, ~2-3 min)            [drafted, not yet built]
 │    GHL message event → filter → seen? → sleep 90 s → GET recording
 │    → keyterms → ElevenLabs Scribe v2 → Claude: Summary + Next steps
 │    → GHL contact note(s) → data store
 └─ daily, inside /daily-ingest (ghl-ingest-agent, step 0)
      scripts/ghl_calls_pull.py
        list call messages in the window → gate → contact note? → else cache?
        → else GET recording → engine → else GHL's own transcript
        → analysis/cache/ghl-calls/runs/<date>.json  (gitignored)
      agent → extensions.ghl.calls[], call_quality, conversations[].call_ids,
              message item summaries, needs_attention, reporting.calls
```

## The join

Every call message carries `id` (messageId), `conversationId`, `contactId`, `userId`
(staff, resolved through `notion-destinations.json` `people`), `direction`,
`dateAdded` (call start, UTC) and `meta.call.{status, duration}`. Utterance times are
`dateAdded` + the engine's offset, written in America/Toronto. The note footer carries
`messageId` and `conversationId`, so note ↔ message ↔ conversation ↔ contact is exact
both ways.

## The note

```
Summary
<≤ 3 sentences>

Next steps
- Us: <what> — by <when>
- Customer: <what> — by <when>

Transcript (Scribe v2 · 03:32 · inbound · 2026-10-01 09:02 · Albert)
[00:00] Speaker 1: …
[00:07] Albert: …

[call-note v1 messageId=… conversationId=… engine=scribe_v2 part=1/1 chars=…]
```

The footer is the only machine-readable line; `parse_call_note()` keys on it and
`render_call_note()` is the reference format. Over ~4,800 characters the transcript
splits into `part=k/N` notes. The continuations are written **first** so the Summary
note is the newest and shows on top. Coaching never goes in the note. The note is
team-visible in GHL by design.

## Engines (prices web-searched 2026-10-01; verify at signup)

| Engine | Price | Vocabulary | Speakers | Notes |
|---|---|---|---|---|
| **ElevenLabs Scribe v2** (in use) | ≈ $0.22/h + $0.05/h keyterms | up to 1,000 keyterms | diarization, up to 32 | audio-event tags; 3 GB upload; sync |
| AssemblyAI | ≈ $0.21/h | up to 1,000 `keyterms_prompt` | speaker labels | async upload → poll |
| OpenAI gpt-4o-transcribe | $0.006/min | free-text prompt | none in the plain model | 25 MB upload cap |
| GHL's own | free | none | 2 speakers | fallback, and the stand-in until the engine key exists (`--engine ghl` selects it explicitly) — the quality Albert is replacing |

Expected spend at 5–25 calls a day of 3–5 min: about $0.07–$0.60 a day on Scribe v2,
plus a few cents of Claude per call in Make. The per-run caps (40 calls, 120 min)
bound the script regardless.

**Keyterms** come from the registry glossary, every supplier in
`airtable-destinations.json`, staff first names, and brand and collection names from
the newest committed Airtable upload CSVs. `--write-keyterms` publishes the list to
`platform-settings/ghl-calls-keyterms.json` (no customer data) for Make to read.

## Checking quality (optional)

```
python3 scripts/ghl_calls_pull.py --hours 168 --message-id <id> … \
    --ignore-notes --bakeoff elevenlabs,ghl
```

Runs Scribe v2 and GHL's own transcript on the same calls. It writes
`analysis/cache/ghl-calls/bakeoff/<date>.md` (full text, gitignored) and prints a
scorecard with no transcript text: speakers found, keyterms heard, confidence, cost.
A transfer and a crosstalk-heavy call are the useful ones to include. This is a check,
not a decision: the engine is locked in.

## What the live account showed (2026-10-02)

- 72 hours: 87 conversations, 71 call messages — 51 completed, 16 no-answer,
  4 voicemail; 43 inbound, 28 outbound. Most calls are logged against Front Desk.
- The messages endpoint **ignores** `type=TYPE_CALL` (1,418 messages scanned for 71
  calls). The script filters `messageType` itself.
- Call status and duration live in `meta.call`.
- Recordings answer with `Version: 2021-04-15` as `audio/x-wav`, **mono, 8 kHz,
  16-bit PCM**, for completed calls and voicemails. Mono means speakers come from
  diarization, which Scribe v2 does.
- GHL's own transcript returns sentences with times in seconds, a `speaker` 0/1 and
  `mediaChannel` 1/2.
- The read token already reads recordings, transcriptions and contact notes.
- `--engine ghl --limit 2` transcribed two real calls end to end (44 and 8
  utterances, absolute Toronto timestamps) into the gitignored cache.

## The Make scenario (drafted, not built)

Module list, filters, prompt and error handling are in
`platform-settings/blueprints/ghl-call-notes-DRAFT.json`. Build it in the Make UI —
API pushes and UI edits overwrote each other on 2026-09-13
(`methods/content-folder-scenario.md`). Things that matter:

- **A new GHL message-events hook.** The existing GHL hooks all watch opportunities.
- **Transcription through the HTTP module, not the ElevenLabs app.** The app's
  speech-to-text module has no keyterms field.
- **Recording lag.** Sleep 90 s, retry once after 120 s on 404, then give up; the
  daily script picks the call up.
- **Idempotence.** A data store keyed on messageId stops a second note for the same
  call (`datastore:ExistRecord` outputs `exist`, singular).
- **Ops.** About 9 per call — about 7,000 a month at 25 calls a day, on a 40,000-op
  Core plan that already carries ~25 scenarios. Drop the voicemail lane first if the
  budget bites.
- **Governance.** The note is a GHL write performed by Make, outside the
  `ghl-actions-agent` approval gate, like Website Inquiry Ingester and the Stage
  scenarios. It writes exactly one thing.

Before activating: keychain entries for ElevenLabs and the read PIT, one manual run
on a real call, the note-length limit confirmed, and Albert's click. Then snapshot
the real blueprint into `platform-settings/blueprints/` and fill
`make_scenarios.call_notes`.

## What it never does

- The script never writes to GHL. Make writes the note and nothing else.
- Nothing lands in `ingest/<date>/` except the agent's own `ghl.json`.
- Audio, transcripts and bake-off sheets are never committed (repo is public).
- Transcript text never enters `ghl.json`; no `metrics` key is added for calls.
- A `host_blocked` engine or GHL host is reported, never worked around.
- Coaching never reaches a GHL note, `items` or `needs_attention`.

## Log

- **2026-10-02 (Albert, in chat).** Confirmed D5–D7 as built: we owe the next reply
  only if we promised something on the call; summaries are team-level unless the call
  is personal; coaching stays in the private section. Asked how to add the Make keys —
  two `API Key Auth` keys are needed (ElevenLabs and the GHL read token).
- **2026-10-02 (Albert, in chat).** "I think I'm going to switch to ElevenLabs":
  Scribe v2 locked in, Deepgram adapter and key removed, bake-off no longer a gate
  (kept as an optional Scribe v2 vs GHL check). Setup is now one key and one host.
- **2026-10-02.** Built the script, client, registry, tests and agent changes. Live
  dry run and recording probe against the account (findings above). Make scenario
  drafted, not created: it needs an ElevenLabs key and keychain entries first.
- **2026-10-01 (Albert, in chat).** Asked for call ingest; chose both paths, Scribe v2
  with Deepgram alternate pending a 10-call bake-off, all four extraction types, status
  stays ok on failure, and the Summary → Next steps → Transcript note on the contact.
