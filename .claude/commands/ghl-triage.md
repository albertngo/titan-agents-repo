---
description: Hourly GHL unread triage. Classifies every unread conversation with the one shared rubric, logs the verdicts, and (once switched on) marks closers and stranger spam read through ghl-actions-agent. plan_only until deliberately flipped.
---

# /ghl-triage

Make GHL's unread count mean *needs a human response*: classify every unread conversation's
unanswered batch with the one rubric, `methods/ghl-unread-triage.md`, and clear the
conversations that need nothing — closers ("sounds good, see you Tuesday") and spam from
strangers. Run by the "GHL Unread Triage" routine (hourly, 8am–9pm Toronto, Mon–Sat;
`methods/ghl-triage-routine-prompt.md`), or by hand.

```
[1] scripts/ghl_unread_pull.py --mode sweep  -> candidates.json + todo.json   read only
[2] the model reads the rubric + todo.json   -> judgements.json
[3] scripts/ghl_unread_plan.py               -> plan.json + run.json          read only
[4] policy approval (write mode only)        -> approval.json
[5] ghl-actions-agent -> scripts/ghl_mark_read.py -> results.json             the one GHL write
[6] scripts/ghl_triage_log.py append         -> branch claude/ghl-triage-log
[7] PushNotification only when something needs a person
```

Authoritative elsewhere, never restated here: the rubric, batch rule, holds and guards
(`methods/ghl-unread-triage.md`); every file's shape and the results vocabulary
(`contracts/ghl-triage-schema.md`); thresholds, caps, switches and the log branch
(`platform-settings/ghl-unread-triage.json`).

## Before you start

Stop on the first failure and report it:

1. **Read `write_mode` and `policy.approve_verdicts`** in the registry. Under `plan_only`
   this command runs steps 1–3 and 6 only: it marks **nothing** read and writes no approval
   file. Never edit either value to get a run through; flipping is a dated vault decision.
2. **Credentials come from `.env`**: `GHL_PIT_TOKEN`, `GHL_LOCATION_ID`. Under `write`,
   `GHL_WRITE_API` too — if it is missing, run as `plan_only` this time and say so in
   the notification (once a day; see step 7).
3. **The log branch is readable**: `python3 scripts/ghl_triage_log.py fetch` prints `ok`.
   `missing` (exit 3) means stop — a person runs `init` once, supervised; never run it from
   an unattended fire.
4. **Hard limits for this command**, unattended or not:
   - commit nothing on this session's own branch, push nothing but the log branch (through
     `ghl_triage_log.py` only), open no PR, never run `scripts/publish_run.py`;
   - never mark anything read except through step 5;
   - a host-blocked exit (3) is reported, never worked around.

## 1. Pull

```
python3 scripts/ghl_unread_pull.py --mode sweep
```

It prints a summary and, on its last line, the run directory
(`analysis/cache/ghl-triage/<date>/<run_id>/`). Use that directory for every step below.

It is slow on purpose (serial, rate-limited): several hundred unread conversations take
6–8 minutes. Give it a Bash timeout of at least 15 minutes and never wrap it in a shorter
`timeout`. The GHL client already retries throttling and dropped connections; if the pull
still exits non-zero, stop, run step 6 only if a run directory exists, and notify (step 7).
Do not loop the whole pull.
If it reports the kill switch, carry on through step 3 and 6, skip 4–5, and say so.

## 2. Judge

Read `methods/ghl-unread-triage.md` in full, then `<dir>/todo.json` — **only** those two.
Do not open `candidates.json`, a conversation, a contact or anything else to "check": the
classifier reads only what the customer wrote (Albert's spec). Write `<dir>/judgements.json`
per `contracts/ghl-triage-schema.md` (`ghl-triage-judgements-1`): exactly one verdict for
every `batch_key` in the todo, a paraphrased reason of 80 characters or less with no names,
numbers or addresses. When in doubt, `UNSURE`.

An empty todo (everything cached or held) needs no judgement file.

## 3. Plan

```
python3 scripts/ghl_unread_plan.py --dir <dir> [--write-approval]
```

Pass `--write-approval` only when `write_mode` is `write`. Exit codes:

| Exit | Meaning | Do |
|---|---|---|
| 0 | plan (and approval, if asked) written | go on |
| 2 | input mismatch (contract or rubric version) | stop; report |
| 4 | approval refused (plan_only, kill switch, no exception date) | expected in the pilot; skip to step 6 |
| 5 | `needs_person`: more clearable conversations than the cap — nothing approved | skip to step 6; notify (step 7) |

## 4–5. Act (write mode, approval written)

1. **Record intent first**: `python3 scripts/ghl_triage_log.py append --run <dir>/run.json`.
   If this push fails, **write nothing** and stop.
2. **Spawn `ghl-actions-agent`** with exactly: "Execute the approved
   `mark_conversation_read` actions: `python3 scripts/ghl_mark_read.py --dir <dir>`." It
   runs the script and reports its output; it originates nothing.
3. **Record results**: `python3 scripts/ghl_triage_log.py append --run <dir>/run.json
   --actions <dir>/results.json`, adding `--kill-switch "raced_new_message <run_id>"` when
   the writer exited 6.

Writer exits: 0 ok · 4 preflight refused (nothing written) · 5 an action failed (batch
stopped) · 6 a message arrived during a write (kill switch). `refused` entries with
`stale_already_read` / `stale_new_message` are the compare-and-swap working, not failures.

## 6. Record the run

```
python3 scripts/ghl_triage_log.py append --run <dir>/run.json
```

Every run, plan_only included: the log is the audit trail **and** the next run's verdict
cache. If the push fails after its retries, say so in the notification and name the
`run_id` (and, in write mode, every executed id from `results.json`) so the notification
itself is the record.

## 7. Notify — only when a person is needed

Silent on a clean run, including a clean pilot run. Otherwise one PushNotification, at most
once a day per reason (check today's `runs.json` on the log branch for an earlier `notified`
entry with the same reason; append the reason to this run's `notified` before step 6):

- `needs_person` — N conversations to clear, over the cap;
- a writer failure, a race, or the kill switch going on;
- the log push failed;
- credentials missing or the host blocked;
- the pull failed after its own retries;
- `GHL_WRITE_API` missing under `write`.

## Done means

The run record is on the log branch. Report: unread total, held by reason, judged, would
clear / cleared by verdict, reply (24h+), to action (opt-outs), FYI, and anything notified.
Never call a run complete if step 6 did not push.
