#!/usr/bin/env python3
"""Structural tests for the content engine registry (Phase 0).

Stdlib unittest, no pytest — matching the repo's convention.

    python3 -m unittest discover -s tests -v

What is pinned and why:

  * the 8 clusters, their slugs (== utm_campaign values) and their Notion labels — the
    option strings on three Notion selects were created from this list on 2026-10-07 and
    must stay byte-identical to it;
  * write_mode == plan_only until a dated decision flips it (same rule as style-tags);
  * scoring weights sum to 1.0 and every prior is in [0, 1];
  * status vocabularies and the person-only subsets;
  * every blog-actions-agent action type is in contracts/actions-log-schema.md and in the
    agent's own table;
  * every command the registry's commands list names exists and is registered under the
    Marketing department, and the agent is in its actions list;
  * every Notion id the engine depends on is a real-looking id, not a TODO.
"""

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "platform-settings" / "content-engine.json"
DEPARTMENTS = REPO_ROOT / "platform-settings" / "departments.json"
AGENT = REPO_ROOT / ".claude" / "agents" / "blog-actions-agent.md"
ACTIONS_LOG_SCHEMA = REPO_ROOT / "contracts" / "actions-log-schema.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
METHOD = REPO_ROOT / "methods" / "content-engine.md"
FACTS = REPO_ROOT / "platform-settings" / "titan-facts.md"

COMMANDS = [
    "topic-harvest", "topic-rank", "topic-track",
    "blog-brief", "blog-draft", "blog-publish", "blog-sweep", "blog-import",
    "content-attribution",
]
AGENT_TYPES = [
    "notion_create_topic", "notion_update_topic_score", "notion_retire_topic",
    "notion_create_blog_post", "notion_update_blog_post", "notion_append_blog_body",
    "notion_create_tracking_row", "notion_update_content_idea_cluster",
    "website_open_post_pr", "website_update_post_pr",
]
CLUSTERS = {
    "basement-flooring": "Basement Flooring",
    "waterproof": "Waterproof",
    "vinyl-laminate": "Vinyl Plank & Laminate",
    "hardwood": "Hardwood",
    "installation-cost": "Installation Cost & Pricing",
    "installation-process": "Installation Process",
    "comparison": "Comparison",
    "maintenance": "Maintenance & Care",
}
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def load(path):
    return json.loads(path.read_text())


def clusters(reg):
    """The cluster entries, minus the registry's own `_comment` keys."""
    return {k: v for k, v in reg["clusters"].items() if not k.startswith("_")}


class TestClusters(unittest.TestCase):
    def setUp(self):
        self.reg = load(REGISTRY)

    def test_exactly_the_eight_clusters(self):
        self.assertEqual(list(clusters(self.reg).keys()), list(CLUSTERS.keys()))
        for slug, label in CLUSTERS.items():
            self.assertEqual(clusters(self.reg)[slug]["label"], label)

    def test_slugs_are_utm_safe(self):
        for slug in clusters(self.reg):
            self.assertRegex(slug, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

    def test_priors_in_unit_interval(self):
        for slug, c in clusters(self.reg).items():
            for key in ("commercial_prior", "local_prior"):
                self.assertGreaterEqual(c[key], 0.0, f"{slug}.{key}")
                self.assertLessEqual(c[key], 1.0, f"{slug}.{key}")

    def test_cluster_rules_name_real_clusters(self):
        for rule in self.reg["cluster_rules"]["rules"]:
            self.assertIn(rule["cluster"], self.reg["clusters"])
            self.assertTrue(rule["any"])

    def test_campaign_aliases_resolve(self):
        for alias, slug in self.reg["campaign_aliases"].items():
            if alias.startswith("_"):
                continue
            self.assertIn(slug, self.reg["clusters"], alias)


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.s = load(REGISTRY)["scoring"]

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(self.s["weights"].values()), 1.0, places=9)
        self.assertEqual(set(self.s["weights"]), {"volume", "difficulty", "local", "cluster", "intent"})

    def test_ramp_and_diversity_are_sane(self):
        self.assertLess(self.s["ramp"]["max"], 1.0)
        self.assertGreater(self.s["ramp"]["full_at_wins"], 0)
        d = self.s["diversity"]
        self.assertLessEqual(d["floor"], 1.0)
        self.assertGreater(d["penalty_per_open"], 0)
        self.assertGreaterEqual(d["coverage_bonus"], 0)

    def test_unknowns_are_not_zero(self):
        self.assertGreater(self.s["volume_unknown"], 0)
        self.assertGreater(self.s["difficulty_unknown"], 0)


class TestWriteModeAndPolicy(unittest.TestCase):
    def setUp(self):
        self.reg = load(REGISTRY)

    def test_write_mode_is_plan_only_until_a_dated_decision(self):
        wm = self.reg["write_mode"]
        self.assertEqual(wm["mode"], "plan_only")
        self.assertIsNone(wm["_flipped"])
        self.assertEqual(wm["_values"], ["plan_only", "write"])

    def test_person_only_ops_are_never_auto(self):
        p = self.reg["policy"]
        self.assertFalse(set(p["auto_approve_ops"]) & set(p["person_only_ops"]))
        for must in ("status:Approved", "pr_merge", "cluster_performance edit", "write_mode flip"):
            self.assertIn(must, p["person_only_ops"])

    def test_cluster_performance_empty_at_phase_0(self):
        cp = self.reg["cluster_performance"]
        self.assertIsNone(cp["as_of"])
        self.assertEqual(cp["wins_attributed"], 0)
        self.assertEqual(cp["values"], {})

    def test_budget_caps(self):
        b = self.reg["openseo"]["budget"]
        self.assertEqual(b["usd_per_harvest"], 1.0)
        self.assertEqual(b["usd_per_month"], 20.0)


class TestNotionSources(unittest.TestCase):
    def setUp(self):
        self.src = load(REGISTRY)["sources"]

    def test_data_sources_are_real_ids(self):
        for key in ("topic_backlog", "blog_posts", "blog_post_tracking", "titan_content_ideas", "titan_projects"):
            ds = self.src[key]["data_source"]
            self.assertTrue(ds.startswith("collection://"), key)
            self.assertRegex(ds[len("collection://"):], UUID, key)
        self.assertRegex(self.src["topic_backlog"]["database_id"], UUID)
        self.assertRegex(self.src["blog_posts"]["database_id"], UUID)

    def test_backlog_status_vocab(self):
        tb = self.src["topic_backlog"]
        self.assertEqual(tb["status_values"], ["Proposed", "Backlog", "Briefed", "Drafting", "Published", "Retired"])
        self.assertEqual(tb["seed_status"]["transcript"], "Proposed")
        for r in tb["person_only_retired_reasons"]:
            self.assertIn(r, tb["retired_reasons"])

    def test_blog_posts_status_vocab_and_gate(self):
        bp = self.src["blog_posts"]
        self.assertEqual(bp["status_values"], ["Idea", "Briefed", "Drafting", "Review", "Approved", "Published"])
        self.assertEqual(bp["person_only_status"], ["Approved"])
        self.assertNotIn("Approved", bp["run_may_set_status"])
        self.assertEqual(bp["status_live_alias"], {"Posted": "Published"})

    def test_blog_posts_never_writes_the_legacy_fields(self):
        bp = self.src["blog_posts"]
        for prop in ("Assignee", "Payout Date", "Neuron URL", "Related Video", "Linked", "Spokes"):
            self.assertNotIn(prop, bp["write_properties"], prop)
            self.assertIn(prop, bp["_never_write"], prop)

    def test_cluster_labels_match_the_select_options(self):
        reg = load(REGISTRY)
        labels = [c["label"] for c in clusters(reg).values()]
        self.assertEqual(labels, list(CLUSTERS.values()))

    def test_content_ideas_write_is_cluster_only(self):
        self.assertEqual(self.src["titan_content_ideas"]["write_properties"], ["Topic Cluster"])

    def test_titan_projects_campaign(self):
        tp = self.src["titan_projects"]
        self.assertEqual(tp["campaign_property"], "Campaign")
        self.assertEqual(tp["make_scenario"]["scenario_id"], 3710214)


class TestWiring(unittest.TestCase):
    def test_every_command_exists(self):
        for name in COMMANDS:
            self.assertTrue((REPO_ROOT / ".claude" / "commands" / f"{name}.md").exists(), name)

    def test_marketing_owns_the_commands_and_the_agent(self):
        marketing = load(DEPARTMENTS)["departments"]["marketing"]
        for name in COMMANDS:
            self.assertIn(name, marketing["owns"]["commands"], name)
        self.assertIn("blog-actions-agent", marketing["specialists"]["actions"])
        self.assertNotIn("blog-actions-agent", marketing["specialists"]["readonly"])
        for kw in ("blog", "seo", "aeo", "topic", "cluster", "pillar"):
            self.assertIn(kw, marketing["route_keywords"], kw)

    def test_agent_types_in_log_vocabulary_and_agent_table(self):
        schema = ACTIONS_LOG_SCHEMA.read_text()
        agent = AGENT.read_text()
        for t in AGENT_TYPES:
            self.assertIn(f"`{t}`", schema, t)
            self.assertIn(f"`{t}`", agent, t)
        self.assertIn("| `blog-actions-agent` |", schema)

    def test_agent_has_no_merge_or_delete_tool(self):
        head = AGENT.read_text().split("---")[1]
        self.assertNotIn("merge", head)
        self.assertNotIn("delete", head)
        self.assertIn("mcp__github__create_pull_request", head)
        self.assertIn("mcp__Notion__notion-update-page", head)

    def test_agent_prose_holds_the_gates(self):
        text = AGENT.read_text()
        for must in ("No approval file means nothing is approved", "Never writes `Approved`", "You never merge"):
            self.assertIn(must, text, must)

    def test_claude_md_and_method_name_the_engine(self):
        claude = CLAUDE_MD.read_text()
        self.assertIn("AEO content engine", claude)
        self.assertIn("platform-settings/content-engine.json", claude)
        self.assertIn("grilling", claude)
        self.assertTrue(METHOD.exists())
        self.assertTrue(FACTS.exists())

    def test_unbuilt_commands_still_stop(self):
        # Phase 1 built the six core commands; these three arrive in later phases.
        for name in ("blog-import", "content-attribution", "topic-track"):
            text = (REPO_ROOT / ".claude" / "commands" / f"{name}.md").read_text()
            self.assertIn("Phase 0 stub", text, name)

    def test_built_commands_read_write_mode_and_name_their_script(self):
        for name, script in (("topic-harvest", "topic_harvest.py"), ("topic-rank", "topic_rank.py"), ("blog-brief", "blog_plan.py"),
                             ("blog-draft", "blog_plan.py"), ("blog-publish", "blog_render.py"), ("blog-sweep", "blog_sweep.py")):
            text = (REPO_ROOT / ".claude" / "commands" / f"{name}.md").read_text()
            self.assertNotIn("Phase 0 stub", text, name)
            self.assertIn("write_mode", text, name)
            self.assertIn(script, text, name)


if __name__ == "__main__":
    unittest.main()
