# Call transcripts and call notes (GHL)

**Why (Albert, 2026-10-01):** add to the daily GHL ingest "the voice calls and the
transcripts at a high level, and attach them to the correct timestamps and the
customer" — download the .wav, run it through a better transcriber than GHL's,
cross-reference customer and message id, and feed it to the ingester. Then: "the
transcription [should be] inputted into the note section of each customer … right
after processing, as the call ends … 1. Summary 2. Next steps 3. The transcription."
**Then (2026-10-02):** name the staff member, put the call's date and time on top, and
post the Summary and Next steps as an **internal comment** on the conversation, with a
reference code into the transcript in Notes — "explicit to internal comments only. Make
a barrier to do so with no slip ups." See The comment gate.

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
| D8 | The contact note | Summary, then Next steps, then the transcript, written right after processing. **Superseded 2026-10-02 by D9** |
| D9 | Summary placement (2026-10-02) | Summary + Next steps → **internal comment** on the conversation, behind the comment gate; transcript → contact Notes; both carry the call line and `Ref C-MMDD-HHmm` |
| D10 | Staff name (2026-10-02) | The call's own GHL user if it is a person; on the shared Front Desk line `Staff`, unless the Titan person introduces themselves ("this is Joey"). Nothing else names them: not the customer using a name, not a colleague called out. Roster: `ghl-calls.json` → `staff` |
| D11 | Role labels (2026-10-02) | Every transcript line says who is talking: `Customer`, `Staff`, `Staff (Joey)` (only when D10 named Joey), `Other`; `Speaker N` only where the model could not tell. Vocabulary: `ghl-calls.json` → `staff.labels` |
| D5 | Ownership (confirmed 2026-10-02) | After a connected call, `next_response_owner` is `us` only if a commitment by us is still open |
| D6 | Sensitivity (confirmed 2026-10-02) | Provenance rule unchanged: team-level; `private` only for `intent: personal` |
| D7 | Coaching notes (confirmed 2026-10-02) | `extensions.ghl.call_quality` (private), rubric + one neutral sentence, never in items, needs_attention or the GHL note |

## How a call flows

```
call ends
 ├─ Make "GHL Call -> Note" 4951497 (real time, ~2-3 min)    [live-tested, inactive]
 │    GHL workflow webhook → recent calls on the contact → seen? → sleep 90 s
 │    → GET recording → ElevenLabs Scribe v2 → Claude: Staff, Speakers, Summary,
 │    Next steps → transcript note(s) → data store → COMMENT GATE → internal
 │    comment → read back its type → data store
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

## The comment and the note (v2, 2026-10-02)

The **internal comment**, in the conversation next to the recording:

```
📞 Call summary · Ref C-1001-1432 · transcript in Notes
Thu Oct 1, 2:32 pm · Outbound · 9m 30s · Joey

Summary
<≤ 3 sentences>

Next steps
- Us: <what> — by <when>
- Customer: <what> — by <when>

[call-summary v1 messageId=… ref=C-1001-1432]
```

The **transcript**, in contact Notes, cut every 3,000 characters and written last-first
so part 1 is on top:

```
Transcript · Ref C-1001-1432 · Thu Oct 1, 2:32 pm · Outbound · 9m 30s · Joey
[00:03] Staff (Joey): …
[00:07] Customer: …

[call-note v2 messageId=… conversationId=… engine=scribe_v2 ref=C-1001-1432 part=1/3]
```

`Ref` is the call's start in Toronto time (`C-MMDD-HHmm`), the same on both, so a
reader can go from the comment to the notes and to the recording at that time in the
conversation. The footers are the only machine-readable lines: `parse_call_summary()`
and `parse_call_note()` key on them; `render_call_summary()` and
`render_call_note_v2()` are the reference formats. v1 notes (Summary, Next steps and
transcript in one note, before 2026-10-02) still parse. Coaching never goes in either.

**Staff (D10).** Make decides the easy half itself: module 9 maps the call's `userId`
to a person (Albert, Pourya, Mike — `notion-destinations.json` people). On the Front
Desk line the summary model reports a name only if the Titan person introduces
themselves by it, and module 11 accepts it through a switch that knows the roster and
nothing else; anything else becomes `Staff`.

**Labels (D11).** The model also writes a `Roles:` line in a closed vocabulary
(`customer`, `staff`, `staff Joey`, `other`, `unclear`). Module 11 reads one role per
speaker, module 12 turns each into a label, and module 34 swaps every `] Speaker N:`
prefix for it. `staff Joey` becomes `Staff (Joey)` only when the Staff line is Joey; on
a person's own GHL user every staff line is `Staff (<that person>)`; anything the switch
does not know leaves `Speaker N`. Speakers 1–3 are relabelled; a fourth keeps its raw
label. Notes before v7 keep their `Speaker N` lines and `Speakers:` key.

"Introduces themselves" is narrow (v6 after the first live call, v7 the same
evening): the model must first write a `Name evidence:` line quoting the words in
which the Titan person says their own name ("this is Helen"), or `none`, and only then
the `Staff:` line. The customer using a name does not count (v6 let it; Albert: "Only
IF the context explicitly has us saying 'this is Joey' … then you can name the
staff"). A name the staff member calls out or asks
for while getting a colleague ("Pourya?", "let me ask Mike"), a name said about
someone else, a name used to spell something ("D for David"), or a guess that the
call was passed on are listed as not evidence. With `Staff` unnamed the Summary says
"Titan staff". Module 11 matches `Staff:` only at the start of a line, so the evidence
line is never read as the Staff value; the evidence line itself is dropped. The miss
this allows is the safe one: a name that was said but not picked up becomes `Staff`.
Staff can make this reliable by answering "Titan Flooring, this is Joey".

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

## The Make scenario (4951497, live since 2026-10-02)

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
                               diarize, audio events, 181 keyterm fields, txt format,
                               NO language_code (Scribe detects the language)
 9  Set variables: transcript ("[mm:ss] Speaker N: …" lines), ghl_user (a person or ""),
                   lang, lang_name, is_english
30  Router on call length (summary_model.long_from_seconds, 300 s):
      route 1  10 Claude haiku-4-5 (under 300 s) → 31 save "call_summary"
      route 2  21 Claude sonnet-4-5 (300 s+)     → 32 save "call_summary"
      route 3  33 read "call_summary" → 11 …     (runs after both; continues below)
    Claude writes Name evidence, Staff, Roles, Summary, Next steps; the saved value is
    "<messageId>|||<text>" and module 11 accepts only this call's
11  Set variables: staff (D10 rule), staff_label, role_1..3, summary block, Ref, date,
                   duration
12  Set variables: note header, continuation header, comment text, lab_1..3 (D11)
34  Set variables: tx — the transcript with every "] Speaker N:" swapped for its label
13  Repeater N → 1
14  GHL: Add a note to the contact — labelled transcript, n equal parts (GHL connection 4426112)
15  Transform to JSON: the comment text                [filter: last part]
16  Set variables: the request body
17  Data store: record the call, comment "pending", language
40  Router (routes run independently):
      route 1  45 Data store: kill switch set?
               18 HTTP POST /conversations/messages  key 97843   [COMMENT GATE + kill switch]
               19 HTTP GET the new message           key 97841   (read back)
               20 Data store: comment "posted" + the type GHL reports
               47 Data store: SET the kill switch      [only if the type is not an internal comment]
               46 WhatsApp Albert (2Chat): ALARM + contact link
      route 2  41 Claude sonnet-4-5: translate to English   [only if not English]
               42 Set variables → 43 Repeater → 44 GHL note "Translation (English, from …)"
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
  are plain HTTP GETs with key 97841; the connection is used only by module 14.
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
  estimate of 10,000. **The summary model switches on call length (Albert, 2026-10-02):**
  Haiku 4.5 under 5 minutes (~7 credits of summary on a 9.5-minute call), Sonnet 4.5 from
  5 minutes, where messy calls make the stronger model worth ~2.4× the tokens. The
  router costs 2 operations (save, read). Make's Claude module cannot take its model
  from a formula, hence one module per route. A fire that finds nothing new costs 4–5
  operations.
- **Governance.** The notes and the comment are GHL writes performed by Make, outside
  the `ghl-actions-agent` approval gate, like Website Inquiry Ingester and the Stage
  scenarios. It writes exactly those two things.

Confirmed on the first live run (2026-10-02): GHL accepts a 4,028-character note, and
Make's `replace()` honours `$n` back-references (module 9's output is clean
`[mm:ss] Speaker N:` lines). The GHL workflow's webhook body works with the scenario's
`ifempty(contact_id; customData.contact_id)` lookup (first live call, 2026-10-02).

## Other languages (2026-10-02)

Albert: *"Can you also do language detection and translation? Eg, chinese/vietnamese/farsi"*.
Chinese means Mandarin **and** Cantonese.

- **Detection.** Scribe v2 detects the language when no `language_code` is sent. Until
  this change the request forced `en`, which renders a Vietnamese call as garbled
  English; both the Make module and `ElevenLabsEngine` now leave it out. The detected
  code lands in the data-store record and, through the translation notes, in the run file.
- **The comment is always English**, whatever the call's language; its first line names the
  language and points to the translation (`📞 Call summary · Ref … · Vietnamese call,
  transcript + English translation in Notes`).
- **The translation** is its own note series next to the original transcript:
  `Translation (English, from Vietnamese) · Ref C-… · <call line>`, one line per original
  line with the same `[mm:ss] Label:` prefix as the labelled transcript (D11), footer
  `[call-translation v1 messageId=… ref=… lang=… part=k/N]`. Sonnet writes it — non-English
  calls are the minority and quality matters there. It runs on its own route, so it can
  neither block nor be blocked by the comment. `parse_call_translation()` reads it back;
  the run file carries it as `translation`.
- **Not verified yet:** Cantonese is not in ElevenLabs' published list as found on
  2026-10-02, and no non-English call has been through the scenario. The first one of each
  is the test. GHL's own transcript (the daily fallback) is English-only.

## The comment gate

Albert, 2026-10-02: *"make it explicit to internal comments only. Make a barrier to do
so with no slip ups."* The risk is real: GHL has no permission narrower than
`conversations/message.write`, and the endpoint that posts an internal comment is the
one that texts and emails customers — only the body's `type` differs. So the barrier is
built into the request, in layers, each of which alone would stop a different slip:

1. **One token, one module.** Key 97843 holds a GHL private integration whose only
   scope is `conversations/message.write`. Module 18 is the only module that uses it;
   reads keep the read key, notes keep the GHL connection.
2. **The type is a literal and the last key.** Module 16 builds
   `{"contactId":"…","message":…,"mentions":[],"type":"InternalComment"}`. JSON parsers
   keep the last duplicate key, so even an earlier injected `type` could not win.
3. **The text is escaped.** Module 15 runs the comment through Make's Transform to JSON,
   so quotes, backslashes and newlines in a summary cannot leave the message string.
4. **The exact body is checked before sending.** Module 18's only filter — one AND
   group, so there is no OR path around it — matches the whole body against
   `comment_gate.body_regex`: these four keys, in this order, `message` a single valid
   JSON string, `mentions` empty, `type` `InternalComment`, nothing else. Tested in Make
   itself on 2026-10-02: a real body passed; a body with a raw-injected `"type":"SMS"`
   was blocked.
5. **Literal URL, redirects off.**
6. **Read-back.** Module 19 reads the new message with the read key and module 20
   records the type GHL reports. The daily script raises an **alarm** if a
   `[call-summary …]` footer is ever found on anything but `TYPE_INTERNAL_COMMENT`; the
   agent turns that into a high-priority `needs_attention` line.
7. **Instant alarm and kill switch** (Albert, 2026-10-02: "yes add the instant alarm").
   If the read-back is anything but `TYPE_INTERNAL_COMMENT` (a missing type included),
   module 47 sets the kill-switch record `comment-gate-tripped` **first** and module 46
   then WhatsApps Albert — through the same 2Chat line as the Bookkeeper Watchdog — with
   the contact's link. Module 45 reads the switch before every post, so from then on no
   summary comment is posted; transcripts and translations keep flowing. **To unblock**,
   after checking the conversation, delete `comment-gate-tripped` in data store 94694.
   Probe-tested: a simulated `TYPE_SMS` read-back tripped the switch and sent a TEST
   WhatsApp; with the switch set the gated step did not post.
8. **Tests.** `test_comment_gate`, `test_comment_gate_regex` and
   `test_instant_alarm_and_kill_switch` check every layer on the blueprint snapshot, so a
   Make UI edit that weakens one fails the suite at the next re-snapshot. The snapshot
   redacts the alarm's phone numbers (public repo).

The call is recorded in the data store (module 17) **before** the comment is posted, so a
failed comment never re-runs the notes. A record left at `comment: pending` is a
comment that did not post; the transcript is still there.

What the gate cannot stop: a person editing module 18 in the Make UI, or using key
97843 in another scenario. Albert is the only person who edits in Make (confirmed
2026-10-02); the snapshot is re-taken and the tests re-run after every UI change. The
alarm's WhatsApp was confirmed received on Albert's phone (2026-10-02, the probe's TEST
message), and the "Call Status" workflow has the webhook as its only action (confirmed
the same day).

## What it never does

- The script never writes to GHL. Make writes the transcript notes and one internal
  comment per call, and nothing else.
- The comment never reaches a customer: see The comment gate.
- Nothing lands in `ingest/<date>/` except the agent's own `ghl.json`.
- Audio, transcripts and bake-off sheets are never committed (repo is public).
- Transcript text never enters `ghl.json`; no `metrics` key is added for calls.
- A `host_blocked` engine or GHL host is reported, never worked around.
- Coaching never reaches a GHL note, `items` or `needs_attention`.

## Log

- **2026-10-03 02:09 UTC (22:09 Toronto), v7: self-introduction only, and role labels
  (Albert: "From now on, Front desk is a general 'staff'. Only IF the context explicitly
  has us saying 'this is Joey, or this is Helen, or this is Albert, etc' then you can
  name the staff deliberately. While if the number being reached is Pourya's or Albert's
  number etc, you can be sure of the name. For the transcript in notes. Can you make it
  perfectly clear speaker 1 and speaker 2 is? Customer vs staff(name) if apparent").**
  The customer greeting someone by name no longer counts (D10). The free-text speaker key
  became a closed-vocabulary `Roles:` line that Make turns into a label on every
  transcript line (D11), so a note now reads `[00:02] Staff: Good morning, Titan
  Flooring.` / `[00:04] Customer: Hi …`. The translation route reads the same labelled
  text. Probe before the push, real expressions on real model output from two calls:
  all four model runs `Staff`; roles staff/customer, plus `other` for the installer on
  the second call's speakerphone; no `Speaker N` left in either relabelled transcript.
  Live blueprint read back identical. Four real calls ran on v6 between the two pushes
  and are unchanged.

- **2026-10-02 14:58 UTC, v6: staff-name evidence (Albert: "The receiver is the front
  desk, and Joey is the one that talked as staff. Why was Pourya made as the staff?").**
  GHL logged the first live call on Front Desk, so Make correctly left the name to the
  summary model. Joey never said his own name; 18 seconds in he called out "Pourya?"
  to a colleague, and the model took that as his name, so the comment's call line, its
  speaker key and its Summary all said Pourya. A first fix that only told the model
  such names don't count still gave Pourya on Haiku (and on Sonnet, until a probe bug
  that fed it the old note headers was fixed). v6 adds the `Name evidence:` line ahead
  of `Staff:` and anchors module 11's Staff match to a line start. Probe on two real
  calls before the push: the first live call → `Staff` on Sonnet and Haiku, no Pourya
  anywhere; an earlier test call where the customer greets Joey by name → Joey on
  Sonnet, `Staff` on Haiku (safe-side miss; that call is long enough for Sonnet). Live blueprint read back identical to the snapshot. The
  comment and notes already written for the first live call still say Pourya; nothing
  rewrites them automatically.

- **2026-10-02 14:17 UTC, live.** Albert built the GHL "Call Status" workflow and switched
  the scenario on. First real call two minutes later: an 11-minute inbound call on the
  Front Desk line took the Sonnet route; 4 transcript notes, one comment read back as
  `TYPE_INTERNAL_COMMENT`, staff named Pourya (wrongly, see v6 above), no alarm, kill
  switch clear. 26 operations,
  ~42 credits. GHL's own workflows sent their usual SMS and email around the same minute;
  none came from Make.

- **2026-10-02, instant alarm.** Kill switch + WhatsApp alarm on the comment route
  (modules 45, 47, 46). Probe-tested, pushed, scenario left inactive. Albert confirmed he
  is the only person who edits in Make.

- **2026-10-02, languages.** Language detection (no forced `en`), English summaries for
  every call, and an English translation note series for non-English calls (router 40,
  route 2). Pushed to Make, scenario left inactive; waiting on a real Vietnamese, Chinese
  or Farsi call to test.

- **2026-10-02, model by call length (Albert: "make it switch depend on length").**
  Router 30 sends calls under 300 s to Haiku and longer ones to Sonnet; both write one
  execution variable tagged with the call's messageId and a third route reads it back
  into the unchanged notes-and-comment chain. The pattern was proven on a throwaway probe
  first (route order, variable output name, tag check, multi-line value).

- **2026-10-02, Haiku test.** Patricia Nelson's 570 s outbound call re-run in v2 with
  module 10 on Haiku 4.5: 4 transcript notes, one comment read back as
  `TYPE_INTERNAL_COMMENT`, Ref identical, staff named from the call (Joey), every
  speaker label keyed, summary and next steps parse. 23 operations, ~29 Make credits;
  the summary step cost ~7 credits against ~16 on Sonnet for a shorter call.

- **2026-10-02, v2 (Albert: "internal comment … make it explicit to internal comments
  only. Make a barrier to do so with no slip ups"; staff: "if the call is from or to a
  particular user, use their name; if the call is to front desk, … unless the name is
  deciphered in the context as one of the names specified. Otherwise resort to
  'Staff'").** Albert created the comment-only integration (key 97843). The gate was
  tested in Make on a probe before any write, then live on one replayed call: three
  transcript notes, then one comment that GHL read back as `TYPE_INTERNAL_COMMENT`,
  posted as the system user (no `userId`), staff named from the call on the Front Desk
  line, Ref identical in both. The other replayed call stopped at the data-store check
  (5 operations), as intended. Cost: 22 operations, ~38 credits for a 389 s call.

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
