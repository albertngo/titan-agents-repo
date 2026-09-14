#!/usr/bin/env python3
"""Tests for scripts/social_publish_reconcile.py — weighted toward the wrong match.

Stdlib unittest, matching the repo's convention.

The failure that matters here is not "no match found" — that is reported and a person
looks. It is a WRONG match: another post's URL and caption written onto this row,
which nothing downstream can detect, because both values are perfectly well-formed.
So most of these tests pin cases where the module must refuse rather than choose.

The analytics fixture is the verbatim row returned by getAnalyticsDataByMetrics for
brand 3951085 on 2026-09-14, metrics IGRE02/IGRE03/IGRE04/IGRE06.
"""

import json
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from social_publish_reconcile import (  # noqa: E402
    BadInput, parse_local, reconcile, reconcile_row, surface_fields, unpack,
)

SCRIPT = REPO_ROOT / "scripts" / "social_publish_reconcile.py"
REGISTRY = json.loads((REPO_ROOT / "platform-settings" / "social-destinations.json").read_text())

# Verbatim from the live call, 2026-09-14.
LIVE_ROW = ["20260806033114", "Tbh we worked really hard on this sign….",
            "3957465875652649088_50452818241",
            "https://www.instagram.com/reel/Dbrvj8RAaCA/"]


def row(due="2026-09-16T20:00:00", surface="Instagram Reels", uuid="-495330"):
    return {"url": "https://www.notion.so/abc", "Content Name": "CC: Test",
            "Post To": surface, "Metricool UUID": uuid, "Post Date": due}


def pub(posted_at, url="https://www.instagram.com/reel/AAA/", text="hello"):
    return {"posted_at": posted_at, "url": url, "text": text}


class ParseCase(unittest.TestCase):
    def test_compact_analytics_timestamp_is_read_as_utc(self):
        """'20260806033114' -> 2026-08-05 23:31 Toronto. See the registry's note on
        why UTC is the working assumption and why the matcher does not lean on it."""
        self.assertEqual(parse_local("20260806033114"), datetime(2026, 8, 5, 23, 31, 14))

    def test_compact_can_be_read_as_local_when_confirmed(self):
        self.assertEqual(parse_local("20260806033114", assume_utc=False),
                         datetime(2026, 8, 6, 3, 31, 14))

    def test_all_three_wire_formats_land_on_the_same_scale(self):
        notion = parse_local("2026-09-17T00:00:00.000Z")      # UTC instant
        metricool = parse_local("2026-09-16T20:00:00")         # local wall clock
        self.assertEqual(notion, metricool)


class RegistryCase(unittest.TestCase):
    def test_every_postable_surface_has_a_mapping(self):
        for surface in ("Instagram Reels", "Facebook Page", "TikTok",
                        "YouTube - Shorts", "YouTube - Long", "Google Business Profile"):
            entry, fields = surface_fields(REGISTRY, surface)
            self.assertIn("posted_at", fields, surface)

    def test_linkedin_is_explicitly_unavailable_not_silently_missing(self):
        with self.assertRaises(BadInput) as cm:
            surface_fields(REGISTRY, "LinkedIn")
        self.assertIn("not connected", str(cm.exception))

    def test_youtube_has_no_caption_field(self):
        """Analytics exposes a title, not a description. A title is not a caption."""
        _, fields = surface_fields(REGISTRY, "YouTube - Shorts")
        self.assertNotIn("text", fields)
        self.assertIn("title", fields)

    def test_gbp_has_no_permalink(self):
        _, fields = surface_fields(REGISTRY, "Google Business Profile")
        self.assertNotIn("url", fields)

    def test_youtube_does_not_use_the_deprecated_connector(self):
        """Every field of YouTube's 'videos' connector is labelled 'Do not use'."""
        for surface in ("YouTube - Shorts", "YouTube - Long"):
            entry, fields = surface_fields(REGISTRY, surface)
            self.assertEqual(entry["connector"], "all videos")
            self.assertFalse(any(f.startswith("YTVI") for f in fields.values()))


class UnpackCase(unittest.TestCase):
    def test_positional_rows_map_to_roles_in_request_order(self):
        _, fields = surface_fields(REGISTRY, "Instagram Reels")
        got = unpack([LIVE_ROW], fields)[0]
        self.assertEqual(got["url"], "https://www.instagram.com/reel/Dbrvj8RAaCA/")
        self.assertEqual(got["text"], "Tbh we worked really hard on this sign….")
        self.assertEqual(got["posted_at"], "20260806033114")

    def test_column_count_mismatch_refuses_rather_than_transposing(self):
        """A silent transpose writes a caption into Live URL and errors nowhere."""
        _, fields = surface_fields(REGISTRY, "Instagram Reels")
        with self.assertRaises(BadInput) as cm:
            unpack([LIVE_ROW[:2]], fields)
        self.assertIn("Refusing to unpack", str(cm.exception))


class MatchCase(unittest.TestCase):
    def test_a_single_post_in_the_window_is_confirmed(self):
        verdict, detail, write = reconcile_row(row(), [pub("2026-09-17T00:05:00.000Z")], 12)
        self.assertEqual(verdict, "published_confirmed")
        self.assertEqual(write["Post Status"], "Posted")
        self.assertEqual(write["Live URL"], "https://www.instagram.com/reel/AAA/")
        self.assertEqual(write["Posted Caption"], "hello")

    def test_nothing_in_the_window_is_not_published(self):
        """The sweep would have guessed 'published' here. This does not."""
        verdict, detail, write = reconcile_row(row(), [pub("2026-10-01T00:00:00.000Z")], 12)
        self.assertEqual(verdict, "not_published")
        self.assertEqual(write, {})
        self.assertIn("deleted in the planner", detail)

    def test_analytics_lag_is_named_in_the_not_published_detail(self):
        _, detail, _ = reconcile_row(row(), [], 12)
        self.assertIn("lag", detail)

    def test_two_posts_in_the_window_refuse_rather_than_pick_the_nearest(self):
        """THE test. Picking the closest would be defensible and wrong: it writes
        another post's URL onto this row, well-formed and undetectable."""
        verdict, detail, write = reconcile_row(
            row(), [pub("2026-09-17T00:05:00.000Z", url="https://x/1"),
                    pub("2026-09-17T02:00:00.000Z", url="https://x/2")], 12)
        self.assertEqual(verdict, "ambiguous_match")
        self.assertEqual(write, {})
        self.assertIn("Refusing to pick one", detail)

    def test_tolerance_can_disambiguate_what_a_wide_window_could_not(self):
        posts = [pub("2026-09-17T00:05:00.000Z", url="https://x/1"),
                 pub("2026-09-17T06:00:00.000Z", url="https://x/2")]
        self.assertEqual(reconcile_row(row(), posts, 12)[0], "ambiguous_match")
        self.assertEqual(reconcile_row(row(), posts, 1)[0], "published_confirmed")

    def test_a_row_with_no_due_date_matches_nothing(self):
        verdict, _, write = reconcile_row(row(due=None), [pub("2026-09-17T00:05:00.000Z")], 12)
        self.assertEqual(verdict, "no_due_date")
        self.assertEqual(write, {})

    def test_missing_permalink_is_reported_not_faked(self):
        verdict, detail, write = reconcile_row(
            row(), [{"posted_at": "2026-09-17T00:05:00.000Z", "text": "hi"}], 12)
        self.assertEqual(verdict, "published_confirmed")
        self.assertNotIn("Live URL", write)
        self.assertIn("no permalink", detail)

    def test_a_youtube_title_is_never_written_as_a_caption(self):
        verdict, detail, write = reconcile_row(
            row(surface="YouTube - Shorts"),
            [{"posted_at": "2026-09-17T00:05:00.000Z", "url": "https://yt/1",
              "title": "Staircase Transformation"}], 12)
        self.assertEqual(verdict, "published_confirmed")
        self.assertNotIn("Posted Caption", write)
        self.assertIn("Staircase Transformation", detail)


class ReportCase(unittest.TestCase):
    def test_counts_and_unclaimed_are_reported(self):
        rows = [row(), row(due="2026-12-01T20:00:00", uuid="other")]
        report = reconcile(rows, [pub("2026-09-17T00:05:00.000Z", url="https://x/1")], 12)
        self.assertEqual(report["counts"]["published_confirmed"], 1)
        self.assertEqual(report["counts"]["not_published"], 1)
        self.assertEqual(report["unclaimed_published"], [])

    def test_unclaimed_published_posts_are_surfaced(self):
        report = reconcile([], [pub("2026-09-17T00:05:00.000Z", url="https://x/9")], 12)
        self.assertEqual(report["unclaimed_published"], ["https://x/9"])

    def test_empty_is_healthy(self):
        report = reconcile([], [], 12)
        self.assertEqual(report["counts"], {})


class CliCase(unittest.TestCase):
    def test_print_metrics_emits_the_request_list_in_order(self):
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--surface", "Instagram Reels",
             "--rows", "/dev/null", "--analytics", "/dev/null",
             "--registry", str(REPO_ROOT / "platform-settings" / "social-destinations.json"),
             "--print-metrics"], capture_output=True, text=True, cwd=REPO_ROOT)
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(out["metrics"], ["IGRE02", "IGRE03", "IGRE04", "IGRE06"])
        self.assertEqual(out["connector"], "reels")

    def test_unknown_surface_exits_one(self):
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--surface", "Myspace",
             "--rows", "/dev/null", "--analytics", "/dev/null",
             "--registry", str(REPO_ROOT / "platform-settings" / "social-destinations.json"),
             "--print-metrics"], capture_output=True, text=True, cwd=REPO_ROOT)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
