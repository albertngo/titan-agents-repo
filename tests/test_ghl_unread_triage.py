#!/usr/bin/env python3
"""Tests for GHL unread triage (scripts/ghl_unread_pull.py, ghl_unread_plan.py, ghl_mark_read.py).

Stdlib unittest, no pytest — matching the repo's convention.

    python3 -m unittest discover -s tests -v

What matters most, in order: the batch boundary (an automation is never "our reply", so a
question can't be buried under a reminder and a "thanks"); nothing is ever cleared that a
hold or guard should keep; plan_only and a null exception_date approve nothing; the writer
can send exactly one request with exactly one body, compare-and-swaps first and reads back
after; and only scripts/ghl_mark_read.py can write to GHL or read its token.
"""

import copy
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

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


gc = _load("ghl_client", "scripts/ghl_client.py")
glog = _load("ghl_triage_log", "scripts/ghl_triage_log.py")
pull = _load("ghl_unread_pull", "scripts/ghl_unread_pull.py")
plan = _load("ghl_unread_plan", "scripts/ghl_unread_plan.py")
mark = _load("ghl_mark_read", "scripts/ghl_mark_read.py")

REG = json.loads((REPO_ROOT / "platform-settings/ghl-unread-triage.json").read_text())
B = REG["batch"]
METHOD = (REPO_ROOT / "methods/ghl-unread-triage.md").read_text()
NOW = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)
CID = "AbCdEfGhIjKlMnOpQrSt"   # 20-char GHL id


def ts(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def m(mid, direction="inbound", mtype="TYPE_SMS", body="hi", source=None, user=None,
      status="delivered", hours_ago=1, attachments=None, meta=None, content_type="text/plain"):
    msg = {"id": mid, "direction": direction, "messageType": mtype, "body": body,
           "status": status, "dateAdded": ts(hours_ago), "contentType": content_type}
    if source:
        msg["source"] = source
    if user:
        msg["userId"] = user
    if attachments:
        msg["attachments"] = attachments
    if meta:
        msg["meta"] = meta
    return msg


def human_sms(mid, hours_ago=10, body="Here's your quote"):
    return m(mid, "outbound", body=body, source="app", user="ooPNab06Ka04uZ1yQ4w6", hours_ago=hours_ago)


def workflow_sms(mid, hours_ago=5, body="Reminder: your appointment"):
    return m(mid, "outbound", body=body, source="workflow", user="ooPNab06Ka04uZ1yQ4w6", hours_ago=hours_ago)


class FakeClient:
    """Serves conversations and pages of messages (newest first), like GHL."""

    def __init__(self, convs, messages, page_size=None):
        self.convs = {c["id"]: c for c in convs}
        self.messages = messages
        self.location_id = "LOC"
        self.page_size = page_size
        self.searches = []

    def get_json(self, path, params=None, version=None):
        params = params or {}
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[2] == "messages":
            rows = self.messages[parts[1]]
            size = self.page_size or params.get("limit", 100)
            start = 0
            if params.get("lastMessageId"):
                start = [r["id"] for r in rows].index(params["lastMessageId"]) + 1
            page = rows[start:start + size]
            return {"messages": {"messages": page, "nextPage": start + size < len(rows),
                                 "lastMessageId": page[-1]["id"] if page else None}}
        if len(parts) == 2:
            return {"conversation": self.convs[parts[1]]}
        raise AssertionError(path)

    def get_conversation(self, cid):
        return self.convs[cid]

    def search_conversations(self, since_utc, limit=100, max_pages=20, status=None, contact_id=None):
        self.searches.append({"status": status, "contact_id": contact_id})
        rows = list(self.convs.values())
        if contact_id:
            rows = [r for r in rows if r.get("contactId") == contact_id]
        if status == "unread":
            rows = [r for r in rows if r.get("unreadCount")]
        return rows

    def stats(self):
        return {"requests": 0}


def conv(cid=CID, contact="k1", unread=1, opportunities=None, name="Sarah Jones"):
    return {"id": cid, "contactId": contact, "unreadCount": unread, "contactName": name,
            "opportunities": [] if opportunities is None else opportunities,
            "lastMessageDate": ts(1), "lastMessageType": "TYPE_SMS"}


def candidate_for(messages, row=None, cache=None, page_size=None):
    row = row or conv()
    client = FakeClient([row], {row["id"]: messages}, page_size=page_size)
    return pull.candidate(client, row, REG, NOW, cache or {}, in_window=False), client


# -- registry and rubric -------------------------------------------------------------

class TestRegistry(unittest.TestCase):
    def test_pilot_state_is_pinned(self):
        # Flipping any of these is a dated vault decision; update this test in that commit.
        self.assertEqual(REG["write_mode"]["mode"], "plan_only")
        self.assertEqual(REG["policy"]["approve_verdicts"], [])
        self.assertIsNone(REG["policy"]["exception_date"])
        self.assertIsNone(REG["writer"]["_verified"])
        self.assertFalse(REG["log"]["excerpts"], "the repo is public: no customer text in the log")

    def test_vocabulary_and_cap(self):
        self.assertEqual(REG["verdicts"], ["NEEDS_RESPONSE", "ACTION", "FYI", "CLOSER", "SPAM", "UNSURE"])
        self.assertEqual(REG["clearable_verdicts"], ["CLOSER", "SPAM"])
        self.assertFalse(plan.NEVER_CLEAR & set(REG["clearable_verdicts"]))
        self.assertEqual(plan.NEVER_CLEAR | set(REG["clearable_verdicts"]), set(REG["verdicts"]))
        # Only holds the model never sees go to "to action" (rubric v3).
        self.assertEqual(set(REG["action_holds"]), {"call_in_batch", "non_text_content"})
        self.assertEqual(REG["guards"]["compliance_prefix"], "compliance:")
        self.assertEqual(REG["policy"]["max_mark_read_per_run"], 25)
        self.assertTrue(REG["policy"]["approved_by"].startswith("policy:"))
        self.assertEqual(REG["policy"]["pilot_exit"]["CLOSER"]["min_verdicts"], 50)
        self.assertEqual(REG["policy"]["pilot_exit"]["SPAM"]["min_verdicts"], 20)
        self.assertEqual(REG["age"]["flag_hours"], 24)
        self.assertEqual(REG["age"]["backlog_days"], 14)

    def test_rubric_version_matches_method_file(self):
        found = re.search(r"\*\*Rubric version: (\S+)\*\*", METHOD)
        self.assertIsNotNone(found)
        self.assertEqual(found.group(1), REG["rubric"]["version"])
        self.assertEqual(REG["rubric"]["file"], "methods/ghl-unread-triage.md")

    def test_schedule_and_log_branch(self):
        self.assertIn("CRON_TZ=America/Toronto", REG["cadence"]["cron"])
        self.assertTrue(REG["cadence"]["cron"].endswith("7-20 * * 1-6"))
        self.assertEqual(REG["log"]["branch"], "claude/ghl-triage-log")
        self.assertTrue(REG["outputs"]["cache_dir"].startswith("analysis/cache/"))
        self.assertIn("analysis/cache/", (REPO_ROOT / ".gitignore").read_text().splitlines())

    def test_writer_spec_matches_the_writer(self):
        w = REG["writer"]
        self.assertEqual(w["token_env"], mark.TOKEN_ENV)
        self.assertEqual(w["scope"], "conversations.write")
        self.assertEqual(w["method"], "PUT")
        self.assertEqual(sorted(w["body_keys"]), sorted(mark.body_for("L")))


class TestRubric(unittest.TestCase):
    SPEC_EXAMPLES = ("Sounds great, see you Thursday for the measure!", "Thanks for the quote 👍",
                     "Do you carry herringbone in oak?", "Actually can we push the install a week?",
                     "Hmm ok")

    def test_spec_rules_and_examples(self):
        for needle in self.SPEC_EXAMPLES + (
                "One open question outweighs any number of closers",
                "Never guess `CLOSER` or `SPAM`", "Customer's words only",
                "Suppliers and trade services are not spam", "An opt-out outranks everything",
                "`NEEDS_RESPONSE`", "`ACTION`", "`FYI`", "`UNSURE`", "`compliance:`"):
            self.assertIn(needle, METHOD)

    def test_albert_rulings(self):
        # v2 rulings on the first dry run, v3 on the review of run 20261008T1252-e2a9.
        rows = {line.split("|")[1].strip(): line.split("|")[2].strip()
                for line in METHOD.splitlines() if line.startswith("| ") and line.count("|") >= 4}
        def verdict_for(fragment):
            hits = [v for k, v in rows.items() if fragment in k]
            self.assertTrue(hits, fragment)
            return hits[0]
        self.assertEqual(verdict_for("A plan to follow up later"), "`FYI`")
        self.assertEqual(verdict_for("A lost or declined job"), "`FYI`")
        self.assertEqual(verdict_for("Praise, a review left, or a referral"), "`FYI`")
        self.assertEqual(verdict_for("A request to cancel"), "`ACTION`")
        self.assertEqual(verdict_for("A request to reschedule"), "`NEEDS_RESPONSE`")
        self.assertEqual(verdict_for("An opt-out"), "`ACTION`")
        self.assertEqual(verdict_for("An address"), "`ACTION`")
        self.assertEqual(verdict_for("A payment notice"), "`ACTION`")
        self.assertEqual(verdict_for("An arrival, pickup or visit notice"), "`ACTION`")
        self.assertEqual(verdict_for("Site logistics for the crew"), "`ACTION`")
        self.assertEqual(verdict_for("A bare time or date"), "`NEEDS_RESPONSE`")
        self.assertEqual(verdict_for('A bare "Ok"'), "`UNSURE`")
        self.assertEqual(verdict_for("A vague fragment"), "`UNSURE`")
        self.assertEqual(verdict_for("A stray line"), "`FYI`")
        self.assertEqual(verdict_for("A trade-service pitch"), "`FYI`")
        self.assertEqual(verdict_for("A supplier, manufacturer or distributor pitch"), "`FYI`")
        self.assertEqual(verdict_for("A cold website, SEO or lead-generation pitch"), "`SPAM`")

    def test_one_copy_only(self):
        # The two callers point at the method file; neither carries a copy (Albert's spec).
        for path in (".claude/commands/ghl-triage.md", "methods/ghl-triage-routine-prompt.md",
                     ".claude/agents/ghl-ingest-agent.md", "CLAUDE.md"):
            src = (REPO_ROOT / path).read_text()
            self.assertIn("methods/ghl-unread-triage.md", src, path)
            for ex in ("herringbone in oak", "see you Thursday for the measure"):
                self.assertNotIn(ex, src, f"{path} copies the rubric")


# -- the shared reply rule -------------------------------------------------------------

class TestKind(unittest.TestCase):
    def k(self, msg):
        return pull.kind(msg, B)

    def test_human_reply_ends_a_batch(self):
        self.assertEqual(self.k(human_sms("o1")), "boundary")
        self.assertEqual(self.k(m("o2", "outbound", "TYPE_EMAIL", "<p>hi</p>", source="app",
                                  user="u", content_type="text/html")), "boundary")

    def test_automation_never_ends_a_batch_even_with_a_user_id(self):
        self.assertEqual(self.k(workflow_sms("o1")), "automation")
        self.assertEqual(self.k(m("o2", "outbound", source="bulk_actions", user="u")), "automation")
        self.assertEqual(self.k(m("o3", "outbound", source="app")), "automation")  # no userId
        self.assertEqual(self.k(m("o4", "outbound", source="app", user="u", status="failed")), "automation")

    def test_comments_and_activity_are_invisible(self):
        self.assertEqual(self.k(m("c1", "outbound", "TYPE_INTERNAL_COMMENT", "[call-summary v1 ...]",
                                  source="app", user="u")), "ignore")
        self.assertEqual(self.k(m("a1", "outbound", "TYPE_ACTIVITY_OPPORTUNITY", "")), "ignore")

    def test_calls(self):
        connected = {"call": {"status": "completed", "duration": 120}}
        self.assertEqual(self.k(m("c1", "inbound", "TYPE_CALL", "", meta=connected)), "boundary")
        self.assertEqual(self.k(m("c2", "outbound", "TYPE_CALL", "", source="app", user="u",
                                  meta=connected)), "boundary")
        self.assertEqual(self.k(m("c3", "outbound", "TYPE_CALL", "", source="app", user="u",
                                  meta={"call": {"status": "completed", "duration": 3}})), "automation")
        self.assertEqual(self.k(m("c4", "inbound", "TYPE_CALL", "",
                                  meta={"call": {"status": "no-answer"}})), "hold:call_in_batch")
        self.assertEqual(self.k(m("c5", "inbound", "TYPE_CALL", "",
                                  meta={"call": {"status": "voicemail"}})), "hold:call_in_batch")
        self.assertEqual(self.k(m("c6", "inbound", "TYPE_IVR_CALL", "", source="workflow",
                                  meta={"call": {"status": "completed", "duration": 199}})),
                         "hold:call_in_batch")

    def test_unreadable_inbound_holds(self):
        self.assertEqual(self.k(m("i1", body="Thanks")), "text")
        self.assertEqual(self.k(m("i2", body="")), "hold:non_text_content")
        self.assertEqual(self.k(m("i3", body="paid", attachments=["https://x/y.jpg"])),
                         "hold:non_text_content")
        self.assertEqual(self.k(m("i4", "inbound", "TYPE_WHATSAPP",
                                  "Message type is currently not supported.")), "hold:non_text_content")
        self.assertEqual(self.k(m("i5", "inbound", "TYPE_SOMETHING_NEW")), "hold:unknown_message_type")
        self.assertEqual(self.k(m("i6", "inbound", "TYPE_CAMPAIGN_SMS")), "hold:unknown_message_type")

    def test_email_text_drops_the_quoted_thread(self):
        html = ("<div>Sounds good, thanks!</div><div>On Tue, Oct 7, 2026 Titan wrote:</div>"
                "<blockquote>Do you want oak?</blockquote>")
        self.assertEqual(pull.message_text(m("e1", "inbound", "TYPE_EMAIL", html,
                                             content_type="text/html")), "Sounds good, thanks!")


class TestBatch(unittest.TestCase):
    def test_the_oak_trap(self):
        # Customer asks, an automation fires, customer thanks: the batch keeps the question.
        msgs = [m("i2", body="Thanks!", hours_ago=1), workflow_sms("o2", hours_ago=2),
                m("i1", body="Do you carry oak?", hours_ago=3), human_sms("o1", hours_ago=10)]
        c, _ = candidate_for(msgs)
        self.assertEqual(c["batch"]["message_ids"], ["i1", "i2"])
        self.assertTrue(c["batch"]["has_question"])
        self.assertEqual(c["owner_by_reply"], "us")
        self.assertAlmostEqual(c["waiting_hours"], 3.0)
        self.assertIsNone(c["hold_reason"])
        self.assertEqual(c["last_message_id"], "i2")

    def test_batch_key_is_stable_and_moves_with_new_inbound(self):
        base = [m("i1", body="Great, thanks", hours_ago=2), human_sms("o1")]
        c1, _ = candidate_for(base)
        c2, _ = candidate_for(list(base))
        c3, _ = candidate_for([m("i9", body="When's install?", hours_ago=1)] + base)
        self.assertEqual(c1["batch_key"], c2["batch_key"])
        self.assertNotEqual(c1["batch_key"], c3["batch_key"])

    def test_nothing_since_our_reply_is_not_ours(self):
        c, _ = candidate_for([human_sms("o2", hours_ago=1), m("i1", body="hi", hours_ago=5)])
        self.assertEqual(c["hold_reason"], "no_customer_text")
        self.assertEqual(c["owner_by_reply"], "them")
        self.assertIsNone(c["batch_key"])

    def test_holds(self):
        c, _ = candidate_for([m("i1", body="", attachments=["x"]), m("i0", body="paid"), human_sms("o1")])
        self.assertEqual(c["hold_reason"], "non_text_content")
        long = [m(f"i{n}", body="ok", hours_ago=n + 1) for n in range(B["max_messages"] + 1)]
        c, _ = candidate_for(long + [human_sms("o1", hours_ago=40)])
        self.assertEqual(c["hold_reason"], "batch_too_long")

    def test_history_truncated(self):
        msgs = [m(f"i{n}", body="ok", hours_ago=n + 1) for n in range(8)]
        c, _ = candidate_for(msgs, page_size=1)  # 5 pages back, more remain
        self.assertEqual(c["hold_reason"], "history_truncated")
        self.assertFalse(c["stranger"])

    def test_stranger(self):
        pitch = [m("i1", body="We build websites. Want to see?"), workflow_sms("o1", hours_ago=30)]
        c, client = candidate_for(pitch)
        self.assertTrue(c["stranger"])
        self.assertIn({"status": None, "contact_id": "k1"}, client.searches)
        c, _ = candidate_for(pitch, row=conv(opportunities=[{"id": "o", "status": "open"}]))
        self.assertFalse(c["stranger"])
        c, _ = candidate_for(pitch + [human_sms("o0", hours_ago=60)])
        self.assertFalse(c["stranger"])
        other = dict(conv("ZZZZZZZZZZZZZZZZZZZZ"), unreadCount=0)
        client = FakeClient([conv(), other], {CID: pitch})
        c = pull.candidate(client, conv(), REG, NOW, {}, False)
        self.assertFalse(c["stranger"], "a contact with another conversation is not a stranger")

    def test_cache_reused_only_for_the_same_batch(self):
        msgs = [m("i1", body="Perfect, thanks"), human_sms("o1")]
        c, _ = candidate_for(msgs)
        cache = {c["batch_key"]: {"verdict": "CLOSER", "reason": "thanks", "run_id": "r"}}
        c2, _ = candidate_for(msgs, cache=cache)
        self.assertEqual(c2["cached"]["verdict"], "CLOSER")
        c3, _ = candidate_for([m("i2", body="wait, when?")] + msgs, cache=cache)
        self.assertIsNone(c3["cached"])


class TestPullRun(unittest.TestCase):
    def test_sweep_files(self):
        rows = [conv(), conv("BBBBBBBBBBBBBBBBBBBB", contact="k2", name="Bo Li")]
        msgs = {CID: [m("i1", body="Thanks so much"), human_sms("o1")],
                rows[1]["id"]: [m("j1", body="", attachments=["x"]), human_sms("o2")]}
        client = FakeClient(rows, msgs)
        with tempfile.TemporaryDirectory() as tmp:
            args = mock.Mock(mode="sweep", registry=REPO_ROOT / "platform-settings/ghl-unread-triage.json",
                             out_dir=Path(tmp) / "run", no_log=True, window_hours=24)
            doc, out = pull.run(args, client=client, now=NOW)
            cands = (out / "candidates.json").read_text()
            todo = json.loads((out / "todo.json").read_text())
        self.assertIn({"status": "unread", "contact_id": None}, client.searches)
        self.assertNotIn("Thanks so much", cands, "candidates must carry no message text")
        self.assertEqual(len(todo["batches"]), 1)  # the held one is not sent to the model
        self.assertEqual(todo["batches"][0]["messages"][0]["text"], "Thanks so much")
        self.assertNotIn("Sarah", json.dumps(todo), "the todo carries no names")
        self.assertEqual(doc["counts"]["unread_total"], 2)

    def test_refuses_ingest(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            pull.refuse_ingest_path(REPO_ROOT / "ingest" / "2026-10-08" / "x")


# -- the plan --------------------------------------------------------------------------

def cands_doc(conversations, mode="sweep", kill=None):
    return {"contract_version": "ghl-triage-candidates-1", "run_id": "20261008T1000-abcd",
            "mode": mode, "run_at": "2026-10-08T10:00:00-04:00", "rubric_version": REG["rubric"]["version"],
            "write_mode": REG["write_mode"]["mode"], "log": {"kill_switch": kill},
            "conversations": conversations}


def cand(cid, key, waiting=30.0, hold=None, has_q=False, longest=20, stranger=False, unread=True,
         cached=None):
    return {"conversation_id": cid, "contact_id": "k-" + cid, "contact": "Sam T.", "channel": "sms",
            "unread": unread, "batch_key": key, "hold_reason": hold, "waiting_hours": waiting,
            "last_message_id": "last-" + cid, "stranger": stranger, "cached": cached, "excerpt": None,
            "batch": {"has_question": has_q, "max_message_chars": longest}}


def judged(**verdicts):
    return {"contract_version": "ghl-triage-judgements-1", "rubric_version": REG["rubric"]["version"],
            "verdicts": {k: {"verdict": v, "reason": f"reason {k}"} for k, v in verdicts.items()}}


def reg_with(**policy):
    r = copy.deepcopy(REG)
    r["policy"].update(policy)
    return r


def reg_write(**policy):
    r = reg_with(**policy)
    r["write_mode"]["mode"] = "write"
    return r


class TestPlan(unittest.TestCase):
    def test_pilot_plans_nothing_to_write(self):
        p = plan.build_plan(cands_doc([cand("c1", "k1"), cand("c2", "k2", stranger=True)]),
                            judged(k1="CLOSER", k2="SPAM"), REG)
        self.assertEqual(p["actions"], [])
        self.assertEqual(p["summary"]["would_clear"], 2)
        self.assertEqual([r["disposition"] for r in p["rows"]], ["clear", "clear"])

    def test_guards_only_move_toward_a_human(self):
        p = plan.build_plan(cands_doc([
            cand("c1", "k1", has_q=True), cand("c2", "k2", longest=201), cand("c3", "k3", stranger=False),
            cand("c4", "k4", stranger=True), cand("c5", "k5")]),
            judged(k1="CLOSER", k2="CLOSER", k3="SPAM", k4="SPAM", k5="NEEDS_RESPONSE"), REG)
        got = {r["conversation_id"]: (r["verdict"], r["guard"], r["disposition"]) for r in p["rows"]}
        self.assertEqual(got["c1"], ("UNSURE", "closer_veto:question", "waiting"))
        self.assertEqual(got["c2"], ("UNSURE", "closer_veto:length", "waiting"))
        self.assertEqual(got["c3"], ("UNSURE", "spam_not_stranger", "waiting"))
        self.assertEqual(got["c4"], ("SPAM", None, "clear"))
        self.assertEqual(got["c5"], ("NEEDS_RESPONSE", None, "waiting"))

    def test_holds_and_bad_judgements(self):
        p = plan.build_plan(cands_doc([
            cand("c1", "k1", hold="call_in_batch"), cand("c2", None, hold="no_customer_text", waiting=None),
            cand("c3", "k3"), cand("c4", "k4"), cand("c5", "k5", hold="non_text_content"),
            cand("c6", "k6", hold="batch_too_long")]), judged(k4="MAYBE"), REG)
        got = {r["conversation_id"]: (r["verdict"], r["hold_reason"], r["disposition"]) for r in p["rows"]}
        self.assertEqual(got["c1"], ("HELD", "call_in_batch", "action"))
        self.assertEqual(got["c2"], ("HELD", "no_customer_text", "not_ours"))
        self.assertEqual(got["c3"], ("HELD", "unjudged", "waiting"))
        self.assertEqual(got["c4"], ("HELD", "invalid_verdict", "waiting"))
        self.assertEqual(got["c5"], ("HELD", "non_text_content", "action"))
        self.assertEqual(got["c6"], ("HELD", "batch_too_long", "waiting"))
        reasons = {r["conversation_id"]: r["reason"] for r in p["rows"]}
        self.assertEqual(reasons["c1"], REG["action_holds"]["call_in_batch"])
        self.assertEqual(reasons["c5"], REG["action_holds"]["non_text_content"])
        self.assertEqual(reasons["c6"], "")

    def test_act_and_know(self):
        p = plan.build_plan(cands_doc([cand("c1", "k1", waiting=30.0), cand("c2", "k2", waiting=30.0),
                                       cand("c3", "k3", waiting=2.0)]),
                            judged(k1="ACTION", k2="FYI", k3="FYI"), REG)
        got = {r["conversation_id"]: (r["verdict"], r["disposition"], r["age_flag"]) for r in p["rows"]}
        self.assertEqual(got["c1"], ("ACTION", "action", True))
        self.assertEqual(got["c2"], ("FYI", "fyi", False), "FYI never carries an age flag")
        s = p["summary"]
        self.assertEqual((s["action"], s["action_24h_plus"], s["fyi"], s["fyi_new_24h"]), (1, 1, 2, 1))
        self.assertEqual((s["waiting"], s["would_clear"]), (0, 0))

    def test_act_and_know_are_never_marked_read(self):
        convs = [cand("c1", "k1", stranger=True), cand("c2", "k2", stranger=True), cand("c3", "k3")]
        p = plan.build_plan(cands_doc(convs), judged(k1="ACTION", k2="FYI", k3="CLOSER"),
                            reg_with(approve_verdicts=["CLOSER", "SPAM"]))
        self.assertEqual([a["conversation_id"] for a in p["actions"]], ["c3"])
        for bad in ("ACTION", "FYI", "NEEDS_RESPONSE", "UNSURE"):
            with self.assertRaises(plan.InputError, msg=bad):
                plan.build_plan(cands_doc(convs), judged(k1="ACTION"), reg_with(approve_verdicts=[bad]))
            r = copy.deepcopy(REG)
            r["clearable_verdicts"] = ["CLOSER", "SPAM", bad]
            with self.assertRaises(plan.InputError, msg=bad):
                plan.build_plan(cands_doc(convs), judged(k1="ACTION"), r)

    def test_an_opt_out_is_always_action(self):
        j = judged(k1="CLOSER", k2="SPAM", k3="FYI", k4="ACTION")
        for k in ("k1", "k2", "k3", "k4"):
            j["verdicts"][k]["reason"] = "Compliance: opt-out, set DND"
        p = plan.build_plan(cands_doc([cand("c1", "k1"), cand("c2", "k2", stranger=True),
                                       cand("c3", "k3"), cand("c4", "k4")]), j,
                            reg_with(approve_verdicts=["CLOSER", "SPAM"]))
        got = {r["conversation_id"]: (r["verdict"], r["guard"], r["disposition"]) for r in p["rows"]}
        self.assertEqual(got["c1"], ("ACTION", "compliance", "action"))
        self.assertEqual(got["c2"], ("ACTION", "compliance", "action"))
        self.assertEqual(got["c3"], ("ACTION", "compliance", "action"))
        self.assertEqual(got["c4"], ("ACTION", None, "action"))
        self.assertEqual(p["actions"], [])
        self.assertEqual(p["summary"]["compliance"], 4)

    def test_cache_is_used_and_guards_reapplied(self):
        p = plan.build_plan(cands_doc([cand("c1", "k1", has_q=True,
                                            cached={"verdict": "CLOSER", "reason": "ok"})]), None, REG)
        r = p["rows"][0]
        self.assertEqual((r["verdict_source"], r["model_verdict"], r["verdict"]), ("cache", "CLOSER", "UNSURE"))

    def test_age_and_backlog(self):
        live = cand("c4", "k4", waiting=20 * 24)
        live["last_inbound_hours"] = 20.0  # wrote 20 days ago AND yesterday: live, not backlog
        j = judged(k1="UNSURE", k2="NEEDS_RESPONSE", k3="NEEDS_RESPONSE", k4="NEEDS_RESPONSE",
                   k5="ACTION", k6="ACTION", k7="FYI")
        j["verdicts"]["k6"]["reason"] = "compliance: opt-out, set DND"
        p = plan.build_plan(cands_doc([cand("c1", "k1", waiting=23.9), cand("c2", "k2", waiting=24.0),
                                       cand("c3", "k3", waiting=15 * 24), live,
                                       cand("c5", "k5", waiting=15 * 24), cand("c6", "k6", waiting=15 * 24),
                                       cand("c7", "k7", waiting=15 * 24),
                                       cand("c8", "k8", waiting=15 * 24, hold="call_in_batch")],
                                      mode="brief"), j, REG)
        got = {r["conversation_id"]: (r["age_flag"], r["disposition"]) for r in p["rows"]}
        self.assertEqual(got["c1"], (False, "waiting"))
        self.assertEqual(got["c2"], (True, "waiting"))
        self.assertEqual(got["c3"][1], "backlog")
        self.assertEqual(got["c4"], (True, "waiting"))
        self.assertEqual(got["c5"][1], "backlog", "a quiet to-action thread drops to the count")
        self.assertEqual(got["c6"], (True, "action"), "an opt-out is never dropped")
        self.assertEqual(got["c7"], (False, "fyi"), "FYI never becomes backlog")
        self.assertEqual(got["c8"][1], "backlog")

    def test_actions_and_the_all_or_nothing_cap(self):
        r = reg_with(approve_verdicts=["CLOSER"])
        convs = [cand(f"c{i}", f"k{i}") for i in range(25)] + [cand("x", "kx", unread=False)]
        verdicts = {f"k{i}": "CLOSER" for i in range(25)}
        verdicts["kx"] = "CLOSER"
        p = plan.build_plan(cands_doc(convs), judged(**verdicts), r)
        self.assertEqual(p["status"], "ready")
        self.assertEqual(len(p["actions"]), 25, "an already-read conversation gets no action")
        a = p["actions"][0]
        self.assertEqual(a["op"], "mark_read")
        self.assertEqual(a["expect"]["last_message_id"], "last-" + a["conversation_id"])
        again = plan.build_plan(cands_doc(convs), judged(**verdicts), r)
        self.assertEqual([x["id"] for x in again["actions"]], [x["id"] for x in p["actions"]])
        convs.append(cand("c25", "k25"))
        verdicts["k25"] = "CLOSER"
        p = plan.build_plan(cands_doc(convs), judged(**verdicts), r)
        self.assertEqual(p["status"], "needs_person")
        with self.assertRaises(LookupError):
            plan.approval_for(p, "plan.json", reg_write(approve_verdicts=["CLOSER"], exception_date="2026-11-01"))

    def test_spam_needs_its_own_switch(self):
        p = plan.build_plan(cands_doc([cand("c1", "k1", stranger=True)]), judged(k1="SPAM"),
                            reg_with(approve_verdicts=["CLOSER"]))
        self.assertEqual(p["actions"], [])

    def test_approval_refusals(self):
        convs = [cand("c1", "k1")]
        j = judged(k1="CLOSER")
        p = plan.build_plan(cands_doc(convs), j, REG)
        with self.assertRaises(PermissionError):  # plan_only: the pilot
            plan.approval_for(p, "plan.json", REG)
        w = reg_write(approve_verdicts=["CLOSER"])
        p = plan.build_plan(cands_doc(convs), j, w)
        with self.assertRaises(PermissionError):  # no dated CLAUDE.md exception yet
            plan.approval_for(p, "plan.json", w)
        ok = reg_write(approve_verdicts=["CLOSER"], exception_date="2026-11-01")
        b = plan.build_plan(cands_doc(convs, mode="brief"), j, ok)
        with self.assertRaises(PermissionError):  # brief mode never approves
            plan.approval_for(b, "plan.json", ok)
        k = plan.build_plan(cands_doc(convs, kill="raced"), j, ok)
        with self.assertRaises(PermissionError):
            plan.approval_for(k, "plan.json", ok)
        with self.assertRaises(PermissionError):
            plan.approval_for(p, "plan.json", w, approved_by="policy: me")
        a = plan.approval_for(p, "plan.json", w, approved_by="Albert, this session")
        self.assertEqual(a["approved_by"], "Albert, this session")
        a = plan.approval_for(plan.build_plan(cands_doc(convs), j, ok), "plan.json", ok)
        self.assertEqual(a["approved_by"], REG["policy"]["approved_by"])
        self.assertEqual(len(a["decisions"]), 1)

    def test_input_checks(self):
        bad = cands_doc([cand("c1", "k1")])
        bad["rubric_version"] = "0"
        with self.assertRaises(plan.InputError):
            plan.build_plan(bad, None, REG)
        j = judged(k1="CLOSER")
        j["rubric_version"] = "0"
        with self.assertRaises(plan.InputError):
            plan.build_plan(cands_doc([cand("c1", "k1")]), j, REG)

    def test_reason_is_sanitized(self):
        j = judged(k1="NEEDS_RESPONSE")
        j["verdicts"]["k1"]["reason"] = "call me at +1 (416) 555-1234 or a@b.com " + "x" * 200
        r = plan.build_plan(cands_doc([cand("c1", "k1")]), j, REG)["rows"][0]["reason"]
        self.assertNotIn("555", r)
        self.assertNotIn("a@b.com", r)
        self.assertLessEqual(len(r), REG["reason_max_chars"])

    def test_run_record_carries_no_names_or_text(self):
        p = plan.build_plan(cands_doc([cand("c1", "k1")]), judged(k1="CLOSER"), REG)
        rec = json.dumps(plan.run_record(p))
        self.assertNotIn("Sam T.", rec)
        self.assertNotIn('"contact"', rec)


# -- the writer --------------------------------------------------------------------------

def write_plan(n=1):
    acts = [{"id": f"gmr-{i:012d}", "seq": i + 1, "op": "mark_read", "conversation_id": CID,
             "contact_id": "k1", "verdict": "CLOSER", "reason": "thanks", "batch_key": "b-x",
             "expect": {"last_message_id": "last"}} for i in range(n)]
    return {"run_id": "R1", "mode": "sweep", "expires": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
            "actions": acts}


def approval(p, by=None):
    return {"run_id": p["run_id"], "plan": "x/plan.json", "approved_by": by or REG["policy"]["approved_by"],
            "decisions": [{"id": a["id"], "status": "approved"} for a in p["actions"]]}


class FakeWriter:
    def __init__(self, states, put_error=None):
        self.states = list(states)
        self.puts = []
        self.put_error = put_error

    def state(self, cid):
        return self.states.pop(0)

    def put(self, cid):
        self.puts.append(cid)
        return self.put_error


class TestWriter(unittest.TestCase):
    def test_one_request_one_body(self):
        req = mark.put_request(CID, "WRITE-TOKEN", "LOC", "2021-04-15")
        self.assertEqual(req.get_method(), "PUT")
        self.assertEqual(req.full_url, gc.BASE + "/conversations/" + CID)
        self.assertEqual(json.loads(req.data), {"locationId": "LOC", "unreadCount": 0})
        self.assertEqual(req.get_header("Authorization"), "Bearer WRITE-TOKEN")
        for bad in ("../contacts/x", "", "short", CID + "/messages"):
            with self.assertRaises(mark.Refused):
                mark.put_request(bad, "t", "LOC", "v")

    def test_put_uses_the_write_token_and_retries(self):
        seen = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout=None):
            seen.append(req)
            if len(seen) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "slow", {}, io.BytesIO(b""))
            return Resp(b"{}")

        w = mark.Writer(REG, reader=None, token="WRITE", location_id="LOC", opener=opener,
                        sleep=lambda s: None)
        self.assertIsNone(w.put(CID))
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(r.get_header("Authorization") == "Bearer WRITE" for r in seen))

    def test_preflight(self):
        p = write_plan()
        now = datetime.now(timezone.utc)
        w = reg_write(exception_date="2026-11-01")
        self.assertEqual(mark.preflight(p, approval(p), w, now, None, "tok", "x/plan.json"), [])
        self.assertTrue(mark.preflight(p, approval(p), REG, now, None, "tok", "x/plan.json"))  # plan_only
        self.assertTrue(mark.preflight(p, None, w, now, None, "tok", "x/plan.json"))
        self.assertTrue(mark.preflight(p, approval(p), reg_write(), now, None, "tok", "x/plan.json"))
        self.assertTrue(mark.preflight(p, approval(p), w, now, "kill", "tok", "x/plan.json"))
        self.assertTrue(mark.preflight(p, approval(p), w, now, None, None, "x/plan.json"))
        self.assertTrue(mark.preflight(p, approval(p), w, now + timedelta(hours=1), None, "tok", "x/plan.json"))
        bad = approval(p)
        bad["decisions"].append({"id": "gmr-not-in-plan", "status": "approved"})
        self.assertTrue(mark.preflight(p, bad, w, now, None, "tok", "x/plan.json"))
        other = approval(p)
        other["run_id"] = "R2"
        self.assertTrue(mark.preflight(p, other, w, now, None, "tok", "x/plan.json"))
        big = write_plan(26)
        self.assertTrue(mark.preflight(big, approval(big), w, now, None, "tok", "x/plan.json"))

    def run_exec(self, states, put_error=None, done=()):
        p = write_plan()
        w = FakeWriter(states, put_error)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "results.json"
            entries, code = mark.execute(p, approval(p), w, set(done), out)
            on_disk = json.loads(out.read_text())
        self.assertEqual(on_disk, entries)
        return entries, code, w

    def test_happy_path(self):
        entries, code, w = self.run_exec([(1, "last"), (0, "last")])
        self.assertEqual((code, entries[0]["result"], w.puts), (0, "executed", [CID]))
        e = entries[0]
        self.assertEqual(e["type"], "mark_conversation_read")
        self.assertEqual(e["agent"], "ghl-actions-agent")
        self.assertEqual(e["raw_ref_action_id"], write_plan()["actions"][0]["id"])

    def test_compare_and_swap_writes_nothing(self):
        entries, code, w = self.run_exec([(0, "last")])
        self.assertEqual((entries[0]["result"], entries[0]["error"], w.puts), ("refused", "stale_already_read", []))
        entries, code, w = self.run_exec([(1, "newer")])
        self.assertEqual((entries[0]["result"], entries[0]["error"], w.puts), ("refused", "stale_new_message", []))
        self.assertEqual(code, 0)

    def test_readback(self):
        entries, code, _ = self.run_exec([(1, "last"), (1, "last")])
        self.assertEqual((code, entries[0]["error"]), (5, "readback_mismatch"))
        entries, code, _ = self.run_exec([(1, "last"), (1, "newer")])
        self.assertEqual((code, entries[0]["error"]), (6, "raced_new_message"))
        entries, code, _ = self.run_exec([(1, "last")], put_error="http_422")
        self.assertEqual((code, entries[0]["result"], entries[0]["error"]), (5, "failed", "http_422"))

    def test_duplicate_is_skipped(self):
        aid = write_plan()["actions"][0]["id"]
        entries, code, w = self.run_exec([], done=[aid])
        self.assertEqual((entries[0]["result"], w.puts), ("skipped_duplicate", []))


# -- structure ---------------------------------------------------------------------------

class TestOnlyOneWriter(unittest.TestCase):
    SCRIPTS = sorted((REPO_ROOT / "scripts").glob("*.py"))

    def test_host_spelled_once(self):
        hits = [p.name for p in self.SCRIPTS if "leadconnectorhq.com" in p.read_text()]
        self.assertEqual(hits, ["ghl_client.py"])

    def test_only_the_writer_writes_to_ghl(self):
        for p in self.SCRIPTS:
            if not p.name.startswith("ghl_") or p.name == "ghl_mark_read.py":
                continue
            src = p.read_text()
            for verb in ("POST", "PUT", "PATCH", "DELETE"):
                self.assertNotIn(f'"{verb}"', src, f"{p.name} has a {verb} literal")
            self.assertNotIn("method=", src, p.name)
        src = (REPO_ROOT / "scripts/ghl_mark_read.py").read_text()
        self.assertEqual(src.count('method="PUT"'), 1)
        for verb in ("POST", "PATCH", "DELETE"):
            self.assertNotIn(f'"{verb}"', src)

    def test_only_the_writer_reads_the_write_token(self):
        for root in ("scripts", "analysis", "tests"):
            for p in (REPO_ROOT / root).rglob("*.py"):
                if p.name in ("ghl_mark_read.py", "test_ghl_unread_triage.py"):
                    continue
                src = p.read_text()
                self.assertNotIn("GHL_MARK_READ_TOKEN", src, p)
                self.assertNotIn('["token_env"]', src, p)

    def test_read_path_has_no_write_verbs(self):
        for name in ("ghl_unread_pull.py", "ghl_unread_plan.py"):
            src = (REPO_ROOT / "scripts" / name).read_text()
            self.assertNotIn("urlopen", src, name)
            self.assertNotIn("data=", src, name)

    def test_log_writer_never_forces_or_checks_out(self):
        src = (REPO_ROOT / "scripts/ghl_triage_log.py").read_text()
        for bad in ('"--force"', '"-f"', "+refs/heads/{branch(reg)}\"", '"checkout"',
                    '"reset"', '"switch"'):
            self.assertFalse(bad in src, f"ghl_triage_log.py contains {bad}")
        self.assertIn('f"{sha}:refs/heads/{branch(reg)}"', src, "pushes a sha, never with +")


class TestProse(unittest.TestCase):
    def read(self, path):
        return (REPO_ROOT / path).read_text()

    def test_command(self):
        src = self.read(".claude/commands/ghl-triage.md")
        for needle in ("write_mode", "scripts/ghl_unread_pull.py", "scripts/ghl_unread_plan.py",
                       "scripts/ghl_mark_read.py", "scripts/ghl_triage_log.py", "ghl-actions-agent",
                       "PushNotification", "scripts/publish_run.py", "todo.json"):
            self.assertIn(needle, src)

    def test_routine_prompt_is_a_pointer(self):
        src = self.read("methods/ghl-triage-routine-prompt.md")
        self.assertIn(".claude/commands/ghl-triage.md", src)
        self.assertIn(REG["cadence"]["cron"], src)

    def test_actions_agent_and_log_contract(self):
        agent = self.read(".claude/agents/ghl-actions-agent.md")
        for needle in ("`mark_conversation_read`", "scripts/ghl_mark_read.py", "stale_new_message",
                       "approval.json", "policy.exception_date"):
            self.assertIn(needle, agent)
        self.assertIn("`mark_conversation_read`", self.read("contracts/actions-log-schema.md"))
        self.assertIn("ghl-triage-approval-1", self.read("contracts/ghl-triage-schema.md"))

    def test_registry_neighbours(self):
        sales = json.loads(self.read("platform-settings/departments.json"))["departments"]["sales"]
        self.assertIn("ghl-triage", sales["owns"]["commands"])
        env = self.read(".env.example")
        self.assertIn("GHL_MARK_READ_TOKEN=", env)
        self.assertIn("conversations.write", env)
        pub = _load("publish_run", "scripts/publish_run.py")
        self.assertIn(REG["log"]["branch"], pub.NEVER_PUBLISH)

    def test_claude_md_and_ingest_agent(self):
        claude = self.read("CLAUDE.md")
        for needle in ("/ghl-triage", "methods/ghl-unread-triage.md", "claude/ghl-triage-log",
                       "Designed, not in force"):
            self.assertIn(needle, claude)
        agent = self.read(".claude/agents/ghl-ingest-agent.md")
        for needle in ("scripts/ghl_unread_pull.py --mode brief", "unanswered-24h+", "triage-closer",
                       "`triage`", "never marks anything read", "triage-action", "action-24h+",
                       "triage-compliance", "triage-fyi", "`fyi_new_24h`"):
            self.assertIn(needle, agent)
        ext = json.loads(self.read("ingest/SAMPLE/ghl.json"))["extensions"]["ghl"]
        self.assertIn("triage", ext)
        self.assertIn("triage", ext["conversations"][0])


if __name__ == "__main__":
    unittest.main()
