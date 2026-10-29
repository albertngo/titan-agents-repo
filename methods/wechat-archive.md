# WeChat archive and ingest

Built 2026-10-29 on Albert's request: "a lot of supplier messages are made there". He
wants every WeChat message that isn't recorded yet archived to a private Notion
database, so he can ask questions about past conversations and the daily brief
can see them.

## Shape

```
WeChat for Mac  --(Accessibility API, Albert's Mac)-->  scripts/wechat_archive.py
                                                              | insert only
                                                              v
                                             Notion: WeChat Archive (private)
                                                              | read only
                                                              v
                       scripts/wechat_pull.py  -->  wechat-ingest-agent  -->  ingest/<date>/wechat.json
                       (also: --search for questions)
```

- **No API exists** for a personal WeChat account, and Tencent publishes no
  connector. The reader is the open-source `wechat-mcp-server`
  ([BiboyQG/WeChat-MCP](https://github.com/BiboyQG/WeChat-MCP), MIT), pinned to
  commit `cc47036` after reading it. Only its read functions are imported; its
  reply, add-contact and Moments functions never are (`tests/test_wechat.py`).
- **The Mac writes, the cloud reads.** The archive is the hand-off, so no new repo
  is needed (Albert, 2026-10-29: "Can you not put this into a private Notion
  database so that I don't have to create a new repo?"). The agents repo is public,
  so raw messages never go there; `wechat.json` carries summaries without numbers.
- **Owner: General** (`platform-settings/departments.json`), beside `outlook`.
  **Sensitivity: private.** It's Albert's own phone, which staff never see.

Settings: `platform-settings/wechat.json`. Database: **WeChat Archive**, a private
page at the top of Albert's Notion workspace.

## How the archiver reads (and why it needs the Mac to itself)

It drives the real app: it brings WeChat to the front, clicks a chat in the sidebar,
scrolls the history and takes a screenshot of the message area. The screenshot is how
it tells **Me** from **Them**: the bubble side, a pixel heuristic. Sender can come back
as `Unknown`. It reads only what WeChat shows as text: an image is `[Image]`, a file
is `[File] name`. Attachments themselves are not archived.

So it:
- never runs on a locked screen, and starts only after 2 minutes without keyboard
  or mouse input;
- stops between chats as soon as someone touches the Mac (`interrupted`; the next
  attempt picks up where it stopped, because nothing it wrote is lost);
- keeps the Mac awake while it runs (`caffeinate`);
- reads at most `max_chats` chats from the top of the sidebar, newest first.

**When it runs.** launchd starts it every 30 minutes. It runs the first time after
06:00 that the Mac is unlocked and idle, then not again for 20 hours. Attempts that
aren't due, or that find the Mac locked or busy, exit without writing anything. A day
with no completed run shows up as a stale heartbeat in the brief.

## What "not recorded yet" means

There is no message id and no per-message timestamp on screen. Per chat:

1. Read the chat's last 20 stored rows (its tail) from Notion.
2. Read the last 30 messages on screen. Drop WeChat's time separators: they only
   stamp `Sent at` on the messages below them, and they are never used for matching
   because WeChat rewrites them ("10:42" becomes "Yesterday 10:42").
3. Line the stored tail up with the screen on text, needing at least 3 messages to
   agree, and insert everything after the match.
4. No match: read up to 200 messages back and try again. Still no match: insert what
   was read, tick **Gap before** on the first row, and report the chat. This happens
   when more than 200 messages arrived between runs, or a message was edited or
   recalled inside the overlap.

A chat seen for the first time starts 100 messages back; anything older is not
archived. Each row's **Message key** chains the previous key, so two identical "ok"s
stay two rows. **Sequence** numbers each chat's rows in order.

The archiver also refuses to write when the chat that opened isn't the one it
clicked, so one chat's messages are never filed under another's name.

## The heartbeat

Every completed, partial, interrupted or failed run inserts one row in the
pseudo-chat `(archiver)` with a JSON summary. A repeated error is written at most
every 6 hours. `wechat-ingest-agent` reports the newest heartbeat, so a dead Mac is
a finding, not a quiet day.

## Write boundary

`scripts/wechat_archive.py` is the only file that writes the archive, and the only
write it can make is `POST /v1/pages` into that one data source. Its Notion integration
has **Read content + Insert content, never Update content**, so no row can be edited or
deleted, even by mistake. Everything else (`wechat_notion.py`, `wechat_pull.py`) can only
query, using a separate Read-content-only integration. `tests/test_wechat.py` pins all of
this.

This is a platform write that sits outside the `*-actions` approval gate, like
`ghl_triage_log.py` and the Make call-note scenario. It's an archive of what already
happened, and it can only add rows.

## Setup (once, on the Mac)

1. **Two Notion integrations** (notion.so/profile/integrations, Internal):
   - `Titan WeChat Archive — writer`: capabilities **Read content** and **Insert
     content** only. Untick Update content and all user and comment capabilities.
   - `Titan WeChat Archive — reader`: **Read content** only.

   Open the WeChat Archive database, then `•••` → Connections, and add both. Share
   nothing else with either.
2. In the Mac's clone of this repo, put the writer secret in `.env` as
   `NOTION_WECHAT_WRITE_TOKEN=…`. **Never put the writer token in the cloud
   environment**: the session-start hook copies any `.env.example` key it finds
   there into `.env`.
3. Put the reader secret in the cloud environment as `NOTION_WECHAT_READ_TOKEN`
   (and in the Mac's `.env` too, to search from there).
4. `zsh scripts/wechat_install_mac.sh` creates `.venv-wechat/`, installs the pinned
   reader and loads the LaunchAgent. It prints the Python path to grant **both**
   Accessibility and Screen Recording in System Settings → Privacy & Security.
   **Grant the same two to Terminal (or iTerm) as well.** macOS checks the app that
   started a process: scheduled runs come from launchd and use the Python grant, while
   supervised runs typed in Terminal use Terminal's.
   **Lock timing:** the archiver needs about 2 idle minutes on an unlocked screen
   before it starts. If the Mac locks or the display turns off sooner than that
   (System Settings → Lock Screen), it can never start. 10 minutes or more works.
   Once running, it holds the display awake itself.
   **After `brew upgrade python`**, re-run the installer and re-grant the new path.
   The upgrade moves Python, and macOS ties the permission to the old file.
5. **Supervised first run, at the desk:**
   ```bash
   .venv-wechat/bin/python scripts/wechat_archive.py --dry-run --no-idle-check --no-notion --chat "<a supplier chat>"
   ```
   Check the preview: Me and Them right, separators gone, images labelled. Correct
   `parse.kind_patterns` in the settings if WeChat labels things differently. Then
   one real chat (`--no-idle-check --chat …` without `--dry-run`), check the rows in
   Notion, and let the schedule take over.

Uninstall: `zsh scripts/wechat_install_mac.sh --uninstall`. The archive stays.

## Asking questions

From any session with the reader token:

```bash
python3 scripts/wechat_pull.py --search "price list" --out analysis/cache/wechat/q.json
python3 scripts/wechat_pull.py --search 涨价 --chat "Tosca Flooring"
python3 scripts/wechat_pull.py --chat "Tosca Flooring" --hours 720
```

`contains` is a plain substring match, so search in the language the chat uses.
Notion's own search and the Notion connector also see the database.

## Known limits

- **Untested against a live WeChat.** The reader was read, not run. The supervised
  first run is the test. The sender heuristic, the separator formats and the kind
  labels are the likeliest things to need tuning, and they are data in the settings
  file.
- **One desktop login.** WeChat allows one desktop session per account. This uses
  the Mac Albert already has logged in, so nothing changes. A second Mac would log
  this one out.
- **Terms of service.** UI automation of the official client isn't sanctioned by
  Tencent. It reads only and at human speed (one pass a day), which is the
  low-risk end, but it isn't zero.
- **Sidebar reach.** It reads only chats it can see in the sidebar, up to 40. On a
  day with more than 40 active chats, the rest wait for the next run, and the
  tail-and-backfill logic catches them up then.
- **Edited or recalled messages** change the text in the overlap and can cause a
  gap flag.

## Changelog

- 2026-10-29 — Built (archiver v1, ingest agent, registry, tests); decision in vault
  `05_decisions/2026-10-29-wechat-archive.md`. Owner General,
  private. Mac schedule: every 30 minutes, once a day when unlocked and idle (asked
  for "early morning"; a fixed 06:30 would almost always find the screen locked).
