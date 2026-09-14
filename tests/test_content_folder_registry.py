#!/usr/bin/env python3
"""Structural tests for the content-folder Make scenario registry.

Stdlib unittest, no pytest -- matching the repo's convention.

    python3 -m unittest discover -s tests -v

Nothing here can reach Make, so these guard registry COHERENCE -- the same job
tests/test_social_registry.py does for the posting surfaces. Every assertion below
corresponds to a failure that produces no error message:

  * the root sentinel drifting from the pinned Drive root, which silently creates
    every folder in the wrong place,
  * a sentinel shaped like a Notion page id, which would hand a real row's folder
    out as the root,
  * max_attempts stored as a string, which compares lexically -- the same class of
    bug as the inverted filter that made the first build process nothing,
  * sequential flipped off, which re-opens the sibling race that leaves two
    identically-named parent folders and a datastore pointing at one of them.

The scenario was green for two runs while being fundamentally broken. These are the
parts of that story a test can hold onto.
"""

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES = REPO_ROOT / "platform-settings" / "content-sources.json"

# Notion page ids are 8-4-4-4-12 hex. A sentinel matching this could collide with a
# real row, and the collision would look like a successful lookup.
NOTION_PAGE_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class ContentFolderRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(SOURCES.read_text())
        cls.scenario = cls.registry["make_scenario"]
        cls.datastore = cls.scenario["datastore"]

    def test_root_sentinel_matches_the_pinned_drive_root(self):
        """The base case of the recursion must point at the same folder as the registry.

        If these drift, every content folder in the business is created somewhere
        else and nothing errors -- the scenario reports success either way. This is
        the single most valuable assertion in this file.
        """
        self.assertEqual(
            self.datastore["root_sentinel_value"],
            self.registry["drive"]["root_folder_id"],
            "root_sentinel_value must equal drive.root_folder_id",
        )

    def test_root_sentinel_cannot_be_mistaken_for_a_notion_page(self):
        key = self.datastore["root_sentinel_key"]
        self.assertTrue(key, "the recursion has no base case without a sentinel key")
        self.assertIsNone(
            NOTION_PAGE_ID.match(key),
            f"sentinel {key!r} is shaped like a Notion page id and could collide with a real row",
        )

    def test_max_attempts_is_a_real_integer(self):
        """A string here compares as text, so the runaway guard stops working past 9."""
        value = self.scenario["max_attempts"]
        self.assertIsInstance(value, int)
        self.assertNotIsInstance(value, bool)
        # The deepest real chain today is 3 levels; each level costs one re-fire.
        self.assertGreaterEqual(value, 4)
        self.assertLessEqual(value, 20)

    def test_sequential_processing_stays_on(self):
        """Encoded as data so nobody turns it off without reading why it is on.

        It is what makes two siblings racing to create the same missing parent
        impossible, and it is only safe because no execution blocks on another.
        """
        self.assertIs(self.scenario["sequential"], True)

    def test_sharing_stays_narrow(self):
        """The predecessor shared a folder above 01_RAW as `writer` -- raw footage
        inside clients' homes, editable by anyone holding the link."""
        share = self.scenario["share"]
        self.assertEqual(share["folder"], "03_FINAL")
        self.assertEqual(share["role"], "reader")

    def test_the_shared_folder_is_a_real_scaffold_folder(self):
        """Sharing a folder the scaffold never creates would silently share nothing."""
        self.assertIn(
            self.scenario["share"]["folder"],
            self.registry["folder_convention"]["scaffold"],
        )

    def test_scenario_and_hook_are_pinned_by_id(self):
        for field in ("scenario_id", "hook_id", "datastore", "notion_data_source"):
            self.assertIn(field, self.scenario)
        self.assertIsInstance(self.scenario["scenario_id"], int)
        self.assertIsInstance(self.scenario["hook_id"], int)
        self.assertNotEqual(
            self.scenario["hook_id"],
            self.scenario["_superseded"]["hook_id"],
            "the live scenario must not share the retired scenario's hook",
        )

    def test_datastore_records_where_not_merely_whether(self):
        """contentID holds a Drive folder id. A hand-edit once put the row's TITLE
        here, which would have been passed to createAFolder as a parent id."""
        self.assertEqual(self.datastore["key"], "notion_page_id")
        self.assertEqual(self.datastore["field"], "contentID")

    def test_status_gate_options_are_documented(self):
        """The gate applies to Notion-originated calls only; a parent must build
        regardless of its own Status. Both halves must stay recorded."""
        self.assertTrue(self.scenario["trigger_statuses"])
        self.assertIn("_status_gate_is_entry_only", self.scenario)

    def test_status_does_not_claim_a_verified_fire(self):
        """The scenario was green twice while being broken. Until a real fire under
        the current design is observed, the registry must not read as proven."""
        status = self.scenario["_status"].lower()
        self.assertIn("never fired", status)

    def test_datastore_key_is_the_notion_page_id(self):
        """Keyed on TC-<n> instead, nesting silently dies.

        Notion's Parent item relation returns page ids, so a child can only ever
        look its parent up by page id. This has been hand-changed three times; the
        reasoning is pinned in the registry so it survives the next edit.
        """
        self.assertEqual(self.datastore["key"], "notion_page_id")
        self.assertIn("_why_the_key_cannot_be_TC_n", self.datastore)

    def test_label_field_exists_so_the_key_does_not_have_to_be_readable(self):
        """The readable-label escape hatch. Without it the pressure lands on the
        key, which is the one field that cannot absorb it."""
        fields = self.datastore["fields"]
        self.assertIn("label", fields)
        self.assertIn("contentID", fields)


if __name__ == "__main__":
    unittest.main()
