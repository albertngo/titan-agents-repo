#!/usr/bin/env python3
"""The one writer of branch claude/ghl-triage-log — GHL unread triage's audit log and verdict cache.

    python3 scripts/ghl_triage_log.py fetch
    python3 scripts/ghl_triage_log.py show ghl-triage/2026-10-08/runs.json
    python3 scripts/ghl_triage_log.py append --run RUN.json [--actions RESULTS.json] [--kill-switch "why"]
    python3 scripts/ghl_triage_log.py init                       # supervised, once
    python3 scripts/ghl_triage_log.py clear-kill-switch --by "Albert, this session"   # supervised

Why a branch. The sweep fires hourly as a routine; every fire works on its own claude/*
branch, and a PR per fire would be ~14 PRs a day to merge (Albert, 2026-10-07). So every
fire appends its run to one long-lived branch that is never merged and never PR'd
(scripts/publish_run.py refuses it). The next fire reads it back as its verdict cache,
and the daily brief reads it for "last sweep" health.

How. Git plumbing only: a temporary index built from the remote tip, `hash-object`,
`update-index --cacheinfo`, `write-tree`, `commit-tree`, then `git push origin
<sha>:refs/heads/claude/ghl-triage-log`. Nothing is checked out, so the session's own
branch, HEAD and working tree are never touched. A rejected push (another fire got there
first) refetches, rebuilds on the new tip and retries; it never force-pushes. It writes
only under ghl-triage/ and pushes only to that one ref.

Exit codes: 0 ok · 2 usage / refused · 3 log branch missing · 4 push failed after retries.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "platform-settings" / "ghl-unread-triage.json"
TZ = ZoneInfo("America/Toronto")
REMOTE = "origin"
DAY_VERSION = "ghl-triage-day-1"
ACTIONS_LOG_VERSION = "1"


class LogError(RuntimeError):
    code = 2


class BranchMissing(LogError):
    code = 3


class PushFailed(LogError):
    code = 4


def load_registry(path=REGISTRY):
    return json.loads(Path(path).read_text())


def git(repo, *args, input=None, env=None, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], input=input, env=env,
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise LogError(f"git {' '.join(args[:2])} failed: {r.stderr.strip()[:300]}")
    return r


def branch(reg):
    return reg["log"]["branch"]


def remote_ref(reg):
    return f"refs/remotes/{REMOTE}/{branch(reg)}"


def runs_path(reg, date):
    return reg["log"]["runs_file"].format(date=date)


def actions_path(reg, date):
    return reg["log"]["actions_log"].format(date=date)


def check_path(reg, path):
    root = reg["log"]["root"].rstrip("/") + "/"
    if not path.startswith(root) or ".." in Path(path).parts or path.startswith("/"):
        raise LogError(f"refusing to write {path!r}: the log writes only under {root}")
    return path


# -- reading -------------------------------------------------------------------

def fetch(repo, reg):
    """'ok', 'missing', or 'error: …'. Updates refs/remotes/origin/<branch>."""
    r = git(repo, "fetch", "--quiet", REMOTE,
            f"+refs/heads/{branch(reg)}:{remote_ref(reg)}", check=False)
    if r.returncode == 0:
        return "ok"
    err = r.stderr.strip()
    if "couldn't find remote ref" in err or "not found" in err.lower():
        return "missing"
    return "error: " + err[:200]


def show(repo, ref, path):
    r = git(repo, "show", f"{ref}:{path}", check=False)
    return r.stdout if r.returncode == 0 else None


def read_json(repo, ref, path):
    text = show(repo, ref, path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def kill_switch(repo, reg, ref=None):
    """The kill switch's text (any content means ON), else None."""
    text = show(repo, ref or remote_ref(reg), reg["log"]["kill_switch"])
    if text is None:
        return None
    return text.strip() or "kill switch present"


def recent_days(now, days):
    base = now.astimezone(TZ).date()
    return [(base - timedelta(days=i)).isoformat() for i in range(days)]


def load_runs(repo, reg, dates, ref=None):
    out = []
    for d in dates:
        doc = read_json(repo, ref or remote_ref(reg), runs_path(reg, d))
        if doc:
            out.extend(doc.get("runs", []))
    return out


def load_cache(repo, reg, now, rubric_version, ref=None):
    """batch_key -> {verdict, reason, run_id} from earlier runs judged under this rubric.

    Only model judgements are reused (verdict_source model or cache); guards and holds are
    recomputed every run. Newest run wins."""
    cache = {}
    runs = load_runs(repo, reg, recent_days(now, reg["log"]["cache_lookback_days"]), ref)
    for run in sorted(runs, key=lambda r: r.get("run_at", "")):
        if str(run.get("rubric_version")) != str(rubric_version):
            continue
        for row in run.get("rows", []):
            if row.get("verdict_source") in ("model", "cache") and row.get("model_verdict") \
                    and row.get("batch_key"):
                cache[row["batch_key"]] = {"verdict": row["model_verdict"],
                                           "reason": row.get("reason") or "",
                                           "run_id": run.get("run_id")}
    return cache


def load_actions(repo, reg, dates, ref=None):
    out = []
    for d in dates:
        doc = read_json(repo, ref or remote_ref(reg), actions_path(reg, d))
        if doc:
            out.extend(doc.get("entries", []))
    return out


# -- merging -------------------------------------------------------------------

def merge_runs(existing, run, date):
    doc = existing if isinstance(existing, dict) else {}
    doc = {"contract_version": DAY_VERSION, "date": date, "runs": list(doc.get("runs", []))}
    doc["runs"] = [r for r in doc["runs"] if r.get("run_id") != run.get("run_id")] + [run]
    doc["runs"].sort(key=lambda r: r.get("run_at", ""))
    return doc


def _entry_key(e):
    return (e.get("raw_ref_action_id"), e.get("result"), e.get("logged_at"))


def merge_actions(existing, entries):
    doc = existing if isinstance(existing, dict) else {}
    have = list(doc.get("entries", []))
    keys = {_entry_key(e) for e in have}
    for e in entries:
        if _entry_key(e) not in keys:
            have.append(e)
            keys.add(_entry_key(e))
    return {"contract_version": ACTIONS_LOG_VERSION, "entries": have}


def run_date(run):
    return datetime.fromisoformat(run["run_at"]).astimezone(TZ).date().isoformat()


def entry_date(entry):
    return datetime.fromisoformat(entry["logged_at"]).astimezone(TZ).date().isoformat()


# -- writing -------------------------------------------------------------------

def _env(repo):
    env = dict(os.environ)
    if not git(repo, "config", "user.email", check=False).stdout.strip():
        env.setdefault("GIT_AUTHOR_NAME", "titan-agents ghl-triage")
        env.setdefault("GIT_AUTHOR_EMAIL", "ghl-triage@titan-agents.local")
        env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
        env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    return env


def commit_files(repo, reg, files, message, parent=None):
    """Build a commit from `parent` plus `files` ({path: text or None to remove}) without
    touching the working tree, index or HEAD. Returns the commit sha."""
    env = _env(repo)
    with tempfile.TemporaryDirectory() as tmp:
        env["GIT_INDEX_FILE"] = str(Path(tmp) / "index")
        if parent:
            git(repo, "read-tree", parent, env=env)
        else:
            git(repo, "read-tree", "--empty", env=env)
        for path, text in sorted(files.items()):
            check_path(reg, path)
            if text is None:
                git(repo, "update-index", "--force-remove", path, env=env)
                continue
            blob = git(repo, "hash-object", "-w", "--stdin", input=text, env=env).stdout.strip()
            git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        tree = git(repo, "write-tree", env=env).stdout.strip()
        args = ["commit-tree", tree, "-m", message] + (["-p", parent] if parent else [])
        return git(repo, *args, env=env).stdout.strip()


def push(repo, reg, sha):
    r = git(repo, "push", "--quiet", REMOTE, f"{sha}:refs/heads/{branch(reg)}", check=False)
    if r.returncode == 0:
        git(repo, "update-ref", remote_ref(reg), sha, check=False)
        return True, ""
    return False, r.stderr.strip()[:300]


def append(repo, reg, run=None, actions=None, kill=None, clear_kill_by=None, retries=None,
           sleep=time.sleep):
    """Merge a run record and/or actions-log entries into the branch and push. Returns sha."""
    retries = reg["log"]["push_retries"] if retries is None else retries
    last = ""
    for attempt in range(retries + 1):
        status = fetch(repo, reg)
        if status == "missing":
            raise BranchMissing(f"branch {branch(reg)} does not exist on {REMOTE}; a person "
                                "runs `ghl_triage_log.py init` once, supervised")
        if status != "ok":
            last = status
            sleep(min(2 ** (attempt + 1), 16))
            continue
        tip = git(repo, "rev-parse", remote_ref(reg)).stdout.strip()
        files, what = {}, []
        if run:
            date = run_date(run)
            path = runs_path(reg, date)
            files[path] = json.dumps(merge_runs(read_json(repo, tip, path), run, date),
                                     indent=1, ensure_ascii=False) + "\n"
            what.append(f"run {run['run_id']}")
        by_date = {}
        for e in actions or []:
            by_date.setdefault(entry_date(e), []).append(e)
        for date, entries in by_date.items():
            path = actions_path(reg, date)
            files[path] = json.dumps(merge_actions(read_json(repo, tip, path), entries),
                                     indent=1, ensure_ascii=False) + "\n"
            what.append(f"{len(entries)} actions")
        if kill:
            files[reg["log"]["kill_switch"]] = f"{datetime.now(TZ).isoformat()} {kill}\n"
            what.append("KILL SWITCH ON")
        if clear_kill_by:
            files[reg["log"]["kill_switch"]] = None
            what.append(f"kill switch cleared by {clear_kill_by}")
        if not files:
            raise LogError("nothing to append")
        sha = commit_files(repo, reg, files, "ghl-triage: " + ", ".join(what), parent=tip)
        ok, err = push(repo, reg, sha)
        if ok:
            return sha
        last = err
        sleep(min(2 ** (attempt + 1), 16))
    raise PushFailed(f"could not push {branch(reg)} after {retries + 1} attempts: {last}")


def init(repo, reg):
    if fetch(repo, reg) == "ok":
        raise LogError(f"{branch(reg)} already exists; init runs once")
    readme = (
        "# GHL unread triage log\n\n"
        "Audit log and verdict cache for `/ghl-triage` (methods/ghl-unread-triage.md).\n"
        "Written only by `scripts/ghl_triage_log.py`. **Never merge this branch, never open a "
        "PR from it.** `scripts/publish_run.py` refuses it.\n\n"
        "- `ghl-triage/<date>/runs.json` — one record per sweep (contracts/ghl-triage-schema.md)\n"
        "- `ghl-triage/<date>/actions-log.json` — every mark-read attempt "
        "(contracts/actions-log-schema.md, type `mark_conversation_read`)\n"
        "- `ghl-triage/KILL_SWITCH` — present = no writes until a person removes it\n")
    sha = commit_files(repo, reg, {reg["log"]["root"] + "/README.md": readme},
                       "ghl-triage: start the log branch (never merge)")
    ok, err = push(repo, reg, sha)
    if not ok:
        raise PushFailed(err)
    return sha


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", type=Path, default=REPO_ROOT)
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    s = sub.add_parser("show")
    s.add_argument("path")
    a = sub.add_parser("append")
    a.add_argument("--run", type=Path)
    a.add_argument("--actions", type=Path, help="JSON list of actions-log entries (writer results)")
    a.add_argument("--kill-switch", help="Turn the kill switch on, with this reason")
    sub.add_parser("init")
    c = sub.add_parser("clear-kill-switch")
    c.add_argument("--by", required=True, help='Who cleared it, e.g. "Albert, this session"')
    args = ap.parse_args(argv)
    reg = load_registry(args.registry)
    try:
        if args.cmd == "fetch":
            status = fetch(args.repo, reg)
            print(status)
            return 0 if status == "ok" else (3 if status == "missing" else 2)
        if args.cmd == "show":
            text = show(args.repo, remote_ref(reg), args.path)
            if text is None:
                print(f"{args.path}: not on {branch(reg)}", file=sys.stderr)
                return 2
            sys.stdout.write(text)
            return 0
        if args.cmd == "append":
            run = json.loads(args.run.read_text()) if args.run else None
            actions = json.loads(args.actions.read_text()) if args.actions else None
            if isinstance(actions, dict):
                actions = actions.get("entries", [])
            sha = append(args.repo, reg, run=run, actions=actions, kill=args.kill_switch)
            print(sha)
            return 0
        if args.cmd == "init":
            print(init(args.repo, reg))
            return 0
        if args.cmd == "clear-kill-switch":
            print(append(args.repo, reg, clear_kill_by=args.by))
            return 0
    except LogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
