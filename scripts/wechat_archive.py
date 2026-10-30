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
FIT = "wechat-4.1.15"  # which WeChat layout the reader was last fitted to


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
            ax_get,
            collect_chat_elements,
            dfs,
            get_current_chat_name,
            get_wechat_ax_app,
        )
        from wechat_mcp.wechat_accessibility import (
            axvalue_to_point,
            axvalue_to_size,
            get_list_center,
        )
        from wechat_mcp.fetch_messages_by_chat_utils import (
            capture_message_area,
            classify_sender_for_message,
            get_messages_list,
            scroll_to_bottom,
            scroll_up_small,
        )
        self._click = click_element_center
        self._collect = collect_chat_elements
        self._current = get_current_chat_name
        self._app = get_wechat_ax_app
        self._norm = _normalize_chat_title
        self._to_point = axvalue_to_point
        self._to_size = axvalue_to_size
        self._list_center = get_list_center
        self._capture = capture_message_area
        self._side = classify_sender_for_message
        self._messages_list = get_messages_list
        self._scroll_to_bottom = scroll_to_bottom
        self._scroll_up = scroll_up_small
        self.name_band = None  # set by archive() from settings["archive"]["name_band"]
        self._ax_get = ax_get
        self._dfs = dfs

    def _opened_name(self):
        """
        The open chat's name. WeChat 4.1 has a label holding just the name
        (id current_chat_name_label, beside a separate member-count label);
        older versions only have the combined title the library reads.
        """
        from ApplicationServices import kAXTitleAttribute, kAXValueAttribute
        label = self._dfs(self._app_quiet(),
                          lambda el, role, title, ident: ident == "current_chat_name_label")
        if label is not None:
            v = self._ax_get(label, kAXValueAttribute) or self._ax_get(label, kAXTitleAttribute)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return self._current()

    def _title_report(self):
        """What the title area looked like, for the error message."""
        from ApplicationServices import kAXTitleAttribute, kAXValueAttribute
        found = []
        for ident in ("current_chat_name_label", "big_title_line_h_view"):
            el = self._dfs(self._app_quiet(), lambda e, r, t, i, want=ident: i == want)
            if el is None:
                found.append(f"{ident}: missing")
            else:
                v = self._ax_get(el, kAXValueAttribute) or self._ax_get(el, kAXTitleAttribute)
                found.append(f"{ident}: {str(v)[:12]!r}")
        found.append(f"frontmost: {self.frontmost()}")
        return "; ".join(found)

    def _app_quiet(self):
        from ApplicationServices import AXUIElementCreateApplication
        import AppKit
        apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(
            "com.tencent.xinWeChat")
        if not apps:
            raise RuntimeError("WeChat is not running")
        return AXUIElementCreateApplication(apps[0].processIdentifier())

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

    @staticmethod
    def frontmost():
        """
        Bundle id of the app in front, asked live. NSWorkspace's
        frontmostApplication only refreshes on a running main run loop, which
        a command-line process doesn't have, so it kept answering "Terminal"
        after WeChat had come forward. The system-wide AX element is asked
        fresh every call.
        """
        import AppKit
        from ApplicationServices import (AXUIElementCopyAttributeValue,
                                         AXUIElementCreateSystemWide,
                                         AXUIElementGetPid,
                                         kAXFocusedApplicationAttribute)
        try:
            err, app_el = AXUIElementCopyAttributeValue(
                AXUIElementCreateSystemWide(), kAXFocusedApplicationAttribute, None)
            if err == 0 and app_el is not None:
                err, pid = AXUIElementGetPid(app_el, None)
                if err == 0:
                    app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
                    if app is not None:
                        return app.bundleIdentifier()
        except Exception:
            pass
        AppKit.NSRunLoop.currentRunLoop().runUntilDate_(
            AppKit.NSDate.dateWithTimeIntervalSinceNow_(0.05))
        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.bundleIdentifier() if app else None

    def bring_to_front(self):
        """
        Make WeChat the frontmost app and raise its window, and confirm it.
        Newer macOS often ignores activateWithOptions_ from a background
        process, and a click sent while another window is on top lands there.
        """
        import AppKit
        from ApplicationServices import (AXUIElementPerformAction,
                                         AXUIElementSetAttributeValue,
                                         kAXChildrenAttribute, kAXFrontmostAttribute,
                                         kAXRaiseAction, kAXRoleAttribute)
        bundle = "com.tencent.xinWeChat"
        apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle)
        if not apps:
            raise RuntimeError("WeChat is not running")
        import subprocess
        ax = self._app_quiet()
        for i in range(20):
            if self.frontmost() == bundle:
                break
            if i % 6 == 0:
                # Opening it through LaunchServices, as the Dock does, is the
                # one request macOS 14+ always honours; activateWithOptions_
                # is refused while Terminal (or anything else) is active.
                subprocess.run(["open", "-b", bundle], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            apps[0].unhide()
            apps[0].activateWithOptions_(AppKit.NSApplicationActivateAllWindows)
            AXUIElementSetAttributeValue(ax, kAXFrontmostAttribute, True)
            time.sleep(0.25)
        for child in self._ax_get(ax, kAXChildrenAttribute) or []:
            if self._ax_get(child, kAXRoleAttribute) == "AXWindow":
                AXUIElementPerformAction(child, kAXRaiseAction)
                break
        time.sleep(0.3)
        if self.frontmost() != bundle:
            raise RuntimeError(f"WeChat would not come to the front ({self.frontmost()} stayed)")

    def read_chat(self, chat, last_n):
        """Open `chat` from the sidebar and return its last messages, oldest first."""
        self.bring_to_front()
        elements = self._collect(self._app())
        el = elements.get(chat)
        if el is None:
            raise RuntimeError("not in the sidebar any more")
        self._click(el)
        # WeChat takes a moment to draw the chat it switched to; wait for the
        # title to show the chat clicked, up to 6 s.
        opened = None
        for _ in range(24):
            time.sleep(0.25)
            opened = self._opened_name()
            if opened is not None and self._norm(opened) == self._norm(chat):
                break
        # Never file one chat's messages under another chat's name.
        if opened is None or self._norm(opened) != self._norm(chat):
            raise RuntimeError(f"opened {opened!r} instead after 6 s "
                               f"(fit {FIT}; {self._title_report()})")
        is_group = self._is_group()
        return {"messages": self._read_messages(last_n, is_group), "is_group": is_group}

    def _is_group(self):
        """WeChat shows a member count, "(4)", beside a group's name only."""
        from ApplicationServices import kAXTitleAttribute, kAXValueAttribute
        el = self._dfs(self._app_quiet(),
                       lambda e, r, t, i: i == "current_chat_count_label")
        if el is None:
            return False
        v = self._ax_get(el, kAXValueAttribute) or self._ax_get(el, kAXTitleAttribute)
        return bool(v and str(v).strip())

    def _read_messages(self, last_n, is_group):
        """
        The open chat's last messages, oldest first, as
        {"sender": ME|OTHER|UNKNOWN, "text", "speaker"}.

        The library's fetch_recent_messages, rebuilt so each row keeps its
        position: WeChat 4.1 exposes a group member's name only as pixels on
        the top line of the message's row, so it is read off the screenshot
        (macOS Vision, on the Mac). Coordinates are scaled to the screenshot,
        which is in device pixels (2x on a Retina screen).
        """
        from ApplicationServices import (kAXChildrenAttribute, kAXPositionAttribute,
                                         kAXSizeAttribute, kAXTitleAttribute,
                                         kAXValueAttribute)
        msg_list = self._messages_list(self._app_quiet())
        center = self._list_center(msg_list)
        self._scroll_to_bottom(msg_list, center)
        messages, no_new = [], 0
        for _ in range(400):
            image, origin, size = self._capture(msg_list)
            scale = image.width / size[0] if size and size[0] else 1.0
            visible = []
            for child in self._ax_get(msg_list, kAXChildrenAttribute) or []:
                text = (self._ax_get(child, kAXValueAttribute)
                        or self._ax_get(child, kAXTitleAttribute))
                if not text:
                    continue
                pt = self._to_point(self._ax_get(child, kAXPositionAttribute))
                sz = self._to_size(self._ax_get(child, kAXSizeAttribute))
                visible.append({"text": str(text), "pt": pt, "sz": sz})
            if not visible:
                break
            if not messages:
                fresh = visible
            else:
                anchor = messages[0]["text"]
                idx = next((i for i, m in enumerate(visible) if m["text"] == anchor), None)
                fresh = visible if idx is None else visible[:idx]
            for m in fresh:  # only rows not seen yet are classified and read
                m.update(self._who(image, origin, scale, m, is_group))
                del m["pt"], m["sz"]
            if fresh:
                messages = fresh + messages
                no_new = 0
            else:
                no_new += 1
                if no_new >= 5:
                    break
            if len(messages) >= last_n:
                break
            self._scroll_up(center)
        return messages[-last_n:]

    def _who(self, image, origin, scale, m, is_group):
        if m["pt"] is None or m["sz"] is None:
            return {"sender": "UNKNOWN", "speaker": None}
        rx, ry = (m["pt"][0] - origin[0]) * scale, (m["pt"][1] - origin[1]) * scale
        w, h = m["sz"][0] * scale, m["sz"][1] * scale
        sender = self._side(image, (0, 0), (rx, ry), (w, h))
        speaker = None
        if is_group and sender != "ME":
            b = self.name_band or {"top": 0, "height": 19, "left": 50, "right_fraction": 0.7}
            box = (int(rx + b["left"] * scale), int(ry + b["top"] * scale),
                   int(rx + w * b["right_fraction"]), int(ry + (b["top"] + b["height"]) * scale))
            if box[2] > box[0] and box[3] > box[1] and h > (b["height"] + 8) * scale:
                speaker = ocr_line(image.crop(box))
                # A band that caught the bubble's own text is not a name.
                if speaker and m["text"].replace("\n", " ").startswith(speaker[:8]):
                    speaker = None
        return {"sender": sender, "speaker": speaker}


def ocr_line(pil_image):
    """
    Read one short line of text (a group member's name) with macOS Vision,
    on the Mac. Nothing leaves the machine. Returns None when nothing reads.
    """
    import io
    import Quartz
    import Vision
    from Foundation import NSData
    img = pil_image.convert("RGB")
    if img.height < 60:  # small UI text reads better upscaled
        f = 60 / img.height
        img = img.resize((int(img.width * f), 60))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    raw = buf.getvalue()
    src = Quartz.CGImageSourceCreateWithData(NSData.dataWithBytes_length_(raw, len(raw)), None)
    cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(False)
    req.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en-US"])
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
    handler.performRequests_error_([req], None)
    parts = []
    for r in req.results() or []:
        cands = r.topCandidates_(1)
        if cands:
            parts.append(str(cands[0].string()).strip())
    text = " ".join(p for p in parts if p)
    return text or None


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
        for key in ("from", "to"):
            if row.get(key):
                props[p[key]] = {"rich_text": [{"text": {"content": row[key][:2000]}}]}
        if row.get("chat_type"):
            props[p["chat_type"]] = {"select": {"name": row["chat_type"]}}
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
        # No -u: declaring user activity would reset the idle clock that
        # archive() reads to notice a real person.
        subprocess.Popen(["caffeinate", "-dims", "-w", str(os.getpid())])
    except OSError:
        pass


def someone_touched(reader, last_touch, clock):
    """
    True when keyboard or mouse input arrived after the reader's own last click
    or scroll. The reader's synthetic events reset the Mac's idle clock too, so
    "idle < 5 s" would always fire after the first chat; the question is whether
    the idle clock is younger than our own last action.
    """
    if last_touch is None:
        return reader.idle_seconds() < 5
    return reader.idle_seconds() < (clock() - last_touch) - 1.0


def archive(reader, store, settings, now, only_chat=None, dry_run=False,
            idle_check=True, clock=time.monotonic, sleep=time.sleep):
    """Archive every unrecorded message. Returns the run summary."""
    a = settings["archive"]
    kinds = settings["parse"]["kind_patterns"]
    people = settings["people"]
    if hasattr(reader, "name_band"):
        reader.name_band = a.get("name_band")
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

    last_touch = None
    try:
        for i, chat in enumerate(chats):
            if idle_check:
                if i:
                    # A quiet moment between chats, so a person's input shows
                    # up as younger than the reader's own last scroll.
                    sleep(a["between_chats_seconds"])
                if someone_touched(reader, last_touch, clock):
                    raise InUse()
            try:
                tail = store.tail(chat, a["stored_tail_compare"]) if store else []
                n = a["tail_check_messages"] if tail else a["first_run_messages"]
                try:
                    raw = reader.read_chat(chat, n)
                finally:
                    last_touch = clock()
                msgs = core.annotate(raw, now, kinds, chat=chat, people=people)
                rows, aligned = core.plan_chat(chat, msgs, tail, a["min_overlap"])
                if tail and not aligned:
                    try:
                        raw = reader.read_chat(chat, a["backfill_cap_messages"])
                    finally:
                        last_touch = clock()
                    msgs = core.annotate(raw, now, kinds, chat=chat, people=people)
                    rows, aligned = core.plan_chat(chat, msgs, tail, a["min_overlap"])
                    if not aligned:
                        summary["gaps"].append(chat)
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
                entry["preview"] = [{k: r.get(k) for k in
                                     ("from", "to", "sender", "kind", "sent_at", "text")}
                                    for r in rows[-8:]]
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
