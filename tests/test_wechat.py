#!/usr/bin/env python3
"""Tests for the WeChat archive (scripts/wechat_core.py, wechat_archive.py, wechat_pull.py).

Stdlib unittest, no pytest — matching the repo's convention.

    python3 -m unittest tests.test_wechat -v

The Mac reader cannot run here, so archive() is driven with a fake WeChat and a
fake Notion. What these pin: separators never take part in matching, a re-run
writes nothing twice, a chat that can't be lined up is flagged rather than
silently duplicated, one chat's messages are never filed under another, and the
write boundary (only wechat_archive.py inserts, and nothing here can send to
WeChat).
"""

import ast
import json
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import wechat_archive  # noqa: E402
import wechat_core as core  # noqa: E402

SETTINGS = core.load_settings()
KINDS = SETTINGS["parse"]["kind_patterns"]
TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 10, 29, 6, 30, tzinfo=TZ)  # a Thursday


def msg(sender, text):
    return {"sender": sender, "text": text}


class TestSeparators(unittest.TestCase):
    def check(self, text, expected):
        got = core.parse_separator(text, NOW)
        self.assertEqual(got.strftime("%Y-%m-%d %H:%M") if got else None, expected, text)

    def test_formats(self):
        self.check("10:42", "2026-10-29 10:42")
        self.check("Yesterday 14:03", "2026-10-28 14:03")
        self.check("昨天 14:03", "2026-10-28 14:03")
        self.check("Monday 09:15", "2026-10-26 09:15")
        self.check("星期一 09:15", "2026-10-26 09:15")
        self.check("Thursday 09:15", "2026-10-22 09:15")  # same weekday = last week
        self.check("2026/10/20 08:00", "2026-10-20 08:00")
        self.check("2026年10月20日 08:00", "2026-10-20 08:00")
        self.check("10/20/26 08:00", "2026-10-20 08:00")
        self.check("10月20日 下午3:05", "2026-10-20 15:05")
        self.check("12:30 PM", "2026-10-29 12:30")
        self.check("12:05 AM", "2026-10-29 00:05")
        self.check("10/21 13:17", "2026-10-21 13:17")  # WeChat 4.1.15
        self.check("12/30 09:00", "2025-12-30 09:00")  # no year shown, later than today

    def test_not_separators(self):
        for text in ("ok", "25:00", "Call me at 3", "2026/13/40 10:00", "", "price 10:42 sqft"):
            self.check(text, None)


class TestAnnotate(unittest.TestCase):
    def test_separators_dropped_and_stamp_messages(self):
        out = core.annotate([msg("UNKNOWN", "Yesterday 14:03"), msg("OTHER", "new list"),
                             msg("ME", "thanks")], NOW, KINDS)
        self.assertEqual([m["text"] for m in out], ["new list", "thanks"])
        self.assertTrue(out[0]["sent_at"].startswith("2026-10-28T14:03"))
        self.assertEqual([m["sender"] for m in out], ["Them", "Me"])

    def test_dated_separator_even_if_the_side_was_misread(self):
        out = core.annotate([msg("OTHER", "10/21 13:17"), msg("OTHER", "hi")], NOW, KINDS)
        self.assertEqual([m["text"] for m in out], ["hi"])
        self.assertTrue(out[0]["sent_at"].startswith("2026-10-21T13:17"))

    def test_a_person_typing_a_time_is_a_message(self):
        out = core.annotate([msg("OTHER", "10:42")], NOW, KINDS)
        self.assertEqual(len(out), 1)

    def test_kinds(self):
        self.assertEqual(core.classify_kind("[Image]", KINDS), "image")
        self.assertEqual(core.classify_kind("[图片]", KINDS), "image")
        self.assertEqual(core.classify_kind("[File] PL-2026.pdf", KINDS), "file")
        self.assertEqual(core.classify_kind("Image", KINDS), "image")  # WeChat 4.1.15
        self.assertEqual(core.classify_kind('Audio10"sec', KINDS), "voice")
        # WeChat 4.1.15, seen live 2026-10-30
        self.assertEqual(core.classify_kind("File\nTrim Price 10-16-2026 Store.pdf\n984.8K", KINDS),
                         "file")
        self.assertEqual(core.classify_kind("File the invoice please", KINDS), "text")
        self.assertEqual(core.classify_kind("Image looks good", KINDS), "text")
        self.assertEqual(core.classify_kind("https://example.com/x", KINDS), "link")
        self.assertEqual(core.classify_kind("Lily recalled a message", KINDS), "system")
        self.assertEqual(core.classify_kind("see you tomorrow", KINDS), "text")


class TestNames(unittest.TestCase):
    """Albert, 2026-10-30: every message carries a named sender."""

    PEOPLE = {"me": "Albert", "aliases": {"helen": "Helen"},
              "alias_patterns": {r"^前景Sam\b": "Sam (前景)"}}

    def names(self, raw, chat, is_group):
        out = core.annotate({"messages": raw, "is_group": is_group}, NOW, KINDS,
                            chat=chat, people=self.PEOPLE)
        return [(m["from"], m["to"], m["sender"], m["chat_type"]) for m in out]

    def test_group_names_read_off_the_screen(self):
        raw = [{"sender": "OTHER", "text": "Image", "speaker": "前景Sam 4165550199"},
               {"sender": "OTHER", "text": "Thank you so much", "speaker": "helen"},
               {"sender": "UNKNOWN", "text": "10/21 13:17", "speaker": None},
               {"sender": "ME", "text": "Got it", "speaker": None},
               {"sender": "OTHER", "text": "ok", "speaker": None}]
        self.assertEqual(self.names(raw, "VISTA (Markham)", True), [
            ("Sam (前景)", "VISTA (Markham)", "Them", "group"),
            ("Helen", "VISTA (Markham)", "Them", "group"),
            ("Albert", "VISTA (Markham)", "Me", "group"),
            ("Unknown", "VISTA (Markham)", "Them", "group"),  # no name read: never guessed
        ])

    def test_a_name_above_the_bubble_means_it_is_not_mine(self):
        raw = [{"sender": "ME", "text": "hi", "speaker": "helen"}]
        self.assertEqual(self.names(raw, "G", True)[0][:3], ("Helen", "G", "Them"))

    def test_direct_chat(self):
        raw = [{"sender": "OTHER", "text": "price list attached"},
               {"sender": "ME", "text": "thanks"},
               {"sender": "UNKNOWN", "text": "?"}]
        self.assertEqual(self.names(raw, "diana", False), [
            ("diana", "Albert", "Them", "direct"),
            ("Albert", "diana", "Me", "direct"),
            ("Unknown", None, "Unknown", "direct"),
        ])

    def test_speaker_ignored_in_direct_chats(self):
        raw = [{"sender": "OTHER", "text": "x", "speaker": "noise"}]
        self.assertEqual(self.names(raw, "diana", False)[0][0], "diana")


class TestSidebar(unittest.TestCase):
    GROUP = "VISTA\nPinned to top\n前景Sam: [File] Trim Price 10-16-2026 Skid.pdf\n10/21\n"

    def test_parse(self):
        self.assertEqual(core.parse_sidebar(self.GROUP),
                         ("前景Sam", "[File] Trim Price 10-16-2026 Skid.pdf"))
        self.assertEqual(core.parse_sidebar("diana\nok see you\nYesterday 18:56\n"),
                         (None, "ok see you"))

    def test_match(self):
        self.assertTrue(core.matches_newest("[File] Trim Price 10-16-2026 Skid.pdf",
                                            "File\nTrim Price 10-16-2026 Skid.pdf\n821.0K", KINDS))
        self.assertTrue(core.matches_newest("[Voice]", 'Audio10"sec', KINDS))
        self.assertFalse(core.matches_newest("see you tomorrow", "Right side open", KINDS))

    def test_newest_named_from_the_sidebar_and_mismatch_warned(self):
        raw = {"is_group": True, "sidebar": self.GROUP,
               "messages": [{"sender": "OTHER", "text": "File\nTrim Price 10-16-2026 Skid.pdf\n821.0K",
                             "speaker": None}]}
        people = {"me": "Albert", "alias_patterns": {"^前景\\s?Sam": "Sam (前景)"}}
        msgs = core.annotate(raw, NOW, KINDS, chat="VISTA", people=people)
        summary = {}
        wechat_archive.check_newest(raw, msgs, "VISTA", people, KINDS, summary)
        self.assertEqual(msgs[-1]["from"], "Sam (前景)")
        self.assertNotIn("warnings", summary)
        raw["messages"][0]["text"] = "an older message"
        msgs = core.annotate(raw, NOW, KINDS, chat="VISTA", people=people)
        wechat_archive.check_newest(raw, msgs, "VISTA", people, KINDS, summary)
        self.assertEqual(len(summary["warnings"]), 1)
        self.assertEqual(msgs[-1]["from"], "Unknown")


class TestAlign(unittest.TestCase):
    def test_empty_tail_starts_at_zero(self):
        self.assertEqual(core.align([], ["a", "b"], 3), 0)

    def test_new_after_overlap(self):
        self.assertEqual(core.align(["a", "b", "c"], ["z", "a", "b", "c", "d", "e"], 3), 4)

    def test_nothing_new(self):
        self.assertEqual(core.align(["a", "b", "c"], ["a", "b", "c"], 3), 3)

    def test_repeated_short_message_uses_the_longest_suffix(self):
        # Stored x, ok, ok; on screen one more ok then y. Matching only "ok, ok"
        # at its latest place would drop the new "ok".
        self.assertEqual(core.align(["x", "ok", "ok"], ["x", "ok", "ok", "ok", "y"], 2), 3)

    def test_ambiguous_repeat_prefers_writing_nothing_twice(self):
        self.assertEqual(core.align(["ok", "ok"], ["ok", "ok", "ok"], 2), 3)

    def test_no_match(self):
        self.assertIsNone(core.align(["a", "b", "c"], ["d", "e"], 3))

    def test_short_overlap_not_trusted(self):
        self.assertIsNone(core.align(["a", "b", "c"], ["c", "d"], 3))

    def test_tiny_tail_accepts_its_own_length(self):
        self.assertEqual(core.align(["a"], ["a", "b"], 3), 1)


class TestPlanChat(unittest.TestCase):
    def test_sequences_and_keys_chain(self):
        msgs = core.annotate([msg("OTHER", "ok"), msg("OTHER", "ok")], NOW, KINDS)
        rows, aligned = core.plan_chat("Tosca", msgs, [], 3)
        self.assertTrue(aligned)
        self.assertEqual([r["sequence"] for r in rows], [1, 2])
        self.assertNotEqual(rows[0]["key"], rows[1]["key"])
        self.assertFalse(any(r["gap_before"] for r in rows))

    def test_gap_flag_only_on_first_unaligned_row(self):
        tail = [{"text": t, "key": "k", "sequence": 9} for t in ("a", "b", "c")]
        msgs = core.annotate([msg("OTHER", "x"), msg("OTHER", "y")], NOW, KINDS)
        rows, aligned = core.plan_chat("Tosca", msgs, tail, 3)
        self.assertFalse(aligned)
        self.assertEqual([r["gap_before"] for r in rows], [True, False])
        self.assertEqual(rows[0]["sequence"], 10)


class FakeWeChat:
    """
    Like the real Mac: the reader's own clicks reset the idle clock, so idle is
    time since the last synthetic event unless a person touched it later.
    """

    def __init__(self, chats, locked=False, idle=600):
        self.chats = chats  # name -> list of raw messages, oldest first
        self.locked = locked
        self.start_idle = idle
        self.reads = []
        self.wrong = set()
        self.t = 0.0
        self.last_event = None
        self.touch_before = set()  # chat names a person touches the Mac just before

    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def screen_locked(self):
        return self.locked

    def idle_seconds(self):
        if self.last_event is None:
            return self.start_idle
        return self.t - self.last_event

    def list_chats(self):
        return list(self.chats)

    def read_chat(self, chat, last_n):
        if chat in self.touch_before:
            self.last_event = self.t - 0.5  # a person moved the mouse in the pause
            self.touch_before.discard(chat)
            raise AssertionError("archive() should have stopped before reading")
        self.reads.append((chat, last_n))
        self.t += 2.0
        self.last_event = self.t  # our own scroll
        if chat in self.wrong:
            raise RuntimeError("opened 'Someone else' instead")
        return self.chats[chat][-last_n:]


class FakeNotion:
    def __init__(self):
        self.rows = []

    def tail(self, chat, n):
        return [r for r in self.rows if r["chat"] == chat][-n:]

    def insert(self, row, run, archived_at):
        self.rows.append(dict(row))


def settings(**archive):
    s = json.loads(json.dumps(SETTINGS))
    s["archive"].update(archive)
    return s


class TestArchive(unittest.TestCase):
    def run_once(self, wx, store, s=None, **kw):
        wx.t += 3600  # runs are hours apart; the Mac is idle at the start
        return wechat_archive.archive(wx, store, s or settings(), NOW,
                                      clock=wx.clock, sleep=wx.sleep, **kw)

    def test_rerun_writes_nothing_twice_even_when_separators_change(self):
        wx = FakeWeChat({"Tosca": [msg("UNKNOWN", "10:42"), msg("OTHER", "new list"),
                                   msg("ME", "thanks"), msg("OTHER", "ok")]})
        store = FakeNotion()
        first = self.run_once(wx, store)
        self.assertEqual(first["messages_new"], 3)
        # Next morning WeChat shows the same separator as "Yesterday 10:42".
        wx.chats["Tosca"] = [msg("UNKNOWN", "Yesterday 10:42"), msg("OTHER", "new list"),
                             msg("ME", "thanks"), msg("OTHER", "ok"),
                             msg("UNKNOWN", "06:01"), msg("OTHER", "ok")]
        second = self.run_once(wx, store)
        self.assertEqual(second["messages_new"], 1)
        self.assertEqual([r["sequence"] for r in store.rows], [1, 2, 3, 4])
        self.assertEqual(second["gaps"], [])

    def test_reads_further_back_before_accepting_a_gap(self):
        history = [msg("OTHER", f"m{i}") for i in range(60)]
        wx = FakeWeChat({"Tosca": history[:5]})
        store = FakeNotion()
        self.run_once(wx, store)
        wx.chats["Tosca"] = history  # 55 new, more than tail_check_messages
        out = self.run_once(wx, store)
        self.assertEqual(out["messages_new"], 55)
        self.assertEqual(out["gaps"], [])
        self.assertEqual(wx.reads[-1], ("Tosca", SETTINGS["archive"]["backfill_cap_messages"]))
        self.assertEqual([r["text"] for r in store.rows], [m["text"] for m in history])

    def test_unalignable_chat_is_flagged_not_duplicated_silently(self):
        wx = FakeWeChat({"Tosca": [msg("OTHER", "a"), msg("OTHER", "b"), msg("OTHER", "c")]})
        store = FakeNotion()
        self.run_once(wx, store)
        wx.chats["Tosca"] = [msg("OTHER", "x"), msg("OTHER", "y")]
        out = self.run_once(wx, store)
        self.assertEqual(out["gaps"], ["Tosca"])
        self.assertTrue(store.rows[3]["gap_before"])

    def test_wrong_chat_opened_is_an_error_and_others_continue(self):
        wx = FakeWeChat({"A": [msg("OTHER", "a")], "B": [msg("OTHER", "b")]})
        wx.wrong = {"A"}
        store = FakeNotion()
        out = self.run_once(wx, store)
        self.assertEqual(out["status"], "partial")
        self.assertEqual([r["chat"] for r in store.rows], ["B"])

    def test_skip_list_and_heartbeat_chat_never_opened(self):
        wx = FakeWeChat({"Subscriptions": [msg("OTHER", "ad")], "(archiver)": [],
                         "Tosca": [msg("OTHER", "hi")]})
        self.run_once(wx, FakeNotion())
        self.assertEqual([c for c, _ in wx.reads], ["Tosca"])

    def test_locked_screen_skips(self):
        out = self.run_once(FakeWeChat({"Tosca": [msg("OTHER", "hi")]}, locked=True),
                            FakeNotion())
        self.assertEqual((out["status"], out["reason"]), ("skipped", "screen locked"))

    def test_own_clicks_do_not_count_as_someone_using_the_mac(self):
        wx = FakeWeChat({f"c{i}": [msg("OTHER", "hi")] for i in range(4)})
        out = self.run_once(wx, FakeNotion())
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["chats_read"], 4)

    def test_someone_using_the_mac_stops_the_run(self):
        class Touchy(FakeWeChat):
            def sleep(self, s):
                super().sleep(s)
                if len(self.reads) == 1:
                    self.last_event = self.t - 0.5  # mouse moved during the pause
        wx = Touchy({"A": [msg("OTHER", "a")], "B": [msg("OTHER", "b")]})
        store = FakeNotion()
        out = self.run_once(wx, store)
        self.assertEqual(out["status"], "interrupted")
        self.assertEqual([r["chat"] for r in store.rows], ["A"])

    def test_busy_at_start_skips(self):
        out = self.run_once(FakeWeChat({"A": [msg("OTHER", "a")]}, idle=30), FakeNotion())
        self.assertEqual(out["status"], "skipped")

    def test_caffeinate_never_declares_user_activity(self):
        src = (REPO_ROOT / "scripts" / "wechat_archive.py").read_text()
        flags = re.search(r'"caffeinate", "-(\w+)"', src).group(1)
        self.assertNotIn("u", flags)

    def test_dry_run_writes_nothing(self):
        store = FakeNotion()
        out = self.run_once(FakeWeChat({"Tosca": [msg("OTHER", "hi")]}), store, dry_run=True)
        self.assertEqual(store.rows, [])
        self.assertEqual(out["messages_new"], 1)

    def test_max_chats(self):
        wx = FakeWeChat({f"c{i}": [msg("OTHER", "hi")] for i in range(10)})
        self.run_once(wx, FakeNotion(), s=settings(max_chats=3))
        self.assertEqual([c for c, _ in wx.reads], ["c0", "c1", "c2"])


class TestSchedule(unittest.TestCase):
    SCHED = SETTINGS["archive"]["schedule"]

    def at(self, hm):
        h, m = map(int, hm.split(":"))
        return NOW.replace(hour=h, minute=m)

    def test_never_ran_is_due_inside_the_window(self):
        self.assertTrue(core.is_due(None, self.at("07:00"), self.SCHED)[0])

    def test_outside_window(self):
        self.assertFalse(core.is_due(None, self.at("05:30"), self.SCHED)[0])
        self.assertFalse(core.is_due(None, self.at("22:30"), self.SCHED)[0])

    def test_once_a_day(self):
        yesterday_8 = (self.at("08:00") - timedelta(days=1)).isoformat()
        self.assertTrue(core.is_due(yesterday_8, self.at("07:00"), self.SCHED)[0])
        this_morning = self.at("07:00").isoformat()
        self.assertFalse(core.is_due(this_morning, self.at("12:00"), self.SCHED)[0])

    def test_one_chat_runs_and_failures_do_not_count_as_the_day(self):
        class S:
            def heartbeats(self, n):
                return [{"status": "ok", "only_chat": "Tosca", "archived_at": "x"},
                        {"status": "skipped", "archived_at": "y"},
                        {"status": "interrupted", "archived_at": "z"},
                        {"status": "ok", "only_chat": None, "archived_at": "w"}]
        self.assertEqual(wechat_archive.last_completed(S()), "w")


class TestBoundary(unittest.TestCase):
    """Nothing here can send to WeChat, and only the archiver writes to Notion."""

    SCRIPTS = REPO_ROOT / "scripts"

    def test_archiver_imports_only_read_functions_of_wechat_mcp(self):
        tree = ast.parse((self.SCRIPTS / "wechat_archive.py").read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("wechat_mcp"):
                imported |= {(node.module, a.name) for a in node.names}
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertFalse(a.name.startswith("wechat_mcp"),
                                     "import wechat_mcp names explicitly")
        allowed = {
            ("wechat_mcp.wechat_accessibility", "axvalue_to_point"),
            ("wechat_mcp.wechat_accessibility", "axvalue_to_size"),
            ("wechat_mcp.wechat_accessibility", "get_list_center"),
            ("wechat_mcp.wechat_accessibility", "post_scroll"),
            ("wechat_mcp.fetch_messages_by_chat_utils", "capture_message_area"),
            ("wechat_mcp.fetch_messages_by_chat_utils", "classify_sender_for_message"),
            ("wechat_mcp.fetch_messages_by_chat_utils", "get_messages_list"),
            ("wechat_mcp.fetch_messages_by_chat_utils", "scroll_up_small"),
            ("wechat_mcp.wechat_accessibility", "_normalize_chat_title"),
            ("wechat_mcp.wechat_accessibility", "ax_get"),
            ("wechat_mcp.wechat_accessibility", "dfs"),
            ("wechat_mcp.wechat_accessibility", "collect_chat_elements"),
            ("wechat_mcp.wechat_accessibility", "get_current_chat_name"),
            ("wechat_mcp.wechat_accessibility", "get_wechat_ax_app"),
        }
        self.assertEqual(imported, allowed)

    def test_no_send_capable_name_anywhere(self):
        banned = re.compile(r"reply_to_messages|publish_moment|add_contact|send_message|"
                            r"focus_and_type_search|send_key_with_modifiers|open_chat_for_contact")
        for path in self.SCRIPTS.glob("wechat_*.py"):
            code = "\n".join(l for l in path.read_text().splitlines()
                             if not l.lstrip().startswith("#"))
            # docstrings may explain what is banned; strip them
            code = re.sub(r'"""[\s\S]*?"""', "", code)
            self.assertIsNone(banned.search(code), path.name)

    def test_only_the_archiver_inserts_and_nothing_updates(self):
        for path in self.SCRIPTS.glob("*.py"):
            text = path.read_text()
            if '"/pages"' in text:
                self.assertEqual(path.name, "wechat_archive.py")
            if "wechat" in path.name:
                self.assertNotRegex(text, r'"(PATCH|DELETE)"', path.name)
                self.assertNotIn("/blocks", text, path.name)

    def test_reader_side_uses_the_read_token(self):
        for name in ("wechat_pull.py", "wechat_notion.py"):
            self.assertNotIn("NOTION_WECHAT_WRITE_TOKEN", (self.SCRIPTS / name).read_text())
        self.assertNotIn("NOTION_WECHAT_READ_TOKEN",
                         (self.SCRIPTS / "wechat_archive.py").read_text())


class TestRegistry(unittest.TestCase):
    def test_ids_and_properties(self):
        n = SETTINGS["notion"]
        self.assertRegex(n["database_id"], r"^[0-9a-f]{32}$")
        self.assertRegex(n["data_source_id"], r"^[0-9a-f-]{36}$")
        self.assertEqual(set(n["properties"]), {
            "title", "chat", "sender", "text", "kind", "sent_at", "archived_at",
            "sequence", "key", "gap_before", "run", "from", "to", "chat_type"})

    def test_kind_patterns_compile_and_are_known_kinds(self):
        for kind, pats in KINDS.items():
            self.assertIn(kind, {"image", "file", "voice", "video", "link", "sticker", "system"})
            for p in pats:
                re.compile(p)

    def test_env_example_documents_both_tokens(self):
        env = (REPO_ROOT / ".env.example").read_text()
        self.assertIn("NOTION_WECHAT_WRITE_TOKEN=", env)
        self.assertIn("NOTION_WECHAT_READ_TOKEN=", env)


if __name__ == "__main__":
    unittest.main()
