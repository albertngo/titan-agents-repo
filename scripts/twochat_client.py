#!/usr/bin/env python3
"""2Chat API transport for whatsapp-ingest-agent (the API catch-up lane).

READ ONLY. Every request this module can make is a GET: urllib.request.Request is
always built without a method argument, and no write verb appears anywhere in this
file. tests/test_whatsapp_ingest.py fails if one is ever added. Sending WhatsApp
messages stays with Make (connection 3776292, the alarm modules) — never this module.

The only file in scripts/ that addresses api.p.2chat.io. Used by
scripts/whatsapp_pull.py. Not a CLI.

Environment (see .env.example):
    TWOCHAT_API_KEY   the 2Chat account API key (sent as X-User-API-Key)

Endpoints used (developers.2chat.co, checked 2026-10-29):
    GET /open/whatsapp/messages/{connected_number}         1-to-1 messages
    GET /open/whatsapp/messages/{connected_number}/{peer}  one peer's messages
    GET /open/whatsapp/groups/{connected_number}           groups the number is in
2Chat documents no group-history endpoint, which is why group messages come from the
Make webhook capture lane instead (methods/whatsapp-ingest.md). The API also only
returns messages sent or received after the number was connected to 2Chat.

Field names in responses are not fully documented; parse_message() in
scripts/whatsapp_pull.py reads them defensively and the first live probe
(methods/whatsapp-ingest.md, build step 1) pins them.
"""

import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.p.2chat.io"
USER_AGENT = "titan-agents/twochat_client (+read-only)"
RETRY_STATUSES = (429, 500, 502, 503, 504)


class TwoChatError(RuntimeError):
    """A non-retryable failure talking to 2Chat. `.code` is the HTTP status or None."""

    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


class TwoChatBlocked(TwoChatError):
    """The environment's egress proxy refused the host. Never worked around."""


def classify_url_error(exc):
    """'host_blocked' for a proxy CONNECT refusal, else None (same test as
    scripts/ghl_client.py)."""
    text = str(exc)
    if "tunnel connection failed" in text.lower() or ("403" in text and "CONNECT" in text):
        return "host_blocked"
    return None


class TwoChatClient:
    """GET-only, serial 2Chat client."""

    def __init__(self, api_key=None, min_interval=0.25, max_retries=4, timeout=60,
                 verbose=False, opener=None):
        self.api_key = api_key or os.environ.get("TWOCHAT_API_KEY")
        if not self.api_key:
            raise TwoChatError("missing credentials: TWOCHAT_API_KEY — set it in .env "
                               "(see .env.example)")
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.verbose = verbose
        self._open = opener or urllib.request.urlopen
        self._last = 0.0
        self.request_count = 0

    def _log(self, msg):
        if self.verbose:
            print(f"[2chat] {msg}", file=sys.stderr)

    def _url(self, path, params=None):
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}, doseq=True)
        return url

    def _request(self, url):
        # No method argument: urllib sends GET for a request without a body.
        return urllib.request.Request(url, headers={
            "X-User-API-Key": self.api_key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        })

    def get_json(self, path, params=None):
        url = self._url(path, params)
        last = None
        for attempt in range(self.max_retries):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.request_count += 1
            try:
                with self._open(self._request(url), timeout=self.timeout) as r:
                    return json.loads(r.read() or b"{}")
            except urllib.error.HTTPError as e:
                body = e.read()[:300].decode("utf-8", "replace")
                last = TwoChatError(f"HTTP {e.code} on GET {path}: {body}", code=e.code)
                if e.code in RETRY_STATUSES:
                    self._log(f"HTTP {e.code} on {path}; retry {attempt + 1}")
                    time.sleep(min(2 ** attempt, 16))
                    continue
                raise last
            except urllib.error.URLError as e:
                if classify_url_error(e) == "host_blocked":
                    raise TwoChatBlocked(f"egress proxy refused api.p.2chat.io: {e}")
                last = TwoChatError(f"{type(e).__name__} on GET {path}: {e}")
                time.sleep(min(2 ** attempt, 16))
            except (http.client.HTTPException, ConnectionError, TimeoutError) as e:
                last = TwoChatError(f"{type(e).__name__} on GET {path}: {e}")
                time.sleep(min(2 ** attempt, 16))
        raise last or TwoChatError(f"giving up on GET {path}")

    # -- domain helpers (all GET) -------------------------------------------

    def messages(self, number, peer=None, max_pages=10):
        """1-to-1 messages for a connected number (optionally one peer), newest first.
        Pages until an empty page or max_pages."""
        path = "/open/whatsapp/messages/" + urllib.parse.quote(number)
        if peer:
            path += "/" + urllib.parse.quote(peer)
        out = []
        for page in range(max_pages):
            data = self.get_json(path, {"page_number": page} if page else None)
            if isinstance(data, dict):
                rows = data.get("messages") or data.get("data") or []
            else:
                rows = data or []
            if not rows:
                break
            out.extend(rows)
        return out

    def groups(self, number):
        """Groups the connected number belongs to: [{uuid, wa_group_name, ...}]."""
        data = self.get_json("/open/whatsapp/groups/" + urllib.parse.quote(number))
        if isinstance(data, list):
            return data
        return data.get("data") or data.get("groups") or []

    def stats(self):
        return {"requests": self.request_count}
