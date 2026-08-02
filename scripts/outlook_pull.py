#!/usr/bin/env python3
"""
Read-only Microsoft Graph mail puller for outlook-ingest-agent.

Why a script and not an MCP server: a claude.ai connector is session-attached,
and in a deferred-tool session a subagent cannot resolve its tools at all
(proven 2026-08-02 — see the failure table in
.claude/agents/outlook-ingest-agent.md). Bash always works. This also makes
scheduled/unattended runs possible, which a session connector never will.

App-only auth (client credentials). Emits normalized message metadata as JSON
on stdout; the agent does the classification. GET only — this script has no
code path that writes to a mailbox.

Usage:
    python3 scripts/outlook_pull.py --hours 24
    python3 scripts/outlook_pull.py --hours 168 --mailbox info@titanfloors.ca
    python3 scripts/outlook_pull.py --hours 24 --folder SentItems --out /tmp/sent.json

Env (see .env.example):
    GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
    OUTLOOK_MAILBOXES   comma-separated; default read from
                        platform-settings/outlook-ingest-sources.json
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(REPO_ROOT, "platform-settings", "outlook-ingest-sources.json")
GRAPH = "https://graph.microsoft.com/v1.0"

# Fields the agent classifies from. bodyPreview is deliberately short — the
# contract forbids raw dumps, and full bodies would blow the response budget.
SELECT = ",".join([
    "id", "internetMessageId", "subject", "from", "toRecipients", "ccRecipients",
    "receivedDateTime", "sentDateTime", "hasAttachments", "importance",
    "isRead", "bodyPreview", "webLink", "conversationId",
])


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


def die(msg, hint=None, code=2):
    out = {"error": msg}
    if hint:
        out["hint"] = hint
    print(json.dumps(out, indent=2), file=sys.stderr)
    sys.exit(code)


def get_token(tenant, client_id, secret):
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode()
    url = "https://login.microsoftonline.com/%s/oauth2/v2.0/token" % tenant
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=30) as r:
            return json.load(r)["access_token"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        die("Token request failed (HTTP %s)" % e.code, detail +
            "\nCheck GRAPH_TENANT_ID / GRAPH_CLIENT_ID / GRAPH_CLIENT_SECRET. "
            "A secret VALUE is required, not the secret ID, and it expires.")


def graph_get(url, token):
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def fetch_folder(mailbox, folder, since_iso, token, page_size, max_pages):
    """One folder of one mailbox. Returns (messages, error_or_None)."""
    q = urllib.parse.urlencode({
        "$select": SELECT,
        "$filter": "receivedDateTime ge %s" % since_iso,
        "$orderby": "receivedDateTime desc",
        "$top": str(page_size),
    })
    url = "%s/users/%s/mailFolders/%s/messages?%s" % (
        GRAPH, urllib.parse.quote(mailbox), folder, q)

    out, pages = [], 0
    while url and pages < max_pages:
        try:
            data = graph_get(url, token)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 403:
                return out, ("403 Forbidden on %s/%s. The app lacks Mail.Read, admin "
                             "consent was never granted, or an Application Access Policy "
                             "excludes this mailbox. Detail: %s" % (mailbox, folder, detail))
            if e.code == 404:
                return out, ("404 on %s/%s — mailbox or folder not found. Shared mailboxes "
                             "work app-only, but the address must be exact. Detail: %s"
                             % (mailbox, folder, detail))
            return out, "HTTP %s on %s/%s: %s" % (e.code, mailbox, folder, detail)
        except Exception as e:  # network, timeout, malformed JSON
            return out, "%s on %s/%s: %s" % (type(e).__name__, mailbox, folder, e)

        for m in data.get("value", []):
            sender = (m.get("from") or {}).get("emailAddress") or {}
            out.append({
                "mailbox": mailbox,
                "folder": folder,
                "id": m.get("id"),
                "internetMessageId": m.get("internetMessageId"),
                "conversationId": m.get("conversationId"),
                "subject": m.get("subject"),
                "sender": sender.get("address"),
                "sender_name": sender.get("name"),
                "recipients": [
                    (r.get("emailAddress") or {}).get("address")
                    for r in (m.get("toRecipients") or [])
                ],
                "cc": [
                    (r.get("emailAddress") or {}).get("address")
                    for r in (m.get("ccRecipients") or [])
                ],
                "receivedDateTime": m.get("receivedDateTime"),
                "sentDateTime": m.get("sentDateTime"),
                "hasAttachments": m.get("hasAttachments"),
                "importance": m.get("importance"),
                "isRead": m.get("isRead"),
                "summary": (m.get("bodyPreview") or "")[:400],
                "webLink": m.get("webLink"),
            })
        url = data.get("@odata.nextLink")
        pages += 1
    return out, None


def default_mailboxes():
    env = os.environ.get("OUTLOOK_MAILBOXES")
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]
    try:
        with open(SETTINGS) as fh:
            cfg = json.load(fh)
        mb = cfg.get("mailbox", {})
        boxes = [mb["primary"]] if mb.get("primary") else []
        boxes += [b for b in mb.get("shared_mailboxes", []) if b not in boxes]
        return boxes
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser(description="Read-only Graph mail puller.")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--mailbox", action="append", dest="mailboxes",
                    help="Repeatable. Defaults to the settings file.")
    ap.add_argument("--folder", default="Inbox",
                    help="Graph well-known name: Inbox, SentItems, Archive, JunkEmail.")
    ap.add_argument("--page-size", type=int, default=50)
    ap.add_argument("--max-pages", type=int, default=6)
    ap.add_argument("--out", help="Write JSON here instead of stdout.")
    args = ap.parse_args()

    load_dotenv(os.path.join(REPO_ROOT, ".env"))
    tenant = os.environ.get("GRAPH_TENANT_ID")
    client_id = os.environ.get("GRAPH_CLIENT_ID")
    secret = os.environ.get("GRAPH_CLIENT_SECRET")
    if not all([tenant, client_id, secret]):
        die("Missing Graph credentials.",
            "Set GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET in .env "
            "(see .env.example). This is the expected error before the Azure app "
            "exists — the agent must report it as a setup gap, not a platform outage.")

    mailboxes = args.mailboxes or default_mailboxes()
    if not mailboxes:
        die("No mailboxes configured.",
            "Pass --mailbox, set OUTLOOK_MAILBOXES, or fill mailbox.primary / "
            "mailbox.shared_mailboxes in platform-settings/outlook-ingest-sources.json.")

    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    token = get_token(tenant, client_id, secret)

    messages, errors = [], []
    for box in mailboxes:
        msgs, err = fetch_folder(box, args.folder, since_iso, token,
                                 args.page_size, args.max_pages)
        messages.extend(msgs)
        if err:
            errors.append(err)

    result = {
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": args.hours,
        "since": since_iso,
        "folder": args.folder,
        "mailboxes": mailboxes,
        # partial = at least one mailbox worked; the agent maps this straight
        # onto contract status, so a dead mailbox never fails the whole run.
        "status": "ok" if not errors else ("partial" if messages else "error"),
        "errors": errors,
        "count": len(messages),
        "messages": messages,
    }

    payload = json.dumps(result, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(payload + "\n")
        print("wrote %d messages to %s (status: %s)" % (len(messages), args.out, result["status"]))
    else:
        print(payload)
    sys.exit(0 if result["status"] != "error" else 1)


if __name__ == "__main__":
    main()
