#!/usr/bin/env python3
"""
Pure logic shared by the WeChat archiver and its tests: no macOS, no network.

The WeChat reader (scripts/wechat_archive.py, Mac only) sees a chat the way the
screen shows it: a list of bubbles with text and a side (me / them), plus time
separators. There is no message id and no per-message timestamp. So:

- Time separators ("10:42", "Yesterday 10:42", "星期一 10:42", "2026/10/27 10:42")
  are dropped from the message list and only stamp `sent_at` on the messages
  below them. They must never take part in matching, because WeChat rewrites them
  as days pass ("10:42" becomes "Yesterday 10:42" tomorrow).
- New messages are found by lining up the stored tail of a chat (its last few
  archived texts) with what is on screen now, and taking everything after the
  match. Matching is on text only: the me/them side is a pixel heuristic and can
  flip between runs.
- Each row gets a chained key, hash(previous key + chat + text), so two identical
  "ok" messages in a row are still two rows.

See methods/wechat-archive.md.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timedelta

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(REPO_ROOT, "platform-settings", "wechat.json")

SENDERS = {"ME": "Me", "OTHER": "Them", "UNKNOWN": "Unknown"}

_TIME = r"(?:(上午|下午|凌晨|早上|中午|晚上)\s*)?(\d{1,2}):(\d{2})(?:\s*([AaPp][Mm]))?"
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
    "saturday": 5, "sunday": 6,
    "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3, "星期五": 4, "星期六": 5,
    "星期日": 6, "星期天": 6,
    "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6,
}
_RE_TODAY = re.compile(rf"^{_TIME}$")
_RE_YESTERDAY = re.compile(rf"^(?:Yesterday|昨天)\s*{_TIME}$", re.I)
_RE_WEEKDAY = re.compile(rf"^({'|'.join(_WEEKDAYS)})\s*{_TIME}$", re.I)
_RE_YMD = re.compile(rf"^(\d{{4}})[/\-年](\d{{1,2}})[/\-月](\d{{1,2}})日?\s*{_TIME}$")
_RE_MDY = re.compile(rf"^(\d{{1,2}})/(\d{{1,2}})/(\d{{2}})\s*{_TIME}$")
_RE_MD_ZH = re.compile(rf"^(\d{{1,2}})月(\d{{1,2}})日\s*{_TIME}$")
_RE_MD = re.compile(rf"^(\d{{1,2}})/(\d{{1,2}})\s+{_TIME}$")  # WeChat 4.1: "10/21 13:17"


def load_settings(path=SETTINGS):
    with open(path) as fh:
        return json.load(fh)


def _clock(groups):
    """(zh_period, hour, minute, ampm) -> (hour24, minute), or None."""
    zh, hour, minute, ampm = groups
    hour, minute = int(hour), int(minute)
    if hour > 23 or minute > 59:
        return None
    pm = (ampm or "").lower() == "pm" or zh in ("下午", "晚上")
    am = (ampm or "").lower() == "am" or zh in ("上午", "凌晨", "早上")
    if pm and hour < 12:
        hour += 12
    if am and hour == 12:
        hour = 0
    if zh == "中午" and hour < 11:
        hour += 12
    return hour, minute


def _at(day, clock):
    if clock is None:
        return None
    return day.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)


def parse_separator(text, now):
    """
    Return the datetime a WeChat time separator stands for, or None if `text`
    is not one. `now` is a timezone-aware datetime in America/Toronto.
    """
    t = (text or "").strip()
    if not t or len(t) > 40:
        return None
    m = _RE_TODAY.match(t)
    if m:
        return _at(now, _clock(m.groups()))
    m = _RE_YESTERDAY.match(t)
    if m:
        return _at(now - timedelta(days=1), _clock(m.groups()))
    m = _RE_WEEKDAY.match(t)
    if m:
        target = _WEEKDAYS[m.group(1).lower() if m.group(1).isascii() else m.group(1)]
        back = (now.weekday() - target) % 7 or 7
        return _at(now - timedelta(days=back), _clock(m.groups()[1:]))
    m = _RE_YMD.match(t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _safe_date(now, y, mo, d, m.groups()[3:])
    m = _RE_MDY.match(t)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), 2000 + int(m.group(3))
        return _safe_date(now, y, mo, d, m.groups()[3:])
    m = _RE_MD_ZH.match(t) or _RE_MD.match(t)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        when = _safe_date(now, now.year, mo, d, m.groups()[2:])
        # No year shown: a date later than today is from last year.
        if when is not None and when.date() > now.date():
            when = _safe_date(now, now.year - 1, mo, d, m.groups()[2:])
        return when
    return None


def _safe_date(now, y, mo, d, clock_groups):
    try:
        day = now.replace(year=y, month=mo, day=d)
    except ValueError:
        return None
    return _at(day, _clock(clock_groups))


def classify_kind(text, kind_patterns):
    t = (text or "").strip()
    for kind, patterns in kind_patterns.items():
        for p in patterns:
            if re.search(p, t, re.I):
                return kind
    return "text"


def parse_sidebar(text):
    """
    WeChat 4.1's sidebar entry text:
    "<chat>\n[Pinned to top\n]<sender>: <preview>\n<time>\n" in a group,
    without "<sender>: " in a direct chat. Returns (sender, preview), either
    None when it doesn't parse.
    """
    if not text:
        return None, None
    lines = [l.strip() for l in str(text).split("\n") if l.strip()]
    lines = [l for l in lines[1:] if l not in ("Pinned to top", "置顶", "Muted", "消息免打扰")]
    if len(lines) >= 2:
        lines = lines[:-1]  # the time column ("10/21", "Yesterday 18:56")
    if not lines:
        return None, None
    body = " ".join(lines)
    m = re.match(r"^(.{1,60}?):\s(.+)$", body)
    if m and not body.startswith("["):
        return m.group(1), m.group(2)
    return None, body


def _flat(t):
    return re.sub(r"[\[\]\s]+", " ", (t or "")).strip().lower()


def matches_newest(preview, newest_text, kind_patterns=None):
    """Does the sidebar's preview describe the newest message read?"""
    if not preview or not newest_text:
        return None  # can't tell
    if kind_patterns:
        k1, k2 = classify_kind(preview, kind_patterns), classify_kind(newest_text, kind_patterns)
        if k1 == k2 and k1 not in ("text", "file", "link"):
            return True  # "[Voice]" vs 'Audio10"sec', "[Image]" vs "Image"
    a, b = _flat(preview).rstrip("…. "), _flat(newest_text)
    n = min(len(a), 25)
    return a[:n] in b or b[:n] in a


def name_of(speaker, people):
    """A read-off-the-screen name, tidied and mapped through people.aliases."""
    if not speaker:
        return None
    name = re.sub(r"\s+", " ", speaker).strip()
    aliases = people.get("aliases") or {}
    if name in aliases:
        return aliases[name]
    for pattern, display in (people.get("alias_patterns") or {}).items():
        if re.search(pattern, name):
            return display
    return name


def annotate(raw_messages, now, kind_patterns, chat=None, people=None):
    """
    raw_messages: the reader's {"messages": [...], "is_group": bool}, or a bare
    list, of {"sender": "ME|OTHER|UNKNOWN", "text": str, "speaker": str|None}
    oldest first. Returns messages without separators, each with sender
    (Me/Them/Unknown), from, to, chat_type, text, kind and sent_at.

    Who wrote it:
    - Albert's own messages (right-hand side) are from people.me;
    - in a direct chat, everything else is from the chat's name, to Albert;
    - in a group, the name WeChat printed above the message, read off the
      screen; no name read means "Unknown", never a guess. A group message's
      "to" is the group.
    """
    people = people or {"me": "Me"}
    me = people.get("me", "Me")
    is_group = False
    if isinstance(raw_messages, dict):
        is_group = bool(raw_messages.get("is_group"))
        raw_messages = raw_messages.get("messages") or []
    out = []
    stamp = None
    for m in raw_messages:
        text = (m.get("text") or "").strip()
        if not text:
            continue
        sender = m.get("sender", "UNKNOWN")
        when = parse_separator(text, now)
        # A dated separator ("10/21 13:17", "Yesterday 09:15") is one whichever
        # side the pixel heuristic guessed; a bare "10:42" only when it sat in
        # the middle (UNKNOWN), since a person might type just a time.
        if when is not None and (sender == "UNKNOWN" or not _RE_TODAY.match(text)):
            stamp = when
            continue
        speaker = name_of(m.get("speaker"), people) if is_group else None
        if speaker:
            sender = "OTHER"  # WeChat prints names over other people's messages only
        if sender == "ME":
            frm, to = me, chat
        elif is_group:
            frm, to = speaker or "Unknown", chat
        elif sender == "OTHER":
            frm, to = chat, me
        else:
            frm, to = "Unknown", None
        out.append({
            "sender": SENDERS.get(sender, "Unknown"),
            "from": frm,
            "to": to,
            "chat_type": "group" if is_group else "direct",
            "text": text,
            "kind": classify_kind(text, kind_patterns),
            "sent_at": stamp.isoformat() if stamp else None,
        })
    return out


def align(tail_texts, fetched_texts, min_overlap):
    """
    Index in fetched_texts where unrecorded messages start, or None if the stored
    tail cannot be found. An empty tail means nothing is recorded: start at 0.

    Tries the longest suffix of the tail first and, for each length, the latest
    position on screen, so a repeated short message ("ok") does not pull the
    match backwards. A match shorter than min_overlap is not trusted unless the
    whole stored tail is that short.
    """
    if not tail_texts:
        return 0
    floor = max(1, min(min_overlap, len(tail_texts)))
    for k in range(min(len(tail_texts), len(fetched_texts)), floor - 1, -1):
        suffix = tail_texts[-k:]
        for j in range(len(fetched_texts), k - 1, -1):
            if fetched_texts[j - k:j] == suffix:
                return j
    return None


def chain_key(prev_key, chat, text):
    h = hashlib.sha256()
    h.update("\x1f".join([prev_key or "", chat, text]).encode("utf-8"))
    return h.hexdigest()[:24]


def plan_chat(chat, messages, tail, min_overlap):
    """
    messages: annotate() output for what is on screen, oldest first.
    tail: stored rows for this chat, oldest first, each {"text", "key", "sequence"}.

    Returns (new_rows, aligned). new_rows carry key, sequence and gap_before.
    aligned is False when the tail was not found; the caller decides whether to
    read further back before accepting a gap.
    """
    start = align([t["text"] for t in tail], [m["text"] for m in messages], min_overlap)
    aligned = start is not None
    if start is None:
        start = 0
    prev_key = tail[-1]["key"] if tail else ""
    seq = int(tail[-1]["sequence"]) if tail else 0
    rows = []
    for i, m in enumerate(messages[start:]):
        seq += 1
        prev_key = chain_key(prev_key, chat, m["text"])
        rows.append(dict(m, chat=chat, key=prev_key, sequence=seq,
                         gap_before=(not aligned and bool(tail) and i == 0)))
    return rows, aligned


def is_due(last_completed_at, now, schedule):
    """
    (due, reason). Due when now is inside the attempt window and the last
    completed run (ok or partial) is at least min_hours_between_runs old.
    last_completed_at is an ISO string or None (never ran).
    """
    hm = now.strftime("%H:%M")
    if hm < schedule["first_attempt"] or hm > schedule["last_attempt"]:
        return False, f"outside {schedule['first_attempt']}-{schedule['last_attempt']}"
    if not last_completed_at:
        return True, None
    last = datetime.fromisoformat(last_completed_at)
    if last.tzinfo is None:
        last = last.replace(tzinfo=now.tzinfo)
    age = (now - last).total_seconds() / 3600
    if age < schedule["min_hours_between_runs"]:
        return False, f"last run {age:.1f} h ago"
    return True, None


def run_id(now):
    return now.strftime("wx-%Y%m%d-%H%M%S")


def to_toronto(dt_utc):
    """Best-effort conversion for callers without zoneinfo data."""
    try:
        from zoneinfo import ZoneInfo
        return dt_utc.astimezone(ZoneInfo("America/Toronto"))
    except Exception:
        return dt_utc


def now_toronto():
    from datetime import timezone
    return to_toronto(datetime.now(timezone.utc))
