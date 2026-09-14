---
description: Schedule one Notion content row into Metricool. Builds a reviewable plan, applies policy, and writes only what is approved. Draft mode until deliberately flipped.
---

# /content-schedule `<logID>`

Takes one row from **Content Calendar Log** and turns it into a scheduled Metricool
post — or explains why it did not.

**`<logID>` is a Content Calendar Log page id, not a Titan Content Ideas id.** The
Calendar Log row *is* the post: one row, one platform, one Metricool id. Pointing this
command at an idea row is a category error — an idea fans out to many posts and has no
single id to write back.

**The trigger is `Post Status` → `Queued`, not row creation** (Albert, 2026-09-14).
The **Publish Content** button creates the row; Albert then adjusts the date and
anything else. Scheduling on creation would put a post in Metricool before its date
was settled, and every later edit would need an `updateScheduledPost` round-trip to
stay in sync. `Queued` is a person saying *this one is final* — the same
ingest → decide → act shape as the rest of the repo. Registry:
`content-sources.json` → `sources.content_calendar_log.trigger`.

Authoritative procedure. `contracts/social-plan-schema.md` defines the plan and the
approval file; `platform-settings/social-destinations.json` and
`platform-settings/content-sources.json` hold every id and platform rule.

## Before you start

Check these in order and **stop on the first failure** — do not proceed part-way:

1. **Metricool is reachable.** `getBrandSettings` returns brand `3951085`. If it
   does not, stop and say so; everything below is pointless without it.
2. **The surface is enabled and its network is connected.** A surface with
   `enabled: false` (LinkedIn) or a `null` in `connected_networks` is not writable.
3. **`write_mode.mode`.** While it is `draft`, every post carries `info.draft: true`.
   Do not raise it. Flipping that value is a dated decision recorded in the vault,
   not something this command decides.

## Steps

### 1 — Read the row

Fetch the Calendar Log page by `<logID>`. Take `Content Name`, `Post Date`, `Post To`,
`Post Status`, `Metricool Post ID`, `Live URL`, and the three rollups that ride on the
`Content Series` relation: `Caption`, `Content ID`, `Link to Files`.

Those rollups are why one fetch is enough — the caption and the Drive content folder
arrive with the row. Do not fetch the idea separately unless something is missing.

**Caption resolution: `Caption Override` on the row wins; otherwise the `Caption`
rollup.** One shared caption cannot serve every surface, and the reason is idiom
rather than length. "Link in bio" is Instagram and TikTok only — on Facebook, YouTube
and Google Business Profile a real URL is possible, so the phrase ships a dead
instruction. A thirty-hashtag block is native on Instagram, renders three deep on
YouTube, and reads as spam on a Google listing. GBP also caps at 1500 characters, so
an Instagram-shaped caption can make a GBP row unpostable through no fault of that
row. Leave the override blank and the shared caption applies; set it and it wins.

**Read the surface's `row_fields`** from `social-destinations.json` →
`surfaces.<surface>.row_fields`. That list is the single answer to "what does this
platform need?" — each entry names a Calendar Log column and the Metricool field it
fills. A `required: true` entry that is blank is a **hold**, named by its column:

- **`Video Title`** on either YouTube surface. YouTube requires a title, and it is not
  the caption — YouTube displays the title, never `info.text`.
- **`GBP Post Type`** on Google Business Profile. This is the field that resolves the
  video trap: `Publication` is text-only and cannot carry video; `Photo` carries media
  and no text of its own. A row with both a video and a caption is not expressible as
  one GBP post, and this column is where a person says which half matters.

Everything else on that list is optional and simply passed through when present.
Anything constant for every Titan post is **not** a column — `madeForKids`, TikTok's
`privacyOption` and YouTube's default privacy live in the registry, because a column
for an invariant is friction on every row forever.

The `Ready To Queue` formula on the log shows the same missing-required check while
Albert is editing, so the gaps can be filtered by platform and filled before anything
is `Queued`. It is a convenience, not the gate — this command re-checks.

`Post To` must match a surface key in `social-destinations.json` **character for
character**. A miss is a silent lookup failure, not an error, so treat an unmatched
value as a hold and name the value you got.

If `Post Status` is blank or anything other than `Queued`, **stop** — the row is still
being edited and nobody has declared it final. Say which status you found. (An
explicitly re-run `Failed` row is the one exception: say so and proceed.)

If `Post Status` is already `Posted`, or `Metricool UUID` is set and
`getScheduledPosts` confirms that post exists — **stop, report, change nothing.**
This is the idempotency gate and it runs before anything else touches Drive. It is
per-row, which is the point of keying on the Calendar Log: the same idea posting to a
second platform is a different row with its own post, and must not be mistaken for a
repeat.

**Key on `Metricool UUID`, never `Metricool Post ID`.** `updateScheduledPost` returns
the post under a **new id** each time — verified live 2026-09-14, uuid unchanged, one
post not two. So the id identifies a version and the uuid identifies the post. A gate
keyed on the id passes silently the first time a post is rescheduled, and the row gets
scheduled twice. The id is still stored, for the audit trail and the planner link, but
nothing decides anything on it.

### 2 — Resolve the media

`Link to Files` is a **folder**, not a file. Resolving it is two Drive listings with
`scripts/content_media_select.py` deciding in between — the script does no I/O and
holds no credential, so fetching is yours to do:

1. `search_files` with `parentId = '<content folder id>'` → pipe that JSON to
   `content_media_select.py --mode find-final` → get the `03_FINAL` id.
2. `search_files` with `parentId = '<03_FINAL id>'` → pipe to
   `--mode select-media` → get the media and any cover.

**Exit 2 is a refusal, not a crash.** It means two videos in `03_FINAL`, an empty or
missing `03_FINAL`, or several images with no video. The reason is on stdout as JSON:
**pass it straight through as a hold, verbatim.** Do not pick a file to keep the run
moving — which clip goes out is a person's decision, and a posted clip cannot be
unposted. Exit 1 is different: that is malformed input, i.e. a bug in this command.

Then check the asset's Drive permissions. **No anyone-with-link grant means the post
will fail at schedule time**, because Metricool fetches anonymously. Hold it with
that reason rather than discovering it as a Metricool error later.

### 3 — Build the plan

Write `plans/<date>/social-plan-<logID>.json` per `contracts/social-plan-schema.md`.

Apply the holds in that contract. The three that are easiest to get wrong:

- **Covers.** Omit the cover keys entirely where they do not apply. Sending one on a
  Story, on Google Business Profile, or without a video in `media` rejects the
  **entire post**, not just the cover.
- **Stories.** A Story has no caption of its own. If every provider on the post is a
  Story, do not send `info.text` at all.
- **Google Business Profile.** A row with both a video and a caption is not
  expressible as one GMB post. Hold it; do not choose a half to discard. Also note the
  caption is a **rollup shared with every other platform on that idea**, so it can
  arrive over GMB's 1500-character limit through no fault of this row. Hold it — never
  truncate, which would publish a sentence nobody wrote.

### 4 — Approve

Policy (in the contract) may write `plans/<date>/social-approval.json` for actions
that clear every condition. Everything else stays held.

**Absence of an approval file means nothing is approved.** Never create it as a
formality, never pre-populate it, never approve a held row to unblock a run.

### 5 — Execute

Spawn `social-actions-agent` with the plan and the approval file. It executes only
ids marked `approved`, logs every attempt to `ingest/<date>/actions-log.json`, and
stops the batch on the first failure.

### 6 — Write back

Update the **Calendar Log row**, never the idea: `Post Status`, `Metricool UUID`,
`Metricool Post ID`, and `Live URL` once known. Those four are the whole write
surface — `Post Date`, `Post To`, `Content Series` and `Content Name` are the plan,
and editing them would be deciding what to post. If the row was held, set
`Post Status` to `Manual Required` and say why in the report.

Write the uuid **first**. If the run dies between the Metricool write and the Notion
write, the uuid is what stops the next run double-posting; the id is only ever
diagnostic.

Then push a notification naming the counts: scheduled, held, failed.

This command never sets `Posted` — it cannot know. A post leaves `getScheduledPosts`
the moment it publishes, so detecting that is `/content-sweep`'s job, run daily.

## Step R — reschedule an already-scheduled post

`/content-schedule <logID> --reschedule` moves a post that is already in Metricool to
the row's current `Post Date`. It changes the date and nothing else.

Use it when a row is `Scheduled` and the date has since changed. It is **not** a
re-run of the schedule path: that path would create a second post.

1. **Read the row.** It must be `Scheduled` and carry a `Metricool UUID`. Anything
   else — blank uuid, `Posted`, `Failed` — is a hold, not a reschedule. A `Posted` row
   has nothing left to move.
2. **Read the live post.** `getScheduledPosts` over a window wide enough to contain
   both the old and the new date. It returns only posts that are still pending, so a
   post that is missing has published (or was deleted in the planner) — hold and say
   which.
3. **Rebuild the payload.**

   ```
   <getScheduledPosts json> | python3 scripts/social_post_rebuild.py \
       --post-uuid '<Metricool UUID>' --post-id '<Metricool Post ID>' \
       --new-date '<Post Date, local, no offset>' --timezone America/Toronto \
       --require-draft        # while write_mode.mode is draft
   ```

   **Never hand-assemble this payload.** `updateScheduledPost` overwrites the entire
   post; whatever the payload omits is deleted, immediately, with no undo. The script
   exists because the live response cannot be echoed back verbatim either — it carries
   `networkData` for networks the post does not target (the live Facebook-only draft
   returns `twitterData` and `instagramData`), and `providers` decorated with delivery
   status the write must not assert.

   **Exit 2 is a refusal** — same rule as the media selector: pass it through as a
   hold, verbatim. Exit 0 with `"noop": true` means the date already matches; emit no
   action and report that nothing needed doing.

4. **Plan and approve** as `social_reschedule_post`, per the contract. Policy may
   clear it; a refusal never is.
5. **Execute** via `social-actions-agent`, logged as `social_reschedule_post` with the
   previous date in the entry — the log is the only place the old date survives.
6. **Write back the NEW `Metricool Post ID`** the update returned, keeping
   `Metricool UUID` as it was. Skipping this leaves a stale id on the row; it breaks
   nothing that decides anything, but it makes the audit trail point at a version that
   no longer exists.

### Not wired to anything yet

A Notion webhook on `Post Date` could fire this automatically. It is **designed, not
built** — deliberately, until the path has run by hand a few times. When it is built
it needs: a guard so it fires only on `Post Status = Scheduled` with a `Metricool UUID`
set, debouncing (dragging a row in calendar view fires an edit per drop), and handling
for the race where the post publishes between the edit and the webhook landing.

## Dry run

With no approval file present, this command must schedule **nothing** and say so
plainly. That is the most important negative test in the build — run it first,
against a real row, before trusting any of the above.

## Done means

- A plan file exists and is readable by a person.
- Every executed action appears in the actions log with `approved_by` non-blank.
- Every held row has a reason a person can act on — not "not ready".
- The Calendar Log row reflects what actually happened, including when nothing did.
- Nothing was written to Titan Content Ideas. The idea is the plan; the log is the
  record.
