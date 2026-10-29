#!/usr/bin/env python3
"""
Read-only WeChat Archive puller for wechat-ingest-agent, and the search tool for
questions about past WeChat conversations.

Reads the private WeChat Archive database in Notion that scripts/wechat_archive.py
fills from Albert's Mac. Read-only twice over: it goes through
scripts/wechat_notion.py, which can only query, and its token is a Notion
integration with Read content only.

Why a script and not the Notion connector: a claude.ai connector is
session-attached and dies on scheduled runs (see outlook-ingest-agent). A token
in .env works everywhere.

Usage:
    python3 scripts/wechat_pull.py                       # the ingest window
    python3 scripts/wechat_pull.py --hours 72
    python3 scripts/wechat_pull.py --search "price list"   # every chat, all time
    python3 scripts/wechat_pull.py --search 涨价 --chat "Tosca Flooring"
    python3 scripts/wechat_pull.py --chat "Tosca Flooring" --hours 720

Output is JSON on stdout (or --out). It carries full message text: write it
under analysis/cache/ (gitignored), never into ingest/ — the repo is public.

Env (see .env.example):
    NOTION_WECHAT_READ_TOKEN
"""

import argparse
import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wechat_core as core  # noqa: E402
import wechat_notion as notion  # noqa: E402


def heartbeat(settings, token):
    rows = notion.heartbeats(settings, token, n=1)
    return rows[0] if rows else None


def pull(settings, token, hours=None, chat=None, search=None, now=None):
    p = settings["notion"]["properties"]
    hb_chat = settings["notion"]["heartbeat_chat"]
    now = now or core.now_toronto()
    conds = [{"property": p["chat"], "rich_text": {"does_not_equal": hb_chat}}]
    if chat:
        conds.append({"property": p["chat"], "rich_text": {"equals": chat}})
    if search:
        conds.append({"property": p["text"], "rich_text": {"contains": search}})
    since = None
    if hours is not None:
        since = (now - timedelta(hours=hours)).isoformat()
        conds.append({"property": p["archived_at"], "date": {"on_or_after": since}})
    rows = notion.query(
        settings, token, filter_={"and": conds},
        sorts=[{"property": p["archived_at"], "direction": "ascending"},
               {"property": p["sequence"], "direction": "ascending"}],
        limit=5000)

    chats = {}
    for r in rows:
        c = chats.setdefault(r["chat"], {"chat": r["chat"], "count": 0, "gap": False,
                                         "first_url": r["url"], "messages": []})
        c["count"] += 1
        c["gap"] = c["gap"] or r["gap_before"]
        c["messages"].append({k: r[k] for k in (
            "sequence", "sender", "kind", "sent_at", "archived_at", "text", "url")})
    for c in chats.values():
        c["messages"].sort(key=lambda m: m["sequence"] or 0)
        last = c["messages"][-1]
        c["last_sender"] = last["sender"]
        c["last_sent_at"] = last["sent_at"]

    return {
        "status": "ok",
        "errors": [],
        "since": since,
        "search": search,
        "count": len(rows),
        "chats": sorted(chats.values(), key=lambda c: c["messages"][-1]["archived_at"] or "",
                        reverse=True),
        "heartbeat": heartbeat(settings, token),
        "database_url": settings["notion"]["database_url"],
    }


def main():
    ap = argparse.ArgumentParser(description="Read the WeChat Archive (read-only).")
    ap.add_argument("--hours", type=float, help="archived in the last N hours")
    ap.add_argument("--chat", help="one chat, by its sidebar name")
    ap.add_argument("--search", help="text contained in the message")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    args = ap.parse_args()

    notion.load_dotenv(os.path.join(core.REPO_ROOT, ".env"))
    settings = core.load_settings()
    token = os.environ.get("NOTION_WECHAT_READ_TOKEN")
    if not token:
        out = {"status": "error", "errors": ["NOTION_WECHAT_READ_TOKEN missing from .env"],
               "chats": [], "count": 0, "heartbeat": None}
    else:
        hours = args.hours
        if hours is None and not args.search and not args.chat:
            hours = settings["ingest"]["window_hours"]
        try:
            out = pull(settings, token, hours=hours, chat=args.chat, search=args.search)
        except Exception as exc:
            out = {"status": "error", "errors": [str(exc)[:500]], "chats": [], "count": 0,
                   "heartbeat": None}

    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(text)
        print(json.dumps({"status": out["status"], "count": out.get("count", 0),
                          "out": args.out}))
    else:
        print(text)
    return 0 if out["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
