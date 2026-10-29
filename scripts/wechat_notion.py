#!/usr/bin/env python3
"""
Read-only access to the WeChat Archive Notion database.

Used by scripts/wechat_pull.py (anywhere) and, for the stored tail of each chat,
by scripts/wechat_archive.py (Mac). The only request this module can make is a
data-source query: POST /v1/data_sources/<id>/query, which reads. It has no code
path that creates, updates or archives a page; the one insert lives in
wechat_archive.py, and tests/test_wechat.py fails if that ever changes.
"""

import json
import os
import time
import urllib.error
import urllib.request

NOTION = "https://api.notion.com/v1"


def load_dotenv(path):
    """Minimal .env loader — real env vars always win."""
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


def request(method, path, token, api_version, body=None, retries=4):
    """One Notion call with 429/5xx backoff. Returns parsed JSON."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            NOTION + path, data=data, method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": api_version,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = float(exc.headers.get("Retry-After") or 2 ** attempt)
                time.sleep(min(wait, 30))
                continue
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"Notion {method} {path} -> {exc.code}: {detail}") from None


def query(settings, token, filter_=None, sorts=None, page_size=100, limit=None):
    """Query the archive data source, following cursors up to `limit` rows."""
    n = settings["notion"]
    path = f"/data_sources/{n['data_source_id']}/query"
    rows, cursor = [], None
    while True:
        body = {"page_size": min(page_size, 100)}
        if filter_:
            body["filter"] = filter_
        if sorts:
            body["sorts"] = sorts
        if cursor:
            body["start_cursor"] = cursor
        out = request("POST", path, token, n["api_version"], body)
        rows.extend(parse_row(settings, r) for r in out.get("results", []))
        if limit is not None and len(rows) >= limit:
            return rows[:limit]
        if not out.get("has_more"):
            return rows
        cursor = out.get("next_cursor")


def _plain(prop):
    if not prop:
        return ""
    items = prop.get("title") or prop.get("rich_text") or []
    return "".join(i.get("plain_text", "") for i in items)


def parse_row(settings, page):
    p = settings["notion"]["properties"]
    props = page.get("properties", {})

    def date(name):
        d = (props.get(name) or {}).get("date")
        return d.get("start") if d else None

    def select(name):
        s = (props.get(name) or {}).get("select")
        return s.get("name") if s else None

    return {
        "page_id": page.get("id"),
        "url": page.get("url"),
        "chat": _plain(props.get(p["chat"])),
        "sender": select(p["sender"]),
        "text": _plain(props.get(p["text"])) or _plain(props.get(p["title"])),
        "kind": select(p["kind"]),
        "sent_at": date(p["sent_at"]),
        "archived_at": date(p["archived_at"]),
        "sequence": (props.get(p["sequence"]) or {}).get("number"),
        "key": _plain(props.get(p["key"])),
        "gap_before": bool((props.get(p["gap_before"]) or {}).get("checkbox")),
        "run": _plain(props.get(p["run"])),
    }


def chat_tail(settings, token, chat, n):
    """The last n stored rows of one chat, oldest first."""
    p = settings["notion"]["properties"]
    rows = query(
        settings, token,
        filter_={"property": p["chat"], "rich_text": {"equals": chat}},
        sorts=[{"property": p["sequence"], "direction": "descending"}],
        page_size=n, limit=n,
    )
    return list(reversed(rows))


def heartbeats(settings, token, n=10):
    """The newest n archiver heartbeats, newest first, Text parsed as JSON."""
    import json as _json
    p = settings["notion"]["properties"]
    rows = query(
        settings, token,
        filter_={"property": p["chat"],
                 "rich_text": {"equals": settings["notion"]["heartbeat_chat"]}},
        sorts=[{"property": p["archived_at"], "direction": "descending"}],
        page_size=n, limit=n)
    out = []
    for r in rows:
        try:
            detail = _json.loads(r["text"])
        except ValueError:
            detail = {"raw": r["text"][:300]}
        out.append({"archived_at": r["archived_at"], **detail})
    return out
