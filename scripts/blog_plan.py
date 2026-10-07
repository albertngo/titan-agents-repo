#!/usr/bin/env python3
"""Deterministic planner for every content-engine stage (contracts/blog-plan-schema.md).

    python3 scripts/blog_plan.py --stage harvest --candidates ingest/<date>/topic-candidates-seed.json
    python3 scripts/blog_plan.py --stage rank    --scores ingest/<date>/topic-scores.json --backlog <snapshot>
    python3 scripts/blog_plan.py --stage brief   --brief ingest/<date>/blog-brief-TB-12.json --backlog <snapshot> --posts <snapshot>
    python3 scripts/blog_plan.py --stage draft   --body ingest/<date>/blog-body-BP-7.md --brief <brief> --posts <snapshot> --bp BP-7
    python3 scripts/blog_plan.py --stage publish --mdx ingest/<date>/blog-mdx/<slug>.mdx --posts <snapshot> --bp BP-7
      ... [--registry platform-settings/content-engine.json] [--date YYYY-MM-DD] [--out plans/...]
      ... [--write-approval [--approval-out plans/...]]

Reads only the files named. Holds no credentials and writes nothing to any platform.
Writes the plan under plans/<date>/ and, only under write_mode `write`, the approval
file that policy allows (--write-approval; exit 4 otherwise). blog-actions-agent
executes nothing that is not `approved` there.

Exit codes: 0 plan written, 2 missing or malformed input, 3 stage input refused
(nothing plannable), 4 approval refused (write_mode is plan_only).
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_engine_lib import (  # noqa: E402
    REPO_ROOT, action_id, clusters, label_to_slug, load_registry, now_local, read_json,
    sha1_file, slug_problem, slugify, today, word_count, write_json,
)
import blog_render  # noqa: E402

PLAN_VERSION = "blog-plan-1"
APPROVAL_VERSION = "blog-approval-1"
STAGES = ("harvest", "rank", "brief", "draft", "publish")


class Refused(Exception):
    pass


def envelope(reg, stage, scope, inputs, now):
    return {
        "contract_version": PLAN_VERSION,
        "stage": stage,
        "scope": scope,
        "run_at": now.isoformat(timespec="seconds"),
        "write_mode": reg["write_mode"]["mode"],
        "registry_config_version": reg["config_version"],
        "inputs": inputs,
        "summary": {},
        "actions": [],
        "held": [],
        "flagged": [],
        "warnings": [],
    }


def finish(plan):
    held = plan["held"]
    plan["summary"] = {
        "actions": len(plan["actions"]),
        "held": len(held),
        "held_by_reason": {r: sum(1 for h in held if h["reason"] == r) for r in sorted({h["reason"] for h in held})},
        "flagged": len(plan["flagged"]),
    }
    for i, a in enumerate(plan["actions"], 1):
        a["seq"] = i
    return plan


def _notion_action(op, type_, target_key, target, fields, expect=None, content=b"", extra=None):
    a = {
        "id": action_id("notion", op, target_key, list(fields.keys()), content),
        "seq": 0,
        "target_system": "notion",
        "type": type_,
        "op": op,
        "target": target,
        "fields": fields,
        "expect": expect or {},
        "flags": [],
    }
    if extra:
        a.update(extra)
    return a


def _rows_by_id(rows, key="id"):
    return {r.get(key): r for r in rows if r.get(key)}


# --------------------------------------------------------------------------- stages

def plan_harvest(reg, plan, candidates_file):
    cands = read_json(candidates_file)
    policy = reg["policy"]
    tb = reg["sources"]["topic_backlog"]
    props = tb["properties"]
    cap = policy["max_new_topics_per_run"]
    for h in cands.get("held", []):
        plan["held"].append(h)
    for i, c in enumerate(cands.get("candidates", [])):
        if i >= cap:
            plan["held"].append({"title": c["title"], "reason": "run_cap", "detail": f"beyond max_new_topics_per_run={cap}; next run"})
            continue
        fields = {
            props["title"]: c["title"],
            props["cluster"]: c["cluster_label"],
            props["material"]: c.get("material", []),
            props["source"]: c["source"],
            props["volume"]: c.get("volume"),
            props["difficulty"]: c.get("difficulty"),
            props["cpc"]: c.get("cpc"),
            props["intent"]: c["intent"],
            props["local"]: bool(c.get("local")),
            props["status"]: c["status_on_create"],
            props["canonical_key"]: c["canonical_key"],
        }
        a = _notion_action("create_topic", "notion_create_topic", c["canonical_key"],
                           {"data_source": tb["data_source"], "canonical_key": c["canonical_key"]}, fields,
                           expect={"canonical_key_absent": True})
        a["batch"] = i // policy["max_batch"] + 1
        for f in cands.get("flagged", []):
            if f.get("title") == c["title"]:
                a["flags"].append(f["reason"])
                plan["flagged"].append({"action_id": a["id"], "reason": f["reason"]})
        plan["actions"].append(a)
    return plan


def plan_rank(reg, plan, scores_file, backlog_file):
    scores = read_json(scores_file)
    backlog = _rows_by_id(read_json(backlog_file).get("rows", []), key="url")
    tb = reg["sources"]["topic_backlog"]
    props = tb["properties"]
    import json as _json
    for r in scores.get("ranked", []):
        if r.get("origin") != "backlog" or not r.get("url"):
            continue
        row = backlog.get(r["url"])
        if not row or row.get("status") != "Backlog":
            plan["held"].append({"title": r.get("title"), "reason": "stale_status", "detail": "not a Backlog row in the snapshot"})
            continue
        if not (0 <= r["effective"] <= 100):
            plan["held"].append({"title": r.get("title"), "reason": "no_volume_source", "detail": f"score out of range: {r['effective']}"})
            continue
        fields = {
            props["score"]: r["effective"],
            props["score_inputs"]: _json.dumps(r["inputs"], ensure_ascii=False, sort_keys=True),
            props["last_scored"]: plan["run_at"][:10],
        }
        a = _notion_action("update_topic_score", "notion_update_topic_score", r["url"],
                           {"page": r["url"], "tb_id": r.get("id")}, fields, expect={"Status": "Backlog"})
        for f in r.get("flags", []):
            a["flags"].append(f)
            plan["flagged"].append({"action_id": a["id"], "reason": f})
        plan["actions"].append(a)
    return plan


def _brief_problems(reg, brief, backlog_rows, post_rows):
    problems = []
    if brief.get("contract_version") != "blog-brief-1":
        problems.append(("stale_status", "brief is not blog-brief-1"))
    if not (brief.get("keyword") or "").strip():
        problems.append(("titan_facts_missing", "keyword is empty"))
    cq = (brief.get("core_question") or "").strip()
    if not cq.endswith("?"):
        problems.append(("h2_not_question", "core_question must be the question as typed, ending with ?"))
    h2s = [h for h in brief.get("h2s", []) if (h or "").strip()]
    if len(h2s) < 3 or any(not h.strip().endswith("?") for h in h2s):
        problems.append(("h2_not_question", "need at least 3 H2s and every one must end with ?"))
    if brief.get("cluster") not in clusters(reg):
        problems.append(("cluster_unresolved", f"cluster {brief.get('cluster')!r} is not a registry slug"))
    topic = brief.get("topic") or {}
    row = next((r for r in backlog_rows if r.get("url") == topic.get("url") or (topic.get("id") and r.get("id") == topic.get("id"))), None)
    if row is None:
        problems.append(("stale_status", "topic not in the backlog snapshot"))
    else:
        if row.get("status") != "Backlog":
            problems.append(("stale_status", f"topic Status is {row.get('status')!r}, not Backlog"))
        if row.get("blog_post"):
            problems.append(("possible_duplicate", "topic already has a Blog Post"))
    slug = brief.get("slug") or slugify(cq)
    sp = slug_problem(reg, slug)
    if sp:
        problems.append((sp, f"slug {slug!r}"))
    if any((p.get("slug") or "") == slug for p in post_rows):
        problems.append(("slug_collision", f"slug {slug!r} already on a Blog Posts row"))
    return problems, row, slug


def brief_markdown(brief):
    lines = [f"## Brief — {brief.get('core_question', '')}", ""]
    lines += [f"- **Target keyword:** {brief.get('keyword', '')}",
              f"- **Cluster:** {brief.get('cluster', '')} · **Material:** {', '.join(brief.get('material', []))} · **Intent:** {brief.get('intent', '')}",
              f"- **Angle:** {brief.get('angle', '')}",
              f"- **Slug:** {brief.get('slug', '')}", ""]
    lines += ["### Supporting questions (H2s)", ""] + [f"- {h}" for h in brief.get("h2s", [])] + [""]
    lines += ["### Titan-only facts to include", ""] + [f"- {f}" for f in brief.get("facts_used", [])] + [""]
    if brief.get("facts_missing"):
        lines += ["### Facts the writer must NOT invent (missing from titan-facts.md)", ""] + [f"- {f}" for f in brief["facts_missing"]] + [""]
    lines += ["### Direct answer (draft, 40–60 words)", "", brief.get("snippet_draft", ""), ""]
    return "\n".join(lines)


def plan_brief(reg, plan, brief_file, backlog_file, posts_file):
    brief = read_json(brief_file)
    backlog_rows = read_json(backlog_file).get("rows", [])
    post_rows = read_json(posts_file).get("rows", [])
    problems, row, slug = _brief_problems(reg, brief, backlog_rows, post_rows)
    title = brief.get("core_question", "")
    if problems:
        for reason, detail in problems:
            plan["held"].append({"title": title, "reason": reason, "detail": detail})
        return plan
    bp = reg["sources"]["blog_posts"]
    props = bp["properties"]
    spelling = reg["intent_rules"].get("blog_posts_spelling", {})
    intent_notion = spelling.get(brief.get("intent"), brief.get("intent"))
    cluster_label = clusters(reg)[brief["cluster"]]["label"]
    body = brief_markdown(brief)
    body_path = Path(brief_file).with_suffix(".md")
    body_path.write_text(body)
    fields = {
        props["title"]: title,
        props["status"]: "Briefed",
        props["topic"]: [row["url"]],
        props["topic_cluster"]: cluster_label,
        props["primary_keyword"]: brief["keyword"],
        props["search_intent"]: intent_notion,
        props["material"]: brief.get("material", []),
        props["content_type"]: brief.get("content_type", "Supporting Content"),
        props["slug"]: slug,
    }
    a = _notion_action("create_blog_post", "notion_create_blog_post", row["url"],
                       {"data_source": bp["data_source"], "topic": row["url"], "tb_id": row.get("id")},
                       fields, expect={"topic_status": "Backlog", "topic_blog_post_empty": True}, content=body.encode(),
                       extra={"body_file": str(body_path.relative_to(REPO_ROOT)) if body_path.is_relative_to(REPO_ROOT) else str(body_path),
                              "then": [{"target_system": "notion", "op": "update_topic", "target": {"page": row["url"]},
                                        "fields": {reg["sources"]["topic_backlog"]["properties"]["status"]: "Briefed"},
                                        "expect": {"Status": "Backlog"}}]})
    if brief.get("facts_missing"):
        a["flags"].append("titan_facts_missing")
        plan["flagged"].append({"action_id": a["id"], "reason": "titan_facts_missing", "detail": brief["facts_missing"]})
    if not brief.get("pillar_slug") and not reg["aeo_structure"]["pillar_rules"]["required"]:
        a["flags"].append("pillar_not_required_yet")
        plan["flagged"].append({"action_id": a["id"], "reason": "pillar_not_required_yet"})
    plan["actions"].append(a)
    return plan


def draft_problems(reg, body_text):
    """Structural checks on a body per aeo_structure. Returns (problems, parsed)."""
    aeo = reg["aeo_structure"]
    parsed = blog_render.parse_body(body_text)
    problems = []
    if parsed["h1_count"] != 1:
        problems.append(("h2_not_question", f"expected exactly one H1, found {parsed['h1_count']}"))
    sn = word_count(parsed["snippet"])
    if not (aeo["snippet_words"]["min"] <= sn <= aeo["snippet_words"]["max"]):
        problems.append(("snippet_length", f"snippet is {sn} words, need {aeo['snippet_words']['min']}–{aeo['snippet_words']['max']}"))
    if aeo["h2_must_be_questions"]:
        bad = [h for h in parsed["h2s"] if not h.strip().endswith("?")]
        if bad:
            problems.append(("h2_not_question", f"H2 not a question: {bad[0]!r}"))
    nfaq = len(parsed["faq"])
    if not (aeo["faq_count"]["min"] <= nfaq <= aeo["faq_count"]["max"]):
        problems.append(("faq_count", f"{nfaq} FAQ items, need {aeo['faq_count']['min']}–{aeo['faq_count']['max']}"))
    elif any(not q.strip().endswith("?") for q, _ in parsed["faq"]):
        problems.append(("faq_count", "every FAQ question must end with ?"))
    wc = word_count(body_text)
    if wc < aeo["min_body_words"]:
        problems.append(("body_too_short", f"{wc} words, need {aeo['min_body_words']}"))
    return problems, parsed


def plan_draft(reg, plan, body_file, brief_file, posts_file, bp_id):
    body_text = Path(body_file).read_text()
    brief = read_json(brief_file) if brief_file else {}
    post_rows = read_json(posts_file).get("rows", [])
    row = next((p for p in post_rows if p.get("id") == bp_id), None)
    title = (brief.get("core_question") or (row or {}).get("title") or bp_id)
    if row is None:
        plan["held"].append({"title": title, "reason": "stale_status", "detail": f"{bp_id} not in the posts snapshot"})
        return plan
    st = row.get("status")
    if st in ("Review", "Approved", "Published", "Posted"):
        plan["held"].append({"title": title, "reason": "body_is_a_persons", "detail": f"Status is {st}; the body is a person's now"})
        return plan
    if st not in ("Briefed", "Drafting"):
        plan["held"].append({"title": title, "reason": "stale_status", "detail": f"Status is {st!r}, need Briefed or Drafting"})
        return plan
    problems, parsed = draft_problems(reg, body_text)
    if problems:
        for reason, detail in problems:
            plan["held"].append({"title": title, "reason": reason, "detail": detail})
        return plan
    bp = reg["sources"]["blog_posts"]
    props = bp["properties"]
    slug = row.get("slug") or brief.get("slug") or slugify(parsed["h1"])
    sp = slug_problem(reg, slug)
    if sp:
        plan["held"].append({"title": title, "reason": sp, "detail": f"slug {slug!r}"})
        return plan
    content = body_text.encode()
    a1 = _notion_action("append_blog_body", "notion_append_blog_body", row["url"], {"page": row["url"], "bp_id": bp_id},
                        {"body_heading": f"## Draft {plan['run_at'][:10]}"}, expect={"Status": st}, content=content,
                        extra={"body_file": body_file, "body_sha1": sha1_file(body_file)})
    a2 = _notion_action("update_blog_post", "notion_update_blog_post", row["url"], {"page": row["url"], "bp_id": bp_id},
                        {props["status"]: "Review", props["snippet"]: parsed["snippet"], props["slug"]: slug,
                         props["primary_keyword"]: brief.get("keyword") or row.get("primary_keyword") or ""},
                        expect={"Status": st}, content=content)
    if not row.get("pillar") and not reg["aeo_structure"]["pillar_rules"]["required"]:
        a2["flags"].append("pillar_not_required_yet")
        plan["flagged"].append({"action_id": a2["id"], "reason": "pillar_not_required_yet"})
    plan["actions"] += [a1, a2]
    return plan


def plan_publish(reg, plan, mdx_file, posts_file, bp_id):
    post_rows = read_json(posts_file).get("rows", [])
    row = next((p for p in post_rows if p.get("id") == bp_id), None)
    title = (row or {}).get("title") or bp_id
    if row is None:
        plan["held"].append({"title": title, "reason": "stale_status", "detail": f"{bp_id} not in the posts snapshot"})
        return plan
    if row.get("status") != "Approved":
        plan["held"].append({"title": title, "reason": "not_approved", "detail": f"Status is {row.get('status')!r}; a person sets Approved"})
        return plan
    mdx_text = Path(mdx_file).read_text()
    problems, fm = blog_render.check(reg, mdx_text, file_name=Path(mdx_file).name)
    hard = [p for p in problems if p[0] not in reg["flagged_reasons"]]
    for reason, detail in hard:
        plan["held"].append({"title": title, "reason": reason, "detail": detail})
    if hard:
        return plan
    slug = fm["slug"]
    w = reg["website"]
    content = mdx_text.encode()
    a = {
        "id": action_id("github", "open_post_pr", slug, ["content/blog/" + slug + ".mdx"], content),
        "seq": 0,
        "target_system": "github",
        "type": "website_open_post_pr",
        "op": "open_post_pr",
        "target": {"repo": w["repo"], "branch": w["branch_template"].format(slug=slug), "base": w["base_branch"]},
        "files": [{"path": f"{w['content_dir']}/{slug}.mdx", "sha1": sha1_file(mdx_file), "source": mdx_file}],
        "pr": {"title": f"blog: {fm['title']}", "body": f"{bp_id} · cluster {fm['cluster']} · {fm['contentType']}\n\nRendered by scripts/blog_render.py from the Notion Blog Posts row; approved in Notion (Status = Approved). Merging publishes."},
        "expect": {"Status": "Approved", "re_read_at_write": True},
        "then": [{"target_system": "notion", "op": "update_blog_post", "target": {"page": row["url"], "bp_id": bp_id},
                  "fields": {reg["sources"]["blog_posts"]["properties"]["pr_url"]: "<from result>"}}],
        "flags": [],
    }
    for reason, detail in problems:
        if reason in reg["flagged_reasons"]:
            a["flags"].append(reason)
            plan["flagged"].append({"action_id": a["id"], "reason": reason, "detail": detail})
    plan["actions"].append(a)
    return plan


# --------------------------------------------------------------------------- approval

def policy_approve(reg, plan, now):
    """Decisions policy may make. Raises Refused when write_mode is not write."""
    if reg["write_mode"]["mode"] != "write":
        raise Refused(f"write_mode is {reg['write_mode']['mode']!r}; no approval file is written")
    allowed = set(reg["policy"]["auto_approve_ops"])
    held_titles = {h.get("title") for h in plan["held"]}
    decisions = []
    for a in plan["actions"]:
        op = a["op"]
        if op == "retire_topic":
            op = f"retire_topic:{a['fields'].get('Retired reason', '')}"
        if op not in allowed:
            continue
        if a["fields"].get("Status") == "Approved":
            continue
        if a.get("target", {}).get("title") in held_titles:
            continue
        decisions.append({"id": a["id"], "status": "approved", "at": now.isoformat(timespec="seconds")})
    return {
        "contract_version": APPROVAL_VERSION,
        "stage": plan["stage"],
        "scope": plan["scope"],
        "plan": plan.get("_path"),
        "approved_by": reg["policy"]["approved_by"],
        "decisions": decisions,
    }


# --------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, choices=STAGES)
    ap.add_argument("--registry", default=None)
    ap.add_argument("--date", default=None, help="plan folder date, default today (Toronto)")
    ap.add_argument("--candidates")
    ap.add_argument("--scores")
    ap.add_argument("--backlog")
    ap.add_argument("--posts")
    ap.add_argument("--brief")
    ap.add_argument("--body")
    ap.add_argument("--mdx")
    ap.add_argument("--bp", help="Blog Posts id, e.g. BP-7")
    ap.add_argument("--out")
    ap.add_argument("--write-approval", action="store_true")
    ap.add_argument("--approval-out")
    args = ap.parse_args(argv)

    try:
        reg = load_registry(args.registry)
    except (OSError, ValueError) as exc:
        print(f"registry error: {exc}", file=sys.stderr)
        return 2
    now = now_local()
    date = args.date or today()
    need = {
        "harvest": ["candidates"], "rank": ["scores", "backlog"], "brief": ["brief", "backlog", "posts"],
        "draft": ["body", "posts", "bp"], "publish": ["mdx", "posts", "bp"],
    }[args.stage]
    missing = [n for n in need if not getattr(args, n)]
    if missing:
        print(f"stage {args.stage} needs --{' --'.join(missing)}", file=sys.stderr)
        return 2
    for n in need:
        v = getattr(args, n)
        if n != "bp" and not Path(v).exists():
            print(f"missing input: {v}", file=sys.stderr)
            return 2

    try:
        if args.stage == "harvest":
            scope = Path(args.candidates).stem.replace("topic-candidates-", "") or "seed"
            plan = plan_harvest(reg, envelope(reg, "harvest", scope, [{"file": args.candidates}], now), args.candidates)
        elif args.stage == "rank":
            plan = plan_rank(reg, envelope(reg, "rank", "all", [{"file": args.scores}, {"file": args.backlog}], now), args.scores, args.backlog)
        elif args.stage == "brief":
            brief = read_json(args.brief)
            scope = (brief.get("topic") or {}).get("id") or Path(args.brief).stem.replace("blog-brief-", "")
            plan = plan_brief(reg, envelope(reg, "brief", scope, [{"file": args.brief, "sha1": sha1_file(args.brief)}, {"file": args.backlog}, {"file": args.posts}], now),
                              args.brief, args.backlog, args.posts)
        elif args.stage == "draft":
            inputs = [{"file": args.body, "sha1": sha1_file(args.body)}, {"file": args.posts}]
            if args.brief:
                inputs.append({"file": args.brief})
            plan = plan_draft(reg, envelope(reg, "draft", args.bp, inputs, now), args.body, args.brief, args.posts, args.bp)
        else:
            plan = plan_publish(reg, envelope(reg, "publish", args.bp, [{"file": args.mdx, "sha1": sha1_file(args.mdx)}, {"file": args.posts}], now),
                                args.mdx, args.posts, args.bp)
    except (OSError, ValueError, KeyError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2

    finish(plan)
    out_path = Path(args.out) if args.out else REPO_ROOT / "plans" / date / f"blog-plan-{args.stage}-{plan['scope']}.json"
    plan["_path"] = str(out_path.relative_to(REPO_ROOT)) if out_path.is_absolute() and out_path.is_relative_to(REPO_ROOT) else str(out_path)
    write_json(out_path, plan)
    print(f"{out_path}: {plan['summary']['actions']} actions, {plan['summary']['held']} held, {plan['summary']['flagged']} flagged (write_mode={plan['write_mode']})")
    for h in plan["held"]:
        print(f"  held [{h['reason']}] {h.get('title', '')}: {h.get('detail', '')}")

    if args.write_approval:
        try:
            approval = policy_approve(reg, plan, now)
        except Refused as exc:
            print(f"approval refused: {exc}", file=sys.stderr)
            return 4
        ap_path = Path(args.approval_out) if args.approval_out else out_path.with_name(out_path.name.replace("blog-plan-", "blog-approval-"))
        write_json(ap_path, approval)
        print(f"{ap_path}: {len(approval['decisions'])} approved by {approval['approved_by']}")
    if not plan["actions"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
