#!/usr/bin/env python3
"""
WeChat -> Notion archiver. Runs on Albert's Mac only (launchd, early morning).

Reads WeChat for Mac through the macOS Accessibility API, using the read
functions of the `wechat-mcp-server` package (BiboyQG/WeChat-MCP), and inserts
every message not yet recorded into the private WeChat Archive database in
Notion. It never sends, replies, adds a contact or posts: those functions of the
package are never imported here, and tests/test_wechat.py fails if one is.

The reader drives the real app: it brings WeChat to the front, clicks a chat in
the sidebar and scrolls. So it starts only on an unlocked screen whose keyboard
and mouse have been idle for a while, and stops between chats the moment
someone touches the machine. Every run, including a skipped one, writes one
heartbeat row so the cloud ingester can tell a quiet day from a dead Mac.

This is the only file in the repo that writes to the archive, and the only write
it can make is POST /v1/pages into that one data source. Its Notion integration
has Insert content and Read content, never Update, so no row can be edited or
deleted even by mistake.

Usage (on the Mac, from the repo root):
    python3 scripts/wechat_archive.py --dry-run            # read, print, write nothing
    python3 scripts/wechat_archive.py --dry-run --chat "Tosca Flooring"
    python3 scripts/wechat_archive.py                      # the launchd run
    python3 scripts/wechat_archive.py --no-idle-check      # supervised run at the desk

Env (.env on the Mac, see .env.example):
    NOTION_WECHAT_WRITE_TOKEN

Method: methods/wechat-archive.md. Settings: platform-settings/wechat.json.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wechat_core as core  # noqa: E402
import wechat_notion as notion  # noqa: E402

ARCHIVER_VERSION = "1"


class InUse(Exception):
    """Someone started using the Mac mid-run."""


class MacReader:
    """The only code that touches WeChat. Read functions of wechat_mcp only."""

    def __init__(self):
        # wechat_mcp logs chat names to ./logs by default: that would be the repo.
        os.environ.setdefault("WECHAT_MCP_LOG_DIR",
                              os.path.expanduser("~/Library/Logs/titan-wechat-archive"))
        from wechat_mcp.wechat_accessibility import (
            _normalize_chat_title,
            click_element_center,
            collect_chat_elements,
            get_current_chat_name,
            get_wechat_ax_app,
        )
        from wechat_mcp.fetch_messages_by_chat_utils import fetch_recent_messages
        self._click = click_element_center
        self._collect = collect_chat_elements
        self._current = get_current_chat_name
        self._app = get_wechat_ax_app
        self._fetch = fetch_recent_messages
        self._norm = _normalize_chat_title

    @staticmethod
    def screen_locked():
        import Quartz
        info = Quartz.CGSessionCopyCurrentDictionary() or {}
        return bool(info.get("CGSSessionScreenIsLocked"))

    @staticmethod
    def idle_seconds():
        import Quartz
        return Quartz.CGEventSourceSecondsSinceLastEventType(
            Quartz.kCGEventSourceStateHIDSystemState, Quartz.kCGAnyInputEventType)

    def list_chats(self):
        return list(self._collect(self._app()).keys())

    def read_chat(self, chat, last_n):
        """Open `chat` from the sidebar and return its last messages, oldest first."""
        elements = self._collect(self._app())
        el = elements.get(chat)
        if el is None:
            raise RuntimeError("not in the sidebar any more")
        self._click(el)
        time.sleep(0.6)
        opened = self._current()
        # Never file one chat's messages under another chat's name.
        if opened is None or self._norm(opened) != self._norm(chat):
            raise RuntimeError(f"opened {opened!r} instead")
        return [m.to_dict() for m in self._fetch(last_n=last_n)]


class NotionStore:
    def __init__(self, settings, token):
        self.s = settings
        self.token = token
        self.p = settings["notion"]["properties"]

    def tail(self, chat, n):
        return notion.chat_tail(self.s, self.token, chat, n)

    def heartbeats(self, n):
        return notion.heartbeats(self.s, self.token, n)

    def insert(self, row, run, archived_at):
        p = self.p
        text = row["text"]
        props = {
            p["title"]: {"title": [{"text": {"content": text[:100]}}]},
            p["chat"]: {"rich_text": [{"text": {"content": row["chat"][:2000]}}]},
            p["sender"]: {"select": {"name": row["sender"]}},
            p["text"]: {"rich_text": [{"text": {"content": text[i:i + 2000]}}
                                      for i in range(0, min(len(text), 200000), 2000)][:100]},
            p["kind"]: {"select": {"name": row["kind"]}},
            p["archived_at"]: {"date": {"start": archived_at}},
            p["sequence"]: {"number": row["sequence"]},
            p["key"]: {"rich_text": [{"text": {"content": row["key"]}}]},
            p["gap_before"]: {"checkbox": bool(row.get("gap_before"))},
            p["run"]: {"rich_text": [{"text": {"content": run}}]},
        }
        if row.get("sent_at"):
            props[p["sent_at"]] = {"date": {"start": row["sent_at"]}}
        body = {
            "parent": {"type": "data_source_id",
                       "data_source_id": self.s["notion"]["data_source_id"]},
            "properties": props,
        }
        notion.request("POST", "/pages", self.token, self.s["notion"]["api_version"], body)
        time.sleep(0.34)  # Notion allows ~3 requests a second


def mac_free(reader, settings, check):
    """(True, None) when the Mac is unlocked and idle, else (False, why)."""
    if not check:
        return True, None
    if reader.screen_locked():
        return False, "screen locked"
    idle = reader.idle_seconds()
    if idle < settings["archive"]["idle_seconds_required"]:
        return False, f"in use (idle {int(idle)} s)"
    return True, None


def last_completed(store):
    """archived_at of the newest ok/partial heartbeat, or None."""
    for hb in store.heartbeats(20):
        # A supervised one-chat run doesn't count as the day's run.
        if hb.get("status") in ("ok", "partial") and not hb.get("only_chat"):
            return hb.get("archived_at")
    return None


def repeated_error(store, summary, hours=6):
    """True when the newest heartbeat is the same error, written < hours ago."""
    try:
        newest = store.heartbeats(1)
    except Exception:
        return False
    if not newest or newest[0].get("status") != "error":
        return False
    if newest[0].get("reason") != summary.get("reason"):
        return False
    from datetime import datetime
    then = datetime.fromisoformat(newest[0]["archived_at"])
    return (core.now_toronto() - then).total_seconds() < hours * 3600


def keep_awake():
    """Hold off display and system sleep for as long as this process lives."""
    import subprocess
    try:
        subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())])
    except OSError:
        pass


def archive(reader, store, settings, now, only_chat=None, dry_run=False,
            idle_check=True):
    """Archive every unrecorded message. Returns the run summary."""
    a = settings["archive"]
    kinds = settings["parse"]["kind_patterns"]
    run = core.run_id(now)
    stamp = now.isoformat()
    summary = {"run": run, "archiver_version": ARCHIVER_VERSION, "status": "ok",
               "reason": None, "dry_run": dry_run, "only_chat": only_chat, "chats_read": 0,
               "messages_new": 0, "gaps": [], "errors": [], "chats": []}

    ok, why = mac_free(reader, settings, idle_check)
    if not ok:
        summary.update(status="skipped", reason=why)
        return summary

    skip = set(a["skip_chats"]) | {settings["notion"]["heartbeat_chat"]}
    chats = [only_chat] if only_chat else [
        c for c in reader.list_chats() if c not in skip][:a["max_chats"]]

    try:
        for chat in chats:
            if idle_check and reader.idle_seconds() < 5:
                raise InUse()
            try:
                tail = store.tail(chat, a["stored_tail_compare"]) if store else []
                n = a["tail_check_messages"] if tail else a["first_run_messages"]
                msgs = core.annotate(reader.read_chat(chat, n), now, kinds)
                rows, aligned = core.plan_chat(chat, msgs, tail, a["min_overlap"])
                if tail and not aligned:
                    msgs = core.annotate(
                        reader.read_chat(chat, a["backfill_cap_messages"]), now, kinds)
                    rows, aligned = core.plan_chat(chat, msgs, tail, a["min_overlap"])
                    if not aligned:
                        summary["gaps"].append(chat)
            except InUse:
                raise
            except Exception as exc:  # one chat failing never stops the others
                summary["errors"].append({"chat": chat, "error": str(exc)[:300]})
                continue
            summary["chats_read"] += 1
            written = 0
            if not dry_run and store:
                for row in rows:
                    try:
                        store.insert(row, run, stamp)
                    except Exception as exc:
                        # Stop this chat: a hole mid-sequence would misalign the next run.
                        summary["errors"].append({"chat": chat, "error": str(exc)[:300]})
                        break
                    written += 1
            else:
                written = len(rows)
            summary["messages_new"] += written
            entry = {"chat": chat, "new": written}
            if dry_run:
                entry["preview"] = [{k: r[k] for k in ("sender", "kind", "sent_at", "text")}
                                    for r in rows[-5:]]
            summary["chats"].append(entry)
    except InUse:
        summary.update(status="interrupted", reason="the Mac was used mid-run")

    if summary["errors"] and summary["status"] == "ok":
        summary["status"] = "partial"
    return summary


def write_heartbeat(store, settings, summary, now):
    text = json.dumps({k: v for k, v in summary.items() if k not in ("chats",)},
                      ensure_ascii=False)
    row = {"chat": settings["notion"]["heartbeat_chat"], "sender": "Unknown",
           "kind": "system", "text": text, "sent_at": now.isoformat(),
           "sequence": 0, "key": summary["run"], "gap_before": False}
    store.insert(row, summary["run"], now.isoformat())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="read and print, write nothing")
    ap.add_argument("--chat", help="archive only this sidebar chat")
    ap.add_argument("--no-idle-check", action="store_true",
                    help="run now even if the Mac is in use (supervised runs)")
    ap.add_argument("--no-notion", action="store_true",
                    help="with --dry-run: don't read stored tails either")
    ap.add_argument("--force", action="store_true",
                    help="run even if a run completed recently or it's outside the window")
    args = ap.parse_args()

    notion.load_dotenv(os.path.join(core.REPO_ROOT, ".env"))
    settings = core.load_settings()
    now = core.now_toronto()

    store = None
    if not args.no_notion:
        token = os.environ.get("NOTION_WECHAT_WRITE_TOKEN")
        if not token:
            print(json.dumps({"status": "error",
                              "error": "NOTION_WECHAT_WRITE_TOKEN missing from .env"}))
            return 2
        store = NotionStore(settings, token)
    elif not args.dry_run:
        print(json.dumps({"status": "error", "error": "--no-notion needs --dry-run"}))
        return 2

    scheduled = not (args.dry_run or args.chat or args.force)
    if scheduled:
        try:
            due, why = core.is_due(last_completed(store), now,
                                   settings["archive"]["schedule"])
        except Exception as exc:
            due, why = False, f"could not read the last run: {exc}"[:300]
        if not due:
            # Not due is the normal case for most launchd attempts: no heartbeat.
            print(json.dumps({"status": "not_due", "reason": why}))
            return 0

    try:
        reader = MacReader()
    except Exception as exc:
        summary = {"run": core.run_id(now), "status": "error",
                   "reason": f"WeChat reader unavailable: {exc}"[:300]}
    else:
        keep_awake()
        try:
            summary = archive(reader, store, settings, now, only_chat=args.chat,
                              dry_run=args.dry_run, idle_check=not args.no_idle_check)
        except Exception as exc:
            summary = {"run": core.run_id(now), "status": "error",
                       "reason": str(exc)[:300]}

    if summary.get("status") == "skipped" and scheduled:
        # Locked or busy: launchd tries again in a few minutes. No heartbeat, or
        # the archive would fill with one row per attempt.
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    if summary.get("status") == "error" and scheduled and store and repeated_error(store, summary):
        # e.g. WeChat not open: say so once every few hours, not every attempt.
        print(json.dumps(summary, ensure_ascii=False))
        return 1

    if store and not args.dry_run:
        try:
            write_heartbeat(store, settings, summary, core.now_toronto())
        except Exception as exc:
            summary["heartbeat_error"] = str(exc)[:300]

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("status") in ("ok", "skipped", "interrupted") else 1


if __name__ == "__main__":
    sys.exit(main())
