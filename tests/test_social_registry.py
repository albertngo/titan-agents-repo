#!/usr/bin/env python3
"""Structural tests for the social posting registries.

Stdlib unittest, no pytest — matching the repo's convention.

    python3 -m unittest discover -s tests -v

This is the first write path in the repo that reaches a public, customer-facing
surface, so the failures worth guarding are the SILENT ones. A post that errors is
cheap; a post that succeeds while being wrong has already been seen by customers.
Three of those are encoded here as data-shape rules rather than as prose somebody
has to remember:

  * a surface marked auto-publishable for a format its platform API cannot do,
  * a cover declared on a surface where sending one rejects the whole post,
  * TikTok stories, which no tool can publish because the API has no story format.

Same job tests/test_lightspeed.py does for "the read path contains no write verb".
"""

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DESTINATIONS = REPO_ROOT / "platform-settings" / "social-destinations.json"
SOURCES = REPO_ROOT / "platform-settings" / "content-sources.json"
AGENT = REPO_ROOT / ".claude" / "agents" / "social-actions-agent.md"
ACTIONS_LOG_SCHEMA = REPO_ROOT / "contracts" / "actions-log-schema.md"

# Networks Metricool's createScheduledPost contract accepts. A typo here does not
# error at schedule time — it is rejected by Metricool with a message about an
# unknown provider, long after the plan looked fine.
VALID_NETWORKS = {
    "twitter", "facebook", "instagram", "linkedin", "pinterest",
    "youtube", "tiktok", "bluesky", "threads", "gmb",
}

# Covers apply only on these. Sending one anywhere else rejects the ENTIRE post
# with VIDEO_THUMBNAIL_NOT_APPLICABLE — the post, not just the cover.
COVER_CAPABLE = {"instagram", "tiktok", "youtube", "linkedin", "facebook"}
VALID_COVER_MODES = {"image_url", "frame_offset", "separate_call", "none"}


def surfaces(d):
    return {k: v for k, v in d["surfaces"].items() if not k.startswith("_")}


class SocialRegistryCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dest = json.loads(DESTINATIONS.read_text())
        cls.src = json.loads(SOURCES.read_text())

    def test_every_surface_names_a_valid_network(self):
        for name, s in surfaces(self.dest).items():
            self.assertIn(s["network"], VALID_NETWORKS,
                          f"{name} routes to unknown network {s['network']!r}")

    def test_enabled_surfaces_have_a_connected_network(self):
        """A surface cannot be enabled if its network was never linked in Metricool.

        This is the check that would have caught shipping Google Business Profile
        as live while it was still unconnected — the whole reason Metricool was
        chosen over Blotato.
        """
        connected = {k: v for k, v in self.dest["connected_networks"].items()
                     if not k.startswith("_")}
        for name, s in surfaces(self.dest).items():
            if s.get("enabled"):
                self.assertIsNotNone(
                    connected.get(s["network"]),
                    f"{name} is enabled but {s['network']} is not connected in Metricool")

    def test_cover_mode_is_known_and_possible(self):
        for name, s in surfaces(self.dest).items():
            mode = s.get("cover")
            self.assertIn(mode, VALID_COVER_MODES, f"{name} has cover mode {mode!r}")
            if mode in ("image_url", "frame_offset"):
                self.assertIn(
                    s["network"], COVER_CAPABLE,
                    f"{name} declares a cover but {s['network']} cannot take one — "
                    "sending it would reject the whole post")

    def test_no_story_surface_declares_a_cover(self):
        """Stories are ephemeral and have no cover. Declaring one rejects the post."""
        for name, s in self.dest["story_surfaces"].items():
            if name.startswith("_") or not isinstance(s, dict):
                continue
            if s.get("supported") is False:
                continue
            self.assertEqual(s.get("cover"), "none",
                             f"story surface {name} must not declare a cover")

    def test_tiktok_stories_are_marked_impossible(self):
        """Not a tool gap — TikTok's Content Posting API has no story format.

        Pinned as a test so a future reader cannot 'fix' it by enabling it.
        """
        tiktok = self.dest["story_surfaces"].get("TikTok")
        self.assertIsNotNone(tiktok, "TikTok must appear in story_surfaces, as unsupported")
        self.assertIs(tiktok.get("supported"), False)

    def test_gmb_records_the_video_text_split(self):
        """publication cannot carry video; photo carries no text. Silent data loss."""
        gmb = surfaces(self.dest)["Google My Business"]
        self.assertIn("_video_trap", gmb,
                      "the GMB publication/photo split must stay documented in the registry")

    def test_write_mode_is_draft_until_deliberately_changed(self):
        self.assertEqual(self.dest["write_mode"]["mode"], "draft",
                         "staged rollout: flipping this is a dated decision, not an edit")

    def test_drive_root_is_pinned_by_id(self):
        """Three folders in this account match 'Titan Flooring', one owned by an
        outside agency. Resolving the root by title could write into theirs."""
        root = self.src["drive"]["root_folder_id"]
        self.assertTrue(root and not root.startswith("_"), "drive root must be a real id")

    def test_drive_sharing_is_not_scoped_to_the_root(self):
        """Sharing the root would expose every 01_RAW folder — raw unedited footage
        inside clients' homes — to anyone holding the link. Finished assets are
        already bound for public feeds; raw footage never consented to that."""
        self.assertEqual(self.src["drive"]["share_scope"], "media_dir_only")

    def test_prefix_is_data_and_legacy_cannot_collide(self):
        conv = self.src["folder_convention"]
        self.assertTrue(conv["prefix"], "prefix must be configured, not hardcoded")
        for legacy in conv["legacy_prefixes"]:
            self.assertNotIn(conv["prefix"], legacy,
                             f"{conv['prefix']!r} is a substring of legacy {legacy!r} — "
                             "a half-migrated estate could match the wrong folder")

    def test_registry_surfaces_match_the_notion_option_list(self):
        """social-destinations surfaces and Notion's 'Next: Post To' options are two
        halves of one mapping. A surface Notion cannot select is dead config; an
        option with no surface routes nowhere and fails at plan time."""
        registry = set(surfaces(self.dest))
        notion = set(self.src["sources"]["titan_content_ideas"]["surface_values"])
        self.assertEqual(registry, notion,
                         "registry surfaces and Notion 'Next: Post To' options have drifted")

    def test_pipeline_never_writes_the_planning_properties(self):
        """Deciding what to post is a person's job. An agent that can rewrite
        'Next: Post To' or 'Caption' has crossed from executing into originating."""
        w = self.src["sources"]["titan_content_ideas"]["write_properties"]
        written = {v for k, v in w.items() if not k.startswith("_")}
        for forbidden in ("Status", "Next: Post To", "Caption", "Post Date", "Link to Files"):
            self.assertNotIn(forbidden, written,
                             f"{forbidden} must never be writable by the pipeline")

    def test_agent_action_types_are_in_the_log_vocabulary(self):
        """actions-log-schema.md's table is closed. An agent writing a type that is
        not in it produces a log entry nothing downstream can classify."""
        schema = ACTIONS_LOG_SCHEMA.read_text()
        for t in ("social_schedule_post", "social_update_post", "social_flag_manual"):
            self.assertIn(t, schema, f"{t} missing from the actions-log vocabulary")

    def test_agent_refuses_live_post_edits_and_replies(self):
        """The two refusals that matter most, pinned so a later edit cannot quietly
        drop them: a live post has already been seen, and an agent must never speak
        to a customer in Titan's voice."""
        text = AGENT.read_text().lower()
        self.assertIn("deleting or editing a live post", text)
        self.assertIn("never", text)
        self.assertTrue("comment" in text and "dm" in text,
                        "the agent must explicitly refuse comment/DM replies")


if __name__ == "__main__":
    unittest.main()
