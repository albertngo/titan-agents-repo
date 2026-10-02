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

    def _snapshot(self):
        sc = CFG["make_scenarios"]["call_notes"]
        snap = json.loads((REPO_ROOT / sc["blueprint"]).read_text())
        return sc, snap, {m["id"]: m for m in snap["blueprint"]["flow"]}

    def test_make_scenario_entry(self):
        sc, snap, mods = self._snapshot()
        self.assertEqual(sc["team_id"], 459654)
        self.assertEqual(sc["writes"], ["GHL contact note", "GHL internal comment"])
        self.assertFalse(sc["isActive"])
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
        # The GHL connection writes notes and nothing else.
        conn = [m["id"] for m in snap["blueprint"]["flow"]
                if (m.get("parameters") or {}).get("__IMTCONN__") == sc["ghl_connection_id"]]
        self.assertEqual(conn, [14])
        self.assertEqual(mods[14]["module"], "highlevel:addNotetoContact")
        self.assertIn("[call-note v2 messageId={{4.id}}", mods[14]["mapper"]["body"])
        # Make formula regexes must be quoted strings; a bare /…[…]/ fails "Unexpected [".
        self.assertNotIn("; /", mods[9]["mapper"]["variables"][0]["value"])
        self.assertTrue(snap["blueprint"]["metadata"]["scenario"]["sequential"])
        sent = [f["value"] for f in mods[8]["mapper"]["multipartBodyContent"] if f["name"] == "keyterms"]
        published = json.loads((REPO_ROOT / CFG["keyterms"]["published_file"]).read_text())["terms"]
        self.assertEqual(sent, published, "module 8's keyterm fields drifted from the published list")

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

    def test_comment_gate(self):
        """Albert, 2026-10-02: internal comments only, with a barrier against any slip.
        Every layer of make_scenarios.call_notes.comment_gate, checked on the snapshot."""
        sc, snap, mods = self._snapshot()
        gate = sc["comment_gate"]
        key = sc["keychains"]["ghl_internal_comment"]
        flow = snap["blueprint"]["flow"]
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
        for needle in ('currently `"4"`', "`calls`", "`call_quality`", "ghl-call-<messageId>",
                       "reporting.calls", "scripts/ghl_calls_pull.py"):
            self.assertIn(needle, src)

    def test_sample(self):
        ext = json.loads((REPO_ROOT / "ingest/SAMPLE/ghl.json").read_text())["extensions"]["ghl"]
        self.assertEqual(ext["template_version"], "4")
        for k in ("calls", "call_quality"):
            self.assertIn(k, ext)
        self.assertIn("calls", ext["reporting"])


if __name__ == "__main__":
    unittest.main()
