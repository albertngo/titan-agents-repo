# GHL unread triage — the one rubric

**Rubric version: 3**

This file is the classifier. Both callers read it and nothing else for their judgement:

- `/ghl-triage` (`.claude/commands/ghl-triage.md`), the hourly sweep that marks closers and
  stranger spam read, and
- `ghl-ingest-agent`'s triage step inside `/daily-ingest`, which builds the brief's reply,
  to-action and FYI lists.

Do not copy its examples or rules into a command, an agent file or a routine prompt; point
here. A copy goes stale and the two callers drift apart, which is the failure this file
exists to prevent (Albert's spec, 2026-10-07: "never two copies"). Changing the rubric
means bumping `Rubric version` here **and** `rubric.version` in
`platform-settings/ghl-unread-triage.json` in the same commit; a test holds them equal,
and the bump throws away every cached verdict so nothing judged under the old rules is
reused.

Why it exists: GHL keeps a conversation unread until somebody replies, not when somebody
opens it, so the unread count fills with "sounds good, see you Tuesday". The goal is that
unread means *needs a human response*.

---

## The rubric (what the model applies)

You get one **batch** per conversation: everything the customer sent since Titan's last
human reply, oldest first, numbered. That text is all you get. You do not get their name,
our messages, the pipeline stage or any notes, and you must not assume any of it.

Judge the batch **as a whole** and return exactly one verdict:

| Verdict | Bucket | When |
|---|---|---|
| `NEEDS_RESPONSE` | reply | At least one message asks a question, raises an issue or a complaint, or asks for something we must answer in words. |
| `ACTION` | act | No reply is needed, but someone at Titan must do something: an info drop (an address, a unit or buzzer code, an email or phone number, a location), an arrival, pickup or visit notice, a payment notice, site logistics for the crew, a cancel request, or an opt-out. |
| `FYI` | know | Nothing to answer or do, but a person should know: a lost or declined job, "still deciding, I'll let you know", praise, a review or a referral, a third party, a job seeker, or a supplier or trade pitch. |
| `CLOSER` | clear | **Every** message is a pure acknowledgement: thanks, 👍, "sounds good", a reaction to one of our messages. |
| `SPAM` | clear | An unsolicited pitch or scam from a stranger: website/SEO/marketing/lead-generation/loan/crypto/"business funding" pitches, phishing, "cash offer" scams, wrong-number bulk texts. |
| `UNSURE` | reply | Anything you cannot confidently place. |

`NEEDS_RESPONSE`, `ACTION`, `FYI` and `UNSURE` are never marked read. Only `CLOSER` and
`SPAM` can be, and only once each one's switch is on (below).

Rules, in order:

1. **An opt-out outranks everything.** "STOP", "unsubscribe", "remove my number" anywhere in
   the batch makes it `ACTION` with a reason that starts `compliance:` ("compliance:
   opt-out, set DND"). Someone sets DND before anyone replies. Never `CLOSER`, `SPAM` or
   `FYI`.
2. **One open question outweighs any number of closers.** If any message needs a reply, the
   whole batch is `NEEDS_RESPONSE`, whatever else is in it. Otherwise the batch takes the
   highest of act (`ACTION`), know (`FYI`), clear (`CLOSER`).
3. **Never guess `CLOSER` or `SPAM`.** Wrongly silencing a real customer is the worst
   outcome this system can have; a wrong `UNSURE`, `ACTION` or `FYI` only costs somebody a
   glance. When in doubt, `UNSURE`.
4. **Customer's words only.** Judge what they wrote. Do not infer what we said to them,
   what stage they are at, or what they "probably meant".
5. **Suppliers and trade services are not spam.** Anything from a flooring supplier,
   distributor, manufacturer's rep, installer (one looking for work included), or a trade
   service a job site might use (bin rentals, hauling, estimating/takeoffs) — even a cold
   pitch — is `FYI`. Titan may buy from them or hire them. `SPAM` is strangers selling
   marketing, websites, leads or money, or scams (Albert, 2026-10-08).
6. **Reason** is a short paraphrase, 80 characters at most, with no names, phone numbers,
   emails, addresses or amounts: "confirming measure appointment", not "Sarah confirming
   Thursday at 14 Elm St". For `ACTION` it says what to do: "address sent, update contact
   and book measure".

Output, per batch key:

```json
{"verdict": "CLOSER", "reason": "confirming measure appointment"}
```

### Examples (Albert's spec)

| Batch | Verdict | Reason |
|---|---|---|
| "Sounds great, see you Thursday for the measure!" | `CLOSER` | confirming appointment |
| "Thanks for the quote 👍" | `CLOSER` | acknowledging quote |
| "Perfect." / "Do you carry herringbone in oak?" / "What's the lead time?" | `NEEDS_RESPONSE` | asking herringbone oak + lead time |
| "Got it thanks." / "Actually can we push the install a week?" | `NEEDS_RESPONSE` | requesting reschedule |
| "Hmm ok" | `UNSURE` | ambiguous |

### Edge cases (Albert, 2026-10-08)

| Batch | Verdict | Why |
|---|---|---|
| A bare "Ok" / "Yes" / "Sure" | `UNSURE` | It may be accepting an offer that needs us to act. It stays on the reply list (v3 review). |
| A bare time or date ("9 am", "Tuesday works") | `NEEDS_RESPONSE` | Usually answering our scheduling question; it needs a confirmation. Not an `ACTION` "confirm" (v3 review). |
| 👍 (or another emoji) alone | `CLOSER` | A pure acknowledgement. |
| A reaction ("Liked …", "Loved …") | judge the reaction itself, normally `CLOSER` | The quoted text after it is ours, not theirs. |
| Thanks or praise words alone ("Perfect, thanks"), or thanks plus agreeing to what we asked ("thanks, will do") | `CLOSER` | Pure acknowledgement: nothing to answer or do (v3 review). |
| Praise, a review left, or a referral | `FYI` | Good to know, nothing to answer. If it also asks something, rule 2. |
| A plan to follow up later, with no question ("still deciding, I'll let you know"; "busy today, will call you later") | `FYI` | Nothing to answer now, but a person should see it; the follow-up belongs to the pipeline. Was `CLOSER` in v2. |
| A lost or declined job ("went with someone else", "postponed", "over budget", "not interested") | `FYI` | A person records it in the pipeline. Was `UNSURE` in v2. |
| An opt-out ("STOP", "remove my number") | `ACTION` | Reason starts `compliance:`; someone sets DND. Rule 1. Was `UNSURE` in v2. |
| An address, a unit or buzzer code, an email or phone number, a location | `ACTION` | Update the contact or book the visit. Was `NEEDS_RESPONSE` in v2. |
| A payment notice ("sent the deposit", "e-transfer sent") | `ACTION` | Check it landed and record it. Was `NEEDS_RESPONSE` in v2. |
| An arrival, pickup or visit notice ("on my way", "coming by the shop to pay", "will collect it tomorrow") | `ACTION` | Someone has to be ready. |
| Site logistics for the crew (waste pickup, access, a material or a detail on site) | `ACTION` | Pass it to the crew or the PM. |
| A request to cancel an appointment or a job | `ACTION` | Someone has to action it. Was `NEEDS_RESPONSE` in v2. |
| A request to reschedule | `NEEDS_RESPONSE` | A new time has to be agreed in words. |
| A complaint, however polite ("floor's great but one board is lifting, thanks") | `NEEDS_RESPONSE` | |
| A conditional closer ("Sounds good, if the price holds") | `NEEDS_RESPONSE` | |
| Another language | judge it only if the meaning is clear, else `UNSURE` | |
| A trade-service pitch (bin rentals, hauling, estimating) | `FYI` | Rule 5. Was `UNSURE` in v2. |
| A supplier, manufacturer or distributor pitch, or an installer looking for work | `FYI` | Rule 5. |
| A stray line that is not a customer writing about their job (a wrong number, a note meant for someone else, a one-word reply from a supplier) | `FYI` | A glance is enough (v3 review). |
| A vague fragment that might be a customer asking or answering about their job ("next month") | `UNSURE` | |
| A cold website, SEO or lead-generation pitch ("I built you a new website", "10 leads a week, pay per appointment") | `SPAM` | Still only from a stranger — the guard below. |

These rows are Albert's rulings: v2 on the first live dry run (2026-10-08), v3 on his
review of run `20261008T1252-e2a9`, where he accepted every proposed bucket. He chose
rulings over a list of reworded real messages. Add a row when the pilot shows a pattern the
table gets wrong. No customer's words are copied here.

---

## What a batch is (applied by `scripts/ghl_unread_pull.py`, never by the model)

The batch is the run of inbound messages since Titan's last **human** reply. One
definition, used by both callers, so the sweep and the brief never disagree about who is
waiting.

| Message | Effect |
|---|---|
| Outbound text (SMS, email, WhatsApp, social, chat) with `source: "app"` and a `userId`, not failed | **Ends the batch** — a person replied |
| A connected call, either direction (`TYPE_CALL`, `meta.call.status: completed`, at least `min_call_seconds`) | **Ends the batch** — a person spoke to them |
| Outbound with `source` `workflow`, `bulk_actions`, a campaign, or any unknown source | Invisible — automations never end a batch (Albert, 2026-10-08) |
| Internal comments (incl. `[call-summary v1 …]`) and every `TYPE_ACTIVITY_*` | Invisible |
| Outbound call that did not connect | Invisible |
| Inbound text with words in it | Goes into the batch |
| Inbound with an attachment, an empty body, any call/IVR/voicemail, or an unknown type | Goes into the batch **and holds it** |

Why automations never end a batch: a customer asks "do you carry oak?", a reminder
automation fires, the customer then texts "thanks". If the reminder counted as our reply,
the batch would be just "thanks", a `CLOSER`, and the oak question would be buried. This
is stricter than `ghl-ingest-agent`'s post-call-SMS rule on purpose: that rule decides who
owes the next message for reporting; this one decides what is safe to silence. The ingest
agent applies its overlays on top of this definition (see its "Conversation analysis").

Verified live 2026-10-08 (40 unread conversations, 1,087 messages): staff messages carry
`source: "app"` with a `userId`; automations carry `source: "workflow"` or `"bulk_actions"`
and **often a `userId` too**, so `userId` alone never means a human. Inbound messages
carry no `source`. Reading a conversation or its messages through the API does not change
its `unreadCount`.

### Holds — batches the model never sees

A held batch is never marked read. Every hold behaves like `UNSURE` (the reply list), except
`no_customer_text`, and `call_in_batch` / `non_text_content`, which go on the "to action" list
with the step the registry's `action_holds` names: call back, check the attachment.

| Hold | Meaning |
|---|---|
| `no_customer_text` | Nothing inbound since our last human reply. Not ours to answer, so on no list; counted. |
| `non_text_content` | An attachment (photos, payment screenshots) or an empty body. The vault's GHL note: these are common and are often a payment proof. To action: check it. |
| `call_in_batch` | A missed call, voicemail, IVR call or short call. Someone tried to reach us. To action: call back. |
| `unknown_message_type` | A type this file does not list. Fail closed. |
| `batch_too_long` | More than `max_messages` messages or `max_chars` characters. A long unanswered run almost always holds a question. |
| `history_truncated` | No human reply found within `max_pages_back` pages. |

Two more come from the plan script: `unjudged` (no verdict for the batch) and
`invalid_verdict` (not one of the six).

### Guards — deterministic, after the model, and only ever toward a human

| Guard | Rule |
|---|---|
| CLOSER veto | Any message in the batch contains `?` or is longer than `max_message_chars` (200) → `UNSURE`. "See you Tuesday?" stays unread; a long message with a request buried in it can never be silenced. |
| Compliance | A reason that starts `compliance:` with any verdict but `ACTION` → `ACTION`. Applied first. An opt-out can never be cleared, filed as `FYI` or dropped into the backlog count. |
| SPAM stranger-only | `SPAM` stands only if the contact has **never had a human reply from Titan** (the whole history was read and no batch boundary exists), is on **no opportunity in any pipeline**, and has **no other conversation** with us. Otherwise → `UNSURE`. A spam call is a call, so it is held anyway. |

Thresholds live in the registry, `guards`.

---

## What happens to each verdict

| Final verdict | Sweep | Brief |
|---|---|---|
| `NEEDS_RESPONSE`, `UNSURE`, any hold not named below | left unread | **reply**: the "waiting on a reply" list → Notion task, 24 h flag |
| `ACTION`; holds `call_in_batch`, `non_text_content` | left unread | **act**: the "to action" list → Notion task, 24 h flag; an opt-out also gets its own attention line |
| `FYI` | left unread | **know**: the "FYI" list on the day it arrives (the customer's latest message is under 24 h old), a count after that; no task, no age flag |
| `CLOSER`, `SPAM` | marked read once its switch is on (`policy.approve_verdicts`); before that, logged as "would clear" | **clear**: off every list; listed under "would clear" / "cleared" |
| `no_customer_text` | left unread | off every list; counted |

The reply and to-action lists also drop threads whose customer has been quiet for more than
`age.backlog_days` (14) — judged by their **latest** message, so someone who wrote 20 days
ago and again yesterday stays on the list. Dropped threads show as one count line and create
no task. An opt-out is never dropped, and `FYI` never becomes backlog. The sweep still judges
them all.

## Rollout and switches

`write_mode` starts `plan_only`. Each clearable verdict has its own switch — its presence
in `policy.approve_verdicts` — and its own pilot bar (Albert, 2026-10-08):

- `CLOSER`: at least 7 days and 50 verdicts with zero wrong closers.
- `SPAM`: at least 7 days and 20 verdicts with zero wrong.

A wrong one means the rubric is fixed (version bumped) and that verdict's clock restarts.
Wrong `NEEDS_RESPONSE`/`UNSURE`/`ACTION`/`FYI` verdicts do not block a switch; they only cost
a glance. Those four never get a switch: they are not in `clearable_verdicts`, and
`scripts/ghl_unread_plan.py` refuses a registry that lists any of them there or in
`approve_verdicts`.

Turning a switch on is a dated vault decision (`05_decisions/`) plus one PR that sets
`write_mode: write`, the verdict in `approve_verdicts`, `policy.exception_date`, and the
dated CLAUDE.md exception for `ghl-actions-agent` — never an edit made to get a run through.
The pilot's backlog of clearable conversations is cleared once, supervised, at the switch;
after that the per-run cap (25, all-or-nothing) applies.

## Change log

- **v1 (2026-10-08).** First version: Albert's spec, grilled 2026-10-07/08 — human-reply
  boundary, holds for unreadable inbound, CLOSER veto, SPAM added with the stranger-only
  guard, edge cases above.
- **v2 (2026-10-08).** Albert's rulings on the first live dry run (377 unread, 177 judged):
  a plan to follow up is `CLOSER`; a cancel request and a bare time are `NEEDS_RESPONSE`; a
  vague fragment is `UNSURE`; trade-service pitches are `UNSURE`, website / lead-generation
  pitches `SPAM`. v1 verdicts in the cache are discarded by the bump.
- **v3 (2026-10-08).** Albert's review of run `20261008T1252-e2a9` (375 unread; every
  proposed bucket accepted; vault `05_decisions/2026-10-08-ghl-triage-rubric-v3.md`). Two new
  verdicts that are never marked read: `ACTION` (act) and `FYI` (know). `CLOSER` narrows to
  pure acknowledgement. A plan to follow up, a decline, praise, and supplier or trade
  pitches are `FYI`. Info drops, arrival and payment notices, site logistics, cancel
  requests and opt-outs (`compliance:`) are `ACTION`. Missed-call and attachment holds move
  to "to action". Bare times and a bare yes/ok/sure stay on the reply list. Judged against
  v3, 17 of the run's 49 `CLOSER` verdicts were wrong, all moved to `FYI` by the new rules,
  so `CLOSER`'s pilot clock restarts; `SPAM` was 3 of 3 right. v2 verdicts in the cache are
  discarded by the bump.
