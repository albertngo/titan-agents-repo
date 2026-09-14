#!/usr/bin/env python3
"""Tests for scripts/social_post_rebuild.py — mostly the refusals.

Stdlib unittest, matching the repo's convention.

The fixture below is not invented. It is the verbatim response from a live
getScheduledPosts call on 2026-09-14 for brand 3951085 — the leftover Drive-ingest
draft, post 375382755 — with nothing added or removed. That matters more here than
usual: this script's whole job is to echo a real API response back into a write, so a
hand-written fixture would test the shape we assumed rather than the shape Metricool
sends. The twitterData/instagramData blocks on a Facebook-only post are exactly the
kind of thing an invented fixture would have missed.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from social_post_rebuild import (  # noqa: E402
    Refusal, find_post, normalize, rebuild, strip_providers,
)

SCRIPT = REPO_ROOT / "scripts" / "social_post_rebuild.py"
TZ = "America/Toronto"
NOW = "2026-09-14T12:00:00"
UUID = "-5728278742307617912"

# Verbatim: getScheduledPosts(brandId=3951085, 2026-12-01..2026-12-31, America/Toronto)
LIVE = {
    "data": [{
        "id": 375382755,
        "publicationDate": {"dateTime": "2026-12-31T10:00:00", "timezone": "America/Toronto"},
        "creationDate": {"dateTime": "2026-09-13T21:21:00", "timezone": "America/Toronto"},
        "text": "Drive ingest test - draft only, do not publish.",
        "firstCommentText": "",
        "providers": [{"network": "facebook", "status": "PENDING", "detailedStatus": "Pending"}],
        "media": ["https://static.metricool.com/planner/202609/3951085-file-3622987319501237545.mp4"],
        "autoPublish": False,
        "saveExternalMediaFiles": False,
        "mediaAltText": [None],
        "shortener": False,
        "draft": True,
        "twitterData": {"type": "POST"},
        "facebookData": {"type": "POST"},
        "instagramData": {"autoPublish": False, "isAiGenerated": False},
        "hasNotReadNotes": False,
        "uuid": "-5728278742307617912",
        "creatorUserMail": "albertngo95@gmail.com",
        "creatorUserId": 3108910,
    }]
}


def live_post(**overrides):
    post = json.loads(json.dumps(LIVE["data"][0]))
    post.update(overrides)
    return post


def build(post=None, new_date="2026-12-24T09:00:00", require_draft=True, now=NOW):
    return rebuild(post or live_post(), new_date, TZ, require_draft, now)


class NormalizeCase(unittest.TestCase):
    def test_accepts_envelope_list_or_single_post(self):
        for raw in (LIVE, LIVE["data"], LIVE["data"][0]):
            self.assertEqual(len(normalize(json.loads(json.dumps(raw)))), 1)

    def test_rejects_nonsense(self):
        with self.assertRaises(ValueError):
            normalize("not a post")


class FindPostCase(unittest.TestCase):
    """The id is version-scoped, the uuid identifies the post. See the module docstring.

    Verified live 2026-09-14: updating 375382755 returned the same post as 375680540,
    uuid unchanged, and a follow-up read showed one post rather than two.
    """

    def test_matches_on_uuid(self):
        post, warnings = find_post(LIVE["data"], post_uuid=UUID)
        self.assertEqual(post["id"], 375382755)
        self.assertEqual(warnings, [])

    def test_matches_across_int_string_boundary(self):
        """Metricool returns an int id; Notion stores it as text."""
        for given in ("375382755", 375382755):
            self.assertEqual(find_post(LIVE["data"], post_id=given)[0]["id"], 375382755)

    def test_matching_on_id_alone_warns_that_it_is_unstable(self):
        _, warnings = find_post(LIVE["data"], post_id="375382755")
        self.assertTrue(any("NOT stable" in w for w in warnings))

    def test_stale_stored_id_is_reported_not_fatal(self):
        """After one update the row's stored id no longer matches the live post."""
        post, warnings = find_post(LIVE["data"], post_uuid=UUID, post_id="375680540")
        self.assertEqual(post["id"], 375382755)
        self.assertTrue(any("stale" in w for w in warnings))

    def test_no_selector_refuses(self):
        with self.assertRaises(Refusal) as cm:
            find_post(LIVE["data"])
        self.assertEqual(cm.exception.reason, "no_selector")

    def test_missing_post_refuses_and_says_why(self):
        with self.assertRaises(Refusal) as cm:
            find_post(LIVE["data"], post_uuid="nope")
        self.assertEqual(cm.exception.reason, "post_not_found")
        self.assertIn("already", cm.exception.detail)

    def test_stale_id_lookup_explains_the_id_churn(self):
        with self.assertRaises(Refusal) as cm:
            find_post(LIVE["data"], post_id="375680540")
        self.assertEqual(cm.exception.reason, "post_not_found")
        self.assertIn("changes on every update", cm.exception.detail)

    def test_duplicates_refuse_rather_than_pick(self):
        with self.assertRaises(Refusal) as cm:
            find_post(LIVE["data"] + LIVE["data"], post_uuid=UUID)
        self.assertEqual(cm.exception.reason, "duplicate_post_uuid")


class ProvidersCase(unittest.TestCase):
    def test_status_fields_are_stripped(self):
        """A read decorates providers with delivery state; a write must not assert it."""
        self.assertEqual(strip_providers(live_post()), [{"network": "facebook"}])

    def test_no_providers_refuses(self):
        with self.assertRaises(Refusal) as cm:
            strip_providers(live_post(providers=[]))
        self.assertEqual(cm.exception.reason, "no_providers")

    def test_provider_without_network_refuses(self):
        with self.assertRaises(Refusal) as cm:
            strip_providers(live_post(providers=[{"status": "PENDING"}]))
        self.assertEqual(cm.exception.reason, "malformed_providers")


class RebuildCase(unittest.TestCase):
    def test_only_the_date_changes(self):
        payload, _ = build()
        info = payload["info"]
        self.assertEqual(info["publicationDate"],
                         {"dateTime": "2026-12-24T09:00:00", "timezone": TZ})
        self.assertEqual(info["text"], "Drive ingest test - draft only, do not publish.")
        self.assertEqual(info["media"], LIVE["data"][0]["media"])
        self.assertEqual(info["facebookData"], {"type": "POST"})

    def test_media_stays_on_the_metricool_cdn(self):
        """The reschedule must not re-fetch from Drive — see the module docstring."""
        payload, _ = build()
        self.assertTrue(all(u.startswith("https://static.metricool.com/")
                            for u in payload["info"]["media"]))
        self.assertFalse(any("drive.google.com" in u for u in payload["info"]["media"]))

    def test_untargeted_networkdata_is_dropped_and_warned(self):
        """The live Facebook-only draft comes back with twitterData and instagramData."""
        payload, warnings = build()
        self.assertNotIn("twitterData", payload["info"])
        self.assertNotIn("instagramData", payload["info"])
        self.assertIn("facebookData", payload["info"])
        self.assertTrue(any("twitterData" in w for w in warnings))

    def test_missing_networkdata_is_sent_empty_not_omitted(self):
        post = live_post()
        del post["facebookData"]
        payload, _ = build(post)
        self.assertEqual(payload["info"]["facebookData"], {})

    def test_server_decoration_never_reaches_the_write(self):
        payload, _ = build()
        for field in ("creatorUserMail", "creatorUserId", "creationDate",
                      "saveExternalMediaFiles", "id", "uuid"):
            self.assertNotIn(field, payload["info"])

    def test_unrecognised_fields_are_warned_not_echoed(self):
        payload, warnings = build(live_post(someNewApiField="x"))
        self.assertNotIn("someNewApiField", payload["info"])
        self.assertTrue(any("someNewApiField" in w for w in warnings))

    def test_id_and_uuid_come_back_as_strings(self):
        payload, _ = build()
        self.assertEqual(payload["id"], "375382755")
        self.assertEqual(payload["uuid"], "-5728278742307617912")

    def test_previous_date_is_reported_for_the_log(self):
        payload, _ = build()
        self.assertEqual(payload["previous_publication_date"]["dateTime"],
                         "2026-12-31T10:00:00")

    def test_draft_flag_is_preserved(self):
        """RULE 0: a reschedule can never be what takes a post out of draft."""
        self.assertIs(build()[0]["info"]["draft"], True)

    def test_unknown_network_refuses(self):
        post = live_post(providers=[{"network": "mastodon"}])
        with self.assertRaises(Refusal) as cm:
            build(post)
        self.assertEqual(cm.exception.reason, "unknown_network")


class RefusalCase(unittest.TestCase):
    def test_past_date_refuses(self):
        with self.assertRaises(Refusal) as cm:
            build(new_date="2026-09-01T09:00:00")
        self.assertEqual(cm.exception.reason, "date_in_past")

    def test_date_equal_to_now_refuses(self):
        with self.assertRaises(Refusal) as cm:
            build(new_date=NOW)
        self.assertEqual(cm.exception.reason, "date_in_past")

    def test_offset_bearing_date_refuses(self):
        with self.assertRaises(Refusal) as cm:
            build(new_date="2026-12-24T09:00:00-05:00")
        self.assertEqual(cm.exception.reason, "bad_new_date")

    def test_non_draft_refuses_while_draft_mode_is_on(self):
        with self.assertRaises(Refusal) as cm:
            build(live_post(draft=False), require_draft=True)
        self.assertEqual(cm.exception.reason, "not_a_draft")

    def test_non_draft_allowed_once_draft_mode_is_flipped(self):
        payload, _ = build(live_post(draft=False), require_draft=False)
        self.assertIs(payload["info"]["draft"], False)

    def test_missing_uuid_refuses(self):
        post = live_post()
        del post["uuid"]
        with self.assertRaises(Refusal) as cm:
            build(post)
        self.assertEqual(cm.exception.reason, "missing_uuid")


class NoopCase(unittest.TestCase):
    def test_same_date_is_a_noop_not_a_write(self):
        """'An action only exists if it changes something' — social-plan-schema.md."""
        result, _ = build(new_date="2026-12-31T10:00:00")
        self.assertTrue(result["noop"])
        self.assertEqual(result["reason"], "date_unchanged")
        self.assertNotIn("info", result)


class CliCase(unittest.TestCase):
    def run_cli(self, *args, stdin=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--timezone", TZ, "--now", NOW, *args],
            input=json.dumps(stdin if stdin is not None else LIVE),
            capture_output=True, text=True,
        )

    def test_exit_zero_and_payload_on_success(self):
        r = self.run_cli("--post-uuid", UUID, "--new-date", "2026-12-24T09:00:00")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["uuid"], "-5728278742307617912")

    def test_exit_two_and_json_reason_on_refusal(self):
        r = self.run_cli("--post-uuid", "nope", "--new-date", "2026-12-24T09:00:00")
        self.assertEqual(r.returncode, 2)
        out = json.loads(r.stdout)
        self.assertTrue(out["refused"])
        self.assertEqual(out["reason"], "post_not_found")
        self.assertIn("refused (post_not_found)", r.stderr)

    def test_exit_one_on_malformed_input(self):
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--post-uuid", UUID, "--new-date",
             "2026-12-24T09:00:00", "--timezone", TZ],
            input="{not json", capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 1)

    def test_require_draft_is_opt_in(self):
        r = self.run_cli("--post-uuid", UUID, "--new-date", "2026-12-24T09:00:00",
                         "--require-draft", stdin={"data": [live_post(draft=False)]})
        self.assertEqual(r.returncode, 2)
        self.assertEqual(json.loads(r.stdout)["reason"], "not_a_draft")


if __name__ == "__main__":
    unittest.main()
