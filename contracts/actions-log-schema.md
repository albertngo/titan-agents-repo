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
| `lightspeed_create_product`, `lightspeed_update_product`, `lightspeed_delete_product` | `lightspeed-actions-agent` |
| `airtable_upsert_product`, `airtable_backfill_ls_id`, `airtable_create_price_history` | `airtable-actions-agent` |
| `social_schedule_post`, `social_update_post`, `social_reschedule_post`, `social_flag_manual` | `social-actions-agent` |
| `notion_write_troubled_table`, `notion_update_page` | `.claude/commands/catalog-sync.md` |

`notion_write_troubled_table` writes the troubled-SKU table into a Price Lists page
body (`contracts/troubled-skus-schema.md`, "The `Action` column"). It replaces the
run's own rows and **never** touches a reviewer's `Action` cells, which is why it is
a distinct type rather than a `notion_update_task`: the thing worth auditing about it
is that it did not overwrite somebody's answer.

`notion_update_page` is every other write a catalogue run makes to its Price Lists
row: tracker properties, `Notes`, re-attaching `Extracted Files` after step 5a, or a
dated update section in the page body. It was in use from 2026-09-22 before this
table named it (added 2026-09-23).

**Deleting a catalogue product: a person's decision, never a policy one (2026-09-24,
Albert — replacing "no delete value for any platform").** `lightspeed_delete_product`
exists for one case: a product the supplier's newest list
no longer carries, which Albert has said to remove ("If they don't exist in the newest,
delete them", FAW PL-377). The rule that survives is who decides. A delete action
executes only under an approval file whose `approved_by` names a person;
`scripts/lightspeed_push.py` refuses one under the policy auto-approval, and
`catalog-plan-schema.md` lists delete as a carve-out policy never clears. The type
is never emitted by the reconciler, so a delete is always hand-planned against a named
instruction. Deactivation has no type of its own: it is a `lightspeed_update_product` of
`is_active` plus an `airtable_upsert_product` of `Active`, on a person's instruction only
(first used 2026-09-24, FAW ENG-FAWK-0060/0065, which Albert chose over deleting). Nothing
deletes or deactivates a record that the newest list still prints. Lightspeed's delete archives the product (`deleted_at`) and
keeps its sales history. **The Airtable record is removed by a person in Airtable's
UI**: `airtable-actions-agent` carries no delete tool, and granting it one was
deliberately not done by a session (2026-09-24). Delete both sides together; a
Lightspeed product deleted while its Airtable record stays leaves a dangling
`Lightspeed ID` that the reconciler blocks as `uuid_not_in_lightspeed`.

The same rule binds the social types, and binds harder. There is **no value for
deleting or editing a live post, and none for replying to a comment or a DM** — a
published post has already been seen, so an agent "fixing" one cannot undo that, and
speaking to a customer under Titan's name is never a thing an agent originates.
`social_update_post` exists only to amend a post that is still *scheduled or drafted*
inside Metricool and has not gone out.

`social_flag_manual` is the odd one: it records that a run deliberately did **not**
publish something — a Decorated Story whose stickers the API cannot set, a TikTok
story the API cannot post at all. It is logged with `result: "refused"` and is a
success, not a failure. Without it, "we chose not to post this" and "we silently
failed to post this" look identical in the log a week later.

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
