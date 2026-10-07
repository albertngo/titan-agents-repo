#!/usr/bin/env python3
"""Decide what /blog-sweep may write back, from a posts snapshot and a checks file.

    python3 scripts/blog_sweep.py --rows ingest/<date>/blog-posts-snapshot.json \
        --checks ingest/<date>/blog-sweep-checks.json [--registry ...] [--now ISO] [--out ...]

Pure decider: reads the two files, prints JSON, writes nothing to any platform. The
command gathers the checks (PR state from GitHub, an HTTP HEAD of the expected URL, the
canonical tag, the current body hash from Notion, a linked Content Idea's live YouTube
URL) and then writes exactly what this script proposes, through blog-actions-agent.

checks file:
  {"production_host": "titan-website.vercel.app",
   "posts": {"<slug>": {"pr_state": "open"|"merged"|"closed"|null, "http_status": 200|404|null,
                        "canonical": "https://.../<slug>/"|null, "body_sha1": "..."|null,
                        "video_url": "https://youtu.be/..."|null}}}

Rules (methods/content-engine.md, Sweep):
  * Approved + PR merged + 200 + canonical == expected URL  -> propose Published
    (Direct URL, Publish Date = today, Status Published; expect Status Approved);
  * Approved + PR open                                        -> not_yet (waiting on merge);
  * Approved + PR merged but not 200                          -> not_yet (deploy pending);
  * 200 but canonical differs                                 -> url_mismatch, no write;
  * PR closed without merge                                   -> needs_person;
  * Published + body_sha1 differs from the published sha1    -> flag body_changed_after_publish;
  * Published + video_url present + Video URL blank           -> video_candidate (Phase 4 embeds it).
Absence of a check is never treated as success.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_engine_lib import action_id, load_registry, now_local, read_json  # noqa: E402

CONTRACT_VERSION = "blog-sweep-1"
PUBLISHED = {"Published", "Posted"}


def expected_url(reg, host, slug):
    return reg["website"]["url_template"].format(host=host, slug=slug)


def decide(reg, rows, checks, now):
    host = checks.get("production_host") or reg["website"].get("production_host")
    per = checks.get("posts", {})
    props = reg["sources"]["blog_posts"]["properties"]
    out = {"contract_version": CONTRACT_VERSION, "run_at": now.isoformat(timespec="seconds"), "production_host": host,
           "proposals": [], "not_yet": [], "url_mismatch": [], "needs_person": [], "flagged": [], "video_candidates": []}
    for r in rows:
        slug, st, bp = r.get("slug"), r.get("status"), r.get("id")
        if not slug:
            continue
        c = per.get(slug)
        if st == "Approved" and r.get("pr_url"):
            if not host:
                out["needs_person"].append({"bp_id": bp, "slug": slug, "detail": "no production_host known"})
                continue
            if c is None:
                out["not_yet"].append({"bp_id": bp, "slug": slug, "detail": "no check gathered"})
                continue
            url = expected_url(reg, host, slug)
            if c.get("pr_state") == "open":
                out["not_yet"].append({"bp_id": bp, "slug": slug, "detail": "PR open, waiting on merge"})
            elif c.get("pr_state") == "closed":
                out["needs_person"].append({"bp_id": bp, "slug": slug, "detail": "PR closed without merge"})
            elif c.get("pr_state") == "merged":
                if c.get("http_status") != 200:
                    out["not_yet"].append({"bp_id": bp, "slug": slug, "detail": f"merged, HTTP {c.get('http_status')} at {url} (deploy pending?)"})
                elif (c.get("canonical") or "").rstrip("/") != url.rstrip("/"):
                    out["url_mismatch"].append({"bp_id": bp, "slug": slug, "detail": f"canonical {c.get('canonical')!r} != {url}"})
                else:
                    fields = {props["direct_url"]: url, props["publish_date"]: now.strftime("%Y-%m-%d"), props["status"]: "Published"}
                    out["proposals"].append({
                        "id": action_id("notion", "update_blog_post", r["url"], list(fields.keys())),
                        "target_system": "notion", "type": "notion_update_blog_post", "op": "update_blog_post",
                        "target": {"page": r["url"], "bp_id": bp}, "fields": fields, "expect": {"Status": "Approved"},
                        "published_sha1": c.get("body_sha1"),
                    })
            else:
                out["not_yet"].append({"bp_id": bp, "slug": slug, "detail": f"unknown pr_state {c.get('pr_state')!r}"})
        elif st in PUBLISHED and c:
            if r.get("published_sha1") and c.get("body_sha1") and c["body_sha1"] != r["published_sha1"]:
                out["flagged"].append({"bp_id": bp, "slug": slug, "reason": "body_changed_after_publish",
                                       "detail": "Notion body edited after publish; the MDX is canonical now (re-publish by PR if intended)"})
            if c.get("video_url") and not r.get("video_url"):
                out["video_candidates"].append({"bp_id": bp, "slug": slug, "video_url": c["video_url"]})
    out["summary"] = {k: len(out[k]) for k in ("proposals", "not_yet", "url_mismatch", "needs_person", "flagged", "video_candidates")}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", required=True)
    ap.add_argument("--checks", required=True)
    ap.add_argument("--registry")
    ap.add_argument("--now")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    try:
        reg = load_registry(args.registry)
        rows = read_json(args.rows).get("rows", [])
        checks = read_json(args.checks)
    except (OSError, ValueError, KeyError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2
    now = datetime.fromisoformat(args.now) if args.now else now_local()
    result = decide(reg, rows, checks, now)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
