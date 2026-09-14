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
        cls.snapshot = json.loads(SNAPSHOT.read_text())

    @classmethod
    def _module(cls, module_id: int) -> dict:
        for m in cls.snapshot["blueprint"]["flow"]:
            if m["id"] == module_id:
                return m
        raise AssertionError(f"module {module_id} is not in the blueprint snapshot")

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

    def test_the_documented_share_posture_matches_the_blueprint(self):
        """The registry must describe the scenario that exists, not one I built.

        This test previously asserted share.folder == "03_FINAL" and role ==
        "reader" -- against the registry, which is where those strings were
        written. It checked this file against itself and passed while both claims
        were false: module 10 shares {{4.id}}, the CONTENT folder, as `writer`.

        So read the blueprint. A documentation test that never opens the artifact
        it documents is worse than no test, because it converts a wrong document
        into a green one.
        """
        share_module = self._module(10)
        self.assertEqual(share_module["module"], "google-drive:shareAFileFolder")
        mapper = share_module["mapper"]
        self.assertEqual(mapper["role"], self.scenario["share"]["role"])
        self.assertEqual(mapper["type"], self.scenario["share"]["type"])
        # It shares the content folder module 4 created, not a scaffold subfolder.
        self.assertEqual(mapper["folder"], "{{4.id}}")
        self.assertIn("{{4.id}}", self.scenario["share"]["folder"])

    def test_the_raw_footage_exposure_stays_on_the_record(self):
        """anyone/writer on the content folder inherits down to 01_RAW: raw footage
        shot inside clients' homes, deletable by any link-holder, with those links
        published on ~45 Notion rows.

        The scenario is frozen by decision, so this is not a failing build -- it is
        an open risk that must not quietly disappear from the registry the next time
        someone tidies it.
        """
        share = self.scenario["share"]
        self.assertEqual(share["role"], "writer", "if this changed, update the risk note")
        self.assertTrue(share["_OPEN_RISK_raw_footage_is_publicly_writable"].strip())

    def test_the_link_is_written_from_the_shared_folder(self):
        """Link to Files comes from {{10.shareLink}}, so the row's link and the
        thing that got shared are the same folder by construction. If module 11 is
        ever repointed at {{4.webViewLink}} without re-narrowing module 10, the row
        would link to a folder nobody shared and open for nobody."""
        notion_module = self._module(11)
        link_key = self.scenario["notion_link_field_key"]
        self.assertEqual(notion_module["mapper"]["fields"][link_key], "{{10.shareLink}}")

    def test_known_behaviours_stay_documented(self):
        """Each was found by tracing a live run, and each looks like a fresh bug to
        whoever meets it next. Losing the note costs that tracing again."""
        behaviours = self.scenario["known_behaviours"]
        for key in ("re_fire_blocked_FIXED", "link_points_at_the_content_folder",
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
