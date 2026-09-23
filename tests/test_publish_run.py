#!/usr/bin/env python3
"""The publish step: a run's output must reach main-agents as a PR.

    python3 -m unittest discover -s tests -v

Until 2026-09-23 nothing in the price-list routine pushed a PR, and fifteen
session branches stranded ~100 commits. These tests hold two things: the script
reuses an open PR instead of duplicating it, and the routine's stored text still
tells every run to publish.
"""

import importlib.util
import io
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("publish_run", REPO_ROOT / "scripts/publish_run.py")
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)

ROUTINE = REPO_ROOT / "methods/pricelist-pipeline-routine-prompt.md"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_returning(*payloads):
    calls = []

    def opener(req, timeout=None):
        calls.append((req.get_method(), req.full_url, json.loads(req.data) if req.data else None))
        return FakeResponse(json.dumps(payloads[len(calls) - 1]).encode())
    return opener, calls


class TestRepoSlug(unittest.TestCase):

    def test_https_and_ssh_remotes(self):
        self.assertEqual("albertngo/titan-agents-repo",
                         pr.repo_slug("https://github.com/albertngo/titan-agents-repo"))
        self.assertEqual("albertngo/titan-agents-repo",
                         pr.repo_slug("git@github.com:albertngo/titan-agents-repo.git"))

    def test_a_proxied_remote(self):
        self.assertEqual("albertngo/titan-agents-repo",
                         pr.repo_slug("http://127.0.0.1:1234/git/albertngo/titan-agents-repo"))


class TestFindOrOpen(unittest.TestCase):

    def test_an_open_pr_is_reused_not_duplicated(self):
        opener, calls = opener_returning([{"html_url": "https://x/pull/9"}])
        url, created = pr.find_or_open_pr("o/r", "claude/x", "t", "b", "tok", opener)
        self.assertEqual(("https://x/pull/9", False), (url, created))
        self.assertEqual(1, len(calls), "no POST when a PR already exists")

    def test_a_new_pr_targets_main_agents(self):
        opener, calls = opener_returning([], {"html_url": "https://x/pull/10"})
        url, created = pr.find_or_open_pr("o/r", "claude/x", "t", "b", "tok", opener)
        self.assertTrue(created)
        method, _, body = calls[1]
        self.assertEqual("POST", method)
        self.assertEqual("main-agents", body["base"])
        self.assertEqual("claude/x", body["head"])


class TestRoutineStillPublishes(unittest.TestCase):
    """The stored routine text is what an unattended run follows."""

    def fenced_block(self):
        text = ROUTINE.read_text()
        section = text.split("## Pointer prompt", 1)[1]
        return re.search(r"```\n(.*?)\n```", section, re.S).group(1)

    def test_the_fenced_block_has_a_publish_step(self):
        block = self.fenced_block()
        self.assertIn("scripts/publish_run.py", block)
        self.assertIn("PARTIAL", block)

    def test_publish_comes_after_sync(self):
        block = self.fenced_block()
        self.assertLess(block.index("Step 2"), block.index("scripts/publish_run.py"))


if __name__ == "__main__":
    unittest.main()
