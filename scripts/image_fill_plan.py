#!/usr/bin/env python3
"""Plan /image-fill: which images go into which blank Airtable image field. READ ONLY.

Inputs (all files; no network):
  --snapshot       the supplier's Airtable records (list_records_for_table output)
  --pages          ingest/<date>/supplier-pages-<scope>.json (scripts/supplier_site_pull.py)
  --judgements     ingest/<date>/image-judgements-<scope>.json (the session model: each
                   image's kind and problems, and a verdict on every ambiguous match)
  --product-pages  optional ingest/<date>/product-page-index-<scope>.json: search-index
                   results for the manufacturer's own pages (title + url), matched to
                   records by title with the same rules as image pages

Two passes, same script:
  --prepare  writes ingest/<date>/image-todo-<scope>.json: the images the model must
             judge and the ambiguous records it must decide. No plan.
  (default)  writes plans/<date>/image-plan-<scope>.json, the contact sheet
             (image-contact-<scope>.html) and the held CSV (image-troubled-<scope>.csv).
  --write-approval  also writes plans/<date>/image-approval-<scope>.json by policy —
             refused while platform-settings/supplier-sites.json write_mode is plan_only.

Rules (registry `targets`, `image_rules`, `policy`; method: methods/image-fill.md):
  - BLANK ONLY: a target field that holds anything is never replaced or appended to.
  - The model's judged kind decides the field; swatches need a long edge of at least
    min_swatch_long_edge_px; watermarked and colour-mismatched images are dropped.
  - Dedupe by content hash; largest first; per-field caps.
  - `Supplier product page` = the manufacturer's own page when the product-page index
    matches the record at tier exact, else the page the images came from.

Writes nothing to any platform; the approval file is what airtable-actions-agent reads.
"""

import argparse
import csv
import hashlib
import html
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import image_match  # noqa: E402
from supplier_site_pull import load_snapshot  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "platform-settings" / "supplier-sites.json"
TZ = ZoneInfo("America/Toronto")
PLAN_VERSION = "image-plan-1"
APPROVAL_VERSION = "image-approval-1"
TODO_VERSION = "image-todo-1"
JUDGEMENTS_VERSION = "image-judgements-1"
TROUBLED_COLUMNS = ["sku", "product_name", "reason", "detail", "candidate_pages", "airtable_record"]


def now():
    return datetime.now(TZ)


def load_json(path):
    return json.loads(Path(path).read_text()) if path else None


def is_blank(value):
    return value in (None, "", [])


def action_id(sku, fields):
    return "img-" + hashlib.sha1(f"{sku}|{json.dumps(fields, sort_keys=True)}".encode()).hexdigest()[:12]


def page_index(pages_file):
    return {p["url"]: p for p in pages_file.get("pages", [])}


LAYING = ("herringbone", "chevron")


def record_laying(rec):
    """`herringbone`, `chevron` or `plank`, from the record's name and collection."""
    text = image_match.norm(f"{rec.get('Product name') or ''} {rec.get('Collection') or ''}")
    words = set(text.split())
    if "herringbone" in words or "hb" in words:
        return "herringbone"
    if "chevron" in words or "chev" in words:
        return "chevron"
    return "plank"


def usable_images(page, judgements, rules, laying=None):
    """[(target, image)] for one page, after the rules; plus problems Counter.

    `laying` is the record's pattern: an image the model saw laid in a different pattern
    is dropped (2026-09-29: The Floor Box put a herringbone room photo on a plank listing)."""
    problems = Counter()
    out = []
    seen = set()
    for img in page.get("images", []):
        if img.get("status") != "downloaded" or not img.get("sha1"):
            if img.get("status") in ("host_blocked", "challenged"):
                problems["host_blocked"] += 1
            continue
        if img["sha1"] in seen:
            continue
        seen.add(img["sha1"])
        j = (judgements or {}).get("images", {}).get(img["sha1"])
        if not j:
            problems["not_judged"] += 1
            continue
        if any(j.get(flag) for flag in ("watermarked",)) or j.get("colour_matches_page") is False:
            problems["excluded"] += 1
            continue
        if laying and j.get("laying") and j["laying"] != laying:
            problems["pattern_mismatch"] += 1
            continue
        target = rules["kind_to_target"].get(j.get("kind"))
        if not target:
            continue
        long_edge = max(img.get("width") or 0, img.get("height") or 0)
        if long_edge and long_edge < rules["min_any_long_edge_px"]:
            problems["too_small"] += 1
            continue
        if target == "swatch" and long_edge < rules["min_swatch_long_edge_px"]:
            problems["low_res_swatch"] += 1
            continue
        out.append((target, {**img, "kind": j["kind"], "long_edge": long_edge}))
    out.sort(key=lambda ti: -ti[1]["long_edge"])
    return out, problems


def photo_set(page):
    return frozenset(i["sha1"] for i in page.get("images", []) if i.get("sha1"))


def choose_page(rid, m, judgements, pages=None):
    """(page_url or None, tier, held_reason or None).

    A tie between listings that carry byte-identical photos is not a real choice (a site
    listing the same product twice, e.g. per box size): it resolves to the first, tier
    `exact`, without asking the model."""
    if m["tier"] == "exact":
        return m["candidates"][0]["url"], "exact", None
    if m["tier"] == "none":
        return None, "none", "no_match"
    if pages is not None:
        sets = {photo_set(pages[c["url"]]) for c in m["candidates"] if c["url"] in pages}
        if len(sets) == 1 and next(iter(sets)):
            return m["candidates"][0]["url"], "exact", None
    verdict = (judgements or {}).get("matches", {}).get(rid)
    if not verdict:
        return None, "ambiguous", "ambiguous_match"
    chosen = verdict.get("page")
    if chosen is None:
        return None, "ambiguous", "model_rejected"
    if chosen not in {c["url"] for c in m["candidates"]}:
        return None, "ambiguous", "ambiguous_match"
    return chosen, "model_confirmed", None


def filename_for(sku, target, n, url):
    ext = Path(url.split("?")[0]).suffix.lower()
    ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".heic") else ".jpg"
    return f"{sku}-{target}-{n}{ext}"


def build(records, pages_file, judgements, product_pages, cfg, supplier, scope):
    sup = cfg["suppliers"][supplier]
    targets, rules = cfg["targets"], cfg["image_rules"]
    pages = page_index(pages_file)
    matches = image_match.match_records(records, list(pages.values()), sup, cfg["matching"])
    pp_matches = {}
    if product_pages and (sup.get("product_pages") or {}).get("enabled", True):
        pp = [{"url": r["url"], "title": r.get("title", "")} for r in product_pages.get("results", [])]
        rule = sup.get("product_pages") or {}
        hosts = set(rule.get("hosts") or [])
        seen = set()
        for r in pp:
            r["url"] = r["url"].split("?")[0]
        pp = [r for r in pp if (not hosts or urlsplit(r["url"]).netloc in hosts)
              and not (r["url"] in seen or seen.add(r["url"]))]
        # One match per URL form, most preferred first: a record takes the first form that
        # matches it at tier exact (the current site before its older URL generations).
        for prefix in rule.get("path_prefixes") or ["/"]:
            tier_pages = [r for r in pp if urlsplit(r["url"]).path.startswith(prefix)]
            for rid, m in image_match.match_records(records, tier_pages, sup, cfg["matching"]).items():
                if m["tier"] == "exact" and rid not in pp_matches:
                    pp_matches[rid] = m
    actions, held, skipped = [], [], Counter()
    for rec in sorted(records, key=lambda r: r.get("SKU") or ""):
        rid, sku = rec["id"], rec.get("SKU")
        blank = [t for t in ("swatch", "room", "detail", "product_page")
                 if is_blank(rec.get(targets[t]["name"]))]
        if not any(t in blank for t in ("swatch", "room", "detail")):
            skipped["all_targets_filled"] += 1
            continue
        m = matches[rid]
        page_url, tier, why = choose_page(rid, m, judgements, pages)
        base = {"sku": sku, "record_id": rid, "product_name": rec.get("Product name") or "",
                "candidate_pages": [c["url"] for c in m["candidates"]]}
        if why:
            held.append({**base, "reason": why, "detail": f"colour '{m['colour']}'; vetoes {m['vetoes']}"})
            continue
        picked, problems = usable_images(pages[page_url], judgements, rules, record_laying(rec))
        fields, images = {}, []
        for target in ("swatch", "room", "detail"):
            if target not in blank:
                continue
            chosen = [img for t, img in picked if t == target][: targets[target]["cap"]]
            if chosen:
                fields[targets[target]["name"]] = [
                    {"url": img["url"], "filename": filename_for(sku, target, i + 1, img["url"])}
                    for i, img in enumerate(chosen)]
                images += [{"target": target, "url": img["url"], "sha1": img["sha1"],
                            "width": img.get("width"), "height": img.get("height")} for img in chosen]
        if not fields:
            reason = ("host_blocked" if problems.get("host_blocked") else
                      "not_judged" if problems.get("not_judged") else
                      "low_res_swatch" if problems.get("low_res_swatch") else "no_usable_image")
            held.append({**base, "reason": reason, "detail": f"page {page_url}; {dict(problems)}"})
            continue
        product_page, pp_source = page_url, "image_page"
        ppm = pp_matches.get(rid)
        if ppm:
            product_page, pp_source = ppm["candidates"][0]["url"], "manufacturer"
        if "product_page" in blank:
            fields[targets["product_page"]["name"]] = product_page
        flags = []
        if "swatch" in blank and targets["swatch"]["name"] not in fields:
            flags.append("no_swatch")
        if tier == "model_confirmed":
            flags.append("model_matched")
        if pp_source != "manufacturer":
            flags.append("product_page_not_manufacturer")
        actions.append({
            "id": action_id(sku, fields), "seq": len(actions) + 1, "target_system": "airtable",
            "op": "attach_images", "record_id": rid, "sku": sku,
            "product_name": rec.get("Product name") or "",
            "fields": fields,
            "field_ids": {name: next(t["id"] for t in targets.values() if isinstance(t, dict) and t["name"] == name)
                          for name in fields},
            "expect_blank": list(fields),
            "source_page": page_url, "product_page_source": pp_source, "match_tier": tier,
            "images": images, "flags": flags,
        })
    return {
        "contract_version": PLAN_VERSION, "scope": scope, "supplier": supplier,
        "run_at": now().isoformat(), "expires": now().strftime("%Y-%m-%dT23:59:59%z"),
        "write_mode": cfg["write_mode"]["mode"], "registry": "platform-settings/supplier-sites.json",
        "inputs": {"pages": pages_file.get("_path"), "judgements": (judgements or {}).get("_path"),
                   "product_pages": (product_pages or {}).get("_path")},
        "summary": {"records": len(records), "actions": len(actions), "held": len(held),
                    "skipped": dict(skipped),
                    "held_by_reason": dict(Counter(h["reason"] for h in held)),
                    "fields": dict(Counter(f for a in actions for f in a["fields"])),
                    "tiers": dict(Counter(a["match_tier"] for a in actions)),
                    "manufacturer_pages": sum(a["product_page_source"] == "manufacturer" for a in actions)},
        "actions": actions,
        "held": held,
    }


def todo(records, pages_file, judgements, cfg, supplier, scope):
    sup = cfg["suppliers"][supplier]
    pages = page_index(pages_file)
    matches = image_match.match_records(records, list(pages.values()), sup, cfg["matching"])
    by_id = {r["id"]: r for r in records}
    judged = set((judgements or {}).get("images", {}))
    decided = set((judgements or {}).get("matches", {}))
    images, ambiguous, need_pages = {}, [], set()
    for rid, m in matches.items():
        if m["tier"] == "exact":
            need_pages.add(m["candidates"][0]["url"])
        elif m["tier"] == "ambiguous":
            need_pages.update(c["url"] for c in m["candidates"])
            if choose_page(rid, m, None, pages)[1] == "exact":
                continue
            if rid not in decided:
                ambiguous.append({"record_id": rid, "sku": by_id[rid].get("SKU"),
                                  "product_name": by_id[rid].get("Product name"),
                                  "candidates": [{"url": c["url"], "title": image_match.page_title_text(pages[c["url"]])}
                                                 for c in m["candidates"]]})
    for url in sorted(need_pages):
        for img in pages[url].get("images", []):
            if img.get("status") == "downloaded" and img.get("sha1") and img["sha1"] not in judged:
                images.setdefault(img["sha1"], {"sha1": img["sha1"], "read_path": img.get("read_path"),
                                                "url": img["url"], "width": img.get("width"),
                                                "height": img.get("height"), "pages": []})
                images[img["sha1"]]["pages"].append(
                    {"url": url, "title": image_match.page_title_text(pages[url])})
    return {"contract_version": TODO_VERSION, "scope": scope, "supplier": supplier,
            "made_at": now().isoformat(),
            "judgements_contract": JUDGEMENTS_VERSION,
            "images_to_judge": list(images.values()), "ambiguous_records": ambiguous}


def approval(plan, cfg, plan_path):
    pol = cfg["policy"]
    ok = [a for a in plan["actions"] if a["match_tier"] in pol["auto_approve_tiers"]]
    ok = ok[: pol["max_actions_per_run"]]
    at = now().isoformat()
    return {"contract_version": APPROVAL_VERSION, "supplier": plan["supplier"], "scope": plan["scope"],
            "plan": str(plan_path), "approved_by": pol["approved_by"],
            "decisions": [{"id": a["id"], "status": "approved", "at": at} for a in ok]}


def contact_sheet(plan):
    e = html.escape
    rows = []
    for a in plan["actions"]:
        cells = []
        for target in ("swatch", "room", "detail"):
            imgs = [i for i in a["images"] if i["target"] == target]
            cells.append("".join(
                f'<a href="{e(i["url"])}"><img loading="lazy" src="{e(i["url"])}" alt="{e(target)}"></a>'
                f'<small>{i.get("width") or "?"}×{i.get("height") or "?"}</small>' for i in imgs) or "—")
        rows.append(
            f'<tr><td><b>{e(a["product_name"])}</b><br><code>{e(a["sku"])}</code><br>'
            f'<span class="tier {e(a["match_tier"])}">{e(a["match_tier"])}</span> '
            f'{" ".join(f"<span class=flag>{e(f)}</span>" for f in a["flags"])}<br>'
            f'<a href="{e(a["source_page"])}">image page</a>'
            + (f' · <a href="{e(a["fields"].get("Supplier product page", ""))}">product page</a>'
               if a["fields"].get("Supplier product page") else "")
            + "</td>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    held = "".join(f'<tr><td>{e(h["product_name"])}<br><code>{e(h["sku"])}</code></td>'
                   f'<td>{e(h["reason"])}</td><td>{e(h["detail"])}</td></tr>' for h in plan["held"])
    s = plan["summary"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Image fill {e(plan["supplier"])}</title><style>
:root{{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#e3e3e3;--acc:#1e6fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141414;--fg:#eee;--mut:#aaa;--line:#333}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif;margin:16px}}
table{{border-collapse:collapse;width:100%}}td,th{{border-top:1px solid var(--line);padding:8px;vertical-align:top;text-align:left}}
img{{height:120px;margin:0 6px 4px 0;border-radius:4px}}small{{display:block;color:var(--mut)}}
a{{color:var(--acc)}}.tier{{font-size:12px;padding:1px 6px;border-radius:8px;background:var(--line)}}
.flag{{font-size:12px;color:var(--mut)}}.wrap{{overflow-x:auto}}
</style></head><body>
<h1>Image fill — {e(plan["supplier"])} ({e(plan["write_mode"])})</h1>
<p>{s["actions"]} records to fill · {s["held"]} held · fields {e(json.dumps(s["fields"]))} ·
manufacturer product pages {s["manufacturer_pages"]} · plan run {e(plan["run_at"])}</p>
<div class="wrap"><table><tr><th>Record</th><th>Swatch</th><th>Room scene</th><th>Detail</th></tr>{"".join(rows)}</table></div>
<h2>Held</h2><div class="wrap"><table><tr><th>Record</th><th>Why</th><th>Detail</th></tr>{held}</table></div>
</body></html>
"""


def write_troubled(plan, path, cfg):
    base = f"https://airtable.com/{cfg['base_id']}/{cfg['table_id']}/"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, TROUBLED_COLUMNS, lineterminator="\n")
        w.writeheader()
        for h in plan["held"]:
            w.writerow({"sku": h["sku"], "product_name": h["product_name"], "reason": h["reason"],
                        "detail": h["detail"], "candidate_pages": " ".join(h["candidate_pages"]),
                        "airtable_record": base + h["record_id"]})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--supplier", required=True)
    ap.add_argument("--scope", required=True)
    ap.add_argument("--snapshot", action="append", required=True, type=Path)
    ap.add_argument("--pages", required=True, type=Path)
    ap.add_argument("--judgements", type=Path)
    ap.add_argument("--product-pages", type=Path)
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--write-approval", action="store_true")
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    ap.add_argument("--date", help="Default today (America/Toronto)")
    args = ap.parse_args(argv)

    cfg = load_json(args.registry)
    if args.supplier not in cfg["suppliers"]:
        print(f"error: {args.supplier} is not in the registry", file=sys.stderr)
        return 2
    date = args.date or now().strftime("%Y-%m-%d")
    records = load_snapshot(args.snapshot)
    pages_file = {**load_json(args.pages), "_path": str(args.pages)}
    judgements = load_json(args.judgements)
    if judgements is not None:
        if judgements.get("contract_version") != JUDGEMENTS_VERSION:
            print(f"error: judgements file is not {JUDGEMENTS_VERSION}", file=sys.stderr)
            return 2
        judgements["_path"] = str(args.judgements)
    product_pages = load_json(args.product_pages)
    if product_pages is not None:
        product_pages["_path"] = str(args.product_pages)
    out = cfg["outputs"]

    if args.prepare:
        t = todo(records, pages_file, judgements, cfg, args.supplier, args.scope)
        path = REPO_ROOT / "ingest" / date / f"image-todo-{args.scope}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(t, indent=1, ensure_ascii=False) + "\n")
        print(path)
        print(f"  judge {len(t['images_to_judge'])} images; decide {len(t['ambiguous_records'])} ambiguous records")
        return 0

    if args.write_approval and cfg["write_mode"]["mode"] != "write":
        print("error: write_mode is plan_only in platform-settings/supplier-sites.json; no approval file "
              "is written. Flipping it is a dated vault decision.", file=sys.stderr)
        return 4
    plan = build(records, pages_file, judgements, product_pages, cfg, args.supplier, args.scope)
    plans = REPO_ROOT / "plans" / date
    plans.mkdir(parents=True, exist_ok=True)
    plan_path = plans / out["plan"].format(scope=args.scope)
    plan_path.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n")
    (plans / out["contact_sheet"].format(scope=args.scope)).write_text(contact_sheet(plan))
    write_troubled(plan, plans / out["troubled"].format(scope=args.scope), cfg)
    print(plan_path)
    s = plan["summary"]
    print(f"  {s['actions']} actions, {s['held']} held {s['held_by_reason']}, skipped {s['skipped']}")
    print(f"  fields {s['fields']}; tiers {s['tiers']}; manufacturer pages {s['manufacturer_pages']}")
    if args.write_approval:
        ap_path = plans / out["approval"].format(scope=args.scope)
        appr = approval(plan, cfg, plan_path.relative_to(REPO_ROOT))
        ap_path.write_text(json.dumps(appr, indent=1) + "\n")
        print(f"  approval: {len(appr['decisions'])} ids -> {ap_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
