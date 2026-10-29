"""Tests for the WhatsApp ingest (scripts/twochat_client.py, scripts/whatsapp_pull.py).

The guarantees pinned here:
- Neither file can write to WhatsApp or 2Chat: no write verbs, no request body,
  every request is a GET.
- api.p.2chat.io is spelled in one file only.
- Phone numbers never leave the pull unhashed, and the personal channel is never team.
"""

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import twochat_client as tc  # noqa: E402
import whatsapp_pull as wp  # noqa: E402

SETTINGS = json.loads((REPO_ROOT / "platform-settings/whatsapp-ingest-sources.json").read_text())
SALT = "test-salt"


class TestNoWritePath(unittest.TestCase):
    FILES = ("scripts/twochat_client.py", "scripts/whatsapp_pull.py")

    def test_no_write_verbs(self):
        for rel in self.FILES:
            src = (REPO_ROOT / rel).read_text()
            for verb in ("POST", "PUT", "PATCH", "DELETE"):
                self.assertNotIn(f'"{verb}"', src, f"{rel} contains a {verb} literal")
            self.assertNotIn("method=", src, f"{rel} passes an explicit HTTP method")
            self.assertNotIn("data=", src, f"{rel} sends a request body")

    def test_client_requests_are_get(self):
        cl = tc.TwoChatClient(api_key="k")
        self.assertEqual(cl._request("https://x/y").get_method(), "GET")

    def test_no_make_or_notion_path(self):
        # 2026-10-29: 2Chat is the only source; the Make capture lane was removed.
        for rel in self.FILES:
            src = (REPO_ROOT / rel).read_text()
            for token in ("make.com", "MAKE_API", "data-stores", "api.notion.com"):
                self.assertNotIn(token, src, f"{rel} references {token}")

    def test_2chat_host_spelled_once(self):
        hits = [p.name for p in (REPO_ROOT / "scripts").glob("*.py")
                if "api.p.2chat.io" in p.read_text()]
        self.assertEqual(hits, ["twochat_client.py"])

    def test_missing_key_is_a_setup_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(tc.TwoChatError) as cm:
                tc.TwoChatClient()
        self.assertIn("TWOCHAT_API_KEY", str(cm.exception))


class TestNormalize(unittest.TestCase):
    def raw(self, **kw):
        base = {"message_uuid": "MSG1", "chat_uuid": "WAGabc", "chat_name": "Titan Flooring - SIDCO",
                "is_group": True, "sender_number": "+1 (905) 555-0101", "sender_name": "Angad",
                "direction": "in", "sent_at": "2026-10-29T14:00:00Z", "text": "pickup done"}
        base.update(kw)
        return base

    def test_numbers_are_hashed_not_emitted(self):
        m = wp.normalize(self.raw(), "business", SALT, {})
        blob = json.dumps(m)
        self.assertNotIn("9055550101", blob)
        self.assertNotIn("555-0101", blob)
        self.assertEqual(m["sender_last4"], "0101")
        self.assertEqual(len(m["sender_hash"]), 16)

    def test_hash_is_salted_and_stable(self):
        a = wp.hash_number("+19055550101", SALT)
        self.assertEqual(a, wp.hash_number("1 905 555 0101", SALT))
        self.assertNotEqual(a, wp.hash_number("+19055550101", "other"))

    def test_one_to_one_chat_key_is_a_hash(self):
        m = wp.normalize(self.raw(is_group=False, chat_uuid="+19055550199",
                                  remote_phone_number="+19055550199"), "business", SALT, {})
        self.assertFalse(m["is_group"])
        self.assertNotIn("9055550199", json.dumps(m))
        self.assertEqual(m["chat_key"], wp.hash_number("+19055550199", SALT))

    def test_registry_override_applies(self):
        chats = {"WAGabc": {"kind": "supplier", "sensitivity": "private", "ghl_covered": False}}
        m = wp.normalize(self.raw(), "business", SALT, chats)
        self.assertEqual(m["kind"], "supplier")

    def test_direction_inferred_from_sent_by(self):
        m = wp.normalize(self.raw(direction=None, sent_by="user"), "business", SALT, {})
        self.assertEqual(m["direction"], "out")

    def test_2chat_group_payload(self):
        raw = {"uuid": "U1", "created_at": "2026-10-29T15:00:00Z", "sent_by": "contact",
               "message": {"text": "pickup done"},
               "group": {"uuid": "WAG42", "wa_group_name": "Titan Flooring - SIDCO"},
               "participant": {"phone_number": "+19055550101", "pushname": "Angad"}}
        m = wp.normalize(raw, "business", SALT, {})
        self.assertTrue(m["is_group"])
        self.assertEqual((m["chat_key"], m["chat_name"], m["sender_name"], m["direction"]),
                         ("WAG42", "Titan Flooring - SIDCO", "Angad", "in"))
        self.assertNotIn("9055550101", json.dumps(m))

    def test_2chat_direct_payload(self):
        raw = {"uuid": "U2", "created_at": "2026-10-29T15:00:00Z", "sent_by": "user",
               "message": {"text": "on our way"}, "remote_phone_number": "+19055550199",
               "contact": {"first_name": "Dawn", "last_name": "G"}}
        m = wp.normalize(raw, "business", SALT, {})
        self.assertFalse(m["is_group"])
        self.assertEqual((m["chat_name"], m["direction"]), ("Dawn G", "out"))

    def test_no_uuid_is_dropped(self):
        self.assertIsNone(wp.normalize({"text": "x"}, "business", SALT, {}))


class FakeClient:
    def __init__(self, direct, groups, group_msgs, fail_group=None):
        self.direct, self.groups_, self.group_msgs, self.fail_group = direct, groups, group_msgs, fail_group

    def messages(self, number):
        return self.direct

    def groups(self, number):
        return self.groups_

    def group_messages(self, uuid):
        if uuid == self.fail_group:
            raise tc.TwoChatError("HTTP 404 on GET group messages", code=404)
        return self.group_msgs.get(uuid, [])


class TestPull(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.env = mock.patch.dict(os.environ, {"TWOCHAT_BUSINESS_NUMBER": "+19055550000"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def msg(self, uuid, hours_ago, **kw):
        d = {"uuid": uuid, "created_at": (self.now - timedelta(hours=hours_ago)).isoformat(),
             "sent_by": "contact", "message": {"text": "t"}}
        d.update(kw)
        return d

    def test_groups_are_read_and_named_from_the_listing(self):
        client = FakeClient(
            direct=[self.msg("D1", 1, remote_phone_number="+19055550199")],
            groups=[{"uuid": "WAG1", "wa_group_name": "Titan Flooring - SIDCO"}],
            group_msgs={"WAG1": [self.msg("G1", 2, participant={"phone_number": "+19055550101"})]})
        out, errors = wp.pull(self.now - timedelta(hours=24), SALT, {}, ["business"], client=client)
        self.assertEqual(errors, [])
        g = [m for m in out if m["is_group"]]
        self.assertEqual([(m["chat_key"], m["chat_name"]) for m in g], [("WAG1", "Titan Flooring - SIDCO")])
        self.assertEqual(len(out), 2)

    def test_window_filter(self):
        client = FakeClient(direct=[self.msg("new", 1), self.msg("old", 72)], groups=[], group_msgs={})
        out, _ = wp.pull(self.now - timedelta(hours=24), SALT, {}, ["business"], client=client)
        self.assertEqual([m["message_uuid"] for m in out], ["new"])

    def test_one_failing_group_is_isolated(self):
        client = FakeClient(direct=[self.msg("D1", 1)],
                            groups=[{"uuid": "WAG1", "wa_group_name": "A"}, {"uuid": "WAG2", "wa_group_name": "B"}],
                            group_msgs={"WAG2": [self.msg("G2", 1)]}, fail_group="WAG1")
        out, errors = wp.pull(self.now - timedelta(hours=24), SALT, {}, ["business"], client=client)
        self.assertEqual(len(errors), 1)
        self.assertIn("group A", errors[0])
        self.assertEqual({m["message_uuid"] for m in out}, {"D1", "G2"})

    def test_missing_number_is_reported_not_fatal(self):
        client = FakeClient(direct=[], groups=[], group_msgs={})
        out, errors = wp.pull(self.now, SALT, {}, ["personal"], client=client)
        self.assertIn("TWOCHAT_PERSONAL_NUMBER not set", errors[0])

    def test_dedupe(self):
        m = {"message_uuid": "A", "sent_at": "2026-10-29T10:00:00+00:00"}
        self.assertEqual(len(wp.dedupe([m, dict(m)])), 1)


class TestRegistry(unittest.TestCase):
    def test_personal_channel_is_private_and_locked(self):
        personal = SETTINGS["channels"]["personal"]
        self.assertEqual(personal["sensitivity"], "private")
        self.assertTrue(personal.get("locked"))

    def test_no_channel_defaults_to_team_without_a_decision(self):
        for name, ch in SETTINGS["channels"].items():
            if name.startswith("_"):
                continue
            self.assertIn(ch["sensitivity"], ("private", "team"))
        self.assertEqual(SETTINGS["channels"]["business"]["sensitivity"], "private")

    def test_registry_holds_no_phone_numbers(self):
        text = (REPO_ROOT / "platform-settings/whatsapp-ingest-sources.json").read_text()
        import re
        self.assertIsNone(re.search(r"\+?\d[\d\s().-]{9,}\d", text), "a phone number in the registry")

    def test_source_default_is_private(self):
        nd = json.loads((REPO_ROOT / "platform-settings/notion-destinations.json").read_text())
        self.assertEqual(nd["source_defaults"]["whatsapp"], "private")

    def test_cache_dir_is_gitignored(self):
        self.assertIn("analysis/cache/", (REPO_ROOT / ".gitignore").read_text())


class TestNotionGate(unittest.TestCase):
    """No WhatsApp item ever reaches the staff Notion board (Albert 2026-10-29)."""

    def test_contract_carries_the_gate(self):
        text = (REPO_ROOT / "contracts/notion-task-schema.md").read_text()
        self.assertIn("WhatsApp: never the team board", text)
        self.assertIn('IF source == "whatsapp"                                ⇒  never the team destination', text)

    def test_notion_sync_applies_the_gate(self):
        text = (REPO_ROOT / ".claude/commands/notion-sync.md").read_text()
        self.assertIn("Apply the WhatsApp gate too", text)

    def test_no_channel_allows_the_team_board(self):
        for name, ch in SETTINGS["channels"].items():
            if not name.startswith("_"):
                self.assertIs(ch.get("notion_team_destination"), False, name)

    def test_agent_types_cover_projects_and_catch_all(self):
        text = (REPO_ROOT / ".claude/agents/whatsapp-ingest-agent.md").read_text()
        for t in ("`project`", "`other`", "`supplier-pickup`", "`customer`"):
            self.assertIn(t, text)


class TestArchive(unittest.TestCase):
    def test_2chat_is_the_archive(self):
        a = SETTINGS["archive"]
        self.assertEqual(a["location"], "2chat")
        self.assertNotIn("business", a)
        self.assertNotIn("personal", a)


if __name__ == "__main__":
    unittest.main()
