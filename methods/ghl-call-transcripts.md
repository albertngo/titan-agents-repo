# Call transcripts and call notes (GHL)

**Why (Albert, 2026-10-01):** add to the daily GHL ingest "the voice calls and the
transcripts at a high level, and attach them to the correct timestamps and the
customer" — download the .wav, run it through a better transcriber than GHL's,
cross-reference customer and message id, and feed it to the ingester. Then: "the
transcription [should be] inputted into the note section of each customer … right
after processing, as the call ends … 1. Summary 2. Next steps 3. The transcription."

Registry: `platform-settings/ghl-calls.json`. Script: `scripts/ghl_calls_pull.py`
(read-only; GHL only through `scripts/ghl_client.py`, which can only GET). Agent:
`.claude/agents/ghl-ingest-agent.md` → "Call recordings". Make scenario 4951497:
`platform-settings/blueprints/ghl-call-notes-4951497.json`. Tests:
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
 ├─ Make "GHL Call -> Note" 4951497 (real time, ~2-3 min)    [created, inactive]
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

## The Make scenario (4951497, created 2026-10-02, inactive)

Blueprint snapshot: `platform-settings/blueprints/ghl-call-notes-4951497.json`. Ids are
in `platform-settings/ghl-calls.json` → `make_scenarios.call_notes`. Once Albert edits
it in the Make UI, Make is the source of truth: re-snapshot after any UI change
(`methods/content-folder-scenario.md`).

```
GHL workflow "Call Status" (completed / voicemail) → Webhook action → Make webhook 2836060
 1  Webhook                         body carries contact_id (custom data, belt and braces)
 2  HTTP GET conversation search for the contact   key 97841 "GHL read PIT (call recordings)"
 3  HTTP GET last 20 messages of that conversation  key 97841
 4  Iterator over the messages
 5  Data store "GHL call notes written": seen?   [filter: TYPE_CALL, completed or
                                                  voicemail, ≥ 8 s, in the last 3 h]
 6  Sleep 90 s                                   [filter: not seen]
 7  HTTP GET recording        key 97841
 8  HTTP POST ElevenLabs      key 97834 "ElevenLabs STT (call notes)": scribe_v2,
                               diarize, audio events, 178 keyterm fields, txt format
 9  Set variables: transcript ("[mm:ss] Speaker N: …" lines), staff name
10  Claude (claude-sonnet-4-5, Make's Claude app): Summary + Next steps
11  Set variables: note header, part count (3,000 characters a part)
12  Repeater N → 1
13  GHL: Add a note to the contact (continuations first, Summary note last = on top)
14  Data store: record the messageId                 [filter: last part]
```

Things that matter:

- **The trigger is a GHL workflow, not Make's GHL app.** Make's GHL "Watch Events"
  covers contacts and opportunities only. The workflow needs **re-entry allowed**, or a
  contact gets a note for their first call only.
- **The scenario finds the call itself.** The webhook only has to carry the contact.
  Steps 2–5 find every recent completed call or voicemail on that contact that has no
  note yet, so a missed fire is caught by the contact's next call.
- **Transcription through the HTTP module, not the ElevenLabs app.** The app's
  speech-to-text module has no keyterms field and its "Make an API call" module cannot
  upload a file. Keyterms must be separate form fields: one JSON-array field is
  rejected (`invalid_keyword`, tested 2026-10-02).
- **Reads go through the read key, never Make's GHL connection.** Connection 4426112
  is not authorized for the conversations scope: `/conversations/search` answered
  `401 The token is not authorized for this scope` (2026-10-02), and module 2's
  Ignore handler hid it — the run simply stopped after 2 operations. Modules 2, 3 and 7
  are plain HTTP GETs with key 97841; the connection is used only by module 13.
- **The key's value is `Bearer <token>`.** The first key (97835) was saved with the
  bare token and GHL answered `401 Invalid JWT`.
- **Quote every regex in a Make formula.** `replace(x; "/…[^\n]…/g"; …)` works; a bare
  `/…[…]/` fails with "Invalid IML … Unexpected [". `validate_module_configuration`
  does not parse formulas, so only a run catches it.
- **Replay one call** by posting `{"contact_id": "…", "message_id": "…"}` to the
  webhook. The `message_id` lane of module 5's filter skips the 3-hour window, so an
  older call can be re-run (a call already in the data store still stops at module 6).
- **Sequential processing is on**, so two fires for the same contact cannot both write.
- **Failures are silent by design.** Steps 2, 3, 7 and 8 ignore errors: no note, and
  the daily script transcribes the call instead.
- **Splitting.** Parts are cut every 3,000 characters, which can fall mid-line;
  `parse_call_note()` rejoins the raw chunks in part order (tested).
- **Cost.** Measured 2026-10-02: 16–17 operations and **31–33 Make credits** per
  transcribed call — about half of it the Claude module's tokens (claude-sonnet-4-5,
  billed in Make credits, no connection). At 25 calls a day that is ~24,000 credits a
  month on a 40,000 Core plan that already carries ~25 scenarios: well above the first
  estimate of 10,000. Cheaper options: Haiku 4.5 in module 10 (about a third of the
  token credits), or Anthropic's API through an HTTP module with Titan's own key. A fire
  that finds nothing new costs 4 operations.
- **Governance.** The note is a GHL write performed by Make, outside the
  `ghl-actions-agent` approval gate, like Website Inquiry Ingester and the Stage
  scenarios. It writes exactly one thing.

Confirmed on the first live run (2026-10-02): GHL accepts a 4,028-character note, and
Make's `replace()` honours `$n` back-references (module 9's output is clean
`[mm:ss] Speaker N:` lines). Still to confirm: the webhook body's field name for the
contact id once the GHL workflow exists.

## What it never does

- The script never writes to GHL. Make writes the note and nothing else.
- Nothing lands in `ingest/<date>/` except the agent's own `ghl.json`.
- Audio, transcripts and bake-off sheets are never committed (repo is public).
- Transcript text never enters `ghl.json`; no `metrics` key is added for calls.
- A `host_blocked` engine or GHL host is reported, never worked around.
- Coaching never reaches a GHL note, `items` or `needs_attention`.

## Log

- **2026-10-02, live test (Albert asked: "give me 2 contacts' transcriptions and do the
  operation in GHL notes so I can see it happen").** Two real calls replayed through the
  webhook with `{contact_id, message_id}`: a 570 s outbound call (4 note parts) and a
  389 s inbound call (3 parts). Both landed Summary-on-top, Next steps, then every
  transcript line as `[mm:ss] Speaker N:`, and `parse_call_note()` reassembled both
  exactly. Three blockers on the way, all silent behind Ignore handlers and found with a
  throwaway probe scenario that wrote status codes to the data store: Make's GHL
  connection has no conversations scope (401); the first GHL key lacked `Bearer `
  (401 Invalid JWT); the ElevenLabs key held the key's *ID*, not the `sk_` secret
  (400 `api_key_id_used_as_api_key`). Albert then asked for named staff, the call's date
  and time on top, and raised posting the summary as an internal comment instead.

- **2026-10-02.** Albert created the two Make keys through a credential request
  (97834, 97835). Make scenario 4951497 created inactive, with webhook 2836060 and data
  store 94694. Make's GHL trigger cannot watch messages, so a GHL "Call Status"
  workflow fires it. Tested against ElevenLabs first: one JSON-array keyterms field is
  rejected, repeated fields work, and the txt format gives one line per speaker turn.
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
