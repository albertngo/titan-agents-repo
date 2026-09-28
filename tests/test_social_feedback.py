#!/usr/bin/env python3
"""Tests for scripts/social_feedback.py.

Stdlib unittest, matching the repo's convention.

The analytics fixture is the verbatim row getAnalyticsDataByMetrics returned for brand
3951085 on 2026-09-28 -- TC-86's staircase reel -- requested in the registry's own
Instagram stats order (IGRE02, 06, 23, 11, 24, 27, 10, 07, 12, 21). The failure worth
guarding here is the silent one: a column transposed, or another post's numbers matched
onto this row. Both produce perfectly plausible numbers.
"""

import json
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from social_feedback import (  # noqa: E402
    BadInput, analyse, due_pull, find_post, match, num, rates, unpack,
)

SCRIPT = REPO_ROOT / "scripts" / "social_feedback.py"
REGISTRY = json.loads((REPO_ROOT / "platform-settings" / "social-destinations.json").read_text())
IG_STATS = REGISTRY["analytics"]["surfaces"]["Instagram Reels"]["stats"]

LIVE_IG = ["20260915013113", "https://www.instagram.com/reel/DdSiP5xgMYT/",
           "625", "413", "11.029", None, "48", "4", "2", "0"]
NOW = datetime(2026, 9, 28, 12, 0)


def row(**kw):
    base = {"url": "https://www.notion.so/r1", "Content Name": "CC: Staircase",
            "Post To": "Instagram Reels", "Post Status": "Posted",
            "Posted At": "2026-09-15T01:31:00.000Z",
            "Live URL": "https://www.instagram.com/reel/DdSiP5xgMYT/",
            "Caption": "We transformed it.", "Posted Caption": "We transformed it."}
    base.update(kw)
    return base


class UnpackCase(unittest.TestCase):
    def test_live_row_maps_to_the_right_roles(self):
        got = unpack([LIVE_IG], IG_STATS)[0]
        self.assertEqual(got["url"], "https://www.instagram.com/reel/DdSiP5xgMYT/")
        self.assertEqual((got["views"], got["reach"], got["likes"]), ("625", "413", "48"))
        self.assertEqual((got["comments"], got["saves"], got["shares"]), ("4", "2", "0"))
        self.assertIsNone(got["completion_pct"])

    def test_column_count_mismatch_refuses(self):
        with self.assertRaises(BadInput):
            unpack([LIVE_IG[:-1]], IG_STATS)

    def test_strings_parse_and_null_stays_blank(self):
        self.assertEqual(num("625"), 625)
        self.assertEqual(num("11.029"), 11.029)
        self.assertIsNone(num(None))
        self.assertIsNone(num(""))
        self.assertEqual(num("0"), 0)


class RegistryCase(unittest.TestCase):
    PREFIX = {"instagram": "IGRE", "tiktok": "TKPO", "facebook": "FBPO", "youtube": "YTVV"}

    def test_every_stats_block_joins_on_url_with_its_own_network_ids(self):
        for surface, entry in REGISTRY["analytics"]["surfaces"].items():
            if "stats" not in entry:
                continue
            self.assertIn("url", entry["stats"], surface)
            self.assertIn("posted_at", entry["stats"], surface)
            prefix = self.PREFIX[entry["network"]]
            for role, fid in entry["stats"].items():
                self.assertTrue(fid.startswith(prefix), f"{surface}.{role} = {fid}")

    def test_deprecated_instagram_view_fields_are_not_used(self):
        self.assertNotIn("IGRE13", IG_STATS.values())
        self.assertNotIn("IGRE15", IG_STATS.values())


class DueCase(unittest.TestCase):
    def test_not_before_day_7(self):
        self.assertIsNone(due_pull(row(), datetime(2026, 9, 20, 12), REGISTRY)[0])

    def test_day_7(self):
        self.assertEqual(due_pull(row(), NOW, REGISTRY)[0], "day7")

    def test_day_30_after_day_7(self):
        r = row(**{"Stats Pulled At": "2026-09-22"})
        self.assertIsNone(due_pull(r, NOW, REGISTRY)[0])
        self.assertEqual(due_pull(r, datetime(2026, 10, 16, 12), REGISTRY)[0], "day30")

    def test_rolling_from_day_60_every_30_days(self):
        r = row(**{"Stats Pulled At": "2026-09-22", "30d Pulled At": "2026-10-16"})
        self.assertIsNone(due_pull(r, datetime(2026, 11, 1), REGISTRY)[0])
        self.assertEqual(due_pull(r, datetime(2026, 11, 15), REGISTRY)[0], "rolling")
        r["Latest Pulled At"] = "2026-11-15"
        self.assertIsNone(due_pull(r, datetime(2026, 12, 1), REGISTRY)[0])
        self.assertEqual(due_pull(r, datetime(2026, 12, 16), REGISTRY)[0], "rolling")

    def test_settled_and_old_rows_are_never_due(self):
        r = row(**{"Stats Pulled At": "2026-09-22", "30d Pulled At": "2026-10-16",
                   "Tracking": "Settled"})
        self.assertIsNone(due_pull(r, datetime(2027, 1, 1), REGISTRY)[0])
        r["Tracking"] = "Active"
        self.assertIsNone(due_pull(r, datetime(2027, 10, 1), REGISTRY)[0])

    def test_unposted_and_unmapped_rows_are_skipped(self):
        self.assertIsNone(due_pull(row(**{"Post Status": "Scheduled"}), NOW, REGISTRY)[0])
        self.assertIsNone(due_pull(row(**{"Post To": "Google Business Profile"}), NOW, REGISTRY)[0])

    def test_sql_date_shape_is_accepted(self):
        r = row()
        r["date:Posted At:start"] = r.pop("Posted At")
        self.assertEqual(due_pull(r, NOW, REGISTRY)[0], "day7")


class MatchCase(unittest.TestCase):
    def run_match(self, r, pull="day7", rows=None, now=NOW):
        return match([{"pull": pull, "row": r}],
                     {"Instagram Reels": {"rows": rows or [LIVE_IG]}}, REGISTRY, now)["results"][0]

    def test_day7_writes_the_live_numbers(self):
        res = self.run_match(row())
        self.assertEqual(res["verdict"], "matched")
        self.assertEqual(res["matched_by"], "url")
        w = res["write"]
        self.assertEqual((w["Views"], w["Reach"], w["Likes"], w["Comments"], w["Saves"], w["Shares"]),
                         (625, 413, 48, 4, 2, 0))
        self.assertEqual(w["Avg Watch Time (s)"], 11.029)
        self.assertNotIn("Completion %", w, "null must stay blank, never 0")
        self.assertEqual(w["Stats Pulled At"], "2026-09-28")
        self.assertIs(w["Caption Edited"], False)
        self.assertEqual(w["Tracking"], "Active")

    def test_caption_edit_is_detected_ignoring_whitespace_and_case(self):
        same = self.run_match(row(**{"Posted Caption": "  we TRANSFORMED  it. "}))
        self.assertIs(same["write"]["Caption Edited"], False)
        edited = self.run_match(row(**{"Posted Caption": "We rebuilt it."}))
        self.assertIs(edited["write"]["Caption Edited"], True)

    def test_url_mismatch_is_unmatched_not_slotted(self):
        """A row WITH a Live URL that is not in the pull must not fall back to the slot:
        the slot would find this other post and write its numbers."""
        res = self.run_match(row(**{"Live URL": "https://www.instagram.com/reel/OTHER/"}))
        self.assertEqual(res["verdict"], "unmatched")

    def test_slot_fallback_without_url(self):
        res = self.run_match(row(**{"Live URL": None}))
        self.assertEqual(res["matched_by"], "slot")

    def test_two_posts_in_one_slot_refuses(self):
        other = list(LIVE_IG)
        other[0], other[1] = "20260915030000", "https://www.instagram.com/reel/B/"
        res = self.run_match(row(**{"Live URL": None}), rows=[LIVE_IG, other])
        self.assertEqual(res["verdict"], "unmatched")
        self.assertIn("refusing", res["detail"])

    def test_day30_writes_only_its_own_columns(self):
        w = self.run_match(row(), pull="day30")["write"]
        self.assertEqual(w["Views 30d"], 625)
        self.assertNotIn("Views", w)
        self.assertNotIn("Tracking", w)

    def test_late_surge(self):
        r = row(**{"Views 30d": 300})
        w = self.run_match(r, pull="rolling")["write"]
        self.assertEqual(w["Views Latest"], 625)
        self.assertEqual(w["Tracking"], "Late Surge")

    def test_quiet_then_settled(self):
        r = row(**{"Views 30d": 600, "Tracking": "Active"})
        self.assertEqual(self.run_match(r, pull="rolling")["write"]["Tracking"], "Quiet")
        r = row(**{"Views 30d": 600, "Views Latest": 620, "Tracking": "Quiet"})
        self.assertEqual(self.run_match(r, pull="rolling")["write"]["Tracking"], "Settled")

    def test_growth_after_quiet_resets_to_active(self):
        r = row(**{"Views 30d": 400, "Views Latest": 450, "Tracking": "Quiet"})
        self.assertEqual(self.run_match(r, pull="rolling")["write"]["Tracking"], "Active")

    def test_late_first_pull_is_noted(self):
        res = self.run_match(row(), now=datetime(2026, 10, 10, 12))
        self.assertTrue(any("not ranked" in n for n in res["notes"]))


def stats_row(surface="Instagram Reels", views=1000, saves=10, shares=5, comments=5,
              likes=50, watch=10.0, **kw):
    r = {"url": f"https://n/{id(kw)}{views}{saves}", "Post To": surface, "Views": views,
         "Saves": saves, "Shares": shares, "Comments": comments, "Likes": likes,
         "Avg Watch Time (s)": watch, "Posted At": "2026-09-01T12:00:00Z",
         "Stats Pulled At": "2026-09-08"}
    r.update(kw)
    return r


class AnalyseCase(unittest.TestCase):
    def test_rates_are_blank_at_zero_views(self):
        r = rates(stats_row(views=0))
        self.assertIsNone(r["save_rate"])
        self.assertIsNone(r["engagement_rate"])

    def test_four_is_early_signal_five_is_a_conclusion(self):
        four = [stats_row(**{"Caption Formula": "Myth Buster"}, saves=i) for i in range(4)]
        out = analyse(four)["platforms"]["Instagram Reels"]["dimensions"]["Caption Formula"]
        self.assertEqual(out["Myth Buster"]["status"], "early_signal")
        five = four + [stats_row(**{"Caption Formula": "Myth Buster"}, saves=9)]
        out = analyse(five)["platforms"]["Instagram Reels"]["dimensions"]["Caption Formula"]
        self.assertEqual(out["Myth Buster"]["status"], "conclusion")

    def test_outliers_at_two_x(self):
        rows = [stats_row(saves=10) for _ in range(4)] + [stats_row(saves=60, **{"Content Name": "Hit"})]
        outliers = analyse(rows)["platforms"]["Instagram Reels"]["outliers"]
        self.assertTrue(any(o["content_name"] == "Hit" and o["metric"] == "save_rate" for o in outliers))

    def test_platforms_never_mix(self):
        out = analyse([stats_row(saves=100), stats_row("TikTok", saves=1)])["platforms"]
        self.assertEqual(out["Instagram Reels"]["posts"], 1)
        self.assertEqual(out["TikTok"]["posts"], 1)
        self.assertEqual(out["Instagram Reels"]["platform_average"]["save_rate"], 0.1)

    def test_edited_caption_is_not_attributed_to_the_formula(self):
        rows = [stats_row(**{"Caption Formula": "Hot Take", "Caption Edited": True})]
        dims = analyse(rows)["platforms"]["Instagram Reels"]["dimensions"]
        self.assertEqual(dims["Caption Formula"], {})

    def test_late_first_pull_is_excluded_from_rankings(self):
        out = analyse([stats_row(**{"Stats Pulled At": "2026-09-20"})])
        self.assertEqual(out["platforms"], {})
        self.assertEqual(out["excluded"][0]["why"], "first pulled after day 10")

    def test_series_rollup_json_is_split(self):
        rows = [stats_row(Series='["Client Q&A", "Event"]')]
        dims = analyse(rows)["platforms"]["Instagram Reels"]["dimensions"]["Series"]
        self.assertEqual(set(dims), {"Client Q&A", "Event"})

    def test_save_cta_is_measured_on_save_rate_others_say_indirect(self):
        rows = [stats_row(**{"CTA Goal": "Save"}), stats_row(**{"CTA Goal": "Free Quote"})]
        cta = analyse(rows)["platforms"]["Instagram Reels"]["cta_goal"]
        self.assertTrue(cta["Save"]["direct_signal"])
        self.assertFalse(cta["Free Quote"]["direct_signal"])


class CliCase(unittest.TestCase):
    def test_bad_mode_input_exits_one(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--mode", "due", "--rows", "/dev/null"],
                           capture_output=True, text=True, cwd=REPO_ROOT)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
