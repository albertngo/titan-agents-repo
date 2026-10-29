"""Tests for the WhatsApp ingest (scripts/twochat_client.py, scripts/whatsapp_pull.py).

The guarantees pinned here:
- Neither file can write to WhatsApp, 2Chat or Make: no write verbs, no request body,
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

    def test_make_store_read_is_get(self):
        seen = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"records": []}'

        def fake_open(req, timeout=None):
            seen.append(req.get_method())
            return Resp()

        with mock.patch.object(wp.urllib.request, "urlopen", fake_open), \
                mock.patch.object(wp.json, "load", lambda r: json.loads(r.read())):
            wp.make_get("https://us2.make.com/api/v2/data-stores/1/data", "t")
        self.assertEqual(seen, ["GET"])

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
        m = wp.normalize(self.raw(), "business", "capture", SALT, {})
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
                                  remote_phone_number="+19055550199"), "business", "api", SALT, {})
        self.assertFalse(m["is_group"])
        self.assertNotIn("9055550199", json.dumps(m))
        self.assertEqual(m["chat_key"], wp.hash_number("+19055550199", SALT))

    def test_registry_override_applies(self):
        chats = {"WAGabc": {"kind": "supplier", "sensitivity": "private", "ghl_covered": False}}
        m = wp.normalize(self.raw(), "business", "capture", SALT, chats)
        self.assertEqual(m["kind"], "supplier")

    def test_direction_inferred_from_sent_by(self):
        m = wp.normalize(self.raw(direction=None, sent_by="user"), "business", "api", SALT, {})
        self.assertEqual(m["direction"], "out")

    def test_no_uuid_is_dropped(self):
        self.assertIsNone(wp.normalize({"text": "x"}, "business", "api", SALT, {}))


class TestMerge(unittest.TestCase):
    def test_dedupe_prefers_capture(self):
        api = {"message_uuid": "A", "lane": "api", "sent_at": "2026-10-29T10:00:00+00:00", "chat_name": None}
        cap = dict(api, lane="capture", chat_name="SIDCO")
        out = wp.merge([[api], [cap]])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["lane"], "capture")

    def test_capture_window_filter(self):
        now = datetime.now(timezone.utc)
        rec = lambda k, ts: {"key": k, "data": {"chat_uuid": "WAGx", "is_group": True,
                                                  "direction": "in", "sent_at": ts.isoformat(),
                                                  "text": "t", "channel": "business"}}
        page = {"records": [rec("new", now - timedelta(hours=1)), rec("old", now - timedelta(days=3))]}
        env = {"MAKE_API_TOKEN": "t", "MAKE_API_HOST": "us2.make.com", "WHATSAPP_LOG_DATASTORE_ID": "1"}
        with mock.patch.dict(os.environ, env), mock.patch.object(wp, "make_get", lambda u, t: page):
            out, err = wp.pull_capture(now - timedelta(hours=24), SALT, {})
        self.assertIsNone(err)
        self.assertEqual([m["message_uuid"] for m in out], ["new"])

    def test_capture_not_configured_is_reported(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            out, err = wp.pull_capture(datetime.now(timezone.utc), SALT, {})
        self.assertEqual(out, [])
        self.assertIn("MAKE_API_TOKEN", err)


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


if __name__ == "__main__":
    unittest.main()
