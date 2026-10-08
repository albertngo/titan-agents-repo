#!/usr/bin/env python3
"""Tests for call-recording transcription (scripts/ghl_client.py, scripts/ghl_calls_pull.py).

Stdlib unittest, no pytest — matching the repo's stdlib-first script convention.

    python3 -m unittest discover -s tests -v

The structural tests matter most. ghl_client.py is the only path to GHL and must
stay GET-only (same job tests/test_lightspeed.py does for "the read path contains no
write verb"); the pull script must never write under the daily ingest folder, which
the orchestrator reads wholesale; and transcripts must never reach a committed file.
"""

import csv
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
import wave
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
gp = _load("ghl_calls_pull", "scripts/ghl_calls_pull.py")
CFG = gp.load_registry()
T0 = datetime(2026, 10, 1, 13, 0, 0, tzinfo=timezone.utc)


def make_wav(channels=1, rate=8000, seconds=1.0):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * channels * int(rate * seconds))
    return buf.getvalue()


def msg(mid="m1", status="completed", duration=120, when=T0, direction="inbound", top_level=False):
    m = {"id": mid, "conversationId": "c1", "contactId": "k1", "messageType": "TYPE_CALL",
         "direction": direction, "userId": "ooPNab06Ka04uZ1yQ4w6",
         "dateAdded": when.isoformat().replace("+00:00", "Z")}
    if top_level:
        m.update(status=status, callDuration=duration)
    else:
        m["meta"] = {"call": {"status": status, "duration": duration}}
    return m


class FakeResp(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestNoWritePath(unittest.TestCase):
    def test_client_has_no_write_verbs(self):
        src = (REPO_ROOT / "scripts/ghl_client.py").read_text()
        for verb in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertNotIn(f'"{verb}"', src, f"ghl_client.py contains a {verb} literal")
        self.assertNotIn("method=", src, "ghl_client.py passes an explicit HTTP method")
        self.assertNotIn("data=", src, "ghl_client.py sends a request body")

    def test_client_requests_are_get(self):
        cl = gc.GhlClient(token="t", location_id="L")
        self.assertEqual(cl._request("https://x/y", "application/json", None).get_method(), "GET")

    def test_client_retries_a_dropped_connection(self):
        # 2026-10-08 15:59: one RemoteDisconnected mid-pull killed the whole triage sweep.
        import http.client

        class Resp(io.BytesIO):
            headers = {}
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        for exc in (http.client.RemoteDisconnected("closed"), ConnectionResetError("reset"),
                    TimeoutError("read timed out"), http.client.IncompleteRead(b"")):
            calls = []
            def opener(req, timeout=None, exc=exc):
                calls.append(1)
                if len(calls) == 1:
                    raise exc
                return Resp(b'{"ok": true}')
            cl = gc.GhlClient(token="t", location_id="L", min_interval=0, opener=opener)
            with mock.patch.object(gc.time, "sleep"):
                self.assertEqual(cl.get_json("/x"), {"ok": True}, type(exc).__name__)
            self.assertEqual(len(calls), 2)

        def always(req, timeout=None):
            raise http.client.RemoteDisconnected("closed")
        cl = gc.GhlClient(token="t", location_id="L", min_interval=0, max_retries=3, opener=always)
        with mock.patch.object(gc.time, "sleep"), self.assertRaises(gc.GhlError):
            cl.get_json("/x")

    def test_pull_reaches_ghl_only_through_the_client(self):
        src = (REPO_ROOT / "scripts/ghl_calls_pull.py").read_text()
        self.assertNotIn("leadconnectorhq.com", src)
        self.assertIn("import ghl_client", src)

    def test_nothing_lands_in_ingest(self):
        src = (REPO_ROOT / "scripts/ghl_calls_pull.py").read_text()
        self.assertNotIn('"ingest/', src)
        for key in ("cache_dir", "run_file"):
            self.assertTrue(CFG["outputs"][key].startswith("analysis/cache/ghl-calls"))
        self.assertTrue(CFG["bakeoff"]["output"].startswith("analysis/cache/ghl-calls"))
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr", io.StringIO()):
                gp.refuse_ingest_path(REPO_ROOT / "ingest" / "2026-10-01" / "calls.json")

    def test_cache_is_gitignored(self):
        self.assertIn("analysis/cache/", (REPO_ROOT / ".gitignore").read_text().splitlines())


class TestRegistry(unittest.TestCase):
    def test_keys_and_caps(self):
        self.assertEqual(CFG["window_hours"], 24)
        self.assertEqual(CFG["min_duration_seconds"], 8)
        self.assertEqual(CFG["max_calls_per_run"], 40)
        self.assertEqual(CFG["max_minutes_per_run"], 120)
        self.assertEqual(CFG["transcribe_statuses"], ["completed", "voicemail"])
        self.assertTrue(CFG["fallback_to_ghl_transcription"])
        self.assertTrue(CFG["prefer_note"])

    def test_engine_decision(self):
        """Albert, 2026-10-02: ElevenLabs Scribe v2 locked in, Deepgram dropped."""
        self.assertEqual(CFG["engine"]["default"], "elevenlabs")
        self.assertEqual(CFG["engine"]["_locked_in"], "2026-10-02")
        self.assertEqual(CFG["engine"]["elevenlabs"]["model_id"], "scribe_v2")
        self.assertNotIn("deepgram", CFG["engine"])
        self.assertNotIn("deepgram", gp.ENGINES)
        self.assertNotIn("channel_map", CFG)
        for name in gp.ENGINES:
            self.assertIn("env_var", CFG["engine"][name])
            self.assertIn(name, CFG["keyterms"]["cap_by_engine"])

    @staticmethod
    def _walk(flow):
        """Every module in execution order, router routes included."""
        for m in flow:
            yield m
            for route in m.get("routes") or []:
                yield from TestRegistry._walk(route["flow"])

    def _snapshot(self):
        sc = CFG["make_scenarios"]["call_notes"]
        snap = json.loads((REPO_ROOT / sc["blueprint"]).read_text())
        snap["all"] = list(self._walk(snap["blueprint"]["flow"]))
        return sc, snap, {m["id"]: m for m in snap["all"]}

    def test_make_scenario_entry(self):
        sc, snap, mods = self._snapshot()
        self.assertEqual(sc["team_id"], 459654)
        self.assertEqual(sc["writes"], ["GHL contact note", "GHL internal comment"])
        self.assertTrue(sc["isActive"])  # live since 2026-10-02 14:17 UTC
        for k in ("id", "hook_id"):
            self.assertTrue(sc[k] is None or isinstance(sc[k], int))
        self.assertEqual(snap["scenario_id"], sc["id"])
        self.assertEqual(mods[1]["parameters"]["hook"], sc["hook_id"])
        # Every GHL read goes through the read key: Make's GHL connection has no
        # conversations scope (401 on /conversations/search, 2026-10-02).
        for mid in (2, 3, 7, 19):
            self.assertEqual(mods[mid]["module"], "http:MakeRequest")
            self.assertEqual(mods[mid]["parameters"]["apiKeyKeychain"], sc["keychains"]["ghl_read_pit"])
            self.assertEqual(mods[mid]["mapper"]["method"], "get")
        self.assertEqual(mods[8]["parameters"]["apiKeyKeychain"], sc["keychains"]["elevenlabs"])
        ids = [m["id"] for m in snap["all"]]
        self.assertEqual(len(ids), len(set(ids)))
        # The GHL connection writes notes and nothing else.
        conn = [m["id"] for m in snap["all"]
                if (m.get("parameters") or {}).get("__IMTCONN__") == sc["ghl_connection_id"]]
        self.assertEqual(conn, [14, 44])  # transcript notes, translation notes
        self.assertEqual(mods[14]["module"], "highlevel:addNotetoContact")
        self.assertIn("[call-note v2 messageId={{4.id}}", mods[14]["mapper"]["body"])
        # Make formula regexes must be quoted strings; a bare /…[…]/ fails "Unexpected [".
        self.assertNotIn("; /", mods[9]["mapper"]["variables"][0]["value"])
        self.assertTrue(snap["blueprint"]["metadata"]["scenario"]["sequential"])
        sent = [f["value"] for f in mods[8]["mapper"]["multipartBodyContent"] if f["name"] == "keyterms"]
        published = json.loads((REPO_ROOT / CFG["keyterms"]["published_file"]).read_text())["terms"]
        self.assertEqual(sent, published, "module 8's keyterm fields drifted from the published list")

    def test_summary_model_by_call_length(self):
        """Albert, 2026-10-02: Haiku for short calls, Sonnet for long ones."""
        sc, snap, mods = self._snapshot()
        rule = sc["summary_model"]
        router = mods[30]
        self.assertEqual(router["module"], "builtin:BasicRouter")
        short, long_, rest = (r["flow"] for r in router["routes"])
        self.assertEqual([m["id"] for m in short], [10, 31])
        self.assertEqual([m["id"] for m in long_], [21, 32])
        self.assertEqual(rest[0]["id"], 33)  # the continuation route runs after both
        self.assertEqual(mods[10]["mapper"]["model"], rule["short"])
        self.assertEqual(mods[21]["mapper"]["model"], rule["long"])
        self.assertEqual(mods[10]["mapper"]["textPrompt"], mods[21]["mapper"]["textPrompt"])
        for mid, op in ((10, "number:less"), (21, "number:greaterorequal")):
            groups = mods[mid]["filter"]["conditions"]
            self.assertEqual(len(groups), 1)
            self.assertIn({"a": "{{4.meta.call.duration}}", "b": str(rule["long_from_seconds"]), "o": op}, groups[0])
            self.assertIn({"a": "{{9.transcript}}", "o": "exist"}, groups[0])
        for mid, src in ((31, 10), (32, 21)):
            self.assertEqual(mods[mid]["module"], "util:SetVariable2")
            self.assertEqual(mods[mid]["mapper"]["name"], "call_summary")
            self.assertEqual(mods[mid]["mapper"]["value"], "{{4.id}}|||{{%d.result}}" % src)
        self.assertEqual(mods[33]["module"], "util:GetVariable2")
        self.assertEqual(mods[33]["mapper"]["name"], "call_summary")
        # A summary is only used by the call it was written for.
        self.assertEqual(mods[11]["filter"]["conditions"],
                         [[{"a": "{{33.call_summary}}", "b": "{{4.id}}|||", "o": "text:startwith"}]])
        body11 = json.dumps(mods[11]["mapper"])
        self.assertNotIn("10.result", body11)
        self.assertNotIn("21.result", body11)

    def test_language_detection_and_translation(self):
        """Albert, 2026-10-02: detect the language; English summary; full English translation."""
        sc, snap, mods = self._snapshot()
        lang = sc["language"]
        fields = [f["name"] for f in mods[8]["mapper"]["multipartBodyContent"]]
        self.assertNotIn("language_code", fields)  # Scribe detects it
        v9 = {v["name"]: v["value"] for v in mods[9]["mapper"]["variables"]}
        for code in lang["english_codes"]:
            self.assertIn(f'"{code}"; "yes"', v9["is_english"])
        self.assertTrue(v9["is_english"].endswith('; "no")}}'))
        for code, name in (("vie", "Vietnamese"), ("cmn", "Mandarin"), ("yue", "Cantonese"), ("fas", "Farsi")):
            self.assertIn(f'"{code}"; "{name}"', v9["lang_name"])
        for mid in (10, 21):
            self.assertIn("write everything below in English", mods[mid]["mapper"]["textPrompt"])
        # Router 40: route 1 is the comment, route 2 the translation — independent.
        a, b = (r["flow"] for r in mods[40]["routes"])
        self.assertEqual([m["id"] for m in a], [45, 18, 19, 20, 47, 46])  # gate, read-back, alarm
        self.assertEqual([m["id"] for m in b], [41, 42, 43, 44])
        self.assertEqual(mods[41]["mapper"]["model"], lang["translation"]["model"])
        self.assertEqual(mods[41]["mapper"]["max_tokens"], lang["translation"]["max_tokens"])
        self.assertEqual(mods[41]["filter"]["conditions"],
                         [[{"a": "{{9.is_english}}", "b": "no", "o": "text:equal"}]])
        self.assertIn("[call-translation v1 messageId={{4.id}} ref={{11.ref}} lang={{9.lang}}",
                      mods[44]["mapper"]["body"])
        # The translation route never touches the comment key or the messages endpoint.
        for m in b:
            self.assertNotEqual((m.get("parameters") or {}).get("apiKeyKeychain"), sc["keychains"]["ghl_internal_comment"])
        # A Language line in the transcript header is not read as a transcript line.
        body = ("Transcript · Ref C-1001-0902 · Thu Oct 1, 9:02 am · Inbound · 3m 32s · Staff\n"
                "Speakers: Speaker 1 = Staff (Titan) · Speaker 2 = customer\n"
                "Language: Vietnamese (English translation in Notes)\n"
                "[00:01] Speaker 1: Xin chào\n\n[call-note v2 messageId=m1 conversationId=c1 "
                "engine=scribe_v2 ref=C-1001-0902 part=1/1]")
        p = gp.parse_call_note([body])
        self.assertEqual(len(p["utterances"]), 1)
        self.assertEqual(p["language_name"], "Vietnamese")

    def test_staff_rule(self):
        """Albert, 2026-10-02: a person's own GHL user -> that name; the shared Front Desk
        line -> a roster name only if said on the call; otherwise 'Staff'."""
        sc, snap, mods = self._snapshot()
        staff = CFG["staff"]
        people = json.loads((REPO_ROOT / "platform-settings/notion-destinations.json").read_text())["people"]
        named = {p["ghl_user_id"]: p["name"] for k, p in people.items()
                 if isinstance(p, dict) and p.get("ghl_user_id") and "bot" not in p["name"].lower()
                 and p["ghl_user_id"] not in staff["shared_line_user_ids"]}
        ghl_user = [v["value"] for v in mods[9]["mapper"]["variables"] if v["name"] == "ghl_user"][0]
        for uid, name in named.items():
            self.assertIn(f'"{uid}"; "{name}"', ghl_user)
        for uid in staff["shared_line_user_ids"]:
            self.assertNotIn(uid, ghl_user)  # the shared line never names a person
        self.assertTrue(ghl_user.endswith('; "")}}'))
        rule = [v["value"] for v in mods[11]["mapper"]["variables"] if v["name"] == "staff"][0]
        self.assertTrue(rule.startswith("{{ifempty(9.ghl_user; switch("))
        self.assertTrue(rule.endswith(f'; "{staff["default"]}"))}}}}'))
        for name in staff["roster"]:
            self.assertIn(f'"{name}"; "{name}"', rule)
            self.assertIn(name, mods[10]["mapper"]["textPrompt"])
            self.assertIn(name, json.loads((REPO_ROOT / CFG["keyterms"]["published_file"]).read_text())["terms"])

    def _module11_staff(self, mods):
        """Module 11's Staff rule, emulated: the line-start regex, then the roster switch."""
        rule = [v["value"] for v in mods[11]["mapper"]["variables"] if v["name"] == "staff"][0]
        pattern = re.search(r'"/(\^\[\\s\\S\]\*\?\(\?:\^\|\\n\)Staff:[^"]*)/"', rule).group(1)
        roster = set(CFG["staff"]["roster"])

        def staff_of(output, ghl_user=""):
            if ghl_user:
                return ghl_user
            got = re.sub(pattern, r"\1", output).strip()
            return got if got in roster else CFG["staff"]["default"]
        return staff_of

    def test_staff_name_needs_evidence(self):
        """Albert, 2026-10-02: 'Joey is the one that talked as staff. Why was Pourya made as
        the staff?', then: 'Front desk is a general staff. Only IF the context explicitly has
        us saying this is Joey … then you can name the staff.' Only a self-introduction is
        evidence; the model quotes it first, and module 11 reads Staff only at a line start."""
        sc, snap, mods = self._snapshot()
        ev = CFG["staff"]["evidence_line"]
        prompt = mods[10]["mapper"]["textPrompt"]
        self.assertLess(prompt.index(ev), prompt.index("\nStaff: <"))
        self.assertLess(prompt.index("\nStaff: <"), prompt.index("\nRoles: <"))
        self.assertNotIn("\nSpeakers: <", prompt)
        for rule in ("the Titan person introduces themselves by name", "not the customer using a name",
                     'calls out or asks for while getting a colleague ("Pourya?"', '"D for David"',
                     "not a guess that the call was passed to someone", '"Titan staff" if it says Staff'):
            self.assertIn(rule, prompt)
        staff_of = self._module11_staff(mods)
        self.assertEqual(staff_of('Name evidence: none ("Pourya?" is a colleague)\n\nStaff: Staff\n'
                                  'Roles: Speaker 1 = staff\nSummary\nx'), "Staff")
        self.assertEqual(staff_of('Name evidence: not Staff: Pourya\nStaff: Staff\nSummary\nx'), "Staff")
        self.assertEqual(staff_of('Name evidence: "this is Joey"\n\nStaff: Joey\nSummary\nx'), "Joey")
        self.assertEqual(staff_of("Staff: <the name was not said>\nSummary\nx"), "Staff")
        self.assertEqual(staff_of("Summary\nNo conversation recorded."), "Staff")
        self.assertEqual(staff_of("Staff: Joey\nSummary\nx", ghl_user="Pourya"), "Pourya")

    def test_transcript_role_labels(self):
        """Albert, 2026-10-02: 'make it perfectly clear speaker 1 and speaker 2 is? Customer vs
        staff(name) if apparent'. The model's Roles line becomes a label on every transcript
        line; a name only where the Staff line already has it (staff.labels)."""
        sc, snap, mods = self._snapshot()
        roster = CFG["staff"]["roster"]
        v11 = {v["name"]: v["value"] for v in mods[11]["mapper"]["variables"]}
        v12 = {v["name"]: v["value"] for v in mods[12]["mapper"]["variables"]}
        self.assertNotIn("speakers", v11)
        self.assertNotIn("Speakers:", v12["note_head"])
        # staff_label: a person's own line names them; anything else is plain Staff.
        sl = v11["staff_label"]
        self.assertTrue(sl.startswith("{{switch(9.ghl_user; ") and sl.endswith('; "Staff")}}'))
        sl_cases = dict(re.findall(r'"(\w+)"; "(Staff \(\w+\))"', sl))
        self.assertEqual(sl_cases, {x: f"Staff ({x})" for x in roster})
        staff_of = self._module11_staff(mods)

        def role_of(n, output):  # module 11 role_N, emulated
            pat = re.search(r'"/(\^.*?Roles:.*?)/"; "\$1"', v11[f"role_{n}"]).group(1)
            return re.sub(r"[()]", "", re.sub(pat, r"\1", output)).strip().lower()

        def label_of(n, role, staff, staff_label):  # module 12 lab_N, emulated
            expr = v12[f"lab_{n}"]
            self.assertTrue(expr.startswith(f"] {{{{switch(11.role_{n}; ") and
                            expr.endswith(f'; "Speaker {n}")}}}}:'))
            for key, named, name, plain in re.findall(
                    r'"([a-z ]+)"; (?:if\(11\.staff = "(\w+)"; "([^"]+)"; 11\.staff_label\)|11\.staff_label|"([^"]+)")',
                    expr):
                if key == role:
                    return name if named and staff == named else (plain or staff_label)
            return f"Speaker {n}"

        def notes_for(output, ghl_user=""):  # modules 11, 12, 34: the relabelled transcript
            staff = staff_of(output, ghl_user)
            staff_label = sl_cases.get(ghl_user, "Staff")
            labs = {n: f"] {label_of(n, role_of(n, output), staff, staff_label)}:" for n in (1, 2, 3)}
            tx = "[00:02] Speaker 1: Good morning.\n[00:04] Speaker 2: Hi.\n[00:09] Speaker 3: Yes."
            chain = mods[34]["mapper"]["variables"][0]["value"]
            for n in (1, 2, 3):
                self.assertIn(f'"] Speaker {n}:"; 12.lab_{n})', chain)
                tx = tx.replace(f"] Speaker {n}:", labs[n])
            return [u["speaker"] for u in gp._utterances(tx)]

        front = "Name evidence: none\n\nStaff: Staff\n\nRoles: Speaker 1 = staff · Speaker 2 = customer"
        self.assertEqual(notes_for(front + " · Speaker 3 = other\nSummary\nx"), ["Staff", "Customer", "Other"])
        self.assertEqual(notes_for(front + "\nSummary\nx"), ["Staff", "Customer", "Speaker 3"])
        self.assertEqual(notes_for('Name evidence: "this is Joey"\nStaff: Joey\n'
                                   "Roles: Speaker 1 = Staff (Joey), Speaker 2 = Customer\nSummary\nx"),
                         ["Staff (Joey)", "Customer", "Speaker 3"])
        # A named role the Staff line does not carry stays plain Staff (no slip-through).
        self.assertEqual(notes_for("Name evidence: none\nStaff: Staff\n"
                                   "Roles: Speaker 1 = staff Pourya · Speaker 2 = customer\nSummary\nx"),
                         ["Staff", "Customer", "Speaker 3"])
        # A person's own line: certain, whatever the model wrote.
        self.assertEqual(notes_for(front + "\nSummary\nx", ghl_user="Pourya"),
                         ["Staff (Pourya)", "Customer", "Speaker 3"])
        self.assertEqual(notes_for("Summary\nNo conversation recorded."), ["Speaker 1", "Speaker 2", "Speaker 3"])
        # Every vocabulary word the registry documents is a case in the switch.
        for key in ("customer", "caller", "other", "staff"):
            self.assertIn(f'"{key}"; ', v12["lab_1"])
        # Notes and the translation both read the labelled text; parts split it evenly.
        route3 = [m["id"] for m in mods[30]["routes"][2]["flow"]]
        self.assertLess(route3.index(12), route3.index(34))
        self.assertLess(route3.index(34), route3.index(13))
        body = mods[14]["mapper"]["body"]
        self.assertIn("{{substring(34.tx; (13.i - 1) * ceil(length(34.tx) / 11.n_parts); "
                      "13.i * ceil(length(34.tx) / 11.n_parts))}}", body)
        self.assertNotIn("9.transcript", body)
        self.assertTrue(mods[41]["mapper"]["textPrompt"].endswith("{{34.tx}}"))

    def test_comment_gate(self):
        """Albert, 2026-10-02: internal comments only, with a barrier against any slip.
        Every layer of make_scenarios.call_notes.comment_gate, checked on the snapshot."""
        sc, snap, mods = self._snapshot()
        gate = sc["comment_gate"]
        key = sc["keychains"]["ghl_internal_comment"]
        flow = snap["all"]
        order = [m["id"] for m in flow]
        # 1. The comment key is used by one module, in this and every other snapshot.
        users = [m["id"] for m in flow if (m.get("parameters") or {}).get("apiKeyKeychain") == key]
        self.assertEqual(users, [gate["module"]])
        for other in (REPO_ROOT / "platform-settings/blueprints").glob("*.json"):
            if other.name != Path(sc["blueprint"]).name:
                self.assertNotIn(f'"apiKeyKeychain": {key}', other.read_text(), other.name)
        self.assertNotIn(key, (sc["keychains"]["ghl_read_pit"], sc["keychains"]["elevenlabs"]))
        # Nothing else in the scenario can post to the messages endpoint.
        posters = [m["id"] for m in flow if m["module"] == "http:MakeRequest"
                   and "/conversations/messages" in m["mapper"]["url"] and m["mapper"]["method"] != "get"]
        self.assertEqual(posters, [gate["module"]])
        post = mods[gate["module"]]
        # 5. Literal URL, POST, no redirects, body is exactly the gate variable.
        self.assertEqual(post["mapper"]["url"], gate["url"])
        self.assertEqual(post["mapper"]["method"], "post")
        self.assertFalse(post["mapper"]["allowRedirects"])
        self.assertEqual(post["mapper"]["inputMethod"], "jsonString")
        self.assertEqual(post["mapper"]["jsonStringBodyContent"], "{{16.comment_body}}")
        # 3. The comment text is JSON-encoded by Make before it is spliced in.
        self.assertEqual(mods[15]["module"], "json:TransformToJSON")
        self.assertEqual(mods[15]["mapper"]["object"], "{{12.comment_text}}")
        # 2. The body template: literal type, last key, only two placeholders.
        body = mods[16]["mapper"]["variables"][0]["value"]
        self.assertEqual(body, '{"contactId":"{{4.contactId}}","message":{{15.json}},'
                               '"mentions":[],"type":"' + gate["type"] + '"}')
        self.assertEqual(re.findall(r"\{\{[^}]*\}\}", body), ["{{4.contactId}}", "{{15.json}}"])
        # 4. One AND group (no OR path around it) holding the exact-body pattern.
        groups = post["filter"]["conditions"]
        self.assertEqual(len(groups), 1)
        cond = [c for c in groups[0] if c["a"] == "{{16.comment_body}}"]
        self.assertEqual(len(cond), 1)
        self.assertEqual((cond[0]["o"], cond[0]["b"]), ("text:pattern", gate["body_regex"]))
        # The call is recorded BEFORE the comment, then again with the read-back type.
        self.assertLess(order.index(17), order.index(gate["module"]))
        self.assertEqual(mods[17]["mapper"]["data"]["comment"], "pending")
        self.assertEqual(mods[20]["mapper"]["data"]["comment"], "posted")
        self.assertIn("19.data", mods[20]["mapper"]["data"]["comment_type"])
        self.assertIn("{{18.data.messageId}}", mods[19]["mapper"]["url"])

    def test_instant_alarm_and_kill_switch(self):
        """Albert, 2026-10-02: an instant alarm if a summary is ever not an internal comment."""
        sc, snap, mods = self._snapshot()
        alarm = sc["comment_gate"]["alarm"]
        route = [m["id"] for m in mods[40]["routes"][0]["flow"]]
        self.assertEqual(route, [45, 18, 19, 20, 47, 46])
        # The kill switch is read before every post and is part of the gate's one AND group.
        self.assertEqual(mods[45]["module"], "datastore:ExistRecord")
        self.assertEqual(mods[45]["mapper"]["key"], alarm["kill_switch_key"])
        self.assertIn({"a": "{{45.exist}}", "b": "false", "o": "boolean:equal"},
                      mods[18]["filter"]["conditions"][0])
        # On a read-back that is not an internal comment: trip the switch first, then alert.
        readback = "{{ifempty(19.data.message.messageType; 19.data.messageType)}}"
        self.assertEqual(mods[47]["mapper"]["key"], alarm["kill_switch_key"])
        self.assertEqual(mods[47]["filter"]["conditions"],
                         [[{"a": readback, "b": "TYPE_INTERNAL_COMMENT", "o": "text:notequal"}]])
        self.assertEqual(mods[46]["module"], "two-chat:WhatsappSendMessage")
        self.assertIn("ALARM", mods[46]["mapper"]["text"])
        self.assertIn("{{4.contactId}}", mods[46]["mapper"]["text"])
        # Phone numbers never reach this public repo.
        text = (REPO_ROOT / sc["blueprint"]).read_text()
        self.assertIsNone(re.search(r"\+1\d{10}", text))

    def test_comment_gate_regex(self):
        """The same pattern Make applies, on bodies built the way Make builds them."""
        gate = re.compile(CFG["make_scenarios"]["call_notes"]["comment_gate"]["body_regex"])

        def body(cid, text, tail='"mentions":[],"type":"InternalComment"}'):
            return '{"contactId":"%s","message":%s,%s' % (cid, json.dumps(text, ensure_ascii=False), tail)
        cid = "jMaagJIOI8l6kL2BFHgf"
        summary = gp.render_call_summary('Wants "Aquaplus" LVP \\ $3.49/sf.', ["Us: quote — by Fri"],
                                         {"ref": "C-1001-1432", "message_id": "m1",
                                          "call_line": "Thu Oct 1, 2:32 pm · Outbound · 9m 30s · Helen"})
        allowed = [body(cid, summary), body(cid, 'x","type":"SMS","toNumber":"+14165550000'), body(cid, "")]
        blocked = [
            '{"contactId":"%s","message":"x","type":"SMS","mentions":[],"type":"InternalComment"}' % cid,
            body(cid, "hi", '"mentions":[],"type":"SMS"}'),
            body(cid, "hi", '"mentions":[],"type":"Email"}'),
            body(cid, "hi", '"mentions":[],"type":"InternalComment","toNumber":"+14165550000"}'),
            body(cid, "hi", '"mentions":[],"emailTo":"a@b.c","type":"InternalComment"}'),
            body(cid, "hi", '"mentions":["u1"],"type":"InternalComment"}'),
            body('k1","type":"SMS', "hi"),
            body("", "hi"),
        ]
        for b in allowed:
            self.assertRegex(b, gate)
            self.assertEqual(json.loads(b)["type"], "InternalComment")  # an escaped injection stays text
        for b in blocked:
            self.assertIsNone(gate.match(b), b)

    def test_env_example_declares_engine_key(self):
        env = (REPO_ROOT / ".env.example").read_text()
        self.assertIn(CFG["engine"]["elevenlabs"]["env_var"] + "=", env)
        self.assertNotIn("DEEPGRAM_API_KEY", env)


class TestGating(unittest.TestCase):
    def test_status_from_either_location(self):
        self.assertEqual(gp.call_status_of(msg(status="Completed")), "completed")
        self.assertEqual(gp.call_status_of(msg(status="voicemail", top_level=True)), "voicemail")
        self.assertEqual(gp.call_duration_of(msg(duration=42, top_level=True)), 42)
        self.assertIsNone(gp.call_status_of({"id": "x"}))

    def test_gate(self):
        self.assertEqual(gp.gate(msg(status="no-answer"), CFG)[0], "none")
        self.assertEqual(gp.gate({"id": "x"}, CFG)[0], "none")
        self.assertEqual(gp.gate(msg(duration=5), CFG)[0], "skipped-short")
        self.assertEqual(gp.gate(msg(duration=8), CFG)[0], "transcribe")
        self.assertEqual(gp.gate(msg(status="voicemail", duration=30), CFG)[0], "transcribe")

    def test_caps(self):
        b = gp.Budget(CFG)
        decisions = [gp.gate(msg(f"m{i}", duration=60), CFG, b)[0] for i in range(41)]
        self.assertEqual(decisions.count("transcribe"), 40)
        self.assertEqual(decisions[-1], "over-cap")
        b = gp.Budget(CFG)
        self.assertEqual(gp.gate(msg(duration=119 * 60), CFG, b)[0], "transcribe")
        self.assertEqual(gp.gate(msg(duration=120), CFG, b)[0], "over-cap")
        self.assertEqual(gp.Budget(CFG, limit=3).max_calls, 3)
        self.assertEqual(gp.Budget(CFG, limit=999).max_calls, 40)

    def test_window_bounds(self):
        since, until = T0, T0 + timedelta(hours=1)
        self.assertTrue(gp.in_window(msg(when=since), since, until))
        self.assertFalse(gp.in_window(msg(when=until), since, until))
        s, u = gp.compute_window(hours=24, cfg=CFG, now=T0)
        self.assertEqual(u - s, timedelta(hours=24))

    def test_epoch_ms_and_iso(self):
        self.assertEqual(gc.parse_ts(int(T0.timestamp() * 1000)), T0)
        self.assertEqual(gc.parse_ts("2026-10-01T13:00:00.000Z"), T0)
        self.assertIsNone(gc.parse_ts(""))


class TestListing(unittest.TestCase):
    def test_type_filter_is_client_side(self):
        cl = mock.Mock()
        cl.search_conversations.return_value = [{"id": "c1", "contactId": "k1"}]
        sms = dict(msg("s1"), messageType="TYPE_SMS")
        cl.list_messages.return_value = [msg("m2", when=T0 + timedelta(minutes=5)), sms, msg("m1"),
                                         msg("old", when=T0 - timedelta(days=3))]
        calls, scan = gp.list_call_messages(cl, CFG, T0 - timedelta(hours=1), T0 + timedelta(hours=1))
        self.assertEqual([c["id"] for c in calls], ["m1", "m2"])
        self.assertEqual(scan["messages_scanned"], 4)


class TestWav(unittest.TestCase):
    def test_stereo_header(self):
        self.assertEqual(gp.wav_info(make_wav(channels=2))["channels"], 2)

    def test_pcm_header(self):
        info = gp.wav_info(make_wav(channels=1, seconds=2))
        self.assertEqual((info["container"], info["channels"], info["sample_rate"], info["format_tag"]),
                         ("riff", 1, 8000, 1))
        self.assertAlmostEqual(info["duration_s"], 2.0)

    def test_mulaw_header_parsed_by_hand(self):
        import struct
        body = b"\xff" * 8000
        fmt = struct.pack("<HHIIHH", 7, 1, 8000, 8000, 1, 8)
        data = b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(body)) + b"WAVE" + \
            b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(body)) + body
        info = gp.wav_info(data)
        self.assertEqual((info["format_tag"], info["channels"], info["duration_s"]), (7, 1, 1.0))

    def test_garbage(self):
        self.assertEqual(gp.wav_info(b"not audio")["container"], "unknown")
        self.assertEqual(gp.wav_info(b"")["bytes"], 0)


class TestEngines(unittest.TestCase):
    def capture(self, payload):
        seen = {}

        def opener(req, timeout=None):
            seen.update(url=req.full_url, headers=dict(req.header_items()), body=req.data,
                        method=req.get_method())
            return FakeResp(json.dumps(payload).encode())
        return seen, opener

    def test_elevenlabs_request_shape(self):
        seen, op = self.capture({"text": "", "words": []})
        el = gp.ElevenLabsEngine(CFG["engine"]["elevenlabs"], key="secret", opener=op)
        el.transcribe(make_wav(), gp.wav_info(make_wav()), ["Vidar", "SPC"])
        self.assertTrue(seen["url"].startswith("https://api.elevenlabs.io/"))
        self.assertEqual(seen["headers"].get("Xi-api-key"), "secret")
        body = seen["body"].decode("latin-1")
        for needle in ('name="model_id"\r\n\r\nscribe_v2', 'name="diarize"\r\n\r\ntrue',
                       'name="keyterms"\r\n\r\nVidar', 'name="keyterms"\r\n\r\nSPC', 'name="file"'):
            self.assertIn(needle, body)
        # Language is detected, never forced (2026-10-02: Chinese, Vietnamese, Farsi callers).
        self.assertNotIn('name="language_code"', body)
        self.assertNotIn("language_code", CFG["engine"]["elevenlabs"]["params"])

    def test_elevenlabs_normalize(self):
        raw = {"language_code": "en", "text": "Hi there. Hello.", "transcription_id": "tr1", "words": [
            {"text": "Hi", "type": "word", "start": 0.0, "end": 0.3, "speaker_id": "speaker_0", "logprob": 0},
            {"text": " ", "type": "spacing", "start": 0.3, "end": 0.35, "speaker_id": "speaker_0"},
            {"text": "there.", "type": "word", "start": 0.35, "end": 0.8, "speaker_id": "speaker_0", "logprob": 0},
            {"text": "(music)", "type": "audio_event", "start": 0.9, "end": 1.5},
            {"text": "Hello.", "type": "word", "start": 61.0, "end": 61.5, "speaker_id": "speaker_1", "logprob": 0}]}
        n = gp.ElevenLabsEngine(CFG["engine"]["elevenlabs"]).normalize(raw, T0)
        self.assertEqual([u["speaker"] for u in n["utterances"]], ["speaker_0", "speaker_1"])
        self.assertTrue(n["utterances"][0]["text"].startswith("Hi there."))
        self.assertIn("(music)", n["utterances"][0]["text"])
        self.assertEqual(n["utterances"][1]["start_at"], "2026-10-01T09:01:01-04:00")
        self.assertEqual(n["confidence"], 1.0)
        self.assertEqual(n["audio_events"][0]["text"], "(music)")

    def test_ghl_normalize_seconds(self):
        raw = {"sentences": [
            {"sentenceIndex": 1, "startTime": 1.84, "endTime": 2.56, "speaker": 0, "mediaChannel": 1,
             "transcript": "second", "confidence": 0.8},
            {"sentenceIndex": 0, "startTime": 1.12, "endTime": 1.84, "speaker": 1, "mediaChannel": 2,
             "transcript": "first", "confidence": 0.6}]}
        n = gp.GhlTranscriptionEngine({}).normalize(raw, T0, duration_s=76)
        self.assertEqual(n["text"], "first second")
        self.assertEqual(n["utterances"][0]["speaker"], "speaker_1")
        self.assertAlmostEqual(n["utterances"][0]["start_s"], 1.12)


class TestTranscribeOne(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = dict(CFG, outputs=dict(CFG["outputs"], cache_dir="cache"))
        self.cfg = cfg
        self.paths = gp.Paths(cfg, root=Path(self.tmp.name))
        self.rec = gp.call_record(msg())
        self.client = mock.Mock()
        self.client.recording.return_value = (make_wav(seconds=2), "audio/x-wav")

    def tearDown(self):
        self.tmp.cleanup()

    def run_one(self, engine, ghl=None):
        with mock.patch.object(gp, "REPO_ROOT", Path(self.tmp.name)):
            return gp.transcribe_one(self.client, engine, dict(self.rec), self.cfg, ["Vidar"],
                                     self.paths, ghl_engine=ghl)

    def test_success_and_cache(self):
        eng = mock.Mock(name="eng", cfg=CFG["engine"]["elevenlabs"])
        eng.name = "elevenlabs"
        eng.transcribe.return_value = {}
        eng.normalize.return_value = {"text": "hello", "language": "en", "confidence": 0.9,
                                      "utterances": [], "audio_events": [], "request_id": "r"}
        eng.describe.return_value = {"name": "elevenlabs", "model": "scribe_v2", "params": {}}
        r = self.run_one(eng)
        self.assertEqual(r["recording"], "transcribed")
        self.assertGreater(r["engine"]["est_cost_usd"], 0)
        r2 = self.run_one(eng)
        self.assertTrue(r2.get("cached"))
        self.assertEqual(eng.transcribe.call_count, 1)

    def test_fallback_then_failure_never_raises(self):
        eng = mock.Mock(cfg={})
        eng.name = "elevenlabs"
        eng.transcribe.side_effect = gp.EngineError("HTTP 500")
        ghl = mock.Mock()
        ghl.fetch.return_value = {"sentences": [{"sentenceIndex": 0, "startTime": 0, "endTime": 1,
                                                 "speaker": 0, "transcript": "hi"}]}
        ghl.normalize.side_effect = gp.GhlTranscriptionEngine({}).normalize
        ghl.describe.return_value = {"name": "ghl"}
        self.assertEqual(self.run_one(eng, ghl)["recording"], "fallback-ghl")
        ghl.fetch.side_effect = gc.GhlError("404", code=404)
        (Path(self.tmp.name) / "cache").mkdir(exist_ok=True)
        for f in (Path(self.tmp.name) / "cache").glob("*.json"):
            f.unlink()
        r = self.run_one(eng, ghl)
        self.assertEqual(r["recording"], "failed")
        self.assertIn("HTTP 500", r["error"])

    def test_empty_recording_fails(self):
        self.client.recording.return_value = (b"", "audio/x-wav")
        eng = mock.Mock(cfg={})
        eng.name = "elevenlabs"
        self.assertEqual(self.run_one(eng)["recording"], "failed")
        eng.transcribe.assert_not_called()


class TestCallNote(unittest.TestCase):
    META = {"message_id": "m1", "conversation_id": "c1", "engine": "scribe_v2", "engine_label": "Scribe v2",
            "duration_s": 212, "direction": "inbound", "started_label": "2026-10-01 09:02", "staff": "Albert"}

    def utts(self, n):
        return [{"start_s": i * 3, "speaker": "Speaker 1" if i % 2 else "Albert", "text": f"line {i} " + "x" * 60}
                for i in range(n)]

    def test_order_summary_next_steps_transcript(self):
        bodies = gp.render_call_note("Wants an LVP quote.", ["Us: send quote — by Fri"], self.utts(3), self.META)
        self.assertEqual(len(bodies), 1)
        b = bodies[0]
        self.assertLess(b.index("Summary"), b.index("Next steps"))
        self.assertLess(b.index("Next steps"), b.index("Transcript ("))
        self.assertTrue(b.rstrip().endswith("]"))
        self.assertIn("[call-note v1 messageId=m1 conversationId=c1 engine=scribe_v2 part=1/1", b)

    def test_split_and_reassemble_any_order(self):
        bodies = gp.render_call_note("S.", [], self.utts(200), self.META, split_chars=4800)
        self.assertGreater(len(bodies), 1)
        self.assertTrue(all(len(b) <= 4800 for b in bodies))
        parsed = gp.parse_call_note(list(reversed(bodies)))
        self.assertEqual(parsed["summary"], "S.")
        self.assertEqual(parsed["next_steps"], [])
        self.assertEqual(len(parsed["utterances"]), 200)
        self.assertEqual(parsed["utterances"][1]["speaker"], "Speaker 1")
        self.assertTrue(parsed["complete"])

    def test_make_style_fixed_offset_split(self):
        """The Make scenario cuts at fixed 3,000-character offsets (mid-line) and writes
        the parts last-first; the reader must rebuild every turn exactly."""
        turns = self.utts(120)
        transcript = "\n".join(f"[{gp.fmt_clock(u['start_s'])}] {u['speaker']}: {u['text']}" for u in turns)
        head = ("Summary\nWants an LVP quote for two rooms.\n\nNext steps\n- Us: send quote — by Friday\n"
                "- Customer: send photos — no date given\n\nTranscript (Scribe v2 · 212s · inbound · "
                "2026-10-01 09:02 · Albert)\n")
        size = 3000
        n = -(-len(transcript) // size)
        bodies = []
        for k in range(n, 0, -1):
            chunk = transcript[(k - 1) * size:k * size]
            lead = head if k == 1 else "Transcript (continued)\n"
            bodies.append(f"{lead}{chunk}\n\n[call-note v1 messageId=m1 conversationId=c1 "
                          f"engine=scribe_v2 part={k}/{n}]")
        self.assertGreater(n, 2)
        parsed = gp.parse_call_note(bodies)
        self.assertEqual(parsed["summary"], "Wants an LVP quote for two rooms.")
        self.assertEqual(parsed["next_steps"], ["Us: send quote — by Friday",
                                                "Customer: send photos — no date given"])
        self.assertEqual([u["text"] for u in parsed["utterances"]], [u["text"] for u in turns])
        self.assertEqual(parsed["utterances"][1]["speaker"], "Speaker 1")
        self.assertTrue(parsed["complete"])

    def test_find_note_ignores_other_notes(self):
        body = gp.render_call_note("S.", ["Customer: send photos — by Mon"], self.utts(2), self.META)[0]
        notes = [{"id": "n0", "body": "Called, waiting on contractor"}, {"id": "n1", "body": body}]
        found = gp.find_call_note(notes, "m1")
        self.assertEqual(found["note_ids"], ["n1"])
        self.assertEqual(found["next_steps"], ["Customer: send photos — by Mon"])
        self.assertIsNone(gp.find_call_note(notes, "other"))

    def test_dry_run_prefers_note_and_skips_download(self):
        body = gp.render_call_note("S.", [], self.utts(2), self.META)[0]
        cl = mock.Mock()
        cl.search_conversations.return_value = [{"id": "c1", "contactId": "k1"}]
        cl.list_messages.return_value = [msg("m1"), msg("m2", when=T0 + timedelta(minutes=1)),
                                         msg("m3", when=T0 + timedelta(minutes=2))]
        cl.notes.return_value = [{"id": "n1", "body": body}]
        cl.stats.return_value = {}
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "run.json"
            args = gp.argparse.Namespace(hours=None, since=(T0 - timedelta(hours=1)).isoformat(),
                                         until=(T0 + timedelta(hours=1)).isoformat(), out=str(out),
                                         message_id=[], engine=None, bakeoff=None, dry_run=True, limit=None,
                                         ignore_notes=False, refresh=False, compare_ghl=False,
                                         no_audio_cache=False, print=False, verbose=False)
            with mock.patch("sys.stdout", io.StringIO()):
                cfg = dict(CFG, max_calls_per_run=1)  # a note-covered call must not use the cap
                self.assertEqual(gp.run(cl, cfg, args), 0)
            doc = json.loads(out.read_text())
        cl.recording.assert_not_called()
        self.assertEqual(cl.notes.call_count, 1)
        self.assertEqual(doc["counts"]["from_note"], 1)
        self.assertEqual([c["recording"] for c in doc["calls"]],
                         ["from-note", "would-transcribe", "over-cap"])


class TestCallNoteV2(unittest.TestCase):
    """2026-10-02 (Albert): Summary and Next steps go in an internal comment; the note
    holds the transcript only; a reference code ties the two together."""
    META = {"message_id": "m1", "conversation_id": "c1", "engine": "scribe_v2", "ref": "C-1001-0902",
            "call_line": "Thu Oct 1, 9:02 am · Inbound · 3m 32s · Helen"}

    def utts(self, n):
        return [{"start_s": i * 3, "speaker": f"Speaker {1 + i % 2}", "text": f"line {i} " + "x" * 60}
                for i in range(n)]

    def test_note_is_transcript_only_and_reassembles(self):
        turns = self.utts(150)
        bodies = gp.render_call_note_v2(turns, self.META, "Speaker 1 = Helen (Titan) · Speaker 2 = customer")
        self.assertGreater(len(bodies), 2)
        self.assertTrue(bodies[0].startswith("Transcript · Ref C-1001-0902 · Thu Oct 1, 9:02 am"))
        self.assertTrue(all("Summary" not in b and "Next steps" not in b for b in bodies))
        parsed = gp.parse_call_note(list(reversed(bodies)))  # Make writes them last-first
        self.assertEqual(parsed["version"], 2)
        self.assertEqual(parsed["ref"], "C-1001-0902")
        self.assertEqual(parsed["staff_named"], "Helen")
        self.assertEqual(parsed["speakers"], "Speaker 1 = Helen (Titan) · Speaker 2 = customer")
        self.assertEqual(parsed["summary"], "")
        self.assertEqual([u["text"] for u in parsed["utterances"]], [u["text"] for u in turns])
        self.assertTrue(parsed["complete"])

    def test_summary_comment_round_trip(self):
        body = gp.render_call_summary("Wants an LVP quote.", ["Us: send quote — by Fri"], self.META)
        self.assertTrue(body.startswith("📞 Call summary · Ref C-1001-0902"))
        self.assertLess(body.index("Summary\n"), body.index("Next steps"))
        c = gp.parse_call_summary(body)
        self.assertEqual((c["message_id"], c["ref"], c["staff_named"]), ("m1", "C-1001-0902", "Helen"))
        self.assertEqual(c["summary"], "Wants an LVP quote.")
        self.assertEqual(c["next_steps"], ["Us: send quote — by Fri"])
        self.assertIsNone(gp.parse_call_summary("called, waiting on contractor"))

    def test_translation_notes_round_trip_and_attach(self):
        turns = [{"start_s": i * 4, "speaker": f"Speaker {1 + i % 2}", "text": f"translated line {i} " + "y" * 70}
                 for i in range(90)]
        tr = gp.render_call_translation(turns, dict(self.META, language_name="Vietnamese"), "vie")
        self.assertGreater(len(tr), 1)
        self.assertTrue(tr[0].startswith("Translation (English, from Vietnamese) · Ref C-1001-0902"))
        parsed = gp.parse_call_translation(list(reversed(tr)), "m1")
        self.assertEqual(parsed["language"], "vie")
        self.assertEqual([u["text"] for u in parsed["utterances"]], [u["text"] for u in turns])
        self.assertTrue(parsed["complete"])
        self.assertIsNone(gp.parse_call_translation(tr, "other-call"))
        # The transcript reader ignores translation notes, and attaches them to the call.
        notes = [{"id": f"n{k}", "body": b} for k, b in enumerate(
            gp.render_call_note_v2(self.utts(4), self.META, "Speaker 1 = Helen (Titan)") + tr, 1)]
        found = gp.find_call_note(notes, "m1")
        self.assertEqual(len(found["utterances"]), 4)
        self.assertEqual(found["translation"]["language"], "vie")
        rec = gp.apply_note({"message_id": "m1"}, found)
        self.assertEqual(rec["language"], "vie")
        self.assertEqual(len(rec["translation"]["utterances"]), 90)

    def test_summary_footer_on_anything_but_a_comment_raises_an_alarm(self):
        body = gp.render_call_summary("S.", [], self.META)
        comments, alarms = {}, []
        gp.note_summary_comment({"id": "x1", "messageType": "TYPE_INTERNAL_COMMENT", "body": body,
                                 "conversationId": "c1"}, comments, alarms)
        self.assertEqual(alarms, [])
        self.assertEqual(comments["m1"]["comment_id"], "x1")
        for leaked in ("TYPE_SMS", "TYPE_EMAIL", None):
            alarms = []
            gp.note_summary_comment({"id": "x2", "messageType": leaked, "body": body,
                                     "conversationId": "c1"}, {}, alarms)
            self.assertEqual(len(alarms), 1, leaked)
            self.assertIn("not an internal comment", alarms[0])

    def test_dry_run_takes_summary_from_the_comment(self):
        notes = [{"id": f"n{k}", "body": b} for k, b in
                 enumerate(gp.render_call_note_v2(self.utts(4), self.META, "Speaker 1 = Helen (Titan)"), 1)]
        comment = {"id": "x1", "conversationId": "c1", "messageType": "TYPE_INTERNAL_COMMENT",
                   "direction": "outbound", "dateAdded": T0.isoformat(),
                   "body": gp.render_call_summary("Wants a quote.", ["Us: call back — by Mon"], self.META)}
        cl = mock.Mock()
        cl.search_conversations.return_value = [{"id": "c1", "contactId": "k1"}]
        cl.list_messages.return_value = [msg("m1"), comment]
        cl.notes.return_value = notes
        cl.stats.return_value = {}
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "run.json"
            args = gp.argparse.Namespace(hours=None, since=(T0 - timedelta(hours=1)).isoformat(),
                                         until=(T0 + timedelta(hours=1)).isoformat(), out=str(out),
                                         message_id=[], engine=None, bakeoff=None, dry_run=True, limit=None,
                                         ignore_notes=False, refresh=False, compare_ghl=False,
                                         no_audio_cache=False, print=False, verbose=False)
            with mock.patch("sys.stdout", io.StringIO()):
                self.assertEqual(gp.run(cl, CFG, args), 0)
            doc = json.loads(out.read_text())
        self.assertEqual(doc["alarms"], [])
        self.assertEqual(len(doc["calls"]), 1)  # the comment is not a call
        call = doc["calls"][0]
        self.assertEqual(call["recording"], "from-note")
        self.assertEqual(call["note"]["summary"], "Wants a quote.")
        self.assertEqual(call["note"]["next_steps"], ["Us: call back — by Mon"])
        self.assertEqual(call["note"]["comment_id"], "x1")
        self.assertEqual(call["staff_named"], "Helen")


class TestMissingEngineKey(unittest.TestCase):
    def test_daily_run_falls_back_to_ghl_and_says_so(self):
        cl = mock.Mock()
        cl.search_conversations.return_value = [{"id": "c1", "contactId": "k1"}]
        cl.list_messages.return_value = [msg("m1")]
        cl.notes.return_value = []
        cl.transcription.return_value = [{"sentenceIndex": 0, "startTime": 0, "endTime": 1,
                                          "speaker": 0, "transcript": "hello"}]
        cl.stats.return_value = {}
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "run.json"
            args = gp.argparse.Namespace(hours=None, since=(T0 - timedelta(hours=1)).isoformat(),
                                         until=(T0 + timedelta(hours=1)).isoformat(), out=str(out),
                                         message_id=[], engine=None, bakeoff=None, dry_run=False, limit=None,
                                         ignore_notes=False, refresh=False, compare_ghl=False,
                                         no_audio_cache=False, print=False, verbose=False)
            env = {k: v for k, v in gp.os.environ.items() if k != "ELEVENLABS_API_KEY"}
            cache = dict(CFG, outputs=dict(CFG["outputs"], cache_dir=str(Path(d) / "cache")))
            with mock.patch.dict(gp.os.environ, env, clear=True), mock.patch("sys.stdout", io.StringIO()):
                self.assertEqual(gp.run(cl, cache, args), 0)
            doc = json.loads(out.read_text())
        cl.recording.assert_not_called()
        self.assertEqual(doc["status"], "partial")
        self.assertIn("ELEVENLABS_API_KEY", doc["errors"][0])
        self.assertEqual(doc["calls"][0]["recording"], "transcribed")
        self.assertEqual(doc["engine"]["name"], "ghl")


class TestKeyterms(unittest.TestCase):
    def test_order_dedupe_cap(self):
        cfg = json.loads(json.dumps(CFG))
        cfg["keyterms"]["static"] = ["LVP", "SPC"]
        cfg["staff"]["roster"] = ["Helen", "albert"]  # the phone roster follows people, deduped
        terms = gp.build_keyterms(cfg, "elevenlabs", suppliers=["Vidar", "spc"], people=["Albert"],
                                  catalogue=["Heritage Hills", "vidar"])
        self.assertEqual(terms, ["LVP", "SPC", "Vidar", "Albert", "Helen", "Heritage Hills"])
        cfg["keyterms"]["cap_by_engine"]["elevenlabs"] = 3
        self.assertEqual(len(gp.build_keyterms(cfg, "elevenlabs", suppliers=["A1", "B1"], people=[],
                                               catalogue=[])), 3)

    def test_catalogue_harvest_cleans_terms(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ingest" / "2026-09-26"
            p.mkdir(parents=True)
            with open(p / "x_airtable_upload_2026-09-26.csv", "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=["Brand", "Collection"])
                w.writeheader()
                for b, c in [("IMPRESSIVE", "Heritage Hills"), ("Vizion", "SPC 4mm"),
                             ("", "Engineered Hickory (NEW)"), ("", "Tiles")]:
                    w.writerow({"Brand": b, "Collection": c})
            got = gp.catalogue_terms({"glob": "ingest/*/*_airtable_upload_*.csv",
                                      "columns": ["Brand", "Collection"]}, Path(d))
        self.assertEqual(got, ["Impressive", "Heritage Hills", "Vizion", "Engineered Hickory"])

    def test_acronyms_stay_upper(self):
        self.assertEqual(gp._tidy_case("CIF DISTRIBUTORS"), "CIF Distributors")
        self.assertEqual(gp._tidy_case("FLOORS AT WORK"), "Floors at Work")

    def test_published_file_matches_generator(self):
        pub = json.loads((REPO_ROOT / CFG["keyterms"]["published_file"]).read_text())
        self.assertEqual(pub["terms"], gp.build_keyterms(CFG),
                         "regenerate with: python3 scripts/ghl_calls_pull.py --write-keyterms")
        self.assertEqual(pub["count"], len(pub["terms"]))


class TestCost(unittest.TestCase):
    def test_estimates(self):
        self.assertAlmostEqual(gp.estimate_cost_usd(60, "elevenlabs", CFG["engine"]["elevenlabs"]), 0.27)
        self.assertAlmostEqual(gp.estimate_cost_usd(60, "elevenlabs", CFG["engine"]["elevenlabs"], False), 0.22)
        self.assertEqual(gp.estimate_cost_usd(10, "ghl", CFG["engine"]["ghl"]), 0.0)


class TestBakeoff(unittest.TestCase):
    def test_scorecard_and_file(self):
        rec = dict(gp.call_record(msg()), recording="transcribed", confidence=0.9,
                   text="Vidar herringbone quote", utterances=[{"start_s": 0, "speaker": "speaker_0",
                                                                "text": "Vidar herringbone quote"}],
                   engine={"est_cost_usd": 0.01, "wall_s": 2})
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "b.md"
            card = gp.write_bakeoff(path, {"m1": {"elevenlabs": rec, "ghl": dict(rec, text="")}},
                                    ["Vidar", "herringbone"])
            self.assertIn("Vidar herringbone quote", path.read_text())
        self.assertEqual(card["elevenlabs"]["keyterm_hits"], 2)
        self.assertEqual(card["ghl"]["keyterm_hits"], 0)
        self.assertEqual(CFG["bakeoff"]["engines"], ["elevenlabs", "ghl"])
        self.assertNotIn("text", json.dumps(card))


class TestProse(unittest.TestCase):
    def test_agent_file(self):
        src = (REPO_ROOT / ".claude/agents/ghl-ingest-agent.md").read_text()
        for needle in ('currently `"6"`', "`calls`", "`call_quality`", "ghl-call-<messageId>",
                       "reporting.calls", "scripts/ghl_calls_pull.py"):
            self.assertIn(needle, src)

    def test_sample(self):
        ext = json.loads((REPO_ROOT / "ingest/SAMPLE/ghl.json").read_text())["extensions"]["ghl"]
        self.assertEqual(ext["template_version"], "6")  # v6: GHL unread triage rubric v3 (2026-10-08)
        for k in ("calls", "call_quality"):
            self.assertIn(k, ext)
        self.assertIn("calls", ext["reporting"])


if __name__ == "__main__":
    unittest.main()
