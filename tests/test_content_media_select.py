#!/usr/bin/env python3
"""Tests for scripts/content_media_select.py — mostly the refusals.

Stdlib unittest, matching the repo's convention.

The happy path here is one line of logic. The value is in what it declines to do:
this choice ends up on a public feed, and a wrong clip cannot be unposted. So the
cases below are weighted heavily toward ambiguity, and each asserts the REASON, not
just that something was raised — a refusal whose reason drifts is a refusal whose
caller stops handling it correctly.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from content_media_select import (  # noqa: E402
    Refusal, classify, find_final, normalize, notion_id_from, select_media,
)

SCRIPT = REPO_ROOT / "scripts" / "content_media_select.py"
FOLDER = "application/vnd.google-apps.folder"


def f(name, id_=None, folder=False):
    return {"id": id_ or name, "title": name,
            "mimeType": FOLDER if folder else "application/octet-stream"}


class NotionIdCase(unittest.TestCase):
    def test_tolerates_every_prefix_spelling_in_the_wild(self):
        """All three exist at once during the migration; live reads found all three."""
        for name in ("TC-170_QA Scratch", "TFC-170_QA Scratch", "TFC170_QA Scratch",
                     "TC_170_QA Scratch"):
            self.assertEqual(notion_id_from(name), 170, name)

    def test_does_not_invent_an_id(self):
        for name in ("MEDIA FILES", "03_FINAL", "Untitled folder", ""):
            self.assertIsNone(notion_id_from(name), name)

    def test_does_not_confuse_a_scaffold_folder_for_content(self):
        """01_RAW starts with digits but is not TC-1. Matching it would resolve the
        wrong folder for content id 1."""
        self.assertIsNone(notion_id_from("01_RAW"))
        self.assertIsNone(notion_id_from("70_VOICEOVERS"))


class ClassifyCase(unittest.TestCase):
    def test_known_types(self):
        self.assertEqual(classify("MT_SCRATCH_EDU_31082026.mp4"), "video")
        self.assertEqual(classify("cover.JPG"), "image")
        self.assertIsNone(classify("notes.txt"))
        self.assertIsNone(classify("project.prproj"))


class FindFinalCase(unittest.TestCase):
    def test_finds_it(self):
        entries = normalize([f("01_RAW", folder=True), f("03_FINAL", "fin", folder=True)])
        self.assertEqual(find_final(entries)["final_dir_id"], "fin")

    def test_refuses_when_absent_and_names_what_is_there(self):
        entries = normalize([f("01_RAW", folder=True), f("02_EDIT", folder=True)])
        with self.assertRaises(Refusal) as cm:
            find_final(entries)
        self.assertEqual(cm.exception.reason, "no_final_dir")
        self.assertIn("01_RAW", cm.exception.detail)

    def test_a_file_named_03_final_is_not_the_directory(self):
        entries = normalize([f("03_FINAL.txt")])
        with self.assertRaises(Refusal) as cm:
            find_final(entries)
        self.assertEqual(cm.exception.reason, "no_final_dir")


class SelectMediaCase(unittest.TestCase):
    def test_single_video(self):
        r = select_media(normalize([f("clip.mp4", "v1")]))
        self.assertEqual(r["media"]["id"], "v1")
        self.assertIsNone(r["cover"])

    def test_video_plus_named_cover(self):
        r = select_media(normalize([f("clip.mp4", "v1"), f("cover.jpg", "c1")]))
        self.assertEqual(r["media"]["id"], "v1")
        self.assertEqual(r["cover"]["id"], "c1")

    def test_two_videos_refuses(self):
        """The case this whole module exists for."""
        with self.assertRaises(Refusal) as cm:
            select_media(normalize([f("a.mp4"), f("b.mp4")]))
        self.assertEqual(cm.exception.reason, "multiple_videos")
        self.assertIn("a.mp4", cm.exception.detail)

    def test_empty_refuses(self):
        with self.assertRaises(Refusal) as cm:
            select_media(normalize([]))
        self.assertEqual(cm.exception.reason, "empty_final_dir")

    def test_only_junk_refuses(self):
        with self.assertRaises(Refusal) as cm:
            select_media(normalize([f("notes.txt"), f("project.prproj")]))
        self.assertEqual(cm.exception.reason, "no_postable_asset")

    def test_multiple_images_no_video_refuses(self):
        """Carousel order is a human decision, not alphabetical."""
        with self.assertRaises(Refusal) as cm:
            select_media(normalize([f("1.jpg"), f("2.jpg"), f("3.jpg")]))
        self.assertEqual(cm.exception.reason, "multiple_images_no_video")

    def test_subfolders_do_not_count_as_assets(self):
        with self.assertRaises(Refusal) as cm:
            select_media(normalize([f("old", folder=True)]))
        self.assertEqual(cm.exception.reason, "empty_final_dir")


class CoverCase(unittest.TestCase):
    def test_heic_is_never_chosen_as_a_cover(self):
        """Metricool takes jpg/jpeg/png only. A .heic cover rejects the whole post,
        so it is warned about, not quietly used."""
        r = select_media(normalize([f("clip.mp4", "v1"), f("cover.heic", "c1")]))
        self.assertIsNone(r["cover"])
        self.assertTrue(any("jpg" in w for w in r["warnings"]))

    def test_ambiguous_covers_yield_none_not_a_guess(self):
        r = select_media(normalize([f("clip.mp4", "v1"), f("a.jpg"), f("b.jpg")]))
        self.assertIsNone(r["cover"], "an unintended cover is worse than none")
        self.assertTrue(r["warnings"])

    def test_two_named_covers_yield_none(self):
        r = select_media(normalize([f("clip.mp4", "v1"), f("cover1.jpg"), f("cover_alt.jpg")]))
        self.assertIsNone(r["cover"])

    def test_lone_unnamed_image_is_accepted_as_cover(self):
        r = select_media(normalize([f("clip.mp4", "v1"), f("still.png", "c1")]))
        self.assertEqual(r["cover"]["id"], "c1")

    def test_a_lone_image_is_the_media_not_its_own_cover(self):
        r = select_media(normalize([f("promo.jpg", "i1")]))
        self.assertEqual(r["media"]["id"], "i1")
        self.assertIsNone(r["cover"])


class NormalizeCase(unittest.TestCase):
    def test_accepts_drive_mcp_shape_and_bare_list(self):
        drive = {"files": [{"id": "x", "title": "clip.mp4", "mimeType": "video/mp4"}]}
        self.assertEqual(normalize(drive)[0]["name"], "clip.mp4")
        graph = [{"id": "x", "name": "clip.mp4"}]
        self.assertEqual(normalize(graph)[0]["name"], "clip.mp4")

    def test_skips_entries_with_no_name(self):
        self.assertEqual(normalize([{"id": "x"}]), [])


class CliCase(unittest.TestCase):
    def _run(self, mode, listing):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--mode", mode],
            input=json.dumps(listing), capture_output=True, text=True)

    def test_refusal_exits_2_and_is_machine_readable(self):
        """A caller logs the reason verbatim, so it must be on stdout as JSON —
        not only in a human sentence on stderr."""
        p = self._run("select-media", [f("a.mp4"), f("b.mp4")])
        self.assertEqual(p.returncode, 2)
        body = json.loads(p.stdout)
        self.assertTrue(body["refused"])
        self.assertEqual(body["reason"], "multiple_videos")

    def test_success_exits_0(self):
        p = self._run("select-media", [f("clip.mp4", "v1")])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["media"]["id"], "v1")

    def test_bad_input_exits_1_not_2(self):
        """Distinguishable from a refusal: broken input is a caller bug."""
        p = subprocess.run([sys.executable, str(SCRIPT), "--mode", "select-media"],
                           input="not json", capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)


if __name__ == "__main__":
    unittest.main()
