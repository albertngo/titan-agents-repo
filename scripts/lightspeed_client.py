#!/usr/bin/env python3
"""Lightspeed Retail (X-Series) API transport for the Titan catalogue pipeline.

READ ONLY. This class exposes get() and paginate() and nothing else. The HTTP verb
is a parameter of the private _send() so retry, throttle and error handling are
written once, but no write verb appears in this file and nothing here can be made to
send one without editing it.

The write side is a separate module, scripts/lightspeed_write.py, which subclasses
this one to add post() and put(). Keeping them apart means the read path — the daily
catalogue pull — stays reviewable on its own, and a reader can tell at a glance which
scripts are capable of changing the POS. tests/test_lightspeed.py fails if a write
verb ever appears in this file or in lightspeed_pull.py.

Titan is on X-Series (formerly Vend), not R-Series. Connection config — base URL
template, pinned API version, pagination and rate-limit tuning — lives in
platform-settings/lightspeed.json; nothing here is hardcoded except the shape of
the HTTP call itself.

Environment (see .env.example):
    LIGHTSPEED_DOMAIN_PREFIX   the <prefix> in <prefix>.retail.lightspeed.app
    LIGHTSPEED_PERSONAL_TOKEN  personal token, Setup > Personal tokens
    LIGHTSPEED_API_VERSION     optional; overrides api.api_version in the registry

A personal token carries the same data access as an Admin user and cannot be
scoped. Keep it in .env with an expiry set, never in a cloud env var.

Rate limiting: two independent limiters. A leaky bucket sized by register count,
and a burst limiter on 1-second fixed windows — so the minimum interval between
requests matters more than average throughput. Both announce themselves with
Retry-After and X-LS-API-RateLimit-Type when they block. Retry-After is honoured
in both the integer-seconds and the RFC 1123 HTTP-date forms the API uses.

Used by scripts/lightspeed_pull.py. Not a CLI.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "platform-settings" / "lightspeed.json"

USER_AGENT = "titan-agents/lightspeed_client (+read-only)"


class LightspeedError(RuntimeError):
    """Any non-retryable failure talking to Lightspeed."""


def load_config(path: Path = REGISTRY) -> dict:
    """The Lightspeed registry. Single source for every id and tunable."""
    return json.loads(path.read_text())


def _retry_after_seconds(value: str, now=None) -> float | None:
    """Retry-After as seconds, accepting both integer-seconds and HTTP-date.

    Lightspeed documents the RFC 1123 date form; integer seconds is the more
    common convention and is accepted defensively. Returns None if neither
    parses, so the caller falls back to its own backoff rather than sleeping on
    a misread header.
    """
    value = (value or "").strip()
    if not value:
        return None
    try:
        return max(0.0, float(int(value)))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(0.0, (when - now).total_seconds())


class LightspeedClient:
    """GET-only client for the X-Series API.

    Serial by construction: one request at a time, with a floor on the interval
    between them. Concurrency would trip the burst limiter for no gain — there is
    no bulk endpoint, so throughput is bounded by the limiter either way.
    """

    def __init__(self, domain_prefix=None, token=None, config=None, verbose=False):
        self.cfg = config or load_config()
        api = self.cfg["api"]

        self.domain_prefix = domain_prefix or os.environ.get("LIGHTSPEED_DOMAIN_PREFIX")
        self.token = token or os.environ.get("LIGHTSPEED_PERSONAL_TOKEN")
        missing = [n for n, v in (("LIGHTSPEED_DOMAIN_PREFIX", self.domain_prefix),
                                  ("LIGHTSPEED_PERSONAL_TOKEN", self.token)) if not v]
        if missing:
            raise LightspeedError(
                "missing credentials: " + ", ".join(missing) +
                ". Generate a personal token at Setup > Personal tokens (set an "
                "expiry) and put both in .env — see .env.example."
            )

        self.base_url = api["base_url_template"].format(domain_prefix=self.domain_prefix)
        self.api_version = os.environ.get("LIGHTSPEED_API_VERSION") or api["api_version"]

        rl = self.cfg["rate_limits"]
        self.min_interval = rl["min_interval_ms"] / 1000.0
        self.max_retries = rl["max_retries"]
        self.retry_after_header = rl["retry_after_header"]
        self.limiter_type_header = rl["limiter_type_header"]

        pg = api["pagination"]
        self.cursor_param = pg["cursor_param"]
        self.page_size_param = pg["page_size_param"]
        self.page_size = pg["page_size"]
        self.cursor_field = pg["cursor_field"]

        self.verbose = verbose
        self._last_request_at = 0.0
        self.request_count = 0
        self.throttle_events = []

    # -- internals ---------------------------------------------------------

    def _log(self, msg):
        if self.verbose:
            print(f"[lightspeed] {msg}", file=sys.stderr)

    def _respect_min_interval(self):
        gap = time.monotonic() - self._last_request_at
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)

    def _open(self, url, method, body=None):
        data = None
        req = urllib.request.Request(url, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", USER_AGENT)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        self._respect_min_interval()
        self._last_request_at = time.monotonic()
        self.request_count += 1
        return urllib.request.urlopen(req, data=data, timeout=60)

    def _send(self, method, path, params=None, body=None):
        """One request, with rate-limit retries. Returns the decoded JSON body.

        `method` is a parameter rather than a literal so retry, throttle and error
        handling live in one place while this class still exposes only get(). The
        write verbs are introduced deliberately, and only in
        scripts/lightspeed_write.py.

        Retries cover 429 and 5xx. Harmless for GET; on the write side it is exactly
        why LightspeedWriter re-reads to confirm rather than trusting a retried
        response, since a 5xx can follow a change that actually landed.
        """
        url = self.base_url.rstrip("/") + path
        if params:
            url += "?" + urllib.parse.urlencode(params)

        for attempt in range(self.max_retries + 1):
            try:
                with self._open(url, method, body) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw) if raw.strip() else {}
            except urllib.error.HTTPError as e:
                retryable = e.code == 429 or 500 <= e.code < 600
                if not retryable or attempt == self.max_retries:
                    detail = ""
                    try:
                        detail = e.read().decode("utf-8", "replace")[:500]
                    except Exception:
                        pass
                    raise LightspeedError(
                        f"HTTP {e.code} on {url}"
                        + (f" (limiter: {e.headers.get(self.limiter_type_header)})"
                           if e.code == 429 else "")
                        + (f": {detail}" if detail else "")
                    ) from e

                wait = _retry_after_seconds(e.headers.get(self.retry_after_header))
                if wait is None:
                    wait = self.min_interval * (2 ** attempt)
                limiter = e.headers.get(self.limiter_type_header) or f"http-{e.code}"
                self.throttle_events.append({"limiter": limiter, "waited_s": round(wait, 3),
                                             "attempt": attempt + 1})
                self._log(f"throttled by {limiter}, sleeping {wait:.2f}s "
                          f"(attempt {attempt + 1}/{self.max_retries})")
                time.sleep(wait)
            except urllib.error.URLError as e:
                if attempt == self.max_retries:
                    raise LightspeedError(f"network error on {url}: {e.reason}") from e
                wait = self.min_interval * (2 ** attempt)
                self._log(f"network error ({e.reason}), retrying in {wait:.2f}s")
                time.sleep(wait)

        raise LightspeedError(f"exhausted retries on {url}")

    # -- public ------------------------------------------------------------

    def get(self, path, params=None):
        """One GET. This class exposes no other verb."""
        return self._send("GET", path, params=params)

    def paginate(self, path, page_size=None, start_after=None, max_pages=None):
        """Yield every record from a collection endpoint, page by page.

        X-Series pages on a resource cursor: each record carries a `version`, and
        `after=<version>` asks for everything above it. A page shorter than
        page_size ends the walk.

        The envelope is read defensively — records under `data` if present, else a
        bare list — and the next cursor is taken from the response's own version
        block when it has one, else from the highest record version seen. Run
        lightspeed_pull.py --probe to dump the real shape before trusting either.

        Two guards, because getting this wrong silently duplicates or drops
        products rather than failing:

        * Records at or below the requested cursor are dropped. `after` is
          documented as exclusive; this holds the walk correct if it is ever
          inclusive, instead of emitting the boundary record on every page.
        * A cursor that does not advance ends the walk BEFORE its page is
          yielded, so a server that keeps returning the same page cannot emit
          duplicates or spin forever.
        """
        page_size = page_size or self.page_size
        after = start_after
        pages = 0

        while True:
            params = {self.page_size_param: page_size}
            if after is not None:
                params[self.cursor_param] = after

            body = self.get(path, params)
            records = body.get("data", body) if isinstance(body, dict) else body
            if not isinstance(records, list):
                raise LightspeedError(
                    f"unexpected response envelope from {path}: expected a list of "
                    f"records under 'data', got {type(records).__name__}. "
                    "Re-run with --probe and reconcile api.pagination in "
                    "platform-settings/lightspeed.json."
                )
            if not records:
                return

            next_after = None
            version_block = body.get("version") if isinstance(body, dict) else None
            if isinstance(version_block, dict):
                next_after = version_block.get("max")
            if next_after is None:
                seen = [r.get(self.cursor_field) for r in records
                        if isinstance(r, dict) and r.get(self.cursor_field) is not None]
                next_after = max(seen) if seen else None
            if next_after is None:
                raise LightspeedError(
                    f"cannot derive the next cursor from {path}: no version block and "
                    f"no '{self.cursor_field}' on any record. Re-run with --probe."
                )

            if after is not None and next_after <= after:
                self._log(f"cursor did not advance past {after}; stopping")
                return

            fresh = records
            if after is not None:
                fresh = [r for r in records
                         if not (isinstance(r, dict)
                                 and r.get(self.cursor_field) is not None
                                 and r[self.cursor_field] <= after)]
            for record in fresh:
                yield record

            pages += 1
            self._log(f"page {pages}: {len(fresh)} of {len(records)} records "
                      f"(after={after} -> {next_after})")

            after = next_after

            if len(records) < page_size:
                return
            if max_pages and pages >= max_pages:
                self._log(f"stopping at --max-pages {max_pages}")
                return

    def products_path(self):
        return self.cfg["api"]["endpoints"]["products"]

    def stats(self):
        return {"requests": self.request_count,
                "throttle_events": self.throttle_events,
                "api_version": self.api_version}
