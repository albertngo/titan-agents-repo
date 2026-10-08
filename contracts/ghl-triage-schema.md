# GHL Triage Contract — v1

The files GHL unread triage passes between its steps, for both callers: the hourly sweep
(`/ghl-triage`) and `ghl-ingest-agent`'s triage step. Method and rubric:
`methods/ghl-unread-triage.md`. Registry: `platform-settings/ghl-unread-triage.json`.

```
ghl_unread_pull.py ──> candidates.json  (no message text)
                  └──> todo.json        (text of unjudged batches only — gitignored cache)
session model ─────> judgements.json   (reads the rubric + todo.json only)
ghl_unread_plan.py ─> plan.json + run.json, and approval.json only when write_mode is write
ghl-actions-agent ─> scripts/ghl_mark_read.py ─> results.json (actions-log entries)
ghl_triage_log.py ─> claude/ghl-triage-log: ghl-triage/<date>/runs.json + actions-log.json
```

Every per-run file lives in `analysis/cache/ghl-triage/<date>/<run_id>/` (gitignored).
Nothing is written under `ingest/<date>/` — `/daily-ingest` and `/notion-sync` read that
folder wholesale. The repo is public until Albert says otherwise, so **no file that is
committed or pushed carries customer text** unless `log.excerpts` is true.

## Ids

| Id | Form | Stable across |
|---|---|---|
| `run_id` | `YYYYMMDDTHHMM-<4 hex>` (Toronto time) | — |
| `batch_key` | `b-` + sha1(conversation id + the batch's inbound message ids, in order)[:16] | every re-run until a new inbound message arrives |
| action `id` | `gmr-` + sha1(conversation id + batch_key + last message id)[:12] | hourly re-runs over an unchanged conversation |

## `candidates.json` — `ghl-triage-candidates-1`

```json
{
  "contract_version": "ghl-triage-candidates-1",
  "run_id": "20261008T0959-a1b2", "mode": "sweep", "run_at": "2026-10-08T09:59:12-04:00",
  "rubric_version": "1", "write_mode": "plan_only",
  "log": {"ref": "origin/claude/ghl-triage-log", "status": "ok", "kill_switch": null,
          "cache_hits": 41, "last_sweep_at": "...", "sweeps_24h": 12, "cleared_24h": [], "refused_24h": [], "failed_24h": []},
  "counts": {"unread_total": 377, "window_total": 0, "conversations": 377, "unknown_outbound_sources": {}},
  "conversations": [{
    "conversation_id": "…", "contact_id": "…", "contact": "First L.", "channel": "sms",
    "unread": true, "unread_count": 2, "in_window": false,
    "last_message_id": "…", "last_message_at": "…",
    "batch": {"message_ids": ["…"], "n": 2, "first_at": "…", "last_at": "…",
              "chars": 64, "max_message_chars": 41, "has_question": false},
    "batch_key": "b-…", "hold_reason": null,
    "stranger": false, "owner_by_reply": "us", "waiting_hours": 30.5, "last_inbound_hours": 2.1,
    "cached": {"verdict": "CLOSER", "reason": "confirming measure appointment", "run_id": "…"},
    "excerpt": null
  }]
}
```

`owner_by_reply` is `us` exactly when the batch is non-empty. `stranger` is true only when
the whole history was read with no batch boundary, the conversation row lists no
opportunity, and the contact has no other conversation. `excerpt` is filled only when the
registry's `log.excerpts` is true.

## `todo.json` — `ghl-triage-todo-1`

The only file with message text. Holds just the batches that need a judgement this run
(not held, not cached), keyed by `batch_key` — no names, no ids beyond the key.

```json
{"contract_version": "ghl-triage-todo-1", "rubric_version": "1",
 "batches": [{"batch_key": "b-…", "messages": [{"n": 1, "channel": "sms", "text": "…"}]}]}
```

## `judgements.json` — `ghl-triage-judgements-1`

Written by the session model after reading `methods/ghl-unread-triage.md` and `todo.json`,
nothing else. One entry per `batch_key` in the todo; `reason` ≤ 80 characters, paraphrased.

```json
{"contract_version": "ghl-triage-judgements-1", "rubric_version": "1",
 "judged_at": "2026-10-08T10:00:03-04:00",
 "verdicts": {"b-…": {"verdict": "CLOSER", "reason": "confirming measure appointment"}}}
```

A wrong `contract_version` or `rubric_version` stops the plan (exit 2). A missing entry is
held `unjudged`; a verdict outside the four is held `invalid_verdict`.

## `plan.json` — `ghl-triage-plan-1`

```json
{
  "contract_version": "ghl-triage-plan-1",
  "run_id": "…", "mode": "sweep", "run_at": "…", "expires": "…",
  "write_mode": "plan_only", "rubric_version": "1",
  "approve_verdicts": [], "status": "ready",
  "summary": {"conversations": 377, "by_verdict": {}, "held_by_reason": {}, "guarded": {},
              "would_clear": 0, "actions": 0, "waiting": 0, "waiting_24h_plus": 0, "backlog": 0},
  "rows": [{
    "conversation_id": "…", "contact_id": "…", "contact": "First L.", "channel": "sms",
    "unread": true, "batch_key": "b-…",
    "model_verdict": "CLOSER", "verdict": "UNSURE", "verdict_source": "model",
    "guard": "closer_veto:question", "hold_reason": null, "reason": "…",
    "disposition": "waiting", "waiting_hours": 30.5, "age_flag": true,
    "action_id": null
  }],
  "actions": [{"id": "gmr-…", "seq": 1, "op": "mark_read", "conversation_id": "…",
               "contact_id": "…", "verdict": "CLOSER", "reason": "…", "batch_key": "b-…",
               "expect": {"last_message_id": "…"}}]
}
```

| Field | Values |
|---|---|
| `verdict_source` | `model`, `cache`, `hold` |
| `verdict` | the four verdicts, or `HELD` |
| `guard` | `closer_veto:question`, `closer_veto:length`, `spam_not_stranger`, or null |
| `disposition` | `clear` (CLOSER/SPAM), `waiting`, `not_ours` (`no_customer_text`), `backlog` (brief only: the customer's **latest** message is older than `age.backlog_days`) |
| `status` | `ready`, or `needs_person` when actions exceed `policy.max_mark_read_per_run` — then **nothing** is approved |

`actions[]` holds only `clear` rows whose verdict is in `policy.approve_verdicts`, in sweep
mode, on a conversation that is still unread. During the pilot `approve_verdicts` is empty,
so `actions` is empty and the `clear` rows are the "would clear" list.

## `approval.json` — `ghl-triage-approval-1`

Written only by `ghl_unread_plan.py --write-approval`, which refuses (exit 4) in brief mode,
under `write_mode: plan_only`, with the kill switch present, or while
`policy.exception_date` is null; and (exit 5) when the plan is `needs_person`.

```json
{"contract_version": "ghl-triage-approval-1", "run_id": "…", "plan": "<path>",
 "approved_by": "policy: ghl-unread-triage auto-approval (rubric v2)",
 "decisions": [{"id": "gmr-…", "status": "approved", "at": "…"}]}
```

**Absence of an approval file means nothing is approved.** Held rows carry no `id`, so they
cannot be approved by anyone. A person may approve a `needs_person` plan in a supervised
session with `--approved-by "<name>, this session"`; that still requires `write_mode: write`.

## `run.json` and the log branch — `ghl-triage-day-1`

The plan script also writes `run.json`, one run record. `scripts/ghl_triage_log.py append`
merges it into `ghl-triage/<date>/runs.json` on branch `claude/ghl-triage-log`:

```json
{"contract_version": "ghl-triage-day-1", "date": "2026-10-08",
 "runs": [{"run_id": "…", "run_at": "…", "mode": "sweep", "write_mode": "plan_only",
           "rubric_version": "1", "status": "ready", "approved_by": null,
           "summary": {}, "rows": [{"conversation_id": "…", "contact_id": "…",
           "batch_key": "b-…", "model_verdict": "…", "verdict": "…", "verdict_source": "…",
           "guard": null, "hold_reason": null, "reason": "…", "disposition": "…",
           "waiting_hours": 30.5, "action_id": null, "excerpt": null}],
           "notified": []}]}
```

Rows carry no contact name and no message text (only `excerpt`, and only when
`log.excerpts` is true). These rows are also the verdict cache: the next pull reuses a
`model_verdict` whose `batch_key` and `rubric_version` both match and whose source was
`model` or `cache`. Guards are re-applied every run, never cached.

The writer's entries go to `ghl-triage/<date>/actions-log.json` on the same branch, in the
`contracts/actions-log-schema.md` shape, type `mark_conversation_read`. `ghl-triage/KILL_SWITCH`
(any content) stops every write until a person removes it.

Only `ghl_triage_log.py` writes the branch: git plumbing, no checkout, no force push, never
merged, never PR'd (`scripts/publish_run.py` refuses it).

## Results vocabulary (`mark_conversation_read`)

| `result` | `error` | Meaning |
|---|---|---|
| `executed` | null | `unreadCount` read back 0 and no new message arrived |
| `refused` | `stale_already_read` | someone read or answered it between plan and write — success of the compare-and-swap |
| `refused` | `stale_new_message` | a new message arrived between plan and write — success of the compare-and-swap |
| `skipped_duplicate` | null | this action id was already `executed` |
| `failed` | `readback_mismatch` | the PUT returned but `unreadCount` is not 0 |
| `failed` | `raced_new_message` | a message arrived during the write; trips the kill switch |
| `failed` | `http_<code>` | GHL refused the write |

A `failed` entry stops the batch.
