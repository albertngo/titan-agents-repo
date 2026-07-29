---
description: One-time backfill — analyze all historical Project Won opportunities to inform the Meeting-scheduled follow-up sequence.
---

Backfill `won_records` for **all** historical won opportunities and write a summary
report. This is NOT part of the daily flow — run it only when Albert asks.

## Why this exists

There is currently no follow-up sequence for the `*Meeting (Scheduled)* CCAM|GHL`
stage. Albert is designing one from real data rather than guesswork. This command
answers: which sources win, how long each takes, how many touches it costs, and
what the appointment actually contributes.

## Scope

All opportunities with `status: "won"` (~297 as of 2026-07-25), across:
- `(2) PROJECT: Sales Pipeline` → `2. *Project Won* ` — project work
- `STORE: Material Pipeline` → `6a. Closed - Won` — retail material

**Report these two separately.** They are different businesses with different
cycles; averaging them produces a number that describes neither.

## Prerequisite

An existing implementation already does the heavy pull:
**`analysis/ghl_win_timeline.py`** — pages all won opportunities, their contacts,
and full conversation histories; computes durations, appointment timing, touch
counts, response times, and cadence; caches raw pulls under `analysis/cache/` so
re-runs are cheap.

**Run that script first** rather than re-implementing it:

```bash
python3 analysis/ghl_win_timeline.py          # incremental, uses cache
python3 analysis/ghl_win_timeline.py --refresh # full re-pull
```

It emits `analysis/output/won_rows.csv` (one row per won deal) and
`analysis/output/stats.json` (aggregates by month, source, and appointment mode).
See `methods/ghl-analysis-framework.md` for metric definitions.

Extend the script if a needed metric is missing — do not fork it.

## Steps

1. Run the script above. Confirm `analysis/output/stats.json` exists and its
   `anomalies` block is clean (no missing close dates, no negative durations, no
   negative cycles).
2. Emit `won_records` conforming to the schema in `.claude/agents/ghl-ingest-agent.md`
   (one per won opportunity) to `/ingest/analysis/won-records.json`, using the
   field mapping below. **Do not eyeball the mapping** — the two schemas were
   written independently and the names only look aligned.
3. Write the report to `/ingest/analysis/won-analysis-<YYYY-MM-DD>.md` with these
   sections:

   **Method** — date fields used, what "first contact" means, exclusions,
   anomaly counts. State that this is a won-only view: fast sources may simply
   abandon slow leads rather than close them. Note the `abandoned` status count
   (~1,132, the largest bucket) as the missing denominator. **Say explicitly
   whether each duration is `cycle_days` (opportunity created → won) or
   `duration_days` (lead age)** — repeat customers make them differ by months, and
   an unlabelled "deal takes N days" is unreadable.

   **Headline** — win count, total value, median/p75 deal cycle (`cycle_days`),
   repeat rate, appointment rate.

   **By source** — count, value, median + p75 `cycle`, `repeat_rate`, median
   touches, appointment rate. Use the real source values from GHL, and say how many
   sources were excluded as long-tail (<3 wins) rather than silently dropping them.
   For any source under ~10 wins, give the count next to the percentile: a p75 over
   4 deals is three data points, not a window.

   **By month** — close month, count, value, median duration, top sources.

   **Appointment analysis** — the section that answers Albert's actual question.
   Compare in-home (`appt-home`) vs in-store (`appt-store`) vs both vs no
   appointment on: deal value, deal cycle, days lead→appointment, days
   appointment→won, touches before vs after the appointment. **The
   appointment→won stretch is the window the new sequence must cover** — quantify
   its length and touch count explicitly.

   **Contact-point analysis** — calls / SMS / emails separately, outbound:inbound
   ratio, automated share, median first-response time and its p75 tail.

   **Recommended sequence** — a concrete proposed cadence for the
   Meeting-scheduled stage: touch timing (day offsets), channel per touch, and the
   exit condition. Ground every number in a figure from the analysis above and cite
   it inline. Where the data cannot support a choice, say so and mark it
   `[FILL: needs Albert's judgment]` rather than inventing a number.

   **Caveats** — won-only bias, GHL-logged touches only (walk-ins and off-platform
   calls undercount), repeat customers inflating lead age.

4. Reply with the headline numbers, the recommended sequence, and anything the data
   could not answer.

## `won_rows.csv` → `won_records` field mapping

The script's columns and the `won_records` schema use different names, different
units, and different vocabularies for the same measures. Six fields aren't in the
CSV at all. Copying by name-similarity produces silently wrong records.

| `won_records` field | CSV column | Conversion |
|---|---|---|
| `opportunity_id` | `opportunity_id` | direct |
| `contact` | `name` | This is the **opportunity** name, usually but not always the contact's. Confirm against `contact_id` before it reaches a vault note. |
| `source` | `source` | direct |
| `pipeline` | — | Not in the CSV. Resolve the opportunity's `pipelineId` through `opportunities_get-pipelines`. |
| `created` | `opp_created_date` | **Not `lead_date`.** `lead_date` is `min(contact.dateAdded, opportunity.createdAt)`; `created` is the opportunity's own `createdAt`. They differ by months for repeat customers. |
| `first_contact` | — | Not in the CSV. First message in either direction, from the cached conversation pull. |
| `appointment_date` | — | Only the offset is emitted. Derive: `opp_created_date + days_opp_to_appt`. |
| `visit_type` | `appt_modes` | Vocabulary differs — see below. |
| `won_date` | `close_date` | direct |
| `value_cents` | `value_cad` | **× 100.** `value_cad` is dollars; `value_cents` is integer cents. Copying it straight understates every deal 100-fold. |
| `days_lead_to_contact` | — | Not in the CSV; depends on `first_contact`. |
| `days_lead_to_appointment` | `days_opp_to_appt` | **Anchor differs (v2).** The CSV figure is opportunity-anchored; the schema field's lead-anchored value is `days_opp_to_appt + max(0, days_contact_to_opp)`. Prefer reporting the opp-anchored number — the lead-anchored one is meaningless for repeat customers. |
| `days_appointment_to_won` | `days_appt_to_close` | rename only |
| `contact_points.{calls,sms,emails}` | `channels` | A JSON channel→count blob. Split it; don't paste it. |
| `conversation_summary` | — | Not in the CSV. Written by reading the thread. |

**Visit type is classified two different ways and they can disagree.** The daily
`ghl-ingest-agent` path reads the `appt-home` / `appt-store` **tags**; this script reads the
`Visit:` / `Store:` **body prefix** on the `TYPE_ACTIVITY_APPOINTMENT` event (see
`methods/ghl-analysis-framework.md`). A contact tagged `appt-home` whose event body says
`Store:` will classify differently depending on which path produced the record. State
which method a given record used rather than presenting the two as one field.

## Hard limits

- **Read-only against GHL.** No tags, no stages, no messages. Ever.
- `/ingest/analysis/` and `analysis/output/` are COMMITTED during the build
  phase (decided 2026-07-26). They hold customer PII and this repo is public —
  a deliberate, accepted tradeoff while the analysis matures. Findings still
  belong in the vault (`platforms/GHL.md`); this is a working corpus, not the
  place conclusions live. `analysis/cache/` stays gitignored.
- Do not write to `/ingest/<date>/` — that namespace belongs to the daily flow.
- If credentials are missing, stop and say what is needed. Never fabricate rows.
