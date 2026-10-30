#!/usr/bin/env python3
"""
Diagnostic for the WeChat archiver (Mac only): print the Accessibility tree of
the open WeChat window, so the archiver can be fitted to the WeChat version on
this Mac. Reads only. It doesn't click, scroll or type: open the chat yourself
first, then run it.

Text is cut to a few characters per element, so the printout shows the window's
structure (roles and identifiers), not conversations.

    .venv-wechat/bin/python scripts/wechat_ax_probe.py --find "Titan Flooring" | pbcopy
    .venv-wechat/bin/python scripts/wechat_ax_probe.py --bubbles | pbcopy

--bubbles lists every attribute WeChat exposes on each element of the open
chat's message list (and their children), plus position and size, to find
where a group member's name lives.
"""

import argparse
import os
import sys

os.environ.setdefault("WECHAT_MCP_LOG_DIR",
                      os.path.expanduser("~/Library/Logs/titan-wechat-archive"))

from ApplicationServices import (  # noqa: E402
    kAXChildrenAttribute,
    kAXDescriptionAttribute,
    kAXIdentifierAttribute,
    kAXRoleAttribute,
    kAXSubroleAttribute,
    kAXTitleAttribute,
    kAXValueAttribute,
)
import AppKit  # noqa: E402

from wechat_mcp.wechat_accessibility import ax_get, get_wechat_ax_app  # noqa: E402

KEEP = 12  # characters of any text shown


def short(v):
    if v is None:
        return None
    s = str(v).replace("\n", " ").strip()
    if not s:
        return None
    return s if len(s) <= KEEP else s[:KEEP] + "…"


def bubbles(root, limit):
    from ApplicationServices import (AXUIElementCopyAttributeNames,
                                     AXUIElementCopyParameterizedAttributeNames)

    def find_list(el, depth=0):
        if depth > 30:
            return None
        if ax_get(el, kAXIdentifierAttribute) == "chat_message_list":
            return el
        for c in ax_get(el, kAXChildrenAttribute) or []:
            hit = find_list(c, depth + 1)
            if hit is not None:
                return hit
        return None

    lst = find_list(root)
    if lst is None:
        print("chat_message_list not found: open a chat first")
        return
    items = [c for c in (ax_get(lst, kAXChildrenAttribute) or [])
             if ax_get(c, kAXIdentifierAttribute) != "virtual_cell"]
    print(f"visible message-list items: {len(items)} (showing last {limit})")

    def dump(el, depth):
        err, names = AXUIElementCopyAttributeNames(el, None)
        perr, pnames = AXUIElementCopyParameterizedAttributeNames(el, None)
        pad = "  " * depth
        print(pad + "---")
        for n in sorted(names or []):
            if n in ("AXParent", "AXTopLevelUIElement", "AXWindow", "AXChildren"):
                continue
            v = ax_get(el, n)
            if n in ("AXPosition", "AXSize", "AXFrame"):
                # geometry is not text: show it whole
                import re as _re
                m = _re.search(r"\{value = (.*?) type", str(v))
                sv = m.group(1) if m else str(v)[:80]
            elif hasattr(v, "__len__") and not isinstance(v, str):
                sv = f"<{len(v)} items>"
            else:
                sv = short(v)
            print(f"{pad}{n} = {sv!r}")
        if pnames:
            print(f"{pad}(parameterized: {', '.join(sorted(pnames))})")
        for c in ax_get(el, kAXChildrenAttribute) or []:
            dump(c, depth + 1)

    for el in items[-limit:]:
        dump(el, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", help="also list the path to every element whose text contains this")
    ap.add_argument("--depth", type=int, default=30)
    ap.add_argument("--max-lines", type=int, default=1500)
    ap.add_argument("--bubbles", action="store_true",
                    help="dump every attribute of the open chat's visible messages")
    ap.add_argument("--last", type=int, default=8, help="with --bubbles: how many items")
    args = ap.parse_args()

    apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(
        "com.tencent.xinWeChat")
    if apps:
        b = AppKit.NSBundle.bundleWithURL_(apps[0].bundleURL())
        info = b.infoDictionary() if b else {}
        print(f"WeChat version: {info.get('CFBundleShortVersionString')} "
              f"({info.get('CFBundleVersion')})")
    root = get_wechat_ax_app()
    if args.bubbles:
        bubbles(root, args.last)
        return 0

    lines, found = [], []

    def walk(el, depth, path):
        if depth > args.depth or len(lines) >= args.max_lines:
            return
        role = ax_get(el, kAXRoleAttribute)
        sub = ax_get(el, kAXSubroleAttribute)
        ident = ax_get(el, kAXIdentifierAttribute)
        texts = {k: ax_get(el, a) for k, a in (
            ("title", kAXTitleAttribute), ("value", kAXValueAttribute),
            ("desc", kAXDescriptionAttribute))}
        kids = ax_get(el, kAXChildrenAttribute) or []
        parts = [str(role)]
        if sub:
            parts.append(f"sub={sub}")
        if ident:
            parts.append(f"id={ident}")
        for k, v in texts.items():
            sv = short(v)
            if sv:
                parts.append(f"{k}={sv!r}")
        if kids:
            parts.append(f"[{len(kids)}]")
        here = path + [f"{role}{'#' + str(ident) if ident else ''}"]
        lines.append("  " * depth + " ".join(parts))
        if args.find:
            for k, v in texts.items():
                if isinstance(v, str) and args.find.lower() in v.lower():
                    found.append(f"{k} on: " + " > ".join(here[-8:]))
        for c in kids:
            walk(c, depth + 1, here)

    walk(root, 0, [])
    print("\n".join(lines))
    if len(lines) >= args.max_lines:
        print(f"... cut at {args.max_lines} lines")
    if args.find:
        print(f"\n--- elements containing {args.find!r}: {len(found)}")
        print("\n".join(found) or "(none)")


if __name__ == "__main__":
    sys.exit(main())
