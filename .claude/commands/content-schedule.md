---
description: Schedule one Notion content row into Metricool. Builds a reviewable plan, applies policy, and writes only what is approved. Draft mode until deliberately flipped.
---

# /content-schedule `<notionID>`

Takes one row from **Titan Content Ideas** and turns it into a scheduled Metricool
post — or explains, per surface, why it did not.

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

Fetch the Notion page by `<notionID>`. Take `Content Name`, `Caption`, `Post Date`,
`Next: Post To`, `Story Variant`, `Cover Image URL`, `Cover Frame (ms)`,
`Link to Files`, `Post Status`, `Metricool Post ID`.

If `Post Status` is already `Posted`, or `Metricool Post ID` is set and
`getScheduledPosts` confirms that post exists — **stop, report, change nothing.**
This is the idempotency gate and it runs before anything else touches Drive.

### 2 — Resolve the media

`scripts/content_media_resolve.py "<Link to Files>" --json`.

Remember `Link to Files` is a **folder**. The resolver walks it to `03_FINAL` and
refuses, rather than guessing, when there is more than one video, nothing at all, or
no `03_FINAL`. **Pass its refusal straight through as a hold.** Do not pick a file
to keep the run moving — which clip goes out is a person's decision.

Then check the asset's Drive permissions. **No anyone-with-link grant means the post
will fail at schedule time**, because Metricool fetches anonymously. Hold it with
that reason rather than discovering it as a Metricool error later.

### 3 — Build the plan

Write `plans/<date>/social-plan-<notionID>.json` per `contracts/social-plan-schema.md`.

Apply the holds in that contract. The three that are easiest to get wrong:

- **Covers.** Omit the cover keys entirely where they do not apply. Sending one on a
  Story, on Google Business Profile, or without a video in `media` rejects the
  **entire post**, not just the cover.
- **Stories.** A Story has no caption of its own. If every provider on the post is a
  Story, do not send `info.text` at all.
- **Google Business Profile.** A row with both a video and a caption is not
  expressible as one GMB post. Hold it; do not choose a half to discard.

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

For each executed action, update the Notion row: `Post Status`, `Metricool Post ID`,
and `Live URL` once known. For each held row, set `Post Status` to `Manual Required`
and say why in the report.

Then push a notification naming the counts: scheduled, held, failed.

## Dry run

With no approval file present, this command must schedule **nothing** and say so
plainly. That is the most important negative test in the build — run it first,
against a real row, before trusting any of the above.

## Done means

- A plan file exists and is readable by a person.
- Every executed action appears in the actions log with `approved_by` non-blank.
- Every held row has a reason a person can act on — not "not ready".
- The Notion row reflects what actually happened, including when nothing did.
