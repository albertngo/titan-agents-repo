#!/usr/bin/env python3
"""Pins the v1 scoring formula (methods/content-engine.md) and the harvester's holds.

Stdlib unittest, no pytest:

    python3 -m unittest discover -s tests -v

The two worked examples Albert accepted on 2026-10-07 are asserted to one decimal, so a
weight change is a deliberate, tested edit rather than a drift.
"""

import copy
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import content_engine_lib as lib  # noqa: E402
import topic_harvest  # noqa: E402
import topic_rank  # noqa: E402

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=ZoneInfo("America/Toronto"))


def registry(**overrides):
    reg = lib.load_registry()
    reg = copy.deepcopy(reg)
    for k, v in overrides.items():
        reg[k] = v
    return reg


def backlog_rows():
    return [
        {"url": "https://www.notion.so/a1", "id": "TB-1", "title": "how much does vinyl plank flooring cost to install in mississauga",
         "cluster": "Installation Cost & Pricing", "volume": 320, "difficulty": 22, "status": "Backlog",
         "canonical_key": "how much does vinyl plank flooring cost to install in mississauga", "blog_post": []},
        {"url": "https://www.notion.so/a2", "id": "TB-2", "title": "is laminate flooring waterproof", "cluster": "Waterproof",
         "volume": 2400, "difficulty": 48, "status": "Backlog", "canonical_key": "is laminate flooring waterproof", "blog_post": []},
        {"url": "https://www.notion.so/a3", "id": "TB-3", "title": "best waterproof flooring for a bathroom", "cluster": "Waterproof",
         "status": "Briefed", "canonical_key": "best waterproof flooring for a bathroom"},
        {"url": "https://www.notion.so/a4", "id": "TB-4", "title": "waterproof laminate vs vinyl in a kitchen", "cluster": "Waterproof",
         "status": "Drafting", "canonical_key": "waterproof laminate vs vinyl in a kitchen"},
    ]


def post_rows():
    rows = [{"url": "https://www.notion.so/p1", "id": "BP-1", "title": "Is vinyl flooring waterproof for a basement bathroom?",
             "status": "Published", "topic_cluster": "Waterproof", "publish_date": "2026-09-20", "slug": "vinyl-basement-bathroom"}]
    # two older waterproof posts + seven others = 10 published, waterproof share 0.30
    for i, (c, n) in enumerate([("Waterproof", 2), ("Hardwood", 3), ("Maintenance & Care", 4)]):
        for j in range(n):
            rows.append({"url": f"https://www.notion.so/p{i}{j}", "id": f"BP-{10 + i * 10 + j}", "title": f"old {c} {j}",
                         "status": "Published", "topic_cluster": c, "publish_date": "2025-02-01", "slug": f"old-{i}-{j}"})
    return rows


class TestWeights(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(lib.load_registry()["scoring"]["weights"].values()), 1.0, places=9)


class TestWorkedExamples(unittest.TestCase):
    def setUp(self):
        self.reg = registry(cluster_performance={"as_of": "2026-10-07", "window_months": 12, "wins_attributed": 12,
                                                 "decision": "test", "values": {"waterproof": 0.75}})

    def test_example_a_local_pricing_question(self):
        ranked, _, _ = topic_rank.rank(self.reg, backlog_rows(), post_rows(), now=NOW)
        a = next(r for r in ranked if r["id"] == "TB-1")
        self.assertEqual(a["effective"], 95.9)
        self.assertEqual(a["inputs"]["cluster"], "installation-cost")
        self.assertEqual(a["inputs"]["L"], 1.0)
        self.assertEqual(a["inputs"]["I"], 1.0)
        self.assertEqual(a["inputs"]["diversity"], 1.15)
        self.assertEqual(a["rank"], 1)

    def test_example_b_busy_waterproof_cluster(self):
        ranked, _, _ = topic_rank.rank(self.reg, backlog_rows(), post_rows(), now=NOW)
        b = next(r for r in ranked if r["id"] == "TB-2")
        self.assertEqual(b["effective"], 43.5)
        self.assertEqual(b["inputs"]["open"], 3)
        self.assertEqual(b["inputs"]["r"], 0.36)
        self.assertEqual(b["inputs"]["C"], 0.654)
        self.assertEqual(b["inputs"]["diversity"], 0.7)

    def test_only_backlog_rows_are_scored(self):
        ranked, _, _ = topic_rank.rank(self.reg, backlog_rows(), post_rows(), now=NOW)
        self.assertEqual({r["id"] for r in ranked}, {"TB-1", "TB-2"})


class TestFormulaEdges(unittest.TestCase):
    def test_no_performance_means_prior_alone(self):
        reg = registry()
        ranked, _, _ = topic_rank.rank(reg, backlog_rows(), post_rows(), now=NOW)
        b = next(r for r in ranked if r["id"] == "TB-2")
        self.assertEqual(b["inputs"]["r"], 0.0)
        self.assertEqual(b["inputs"]["C"], 0.6)

    def test_ramp_caps_at_full_at_wins(self):
        reg = registry(cluster_performance={"wins_attributed": 200, "values": {"waterproof": 1.0}})
        ranked, _, _ = topic_rank.rank(reg, backlog_rows(), post_rows(), now=NOW)
        b = next(r for r in ranked if r["id"] == "TB-2")
        self.assertEqual(b["inputs"]["r"], 0.6)
        self.assertAlmostEqual(b["inputs"]["C"], 0.4 * 0.6 + 0.6 * 1.0, places=4)

    def test_unknown_volume_is_flagged_not_zero(self):
        rows = [{"url": "u", "id": "TB-9", "title": "does laminate scratch easily", "cluster": "Maintenance & Care", "status": "Backlog"}]
        ranked, _, _ = topic_rank.rank(registry(), rows, [], now=NOW)
        self.assertIn("volume_unknown", ranked[0]["flags"])
        self.assertEqual(ranked[0]["inputs"]["V"], 0.25)
        self.assertEqual(ranked[0]["inputs"]["D"], 0.5)

    def test_diversity_floor(self):
        rows = [{"url": f"u{i}", "id": f"TB-{i}", "title": f"hardwood question {i}", "cluster": "Hardwood", "status": "Briefed"} for i in range(9)]
        rows.append({"url": "ux", "id": "TB-x", "title": "is oak hardwood good", "cluster": "Hardwood", "status": "Backlog", "volume": 100})
        ranked, _, _ = topic_rank.rank(registry(), rows, [], now=NOW)
        x = ranked[0]
        self.assertEqual(x["inputs"]["open"], 9)
        self.assertEqual(x["inputs"]["diversity"], 0.5)

    def test_order_is_deterministic(self):
        reg = registry()
        a, _, _ = topic_rank.rank(reg, backlog_rows(), post_rows(), now=NOW)
        b, _, _ = topic_rank.rank(reg, list(reversed(backlog_rows())), post_rows(), now=NOW)
        self.assertEqual([r["id"] for r in a], [r["id"] for r in b])

    def test_unresolved_cluster_is_skipped(self):
        rows = [{"url": "u", "id": "TB-9", "title": "x", "cluster": "Not A Cluster", "status": "Backlog"}]
        ranked, skipped, _ = topic_rank.rank(registry(), rows, [], now=NOW)
        self.assertEqual(ranked, [])
        self.assertEqual(skipped[0]["reason"], "cluster_unresolved")


class TestHarvest(unittest.TestCase):
    def setUp(self):
        self.reg = registry()

    def run_seeds(self, questions, source="seed"):
        raws = [(source, [{"query": q} for q in questions])]
        return topic_harvest.harvest(self.reg, raws, backlog_rows(), post_rows())

    def test_cluster_rules_and_local_and_intent(self):
        c, h, f = self.run_seeds(["What does it cost to install laminate in Brampton?"])
        self.assertEqual(c[0]["cluster"], "installation-cost")
        self.assertTrue(c[0]["local"])
        self.assertEqual(c[0]["intent"], "Transaction")
        self.assertEqual(c[0]["status_on_create"], "Backlog")
        self.assertIn("volume_unknown", [x["reason"] for x in f])

    def test_exact_duplicate_is_held(self):
        c, h, _ = self.run_seeds(["Is laminate flooring waterproof?"])
        self.assertEqual(c, [])
        self.assertEqual(h[0]["reason"], "possible_duplicate")

    def test_near_duplicate_is_held(self):
        c, h, _ = self.run_seeds(["is laminate flooring really waterproof"])
        self.assertEqual(c, [])
        self.assertEqual(h[0]["reason"], "possible_duplicate")

    def test_overlap_with_existing_post_is_held(self):
        c, h, _ = self.run_seeds(["Is vinyl flooring waterproof for a basement bathroom?"])
        self.assertEqual(h[0]["reason"], "possible_overlap")

    def test_unresolved_cluster_is_held(self):
        c, h, _ = self.run_seeds(["What flooring colour goes with grey walls?"])
        self.assertEqual(h[0]["reason"], "cluster_unresolved")

    def test_transcript_seeds_land_as_proposed(self):
        c, _, _ = self.run_seeds(["Can I put vinyl plank over my existing tile?"], source="transcript")
        self.assertEqual(c[0]["status_on_create"], "Proposed")
        self.assertEqual(c[0]["cluster"], "vinyl-laminate")

    def test_duplicate_within_run_is_held_once(self):
        c, h, _ = self.run_seeds(["Does engineered hardwood scratch easily?", "does engineered hardwood scratch easily"])
        self.assertEqual(len(c), 1)
        self.assertEqual(len(h), 1)


class TestNoWritePath(unittest.TestCase):
    def test_scripts_carry_no_platform_write(self):
        for name in ("content_engine_lib.py", "topic_harvest.py", "topic_rank.py", "blog_plan.py", "blog_render.py", "blog_sweep.py", "blog_snapshot.py"):
            src = (REPO_ROOT / "scripts" / name).read_text()
            for verb in ("api.notion.com", "notion-create-pages", "notion-update-page", "push_files", "create_pull_request",
                         "api.github.com", "urllib.request", "requests.", '"POST"', '"PUT"', '"PATCH"', '"DELETE"'):
                self.assertNotIn(verb, src, f"{name} must stay read-only ({verb})")


if __name__ == "__main__":
    unittest.main()
