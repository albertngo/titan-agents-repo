#!/usr/bin/env python3
"""Publish a run: push the session branch and open (or find) its PR against main-agents.

    python3 scripts/publish_run.py --title "price list: PL-381 IMPRESSIVE" --body-file /tmp/body.md

Why this exists. Every price-list run commits to its own `claude/*` branch, and
until 2026-09-23 nothing pushed a PR for it. Fifteen branches ended up carrying
~100 commits that never reached main-agents: live-write logs, plans, CSVs and at
least eleven code fixes, several of which were then rediscovered and re-fixed by
later runs (the supply_price 422 four times). A run whose output does not reach
main-agents is invisible to the next run, so this step is part of the run, not
tidy-up afterwards.

Fail closed: exit 0 only when the branch is pushed AND a PR exists; the URL is
printed on the last line. Anything else exits non-zero, and the run must report
itself PARTIAL, naming the branch.

It never merges. Albert merges (CLAUDE.md, Git workflow, 2026-07-27).

Credentials: GH_TOKEN or GITHUB_TOKEN from the environment, used only for the
GitHub REST call. The token is never printed.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

BASE = "main-agents"
API = "https://api.github.com"


def git(*args, check=True):
    return subprocess.run(["git", *args], check=check, capture_output=True, text=True)


def repo_slug(remote_url):
    """'owner/repo' from an https or ssh GitHub remote, or a proxied one."""
    m = re.search(r"github\.com[/:]([^/]+)/([^/.]+?)(?:\.git)?/?$", remote_url.strip())
    if not m:
        m = re.search(r"/([^/]+)/([^/.]+?)(?:\.git)?/?$", remote_url.strip())
    if not m:
        raise ValueError(f"cannot read owner/repo from remote {remote_url!r}")
    return f"{m.group(1)}/{m.group(2)}"


def api(method, path, token, body=None, opener=urllib.request.urlopen):
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"})
    with opener(req, timeout=30) as resp:
        return json.loads(resp.read() or b"null")


def find_or_open_pr(slug, branch, title, body, token, opener=urllib.request.urlopen):
    """Return (url, created). Reuses an open PR for the branch rather than duplicating it."""
    owner = slug.split("/")[0]
    existing = api("GET", f"/repos/{slug}/pulls?state=open&head={owner}:{branch}&base={BASE}",
                   token, opener=opener)
    if existing:
        return existing[0]["html_url"], False
    pr = api("POST", f"/repos/{slug}/pulls", token,
             {"title": title, "head": branch, "base": BASE, "body": body}, opener=opener)
    return pr["html_url"], True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--title", required=True)
    ap.add_argument("--body-file", help="Markdown PR body. Default: the latest commit message.")
    args = ap.parse_args()

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch in (BASE, "main", "HEAD"):
        print(f"PUBLISH FAILED: on {branch!r}. A run works on its own session branch; "
              "refusing to push to a shared branch.", file=sys.stderr)
        return 2
    if git("status", "--porcelain").stdout.strip():
        print("PUBLISH FAILED: uncommitted changes. Commit the run's files first, so the "
              "PR carries everything the run produced.", file=sys.stderr)
        return 2

    push = subprocess.run(["git", "push", "-u", "origin", branch], capture_output=True, text=True)
    if push.returncode != 0:
        print(f"PUBLISH FAILED: git push of {branch} failed:\n{push.stderr.strip()}",
              file=sys.stderr)
        return 1

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print(f"PUBLISH PARTIAL: {branch} is pushed but no GH_TOKEN/GITHUB_TOKEN is set, so "
              f"no PR was opened. Open one from {branch} into {BASE} by hand.", file=sys.stderr)
        return 1

    body = (open(args.body_file).read() if args.body_file
            else git("log", "-1", "--format=%B").stdout)
    try:
        slug = repo_slug(git("remote", "get-url", "origin").stdout)
        url, created = find_or_open_pr(slug, branch, args.title, body, token)
    except (urllib.error.URLError, ValueError, KeyError, IndexError) as e:
        detail = e.read().decode(errors="replace")[:400] if hasattr(e, "read") else str(e)
        print(f"PUBLISH PARTIAL: {branch} is pushed but the PR could not be opened: "
              f"{detail}", file=sys.stderr)
        return 1

    print(f"{'opened' if created else 'already open'}: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
