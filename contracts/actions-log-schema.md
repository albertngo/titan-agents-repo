# Actions Log Contract — v1

Every `*-actions` agent appends to one file per day:

```
/ingest/YYYY-MM-DD/actions-log.json
```

Unlike ingest files (overwrite), the actions log is **append-only**. Never rewrite
or delete prior entries. If the file doesn't exist, create it with an empty `entries` array.

## Structure

```json
{
  "contract_version": "1",
  "entries": [
    {
      "logged_at": "2026-07-24T09:14:00-04:00",
      "agent": "ghl-actions-agent",
      "type": "send_sms",
      "target": "conversation 8842 (contact +19055551234)",
      "content_summary": "Quote follow-up: confirmed 1200 sqft LVP pricing, offered showroom visit",
      "approved_by": "Albert, this session",
      "result": "executed",
      "error": null,
      "raw_ref": "GHL message id msg_ab12"
    }
  ]
}
```

| Field | Rules |
|---|---|
| `agent` | Which actions agent wrote this. |
| `type` | From that agent's allowed-actions table. |
| `target` | Human-readable target: who/what was acted on. |
| `content_summary` | 1 sentence. For messages, the gist — full text lives in the platform (`raw_ref`). |
| `approved_by` | How approval was given. Never blank. |
| `result` | `executed`, `failed`, `skipped_duplicate`, or `refused`. |
| `error` | String when result is `failed`, else null. |
| `raw_ref` | Platform-side ID of the created record when available. |

## Why this exists

1. **Audit** — one place to see everything the agent system *did* (vs. observed).
2. **Idempotency** — actions agents check today's log before executing, so a re-run
   never double-texts a customer.
3. **Feedback loop** — ingest agents and the daily brief may read this log to report
   "actions taken yesterday" alongside new activity.
