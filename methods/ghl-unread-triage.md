# GHL unread triage — the one rubric

**Rubric version: 1**

This file is the classifier. Both callers read it and nothing else for their judgement:

- `/ghl-triage` (`.claude/commands/ghl-triage.md`), the hourly sweep that marks closers and
  stranger spam read, and
- `ghl-ingest-agent`'s triage step inside `/daily-ingest`, which builds the one "waiting on
  us" list.

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

| Verdict | When |
|---|---|
| `NEEDS_RESPONSE` | At least one message asks a question, raises an issue, requests something, or gives us something we must act on. |
| `CLOSER` | **Every** message is a confirmation, acknowledgement, thanks or sign-off. |
| `SPAM` | An unsolicited pitch or scam from a stranger: SEO/marketing/loan/crypto/"business funding" pitches, phishing, "cash offer" scams, wrong-number bulk texts. |
| `UNSURE` | Anything you cannot confidently place. |

Rules, in order:

1. **One open question outweighs any number of closers.** If any message needs a reply, the
   whole batch is `NEEDS_RESPONSE`.
2. **Never guess `CLOSER` or `SPAM`.** Wrongly silencing a real customer is the worst
   outcome this system can have; a wrong `UNSURE` only costs somebody a glance. When in
   doubt, `UNSURE`.
3. **Customer's words only.** Judge what they wrote. Do not infer what we said to them,
   what stage they are at, or what they "probably meant".
4. **Suppliers are not spam.** Anything from a flooring supplier, distributor,
   manufacturer's rep, installer or trade contact — even a cold pitch — is `UNSURE`. Titan
   may buy from them. `SPAM` is strangers selling something unrelated, or scams.
5. **Reason** is a short paraphrase, 80 characters at most, with no names, phone numbers,
   emails, addresses or amounts: "confirming measure appointment", not "Sarah confirming
   Thursday at 14 Elm St".

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
| A bare "Ok" / "Yes" / "Sure" | `UNSURE` | It may be accepting an offer that needs us to act. |
| "We went with someone else" / "Not interested" / "STOP" | `UNSURE` | A person decides whether to reply or record the loss. |
| 👍 (or another emoji) alone | `CLOSER` | A pure acknowledgement. |
| "Sent the deposit" / an address / "here are the photos" | `NEEDS_RESPONSE` | We have to act on it. |
| Another language | judge it only if the meaning is clear, else `UNSURE` | |
| A reaction ("Liked …", "Loved …") | judge the reaction itself, normally `CLOSER` | The quoted text after it is ours, not theirs. |
| A complaint, however polite ("floor's great but one board is lifting, thanks") | `NEEDS_RESPONSE` | |
| A conditional closer ("Sounds good, if the price holds") | `NEEDS_RESPONSE` | |

Real Titan phrasing replaces or extends these once Albert approves the examples drafted
from live batches (spec: "replace with real Titan phrasing once live"). Examples are
reworded; no customer's words are copied here.

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

A held batch is never marked read and stays on the waiting list. Every hold behaves like
`UNSURE`, except `no_customer_text`.

| Hold | Meaning |
|---|---|
| `no_customer_text` | Nothing inbound since our last human reply. Not ours to answer, so not on the waiting list; counted. |
| `non_text_content` | An attachment (photos, payment screenshots) or an empty body. The vault's GHL note: these are common and are often a payment proof. |
| `call_in_batch` | A missed call, voicemail, IVR call or short call. Someone tried to reach us. |
| `unknown_message_type` | A type this file does not list. Fail closed. |
| `batch_too_long` | More than `max_messages` messages or `max_chars` characters. A long unanswered run almost always holds a question. |
| `history_truncated` | No human reply found within `max_pages_back` pages. |

Two more come from the plan script: `unjudged` (no verdict for the batch) and
`invalid_verdict` (not one of the four).

### Guards — deterministic, after the model, and only ever toward a human

| Guard | Rule |
|---|---|
| CLOSER veto | Any message in the batch contains `?` or is longer than `max_message_chars` (200) → `UNSURE`. "See you Tuesday?" stays unread; a long message with a request buried in it can never be silenced. |
| SPAM stranger-only | `SPAM` stands only if the contact has **never had a human reply from Titan** (the whole history was read and no batch boundary exists), is on **no opportunity in any pipeline**, and has **no other conversation** with us. Otherwise → `UNSURE`. A spam call is a call, so it is held anyway. |

Thresholds live in the registry, `guards`.

---

## What happens to each verdict

| Final verdict | Sweep | Brief |
|---|---|---|
| `NEEDS_RESPONSE`, `UNSURE`, any hold except `no_customer_text` | left unread | on the waiting list → Notion task |
| `CLOSER`, `SPAM` | marked read once its switch is on (`policy.approve_verdicts`); before that, logged as "would clear" | off the waiting list; listed under "would clear" / "cleared" |
| `no_customer_text` | left unread | off the waiting list; counted |

The waiting list also drops threads whose customer has been quiet for more than
`age.backlog_days` (14) — judged by their **latest** message, so someone who wrote 20 days
ago and again yesterday stays on the list. Dropped threads show as one count line and create
no task. The sweep still judges them.

## Rollout and switches

`write_mode` starts `plan_only`. Each clearable verdict has its own switch — its presence
in `policy.approve_verdicts` — and its own pilot bar (Albert, 2026-10-08):

- `CLOSER`: at least 7 days and 50 verdicts with zero wrong closers.
- `SPAM`: at least 7 days and 20 verdicts with zero wrong.

A wrong one means the rubric is fixed (version bumped) and that verdict's clock restarts.
Wrong `NEEDS_RESPONSE`/`UNSURE` verdicts do not block a switch; they only cost a glance.

Turning a switch on is a dated vault decision (`05_decisions/`) plus one PR that sets
`write_mode: write`, the verdict in `approve_verdicts`, `policy.exception_date`, and the
dated CLAUDE.md exception for `ghl-actions-agent` — never an edit made to get a run through.
The pilot's backlog of clearable conversations is cleared once, supervised, at the switch;
after that the per-run cap (25, all-or-nothing) applies.

## Change log

- **v1 (2026-10-08).** First version: Albert's spec, grilled 2026-10-07/08 — human-reply
  boundary, holds for unreadable inbound, CLOSER veto, SPAM added with the stranger-only
  guard, edge cases above.
