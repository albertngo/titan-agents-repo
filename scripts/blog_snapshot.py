#!/usr/bin/env python3
"""Turn a Notion SQL result (from notion-query-data-sources) into a snapshot file.

    python3 scripts/blog_snapshot.py --kind backlog --in ingest/<date>/topic-backlog-sql.json --out ingest/<date>/topic-backlog-snapshot.json
    python3 scripts/blog_snapshot.py --kind posts   --in ingest/<date>/blog-posts-sql.json   --out ingest/<date>/blog-posts-snapshot.json

Pure transform; reads only the file named. The command saves the MCP tool's `results`
array (or the whole response) as JSON first. Column names are the registry's exact
Notion property names; relation and multi-select columns arrive as JSON strings and are
parsed here; `__YES__` becomes true; `userDefined:ID` becomes `TB-<n>` / `BP-<n>`.

The SQL the commands run (one line, copy exactly):

  backlog: SELECT url, "userDefined:ID", "Topic / Question", "Cluster", "Material", "Source of idea",
           "Volume", "Difficulty", "CPC", "Intent", "Local", "Score", "Status", "Canonical key", "Blog Post"
           FROM "collection://<topic_backlog.data_source>"
  posts:   SELECT url, "userDefined:ID", "Blog Title", "Status", "Slug", "Topic Cluster", "Material",
           "Content Type", "Search Intent", "Primary Keyword", "date:Publish Date:start", "Direct URL",
           "Pillar", "PR URL", "Video URL", "Snippet"
           FROM "collection://<blog_posts.data_source>"
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_engine_lib import load_registry, now_local, read_json, write_json  # noqa: E402

VERSIONS = {"backlog": "topic-backlog-snapshot-1", "posts": "blog-posts-snapshot-1"}


def _list(v):
    if v in (None, ""):
        return []
    if isinstance(v, list):
        return v
    try:
        parsed = json.loads(v)
        return parsed if isinstance(parsed, list) else [parsed]
    except (TypeError, ValueError):
        return [v]


def _bool(v):
    return v == "__YES__" or v is True


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(v) if "." in str(v) else int(float(v))
    except (TypeError, ValueError):
        return None


def to_backlog(rows, prefix):
    out = []
    for r in rows:
        out.append({
            "url": r.get("url"),
            "id": f"{prefix}-{r.get('userDefined:ID')}" if r.get("userDefined:ID") is not None else None,
            "title": r.get("Topic / Question") or "",
            "cluster": r.get("Cluster"),
            "material": _list(r.get("Material")),
            "source": r.get("Source of idea"),
            "volume": _num(r.get("Volume")),
            "difficulty": _num(r.get("Difficulty")),
            "cpc": _num(r.get("CPC")),
            "intent": r.get("Intent"),
            "local": _bool(r.get("Local")),
            "score": _num(r.get("Score")),
            "status": r.get("Status"),
            "canonical_key": r.get("Canonical key") or "",
            "blog_post": _list(r.get("Blog Post")),
        })
    return out


def to_posts(rows, prefix, alias):
    out = []
    for r in rows:
        st = r.get("Status")
        out.append({
            "url": r.get("url"),
            "id": f"{prefix}-{r.get('userDefined:ID')}" if r.get("userDefined:ID") is not None else None,
            "title": r.get("Blog Title") or "",
            "status": alias.get(st, st),
            "status_raw": st,
            "slug": r.get("Slug") or "",
            "topic_cluster": r.get("Topic Cluster"),
            "material": _list(r.get("Material")),
            "content_type": r.get("Content Type"),
            "search_intent": r.get("Search Intent"),
            "primary_keyword": r.get("Primary Keyword") or "",
            "publish_date": r.get("date:Publish Date:start"),
            "direct_url": r.get("Direct URL"),
            "pillar": _list(r.get("Pillar")),
            "pr_url": r.get("PR URL"),
            "video_url": r.get("Video URL"),
            "snippet": r.get("Snippet") or "",
        })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", required=True, choices=list(VERSIONS))
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--registry")
    args = ap.parse_args(argv)
    try:
        reg = load_registry(args.registry)
        data = read_json(args.inp)
    except (OSError, ValueError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2
    rows = data.get("results", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        print("input must be a list of rows or {results: [...]}", file=sys.stderr)
        return 2
    if args.kind == "backlog":
        src = reg["sources"]["topic_backlog"]
        out_rows = to_backlog(rows, src["id_prefix"])
    else:
        src = reg["sources"]["blog_posts"]
        out_rows = to_posts(rows, src["id_prefix"], src.get("status_live_alias", {}))
    write_json(args.out, {"contract_version": VERSIONS[args.kind], "pulled_at": now_local().isoformat(timespec="seconds"),
                          "data_source": src["data_source"], "rows": out_rows})
    print(f"{args.out}: {len(out_rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
