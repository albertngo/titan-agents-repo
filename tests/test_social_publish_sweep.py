#!/usr/bin/env python3
"""Tests for scripts/social_publish_sweep.py — weighted toward what it refuses to conclude.

Stdlib unittest, matching the repo's convention.

The sweep's only real input is an ABSENCE, and an absence has three possible causes
(published / deleted / outside the window) that look identical. Nearly every test below
pins a case where absence must NOT be read as "published", because that is the error
with no later detection: a row marked Posted for a post that never went out leaves no
evidence in either system.
"""

import json
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from social_publish_sweep import (  # noqa: E402
    WRITES, classify, is_date_only, parse_dt, scheduled_index, sweep,
)

SCRIPT = REPO_ROOT / "scripts" / "social_publish_sweep.py"
UUID = "-5728278742307617912"
NOW = datetime(2026, 12, 24, 18, 0, 0)          # six hours after the due time below
DUE = "2026-12-24T09:00:00"


def row(uuid=UUID, due=DUE, name="CC: Interview", surface="Facebook Page"):
    return {"url": "https://www.notion.so/abc", "Content Name": name,
            "Post To": surface, "Post Status": "Scheduled",
            "Metricool UUID": uuid, "Post Date": due}


def scheduled(uuid=UUID, due=DUE):
    return {"data": [{"id": 375680540, "uuid": uuid,
                      "publicationDate": {"dateTime": due, "timezone": "America/Toronto"}}]}


def verdict(r=None, posts=None, now=NOW, draft=False, window=None, grace=30, stuck=6):
    index = scheduled_index(posts if posts is not None else {"data": []})
    return classify(r or row(), index, now, grace, stuck, draft, window)[0]


class ParseCase(unittest.TestCase):
    """Notion and Metricool express the same moment differently. Every value below is
    a real wire format observed on the TC-86 run, not an invented one."""

    def test_notion_utc_and_metricool_local_resolve_to_the_same_moment(self):
        """THE bug this guards. Notion returns Post Date as an instant in UTC;
        Metricool returns a local wall clock. 8pm Toronto is '2026-09-16T00:00:00.000Z'
        to one and '2026-09-15T20:00:00' to the other. Stripping the Z instead of
        converting puts them four hours and one DAY apart — permanent false drift."""
        notion = parse_dt("2026-09-16T00:00:00.000Z")
        metricool = parse_dt("2026-09-15T20:00:00")
        self.assertEqual(notion, metricool)
        self.assertEqual(notion, datetime(2026, 9, 15, 20, 0))

    def test_dst_is_handled_not_assumed(self):
        """EDT in September (-04:00), EST in December (-05:00). A fixed offset would
        be right half the year."""
        self.assertEqual(parse_dt("2026-07-01T00:00:00.000Z"), datetime(2026, 6, 30, 20, 0))
        self.assertEqual(parse_dt("2026-12-24T14:00:00.000Z"), datetime(2026, 12, 24, 9, 0))

    def test_accepts_the_shapes_notion_and_metricool_emit(self):
        self.assertEqual(parse_dt("2026-12-24T09:00:00"), datetime(2026, 12, 24, 9, 0))
        self.assertEqual(parse_dt("2026-12-24"), datetime(2026, 12, 24, 0, 0))
        self.assertEqual(parse_dt("2026-12-24T09:00:00-05:00"), datetime(2026, 12, 24, 9, 0))
        self.assertEqual(parse_dt("2026-09-15T20:00:00.000"), datetime(2026, 9, 15, 20, 0))

    def test_blank_and_nonsense_are_none_not_an_exception(self):
        for value in (None, "", "not a date"):
            self.assertIsNone(parse_dt(value))

    def test_date_only_is_distinguished_from_midnight(self):
        """Both parse to 00:00, but they mean different things — see DateOnlyRowCase."""
        self.assertTrue(is_date_only("2026-09-15"))
        self.assertFalse(is_date_only("2026-09-15T00:00:00"))
        self.assertFalse(is_date_only(None))


class StillScheduledCase(unittest.TestCase):
    def test_present_and_agreeing_is_a_no_op(self):
        self.assertEqual(verdict(posts=scheduled(), now=datetime(2026, 12, 20, 9, 0)),
                         "still_scheduled")

    def test_a_no_op_verdict_writes_nothing(self):
        self.assertNotIn("still_scheduled", WRITES)
        self.assertNotIn("date_drift", WRITES)
        self.assertNotIn("outside_window", WRITES)

    def test_date_disagreement_is_reported_never_resolved(self):
        """Notion and Metricool disagreeing is exactly what --reschedule is for.
        Picking a winner here would silently move a real post."""
        v = verdict(r=row(due="2026-12-28T09:00:00"), posts=scheduled(),
                    now=datetime(2026, 12, 20, 9, 0))
        self.assertEqual(v, "date_drift")

    def test_still_pending_long_after_its_slot_reads_as_stuck(self):
        self.assertEqual(verdict(posts=scheduled(), now=NOW), "stuck_past_due")
        self.assertEqual(WRITES["stuck_past_due"], "Failed")

    def test_grace_period_protects_a_post_read_seconds_after_its_slot(self):
        """Metricool publishes on a queue, not on the second."""
        self.assertEqual(
            verdict(posts=scheduled(), now=datetime(2026, 12, 24, 9, 0, 30)),
            "still_scheduled")


class AbsenceCase(unittest.TestCase):
    """Absence is the ambiguous input. These pin every reading of it."""

    def test_absent_and_overdue_in_live_mode_is_published(self):
        self.assertEqual(verdict(), "published")
        self.assertEqual(WRITES["published"], "Posted")

    def test_absent_in_draft_mode_is_never_published(self):
        """A draft does not publish when its time comes. So a vanished draft was
        deleted by a person — marking it Posted would record a post that never went out."""
        self.assertEqual(verdict(draft=True), "vanished_in_draft_mode")
        self.assertEqual(WRITES["vanished_in_draft_mode"], "Manual Required")

    def test_absent_before_its_due_time_is_never_published(self):
        """Nothing publishes early, so this is a deletion or a planner move."""
        self.assertEqual(verdict(now=datetime(2026, 12, 24, 8, 0)), "vanished_before_due")
        self.assertEqual(WRITES["vanished_before_due"], "Manual Required")

    def test_absent_within_the_grace_period_is_not_yet_published(self):
        self.assertEqual(verdict(now=datetime(2026, 12, 24, 9, 20)), "vanished_before_due")

    def test_absent_but_outside_the_queried_window_concludes_nothing(self):
        """The post may be perfectly fine and simply not in the range we asked for."""
        v = verdict(window=(datetime(2027, 1, 1), datetime(2027, 1, 31)))
        self.assertEqual(v, "outside_window")

    def test_absent_with_no_post_date_concludes_nothing(self):
        self.assertEqual(verdict(r=row(due=None)), "vanished_no_date")
        self.assertNotIn("vanished_no_date", WRITES)

    def test_row_without_a_uuid_is_flagged_not_swept(self):
        self.assertEqual(verdict(r=row(uuid="")), "missing_uuid")
        self.assertEqual(WRITES["missing_uuid"], "Manual Required")


class DateOnlyRowCase(unittest.TestCase):
    """Notion's Post Date can be a DATE with no time — TC-86, the first real row
    through this pipeline, was exactly that. A date names a day, not midnight."""

    DATE_ONLY = "2026-09-15"
    LIVE = "2026-09-15T20:00:00"

    def test_a_date_only_row_scheduled_that_evening_is_not_drift(self):
        v = verdict(r=row(due=self.DATE_ONLY), posts=scheduled(due=self.LIVE),
                    now=datetime(2026, 9, 15, 9, 0))
        self.assertEqual(v, "still_scheduled")

    def test_a_date_only_row_on_a_different_day_is_still_drift(self):
        v = verdict(r=row(due=self.DATE_ONLY), posts=scheduled(due="2026-09-18T20:00:00"),
                    now=datetime(2026, 9, 15, 9, 0))
        self.assertEqual(v, "date_drift")

    def test_absence_mid_day_is_not_read_as_published(self):
        """The bug this guards: midnight + 30min grace would call a row due at 20:00
        'published' at 00:30 — twenty hours early, and unrecoverably wrong."""
        v = verdict(r=row(due=self.DATE_ONLY), now=datetime(2026, 9, 15, 0, 30))
        self.assertEqual(v, "vanished_before_due")

    def test_absence_after_the_day_is_out_is_published(self):
        v = verdict(r=row(due=self.DATE_ONLY), now=datetime(2026, 9, 16, 1, 0))
        self.assertEqual(v, "published")

    def test_a_timed_row_still_compares_to_the_minute(self):
        v = verdict(r=row(due="2026-09-15T20:00:00"), posts=scheduled(due="2026-09-15T18:00:00"),
                    now=datetime(2026, 9, 15, 9, 0))
        self.assertEqual(v, "date_drift")


class DriftResolutionCase(unittest.TestCase):
    """Notion owns Post Date, so ordinary drift is mechanically resolvable — but the
    sweep proposes a reschedule, it never writes one. The proposal goes through the
    same plan/approval/actions-log gate as every other platform write."""

    NOW = datetime(2026, 9, 14, 12, 0)

    def classify3(self, notion_due, live_due, now=None, imminent=1):
        index = scheduled_index(scheduled(due=live_due))
        return classify(row(due=notion_due), index, now or self.NOW, 30, 6, False, None, imminent)

    def test_ordinary_drift_proposes_a_reschedule_to_notions_date(self):
        v, _, extra = self.classify3("2026-09-16T20:00:00", "2026-09-15T20:00:00")
        self.assertEqual(v, "date_drift")
        a = extra["proposed_action"]
        self.assertEqual(a["type"], "social_reschedule_post")
        self.assertEqual(a["scheduled_at"]["dateTime"], "2026-09-16T20:00:00")
        self.assertEqual(a["from"]["dateTime"], "2026-09-15T20:00:00")
        self.assertEqual(a["metricool_uuid"], UUID)

    def test_a_date_only_row_proposes_end_of_that_day(self):
        """A date names a day; the only unambiguous instant in it is its end."""
        _, _, extra = self.classify3("2026-09-16", "2026-09-15T20:00:00")
        self.assertEqual(extra["proposed_action"]["scheduled_at"]["dateTime"],
                         "2026-09-16T23:59:59")

    def test_a_past_notion_date_is_never_auto_resolved(self):
        """A stale row is not an instruction to move a post backwards."""
        v, detail, extra = self.classify3("2026-09-01T20:00:00", "2026-09-15T20:00:00")
        self.assertEqual(v, "date_drift")
        self.assertEqual(extra, {})
        self.assertIn("in the past", detail)

    def test_an_imminent_live_post_is_never_auto_resolved(self):
        """The post can publish while the update is in flight."""
        v, detail, extra = self.classify3("2026-09-20T20:00:00", "2026-09-14T12:30:00")
        self.assertEqual(extra, {})
        self.assertIn("in flight", detail)

    def test_moving_a_post_to_fire_imminently_is_never_auto_resolved(self):
        v, detail, extra = self.classify3("2026-09-14T12:30:00", "2026-09-20T20:00:00")
        self.assertEqual(extra, {})
        self.assertIn("surprise", detail)

    def test_the_sweep_still_writes_nothing_for_drift(self):
        """A proposal is not a write. date_drift carries no set_post_status."""
        rows = [row(due="2026-09-16T20:00:00")]
        report = sweep(rows, scheduled(due="2026-09-15T20:00:00"), self.NOW, 30, 6, False)
        entry = report["results"][0]
        self.assertNotIn("set_post_status", entry)
        self.assertIn("proposed_action", entry)


class SweepCase(unittest.TestCase):
    def test_counts_and_write_targets_are_reported_per_row(self):
        rows = [row(), row(uuid="other-uuid", name="CC: Second")]
        report = sweep(rows, scheduled(), NOW, 30, 6, draft_mode=False)
        self.assertEqual(report["rows_examined"], 2)
        self.assertEqual(report["counts"]["stuck_past_due"], 1)
        self.assertEqual(report["counts"]["published"], 1)
        by_uuid = {r["metricool_uuid"]: r for r in report["results"]}
        self.assertEqual(by_uuid["other-uuid"]["set_post_status"], "Posted")

    def test_draft_mode_marks_nothing_posted(self):
        """The single most important property while write_mode is draft."""
        rows = [row(), row(uuid="a"), row(uuid="b")]
        report = sweep(rows, {"data": []}, NOW, 30, 6, draft_mode=True)
        self.assertEqual(report["write_mode"], "draft")
        self.assertEqual([r["set_post_status"] for r in report["results"]],
                         ["Manual Required"] * 3)

    def test_orphan_posts_are_surfaced_but_never_actioned(self):
        """A Metricool post no row claims was made in the planner by hand. This
        pipeline does not own posts it did not create."""
        report = sweep([row(uuid="mine")], scheduled(uuid="theirs"), NOW, 30, 6, False)
        self.assertEqual(report["orphans"], ["theirs"])

    def test_empty_sweep_is_healthy_not_an_error(self):
        report = sweep([], {"data": []}, NOW, 30, 6, False)
        self.assertEqual(report["rows_examined"], 0)
        self.assertEqual(report["counts"], {})


class CliCase(unittest.TestCase):
    def run_cli(self, rows, posts, *args):
        tmp = Path(__file__).resolve().parent / "__sweep_tmp__"
        tmp.mkdir(exist_ok=True)
        try:
            (tmp / "rows.json").write_text(json.dumps(rows))
            (tmp / "posts.json").write_text(json.dumps(posts))
            return subprocess.run(
                [sys.executable, str(SCRIPT),
                 "--rows", str(tmp / "rows.json"), "--posts", str(tmp / "posts.json"),
                 "--now", NOW.strftime("%Y-%m-%dT%H:%M:%S"), *args],
                capture_output=True, text=True)
        finally:
            for f in tmp.iterdir():
                f.unlink()
            tmp.rmdir()

    def test_reports_and_exits_zero(self):
        r = self.run_cli([row()], {"data": []}, "--write-mode", "live")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["results"][0]["verdict"], "published")

    def test_accepts_the_notion_query_envelope(self):
        r = self.run_cli({"results": [row()]}, {"data": []}, "--write-mode", "live")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["rows_examined"], 1)

    def test_write_mode_is_required_never_defaulted(self):
        """Guessing it wrong in the unsafe direction marks drafts as Posted."""
        r = self.run_cli([row()], {"data": []})
        self.assertNotEqual(r.returncode, 0)

    def test_bad_input_exits_one(self):
        r = self.run_cli("not a list", {"data": []}, "--write-mode", "live")
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
