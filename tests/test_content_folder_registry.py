#!/usr/bin/env python3
"""Structural tests for the content-folder Make scenario registry.

Stdlib unittest, no pytest -- matching the repo's convention.

    python3 -m unittest discover -s tests -v

The scenario itself is FROZEN and hand-edited in the Make UI (2026-09-14), so
these tests cannot and do not police its behaviour. What they guard is that the
registry keeps telling the truth ABOUT it, because the expensive mistake in this
area has never been a broken scenario -- it has been a correct-looking document
describing a scenario that no longer exists.

Two things earn a test here:

  * facts a wrong value would make silently wrong (the content root the scenario
    hardcodes; the sharing posture that keeps raw client footage private),
  * the known behaviours, which must stay written down. They were each found by
    tracing a live run, and every one of them looks like a bug to whoever meets
    it next without the note.

Same job tests/test_lightspeed.py does for "the read path contains no write verb".
"""

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES = REPO_ROOT / "platform-settings" / "content-sources.json"
SNAPSHOT = REPO_ROOT / "platform-settings" / "blueprints" / "content-folder-scenario-4918320.json"


class ContentFolderRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(SOURCES.read_text())
        cls.scenario = cls.registry["make_scenario"]
        cls.datastore = cls.scenario["datastore"]

    def test_hardcoded_content_root_matches_the_pinned_drive_root(self):
        """Module 4 hardcodes a root folder id in its ifempty fallback.

        If that literal and drive.root_folder_id ever diverge, every folder is
        created somewhere other than where the rest of the pipeline looks, and
        nothing errors -- the scenario reports success either way.
        """
        self.assertEqual(
            self.datastore["content_root_folder_id"],
            self.registry["drive"]["root_folder_id"],
        )

    def test_sharing_stays_narrow(self):
        """The OneDrive predecessor shared as `writer` on a folder above 01_RAW --
        raw unedited footage inside clients' homes, editable by anyone holding the
        link. That fix must survive any future rewrite."""
        share = self.scenario["share"]
        self.assertEqual(share["folder"], "03_FINAL")
        self.assertEqual(share["role"], "reader")

    def test_the_shared_folder_is_a_real_scaffold_folder(self):
        """Sharing a folder the scaffold never creates would silently share nothing."""
        self.assertIn(
            self.scenario["share"]["folder"],
            self.registry["folder_convention"]["scaffold"],
        )

    def test_known_behaviours_stay_documented(self):
        """Each was found by tracing a live run, and each looks like a fresh bug to
        whoever meets it next. Losing the note costs that tracing again."""
        behaviours = self.scenario["known_behaviours"]
        for key in ("re_fire_blocked_FIXED", "link_points_at_03_final",
                    "datastore_holds_titles", "writes_post_date"):
            self.assertIn(key, behaviours)
            self.assertTrue(behaviours[key].strip())

    def test_the_already_built_guard_uses_the_singular_field_name(self):
        """`datastore:ExistRecord` outputs `exist`. A filter on `{{N.exists}}` never
        resolves, so the guard silently stops blocking and every re-fire builds
        another full folder tree -- with no error anywhere.

        That exact typo shipped once and survived two green runs before anyone
        noticed. It is checkable against the committed snapshot, so check it.
        """
        snap = json.loads(SNAPSHOT.read_text())
        filters = json.dumps([m.get("filter") for m in snap["blueprint"]["flow"]])
        self.assertIn("{{2.exist}}", filters)
        self.assertNotIn("{{2.exists}}", filters)

    def test_registry_does_not_claim_nesting(self):
        """The parent-aware build is in git history, not in the live scenario.
        A registry that claims otherwise would send someone hunting a bug in
        working code."""
        self.assertEqual(self.scenario["nesting"], "NONE. Every content folder is created at the Drive root.")

    def test_scenario_and_hook_are_pinned_by_id(self):
        self.assertIsInstance(self.scenario["scenario_id"], int)
        self.assertIsInstance(self.scenario["hook_id"], int)
        self.assertNotEqual(
            self.scenario["hook_id"],
            self.scenario["_superseded"]["hook_id"],
            "the live scenario must not share the retired scenario's hook",
        )

    def test_blueprint_snapshot_exists_and_matches_the_registry(self):
        """The snapshot is the only record of a scenario edited outside this repo.
        If it drifts from the registry's ids, one of the two is stale."""
        self.assertTrue(SNAPSHOT.exists(), f"missing blueprint snapshot: {SNAPSHOT}")
        snap = json.loads(SNAPSHOT.read_text())
        self.assertEqual(snap["scenario_id"], self.scenario["scenario_id"])
        self.assertEqual(snap["hook_id"], self.scenario["hook_id"])
        self.assertNotIn("samples", json.dumps(snap["blueprint"]["metadata"]["designer"]),
                         "run samples carry live Notion page content; strip them")

    def test_registry_says_where_the_scenario_is_edited(self):
        """API pushes and UI edits overwrote each other repeatedly on 2026-09-13.
        The warning is the fix."""
        self.assertEqual(self.scenario["edited_in"], "the Make UI")
        self.assertIn("_edited_in_comment", self.scenario)


if __name__ == "__main__":
    unittest.main()
