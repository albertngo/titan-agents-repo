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
| `raw_ref_action_id` | Optional. The plan action `id` this entry executed. Present on catalogue-sync entries; that is what makes resume work. |

## Type vocabulary

Each value belongs to exactly one agent's allowed-actions table.

| type | Agent |
|---|---|
| `send_sms`, `send_email`, `move_stage`, `add_tag`, `remove_tag`, `create_task` | `ghl-actions-agent` |
| `notion_create_task`, `notion_update_task`, `notion_create_page` | `.claude/commands/notion-sync.md`, `project-status-meeting-processor` |
| `lightspeed_create_product`, `lightspeed_update_product` | `lightspeed-actions-agent` |
| `airtable_upsert_product`, `airtable_backfill_ls_id`, `airtable_create_price_history` | `airtable-actions-agent` |

There is deliberately **no delete or deactivate value for any platform**. Removing a
product from the POS or a record from the catalogue is a person's decision made in
that platform's UI, so no agent has a type for it and none may be added.

## Resume, for the catalogue sync

The catalogue-sync agents are the first to run batches large enough that a run can be
interrupted part-way — by a Lightspeed rate limit, or by the stop-the-batch rule
after one bad row. They need no separate state file:

- A plan action `id` is a stable hash of supplier + sku + target system + op, so the
  same logical change gets the same id on every re-run.
- A writer records that id in `raw_ref_action_id`.
- Before executing, a writer reads today's log and skips any id already `executed`.

So resuming is just running the command again. This is the same idempotency rule the
GHL agent already follows, keyed on an id instead of on target + content.

## Why this exists

1. **Audit** — one place to see everything the agent system *did* (vs. observed).
2. **Idempotency** — actions agents check today's log before executing, so a re-run
   never double-texts a customer.
3. **Feedback loop** — ingest agents and the daily brief may read this log to report
   "actions taken yesterday" alongside new activity.
