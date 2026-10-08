# GHL unread triage log

Audit log and verdict cache for `/ghl-triage` (methods/ghl-unread-triage.md).
Written only by `scripts/ghl_triage_log.py`. **Never merge this branch, never open a PR from it.** `scripts/publish_run.py` refuses it.

- `ghl-triage/<date>/runs.json` — one record per sweep (contracts/ghl-triage-schema.md)
- `ghl-triage/<date>/actions-log.json` — every mark-read attempt (contracts/actions-log-schema.md, type `mark_conversation_read`)
- `ghl-triage/KILL_SWITCH` — present = no writes until a person removes it
