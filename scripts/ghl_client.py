#!/usr/bin/env python3
"""GoHighLevel (LeadConnector) API transport for call recordings and transcripts.

READ ONLY. Every request this module can make is a GET: urllib.request.Request is
always built without a method argument, and no write verb appears anywhere in this
file. tests/test_ghl_calls.py fails if one is ever added. Writing to GHL is the job
of ghl-actions-agent (separate token, approval file) and of the Make scenario
"GHL Call -> Note" (see methods/ghl-call-transcripts.md) — never of this module.

The only file in scripts/ that addresses services.leadconnectorhq.com. Used by
scripts/ghl_calls_pull.py. Not a CLI.

Environment (see .env.example):
    GHL_PIT_TOKEN     read-only private integration token. Needs
                      conversations.readonly, conversations/message.readonly
                      (recording + transcription) and contacts.readonly (notes).
    GHL_LOCATION_ID   the sub-account (location) id

Rate limiting: the PIT burst limit is 100 requests / 10 s, so requests are serial
with a 0.17 s floor between them (same constant as analysis/ghl_*.py). 401 is
retried along with 429/5xx because GHL intermittently rejects a valid PIT
mid-burst (observed 2026-07-29); a genuinely dead token still fails after the
retries run out.

Known shape uncertainties, handled defensively rather than assumed:
- /conversations/search returns lastMessageDate as epoch milliseconds in some
  payloads and ISO strings in others; parse_ts() accepts both.
- /conversations/{id}/messages nests the page as {"messages": {"messages": [...],
  "nextPage": bool, "lastMessageId": str}}; a flat list is accepted too.
- The `type` filter on the messages endpoint may be ignored; callers filter on
  messageType client-side regardless.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE = "https://services.leadconnectorhq.com"
USER_AGENT = "titan-agents/ghl_client (+read-only)"
RETRY_STATUSES = (401, 429, 500, 502, 503, 504)


class GhlError(RuntimeError):
    """A non-retryable failure talking to GHL. `.code` is the HTTP status or None."""

    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


class GhlBlocked(GhlError):
    """The environment's egress proxy refused the host. Never worked around."""


def load_dotenv(path):
    """Minimal .env loader — real env vars always win."""
    path = str(path)
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if val:
                os.environ.setdefault(key, val)


def classify_url_error(exc):
    """'host_blocked' for a proxy CONNECT refusal, else None (same test as
    scripts/supplier_site_pull.py)."""
    text = str(exc)
    if "tunnel connection failed" in text.lower() or ("403" in text and "CONNECT" in text):
        return "host_blocked"
    return None


def parse_ts(value):
    """Epoch-ms / epoch-s number or ISO string -> aware UTC datetime, else None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        n = float(value)
        if n > 1e11:  # milliseconds
            n /= 1000.0
        return datetime.fromtimestamp(n, tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class GhlClient:
    """GET-only, serial GHL client."""

    def __init__(self, token=None, location_id=None, version="2021-04-15",
                 min_interval=0.17, max_retries=5, timeout=60, verbose=False, opener=None):
        self.token = token or os.environ.get("GHL_PIT_TOKEN")
        self.location_id = location_id or os.environ.get("GHL_LOCATION_ID")
        missing = [n for n, v in (("GHL_PIT_TOKEN", self.token),
                                  ("GHL_LOCATION_ID", self.location_id)) if not v]
        if missing:
            raise GhlError("missing credentials: " + ", ".join(missing) +
                           " — set them in .env (see .env.example)")
        self.version = version
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.verbose = verbose
        self._open = opener or urllib.request.urlopen
        self._last = 0.0
        self.request_count = 0
        self.throttle_events = 0

    # -- transport ------------------------------------------------------------

    def _log(self, msg):
        if self.verbose:
            print(f"[ghl] {msg}", file=sys.stderr)

    def _url(self, path, params=None):
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}, doseq=True)
        return url

    def _request(self, url, accept, version):
        # No method argument: urllib sends GET for a request without a body.
        return urllib.request.Request(url, headers={
            "Authorization": "Bearer " + self.token,
            "Version": version or self.version,
            "Accept": accept,
            "User-Agent": USER_AGENT,
        })

    def _fetch(self, path, params=None, accept="application/json", version=None):
        """GET with throttle and retry. Returns (bytes, headers)."""
        url = self._url(path, params)
        last = None
        for attempt in range(self.max_retries):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.request_count += 1
            try:
                with self._open(self._request(url, accept, version), timeout=self.timeout) as r:
                    return r.read(), dict(r.headers.items())
            except urllib.error.HTTPError as e:
                body = e.read()[:400].decode("utf-8", "replace")
                last = GhlError(f"HTTP {e.code} on GET {path}: {body}", code=e.code)
                if e.code in RETRY_STATUSES:
                    self.throttle_events += 1
                    self._log(f"HTTP {e.code} on {path}; retry {attempt + 1}")
                    time.sleep(min(2 ** attempt, 16))
                    continue
                raise last
            except urllib.error.URLError as e:
                if classify_url_error(e) == "host_blocked":
                    raise GhlBlocked(f"egress proxy refused services.leadconnectorhq.com: {e}")
                last = GhlError(f"{type(e).__name__} on GET {path}: {e}")
                time.sleep(min(2 ** attempt, 16))
        raise last or GhlError(f"giving up on GET {path}")

    def get_json(self, path, params=None, version=None):
        data, _ = self._fetch(path, params, "application/json", version)
        return json.loads(data or b"{}")

    def get_bytes(self, path, params=None, accept="audio/x-wav, audio/*, */*", version=None):
        data, headers = self._fetch(path, params, accept, version)
        low = {k.lower(): v for k, v in headers.items()}
        return data, low.get("content-type", ""), low.get("content-disposition", "")

    # -- domain helpers (all GET) -------------------------------------------

    def search_conversations(self, since_utc, limit=100, max_pages=20):
        """Conversations whose last message is at or after since_utc, newest first."""
        out, params, pages = [], {"locationId": self.location_id,
                                  "sortBy": "last_message_date", "sort": "desc",
                                  "limit": limit}, 0
        seen = set()
        while pages < max_pages:
            page = self.get_json("/conversations/search", params)
            pages += 1
            rows = page.get("conversations") or []
            stop = not rows
            for c in rows:
                if c.get("id") in seen:
                    continue
                seen.add(c.get("id"))
                ts = parse_ts(c.get("lastMessageDate") or c.get("dateUpdated"))
                if ts is not None and ts < since_utc:
                    stop = True
                    break
                out.append(c)
            if stop or len(rows) < limit:
                break
            tail = rows[-1]
            cursor = tail.get("sort") or [tail.get("lastMessageDate")]
            nxt = cursor[0] if isinstance(cursor, list) and cursor else cursor
            if nxt is None or params.get("startAfterDate") == nxt:
                break  # cursor not advancing
            params["startAfterDate"] = nxt
        return out

    def list_messages(self, conversation_id, message_type="TYPE_CALL", limit=100, max_pages=10):
        out, params = [], {"limit": limit, "type": message_type}
        for _ in range(max_pages):
            page = self.get_json(f"/conversations/{conversation_id}/messages", params)
            block = page.get("messages", page)
            rows = block.get("messages", []) if isinstance(block, dict) else (block or [])
            out.extend(rows)
            if not isinstance(block, dict) or not block.get("nextPage"):
                break
            last_id = block.get("lastMessageId") or (rows[-1].get("id") if rows else None)
            if not last_id or params.get("lastMessageId") == last_id:
                break
            params["lastMessageId"] = last_id
        return out

    def notes(self, contact_id):
        page = self.get_json(f"/contacts/{contact_id}/notes", version="2021-07-28")
        return page.get("notes", []) if isinstance(page, dict) else []

    def recording(self, message_id, version=None):
        data, ctype, _ = self.get_bytes(
            f"/conversations/messages/{message_id}/locations/{self.location_id}/recording",
            version=version)
        return data, ctype

    def transcription(self, message_id):
        page = self.get_json(
            f"/conversations/locations/{self.location_id}/messages/{message_id}/transcription")
        if isinstance(page, list):
            return page
        return page.get("transcriptions") or page.get("data") or []

    def stats(self):
        return {"requests": self.request_count, "throttle_events": self.throttle_events,
                "version": self.version}
