---
description: Daily — for every Approved row with a PR, check the PR state and the live URL on the production host; plan Direct URL / Publish Date / Status Published only when merged, 200 and canonical match; flag bodies edited after publish; list YouTube embeds for Phase 4. Absence of a check is never success. plan_only until deliberately flipped.
---

# /blog-sweep

Close the loop between the website and Notion. Nothing else can set `Published`:
a merged PR says the file is on `main`, not that the page is live, so the sweep
demands **merged AND HTTP 200 AND the canonical URL matching** before it writes.
Pure decider in `scripts/blog_sweep.py`; this command only gathers its inputs.

```
[1] Notion snapshot: Blog Posts (MCP SQL, saved as JSON)                   read only
[2] gather checks per Approved/Published row -> ingest/<date>/blog-sweep-checks.json
      PR state (mcp__github__pull_request_read), HEAD + canonical of the expected URL,
      body sha1 of a Published row (notion-fetch), linked Content Idea's YouTube Live URL
[3] scripts/blog_sweep.py  -> ingest/<date>/blog-sweep.json
[4] scripts/blog_plan.py --stage sweep -> plans/<date>/blog-plan-sweep-all.json
[5] POLICY approves update_blog_post (expect Status Approved)             (approval file)
[6] blog-actions-agent writes Direct URL, Publish Date, Status Published  (actions log)
[7] PushNotification; commit; PR
```

Authoritative procedure. `scripts/blog_sweep.py`'s docstring is the rule table;
`platform-settings/content-engine.json` → `website.production_host`, `url_template`,
`trailing_slash`, `video_embed`; `contracts/blog-plan-schema.md` (plan, approval).

## Before you start

1. **`write_mode`** in `platform-settings/content-engine.json`. While `plan_only`
   this command runs steps 1–4 and 7 and writes **no approval file and no Notion
   property**.
2. **`website.production_host`** is set. While it is `null` (no production deploy yet),
   every candidate is `needs_person` and the sweep writes nothing — say so and stop
   after step 4. Setting the host is a registry change with a dated note, not a guess.
3. **Notion is reachable** through `mcp__Notion__*`; GitHub through `mcp__github__*`
   (read only here — `pull_request_read`); the production host is reachable from this
   environment (an egress refusal is reported as an environment limit, never as 404).

## 1. Snapshot — read only

Posts query from `scripts/blog_snapshot.py` → `ingest/<date>/blog-posts-sql.json` →
`ingest/<date>/blog-posts-snapshot.json`. Candidates are rows with `status` in
{`Approved`, `Published`} and a `slug`.

## 2. Gather the checks — read only

`ingest/<date>/blog-sweep-checks.json`, shape in the script's docstring:

- **Approved rows**: `pr_state` from `pull_request_read` on the row's `PR URL`
  (`open` / `merged` / `closed`; `null` when there is no PR URL); `http_status` and
  `canonical` from a HEAD then a GET of `website.url_template` with the production
  host and the slug (read `<link rel="canonical">`; `null` on anything but 200).
- **Published rows**: `body_sha1` = sha1 of the `.mdx` currently on `main`
  (`mcp__github__get_file_contents` on `content/blog/<slug>.mdx`) — the sweep compares
  it with the sha1 the publish plan recorded; `video_url` = the linked Content Idea's
  live YouTube URL (`Live URL` on its Content Calendar Log row), `null` otherwise.
- A check you could not make is `null`. **Never fill a gap with the hopeful value.**
  A short read-only helper that writes just this file is fine; it never touches a platform.

## 3. Decide — read only

```bash
python3 scripts/blog_sweep.py --rows ingest/<date>/blog-posts-snapshot.json \
    --checks ingest/<date>/blog-sweep-checks.json --out ingest/<date>/blog-sweep.json
```

Read the six lists: `proposals` (will be written), `not_yet` (waiting on merge or
deploy), `url_mismatch` (live but at a different canonical — no write, a person
looks), `needs_person` (PR closed unmerged, or no production host), `flagged`
(`body_changed_after_publish`), `video_candidates` (Phase 4 embeds them; today they are
reported).

## 4. Plan — read only

```bash
python3 scripts/blog_plan.py --stage sweep --sweep ingest/<date>/blog-sweep.json
```

Output `plans/<date>/blog-plan-sweep-all.json`: one `update_blog_post` per proposal
(`Status: Published`, `Direct URL`, `Publish Date` = today, `expect: {Status: Approved}`),
holds for `needs_person` and `url_mismatch`, flags carried, `not_yet` as warnings.
Exit 3 (no actions) is the normal quiet day.

## 5. Policy — the approval file

**Under `write_mode: plan_only`, skip to step 7.**

Under `write`, re-run step 4 with `--write-approval` →
`plans/<date>/blog-approval-sweep-all.json`.

## 6. Act — `blog-actions-agent`

Action type `notion_update_blog_post`. The agent re-reads `Status` and writes only a
row still at `Approved`. It writes the three properties in `fields` and nothing else —
not `Video URL` (Phase 4), not the body.

## 7. Report — the ping, the commit

1. **PushNotification** — only when something changed or needs a person: posts now
   live (with URLs), posts waiting on a merge, anything in `url_mismatch` /
   `needs_person`, bodies edited after publish, videos ready to embed. A quiet day
   under `plan_only` still commits but does not ping.
2. **Commit** the run's files (SQL result, snapshot, checks, decision, plan, approval,
   actions-log) and open the run's PR with `python3 scripts/publish_run.py`.

## Done means

- Steps 1–4 ran; every candidate row appears in exactly one of the six lists.
- Under `plan_only`: **nothing was written to Notion**, and the report says so.
- No row was marked `Published` without a merged PR, a 200 and a matching canonical;
  no missing check was read as success.

Report honestly. If a step did not run, say which.
