#!/usr/bin/env python3
"""Tests for scripts/content_migration_map.py.

Stdlib unittest, matching the repo's convention.

This plan drives ~200GB of irreversible-in-practice copying against 32 live folders,
so the cases that matter are the ones where a wrong plan is worse than no plan: two
folders claiming one Notion id (which would MERGE at the destination), a non-content
folder swept in, and the generated script reaching for `sync` instead of `copy`.
"""

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from content_migration_map import (  # noqa: E402
    MapError, build, new_name, parse_name, write_runner,
)


class ParseNameCase(unittest.TestCase):
    def test_all_three_live_spellings(self):
        for name in ("TC-170_QA Scratch", "TFC-170_QA Scratch", "TFC170_QA Scratch"):
            self.assertEqual(parse_name(name), (170, "QA Scratch"), name)

    def test_rejects_scaffold_and_stray_folders(self):
        """01_RAW must not read as content id 1 — it is a subfolder of every item."""
        for name in ("01_RAW", "70_VOICEOVERS", "MEDIA FILES", "Untitled folder"):
            self.assertIsNone(parse_name(name), name)

    def test_rejects_an_unknown_prefix(self):
        """A folder from some other system must not be swept into the migration."""
        self.assertIsNone(parse_name("ABC-12_Something"))

    def test_preserves_the_name_verbatim(self):
        """Including the double space in 'Zubair  Mississauga'. Renaming beyond the
        prefix is scope creep, and a silent rename breaks a human's bookmark."""
        self.assertEqual(parse_name("TFC-70_Zubair  Mississauga"), (70, "Zubair  Mississauga"))
        self.assertEqual(new_name(70, "Zubair  Mississauga"), "TC-70_Zubair  Mississauga")


class BuildCase(unittest.TestCase):
    def test_duplicate_notion_id_is_refused(self):
        """Two folders for one row would MERGE at the destination — silently, since
        rclone copies into a named folder. Refuse rather than plan it."""
        entries = [{"name": "TFC-170_A", "size": 1}, {"name": "TC-170_B", "size": 2}]
        with self.assertRaises(MapError) as cm:
            build(entries)
        self.assertIn("170", str(cm.exception))
        self.assertIn("merge", str(cm.exception).lower())

    def test_smallest_first(self):
        entries = [{"name": "TFC-1_big", "size": 900}, {"name": "TFC-2_small", "size": 5}]
        rows = build(entries)["rows"]
        self.assertEqual([r["notion_id"] for r in rows], [2, 1])
        self.assertEqual([r["order"] for r in rows], [1, 2])

    def test_non_content_is_skipped_not_copied(self):
        entries = [{"name": "TFC-1_real", "size": 1}, {"name": "_TEMPLATES", "size": 99}]
        plan = build(entries)
        self.assertEqual(len(plan["rows"]), 1)
        self.assertEqual(plan["skipped"][0]["name"], "_TEMPLATES")

    def test_totals_are_reported(self):
        plan = build([{"name": "TFC-1_a", "size": 10}, {"name": "TFC-2_b", "size": 5}])
        self.assertEqual(plan["total_bytes"], 15)


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        rows = build([{"name": "TFC-170_QA Scratch", "size": 84957222}])["rows"]
        self.sh = self.tmp / "migrate.sh"
        write_runner(rows, self.sh, "onedrive:src", "gdrive:dst")
        self.text = self.sh.read_text()

    def test_is_valid_bash(self):
        p = subprocess.run(["bash", "-n", str(self.sh)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_uses_copy_and_never_sync(self):
        """`rclone sync` deletes at the destination to match the source. On a
        half-migrated estate that is data loss, so it must never appear."""
        self.assertIn("rclone copy", self.text)
        self.assertNotIn("rclone sync", self.text)

    def test_never_deletes_or_purges(self):
        for danger in ("--delete", "purge", "deletefile", "rmdir"):
            self.assertNotIn(danger, self.text, f"generated script must not contain {danger}")

    def test_checks_one_way(self):
        """Extra files on the Drive side are fine; missing ones are the failure."""
        self.assertIn("--one-way", self.text)

    def test_renames_in_flight(self):
        self.assertIn("TFC-170_QA Scratch", self.text)
        self.assertIn("TC-170_QA Scratch", self.text)

    def test_supports_a_dry_run(self):
        self.assertIn("--dry-run", self.text)

    def test_nonzero_exit_when_any_folder_fails(self):
        self.assertIn("exit 1", self.text)


class CliCase(unittest.TestCase):
    def test_writes_both_artefacts(self):
        tmp = Path(tempfile.mkdtemp())
        listing = '[{"name":"TFC-9_Test","size":123}]'
        p = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "content_migration_map.py"),
             "--out-dir", str(tmp)],
            input=listing, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = list(csv.DictReader((tmp / "migration-map.csv").open()))
        self.assertEqual(rows[0]["new_name"], "TC-9_Test")
        self.assertTrue((tmp / "migrate.sh").stat().st_mode & 0o111, "runner must be executable")

    def test_duplicate_id_exits_2(self):
        tmp = Path(tempfile.mkdtemp())
        listing = '[{"name":"TFC-9_A","size":1},{"name":"TC-9_B","size":1}]'
        p = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "content_migration_map.py"),
             "--out-dir", str(tmp)],
            input=listing, capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertFalse((tmp / "migrate.sh").exists(),
                         "a refused plan must not leave a runnable script behind")


if __name__ == "__main__":
    unittest.main()
