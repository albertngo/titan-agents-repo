#!/usr/bin/env python3
"""Render a Blog Posts row + its Markdown body into the site's post file (blog-mdx-1).

    python3 scripts/blog_render.py --row ingest/<date>/blog-row-BP-7.json --body ingest/<date>/blog-body-BP-7.md \
        [--date YYYY-MM-DD] [--registry ...] [--out ingest/<date>/blog-mdx/<slug>.mdx]
    python3 scripts/blog_render.py --check ingest/<date>/blog-mdx/<slug>.mdx [--registry ...]

Reads only the files named; holds no credentials; writes nothing to any platform.

--row is a small JSON the command assembles from the Notion row and the brief:
  {"bp_id": "BP-7", "page_id": "...", "title": "...", "slug": "...", "keyword": "...",
   "intent": "Informational"|"Commericial"|..., "cluster": "<slug or Notion label>",
   "material": [...], "content_type": "Supporting Content"|"Pillar Page",
   "pillar_slug": "..."|null, "siblings": [...], "video_url": null, "description": "..."?,
   "publish_date": "YYYY-MM-DD"?, "updated_date": null, "legacy": null}

The body is the Markdown the draft stage validated: one H1, the snippet paragraph,
question H2s, a `## FAQ` section of `### question` + answer, optional `## Sources`.
The H1, the snippet and the FAQ leave the body and become frontmatter fields; the site
renders them in its own order (contracts/blog-mdx-schema.md).

Exit codes: 0 ok, 1 check found problems, 2 missing input.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_engine_lib import (  # noqa: E402
    REPO_ROOT, clusters, label_to_slug, load_registry, read_json, slug_problem, slugify, today,
    word_count, write_json,
)

SCHEMA = "blog-mdx-1"
KEYS = ["schema", "blogId", "notionPageId", "title", "slug", "description", "snippet", "keyword", "intent",
        "cluster", "material", "contentType", "pillar", "siblings", "publishDate", "updatedDate", "videoUrl", "faq", "legacy"]
INTENTS = ["Informational", "Commercial", "Navigation", "Transaction"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
YT_RE = re.compile(r"^https://(www\.)?(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)[A-Za-z0-9_-]{6,}")


def parse_body(text):
    """Split the body into h1, snippet, sections, faq, rest. Pure string work."""
    lines = text.splitlines()
    h1, h1_count = "", 0
    i = 0
    # H1
    for idx, ln in enumerate(lines):
        if ln.startswith("# "):
            h1_count += 1
            if not h1:
                h1 = ln[2:].strip()
                i = idx + 1
    # snippet = first non-empty paragraph after the H1
    while i < len(lines) and not lines[i].strip():
        i += 1
    snippet_lines = []
    while i < len(lines) and lines[i].strip() and not lines[i].startswith("#"):
        snippet_lines.append(lines[i].strip())
        i += 1
    snippet = " ".join(snippet_lines)
    body_lines = lines[i:]
    # sections
    sections, cur, cur_title = [], [], None
    for ln in body_lines:
        if ln.startswith("## "):
            if cur_title is not None:
                sections.append((cur_title, cur))
            cur_title, cur = ln[3:].strip(), []
        else:
            cur.append(ln)
    if cur_title is not None:
        sections.append((cur_title, cur))
    faq, kept, h2s = [], [], []
    for title, body in sections:
        t = title.strip().rstrip(":").lower()
        if t in ("faq", "faqs", "frequently asked questions"):
            q, ans = None, []
            for ln in body:
                if ln.startswith("### "):
                    if q:
                        faq.append((q, " ".join(a.strip() for a in ans if a.strip())))
                    q, ans = ln[4:].strip(), []
                elif q is not None:
                    ans.append(ln)
            if q:
                faq.append((q, " ".join(a.strip() for a in ans if a.strip())))
            continue
        if t in ("sources", "references"):
            continue
        h2s.append(title)
        kept.append("## " + title)
        kept += body
    body_out = "\n".join(kept).strip() + "\n"
    return {"h1": h1, "h1_count": h1_count, "snippet": snippet, "h2s": h2s, "faq": faq, "body": body_out}


def _description(row, snippet):
    d = (row.get("description") or "").strip()
    if not d:
        first = re.split(r"(?<=[.!?])\s", snippet.strip(), maxsplit=1)[0]
        d = first
    if len(d) > 160:
        d = d[:157].rstrip() + "..."
    return d


def render(reg, row, body_text, publish_date=None):
    parsed = parse_body(body_text)
    l2s = label_to_slug(reg)
    cluster = row.get("cluster")
    cluster = cluster if cluster in clusters(reg) else l2s.get(cluster)
    spelling = {v: k for k, v in reg["intent_rules"].get("blog_posts_spelling", {}).items()}
    intent = spelling.get(row.get("intent"), row.get("intent"))
    slug = row.get("slug") or slugify(parsed["h1"])
    fm = {
        "schema": SCHEMA,
        "blogId": row.get("bp_id"),
        "notionPageId": row.get("page_id"),
        "title": parsed["h1"] or row.get("title", ""),
        "slug": slug,
        "description": _description(row, parsed["snippet"]),
        "snippet": parsed["snippet"],
        "keyword": row.get("keyword", ""),
        "intent": intent,
        "cluster": cluster,
        "material": row.get("material", []),
        "contentType": row.get("content_type", "Supporting Content"),
        "pillar": row.get("pillar_slug"),
        "siblings": row.get("siblings", []),
        "publishDate": publish_date or row.get("publish_date") or today(),
        "updatedDate": row.get("updated_date"),
        "videoUrl": row.get("video_url"),
        "faq": [{"q": q, "a": a} for q, a in parsed["faq"]],
        "legacy": row.get("legacy"),
    }
    front = "\n".join(f"{k}: {json.dumps(fm[k], ensure_ascii=False)}" for k in KEYS)
    return fm, f"---\n{front}\n---\n\n{parsed['body']}"


def parse_frontmatter(text):
    if not text.startswith("---\n"):
        raise ValueError("no frontmatter")
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("unterminated frontmatter")
    fm = {}
    for ln in text[4:end].splitlines():
        if not ln.strip():
            continue
        k, _, v = ln.partition(":")
        fm[k.strip()] = json.loads(v.strip())
    body = text[end + 4:].lstrip("\n")
    return fm, body


def check(reg, mdx_text, file_name=None):
    """Returns (problems, frontmatter). problems = [(reason, detail)], flagged reasons included."""
    aeo, w = reg["aeo_structure"], reg["website"]
    try:
        fm, body = parse_frontmatter(mdx_text)
    except (ValueError, json.JSONDecodeError) as exc:
        return [("slug_invalid", f"frontmatter unreadable: {exc}")], {}
    p = []
    missing = [k for k in KEYS if k not in fm]
    if missing:
        p.append(("slug_invalid", f"frontmatter missing keys: {missing}"))
        return p, fm
    if fm["schema"] != SCHEMA:
        p.append(("slug_invalid", f"schema {fm['schema']!r} != {SCHEMA}"))
    if not re.match(r"^BP-\d+$", str(fm["blogId"] or "")):
        p.append(("stale_status", f"blogId {fm['blogId']!r} is not BP-<n>"))
    if not fm["title"] or len(fm["title"]) > 110:
        p.append(("h2_not_question", "title empty or over 110 chars"))
    sp = slug_problem(reg, fm["slug"])
    if sp:
        p.append((sp, f"slug {fm['slug']!r}"))
    if file_name and file_name != f"{fm['slug']}.mdx":
        p.append(("slug_invalid", f"file name {file_name} != slug {fm['slug']}.mdx"))
    if len(fm["description"] or "") > 160 or not fm["description"]:
        p.append(("snippet_length", "description empty or over 160 chars"))
    sn = word_count(fm["snippet"])
    if not (aeo["snippet_words"]["min"] <= sn <= aeo["snippet_words"]["max"]):
        p.append(("snippet_length", f"snippet {sn} words"))
    if not fm["keyword"]:
        p.append(("titan_facts_missing", "keyword empty"))
    if fm["intent"] not in INTENTS:
        p.append(("stale_status", f"intent {fm['intent']!r}"))
    if fm["cluster"] not in clusters(reg):
        p.append(("cluster_unresolved", f"cluster {fm['cluster']!r}"))
    mats = set(reg["sources"]["blog_posts"]["material_values"])
    if not isinstance(fm["material"], list) or not set(fm["material"]) <= mats:
        p.append(("stale_status", f"material {fm['material']!r}"))
    if fm["contentType"] not in ("Pillar Page", "Supporting Content"):
        p.append(("stale_status", f"contentType {fm['contentType']!r}"))
    pr = aeo["pillar_rules"]
    if fm["contentType"] == "Pillar Page":
        if fm["pillar"] is not None:
            p.append(("pillar_missing", "a Pillar Page must have pillar: null"))
    elif fm["pillar"] is None:
        p.append(("pillar_missing" if pr["required"] else "pillar_not_required_yet", "spoke has no pillar"))
    elif slug_problem(reg, fm["pillar"]):
        p.append(("pillar_missing", f"pillar slug {fm['pillar']!r} invalid"))
    sib = fm["siblings"] if isinstance(fm["siblings"], list) else None
    if sib is None or len(sib) > pr["siblings_max"] or (pr["required"] and fm["contentType"] != "Pillar Page" and len(sib) < pr["siblings_min"]):
        p.append(("pillar_missing", f"siblings {fm['siblings']!r}"))
    if not DATE_RE.match(str(fm["publishDate"] or "")):
        p.append(("stale_status", f"publishDate {fm['publishDate']!r}"))
    if fm["updatedDate"] is not None and not DATE_RE.match(str(fm["updatedDate"])):
        p.append(("stale_status", f"updatedDate {fm['updatedDate']!r}"))
    if fm["videoUrl"] is not None and not YT_RE.match(str(fm["videoUrl"])):
        p.append(("stale_status", f"videoUrl is not a YouTube URL: {fm['videoUrl']!r}"))
    faq = fm["faq"] if isinstance(fm["faq"], list) else []
    if not (aeo["faq_count"]["min"] <= len(faq) <= aeo["faq_count"]["max"]):
        p.append(("faq_count", f"{len(faq)} FAQ items"))
    elif any(not isinstance(f, dict) or not str(f.get("q", "")).strip().endswith("?") or not str(f.get("a", "")).strip() for f in faq):
        p.append(("faq_count", "every FAQ item needs q ending with ? and a non-empty a"))
    if fm["legacy"] is not None and not (isinstance(fm["legacy"], dict) and "wpId" in fm["legacy"]):
        p.append(("stale_status", "legacy must be null or {wpId, importedAt}"))
    if re.search(r"^# ", body, re.M):
        p.append(("h2_not_question", "body still contains an H1"))
    for m in re.finditer(r"^## (.+)$", body, re.M):
        if not m.group(1).strip().endswith("?"):
            p.append(("h2_not_question", f"body H2 not a question: {m.group(1)!r}"))
    if aeo["h2_must_be_questions"] and word_count(body) < aeo["min_body_words"] - sn:
        p.append(("body_too_short", f"body {word_count(body)} words"))
    return p, fm


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--row")
    ap.add_argument("--body")
    ap.add_argument("--date")
    ap.add_argument("--registry")
    ap.add_argument("--out")
    ap.add_argument("--check", help="an existing .mdx to validate")
    args = ap.parse_args(argv)
    try:
        reg = load_registry(args.registry)
    except (OSError, ValueError) as exc:
        print(f"registry error: {exc}", file=sys.stderr)
        return 2
    if args.check:
        path = Path(args.check)
        if not path.exists():
            print(f"missing: {path}", file=sys.stderr)
            return 2
        problems, fm = check(reg, path.read_text(), file_name=path.name)
        hard = [pr for pr in problems if pr[0] not in reg["flagged_reasons"]]
        for reason, detail in problems:
            kind = "flag" if reason in reg["flagged_reasons"] else "FAIL"
            print(f"  {kind} [{reason}] {detail}")
        print(f"{path}: {'ok' if not hard else str(len(hard)) + ' problem(s)'}" + (f" ({len(problems) - len(hard)} flagged)" if len(problems) - len(hard) else ""))
        return 1 if hard else 0
    if not (args.row and args.body):
        print("need --row and --body, or --check", file=sys.stderr)
        return 2
    try:
        row = read_json(args.row)
        body = Path(args.body).read_text()
    except OSError as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2
    fm, text = render(reg, row, body, args.date)
    out = Path(args.out) if args.out else REPO_ROOT / "ingest" / today() / "blog-mdx" / f"{fm['slug']}.mdx"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    problems, _ = check(reg, text, file_name=out.name)
    hard = [pr for pr in problems if pr[0] not in reg["flagged_reasons"]]
    for reason, detail in problems:
        print(f"  {'flag' if reason in reg['flagged_reasons'] else 'FAIL'} [{reason}] {detail}")
    print(f"{out}: {'ok' if not hard else str(len(hard)) + ' problem(s)'}")
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
