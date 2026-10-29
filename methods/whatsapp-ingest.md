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
- **History you can ask about.** 2Chat already keeps it, group chats included, so it
  is read live and never copied (see "Answering questions").
- **Personal chats never reach staff.** No `whatsapp` item ever goes to the staff
  Notion board, from either number. Personal-number items reach Albert's private to-do
  list only one at a time, on an explicit yes (the WhatsApp gate in
  `contracts/notion-task-schema.md`).

## Answering questions

2Chat is the archive (Albert, 2026-10-29). Both numbers are connected to 2Chat, a
third-party app, and it stores their 1-to-1 and group messages. Nothing is copied
anywhere else. There are two ways to read it:

1. **The pull script, any window.** For example,
   `python3 scripts/whatsapp_pull.py --hours 1440 --channel business --out analysis/cache/whatsapp/q-<date>.json`,
   then read the chat in question by `chat_name`, ordered by `sent_at`.
2. **The 2Chat MCP connector**, if Albert adds it (`https://mcp.2chat.io/mcp`, the
   same API key): `get_whatsapp_group_messages`, `get_whatsapp_messages`,
   `list_whatsapp_conversations`. It also has send and edit tools. Those must be
   switched off in the connector settings, and never used without a separate explicit
   confirmation.

Rules for both:
- Read the **personal** number only when Albert asks about personal chats, and never mix
  it into a business answer unprompted.
- Answers stay in chat, cited by chat, date and sender. Copying anything from a
  personal chat where staff can see it is ruled out by the WhatsApp gate.

**History depth (first read, 2026-10-29):** the business number goes back to
2025-08-19, its connection date (2,249 messages, no trimming seen). The personal number
starts 2026-10-29. Whether 2Chat ever trims old messages is still unknown. If it does,
revisit and copy only what's at risk.

## Design history

Designed first, and dropped the same day (2026-10-29):
- A Make capture scenario (a 2Chat webhook feeding a 14-day data store);
- two private Notion archive databases, "WhatsApp Archive — Business" and "— Personal".

At the time 2Chat's API looked like it had no group-history endpoint. Its MCP server
(`get_whatsapp_group_messages`) shows the API does serve group messages, so copying
them only cost Make operations: about 4 per message against the Core plan's
40,000 a month. The two Notion databases were created empty in Albert's Notion
Directory and trashed on his yes the same day (restorable from Notion's Trash). Meta's WhatsApp Cloud API was rejected outright: history arrives
only by webhook, connecting the business number can't be undone, and it can't reach
the personal number.

The payload fields Make documents for 2Chat (and which `normalize()` reads) are `uuid`,
`created_at`, `sent_by`, `message.text`, `message.media.type`, `remote_phone_number`,
`contact.first_name/last_name`, plus `group.uuid`, `group.wa_group_name` and
`participant.phone_number/pushname` on group messages.

## Privacy

titan-agents is public. Full message text lives only in 2Chat and in
`analysis/cache/whatsapp/` (gitignored). The committed `whatsapp.json` holds
summaries in the agent's own words, names or last-4 digits, and salted hashes
(`REQUESTER_ID_SALT`). There are never phone numbers or quotes. The personal channel is
always `private` (admin in the vault). The business channel is `private` too, by Albert's
decision of 2026-10-29 (vault `05_decisions/2026-10-29-whatsapp-business-chats-private.md`).

## Build steps and status

| Step | What | Status |
|---|---|---|
| 1 | First live read: `python3 scripts/whatsapp_pull.py --hours 72 --out analysis/cache/whatsapp/probe.json` | done 2026-10-29 (see First read below) |
| 2 | ~~Make capture scenario~~ | dropped 2026-10-29 |
| 3 | Client, pull script, tests | done 2026-10-29 |
| 4 | Agent file, registry, wiring (CLAUDE.md, departments, notion source_defaults, .env.example) | done 2026-10-29 |
| 5 | One manual run, then add to `/daily-ingest` step 2 and the step 5 ledger | after step 1 |

## First read (2026-10-29)

The pull ran on both numbers: 37 messages in 72 h (34 business, 3 personal) across
6 chats, `status: ok`, no errors. What it settled:

- **The group messages path works.** `GROUP_MESSAGES_PATH`
  (`/open/whatsapp/groups/messages/{group_uuid}`) returns the group's messages. The
  business number is in 18 groups and the personal number in 61.
- **The number-level messages endpoint returns group messages too**, not only 1-to-1.
  `session_key` is `WW-<channel uuid>-<wa id>`. The wa id ends `@g.us` for a group, and
  that is the group's `wa_group_id` from the groups list. It ends `@c.us` for a 1-to-1
  chat. `normalize()` maps a group wa id to the group's uuid and name, so a message read
  both ways dedupes to one record with the right chat.
- **Direction.** `sent_by: "user"` means the other side wrote (inbound). `agent` (the
  2Chat inbox), `api`, and null (sent from the phone) are Titan's own messages. So sent
  messages do appear, and unanswered detection can work. The first guess had `user` as
  outbound, which would have inverted every unanswered flag.
- **Senders.** `remote_phone_number` is set on 1-to-1 messages only. An inbound group
  message carries `participant.phone_number` and `pushname`. Titan's own group messages
  carry no participant, so their sender is the connected number.
- `created_at` is naive UTC. Media is `message.media.{type, url, mime_type}`. About 1
  message in 10 has neither text nor media (reactions, deletions).
- Paging: about 49 per page, newest first. Both readers now stop once a page reaches
  back past the window, so a daily run reads about one page per group.
