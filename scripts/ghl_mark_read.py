#!/usr/bin/env python3
"""The only file in this repo that writes to GoHighLevel: mark an approved conversation read.

    python3 scripts/ghl_mark_read.py --dir analysis/cache/ghl-triage/<date>/<run_id>

Run by ghl-actions-agent only, from /ghl-triage step 5, on that run's plan.json and
approval.json (contracts/ghl-triage-schema.md). It can do exactly one thing:

    PUT <ghl_client.BASE>/conversations/<20-char id>
    {"locationId": <GHL_LOCATION_ID>, "unreadCount": 0}

with its own token, GHL_MARK_READ_TOKEN (scope conversations.write only — "two tokens, two
blast radii", methods/architecture.md). Every read goes through ghl_client (GET-only, the
read PIT). The host comes from ghl_client.BASE, so it is spelled in one file.

Per approved action, in plan order:
  1. preflight (once): write_mode is write; the approval names this plan; a policy approval
     needs policy.exception_date; the plan has not expired; approved ids within the cap; the
     kill switch is off; the token is present.
  2. skip an id already `executed` (log branch or this run's results) — skipped_duplicate.
  3. compare-and-swap: re-read the conversation. Already read -> refused stale_already_read.
     A newer message than the plan saw -> refused stale_new_message. Nothing is written.
  4. the PUT.
  5. read back: unreadCount 0 and the same newest message -> executed. A message arrived
     during the write -> failed raced_new_message, exit 6 (the command trips the kill
     switch). unreadCount not 0 -> failed readback_mismatch.
Every entry is written to <dir>/results.json before the next action. The first failure
stops the batch.

Exit codes: 0 ok · 2 config/credentials · 3 host blocked · 4 preflight refused ·
5 an action failed · 6 race (kill switch).
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import ghl_client  # noqa: E402
import ghl_triage_log  # noqa: E402
import ghl_unread_pull  # noqa: E402

REGISTRY = REPO_ROOT / "platform-settings" / "ghl-unread-triage.json"
TZ = ZoneInfo("America/Toronto")
TOKEN_ENV = "GHL_MARK_READ_TOKEN"
ACTION_TYPE = "mark_conversation_read"
AGENT = "ghl-actions-agent"
ID_FORMAT = re.compile(r"^[A-Za-z0-9]{20}$")
RETRY = (401, 429, 500, 502, 503, 504)


class Refused(RuntimeError):
    pass


def load_registry(path=REGISTRY):
    return json.loads(Path(path).read_text())


def body_for(location_id):
    """The one body this file ever sends."""
    return {"locationId": location_id, "unreadCount": 0}


def put_request(conversation_id, token, location_id, version):
    if not ID_FORMAT.match(conversation_id or ""):
        raise Refused(f"not a GHL conversation id: {conversation_id!r}")
    return urllib.request.Request(
        ghl_client.BASE + "/conversations/" + conversation_id,
        data=json.dumps(body_for(location_id)).encode(), method="PUT",
        headers={"Authorization": "Bearer " + token, "Version": version,
                 "Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "titan-agents/ghl_mark_read (+one write: unreadCount 0)"})


class Writer:
    def __init__(self, reg, reader, token, location_id, opener=None, sleep=time.sleep):
        self.reg, self.reader, self.token, self.location_id = reg, reader, token, location_id
        self.version = reg["writer"]["api_version"]
        self.open = opener or urllib.request.urlopen
        self.sleep = sleep

    def state(self, conversation_id):
        """(unreadCount, newest relevant message id) via the read client."""
        conv = self.reader.get_conversation(conversation_id)
        rows = next(ghl_unread_pull.iter_pages(self.reader, conversation_id, 20, 1))[0]
        return conv.get("unreadCount") or 0, ghl_unread_pull.newest_relevant_id(rows, self.reg["batch"])

    def put(self, conversation_id):
        """None on success, else 'http_<code>'."""
        last = "http_unknown"
        for attempt in range(4):
            req = put_request(conversation_id, self.token, self.location_id, self.version)
            try:
                with self.open(req, timeout=60) as r:
                    r.read()
                    return None
            except urllib.error.HTTPError as e:
                last = f"http_{e.code}"
                if e.code in RETRY:
                    self.sleep(min(2 ** attempt, 16))
                    continue
                return last
            except urllib.error.URLError as e:
                if ghl_client.classify_url_error(e) == "host_blocked":
                    raise ghl_client.GhlBlocked(str(e))
                last = "network_error"
                self.sleep(min(2 ** attempt, 16))
        return last


def preflight(plan, approval, reg, now, kill, token, plan_path):
    problems = []
    if reg["write_mode"]["mode"] != "write":
        problems.append(f"write_mode is {reg['write_mode']['mode']!r}")
    if plan.get("mode") != "sweep":
        problems.append("only a sweep plan is ever executed")
    if not approval:
        problems.append("no approval file — absence means nothing is approved")
        return problems
    if approval.get("run_id") != plan.get("run_id") or \
            Path(approval.get("plan", "")).name != Path(plan_path).name:
        problems.append("the approval does not name this plan")
    by = approval.get("approved_by") or ""
    if not by:
        problems.append("approved_by is blank")
    if by == reg["policy"]["approved_by"] and not reg["policy"].get("exception_date"):
        problems.append("policy approval while policy.exception_date is null")
    if datetime.fromisoformat(plan["expires"]) < now:
        problems.append(f"the plan expired at {plan['expires']}")
    approved = [d["id"] for d in approval.get("decisions", []) if d.get("status") == "approved"]
    known = {a["id"] for a in plan.get("actions", [])}
    if set(approved) - known:
        problems.append("the approval names ids the plan does not have")
    if by == reg["policy"]["approved_by"] and len(approved) > reg["policy"]["max_mark_read_per_run"]:
        problems.append("more approved ids than the cap")
    if kill:
        problems.append(f"the kill switch is on: {kill}")
    if not token:
        problems.append(f"{TOKEN_ENV} is not set in .env")
    return problems


def log_entry(action, result, error, approved_by, now):
    return {"logged_at": now.isoformat(timespec="seconds"), "agent": AGENT, "type": ACTION_TYPE,
            "target": f"conversation {action['conversation_id']} (contact {action.get('contact_id')})",
            "content_summary": f"{action['verdict']}: {action['reason']}",
            "approved_by": approved_by, "result": result, "error": error,
            "raw_ref": action["conversation_id"], "raw_ref_action_id": action["id"]}


def execute(plan, approval, writer, done_ids, results_path, now_fn=lambda: datetime.now(TZ),
            prior=None):
    """Run the approved actions. Returns (this run's entries, exit_code). results_path keeps
    `prior` entries plus these, rewritten after every action."""
    approved = {d["id"] for d in approval["decisions"] if d.get("status") == "approved"}
    by = approval["approved_by"]
    prior, entries = list(prior or []), []

    def record(action, result, error=None):
        entries.append(log_entry(action, result, error, by, now_fn()))
        results_path.write_text(json.dumps(prior + entries, indent=1, ensure_ascii=False) + "\n")

    for action in sorted(plan["actions"], key=lambda a: a["seq"]):
        if action["id"] not in approved:
            continue
        if action["id"] in done_ids:
            record(action, "skipped_duplicate")
            continue
        cid, expect = action["conversation_id"], action["expect"]["last_message_id"]
        unread, newest = writer.state(cid)
        if unread == 0:
            record(action, "refused", "stale_already_read")
            continue
        if newest != expect:
            record(action, "refused", "stale_new_message")
            continue
        err = writer.put(cid)
        if err:
            record(action, "failed", err)
            return entries, 5
        unread, newest = writer.state(cid)
        if newest != expect:
            record(action, "failed", "raced_new_message")
            return entries, 6
        if unread != 0:
            record(action, "failed", "readback_mismatch")
            return entries, 5
        record(action, "executed")
    return entries, 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    args = ap.parse_args(argv)
    reg = load_registry(args.registry)
    if reg["writer"]["token_env"] != TOKEN_ENV:
        print("error: registry writer.token_env disagrees with this file", file=sys.stderr)
        return 2
    plan_path = args.dir / "plan.json"
    plan = json.loads(plan_path.read_text())
    apath = args.dir / "approval.json"
    approval = json.loads(apath.read_text()) if apath.exists() else None

    ghl_client.load_dotenv(REPO_ROOT / ".env")
    token = os.environ.get(TOKEN_ENV)
    status = ghl_triage_log.fetch(REPO_ROOT, reg)
    ref = ghl_triage_log.remote_ref(reg)
    kill = ghl_triage_log.kill_switch(REPO_ROOT, reg, ref) if status == "ok" else \
        f"log branch unreadable ({status})"
    now = datetime.now(TZ)
    problems = preflight(plan, approval, reg, now, kill, token, plan_path)
    if problems:
        print("refused — nothing written:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 4

    done = {e.get("raw_ref_action_id") for e in ghl_triage_log.load_actions(
        REPO_ROOT, reg, ghl_triage_log.recent_days(now, 2), ref) if e.get("result") == "executed"}
    results_path = args.dir / "results.json"
    prior = json.loads(results_path.read_text()) if results_path.exists() else []
    done |= {e.get("raw_ref_action_id") for e in prior if e.get("result") == "executed"}
    try:
        reader = ghl_client.GhlClient()
        writer = Writer(reg, reader, token, reader.location_id)
        entries, code = execute(plan, approval, writer, done, results_path, prior=prior)
    except ghl_client.GhlBlocked as exc:
        print(f"error: host blocked: {exc}", file=sys.stderr)
        return 3
    except ghl_client.GhlError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    tally = {}
    for e in entries:
        k = e["result"] + (f":{e['error']}" if e["error"] else "")
        tally[k] = tally.get(k, 0) + 1
    print(f"  results      {tally} -> {results_path}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
