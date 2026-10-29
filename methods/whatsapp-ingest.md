# WhatsApp ingest (via 2Chat)

Started 2026-10-29 on Albert's request: bring WhatsApp into the daily ingest the way GHL,
Outlook and Notion already are. In scope: supplier groups (e.g. the Sidco group, where
orders, pickups and payment requests happen), customer chats, staff groups, and Albert's
personal number. Serves Q4 goals S1 (WhatsApp leads went unanswered for 14–23 h), A1 and T3.

Agent: `.claude/agents/whatsapp-ingest-agent.md` · Registry:
`platform-settings/whatsapp-ingest-sources.json` · Scripts: `scripts/whatsapp_pull.py`,
`scripts/twochat_client.py` · Tests: `tests/test_whatsapp_ingest.py`.

## What it is for (Albert, 2026-10-29)

The main use is **asking questions** about past discussions: what was ordered or
promised in a supplier group, what a client agreed to in a project group, and pulling
those details into sales, orders and payments (e.g. the Sidco statement check done by
hand on 2026-10-29). The daily ingest comes second. That means:

- **Open-ended chats.** Supplier groups, client project groups, staff groups and
  1-to-1 customers, with more kinds as they appear. The agent classifies from context,
  and the registry only overrides.
- **A long-term archive** is needed. The 14-day capture buffer can't answer "what did
  Sidco say in September". Where it lives is an open decision (below).
- **Personal chats never reach staff.** No `whatsapp` item ever goes to the staff
  Notion board, from either number. Personal-number items reach Albert's private to-do
  list only one at a time, on an explicit yes (the WhatsApp gate in
  `contracts/notion-task-schema.md`).

## Why two lanes

Both numbers are connected to 2Chat, a third-party app. 2Chat's API returns 1-to-1
messages (only those since the number was connected) and lists groups, but documents
**no group-history endpoint**. It does fire webhooks for both kinds
(`whatsapp.message.received`, `whatsapp.group.message.received`). So:

1. **Capture (primary).** A Make scenario, "2Chat -> WhatsApp Log", subscribes to those
   webhooks for both numbers and writes one record per message into a Make data store,
   keyed on the 2Chat message uuid. The fields are listed in the registry under
   `capture.record_fields`. A scheduled step deletes records older than 14 days: the
   store is a rolling buffer, not an archive (earned relevance, vault CONVENTIONS rule 4).
2. **API (backstop).** `scripts/twochat_client.py` reads 1-to-1 messages directly, so a
   missed webhook is not a lost message, and maps group uuids to names.

Both lanes are GET-only from this repo. Make is the only thing that writes, and only to
its own data store.

Meta's WhatsApp Cloud API was rejected: history arrives only by webhook, connecting the
business number is a one-way switch (coexistence can't be undone), and it can't reach the
personal number.

## Privacy

titan-agents is public. Full message text lives only in the Make data store (14 days)
and in `analysis/cache/whatsapp/` (gitignored). The committed `whatsapp.json` holds
summaries in the agent's own words, names or last-4 digits, and salted hashes
(`REQUESTER_ID_SALT`). There are never phone numbers or quotes. The personal channel is
always `private` (admin in the vault). The business channel is `private` until Albert
decides otherwise.

## Build steps and status

| Step | What | Status |
|---|---|---|
| 1 | Probe: with `TWOCHAT_API_KEY` set, run `python3 scripts/whatsapp_pull.py --lane api --hours 72 --out analysis/cache/whatsapp/probe.json`, then pin the real field names in `normalize()` | waiting on the key |
| 2 | Make capture scenario + data store + 14-day prune; show Albert the blueprint before activating | not started |
| 3 | Client, pull script, tests | done 2026-10-29 |
| 4 | Agent file, registry, wiring (CLAUDE.md, departments, notion source_defaults, .env.example) | done 2026-10-29 |
| 5 | One manual run, then add to `/daily-ingest` step 2 and the step 5 ledger | after 1–2 |

## Open decisions (Albert)

- **Where the long-term archive lives**, so questions can reach back months. The
  options are a private Notion database only Albert can see, written by the same Make
  scenario; a longer-lived Make data store; or a private Airtable base.

- Should business-number chats default to **team** (staff already see them in the shared
  2Chat inbox) or stay **private**? Flipping it is a dated vault decision.
- Does the 2Chat plan deliver outbound/echo events? Without them, "unanswered" can only
  come from the API lane, and the agent says so rather than flagging every chat.
