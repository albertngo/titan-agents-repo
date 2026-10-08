#!/usr/bin/env python3
"""Tests for scripts/ghl_triage_log.py against throwaway git repos (no network).

    python3 -m unittest discover -s tests -v

The log branch is written by plumbing so an hourly routine never disturbs its own session
branch, two fires racing each other both land, and nothing outside ghl-triage/ is ever
written. Skipped when git is unavailable.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


glog = _load("ghl_triage_log", "scripts/ghl_triage_log.py")
REG = json.loads((REPO_ROOT / "platform-settings/ghl-unread-triage.json").read_text())
TZ = ZoneInfo("America/Toronto")
ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t"}


def sh(cwd, *args):
    import os
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=dict(os.environ, **ENV)).stdout.strip()


def run(run_id, when, rows=None, rubric="1"):
    return {"run_id": run_id, "run_at": when.isoformat(), "mode": "sweep", "write_mode": "plan_only",
            "rubric_version": rubric, "status": "ready", "summary": {}, "notified": [],
            "rows": rows or [{"conversation_id": "c1", "batch_key": "b-1", "model_verdict": "CLOSER",
                              "verdict": "CLOSER", "verdict_source": "model", "reason": "thanks"}]}


@unittest.skipUnless(shutil.which("git"), "git not installed")
class TestLogBranch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.origin = self.tmp / "origin.git"
        sh(self.tmp, "init", "--bare", "-q", str(self.origin))
        self.a = self.clone("a")
        (self.a / "f.txt").write_text("x")
        sh(self.a, "add", "f.txt")
        sh(self.a, "commit", "-q", "-m", "main")
        sh(self.a, "push", "-q", "origin", "HEAD:refs/heads/main")
        self.now = datetime(2026, 10, 8, 10, 0, tzinfo=TZ)
        self.sleep = lambda s: None

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def clone(self, name):
        path = self.tmp / name
        sh(self.tmp, "clone", "-q", str(self.origin), str(path))
        for k, v in (("user.name", "t"), ("user.email", "t@t")):
            sh(path, "config", k, v)
        return path

    def test_missing_branch_then_init(self):
        self.assertEqual(glog.fetch(self.a, REG), "missing")
        with self.assertRaises(glog.BranchMissing):
            glog.append(self.a, REG, run=run("r1", self.now), sleep=self.sleep)
        glog.init(self.a, REG)
        self.assertEqual(glog.fetch(self.a, REG), "ok")
        self.assertIn("Never merge", glog.show(self.a, glog.remote_ref(REG), "ghl-triage/README.md"))
        with self.assertRaises(glog.LogError):
            glog.init(self.a, REG)

    def test_append_leaves_the_working_branch_alone(self):
        glog.init(self.a, REG)
        head = sh(self.a, "rev-parse", "HEAD")
        branch = sh(self.a, "rev-parse", "--abbrev-ref", "HEAD")
        glog.append(self.a, REG, run=run("r1", self.now), sleep=self.sleep)
        self.assertEqual(sh(self.a, "rev-parse", "HEAD"), head)
        self.assertEqual(sh(self.a, "rev-parse", "--abbrev-ref", "HEAD"), branch)
        self.assertEqual(sh(self.a, "status", "--porcelain"), "")
        doc = glog.read_json(self.a, glog.remote_ref(REG), "ghl-triage/2026-10-08/runs.json")
        self.assertEqual([r["run_id"] for r in doc["runs"]], ["r1"])
        self.assertEqual(doc["contract_version"], "ghl-triage-day-1")

    def test_idempotent_runs_and_union_of_actions(self):
        glog.init(self.a, REG)
        glog.append(self.a, REG, run=run("r1", self.now), sleep=self.sleep)
        glog.append(self.a, REG, run=dict(run("r1", self.now), status="needs_person"), sleep=self.sleep)
        e = {"logged_at": self.now.isoformat(), "raw_ref_action_id": "gmr-1", "result": "executed",
             "type": "mark_conversation_read"}
        glog.append(self.a, REG, actions=[e], sleep=self.sleep)
        glog.append(self.a, REG, actions=[e, dict(e, raw_ref_action_id="gmr-2")], sleep=self.sleep)
        ref = glog.remote_ref(REG)
        runs = glog.read_json(self.a, ref, "ghl-triage/2026-10-08/runs.json")["runs"]
        self.assertEqual([(r["run_id"], r["status"]) for r in runs], [("r1", "needs_person")])
        acts = glog.read_json(self.a, ref, "ghl-triage/2026-10-08/actions-log.json")["entries"]
        self.assertEqual([x["raw_ref_action_id"] for x in acts], ["gmr-1", "gmr-2"])

    def test_two_fires_racing_both_land(self):
        glog.init(self.a, REG)
        b = self.clone("b")
        self.assertEqual(glog.fetch(b, REG), "ok")
        glog.append(self.a, REG, run=run("r1", self.now), sleep=self.sleep)
        # b's remote-tracking ref is stale; its first push is rejected, then it rebuilds.
        real_fetch = glog.fetch
        calls = {"n": 0}

        def stale_once(repo, reg):
            calls["n"] += 1
            return "ok" if (calls["n"] == 1 and repo == b) else real_fetch(repo, reg)

        glog.fetch = stale_once
        try:
            glog.append(b, REG, run=run("r2", self.now + timedelta(minutes=1)), sleep=self.sleep)
        finally:
            glog.fetch = real_fetch
        self.assertGreaterEqual(calls["n"], 2, "the first push should have been rejected")
        glog.fetch(self.a, REG)
        runs = glog.read_json(self.a, glog.remote_ref(REG), "ghl-triage/2026-10-08/runs.json")["runs"]
        self.assertEqual([r["run_id"] for r in runs], ["r1", "r2"])

    def test_kill_switch_and_cache(self):
        glog.init(self.a, REG)
        glog.append(self.a, REG, run=run("r1", self.now), kill="raced_new_message r1", sleep=self.sleep)
        ref = glog.remote_ref(REG)
        self.assertIn("raced_new_message", glog.kill_switch(self.a, REG, ref))
        cache = glog.load_cache(self.a, REG, self.now, "1", ref)
        self.assertEqual(cache["b-1"]["verdict"], "CLOSER")
        self.assertEqual(glog.load_cache(self.a, REG, self.now, "2", ref), {}, "a rubric bump drops the cache")
        glog.append(self.a, REG, clear_kill_by="Albert, this session", sleep=self.sleep)
        self.assertIsNone(glog.kill_switch(self.a, REG, ref))

    def test_writes_only_under_its_root(self):
        for bad in ("README.md", "ghl-triage/../x", "/etc/x", "ingest/2026-10-08/ghl.json"):
            with self.assertRaises(glog.LogError):
                glog.check_path(REG, bad)
        glog.check_path(REG, "ghl-triage/2026-10-08/runs.json")


if __name__ == "__main__":
    unittest.main()
