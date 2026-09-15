#!/usr/bin/env python3
"""Rebuild a live Metricool post as an `info` payload with a new publication date.

This is the *decision* half of rescheduling, split from I/O for the same reason as
content_media_select.py: the refusals are the part that matters, and as a pure
function they are unit-testable with no network and no credential.

    <getScheduledPosts json> | python3 scripts/social_post_rebuild.py \
        --post-uuid -5728278742307617912 \
        --new-date 2026-12-24T09:00:00 --timezone America/Toronto

Exit 0 = a payload (or a no-op); exit 2 = a refusal, reason on stdout as JSON and on
stderr as text; exit 1 = bad input.

THE POST ID IS NOT STABLE. THE UUID IS. Verified live on 2026-09-14: updating post
375382755 returned the same post under a NEW id, 375680540, with the uuid unchanged
at -5728278742307617912 and a fresh creationDate. A follow-up getScheduledPosts
showed one post, not two -- so an update is not a duplicate, it is a new version of
the same post, and Metricool's `id` identifies the version while `uuid` identifies
the post.

This is why `uuid` is the key everywhere downstream, and why the Calendar Log's
`Metricool UUID` is the idempotency field rather than `Metricool Post ID`. Keying on
the id would break the moment a post is rescheduled: the stored id no longer matches
anything, the row reads as never-scheduled, and a re-run would schedule it a second
time. That failure is silent and it double-posts.

WHY THIS EXISTS. `updateScheduledPost` is not a patch. Its contract: "ensure the full
original content is included in the request, modifying only the new information while
keeping the rest unchanged." Send a partial and the omitted fields are wiped -- from a
post that is already live-scheduled, with no undo.

WHY IT READS THE LIVE POST AND NOT A STORED COPY. `getScheduledPosts` returns the
post's full current content, so Metricool itself is the source of the "full original
content". Three consequences, all of which beat keeping our own copy:

  1. No drift. Anything edited in the Metricool planner is in what we read back. A
     payload we stored at schedule time would silently disagree, and the whole point
     of this path is that Albert fiddles after scheduling.
  2. `media` comes back rewritten to static.metricool.com -- Metricool downloads
     external media at schedule time and re-hosts it. Echoing those CDN URLs means a
     reschedule does not re-fetch from Drive, so it still works after the Drive file
     is unshared, moved or deleted.
  3. The endpoint only returns posts that are scheduled and NOT yet published, so a
     post it does not return cannot be rescheduled anyway. The lookup and the
     precondition are the same call.

WHAT IT REFUSES TO GUESS. Only the date changes. Everything else is echoed. If a
field cannot be echoed safely the script refuses rather than sending its best guess,
because the failure mode here is not an error -- it is a post that quietly loses its
caption or its cover and stays scheduled.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Provider name -> the networkData key that belongs to it. The write contract is
# explicit: "Only include the networkData for the networks you have in the providers
# list." A read comes back carrying MORE than that -- the live Facebook-only draft
# (post 375382755) returns twitterData and instagramData too -- so echoing the
# response verbatim sends networkData for networks the post does not target.
NETWORK_DATA_KEY = {
    "twitter": "twitterData",
    "facebook": "facebookData",
    "instagram": "instagramData",
    "linkedin": "linkedinData",
    "pinterest": "pinterestData",
    "youtube": "youtubeData",
    "tiktok": "tiktokData",
    "bluesky": "blueskyData",
    "threads": "threadsData",
    "gmb": "gmbData",
}

# Content fields carried through untouched. A WHITELIST, not a blacklist: an unknown
# field in a future API response is likelier to be server-side decoration than
# content, and echoing one back into a write is how a post acquires a field nobody
# chose. Anything unrecognised is reported as a warning rather than sent -- see
# rebuild().
CARRY_FIELDS = (
    "text",
    "media",
    "mediaAltText",
    "autoPublish",
    "draft",
    "shortener",
    "firstCommentText",
    "hasNotReadNotes",
    "descendants",
    "smartLinkData",
    "videoThumbnailUrl",
    "videoCoverMilliseconds",
)

# Server-side decoration on a read. Known, deliberately dropped, and NOT warned about.
READ_ONLY_FIELDS = frozenset({
    "id",
    "uuid",
    "creationDate",
    "creatorUserMail",
    "creatorUserId",
    "publicationDate",   # replaced by the new date
    "providers",         # rebuilt, see strip_providers()
    "saveExternalMediaFiles",
    "status",
    "detailedStatus",
})

ISO_LOCAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


class Refusal(Exception):
    """Not an error. A deliberate stop, carrying a reason and the fix."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def normalize(raw):
    """Accept the getScheduledPosts envelope, a bare list, or a single post."""
    if isinstance(raw, dict) and "data" in raw:
        raw = raw["data"]
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("expected a list of posts, the {'data': [...]} envelope, or one post")
    return raw


def find_post(posts, post_uuid=None, post_id=None):
    """Locate the post, by uuid for preference. Returns (post, warnings).

    Matching is done on strings throughout: Metricool returns `id` as an integer and
    `uuid` as a string, and both arrive back from Notion as text.
    """
    if not post_uuid and not post_id:
        raise Refusal("no_selector", "give --post-uuid (preferred) or --post-id.")

    warnings = []
    if post_uuid:
        key, value = "uuid", str(post_uuid)
    else:
        key, value = "id", str(post_id)
        warnings.append(
            "matched on id, which is NOT stable -- Metricool mints a new id on every "
            "update. This works only for a post that has never been updated. Store and "
            "pass the uuid instead."
        )

    matches = [p for p in posts if str(p.get(key)) == value]
    if not matches:
        raise Refusal(
            "post_not_found",
            f"no scheduled post with {key} {value} in this listing. It has already "
            "published, was deleted, or the queried date range does not cover its "
            "current date -- getScheduledPosts returns only posts still pending. A "
            "published post cannot be rescheduled; there is nothing left to move."
            + ("" if key == "uuid" else
               " Note the id changes on every update, so a stale id also lands here."),
        )
    if len(matches) > 1:
        raise Refusal(f"duplicate_post_{key}",
                      f"{len(matches)} posts share {key} {value}; refusing to pick one.")

    post = matches[0]
    if post_uuid and post_id and str(post.get("id")) != str(post_id):
        warnings.append(
            f"the stored Metricool Post ID ({post_id}) is stale -- this post is now "
            f"id {post.get('id')}. Expected after any update; write the new id back to "
            "the Calendar Log row."
        )
    return post, warnings


def strip_providers(post):
    """`[{network, status, detailedStatus}]` -> `[{network}]`.

    A read decorates each provider with its delivery state. The write contract takes
    `[{"network": "<string>"}]`; status is Metricool's to set, not ours to assert.
    """
    providers = post.get("providers") or []
    out = []
    for p in providers:
        network = (p or {}).get("network")
        if not network:
            raise Refusal("malformed_providers",
                          f"a provider entry has no network: {json.dumps(p)}")
        out.append({"network": network})
    if not out:
        raise Refusal("no_providers",
                      "the live post lists no providers, so there is no network to "
                      "publish to. This is a broken post in Metricool, not a date problem.")
    return out


def rebuild(post, new_date: str, timezone: str, require_draft: bool, now: str):
    """Return (payload, warnings) for updateScheduledPost, or raise Refusal."""
    if not ISO_LOCAL.match(new_date):
        raise Refusal("bad_new_date",
                      f"--new-date must be YYYY-MM-DDTHH:MM:SS with no offset, got {new_date!r}. "
                      "Metricool takes a local wall-clock time plus a separate IANA timezone.")

    if new_date <= now:
        raise Refusal(
            "date_in_past",
            f"the new date {new_date} is not in the future (now {now}, {timezone}). "
            "Metricool would either publish it immediately or reject it; neither is "
            "what moving a post to a past slot is meant to mean.",
        )

    uuid = post.get("uuid")
    if not uuid:
        raise Refusal("missing_uuid",
                      f"post {post.get('id')} came back with no uuid. updateScheduledPost "
                      "requires both id and uuid -- without it this post cannot be updated "
                      "through the API at all, only in the planner UI.")

    # RULE 0 guard. While write_mode is draft every post must be a draft; a live post
    # that is not one was made somewhere other than this pipeline, and a reschedule is
    # not the moment to discover that.
    if require_draft and not post.get("draft"):
        raise Refusal(
            "not_a_draft",
            f"post {post.get('id')} is not a draft, but write_mode.mode is 'draft' in "
            "social-destinations.json. Rescheduling it would be editing a post that is "
            "set to publish for real. Check who created it before touching it.",
        )

    current = (post.get("publicationDate") or {}).get("dateTime")
    if current == new_date and (post.get("publicationDate") or {}).get("timezone") == timezone:
        return {"noop": True, "reason": "date_unchanged", "id": post.get("id"),
                "publicationDate": post.get("publicationDate")}, []

    providers = strip_providers(post)
    targeted = {p["network"] for p in providers}

    info = {}
    for field in CARRY_FIELDS:
        if field in post:
            info[field] = post[field]

    # Only the networkData of a targeted network. See NETWORK_DATA_KEY.
    wanted = {NETWORK_DATA_KEY[n] for n in targeted if n in NETWORK_DATA_KEY}
    for network in sorted(targeted):
        key = NETWORK_DATA_KEY.get(network)
        if key is None:
            raise Refusal("unknown_network",
                          f"provider {network!r} has no known networkData key. Add it to "
                          "NETWORK_DATA_KEY once its shape is confirmed against the write "
                          "contract -- do not send the post without it.")
        # "Always you need to add the networkData for the posts, as empty if you don't
        # have more information." An absent block is sent as {}, never omitted.
        info[key] = post.get(key, {})

    info["providers"] = providers
    info["publicationDate"] = {"dateTime": new_date, "timezone": timezone}

    warnings = []
    dropped_data = sorted(k for k in post
                          if k.endswith("Data") and k in NETWORK_DATA_KEY.values()
                          and k not in wanted)
    if dropped_data:
        warnings.append(
            f"dropped networkData for networks this post does not target: "
            f"{', '.join(dropped_data)}. Metricool returns these on a read; sending them "
            "back would declare networks the post is not publishing to."
        )

    known = set(CARRY_FIELDS) | READ_ONLY_FIELDS | set(NETWORK_DATA_KEY.values())
    unknown = sorted(k for k in post if k not in known)
    if unknown:
        warnings.append(
            f"unrecognised field(s) in the live post, NOT echoed into the update: "
            f"{', '.join(unknown)}. If any of these is real content, add it to "
            "CARRY_FIELDS -- until then this reschedule would drop it."
        )

    payload = {"id": str(post["id"]), "uuid": str(uuid), "info": info,
               "previous_publication_date": post.get("publicationDate")}
    return payload, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--post-uuid",
                    help="Metricool post uuid — the stable key, preferred")
    ap.add_argument("--post-id",
                    help="Metricool post id. NOT stable across updates; use only for a "
                         "post that has never been updated, or alongside --post-uuid "
                         "to have a stale stored id reported")
    ap.add_argument("--new-date", required=True,
                    help="new local time, YYYY-MM-DDTHH:MM:SS (no offset)")
    ap.add_argument("--timezone", required=True, help="IANA identifier, e.g. America/Toronto")
    ap.add_argument("--posts", type=Path, help="getScheduledPosts JSON file; default stdin")
    ap.add_argument("--require-draft", action="store_true",
                    help="refuse unless the live post is a draft (use while write_mode is draft)")
    ap.add_argument("--now", help="override 'now' for tests; local YYYY-MM-DDTHH:MM:SS")
    args = ap.parse_args()

    try:
        raw = args.posts.read_text() if args.posts else sys.stdin.read()
        posts = normalize(json.loads(raw))
    except (OSError, ValueError) as exc:
        print(f"bad posts input: {exc}", file=sys.stderr)
        return 1

    # BUG FIXED 2026-09-14: this used to be datetime.now().strftime(...), the host's
    # naive system clock (UTC in this environment) mislabelled as if it were already
    # wall-clock time in --timezone. That made "now" run hours ahead of the real
    # America/Toronto time for most of the day, so a genuinely future --new-date
    # (e.g. tonight 9:30pm while it's currently 8:42pm) was refused as date_in_past.
    # The bug only ever pushed "now" later than reality here (UTC is ahead of
    # Toronto), so it could over-refuse but never under-refuse -- still wrong, and
    # caught live rescheduling TC-86's real Instagram Reel post.
    now = args.now or datetime.now(ZoneInfo(args.timezone)).strftime("%Y-%m-%dT%H:%M:%S")

    try:
        post, warnings = find_post(posts, args.post_uuid, args.post_id)
        result, more = rebuild(post, args.new_date, args.timezone, args.require_draft, now)
        warnings += more
    except Refusal as r:
        print(json.dumps({"refused": True, "reason": r.reason, "detail": r.detail}, indent=2))
        print(f"refused ({r.reason}): {r.detail}", file=sys.stderr)
        return 2

    if warnings:
        result = dict(result, warnings=warnings)
    print(json.dumps(result, indent=2))
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
