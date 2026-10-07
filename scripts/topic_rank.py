#!/usr/bin/env python3
"""Score the Topic Backlog (deterministic, v1 weights from the registry).

    python3 scripts/topic_rank.py --backlog ingest/<date>/topic-backlog-snapshot.json \
        --posts ingest/<date>/blog-posts-snapshot.json \
        [--candidates ingest/<date>/topic-candidates-seed.json] \
        [--registry platform-settings/content-engine.json] [--out ingest/<date>/topic-scores.json] [--now ISO]

Reads only the files named. Holds no credentials, writes nothing to any platform.

The formula (methods/content-engine.md, Scoring; accepted by Albert 2026-10-07):

    V  = min(1, log10(1+volume) / log10(1+volume_cap))        volume null -> volume_unknown, flagged
    D  = 1 - clamp(difficulty/100, 0, 1)                       difficulty null -> difficulty_unknown
    L  = min(1, local_prior[cluster] + local_explicit_bonus * has_local_token)
    C  = (1-r) * commercial_prior[cluster] + r * perf[cluster]   perf absent -> C = prior
         r = ramp.max * min(1, wins_attributed / ramp.full_at_wins)
    I  = intent score (registry intent_rules)
    score     = 100 * (w_v V + w_d D + w_l L + w_c C + w_i I)
    diversity = clamp(1 + coverage_bonus*[published[c]==0] - penalty_per_open*open[c], floor, 1+coverage_bonus)
         open[c] = backlog rows in c with Status in {Briefed, Drafting}
                 + Blog Posts in c with Status in {Review, Approved}
                 + Blog Posts in c Published within recency_window_days
    effective = round(min(100, score * diversity), decimals)
    order     = (-effective, -volume_or_0, canonical_key)

Only rows with Status == Backlog are scored (a briefed topic never moves). With
--candidates, not-yet-created candidates are scored too (status_on_create == Backlog)
so a harvest report can show where they would land; they carry no url.

Exit codes: 0 ok, 2 missing or malformed input.
"""

import argparse
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_engine_lib import (  # noqa: E402
    REPO_ROOT, canonical_key, clusters, is_local, label_to_slug, load_registry, map_intent,
    now_local, read_json, today, write_json,
)

CONTRACT_VERSION = "topic-scores-1"
OPEN_BACKLOG = {"Briefed", "Drafting"}
OPEN_POSTS = {"Review", "Approved"}
PUBLISHED = {"Published", "Posted"}


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _cluster_slug(reg, value):
    """Accepts a slug or a Notion label."""
    cl = clusters(reg)
    if value in cl:
        return value
    return label_to_slug(reg).get(value)


def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def cluster_counts(reg, backlog_rows, post_rows, now):
    """open[c], published[c] (ever), published_total, per the formula."""
    window = timedelta(days=reg["scoring"]["diversity"]["recency_window_days"])
    today_d = now.date()
    open_, published = {}, {}
    for r in backlog_rows:
        c = _cluster_slug(reg, r.get("cluster"))
        if c and r.get("status") in OPEN_BACKLOG:
            open_[c] = open_.get(c, 0) + 1
    for p in post_rows:
        c = _cluster_slug(reg, p.get("topic_cluster"))
        if not c:
            continue
        st = p.get("status")
        if st in OPEN_POSTS:
            open_[c] = open_.get(c, 0) + 1
        elif st in PUBLISHED:
            published[c] = published.get(c, 0) + 1
            d = _parse_date(p.get("publish_date"))
            if d and today_d - d <= window:
                open_[c] = open_.get(c, 0) + 1
    return open_, published


def score_row(reg, row, open_, published):
    s = reg["scoring"]
    w = s["weights"]
    cl = clusters(reg)
    c = _cluster_slug(reg, row.get("cluster"))
    if c is None:
        return None, "cluster_unresolved"
    flags = []
    vol = row.get("volume")
    if vol is None:
        V = s["volume_unknown"]
        flags.append("volume_unknown")
    else:
        V = min(1.0, math.log10(1 + float(vol)) / math.log10(1 + s["volume_cap"]))
    diff = row.get("difficulty")
    D = s["difficulty_unknown"] if diff is None else 1.0 - clamp(float(diff) / 100.0, 0.0, 1.0)
    title = row.get("title", "")
    local_token = bool(row.get("local")) or is_local(reg, title)
    L = min(1.0, cl[c]["local_prior"] + (s["local_explicit_bonus"] if local_token else 0.0))
    perf_block = reg.get("cluster_performance", {})
    perf = (perf_block.get("values") or {}).get(c)
    wins = perf_block.get("wins_attributed") or 0
    r = s["ramp"]["max"] * min(1.0, wins / float(s["ramp"]["full_at_wins"])) if perf is not None else 0.0
    C = (1 - r) * cl[c]["commercial_prior"] + r * (perf if perf is not None else 0.0)
    intent_label, I = map_intent(reg, title)
    if row.get("intent") and row["intent"] != intent_label:
        # the row's stored intent wins when a person set it; score follows the registry rule for it
        for rule in reg["intent_rules"]["rules"]:
            if rule["intent"] == row["intent"]:
                I = float(rule["score"])
                intent_label = row["intent"]
                break
    score = 100.0 * (w["volume"] * V + w["difficulty"] * D + w["local"] * L + w["cluster"] * C + w["intent"] * I)
    dv = s["diversity"]
    div = 1.0 + (dv["coverage_bonus"] if published.get(c, 0) == 0 else 0.0) - dv["penalty_per_open"] * open_.get(c, 0)
    div = clamp(div, dv["floor"], 1.0 + dv["coverage_bonus"])
    effective = round(min(100.0, score * div), s["decimals"])
    inputs = {
        "V": round(V, 4), "D": round(D, 4), "L": round(L, 4), "C": round(C, 4), "I": I, "r": round(r, 4),
        "perf": perf, "open": open_.get(c, 0), "published": published.get(c, 0),
        "diversity": round(div, 4), "score": round(score, 2), "effective": effective,
        "intent": intent_label, "cluster": c, "registry_config_version": reg["config_version"], "flags": flags,
    }
    return {"effective": effective, "score": round(score, 2), "inputs": inputs, "flags": flags, "cluster": c}, None


def rank(reg, backlog_rows, post_rows, candidates=None, now=None):
    now = now or now_local()
    open_, published = cluster_counts(reg, backlog_rows, post_rows, now)
    ranked, skipped = [], []
    pool = [dict(r, _origin="backlog") for r in backlog_rows if r.get("status") == "Backlog"]
    for c in candidates or []:
        if c.get("status_on_create", "Backlog") == "Backlog":
            pool.append({"title": c["title"], "cluster": c["cluster"], "volume": c.get("volume"),
                         "difficulty": c.get("difficulty"), "intent": c.get("intent"), "local": c.get("local"),
                         "canonical_key": c.get("canonical_key"), "_origin": "candidate"})
    for row in pool:
        result, why = score_row(reg, row, open_, published)
        if result is None:
            skipped.append({"title": row.get("title"), "reason": why})
            continue
        ranked.append({
            "url": row.get("url"), "id": row.get("id"), "title": row.get("title"),
            "canonical_key": row.get("canonical_key") or canonical_key(row.get("title", "")),
            "origin": row["_origin"], "cluster": result["cluster"], "volume": row.get("volume"),
            "score": result["score"], "effective": result["effective"], "inputs": result["inputs"], "flags": result["flags"],
        })
    ranked.sort(key=lambda r: (-r["effective"], -(r["volume"] or 0), r["canonical_key"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return ranked, skipped, {"open": open_, "published": published}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backlog", required=True)
    ap.add_argument("--posts", required=True)
    ap.add_argument("--candidates", default=None)
    ap.add_argument("--registry", default=None)
    ap.add_argument("--out", default=None, help="default ingest/<today>/topic-scores.json")
    ap.add_argument("--now", default=None, help="local ISO datetime (tests)")
    args = ap.parse_args(argv)
    try:
        reg = load_registry(args.registry)
        backlog = read_json(args.backlog).get("rows", [])
        posts = read_json(args.posts).get("rows", [])
        cands = read_json(args.candidates).get("candidates", []) if args.candidates else None
    except (OSError, ValueError, KeyError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2
    now = datetime.fromisoformat(args.now) if args.now else now_local()
    ranked, skipped, counts = rank(reg, backlog, posts, cands, now)
    out = {
        "contract_version": CONTRACT_VERSION,
        "run_at": now.isoformat(timespec="seconds"),
        "registry_config_version": reg["config_version"],
        "weights": reg["scoring"]["weights"],
        "counts": counts,
        "summary": {"ranked": len(ranked), "skipped": len(skipped), "backlog_rows": sum(1 for r in ranked if r["origin"] == "backlog")},
        "ranked": ranked,
        "skipped": skipped,
    }
    out_path = Path(args.out) if args.out else REPO_ROOT / "ingest" / today() / "topic-scores.json"
    write_json(out_path, out)
    print(f"{out_path}: {len(ranked)} ranked, {len(skipped)} skipped")
    for r in ranked[:10]:
        print(f"  {r['rank']:>2}. {r['effective']:>5}  {r['cluster']:<22} {r['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
