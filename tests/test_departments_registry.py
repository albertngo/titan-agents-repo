#!/usr/bin/env python3
"""Structural tests for platform-settings/departments.json and requesters.json.

Stdlib unittest, no pytest — matching the repo's convention.

    python3 -m unittest discover -s tests -v

The registry is only a routing *partition* as long as someone maintains it, and a
stale entry fails silently: a source owned twice routes non-deterministically, a
source owned by nobody falls through to `general` without saying so. These tests
make that mechanical rather than a promise — the same job test_lightspeed.py does
for the read path containing no write verb.
"""

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "platform-settings" / "departments.json"
REQUESTERS = REPO_ROOT / "platform-settings" / "requesters.json"
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

# The ingest sources named in CLAUDE.md's agent table. Kept as a literal so a
# source added there without a department entry fails loudly here, rather than
# being discovered by a misrouted request.
INGEST_SOURCES = {"ghl", "outlook", "bookkeeper", "notion", "meta-ads", "content"}


class RegistryCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY.read_text())
        cls.departments = cls.registry["departments"]
        cls.requesters = json.loads(REQUESTERS.read_text())


class TestPartition(RegistryCase):
    """owns.sources[] must be a partition of the ingest sources."""

    def test_no_source_is_owned_twice(self):
        owners = {}
        for key, dept in self.departments.items():
            for source in dept["owns"]["sources"]:
                owners.setdefault(source, []).append(key)
        doubly = {s: d for s, d in owners.items() if len(d) > 1}
        self.assertEqual(doubly, {}, f"sources owned by more than one department: {doubly}")

    def test_every_ingest_source_is_owned(self):
        owned = {s for d in self.departments.values() for s in d["owns"]["sources"]}
        unowned = INGEST_SOURCES - owned
        self.assertEqual(
            unowned, set(), f"ingest sources owned by nobody — they fall to general: {unowned}"
        )

    def test_no_department_claims_a_source_that_does_not_exist(self):
        owned = {s for d in self.departments.values() for s in d["owns"]["sources"]}
        unknown = owned - INGEST_SOURCES
        self.assertEqual(
            unknown, set(), f"departments claim sources no ingest agent writes: {unknown}"
        )

    def test_ingest_sources_literal_matches_claude_md(self):
        """INGEST_SOURCES above has not drifted from CLAUDE.md's agent table."""
        text = CLAUDE_MD.read_text()
        for source in sorted(INGEST_SOURCES):
            self.assertIn(
                f"`{source}.json`",
                text,
                f"{source} is in INGEST_SOURCES but CLAUDE.md's table names no {source}.json",
            )


class TestNamesResolve(RegistryCase):
    def test_specialist_agents_exist(self):
        for key, dept in self.departments.items():
            for role in ("readonly", "actions"):
                for agent in dept["specialists"][role]:
                    self.assertTrue(
                        (AGENTS_DIR / f"{agent}.md").is_file(),
                        f"{key}.specialists.{role} names {agent}, not a file in .claude/agents/",
                    )

    def test_owned_commands_exist(self):
        for key, dept in self.departments.items():
            for command in dept["owns"]["commands"]:
                self.assertTrue(
                    (COMMANDS_DIR / f"{command}.md").is_file(),
                    f"{key}.owns.commands names {command}, not a file in .claude/commands/",
                )

    def test_lead_resolves(self):
        for key, dept in self.departments.items():
            lead = dept["lead"]
            if lead is None:
                self.assertIn(
                    dept["status"],
                    ("spec", "registry_only", "blocked"),
                    f"{key} is {dept['status']} but has no lead",
                )
                continue
            directory = AGENTS_DIR if dept["kind"] == "agent" else COMMANDS_DIR
            self.assertTrue(
                (directory / f"{lead}.md").is_file(),
                f"{key}.lead {lead} does not resolve in {directory.name}/",
            )


class TestBoundaries(RegistryCase):
    """The properties that erode quietly if nothing checks them."""

    def test_no_actions_agent_is_dispatchable(self):
        """The likeliest future mistake: adding a writer to a readonly list.

        contracts/dept-plan-schema.md states this as an invalid-plan condition,
        not a permission question. An *-actions agent is reachable only through
        an approval file naming exact action ids.
        """
        for key, dept in self.departments.items():
            for agent in dept["specialists"]["readonly"]:
                self.assertFalse(
                    agent.endswith("-actions-agent"),
                    f"{key}.specialists.readonly contains {agent}. An actions agent is never "
                    f"dispatchable — it belongs in specialists.actions.",
                )

    def test_registry_carries_no_sensitivity_or_write_policy(self):
        """A department is not a sensitivity boundary; provenance decides."""
        raw = REGISTRY.read_text()
        for banned in ('"sensitivity"', '"write_policy"'):
            self.assertNotIn(
                banned,
                raw,
                f"{banned} appears in departments.json — see its _no_sensitivity_note.",
            )

    def test_parked_departments_say_how_to_unpark(self):
        for key, dept in self.departments.items():
            if dept["status"] == "blocked":
                self.assertTrue(dept.get("blocked_reason"), f"{key} blocked with no reason")
                self.assertTrue(dept.get("unblock_criteria"), f"{key} blocked with no criteria")
            if dept["status"] == "registry_only":
                self.assertTrue(
                    dept.get("promote_criteria"), f"{key} registry_only with no promote_criteria"
                )
            if dept["status"] == "spec":
                self.assertTrue(dept.get("spec_reason"), f"{key} is spec with no spec_reason")

    def test_escalation_order_is_a_total_order(self):
        """Departments render side by side in this order, never merged into one
        ranked list — so it has to be unambiguous."""
        orders = [d["escalation_order"] for d in self.departments.values()]
        self.assertEqual(len(orders), len(set(orders)), f"duplicate escalation_order: {orders}")

    def test_active_agent_departments_declare_a_real_plan_contract(self):
        for key, dept in self.departments.items():
            if dept["status"] == "active" and dept["kind"] == "agent":
                self.assertTrue(dept["plan_file"], f"{key} is active but has no plan_file")
                self.assertTrue(
                    (REPO_ROOT / dept["plan_contract"]).is_file(),
                    f"{key}.plan_contract {dept['plan_contract']} does not exist",
                )


class TestRequesters(RegistryCase):
    def test_tiers_are_defined(self):
        for entry in self.requesters["requesters"]:
            self.assertIn(
                entry["tier"],
                self.requesters["tiers"],
                f"{entry['requester_id']} names undefined tier {entry['tier']}",
            )

    def test_tiers_reach_only_real_departments(self):
        for name, tier in self.requesters["tiers"].items():
            allowed = tier["departments"]
            if allowed == "*":
                continue
            unknown = set(allowed) - set(self.departments)
            self.assertEqual(
                unknown, set(), f"tier {name} may reach departments that do not exist: {unknown}"
            )

    def test_no_raw_contact_details(self):
        """The repo is public. Identifiers are hashed, or resolved upstream by Make."""
        raw = REQUESTERS.read_text()

        # Count digits rather than pattern-match: a phone number carries 10+,
        # while the ISO dates this file legitimately cites carry 8.
        for candidate in re.findall(r"\+?[\d][\d\-\s().]{7,}[\d]", raw):
            digits = sum(c.isdigit() for c in candidate)
            self.assertLess(
                digits,
                10,
                f"requesters.json contains {candidate!r}, which looks like a phone number. "
                f"See its _privacy_note.",
            )

        self.assertIsNone(
            re.search(r"[\w.+-]+@[\w-]+\.[\w.]{2,}", raw),
            "requesters.json looks like it contains an email address — see its _privacy_note.",
        )


if __name__ == "__main__":
    unittest.main()
