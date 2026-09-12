# Social Plan Contract — social-plan-1

The diff between "what Notion says should go out" and "what Metricool has scheduled",
plus the approval file that decides which of it actually runs.

Written by `.claude/commands/content-schedule.md`. Read by `social-actions-agent`.
Ids and platform rules live in `platform-settings/social-destinations.json` and
`platform-settings/content-sources.json`, never here and never in a prompt.

Mirrors `contracts/catalog-plan-schema.md` deliberately — same envelope, same stable
ids, same "absence of an approval file means nothing is approved". Read that one
first if this is unfamiliar; only the differences are explained here.

## What this is for

A Notion row says: this asset, this caption, this platform, this date. Turning that
into a scheduled post is a handful of decisions that all look trivial and are not —
whether a cover applies, whether a Story can carry text, whether Google Business
Profile can express a video and a caption at once. This plan makes each of them
explicit and reviewable **before** anything reaches a feed.

## The approval boundary

Unchanged from the catalogue pipeline, and enforced harder here:

- The planner **never** creates, edits or pre-populates the approval file.
- **Absence of an approval file means nothing is approved.** Not "approve
  everything", not "ask again later".
- `social-actions-agent` may execute an action **only** if its `id` appears in
  `plans/YYYY-MM-DD/social-approval.json` with `status: "approved"`.
- Plans expire at end of day. A stale plan is re-derived, never re-approved.
- `held` entries carry no `id` and are unapprovable by construction.

### Why this one is stricter than the catalogue's

`/catalog-sync` auto-approves nearly everything because a wrong catalogue row is
found and fixed before a customer sees it. That is not true here. **A published post
has been seen.** There is no correcting write — deleting it does not unsend it.

So the policy below clears less, and the staged rollout in
`social-destinations.json` (`write_mode.mode: "draft"`) means that even an approved,
executed action lands as a Metricool *draft* until a person deliberately flips that
value. Two independent brakes, not one.

## Policy auto-approval (2026-09-12, Albert)

`/content-schedule` may write the approval file itself, with no person's yes, for an
action where **all** of the following hold:

- the surface is `enabled` in `social-destinations.json` **and** its network appears
  in `connected_networks`;
- the format is a feed post or a `Plain Story` — never a `Decorated Story`;
- `caption`, `media_url`, `scheduled_at` and `surface` are all present and non-empty;
- the caption is within the surface's `text_max_chars`, where one is set;
- the cover situation is unambiguous (see `cover` below).

**Everything else is `held`.** A held row is not a failure and not an error — it is
the pipeline declining to guess. Held rows are reported per row, with the reason.

### The holds, and why each one exists

| Hold reason | Why it cannot be auto-approved |
|---|---|
| `decorated_story` | Link stickers, polls, mentions and music cannot be set through Meta's API. Posting it "plain" would silently ship a worse version of a post someone designed. Goes out with `autoPublish: false` instead — a phone notification — and is logged `social_flag_manual`. |
| `tiktok_story_impossible` | TikTok's Content Posting API has no story format. Nothing to retry, ever. |
| `missing_caption` / `missing_media` | An empty caption posts an empty caption. There is no safe default. |
| `caption_too_long` | Truncation changes the meaning of the last sentence, which is usually the call to action. |
| `youtube_long_no_cover` | Policy, not an API rule. A default auto-thumbnail is a lasting click-through cost on long-form, and the cover is a *second* API call that can fail on its own. |
| `cover_not_applicable` | A cover was supplied for a surface whose `cover` mode is `none` or `frame_offset`. Sending it rejects the **entire post** with `VIDEO_THUMBNAIL_NOT_APPLICABLE` — so this is reported, never silently dropped. |
| `gmb_video_with_caption` | `gmbData.type: "publication"` is text-only and cannot carry video; `"photo"` carries a video and no text. The row is not expressible as one GMB post, and choosing a half to discard is a person's call. |
| `surface_disabled` | The surface is off (LinkedIn) or its network was never connected. Writing anyway produces a confusing Metricool error rather than an honest hold. |

## Envelope

```json
{
  "contract_version": "social-plan-1",
  "generated_at": "2026-09-12T14:03:11-04:00",
  "notion_id": 170,
  "content_name": "QA What Is the Most Scratch Resistant Flooring",
  "blog_id": "3951085",
  "write_mode": "draft",
  "actions": [],
  "held": [],
  "warnings": []
}
```

`write_mode` is copied from the registry **at plan time** and re-checked by the agent
at execute time. If they disagree, the agent stops: it means the registry changed
between planning and execution, and a post is not the place to discover that.

## Action

```json
{
  "id": "a3f9c1e2",
  "type": "social_schedule_post",
  "surface": "Instagram Reels",
  "network": "instagram",
  "network_data": { "type": "REEL" },
  "story_variant": "Not a Story",
  "caption": "Scratch-resistant floors, ranked…",
  "media_url": "https://drive.google.com/uc?id=…",
  "cover": { "mode": "image_url", "value": "https://drive.google.com/uc?id=…" },
  "scheduled_at": { "dateTime": "2026-09-15T10:00:00", "timezone": "America/Toronto" },
  "notion_page_url": "https://www.notion.so/…"
}
```

`id` is a stable hash of `notion_id + surface + story_variant + scheduled_at`. Same
logical post, same id, on every re-run — which is what makes resume work and what
stops a retry double-posting. It deliberately does **not** include the caption: a
typo fix should not create a second post.

`cover.mode` is one of the registry's `cover` values. **When no cover applies, the
key is omitted entirely** — not set to `null`, not set to an empty string. The agent
must be able to tell "no cover" from "a cover I failed to resolve", because sending
the latter rejects the whole post.

## `held`

Same shape as an action, minus `id`, plus:

```json
{ "reason": "decorated_story", "detail": "Story Variant = Decorated Story; API cannot set stickers" }
```

No `id` means unapprovable by construction. A held row is cleared by fixing the
Notion row and re-running, or by a person approving the equivalent action by hand.

## `warnings`

Things that do not stop a write but that a person should see: a caption close to the
limit, a cover whose aspect ratio will be centre-cropped on the Instagram grid, a
scheduled time in the past, a media file large enough to risk a slow ingest.

## Execution order

One surface at a time, in the plan's order. **No parallelism**, deliberately: the
stop-the-batch rule is only meaningful if a failure stops things that have not
happened yet.

## An action only exists if it changes something

If `getScheduledPosts` already shows this exact post for this brand and slot, the
planner emits nothing for it. A plan with zero actions is a normal, healthy outcome
and means the schedule is already correct — it is not an error and must not be
reported as one.
