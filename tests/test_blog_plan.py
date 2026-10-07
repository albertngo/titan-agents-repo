#!/usr/bin/env python3
"""Pins the planner (scripts/blog_plan.py) and the post renderer (scripts/blog_render.py).

Stdlib unittest, no pytest:

    python3 -m unittest discover -s tests -v

The rules that matter are the silent ones: an approval file under plan_only, a PR planned
for a row nobody approved, a Status write of Approved, a body appended after a person
took the draft over. Each is a test here, not a sentence in a prompt.
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import blog_plan  # noqa: E402
import blog_render  # noqa: E402
import content_engine_lib as lib  # noqa: E402

PLAN = REPO_ROOT / "scripts" / "blog_plan.py"


def registry(mode="plan_only"):
    reg = copy.deepcopy(lib.load_registry())
    reg["write_mode"]["mode"] = mode
    return reg


def words(n, seed="word"):
    return " ".join(f"{seed}{i}" for i in range(n))


def sample_body(snippet_words=50, sections=3, section_words=240, faq=3, h1="Is laminate flooring waterproof?"):
    out = [f"# {h1}", "", words(snippet_words, "snip"), ""]
    for i in range(sections):
        out += [f"## What about section {i}?", "", words(section_words, f"s{i}w"), ""]
    out += ["## FAQ", ""]
    for i in range(faq):
        out += [f"### Question number {i}?", "", f"Answer number {i} in one sentence.", ""]
    out += ["## Sources", "", "- Titan facts file", ""]
    return "\n".join(out)


def sample_row(**over):
    row = {"bp_id": "BP-7", "page_id": "2f3596a4-0000-0000-0000-000000000007", "title": "Is laminate flooring waterproof?",
           "slug": "is-laminate-flooring-waterproof", "keyword": "laminate flooring waterproof", "intent": "Commericial",
           "cluster": "Waterproof", "material": ["Laminate"], "content_type": "Supporting Content", "pillar_slug": None,
           "siblings": [], "video_url": None, "publish_date": "2026-10-14", "updated_date": None, "legacy": None}
    row.update(over)
    return row


class TestRender(unittest.TestCase):
    def setUp(self):
        self.reg = registry()

    def test_parse_body_extracts_h1_snippet_h2s_faq(self):
        p = blog_render.parse_body(sample_body())
        self.assertEqual(p["h1"], "Is laminate flooring waterproof?")
        self.assertEqual(p["h1_count"], 1)
        self.assertEqual(lib.word_count(p["snippet"]), 50)
        self.assertEqual(len(p["h2s"]), 3)
        self.assertEqual(len(p["faq"]), 3)
        self.assertNotIn("## FAQ", p["body"])
        self.assertNotIn("Sources", p["body"])

    def test_render_then_check_is_clean_apart_from_pillar_flag(self):
        fm, text = blog_render.render(self.reg, sample_row(), sample_body())
        self.assertEqual(fm["schema"], "blog-mdx-1")
        self.assertEqual(fm["intent"], "Commercial")  # Notion's misspelling mapped back
        self.assertEqual(fm["cluster"], "waterproof")
        self.assertEqual(len(fm["faq"]), 3)
        problems, fm2 = blog_render.check(self.reg, text, file_name="is-laminate-flooring-waterproof.mdx")
        self.assertEqual([p[0] for p in problems], ["pillar_not_required_yet"])
        self.assertEqual(fm2["slug"], "is-laminate-flooring-waterproof")

    def test_frontmatter_is_one_json_value_per_line(self):
        _, text = blog_render.render(self.reg, sample_row(), sample_body())
        front = text.split("---\n")[1]
        for ln in front.splitlines():
            k, _, v = ln.partition(":")
            json.loads(v.strip())
        self.assertEqual([ln.split(":")[0] for ln in front.splitlines()], blog_render.KEYS)

    def test_check_refuses_bad_slug_snippet_faq(self):
        fm, text = blog_render.render(self.reg, sample_row(slug="Bad Slug"), sample_body(snippet_words=30, faq=2))
        problems, _ = blog_render.check(self.reg, text)
        reasons = {p[0] for p in problems}
        self.assertIn("slug_invalid", reasons)
        self.assertIn("snippet_length", reasons)
        self.assertIn("faq_count", reasons)

    def test_reserved_slug_is_refused(self):
        _, text = blog_render.render(self.reg, sample_row(slug="blog"), sample_body())
        problems, _ = blog_render.check(self.reg, text)
        self.assertIn("slug_reserved", {p[0] for p in problems})

    def test_pillar_page_must_have_null_pillar(self):
        _, text = blog_render.render(self.reg, sample_row(content_type="Pillar Page", pillar_slug="x"), sample_body())
        problems, _ = blog_render.check(self.reg, text)
        self.assertIn("pillar_missing", {p[0] for p in problems})

    def test_pillar_required_flips_flag_to_hold(self):
        reg = registry()
        reg["aeo_structure"]["pillar_rules"]["required"] = True
        _, text = blog_render.render(reg, sample_row(), sample_body())
        problems, _ = blog_render.check(reg, text)
        self.assertIn("pillar_missing", {p[0] for p in problems})

    def test_non_youtube_video_is_refused(self):
        _, text = blog_render.render(self.reg, sample_row(video_url="https://www.tiktok.com/@x/video/1"), sample_body())
        problems, _ = blog_render.check(self.reg, text)
        self.assertIn("stale_status", {p[0] for p in problems})


class TestDraftStage(unittest.TestCase):
    def setUp(self):
        self.reg = registry()

    def test_draft_problems_catch_every_structural_rule(self):
        ok, _ = blog_plan.draft_problems(self.reg, sample_body())
        self.assertEqual(ok, [])
        bad, _ = blog_plan.draft_problems(self.reg, sample_body(snippet_words=70, faq=6, section_words=50)
                                          .replace("## What about section 1?", "## Section one"))
        reasons = {p[0] for p in bad}
        self.assertEqual(reasons, {"snippet_length", "faq_count", "h2_not_question", "body_too_short"})

    def test_two_h1s_are_refused(self):
        bad, _ = blog_plan.draft_problems(self.reg, sample_body() + "\n# Another title\n")
        self.assertIn("h2_not_question", {p[0] for p in bad})


class TestPlannerCli(unittest.TestCase):
    """Runs the script the way a command does, in a temp dir with a plan_only registry."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reg_path = self.tmp / "reg.json"
        self.reg_path.write_text(json.dumps(registry()))
        self.posts = self.tmp / "posts.json"
        self.posts.write_text(json.dumps({"rows": [
            {"url": "https://www.notion.so/p7", "id": "BP-7", "title": "Is laminate flooring waterproof?", "status": "Briefed",
             "slug": "is-laminate-flooring-waterproof", "topic_cluster": "Waterproof", "pillar": []},
            {"url": "https://www.notion.so/p8", "id": "BP-8", "title": "Taken over", "status": "Review", "slug": "taken-over"},
            {"url": "https://www.notion.so/p9", "id": "BP-9", "title": "Approved one", "status": "Approved", "slug": "approved-one"},
        ]}))
        self.backlog = self.tmp / "backlog.json"
        self.backlog.write_text(json.dumps({"rows": [
            {"url": "https://www.notion.so/a2", "id": "TB-2", "title": "is laminate flooring waterproof", "cluster": "Waterproof",
             "status": "Backlog", "canonical_key": "is laminate flooring waterproof", "blog_post": []},
            {"url": "https://www.notion.so/a3", "id": "TB-3", "title": "briefed already", "cluster": "Waterproof",
             "status": "Briefed", "canonical_key": "briefed already", "blog_post": ["https://www.notion.so/p7"]},
        ]}))
        self.body = self.tmp / "blog-body-BP-7.md"
        self.body.write_text(sample_body())

    def run_plan(self, *args, expect=0):
        out = self.tmp / "plan.json"
        cmd = [sys.executable, str(PLAN), "--registry", str(self.reg_path), "--out", str(out), "--date", "2026-10-07", *args]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        self.assertEqual(res.returncode, expect, res.stdout + res.stderr)
        return json.loads(out.read_text()) if out.exists() else None, res

    def test_draft_plans_append_and_review_never_approved(self):
        plan, _ = self.run_plan("--stage", "draft", "--body", str(self.body), "--posts", str(self.posts), "--bp", "BP-7")
        self.assertEqual(plan["contract_version"], "blog-plan-1")
        self.assertEqual([a["op"] for a in plan["actions"]], ["append_blog_body", "update_blog_post"])
        self.assertEqual(plan["actions"][1]["fields"]["Status"], "Review")
        self.assertEqual(plan["actions"][1]["expect"], {"Status": "Briefed"})
        for a in plan["actions"]:
            self.assertNotEqual(a["fields"].get("Status"), "Approved")
            self.assertTrue(a["id"].startswith("blg-") and len(a["id"]) == 16)
        self.assertEqual(plan["write_mode"], "plan_only")
        self.assertIn("pillar_not_required_yet", plan["actions"][1]["flags"])

    def test_ids_are_stable_and_content_sensitive(self):
        p1, _ = self.run_plan("--stage", "draft", "--body", str(self.body), "--posts", str(self.posts), "--bp", "BP-7")
        p2, _ = self.run_plan("--stage", "draft", "--body", str(self.body), "--posts", str(self.posts), "--bp", "BP-7")
        self.assertEqual([a["id"] for a in p1["actions"]], [a["id"] for a in p2["actions"]])
        self.body.write_text(sample_body(h1="Is laminate flooring waterproof in Ontario?"))
        p3, _ = self.run_plan("--stage", "draft", "--body", str(self.body), "--posts", str(self.posts), "--bp", "BP-7")
        self.assertNotEqual(p1["actions"][0]["id"], p3["actions"][0]["id"])

    def test_body_after_review_is_a_persons(self):
        plan, _ = self.run_plan("--stage", "draft", "--body", str(self.body), "--posts", str(self.posts), "--bp", "BP-8", expect=3)
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["held"][0]["reason"], "body_is_a_persons")
        self.assertNotIn("id", plan["held"][0])

    def test_approval_refused_under_plan_only(self):
        _, res = self.run_plan("--stage", "draft", "--body", str(self.body), "--posts", str(self.posts), "--bp", "BP-7",
                               "--write-approval", expect=4)
        self.assertIn("plan_only", res.stderr)
        self.assertFalse(list(self.tmp.glob("*approval*")))

    def test_approval_written_under_write_and_skips_person_only(self):
        reg = registry("write")
        self.reg_path.write_text(json.dumps(reg))
        plan, res = self.run_plan("--stage", "draft", "--body", str(self.body), "--posts", str(self.posts), "--bp", "BP-7",
                                  "--write-approval", "--approval-out", str(self.tmp / "approval.json"))
        approval = json.loads((self.tmp / "approval.json").read_text())
        self.assertEqual(approval["contract_version"], "blog-approval-1")
        self.assertEqual({d["id"] for d in approval["decisions"]}, {a["id"] for a in plan["actions"]})
        self.assertTrue(approval["approved_by"].startswith("policy:"))

    def test_publish_refuses_unless_approved(self):
        reg = registry()
        _, text = blog_render.render(reg, sample_row(bp_id="BP-7"), sample_body())
        mdx = self.tmp / "is-laminate-flooring-waterproof.mdx"
        mdx.write_text(text)
        plan, _ = self.run_plan("--stage", "publish", "--mdx", str(mdx), "--posts", str(self.posts), "--bp", "BP-7", expect=3)
        self.assertEqual(plan["held"][0]["reason"], "not_approved")
        self.assertEqual(plan["actions"], [])

    def test_publish_plans_pr_for_approved_row(self):
        reg = registry()
        _, text = blog_render.render(reg, sample_row(bp_id="BP-9", slug="approved-one", h1=None), sample_body(h1="Approved one?"))
        mdx = self.tmp / "approved-one.mdx"
        mdx.write_text(text)
        plan, _ = self.run_plan("--stage", "publish", "--mdx", str(mdx), "--posts", str(self.posts), "--bp", "BP-9")
        a = plan["actions"][0]
        self.assertEqual(a["type"], "website_open_post_pr")
        self.assertEqual(a["target"]["branch"], "blog/approved-one")
        self.assertEqual(a["files"][0]["path"], "content/blog/approved-one.mdx")
        self.assertEqual(a["expect"]["Status"], "Approved")
        self.assertEqual(a["then"][0]["fields"], {"PR URL": "<from result>"})

    def test_brief_plans_create_and_refuses_claimed_topic(self):
        brief = {"contract_version": "blog-brief-1", "topic": {"url": "https://www.notion.so/a2", "id": "TB-2", "title": "is laminate flooring waterproof"},
                 "keyword": "laminate flooring waterproof", "core_question": "Is laminate flooring waterproof?", "cluster": "waterproof",
                 "material": ["Laminate"], "intent": "Commercial", "slug": "laminate-waterproof-guide", "content_type": "Supporting Content",
                 "pillar_slug": None, "angle": "friendly expert", "h2s": ["What does water-resistant mean?", "Which rooms are safe?", "How does it compare to vinyl?"],
                 "facts_used": [], "facts_missing": ["pricing.laminate.mid"], "snippet_draft": words(45)}
        bf = self.tmp / "blog-brief-TB-2.json"
        bf.write_text(json.dumps(brief))
        plan, _ = self.run_plan("--stage", "brief", "--brief", str(bf), "--backlog", str(self.backlog), "--posts", str(self.posts))
        a = plan["actions"][0]
        self.assertEqual(a["op"], "create_blog_post")
        self.assertEqual(a["fields"]["Status"], "Briefed")
        self.assertEqual(a["fields"]["Search Intent"], "Commericial")
        self.assertEqual(a["then"][0]["fields"], {"Status": "Briefed"})
        self.assertIn("titan_facts_missing", a["flags"])
        self.assertTrue((self.tmp / "blog-brief-TB-2.md").exists())
        brief["topic"] = {"url": "https://www.notion.so/a3", "id": "TB-3", "title": "briefed already"}
        bf.write_text(json.dumps(brief))
        plan, _ = self.run_plan("--stage", "brief", "--brief", str(bf), "--backlog", str(self.backlog), "--posts", str(self.posts), expect=3)
        self.assertEqual({h["reason"] for h in plan["held"]} & {"stale_status", "possible_duplicate"}, {"stale_status", "possible_duplicate"})

    def test_harvest_respects_run_cap_and_batches(self):
        reg = registry()
        reg["policy"]["max_new_topics_per_run"] = 3
        reg["policy"]["max_batch"] = 2
        self.reg_path.write_text(json.dumps(reg))
        cands = {"contract_version": "topic-candidates-1", "candidates": [
            {"title": f"q{i}", "canonical_key": f"q{i}", "cluster": "hardwood", "cluster_label": "Hardwood", "material": [], "source": "seed",
             "volume": None, "difficulty": None, "cpc": None, "intent": "Informational", "local": False, "status_on_create": "Backlog"} for i in range(5)],
            "held": [{"title": "dup", "reason": "possible_duplicate", "detail": "x"}], "flagged": [{"title": "q0", "reason": "volume_unknown"}]}
        cf = self.tmp / "topic-candidates-seed.json"
        cf.write_text(json.dumps(cands))
        plan, _ = self.run_plan("--stage", "harvest", "--candidates", str(cf))
        self.assertEqual(len(plan["actions"]), 3)
        self.assertEqual([a["batch"] for a in plan["actions"]], [1, 1, 2])
        self.assertEqual(plan["summary"]["held_by_reason"], {"possible_duplicate": 1, "run_cap": 2})
        self.assertEqual(plan["actions"][0]["fields"]["Status"], "Backlog")
        self.assertIn("volume_unknown", plan["actions"][0]["flags"])

    def test_rank_plans_scores_with_backlog_cas(self):
        scores = {"contract_version": "topic-scores-1", "ranked": [
            {"url": "https://www.notion.so/a2", "id": "TB-2", "title": "is laminate flooring waterproof", "origin": "backlog", "effective": 43.5,
             "inputs": {"V": 0.9}, "flags": []},
            {"url": "https://www.notion.so/a3", "id": "TB-3", "title": "briefed already", "origin": "backlog", "effective": 10.0, "inputs": {}, "flags": []},
            {"url": None, "id": None, "title": "cand", "origin": "candidate", "effective": 50.0, "inputs": {}, "flags": []}]}
        sf = self.tmp / "topic-scores.json"
        sf.write_text(json.dumps(scores))
        plan, _ = self.run_plan("--stage", "rank", "--scores", str(sf), "--backlog", str(self.backlog))
        self.assertEqual(len(plan["actions"]), 1)
        self.assertEqual(plan["actions"][0]["expect"], {"Status": "Backlog"})
        self.assertEqual(plan["actions"][0]["fields"]["Score"], 43.5)
        self.assertEqual(plan["held"][0]["reason"], "stale_status")

    def test_sweep_stage_carries_proposals_through_the_same_gate(self):
        sweep = {"contract_version": "blog-sweep-1", "proposals": [
            {"id": "blg-000000000001", "target_system": "notion", "type": "notion_update_blog_post", "op": "update_blog_post",
             "target": {"url": "https://www.notion.so/p9", "bp_id": "BP-9"},
             "fields": {"Status": "Published", "Direct URL": "https://x/approved-one/", "Publish Date": "2026-10-07"},
             "expect": {"Status": "Approved"}}],
            "needs_person": [{"bp_id": "BP-8", "detail": "no production_host"}],
            "url_mismatch": [{"bp_id": "BP-7", "detail": "canonical differs"}],
            "flagged": [{"bp_id": "BP-5", "reason": "body_changed_after_publish", "detail": "sha differs"}],
            "not_yet": [{"bp_id": "BP-6", "detail": "pr open"}]}
        sf = self.tmp / "blog-sweep.json"
        sf.write_text(json.dumps(sweep))
        plan, _ = self.run_plan("--stage", "sweep", "--sweep", str(sf))
        self.assertEqual(plan["stage"], "sweep")
        self.assertEqual(len(plan["actions"]), 1)
        self.assertEqual(plan["actions"][0]["fields"]["Status"], "Published")
        self.assertEqual(plan["actions"][0]["expect"], {"Status": "Approved"})
        self.assertEqual({h["reason"] for h in plan["held"]}, {"stale_status", "slug_collision"})
        self.assertEqual(plan["flagged"][0]["reason"], "body_changed_after_publish")
        self.assertEqual(len(plan["warnings"]), 1)
        _, res = self.run_plan("--stage", "sweep", "--sweep", str(sf), "--write-approval", expect=4)
        self.assertIn("plan_only", res.stderr)


if __name__ == "__main__":
    unittest.main()
