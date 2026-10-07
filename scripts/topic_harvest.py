#!/usr/bin/env python3
"""Normalise raw topic material into candidates for the Topic Backlog.

    python3 scripts/topic_harvest.py --mode seed --seeds ingest/<date>/topic-seeds.json \
        --backlog ingest/<date>/topic-backlog-snapshot.json \
        --posts ingest/<date>/blog-posts-snapshot.json \
        [--registry platform-settings/content-engine.json] [--out ingest/<date>/topic-candidates-seed.json]

Reads ONLY the files named on the command line. Holds no credentials and writes nothing
to any platform: the command fetches the snapshots through the Notion MCP and
blog-actions-agent writes what the plan approves.

What it does to every raw item:
  1. canonical key   lower-case alphanumeric tokens (the dedupe key, set once);
  2. cluster         first matching registry rule, else held `cluster_unresolved`;
  3. local           any registry local token in the query;
  4. intent          first matching registry intent rule, else Informational;
  5. dedupe          Jaccard >= scoring.duplicate_jaccard against backlog canonical keys
                     -> held `possible_duplicate`; >= scoring.overlap_jaccard against
                     Blog Posts titles -> held `possible_overlap`; exact key already in
                     the backlog -> held `possible_duplicate`;
  6. status          transcript seeds land as `Proposed`, everything else `Backlog`
                     (registry sources.topic_backlog.seed_status).

Raw file shapes accepted (`--seeds`, repeatable):
  topic-seeds-1   {"contract_version": "topic-seeds-1", "source": "seed"|"transcript"|...,
                   "seeds": [{"question": "...", "material": [...], "cluster": "<slug>"?,
                              "volume": n?, "difficulty": n?, "cpc": x?}]}
  topic-raw-1     {"contract_version": "topic-raw-1", "source": "openseo-related"|"paa"|...,
                   "items": [{"query": "...", "volume": n?, "difficulty": n?, "cpc": x?}]}
Phase 2 adapters turn OpenSEO / GSC responses into topic-raw-1; this script never changes.

Exit codes: 0 ok, 2 missing or malformed input.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_engine_lib import (  # noqa: E402
    REPO_ROOT, canonical_key, clusters, is_local, jaccard, load_registry, map_cluster,
    map_intent, now_local, read_json, today, tokens, write_json,
)

CONTRACT_VERSION = "topic-candidates-1"


def load_raw(path):
    data = read_json(path)
    cv = data.get("contract_version")
    source = data.get("source", "seed")
    if cv == "topic-seeds-1":
        items = [dict(query=s.get("question", ""), **{k: s.get(k) for k in ("material", "cluster", "volume", "difficulty", "cpc")})
                 for s in data.get("seeds", [])]
    elif cv == "topic-raw-1":
        items = [dict(query=i.get("query", ""), material=i.get("material"), cluster=i.get("cluster"),
                      volume=i.get("volume"), difficulty=i.get("difficulty"), cpc=i.get("cpc"))
                 for i in data.get("items", [])]
    else:
        raise ValueError(f"{path}: unknown contract_version {cv!r}")
    return source, items


def harvest(reg, raws, backlog_rows, post_rows):
    dup_j = reg["scoring"]["duplicate_jaccard"]
    ovl_j = reg["scoring"]["overlap_jaccard"]
    seed_status = reg["sources"]["topic_backlog"]["seed_status"]
    valid_clusters = clusters(reg)
    materials_ok = set(reg["sources"]["blog_posts"]["material_values"])

    backlog_keys = {}
    for r in backlog_rows:
        k = r.get("canonical_key") or canonical_key(r.get("title", ""))
        if k:
            backlog_keys[k] = r
    post_titles = [(canonical_key(p.get("title", "")), p) for p in post_rows if p.get("title")]

    candidates, held, flagged = [], [], []
    seen = {}
    for source, items in raws:
        status = seed_status.get(source, seed_status["_default"])
        for it in items:
            q = (it.get("query") or "").strip()
            if not q:
                continue
            key = canonical_key(q)
            if key in seen:
                held.append({"title": q, "reason": "possible_duplicate", "detail": f"repeats '{seen[key]}' in this run"})
                continue
            seen[key] = q
            if key in backlog_keys:
                held.append({"title": q, "reason": "possible_duplicate",
                             "detail": f"exact canonical key already in backlog ({backlog_keys[key].get('id', '?')})"})
                continue
            best = max(((jaccard(tokens(key), tokens(bk)), br) for bk, br in backlog_keys.items()),
                       key=lambda t: t[0], default=(0.0, None))
            if best[0] >= dup_j:
                held.append({"title": q, "reason": "possible_duplicate",
                             "detail": f"Jaccard {best[0]:.2f} with {best[1].get('id', '?')} '{best[1].get('title', '')}'"})
                continue
            bestp = max(((jaccard(tokens(key), tokens(pk)), pr) for pk, pr in post_titles),
                        key=lambda t: t[0], default=(0.0, None))
            if bestp[0] >= ovl_j:
                held.append({"title": q, "reason": "possible_overlap",
                             "detail": f"Jaccard {bestp[0]:.2f} with post '{bestp[1].get('title', '')}' ({bestp[1].get('id', '?')})"})
                continue
            cluster = it.get("cluster") if it.get("cluster") in valid_clusters else map_cluster(reg, q)
            if cluster is None:
                held.append({"title": q, "reason": "cluster_unresolved", "detail": "no cluster rule matched; a person assigns it"})
                continue
            intent, _ = map_intent(reg, q)
            material = [m for m in (it.get("material") or []) if m in materials_ok]
            if not material:
                material = list(valid_clusters[cluster].get("materials", []))
            cand = {
                "title": q,
                "canonical_key": key,
                "cluster": cluster,
                "cluster_label": valid_clusters[cluster]["label"],
                "material": material,
                "source": source,
                "volume": it.get("volume"),
                "difficulty": it.get("difficulty"),
                "cpc": it.get("cpc"),
                "intent": intent,
                "local": is_local(reg, q),
                "status_on_create": status,
            }
            if cand["volume"] is None:
                flagged.append({"title": q, "reason": "volume_unknown"})
            candidates.append(cand)
    return candidates, held, flagged


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", default="seed", help="seed | transcript | related | paa | autocomplete | gap | gsc (label only)")
    ap.add_argument("--seeds", action="append", required=True, help="topic-seeds-1 or topic-raw-1 file (repeatable)")
    ap.add_argument("--backlog", required=True, help="topic-backlog-snapshot-1 file")
    ap.add_argument("--posts", required=True, help="blog-posts-snapshot-1 file")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--out", default=None, help="default ingest/<today>/topic-candidates-<mode>.json")
    args = ap.parse_args(argv)

    try:
        reg = load_registry(args.registry)
        raws = [load_raw(p) for p in args.seeds]
        backlog = read_json(args.backlog).get("rows", [])
        posts = read_json(args.posts).get("rows", [])
    except (OSError, ValueError, KeyError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2

    candidates, held, flagged = harvest(reg, raws, backlog, posts)
    out = {
        "contract_version": CONTRACT_VERSION,
        "mode": args.mode,
        "run_at": now_local().isoformat(timespec="seconds"),
        "registry_config_version": reg["config_version"],
        "inputs": {"seeds": args.seeds, "backlog": args.backlog, "posts": args.posts},
        "summary": {"candidates": len(candidates), "held": len(held), "flagged": len(flagged),
                    "held_by_reason": {r: sum(1 for h in held if h["reason"] == r) for r in sorted({h["reason"] for h in held})}},
        "candidates": candidates,
        "held": held,
        "flagged": flagged,
    }
    out_path = Path(args.out) if args.out else REPO_ROOT / "ingest" / today() / f"topic-candidates-{args.mode}.json"
    write_json(out_path, out)
    print(f"{out_path}: {len(candidates)} candidates, {len(held)} held, {len(flagged)} flagged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
