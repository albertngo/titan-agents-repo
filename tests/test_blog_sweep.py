#!/usr/bin/env python3
"""Pins scripts/blog_sweep.py: absence of a check is never proof of publication.

    python3 -m unittest discover -s tests -v
"""

import copy
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import blog_sweep  # noqa: E402
import content_engine_lib as lib  # noqa: E402

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
HOST = "titan-website.vercel.app"


def rows():
    return [
        {"url": "https://www.notion.so/p1", "id": "BP-1", "slug": "a", "status": "Approved", "pr_url": "https://github.com/x/pull/1"},
        {"url": "https://www.notion.so/p2", "id": "BP-2", "slug": "b", "status": "Approved", "pr_url": "https://github.com/x/pull/2"},
        {"url": "https://www.notion.so/p3", "id": "BP-3", "slug": "c", "status": "Approved", "pr_url": "https://github.com/x/pull/3"},
        {"url": "https://www.notion.so/p4", "id": "BP-4", "slug": "d", "status": "Approved", "pr_url": "https://github.com/x/pull/4"},
        {"url": "https://www.notion.so/p5", "id": "BP-5", "slug": "e", "status": "Published", "published_sha1": "aaa", "video_url": None},
        {"url": "https://www.notion.so/p6", "id": "BP-6", "slug": "f", "status": "Approved", "pr_url": "https://github.com/x/pull/6"},
    ]


def checks():
    return {"production_host": HOST, "posts": {
        "a": {"pr_state": "merged", "http_status": 200, "canonical": f"https://{HOST}/a/"},
        "b": {"pr_state": "open", "http_status": None, "canonical": None},
        "c": {"pr_state": "merged", "http_status": 404, "canonical": None},
        "d": {"pr_state": "merged", "http_status": 200, "canonical": f"https://{HOST}/wrong/"},
        "e": {"body_sha1": "bbb", "video_url": "https://youtu.be/abcdefghijk"},
    }}


class TestSweep(unittest.TestCase):
    def setUp(self):
        self.reg = copy.deepcopy(lib.load_registry())
        self.out = blog_sweep.decide(self.reg, rows(), checks(), NOW)

    def test_merged_live_canonical_becomes_published(self):
        p = self.out["proposals"]
        self.assertEqual([x["target"]["bp_id"] for x in p], ["BP-1"])
        self.assertEqual(p[0]["fields"]["Status"], "Published")
        self.assertEqual(p[0]["fields"]["Direct URL"], f"https://{HOST}/a/")
        self.assertEqual(p[0]["fields"]["Publish Date"], "2026-10-14")
        self.assertEqual(p[0]["expect"], {"Status": "Approved"})

    def test_open_pr_and_404_wait(self):
        self.assertEqual({x["bp_id"] for x in self.out["not_yet"]}, {"BP-2", "BP-3", "BP-6"})

    def test_canonical_mismatch_never_writes(self):
        self.assertEqual([x["bp_id"] for x in self.out["url_mismatch"]], ["BP-4"])

    def test_missing_check_is_not_success(self):
        self.assertIn("BP-6", {x["bp_id"] for x in self.out["not_yet"]})

    def test_body_change_after_publish_is_flagged_and_video_is_a_candidate(self):
        self.assertEqual(self.out["flagged"][0]["reason"], "body_changed_after_publish")
        self.assertEqual(self.out["video_candidates"][0]["bp_id"], "BP-5")

    def test_no_host_means_needs_person(self):
        c = checks()
        c["production_host"] = None
        reg = copy.deepcopy(self.reg)
        reg["website"]["production_host"] = None
        out = blog_sweep.decide(reg, rows(), c, NOW)
        self.assertEqual(out["proposals"], [])
        self.assertTrue(all(x["detail"].startswith("no production_host") for x in out["needs_person"]))


if __name__ == "__main__":
    unittest.main()
