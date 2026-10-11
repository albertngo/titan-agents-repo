#!/usr/bin/env python3
"""Pull GHL conversations for unread triage and build each one's unanswered batch. READ ONLY.

    python3 scripts/ghl_unread_pull.py --mode sweep            # /ghl-triage, hourly
    python3 scripts/ghl_unread_pull.py --mode brief            # ghl-ingest-agent's triage step

Sweep mode reads every conversation GHL flags unread. Brief mode reads those plus every
conversation with a message in the last --window-hours (24), so the daily brief's
"waiting on us" list is one combined list (Albert, 2026-10-07).

For each conversation it pages messages newest-first back to Titan's last HUMAN reply
(methods/ghl-unread-triage.md, "What a batch is"), applies the holds, computes the facts
the plan script's guards need (has a '?', longest message, stranger), and reuses a cached
verdict from branch claude/ghl-triage-log when the batch and rubric version are
unchanged. It writes, into analysis/cache/ghl-triage/<date>/<run_id>/ (gitignored):

    candidates.json   every conversation, no message text   (ghl-triage-candidates-1)
    todo.json         text of the batches the model must judge (ghl-triage-todo-1)

and prints that directory on its last line. It reaches GHL only through ghl_client
(GET-only), never writes under ingest/, and never writes the log branch.

Exit codes: 0 ok · 1 error · 2 config/credentials · 3 host blocked.
"""

import argparse
import hashlib
import html
import json
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import ghl_client  # noqa: E402
import ghl_triage_log  # noqa: E402

REGISTRY = REPO_ROOT / "platform-settings" / "ghl-unread-triage.json"
TZ = ZoneInfo("America/Toronto")
CANDIDATES_VERSION = "ghl-triage-candidates-1"
TODO_VERSION = "ghl-triage-todo-1"
KNOWN_SOURCES = ("app", "workflow", "bulk_actions")  # seen live 2026-10-08; anything else is reported
HOLD_ORDER = ("call_in_batch", "non_text_content", "unknown_message_type",
              "batch_too_long", "history_truncated")
CHANNELS = {"TYPE_SMS": "sms", "TYPE_SMS_REACTION": "sms", "TYPE_CUSTOM_SMS": "sms",
            "TYPE_CUSTOM_PROVIDER_SMS": "sms", "TYPE_EMAIL": "email", "TYPE_CUSTOM_EMAIL": "email",
            "TYPE_CUSTOM_PROVIDER_EMAIL": "email", "TYPE_WHATSAPP": "whatsapp",
            "TYPE_FACEBOOK": "facebook", "TYPE_INSTAGRAM": "instagram", "TYPE_GMB": "google",
            "TYPE_LIVE_CHAT": "chat", "TYPE_WEBCHAT": "chat"}


def load_registry(path=REGISTRY):
    return json.loads(Path(path).read_text())


def die(msg, hint=None, code=2):
    print(f"error: {msg}" + (f"\n  hint: {hint}" if hint else ""), file=sys.stderr)
    raise SystemExit(code)


def refuse_ingest_path(path):
    p = Path(path).resolve()
    if (REPO_ROOT / "ingest") in p.parents:
        die(f"{path} is under ingest/ — /daily-ingest and /notion-sync read that folder "
            "wholesale; triage files live in analysis/cache/ghl-triage/", code=2)


def new_run_id(now):
    return now.astimezone(TZ).strftime("%Y%m%dT%H%M") + "-" + secrets.token_hex(2)


# -- message text ----------------------------------------------------------------

class _Text(HTMLParser):
    BREAKS = {"br", "p", "div", "li", "tr", "blockquote"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self.skip += 1
        if tag == "blockquote":
            self.skip += 1  # quoted earlier messages are ours, not the customer's words
        if tag in self.BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head", "blockquote") and self.skip:
            self.skip -= 1
        if tag in self.BREAKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


QUOTE_START = re.compile(
    r"^\s*(On .{0,200}wrote:|-{2,}\s*Original Message|From:\s|Sent from my |>)", re.I)


def html_to_text(raw):
    p = _Text()
    p.feed(raw)
    p.close()
    return html.unescape("".join(p.parts))


def strip_quoted(text):
    """Cut an email reply at the start of the quoted thread."""
    out = []
    for line in text.splitlines():
        if QUOTE_START.match(line):
            break
        out.append(line)
    return "\n".join(out)


def message_text(m):
    body = m.get("body") or ""
    if m.get("messageType") in ("TYPE_EMAIL", "TYPE_CUSTOM_EMAIL", "TYPE_CUSTOM_PROVIDER_EMAIL") \
            or "html" in (m.get("contentType") or ""):
        body = strip_quoted(html_to_text(body))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", body)).strip()


# -- classifying one message (the shared reply rule) ---------------------------------

def connected(m, b):
    call = (m.get("meta") or {}).get("call") or {}
    status = call.get("status") or m.get("status")
    duration = call.get("duration") or m.get("callDuration") or 0
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = 0
    return status == b["connected_call_status"] and duration >= b["min_call_seconds"]


def kind(m, b):
    """'ignore' | 'boundary' | 'automation' | 'text' | 'hold:<reason>'.

    The one definition of "Titan replied" (methods/ghl-unread-triage.md). Used here and by
    scripts/ghl_mark_read.py, so the sweep, the brief and the writer never disagree."""
    t = m.get("messageType") or ""
    if t in b["ignore_types"] or any(t.startswith(p) for p in b["ignore_type_prefixes"]):
        return "ignore"
    if m.get("direction") != "inbound":
        human = m.get("source") in b["human_sources"] and bool(m.get("userId"))
        if t in b["text_types"] and human and m.get("status") not in b["failed_statuses"]:
            return "boundary"
        if t in b["boundary_call_types"] and human and connected(m, b):
            return "boundary"
        return "automation"
    if t in b["boundary_call_types"] and connected(m, b):
        return "boundary"
    if t in b["call_types"]:
        return "hold:call_in_batch"
    if t in b["text_types"]:
        text = message_text(m)
        if m.get("attachments") or not text or text in b.get("non_text_bodies", ()):
            return "hold:non_text_content"
        return "text"
    return "hold:unknown_message_type"


def newest_relevant_id(messages, b):
    """Id of the newest message that is not an internal comment or activity line — what the
    writer's compare-and-swap expects to still be newest."""
    for m in messages:
        if kind(m, b) != "ignore":
            return m.get("id")
    return None


def iter_pages(client, conversation_id, page_size, max_pages):
    """Yield (messages newest-first, has_next) one page at a time."""
    params = {"limit": page_size}
    for _ in range(max_pages):
        page = client.get_json(f"/conversations/{conversation_id}/messages", params)
        block = page.get("messages", page) if isinstance(page, dict) else page
        rows = block.get("messages", []) if isinstance(block, dict) else (block or [])
        has_next = bool(isinstance(block, dict) and block.get("nextPage"))
        yield rows, has_next
        last_id = (block.get("lastMessageId") if isinstance(block, dict) else None) or \
            (rows[-1].get("id") if rows else None)
        if not has_next or not last_id or params.get("lastMessageId") == last_id:
            return
        params["lastMessageId"] = last_id


def walk(pages, b):
    """Collect the batch from pages of messages (newest first).

    Returns {inbound: [msg oldest-first], holds: set, boundary: msg|None, exhausted: bool,
             truncated: bool, newest_id, unknown_outbound_sources: {source: n}}."""
    seen, inbound, holds, unknown = set(), [], set(), {}
    newest_id, boundary, exhausted, truncated = None, None, False, False
    for rows, has_next in pages:
        for m in rows:
            mid = m.get("id")
            if mid in seen:
                continue
            seen.add(mid)
            k = kind(m, b)
            if k == "ignore":
                continue
            if newest_id is None:
                newest_id = mid
            if k == "boundary":
                boundary = m
                break
            if k == "automation":
                src = m.get("source") or "none"
                if src not in KNOWN_SOURCES:
                    unknown[src] = unknown.get(src, 0) + 1
                continue
            inbound.append(m)
            if k.startswith("hold:"):
                holds.add(k.split(":", 1)[1])
        if boundary:
            break
        if not has_next:
            exhausted = True
    if not boundary and not exhausted:
        truncated = True
        holds.add("history_truncated")
    inbound.reverse()
    return {"inbound": inbound, "holds": holds, "boundary": boundary, "exhausted": exhausted,
            "truncated": truncated, "newest_id": newest_id, "unknown_outbound_sources": unknown}


def batch_key(conversation_id, message_ids):
    return "b-" + hashlib.sha1((conversation_id + "|" + "|".join(message_ids)).encode()).hexdigest()[:16]


def short_name(row):
    full = (row.get("contactName") or row.get("fullName") or "").strip()
    if not full:
        return "(no name)"
    parts = full.split()
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


def hours_since(ts, now):
    dt = ghl_client.parse_ts(ts)
    return None if dt is None else round((now - dt).total_seconds() / 3600, 1)


def candidate(client, row, reg, now, cache, in_window):
    b = reg["batch"]
    cid = row["id"]
    w = walk(iter_pages(client, cid, b["page_size"], b["max_pages_back"]), b)
    texts = [message_text(m) for m in w["inbound"]]
    ids = [m.get("id") for m in w["inbound"]]
    holds = set(w["holds"])
    chars = sum(len(t) for t in texts)
    if not ids:
        holds = {"no_customer_text"} if not w["truncated"] else holds
    elif len(ids) > b["max_messages"] or chars > b["max_chars"]:
        holds.add("batch_too_long")
    hold = "no_customer_text" if "no_customer_text" in holds else \
        next((h for h in HOLD_ORDER if h in holds), None)
    key = batch_key(cid, ids) if ids else None

    stranger = False
    opps = row.get("opportunities")
    if w["exhausted"] and not w["boundary"] and isinstance(opps, list) and not opps and ids:
        others = client.search_conversations(None, limit=10, max_pages=1,
                                             contact_id=row.get("contactId"))
        stranger = all(o.get("id") == cid for o in others)

    first_at = w["inbound"][0].get("dateAdded") if w["inbound"] else None
    last_type = (w["inbound"][-1].get("messageType") if w["inbound"] else None) or row.get("lastMessageType")
    excerpt = None
    if reg["log"]["excerpts"] and texts:
        excerpt = " / ".join(texts)[: reg["log"]["excerpt_chars"]]
    cached = cache.get(key) if key and not hold else None
    return {
        "conversation_id": cid,
        "contact_id": row.get("contactId"),
        "contact": short_name(row),
        "channel": CHANNELS.get(last_type, (last_type or "").replace("TYPE_", "").lower() or "unknown"),
        "unread": (row.get("unreadCount") or 0) > 0,
        "unread_count": row.get("unreadCount") or 0,
        "in_window": in_window,
        "last_message_id": w["newest_id"],
        "last_message_at": row.get("lastMessageDate"),
        "batch": {"message_ids": ids, "n": len(ids), "first_at": first_at,
                  "last_at": w["inbound"][-1].get("dateAdded") if w["inbound"] else None,
                  "chars": chars, "max_message_chars": max((len(t) for t in texts), default=0),
                  "has_question": any("?" in t for t in texts)},
        "batch_key": key,
        "hold_reason": hold,
        "stranger": stranger,
        "owner_by_reply": "us" if ids else "them",
        "waiting_hours": hours_since(first_at, now) if ids else None,
        "last_inbound_hours": hours_since(w["inbound"][-1].get("dateAdded"), now) if ids else None,
        "last_message_hours": hours_since(row.get("lastMessageDate"), now),
        "cached": cached,
        "excerpt": excerpt,
        "_texts": texts,
        "_unknown_outbound_sources": w["unknown_outbound_sources"],
    }


def sweep_health(repo, reg, now, ref):
    """For brief mode: what the hourly sweep did in the last 24 h (from the log branch)."""
    dates = ghl_triage_log.recent_days(now, 2)
    runs = [r for r in ghl_triage_log.load_runs(repo, reg, dates, ref) if r.get("mode") == "sweep"]
    since = (now - timedelta(hours=24)).isoformat()
    recent = [r for r in runs if r.get("run_at", "") >= since]
    entries = [e for e in ghl_triage_log.load_actions(repo, reg, dates, ref)
               if e.get("logged_at", "") >= since]
    by = lambda res: [e for e in entries if e.get("result") == res]  # noqa: E731
    return {"last_sweep_at": max((r["run_at"] for r in runs), default=None),
            "sweeps_24h": len(recent),
            "cleared_24h": [{"conversation_id": e.get("raw_ref"), "reason": e.get("content_summary")}
                            for e in by("executed")],
            "refused_24h": [{"conversation_id": e.get("raw_ref"), "error": e.get("error")}
                            for e in by("refused")],
            "failed_24h": [{"conversation_id": e.get("raw_ref"), "error": e.get("error")}
                           for e in by("failed")],
            "needs_person_24h": sum(1 for r in recent if r.get("status") == "needs_person")}


def run(args, client=None, repo=REPO_ROOT, now=None):
    reg = load_registry(args.registry)
    now = now or datetime.now(timezone.utc)
    if args.mode == "sweep" and not reg["pull"].get("probe_verified"):
        die("pull.probe_verified is null — run the supervised read probe first "
            "(methods/ghl-unread-triage.md)", code=2)
    if client is None:
        ghl_client.load_dotenv(REPO_ROOT / ".env")
        try:
            client = ghl_client.GhlClient()
        except ghl_client.GhlError as exc:
            die(str(exc), "GHL_PIT_TOKEN and GHL_LOCATION_ID come from .env (.env.example)")

    run_id = new_run_id(now)
    out_dir = args.out_dir or (REPO_ROOT / reg["outputs"]["cache_dir"] /
                               now.astimezone(TZ).date().isoformat() / run_id)
    refuse_ingest_path(out_dir)

    log_status = "skipped" if args.no_log else ghl_triage_log.fetch(repo, reg)
    ref = ghl_triage_log.remote_ref(reg)
    cache, kill, health = {}, None, {}
    if log_status == "ok":
        cache = ghl_triage_log.load_cache(repo, reg, now, reg["rubric"]["version"], ref)
        kill = ghl_triage_log.kill_switch(repo, reg, ref)
        if args.mode == "brief":
            health = sweep_health(repo, reg, now, ref)

    pages = max(1, -(-reg["pull"]["max_conversations"] // 100))
    try:
        unread = [r for r in client.search_conversations(None, limit=100, max_pages=pages,
                                                         status=reg["pull"]["status_param"])
                  if (r.get("unreadCount") or 0) > 0]
        rows = {r["id"]: (r, False) for r in unread}
        window_total = 0
        if args.mode == "brief":
            since = now - timedelta(hours=args.window_hours)
            for r in client.search_conversations(since, limit=100, max_pages=pages):
                window_total += 1
                rows[r["id"]] = (rows.get(r["id"], (r, True))[0], True)
        cands = [candidate(client, r, reg, now, cache, in_window)
                 for r, in_window in rows.values()]
    except ghl_client.GhlBlocked as exc:
        die(str(exc), f"the environment's network policy must allow {ghl_client.BASE}; "
            "never work around it", code=3)
    except ghl_client.GhlError as exc:
        die(str(exc), code=1)

    todo = {"contract_version": TODO_VERSION, "rubric_version": reg["rubric"]["version"],
            "batches": []}
    unknown_sources = {}
    for c in cands:
        texts = c.pop("_texts")
        for s, n in c.pop("_unknown_outbound_sources").items():
            unknown_sources[s] = unknown_sources.get(s, 0) + n
        if c["hold_reason"] is None and c["cached"] is None and c["batch_key"]:
            todo["batches"].append({"batch_key": c["batch_key"], "messages": [
                {"n": i + 1, "channel": c["channel"], "text": t} for i, t in enumerate(texts)]})

    doc = {
        "contract_version": CANDIDATES_VERSION, "run_id": run_id, "mode": args.mode,
        "run_at": now.astimezone(TZ).isoformat(timespec="seconds"),
        "rubric_version": reg["rubric"]["version"], "write_mode": reg["write_mode"]["mode"],
        "log": dict({"ref": ref, "status": log_status, "kill_switch": kill,
                     "cache_hits": sum(1 for c in cands if c["cached"])}, **health),
        "counts": {"unread_total": len(unread), "window_total": window_total,
                   "conversations": len(cands), "to_judge": len(todo["batches"]),
                   "unknown_outbound_sources": unknown_sources,
                   "ghl_requests": client.stats()["requests"] if hasattr(client, "stats") else None},
        "conversations": cands,
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "candidates.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    (out_dir / "todo.json").write_text(json.dumps(todo, indent=1, ensure_ascii=False) + "\n")
    return doc, out_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("sweep", "brief"), required=True)
    ap.add_argument("--window-hours", type=float, default=24, help="Brief mode: the activity window")
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    ap.add_argument("--no-log", action="store_true",
                    help="Do not read the log branch (no cache, no health). Tests and dry runs")
    args = ap.parse_args(argv)
    doc, out_dir = run(args)
    c = doc["counts"]
    held = {}
    for x in doc["conversations"]:
        if x["hold_reason"]:
            held[x["hold_reason"]] = held.get(x["hold_reason"], 0) + 1
    print(f"  mode         {doc['mode']}   run {doc['run_id']}   write_mode {doc['write_mode']}")
    print(f"  log          {doc['log']['status']}   cache hits {doc['log']['cache_hits']}"
          + (f"   KILL SWITCH: {doc['log']['kill_switch']}" if doc["log"]["kill_switch"] else ""))
    print(f"  unread       {c['unread_total']}   window {c['window_total']}   total {c['conversations']}")
    print(f"  held         {sum(held.values())} {held}")
    print(f"  to judge     {c['to_judge']}")
    if c["unknown_outbound_sources"]:
        print(f"  unknown outbound sources (treated as automation): {c['unknown_outbound_sources']}")
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
