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
    WRITES, classify, parse_dt, scheduled_index, sweep,
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
    def test_accepts_the_shapes_notion_and_metricool_emit(self):
        self.assertEqual(parse_dt("2026-12-24T09:00:00"), datetime(2026, 12, 24, 9, 0))
        self.assertEqual(parse_dt("2026-12-24"), datetime(2026, 12, 24, 0, 0))
        self.assertEqual(parse_dt("2026-12-24T09:00:00-05:00"), datetime(2026, 12, 24, 9, 0))
        self.assertEqual(parse_dt("2026-12-24T09:00:00Z"), datetime(2026, 12, 24, 9, 0))

    def test_blank_and_nonsense_are_none_not_an_exception(self):
        for value in (None, "", "not a date"):
            self.assertIsNone(parse_dt(value))


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
