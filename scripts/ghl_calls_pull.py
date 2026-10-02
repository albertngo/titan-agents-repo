#!/usr/bin/env python3
"""Read-only call-recording puller and transcriber for the daily GHL ingest.

Lists the window's GHL call messages, finds each call's transcript, and writes one
run file that .claude/agents/ghl-ingest-agent.md reads. The agent does the analysis
(summary, intent, commitments, coaching); this script never calls an LLM.

Where a transcript comes from, in order:
  1. The contact's "[call-note v1 messageId=…]" note, written by the Make scenario
     "GHL Call -> Note" right after the call (recording: "from-note"). The note is
     the durable cache — cloud containers are ephemeral.
  2. This run's own cache, analysis/cache/ghl-calls/<messageId>.<engine>.json.
  3. The recording (.wav) from GHL, sent to the configured engine
     (platform-settings/ghl-calls.json engine.default: ElevenLabs Scribe v2, locked
     in 2026-10-02).
  4. GHL's own transcription, when the engine fails (recording: "fallback-ghl").

Read-only against GHL: every GHL request goes through scripts/ghl_client.py, which
can only GET. The one outbound body this script ever sends is the audio, to the
configured engine host. It never writes under the daily ingest folder (the
orchestrator reads every *.json there); audio, transcripts and bake-off sheets go to
the gitignored analysis/cache/ghl-calls/. The only repo file it can write is the
keyterm list (--write-keyterms), which holds no customer data.

Usage:
    python3 scripts/ghl_calls_pull.py                          # registry window (24 h)
    python3 scripts/ghl_calls_pull.py --dry-run --hours 72 --verbose
    python3 scripts/ghl_calls_pull.py --probe <messageId>
    python3 scripts/ghl_calls_pull.py --hours 168 --message-id A --message-id B \
        --ignore-notes --bakeoff elevenlabs,ghl
    python3 scripts/ghl_calls_pull.py --write-keyterms

Exit codes: 0 ok or partial; 1 error (nothing could be listed); 2 bad config,
credentials or usage; 3 host_blocked (allow the host in the environment's Network
access — never worked around).

Env (see .env.example): GHL_PIT_TOKEN, GHL_LOCATION_ID, and the engine's key
(ELEVENLABS_API_KEY; ASSEMBLYAI_API_KEY / OPENAI_API_KEY only if those adapters are
chosen).
"""

import argparse
import csv
import glob
import hashlib
import io
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import ghl_client  # noqa: E402  (GET-only; the only path to GHL)

REGISTRY = REPO_ROOT / "platform-settings" / "ghl-calls.json"
NOTION_DEST = REPO_ROOT / "platform-settings" / "notion-destinations.json"
AIRTABLE_DEST = REPO_ROOT / "platform-settings" / "airtable-destinations.json"
TZ = ZoneInfo("America/Toronto")
INGEST_DIR = REPO_ROOT / "ingest"

TERMINAL_OK = ("transcribed", "fallback-ghl", "from-note")


# --------------------------------------------------------------------------- basics

def die(msg, hint=None, code=2):
    out = {"error": msg}
    if hint:
        out["hint"] = hint
    print(json.dumps(out, indent=2), file=sys.stderr)
    sys.exit(code)


def load_registry(path=REGISTRY):
    return json.loads(Path(path).read_text())


def now_utc():
    return datetime.now(timezone.utc)


def today():
    return datetime.now(TZ).date().isoformat()


def to_local_iso(dt):
    return dt.astimezone(TZ).isoformat(timespec="seconds") if dt else None


def parse_when(value):
    """CLI timestamp: ISO with or without offset (naive = America/Toronto)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(timezone.utc)


def compute_window(hours=None, since=None, until=None, cfg=None, now=None):
    now = now or now_utc()
    until_dt = parse_when(until) if until else now
    if since:
        since_dt = parse_when(since)
    else:
        h = hours if hours is not None else (cfg or {}).get("window_hours", 24)
        since_dt = until_dt - timedelta(hours=float(h))
    if since_dt >= until_dt:
        die("window is empty: --since must be before --until")
    return since_dt, until_dt


# --------------------------------------------------------------------------- call fields

def call_status_of(msg):
    """Call status from the top level or meta.call.status, lower-cased; None if absent."""
    meta_call = ((msg.get("meta") or {}).get("call") or {})
    for v in (meta_call.get("status"), msg.get("callStatus"), msg.get("status")):
        if isinstance(v, str) and v:
            return v.strip().lower()
    return None


def call_duration_of(msg):
    meta_call = ((msg.get("meta") or {}).get("call") or {})
    for v in (meta_call.get("duration"), msg.get("callDuration"), msg.get("duration")):
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


def message_time(msg):
    return ghl_client.parse_ts(msg.get("dateAdded") or msg.get("dateUpdated"))


def in_window(msg, since, until):
    ts = message_time(msg)
    return ts is not None and since <= ts < until


class Budget:
    def __init__(self, cfg, limit=None):
        self.max_calls = cfg["max_calls_per_run"] if limit is None else min(limit, cfg["max_calls_per_run"])
        self.max_minutes = cfg["max_minutes_per_run"]
        self.calls = 0
        self.minutes = 0.0

    def take(self, duration_s):
        mins = (duration_s or 0) / 60.0
        if self.calls + 1 > self.max_calls or self.minutes + mins > self.max_minutes:
            return False
        self.calls += 1
        self.minutes += mins
        return True


def gate(msg, cfg, budget=None):
    """('transcribe' | 'none' | 'skipped-short' | 'over-cap', reason)."""
    status = call_status_of(msg)
    if status not in cfg["transcribe_statuses"]:
        return "none", f"call status {status or 'unknown'} has no recording to read"
    dur = call_duration_of(msg)
    if dur is not None and dur < cfg["min_duration_seconds"]:
        return "skipped-short", f"{dur}s < {cfg['min_duration_seconds']}s"
    if budget is not None and not budget.take(dur):
        return "over-cap", "per-run call or minute cap reached"
    return "transcribe", None


# --------------------------------------------------------------------------- audio

def wav_info(data):
    """Header facts from the recording bytes. Never raises."""
    info = {"container": "unknown", "format_tag": None, "channels": None,
            "sample_rate": None, "bits": None, "duration_s": None, "bytes": len(data or b"")}
    if not data or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return info
    info["container"] = "riff"
    try:
        with wave.open(io.BytesIO(data)) as w:
            info.update(format_tag=1, channels=w.getnchannels(), sample_rate=w.getframerate(),
                        bits=w.getsampwidth() * 8,
                        duration_s=round(w.getnframes() / float(w.getframerate()), 2))
            return info
    except (wave.Error, EOFError, ZeroDivisionError):
        pass
    # Non-PCM (μ-law = 7, A-law = 6, …): read the fmt and data chunks by hand.
    pos, byte_rate, data_len = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt " and len(body) >= 16:
            tag, ch, rate, brate, _align, bits = struct.unpack("<HHIIHH", body[:16])
            info.update(format_tag=tag, channels=ch, sample_rate=rate, bits=bits)
            byte_rate = brate
        elif cid == b"data":
            data_len = min(size, len(data) - pos - 8)
        pos += 8 + size + (size & 1)
    if byte_rate and data_len is not None:
        info["duration_s"] = round(data_len / float(byte_rate), 2)
    return info


def sha1(data):
    return hashlib.sha1(data).hexdigest()


# --------------------------------------------------------------------------- keyterms

def _people_names():
    try:
        people = json.loads(NOTION_DEST.read_text()).get("people", {})
    except (OSError, ValueError):
        return []
    out = []
    for key, p in people.items():
        if key.startswith("_") or not isinstance(p, dict):
            continue
        name = p.get("name") or ""
        if name and "bot" not in name.lower() and name.lower() != "front desk":
            out.append(name)
    return out


def _supplier_names():
    try:
        aliases = json.loads(AIRTABLE_DEST.read_text()).get("supplier_aliases", {})
    except (OSError, ValueError):
        return []
    return [_tidy_case(v) for k, v in aliases.items() if not k.startswith("_") and isinstance(v, str)]


SMALL_WORDS = {"at", "of", "and", "the", "on", "in", "for"}


def _tidy_case(s):
    """ALL-CAPS registry names to readable case; short acronyms (CIF, JL) stay upper."""
    s = s.strip()
    if not (s.isupper() and len(s) > 3):
        return s
    words = []
    for i, w in enumerate(s.split()):
        lw = w.lower()
        if i and lw in SMALL_WORDS:
            words.append(lw)
        elif len(w) <= 3 and w.isalpha():
            words.append(w)
        else:
            words.append(w.capitalize())
    return " ".join(words)


GENERIC_COLLECTIONS = {"tiles", "accessories", "hybrid", "laminate", "vinyl", "series", "spc", "wpc"}


def _clean_catalogue_term(raw):
    s = re.sub(r"\([^)]*\)", "", raw or "").strip(" -–/")
    s = re.sub(r"\s+", " ", s)
    if not s or re.search(r"\d", s) or len(s) > 30 or len(s.split()) > 4:
        return None
    if s.lower() in GENERIC_COLLECTIONS:
        return None
    return _tidy_case(s)


def catalogue_terms(spec, root=REPO_ROOT):
    files = sorted(glob.glob(str(root / spec["glob"])))[-int(spec.get("newest_files", 30)):]
    out = []
    for f in reversed(files):
        try:
            with open(f, newline="", encoding="utf-8-sig") as fh:
                for row in csv.DictReader(fh):
                    for col in spec["columns"]:
                        t = _clean_catalogue_term(row.get(col))
                        if t:
                            out.append(t)
        except (OSError, csv.Error, UnicodeDecodeError):
            continue
    return out


def build_keyterms(cfg, engine=None, root=REPO_ROOT, suppliers=None, people=None, catalogue=None):
    """Static glossary, then suppliers, then staff names, then catalogue brands and
    collections. Case-insensitive dedupe keeps the first spelling; capped per engine."""
    kt = cfg["keyterms"]
    groups = [list(kt.get("static", []))]
    if kt.get("from_suppliers"):
        groups.append(_supplier_names() if suppliers is None else suppliers)
    if kt.get("from_people"):
        groups.append(_people_names() if people is None else people)
    if kt.get("from_staff_roster"):
        groups.append(cfg.get("staff", {}).get("roster", []))
    if kt.get("from_catalogue"):
        groups.append(catalogue_terms(kt["from_catalogue"], root) if catalogue is None else catalogue)
    seen, out = set(), []
    for g in groups:
        for t in g:
            t = (t or "").strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
    cap = kt.get("cap_by_engine", {}).get(engine) if engine else None
    return out[:cap] if cap else out


# --------------------------------------------------------------------------- cost

def estimate_cost_usd(minutes, engine_name, ecfg, keyterms_used=True):
    hours = minutes / 60.0
    if "price_per_hour_usd" in ecfg:
        rate = ecfg["price_per_hour_usd"] + (ecfg.get("keyterm_surcharge_per_hour_usd", 0) if keyterms_used else 0)
        return round(hours * rate, 4)
    if "price_per_minute_usd" in ecfg:
        rate = ecfg["price_per_minute_usd"] + (ecfg.get("keyterm_surcharge_per_minute_usd", 0) if keyterms_used else 0)
        return round(minutes * rate, 4)
    return 0.0


# --------------------------------------------------------------------------- HTTP to engines

class EngineError(RuntimeError):
    pass


def multipart(fields, files):
    """Stdlib multipart/form-data body. fields: [(name, str)], files: [(name, filename, ctype, bytes)]."""
    boundary = "titan" + uuid.uuid4().hex
    buf = io.BytesIO()
    for name, value in fields:
        buf.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode())
        buf.write(str(value).encode("utf-8"))
        buf.write(b"\r\n")
    for name, filename, ctype, data in files:
        buf.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                  f"filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n".encode())
        buf.write(data)
        buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def _send(opener, url, body, headers, timeout):
    """One request carrying a body (urllib sends it with the body's default verb).
    Engine hosts only — never GHL."""
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with opener(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise EngineError(f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}: "
                          f"{e.read()[:300].decode('utf-8', 'replace')}")
    except urllib.error.URLError as e:
        if ghl_client.classify_url_error(e) == "host_blocked":
            raise ghl_client.GhlBlocked(f"egress proxy refused {urllib.parse.urlsplit(url).netloc}")
        raise EngineError(f"{type(e).__name__} reaching {urllib.parse.urlsplit(url).netloc}: {e}")


def _get(opener, url, headers, timeout):
    req = urllib.request.Request(url, headers=headers)
    with opener(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


# --------------------------------------------------------------------------- engines

def _utt(start_s, end_s, speaker, text, started_at, channel=None, confidence=None):
    u = {"start_s": round(float(start_s or 0), 2), "end_s": round(float(end_s or 0), 2),
         "speaker": speaker, "channel": channel, "confidence": confidence, "text": text.strip()}
    if started_at:
        u["start_at"] = to_local_iso(started_at + timedelta(seconds=u["start_s"]))
        u["end_at"] = to_local_iso(started_at + timedelta(seconds=u["end_s"]))
    return u


class Engine:
    name = "base"
    needs_audio = True

    def __init__(self, ecfg, key=None, opener=None):
        self.cfg = ecfg or {}
        self.key = key
        self.opener = opener or urllib.request.urlopen
        self.model = self.cfg.get("model") or self.cfg.get("model_id")

    def describe(self):
        return {"name": self.name, "model": self.model, "params": self.cfg.get("params", {})}


class ElevenLabsEngine(Engine):
    """ElevenLabs Scribe v2. Multipart upload; diarizes (no channel mapping)."""
    name = "elevenlabs"

    def request(self, audio, info, keyterms, language=None):
        p = self.cfg.get("params", {})
        fields = [("model_id", self.cfg.get("model_id", "scribe_v2")),
                  ("diarize", str(p.get("diarize", True)).lower()),
                  ("tag_audio_events", str(p.get("tag_audio_events", True)).lower()),
                  ("timestamps_granularity", p.get("timestamps_granularity", "word"))]
        # No language_code means Scribe detects it (2026-10-02: Chinese, Vietnamese, Farsi
        # callers). Forcing "en" turned a non-English call into garbled English.
        lang = p.get("language_code", language)
        if lang:
            fields.append(("language_code", lang))
        # Repeated form field, one term each (to confirm on the first live call).
        fields += [("keyterms", t) for t in keyterms[: self.cfg.get("max_keyterms", 1000)]]
        ctype = "audio/wav" if info.get("container") == "riff" else "application/octet-stream"
        body, content_type = multipart(fields, [("file", "call.wav", ctype, audio)])
        headers = {"xi-api-key": self.key or "", "Content-Type": content_type, "Accept": "application/json"}
        return self.cfg["url"], body, headers

    def transcribe(self, audio, info, keyterms, language=None):
        url, body, headers = self.request(audio, info, keyterms, language)
        return _send(self.opener, url, body, headers, self.cfg.get("timeout_s", 600))

    def normalize(self, raw, started_at, direction=None, cfg=None):
        utts, events, cur = [], [], None
        for w in raw.get("words") or []:
            kind = w.get("type", "word")
            if kind == "audio_event":
                events.append({"start_s": w.get("start"), "text": w.get("text")})
                if cur is not None:
                    cur["text"] += " " + (w.get("text") or "")
                continue
            spk = w.get("speaker_id") or "speaker_0"
            if kind == "spacing":
                if cur is not None:
                    cur["text"] += w.get("text") or " "
                continue
            if cur is None or cur["speaker"] != spk:
                if cur is not None:
                    utts.append(cur)
                cur = {"speaker": spk, "start": w.get("start"), "end": w.get("end"), "text": "",
                       "lp": []}
            cur["text"] += w.get("text") or ""
            cur["end"] = w.get("end", cur["end"])
            if isinstance(w.get("logprob"), (int, float)):
                cur["lp"].append(w["logprob"])
        if cur is not None:
            utts.append(cur)
        out = []
        for u in utts:
            conf = None
            if u["lp"]:
                import math
                conf = round(math.exp(sum(u["lp"]) / len(u["lp"])), 3)
            out.append(_utt(u["start"], u["end"], u["speaker"], u["text"], started_at, confidence=conf))
        confs = [u["confidence"] for u in out if u["confidence"] is not None]
        return {"text": raw.get("text", "").strip(), "language": raw.get("language_code"),
                "confidence": round(sum(confs) / len(confs), 3) if confs else raw.get("language_probability"),
                "utterances": out, "audio_events": events,
                "request_id": raw.get("transcription_id")}


class AssemblyAIEngine(Engine):
    """AssemblyAI: upload, create, poll. Comparison adapter."""
    name = "assemblyai"

    def transcribe(self, audio, info, keyterms, language="en"):
        base, h = self.cfg["url"], {"authorization": self.key or ""}
        up = _send(self.opener, base + "/upload", audio,
                   dict(h, **{"Content-Type": "application/octet-stream"}), self.cfg.get("timeout_s", 600))
        job = {"audio_url": up.get("upload_url"), "speaker_labels": True, "language_code": language}
        if self.model:
            job["speech_model"] = self.model
        if keyterms:
            job["keyterms_prompt"] = keyterms[: self.cfg.get("max_keyterms", 1000)]
        created = _send(self.opener, base + "/transcript", json.dumps(job).encode(),
                        dict(h, **{"Content-Type": "application/json"}), 60)
        deadline = time.monotonic() + self.cfg.get("poll_timeout_s", 600)
        while time.monotonic() < deadline:
            res = _get(self.opener, f"{base}/transcript/{created.get('id')}", h, 60)
            if res.get("status") == "completed":
                return res
            if res.get("status") == "error":
                raise EngineError(f"assemblyai: {res.get('error')}")
            time.sleep(self.cfg.get("poll_interval_s", 3))
        raise EngineError("assemblyai: polling timed out")

    def normalize(self, raw, started_at, direction=None, cfg=None):
        out = [_utt((u.get("start") or 0) / 1000.0, (u.get("end") or 0) / 1000.0,
                    f"speaker_{u.get('speaker')}", u.get("text", ""), started_at,
                    confidence=u.get("confidence")) for u in raw.get("utterances") or []]
        return {"text": (raw.get("text") or "").strip(), "language": raw.get("language_code"),
                "confidence": raw.get("confidence"), "utterances": out, "audio_events": [],
                "request_id": raw.get("id")}


class OpenAIEngine(Engine):
    """OpenAI transcription. 25 MB upload cap; no diarization in the plain model."""
    name = "openai"

    def transcribe(self, audio, info, keyterms, language="en"):
        if len(audio) > self.cfg.get("max_upload_mb", 25) * 1024 * 1024:
            raise EngineError("too_large")
        fields = [("model", self.model), ("language", language), ("response_format", "json")]
        if keyterms:
            fields.append(("prompt", "Vocabulary: " + ", ".join(keyterms[:50])))
        body, ctype = multipart(fields, [("file", "call.wav", "audio/wav", audio)])
        return _send(self.opener, self.cfg["url"], body,
                     {"Authorization": "Bearer " + (self.key or ""), "Content-Type": ctype},
                     self.cfg.get("timeout_s", 600))

    def normalize(self, raw, started_at, direction=None, cfg=None):
        segs = raw.get("segments") or []
        out = [_utt(s.get("start"), s.get("end"), s.get("speaker", "speaker_0"), s.get("text", ""),
                    started_at) for s in segs]
        return {"text": (raw.get("text") or "").strip(), "language": raw.get("language"),
                "confidence": None, "utterances": out, "audio_events": [], "request_id": None}


class GhlTranscriptionEngine(Engine):
    """GHL's own transcript, via the GET-only client. Fallback; needs no audio."""
    name = "ghl"
    needs_audio = False

    def __init__(self, ecfg, client=None, **kw):
        super().__init__(ecfg, **kw)
        self.client = client
        self.model = "ghl-native"

    def fetch(self, message_id):
        return {"sentences": self.client.transcription(message_id)}

    def normalize(self, raw, started_at, direction=None, cfg=None, duration_s=None):
        sents = sorted(raw.get("sentences") or [], key=lambda s: s.get("sentenceIndex", 0))
        ends = [float(s.get("endTime") or 0) for s in sents]
        # Seconds as observed live 2026-10-02; milliseconds handled defensively.
        scale = 1000.0 if ends and duration_s and max(ends) > duration_s * 5 else 1.0
        if ends and not duration_s and max(ends) > 20000:
            scale = 1000.0
        out = [_utt(float(s.get("startTime") or 0) / scale, float(s.get("endTime") or 0) / scale,
                    (f"speaker_{s['speaker']}" if s.get("speaker") is not None
                     else f"channel_{s.get('mediaChannel', 0)}"), s.get("transcript", ""), started_at,
                    channel=s.get("mediaChannel"), confidence=s.get("confidence")) for s in sents]
        confs = [u["confidence"] for u in out if isinstance(u["confidence"], (int, float))]
        return {"text": " ".join(u["text"] for u in out).strip(), "language": "en",
                "confidence": round(sum(confs) / len(confs), 3) if confs else None,
                "utterances": out, "audio_events": [], "request_id": None}


ENGINES = {"elevenlabs": ElevenLabsEngine, "assemblyai": AssemblyAIEngine,
           "openai": OpenAIEngine}


def make_engine(name, cfg, opener=None):
    if name not in ENGINES:
        die(f"unknown engine {name!r}", "choose one of ghl, " + ", ".join(sorted(ENGINES)))
    ecfg = cfg["engine"][name]
    key = os.environ.get(ecfg.get("env_var", ""))
    if not key:
        die(f"{ecfg.get('env_var')} is not set", "add it to .env (declared in .env.example)")
    return ENGINES[name](ecfg, key=key, opener=opener)


# --------------------------------------------------------------------------- call notes

FOOTER_RE = re.compile(r"\[call-note v(\d+) ([^\]]*)\]")
# v2 (2026-10-02, Albert): the note holds the transcript only; Summary and Next steps go
# in an internal comment on the conversation, carrying this footer.
SUMMARY_FOOTER_RE = re.compile(r"\[call-summary v(\d+) ([^\]]*)\]")
# Non-English calls (2026-10-02): an English translation in its own notes, same Ref.
TRANSLATION_FOOTER_RE = re.compile(r"\[call-translation v(\d+) ([^\]]*)\]")
TRANSLATION_HEAD_RE = re.compile(r"(?m)^Translation[^\n]*\n")
ENGLISH_CODES = ("en", "eng")
INTERNAL_COMMENT = "TYPE_INTERNAL_COMMENT"
LINE_RE = re.compile(r"^\[(\d+):(\d{2})\]\s*([^:]{1,40}):\s*(.*)$")


def fmt_clock(seconds):
    s = int(seconds or 0)
    return f"{s // 60:02d}:{s % 60:02d}"


def _footer_fields(m):
    fields = dict(kv.split("=", 1) for kv in m.group(2).split() if "=" in kv)
    fields["version"] = int(m.group(1))
    return fields


def parse_footer(body):
    m = FOOTER_RE.search(body or "")
    if not m:
        return None
    fields = _footer_fields(m)
    part = fields.get("part", "1/1")
    try:
        k, n = (int(x) for x in part.split("/"))
    except ValueError:
        k, n = 1, 1
    fields["part_k"], fields["part_n"] = k, n
    return fields


def _section(body, name, nxt):
    pat = rf"(?ms)^{name}[^\n]*\n(.*?)(?=^(?:{'|'.join(nxt)})\b|\[call-(?:note|summary) v\d|\Z)"
    m = re.search(pat, body)
    return m.group(1).strip() if m else ""


# v1: "Transcript (Scribe v2 · …)" / "Transcript (continued)".
# v2: "Transcript · Ref C-… · <call line>" + "Speakers: …" / "Transcript (continued) · Ref C-…".
TRANSCRIPT_HEAD_RE = re.compile(r"(?m)^Transcript(?: \([^\n]*\)| ·)[^\n]*\n(?:Speakers:[^\n]*\n)?"
                                r"(?:Language:[^\n]*\n)?")


def _transcript_raw(body):
    """The transcript chunk of one note part, unstripped: everything after its
    'Transcript (…)' header line up to the blank line before the footer."""
    m = TRANSCRIPT_HEAD_RE.search(body or "")
    if not m:
        return ""
    rest = body[m.end():]
    end = rest.find("\n\n[call-note v")
    return rest if end < 0 else rest[:end]


def parse_call_note(bodies):
    """Reassemble a call note from its parts (any order). None if no part is a call note.

    Returns {message_id, conversation_id, engine, summary, next_steps[], utterances[], parts}.
    """
    parts = []
    for b in bodies:
        f = parse_footer(b)
        if f:
            parts.append((f["part_k"], f, b))
    if not parts:
        return None
    parts.sort(key=lambda p: p[0])
    head = parts[0][1]
    main = next((b for k, _, b in parts if k == 1), parts[0][2])
    summary = _section(main, "Summary", ["Next steps", "Transcript"])
    steps_txt = _section(main, "Next steps", ["Transcript"])
    steps = [ln.lstrip("-• ").strip() for ln in steps_txt.splitlines() if ln.strip()]
    # Make cuts the transcript at fixed character offsets, so a line can be split
    # across two parts. Joining the raw chunks in part order restores it exactly.
    text = "".join(_transcript_raw(b) for _, _, b in parts)
    utts = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        m = LINE_RE.match(s)
        if m:
            utts.append({"start_s": int(m.group(1)) * 60 + int(m.group(2)),
                         "speaker": m.group(3).strip(), "text": m.group(4).strip()})
        elif utts:  # a wrapped line: belongs to the previous turn
            utts[-1]["text"] += " " + s
    hm = re.search(r"(?m)^Transcript · ([^\n]*)$", main)
    call_line = [x.strip() for x in hm.group(1).split("·")] if hm else []
    sp = re.search(r"(?m)^Speakers:[ \t]*([^\n]*)$", main)
    lang = re.search(r"(?m)^Language:[ \t]*([^\n(]*)", main)
    return {"message_id": head.get("messageId"), "conversation_id": head.get("conversationId"),
            "engine": head.get("engine"), "version": head.get("version", 1), "ref": head.get("ref"),
            "staff_named": call_line[-1] if len(call_line) > 1 else None,
            "speakers": sp.group(1).strip() if sp else None, "summary": summary,
            "language_name": lang.group(1).strip() if lang else None,
            "next_steps": [s for s in steps if s.lower() != "none"],
            "utterances": utts, "parts": len(parts), "complete": len(parts) == head["part_n"]}


def _utterances(text):
    utts = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        m = LINE_RE.match(s)
        if m:
            utts.append({"start_s": int(m.group(1)) * 60 + int(m.group(2)),
                         "speaker": m.group(3).strip(), "text": m.group(4).strip()})
        elif utts:
            utts[-1]["text"] += " " + s
    return utts


def parse_call_translation(bodies, message_id=None):
    """Reassemble the English translation notes of one call (any order). None if none."""
    parts = []
    for b in bodies:
        m = TRANSLATION_FOOTER_RE.search(b or "")
        if not m:
            continue
        f = _footer_fields(m)
        if message_id and f.get("messageId") != message_id:
            continue
        try:
            k, n = (int(x) for x in f.get("part", "1/1").split("/"))
        except ValueError:
            k, n = 1, 1
        h = TRANSLATION_HEAD_RE.search(b)
        chunk = b[h.end():] if h else ""
        end = chunk.find("\n\n[call-translation v")
        parts.append((k, n, f, chunk if end < 0 else chunk[:end]))
    if not parts:
        return None
    parts.sort(key=lambda p: p[0])
    head = parts[0][2]
    return {"message_id": head.get("messageId"), "ref": head.get("ref"), "language": head.get("lang"),
            "utterances": _utterances("".join(p[3] for p in parts)), "parts": len(parts),
            "complete": len(parts) == parts[0][1]}


def render_call_translation(utterances, meta, language, split_chars=3000):
    """Reference format of the translation notes, cut like Make cuts them."""
    text = "\n".join(f"[{fmt_clock(u.get('start_s'))}] {u.get('speaker')}: {u.get('text')}" for u in utterances)
    n = max(1, -(-len(text) // split_chars))
    out = []
    for k in range(1, n + 1):
        head = (f"Translation (English, from {meta.get('language_name', language)}) · Ref {meta['ref']} · "
                f"{meta['call_line']}\n" if k == 1 else f"Translation (continued) · Ref {meta['ref']}\n")
        out.append(f"{head}{text[(k - 1) * split_chars:k * split_chars]}\n\n[call-translation v1 "
                   f"messageId={meta['message_id']} ref={meta['ref']} lang={language} part={k}/{n}]")
    return out


def parse_call_summary(body):
    """The internal comment the Make scenario posts (v2): call line, Summary, Next steps.
    None if the body carries no [call-summary …] footer."""
    m = SUMMARY_FOOTER_RE.search(body or "")
    if not m:
        return None
    f = _footer_fields(m)
    lines = (body or "").splitlines()
    call_line = [x.strip() for x in lines[1].split("·")] if len(lines) > 1 and "·" in lines[1] else []
    steps_txt = _section(body, "Next steps", ["Summary"])
    steps = [ln.lstrip("-• ").strip() for ln in steps_txt.splitlines() if ln.strip()]
    return {"message_id": f.get("messageId"), "ref": f.get("ref"), "version": f["version"],
            "staff_named": call_line[-1] if len(call_line) > 1 else None,
            "summary": _section(body, "Summary", ["Next steps"]),
            "next_steps": [s for s in steps if s.lower() != "none"]}


def render_call_summary(summary, next_steps, meta):
    """Reference format of the v2 internal comment (methods/ghl-call-transcripts.md)."""
    steps = "\n".join(f"- {s}" for s in next_steps) or "- none"
    return (f"📞 Call summary · Ref {meta['ref']} · transcript in Notes\n{meta['call_line']}\n\n"
            f"Summary\n{summary.strip()}\n\nNext steps\n{steps}\n\n"
            f"[call-summary v1 messageId={meta['message_id']} ref={meta['ref']}]")


def render_call_note_v2(utterances, meta, speakers, split_chars=3000):
    """Reference format of the v2 transcript notes, cut like Make cuts them: fixed
    split_chars offsets, part 1 carries the call line and the speaker key. Bodies in
    reading order; Make writes them last-first."""
    transcript = "\n".join(f"[{fmt_clock(u.get('start_s'))}] {u.get('speaker')}: {u.get('text')}"
                           for u in utterances)
    n = max(1, -(-len(transcript) // split_chars))
    bodies = []
    for k in range(1, n + 1):
        head = (f"Transcript · Ref {meta['ref']} · {meta['call_line']}\nSpeakers: {speakers}\n" if k == 1
                else f"Transcript (continued) · Ref {meta['ref']}\n")
        chunk = transcript[(k - 1) * split_chars:k * split_chars]
        bodies.append(f"{head}{chunk}\n\n[call-note v2 messageId={meta['message_id']} "
                      f"conversationId={meta['conversation_id']} engine={meta.get('engine', '')} "
                      f"ref={meta['ref']} part={k}/{n}]")
    return bodies


def render_call_note(summary, next_steps, utterances, meta, split_chars=4800):
    """The note format the Make scenario writes (methods/ghl-call-transcripts.md).

    Returns the bodies in READING order: [main (Summary, Next steps, Transcript 1/N),
    continuation 2/N, …]. Write them in reverse so the main note is newest and on top.
    """
    header = (f"Transcript ({meta.get('engine_label', meta.get('engine', ''))} · "
              f"{fmt_clock(meta.get('duration_s'))} · {meta.get('direction', '')} · "
              f"{meta.get('started_label', '')} · {meta.get('staff') or 'unassigned'})")
    steps = "\n".join(f"- {s}" for s in next_steps) or "- none"
    lines = [f"[{fmt_clock(u.get('start_s'))}] {u.get('speaker')}: {u.get('text')}" for u in utterances]

    def footer(k, n, chars):
        return (f"[call-note v1 messageId={meta['message_id']} conversationId={meta['conversation_id']} "
                f"engine={meta.get('engine', '')} part={k}/{n} chars={chars}]")

    lead = f"Summary\n{summary.strip()}\n\nNext steps\n{steps}\n\n{header}\n"
    budget_first = split_chars - len(lead) - 160
    chunks, cur, room = [], [], budget_first
    for ln in lines:
        if cur and sum(len(x) + 1 for x in cur) + len(ln) + 1 > room:
            chunks.append(cur)
            cur, room = [], split_chars - 200
        cur.append(ln)
    chunks.append(cur)
    n = len(chunks)
    bodies = []
    for k, chunk in enumerate(chunks, 1):
        text = "\n".join(chunk) + "\n"  # each chunk ends a line, so raw parts rejoin cleanly
        body = (lead if k == 1 else f"Transcript ({k}/{n}, continued)\n") + text
        bodies.append(body + "\n\n" + footer(k, n, len(body)))
    return bodies


def find_call_note(notes, message_id):
    bodies = [n.get("body") or "" for n in notes
              if (parse_footer(n.get("body")) or {}).get("messageId") == message_id]
    ids = [n.get("id") for n in notes
           if (parse_footer(n.get("body")) or {}).get("messageId") == message_id]
    parsed = parse_call_note(bodies) if bodies else None
    if parsed:
        parsed["note_ids"] = ids
        parsed["translation"] = parse_call_translation([n.get("body") or "" for n in notes], message_id)
    return parsed


# --------------------------------------------------------------------------- per call

def call_record(msg, people=None):
    started = message_time(msg)
    dur = call_duration_of(msg)
    people = people or {}
    return {
        "message_id": msg.get("id"), "conversation_id": msg.get("conversationId"),
        "contact_id": msg.get("contactId"), "message_type": msg.get("messageType"),
        "direction": msg.get("direction"), "user_id": msg.get("userId"),
        "staff": people.get(msg.get("userId")) if msg.get("userId") else None,
        "call_status": call_status_of(msg), "duration_s": dur,
        "started_at_utc": started.isoformat().replace("+00:00", "Z") if started else None,
        "started_at": to_local_iso(started),
        "ended_at": to_local_iso(started + timedelta(seconds=dur)) if started and dur else None,
        "recording": None, "engine": None, "language": None, "confidence": None,
        "text": None, "utterances": [], "audio_events": [], "audio": None, "note": None,
        "ghl_transcription": None, "error": None,
    }


def people_by_ghl_id():
    try:
        people = json.loads(NOTION_DEST.read_text()).get("people", {})
    except (OSError, ValueError):
        return {}
    return {p["ghl_user_id"]: p["name"] for k, p in people.items()
            if not k.startswith("_") and isinstance(p, dict) and p.get("ghl_user_id")}


class Paths:
    def __init__(self, cfg, root=REPO_ROOT):
        self.dir = root / cfg["outputs"]["cache_dir"]

    def wav(self, mid):
        return self.dir / f"{mid}.wav"

    def json(self, mid, engine):
        return self.dir / f"{mid}.{engine}.json"


def get_audio(client, rec, paths, cfg):
    p = paths.wav(rec["message_id"])
    if p.exists():
        data = p.read_bytes()
    else:
        data, _ctype = client.recording(rec["message_id"])
        if len(data) > cfg["max_recording_mb"] * 1024 * 1024:
            raise EngineError("too_large")
        if cfg.get("audio", {}).get("keep", True):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    info = wav_info(data)
    rec["audio"] = dict(info, sha1=sha1(data), path=str(p.relative_to(REPO_ROOT)) if p.exists() else None)
    return data, info


def transcribe_one(client, engine, rec, cfg, keyterms, paths, refresh=False, fallback=True,
                   compare_ghl=False, ghl_engine=None, keep_audio=True):
    """Fills rec in place. Never raises past here except GhlBlocked."""
    started = ghl_client.parse_ts(rec["started_at_utc"])
    cpath = paths.json(rec["message_id"], engine.name)
    if cpath.exists() and not refresh:
        cached = json.loads(cpath.read_text())
        rec.update({k: cached.get(k) for k in ("recording", "engine", "language", "confidence", "text",
                                               "utterances", "audio_events", "audio",
                                               "ghl_transcription", "error")})
        rec["cached"] = True
        return rec
    t0 = time.monotonic()
    try:
        if engine.needs_audio:
            data, info = get_audio(client, rec, paths, cfg)
            if info.get("bytes", 0) < 1000:
                raise EngineError("recording is empty")
            raw = engine.transcribe(data, info, keyterms)
            norm = engine.normalize(raw, started, rec["direction"], cfg)
        else:  # GHL's own transcript: no audio, no keyterms
            info = {}
            norm = engine.normalize(engine.fetch(rec["message_id"]), started, rec["direction"], cfg,
                                    rec["duration_s"])
            if not norm["text"]:
                raise EngineError("GHL returned no transcription")
        minutes = (info.get("duration_s") or rec["duration_s"] or 0) / 60.0
        rec.update(recording="transcribed", language=norm["language"], confidence=norm["confidence"],
                   text=norm["text"], utterances=norm["utterances"], audio_events=norm["audio_events"])
        rec["engine"] = dict(engine.describe(), request_id=norm.get("request_id"),
                             keyterms=len(keyterms), wall_s=round(time.monotonic() - t0, 1),
                             est_cost_usd=estimate_cost_usd(minutes, engine.name, engine.cfg, bool(keyterms)))
    except ghl_client.GhlBlocked:
        raise
    except (EngineError, ghl_client.GhlError, ValueError, OSError) as exc:
        rec["error"] = str(exc)[:300]
        rec["recording"] = "too_large" if "too_large" in str(exc) else "failed"
        if fallback and ghl_engine is not None and ghl_engine is not engine \
                and rec["recording"] == "failed":
            try:
                raw = ghl_engine.fetch(rec["message_id"])
                norm = ghl_engine.normalize(raw, started, rec["direction"], cfg, rec["duration_s"])
                if norm["text"]:
                    rec.update(recording="fallback-ghl", language=norm["language"],
                               confidence=norm["confidence"], text=norm["text"],
                               utterances=norm["utterances"], engine=ghl_engine.describe())
            except ghl_client.GhlBlocked:
                raise
            except (ghl_client.GhlError, ValueError) as exc2:
                rec["error"] += f" | ghl fallback: {str(exc2)[:200]}"
    if compare_ghl and ghl_engine is not None and ghl_engine is not engine \
            and rec["recording"] == "transcribed":
        try:
            raw = ghl_engine.fetch(rec["message_id"])
            rec["ghl_transcription"] = ghl_engine.normalize(raw, started, rec["direction"], cfg,
                                                           rec["duration_s"])["text"]
        except ghl_client.GhlError as exc:
            rec["ghl_transcription"] = f"(unavailable: {str(exc)[:120]})"
    if rec["recording"] in ("transcribed", "fallback-ghl"):
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(json.dumps(rec, indent=1) + "\n")
    if not keep_audio:
        paths.wav(rec["message_id"]).unlink(missing_ok=True)
    return rec


def apply_note(rec, note):
    rec.update(recording="from-note", text=" ".join(u["text"] for u in note["utterances"]),
               utterances=note["utterances"],
               engine={"name": note.get("engine"), "model": note.get("engine"), "source": "contact note"})
    rec["note"] = {"ids": note.get("note_ids", []), "summary": note["summary"],
                   "next_steps": note["next_steps"], "parts": note["parts"],
                   "complete": note["complete"], "version": note.get("version", 1),
                   "ref": note.get("ref"), "speakers": note.get("speakers")}
    if note.get("staff_named"):
        rec["staff_named"] = note["staff_named"]
    tr = note.get("translation")
    if tr:
        rec["language"] = tr["language"]
        rec["translation"] = {"language": tr["language"], "utterances": tr["utterances"],
                              "complete": tr["complete"]}
    return rec


def apply_summary_comment(rec, comment):
    """v2: Summary and Next steps live in the internal comment, not the note."""
    note = rec.setdefault("note", {"ids": [], "summary": "", "next_steps": [], "parts": 0,
                                   "complete": False, "version": 2})
    note.update(summary=comment["summary"], next_steps=comment["next_steps"],
                comment_id=comment.get("comment_id"), ref=note.get("ref") or comment.get("ref"))
    if comment.get("staff_named"):
        rec["staff_named"] = comment["staff_named"]
    return rec


# --------------------------------------------------------------------------- listing

def note_summary_comment(m, comments, alarms):
    """Collect the Make scenario's call-summary comments while scanning messages, and
    raise an alarm if that footer ever sits on anything but an internal comment: the
    one way the summary could have reached a customer (methods/ghl-call-transcripts.md,
    the comment gate)."""
    body = m.get("body") or ""
    if "[call-summary v" not in body:
        return
    parsed = parse_call_summary(body)
    if not parsed:
        return
    if m.get("messageType") != INTERNAL_COMMENT:
        alarms.append(f"call summary posted as {m.get('messageType') or 'unknown type'} "
                      f"(message {m.get('id')}, conversation {m.get('conversationId')}, "
                      f"call {parsed['message_id']}) — not an internal comment; check whether "
                      f"the customer received it")
        return
    parsed.update(comment_id=m.get("id"), comment_type=m.get("messageType"),
                  author_user_id=m.get("userId"))
    comments.setdefault(parsed["message_id"], parsed)


def list_call_messages(client, cfg, since, until, message_ids=None, verbose=False,
                       comments=None, alarms=None):
    comments = {} if comments is None else comments
    alarms = [] if alarms is None else alarms
    convs = client.search_conversations(since)
    if verbose:
        print(f"[calls] {len(convs)} conversations active since {since.isoformat()}", file=sys.stderr)
    total_msgs, calls = 0, []
    for c in convs:
        for mt in cfg["message_types"]:
            msgs = client.list_messages(c["id"], message_type=mt)
            total_msgs += len(msgs)
            for m in msgs:
                m.setdefault("conversationId", c["id"])
                m.setdefault("contactId", c.get("contactId"))
                note_summary_comment(m, comments, alarms)
                if m.get("messageType") not in cfg["message_types"]:
                    continue  # the endpoint's type filter is not trusted
                if message_ids and m.get("id") not in message_ids:
                    continue
                if not message_ids and not in_window(m, since, until):
                    continue
                calls.append(m)
    seen, out = set(), []
    for m in sorted(calls, key=lambda m: message_time(m) or since):
        if m.get("id") not in seen:
            seen.add(m.get("id"))
            out.append(m)
    return out, {"conversations": len(convs), "messages_scanned": total_msgs}


# --------------------------------------------------------------------------- bake-off

def keyterm_hits(text, keyterms):
    low = (text or "").lower()
    return sorted({t for t in keyterms if len(t) > 3 and t.lower() in low})


def write_bakeoff(path, results, keyterms):
    """results: {message_id: {engine: rec}}. Markdown with full text — gitignored."""
    lines = [f"# Call transcription bake-off — {today()}", "",
             "Full transcripts: customer PII. This file lives in analysis/cache/ (gitignored). "
             "Score each call on product and supplier names, speaker turns, numbers and dates, "
             "and invented words.", ""]
    score = {}
    for mid, by_engine in results.items():
        any_rec = next(iter(by_engine.values()))
        lines += [f"## {mid} · {any_rec.get('direction')} · {fmt_clock(any_rec.get('duration_s'))} · "
                  f"{any_rec.get('started_at')}", ""]
        for name, rec in by_engine.items():
            hits = keyterm_hits(rec.get("text"), keyterms)
            spk = len({u.get("speaker") for u in rec.get("utterances") or []})
            e = rec.get("engine") or {}
            s = score.setdefault(name, {"calls": 0, "ok": 0, "speakers": 0, "keyterm_hits": 0,
                                        "conf": [], "cost": 0.0, "wall_s": 0.0})
            s["calls"] += 1
            s["ok"] += rec.get("recording") == "transcribed"
            s["speakers"] += spk
            s["keyterm_hits"] += len(hits)
            if isinstance(rec.get("confidence"), (int, float)):
                s["conf"].append(rec["confidence"])
            s["cost"] += e.get("est_cost_usd") or 0
            s["wall_s"] += e.get("wall_s") or 0
            lines += [f"### {name} — {rec.get('recording')} · speakers {spk} · confidence "
                      f"{rec.get('confidence')} · keyterms hit {len(hits)}", ""]
            if hits:
                lines += ["Keyterms heard: " + ", ".join(hits), ""]
            for u in rec.get("utterances") or []:
                lines.append(f"- [{fmt_clock(u.get('start_s'))}] **{u.get('speaker')}**: {u.get('text')}")
            if rec.get("error"):
                lines.append(f"- error: {rec['error']}")
            lines.append("")
        g = any_rec.get("ghl_transcription")
        if g:
            lines += ["### GHL's own transcript", "", g, ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    card = {k: {"calls": v["calls"], "transcribed": v["ok"], "speakers_total": v["speakers"],
                "keyterm_hits": v["keyterm_hits"],
                "mean_confidence": round(sum(v["conf"]) / len(v["conf"]), 3) if v["conf"] else None,
                "est_cost_usd": round(v["cost"], 4), "wall_s": round(v["wall_s"], 1)}
            for k, v in score.items()}
    return card


# --------------------------------------------------------------------------- main

def refuse_ingest_path(p):
    p = Path(p).resolve()
    if INGEST_DIR.resolve() in p.parents or p == INGEST_DIR.resolve():
        die("refusing to write under the daily ingest folder",
            "the orchestrator reads every *.json there; use analysis/cache/ghl-calls/")
    return p


def write_keyterms(cfg):
    terms = build_keyterms(cfg)
    out = REPO_ROOT / cfg["keyterms"]["published_file"]
    out.write_text(json.dumps({
        "_comment": "Generated by scripts/ghl_calls_pull.py --write-keyterms from platform-settings/ghl-calls.json "
                    "keyterms sources. Read by the Make scenario 'GHL Call -> Note' (raw GitHub URL on main-agents). "
                    "No customer data. Do not hand-edit; regenerate.",
        "generated_at": now_utc().isoformat(timespec="seconds").replace("+00:00", "Z"),
        "count": len(terms), "terms": terms}, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {out.relative_to(REPO_ROOT)} ({len(terms)} terms)")
    return 0


def probe(client, message_id, cfg):
    report = {"message_id": message_id, "attempts": []}
    for ver in (cfg["api"]["version"], "2021-07-28"):
        try:
            data, ctype = client.recording(message_id, version=ver)
            report["attempts"].append({"version": ver, "ok": True, "content_type": ctype,
                                       "wav": wav_info(data)})
            break
        except ghl_client.GhlBlocked:
            raise
        except ghl_client.GhlError as exc:
            report["attempts"].append({"version": ver, "ok": False, "error": str(exc)[:200]})
    print(json.dumps(report, indent=1))
    return 0 if any(a["ok"] for a in report["attempts"]) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    w = ap.add_mutually_exclusive_group()
    w.add_argument("--hours", type=float)
    w.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--engine")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--probe", metavar="MESSAGE_ID")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--message-id", action="append", default=[])
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--no-audio-cache", action="store_true")
    ap.add_argument("--ignore-notes", action="store_true")
    ap.add_argument("--compare-ghl", action="store_true")
    ap.add_argument("--bakeoff", metavar="ENGINES")
    ap.add_argument("--write-keyterms", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--print", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_registry()
    if args.write_keyterms:
        return write_keyterms(cfg)

    ghl_client.load_dotenv(REPO_ROOT / ".env")
    try:
        client = ghl_client.GhlClient(version=cfg["api"]["version"],
                                      min_interval=cfg["rate_limits"]["min_interval_ms"] / 1000.0,
                                      max_retries=cfg["rate_limits"]["max_retries"], verbose=args.verbose)
    except ghl_client.GhlError as exc:
        die(str(exc), "GHL_PIT_TOKEN and GHL_LOCATION_ID belong in .env")

    try:
        if args.probe:
            return probe(client, args.probe, cfg)
        return run(client, cfg, args)
    except ghl_client.GhlBlocked as exc:
        print(json.dumps({"status": "error", "host_blocked": True, "error": str(exc),
                          "hint": "allow the host in the environment's Network access; not worked around"},
                         indent=1), file=sys.stderr)
        return 3


def run(client, cfg, args):
    since, until = compute_window(args.hours, args.since, args.until, cfg)
    out_path = refuse_ingest_path(args.out) if args.out else \
        REPO_ROOT / cfg["outputs"]["run_file"].format(date=today())
    paths = Paths(cfg)
    people = people_by_ghl_id()
    errors = []

    comments, alarms = {}, []
    try:
        msgs, scan = list_call_messages(client, cfg, since, until, set(args.message_id) or None,
                                        args.verbose, comments=comments, alarms=alarms)
    except ghl_client.GhlBlocked:
        raise
    except ghl_client.GhlError as exc:
        doc = {"status": "error", "errors": [str(exc)[:300]], "pulled_at": now_utc().isoformat(),
               "window": {"since": since.isoformat(), "until": until.isoformat()}, "calls": []}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(doc, indent=1) + "\n")
        print(json.dumps(doc, indent=1), file=sys.stderr)
        return 1

    engine_names = [e.strip() for e in (args.bakeoff or args.engine or cfg["engine"]["default"]).split(",") if e.strip()]
    ghl_engine = GhlTranscriptionEngine(cfg["engine"]["ghl"], client=client)
    if not args.bakeoff and not args.engine and not args.dry_run and engine_names[0] != "ghl":
        env_var = cfg["engine"][engine_names[0]].get("env_var", "")
        if not os.environ.get(env_var) and cfg["fallback_to_ghl_transcription"]:
            # Daily run before the engine is set up: GHL's own transcript beats nothing.
            errors.append(f"{env_var} is not set — used GHL's own transcription instead of "
                          f"{engine_names[0]}")
            engine_names = ["ghl"]
    engines = [] if args.dry_run else [ghl_engine if n == "ghl" else make_engine(n, cfg)
                                       for n in engine_names]
    kt = {n: ([] if n == "ghl" else build_keyterms(cfg, n)) for n in engine_names}

    budget = Budget(cfg, args.limit)
    counts = {k: 0 for k in ("listed", "from_note", "transcribed", "fallback_ghl", "skipped_short",
                             "no_recording", "failed", "over_cap", "cached", "too_large")}
    notes_cache, calls, bake = {}, [], {}
    for m in msgs:
        rec = call_record(m, people)
        counts["listed"] += 1
        decision, reason = gate(m, cfg)  # the cap is applied after the note lookup
        if decision != "transcribe":
            rec["recording"], rec["error"] = decision, reason
            counts[{"none": "no_recording", "skipped-short": "skipped_short",
                    "over-cap": "over_cap"}[decision]] += 1
            calls.append(rec)
            continue
        if cfg.get("prefer_note") and not args.ignore_notes and rec["contact_id"]:
            if rec["contact_id"] not in notes_cache:
                try:
                    notes_cache[rec["contact_id"]] = client.notes(rec["contact_id"])
                except ghl_client.GhlBlocked:
                    raise
                except ghl_client.GhlError as exc:
                    notes_cache[rec["contact_id"]] = []
                    errors.append(f"notes for {rec['contact_id']}: {str(exc)[:160]}")
            note = find_call_note(notes_cache[rec["contact_id"]], rec["message_id"])
            if note:
                apply_note(rec, note)
                if rec["message_id"] in comments:
                    apply_summary_comment(rec, comments[rec["message_id"]])
                counts["from_note"] += 1
                calls.append(rec)
                continue
        if not budget.take(rec["duration_s"]):
            rec["recording"], rec["error"] = "over-cap", "per-run call or minute cap reached"
            counts["over_cap"] += 1
            calls.append(rec)
            continue
        if args.dry_run:
            rec["recording"] = "would-transcribe"
            calls.append(rec)
            continue
        by_engine = {}
        for eng in engines:
            r = transcribe_one(client, eng, dict(rec), cfg, kt[eng.name], paths,
                               refresh=args.refresh, fallback=cfg["fallback_to_ghl_transcription"] and not args.bakeoff,
                               compare_ghl=args.compare_ghl, ghl_engine=ghl_engine,
                               keep_audio=not args.no_audio_cache or eng is not engines[-1])
            by_engine[eng.name] = r
        primary = by_engine[engines[0].name]
        if args.bakeoff:
            bake[rec["message_id"]] = by_engine
        st = primary["recording"]
        counts["cached"] += bool(primary.get("cached"))
        counts[{"transcribed": "transcribed", "fallback-ghl": "fallback_ghl",
                "too_large": "too_large"}.get(st, "failed")] += 1
        if st not in TERMINAL_OK and primary.get("error"):
            errors.append(f"{rec['message_id']}: {primary['error'][:200]}")
        calls.append(primary)

    minutes = sum((c.get("duration_s") or 0) for c in calls if c.get("recording") in ("transcribed",)) / 60.0
    cost = sum(((c.get("engine") or {}).get("est_cost_usd") or 0) for c in calls if not c.get("cached"))
    failed = counts["failed"] + counts["too_large"]
    status = "partial" if failed or errors else "ok"
    doc = {
        "status": status, "errors": errors, "pulled_at": now_utc().isoformat(timespec="seconds"),
        "window": {"since": to_local_iso(since), "until": to_local_iso(until)},
        "dry_run": bool(args.dry_run), "counts": counts, "scan": scan,
        "engine": {"name": engine_names[0], **({k: v for k, v in (engines[0].describe().items() if engines else [])}),
                   "keyterms_used": len(kt.get(engine_names[0], []))},
        "minutes_transcribed": round(minutes, 1), "est_cost_usd": round(cost, 4),
        "ghl": client.stats(), "host_blocked": False, "alarms": alarms,
        "summary_comments": len(comments), "calls": calls,
    }
    if args.bakeoff and bake:
        bpath = REPO_ROOT / cfg["bakeoff"]["output"].format(date=today())
        doc["bakeoff"] = {"file": str(bpath.relative_to(REPO_ROOT)),
                          "scorecard": write_bakeoff(bpath, bake, kt[engine_names[0]])}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    summary = {"status": status, "run_file": str(out_path.relative_to(REPO_ROOT)) if out_path.is_relative_to(REPO_ROOT) else str(out_path),
               "counts": counts, "minutes": doc["minutes_transcribed"], "est_cost_usd": doc["est_cost_usd"],
               "errors": len(errors), "alarms": alarms}
    if "bakeoff" in doc:
        summary["bakeoff"] = doc["bakeoff"]
    print(json.dumps(doc if args.print else summary, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
