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
import re
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


def ahash(path):
    """64-bit average hash of an image file (None if unreadable): the same photo re-encoded
    by two sites hashes within a few bits."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            small = im.convert("L").resize((8, 8))
            px = [small.getpixel((x, y)) for y in range(8) for x in range(8)]
    except Exception:
        return None
    mean = sum(px) / 64
    return sum(1 << i for i, v in enumerate(px) if v >= mean)


def near_same(a, b, bits=6):
    return a is not None and b is not None and bin(a ^ b).count("1") <= bits


def is_blank(value):
    return value in (None, "", [])


def action_id(sku, fields):
    return "img-" + hashlib.sha1(f"{sku}|{json.dumps(fields, sort_keys=True)}".encode()).hexdigest()[:12]


def page_index(pages_file):
    return {p["url"]: p for p in pages_file.get("pages", [])}


LAYING = ("herringbone", "chevron", "versailles")


def record_laying(rec):
    """`herringbone`, `chevron`, `versailles` or `plank`, from the record's name and collection."""
    text = image_match.norm(f"{rec.get('Product name') or ''} {rec.get('Collection') or ''}")
    words = set(text.split())
    if "herringbone" in words or "hb" in words:
        return "herringbone"
    if "chevron" in words or "chev" in words:
        return "chevron"
    if "versailles" in words:
        return "versailles"
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


def source_order(sup):
    """Registry order of a supplier's sources: extra_sources first, then the main site."""
    return [*(sup.get("extra_sources") or []), {"name": sup.get("source_name", "main")}]


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


KIND_WORD = {"swatch": "swatch", "room": "room-scene", "detail": "detail"}


def slug(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (text or "").lower())).strip("-")


def width_word(width):
    """9 -> `9in`, 7.5 -> `7-5in`, 10.25 -> `10-25in` (a dot reads badly in a file name)."""
    if not width:
        return ""
    return f"{float(width):g}".replace(".", "-") + "in"


def seo_filename(rec, target, n, url, sup, matching):
    """A file name a shopper's search could land on (Albert, 2026-09-29: SEO/AEO):
    brand-colour-species-category-pattern-width-grade-code-kind[-n].ext, every part taken
    from the record's own fields, e.g.
    `vidar-naked-oak-american-white-oak-engineered-hardwood-9in-select-swatch.jpg`.
    The internal SKU is left out: Airtable already ties the file to the record, and no
    one searches it. The supplier's own code is kept when there is one (contractors search
    codes like NK25)."""
    ext = Path(url.split("?")[0]).suffix.lower()
    ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".heic") else ".jpg"
    feat = image_match.record_features(rec, sup, matching)
    species_words = (sup.get("species_words") or {}).get(feat["species"] or "", [])
    laying = record_laying(rec)
    parts = [rec.get("Brand") or (rec.get("Supplier") or "").title(), feat["colour"],
             species_words[0] if species_words else "", rec.get("Category") or "",
             laying if laying != "plank" else "", width_word(rec.get("Width (in)")),
             rec.get("Grade") or "", rec.get("Supplier SKU") or "", KIND_WORD.get(target, target)]
    kept = []
    for part in (slug((p or "").replace("&", " and ")) for p in parts):
        # Drop a part already said in full (the code NK25 is also the colour), never a
        # word inside one: `naked-oak` must not shorten `american-white-oak`.
        if part and not any(f"-{part}-" in f"-{k}-" for k in kept):
            kept.append(part)
    name = "-".join(kept)[:150].rstrip("-")
    return f"{name}-{n}{ext}" if n > 1 else f"{name}{ext}"


def build(records, pages_file, judgements, product_pages, cfg, supplier, scope):
    sup = cfg["suppliers"][supplier]
    targets, rules = cfg["targets"], cfg["image_rules"]
    pages = page_index(pages_file)
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
    by_source = {}
    for pg in pages.values():
        by_source.setdefault(pg.get("source") or "main", []).append(pg)
    order = [src["name"] for src in source_order(sup) if src["name"] in by_source] + \
        [name for name in by_source if name not in {s["name"] for s in source_order(sup)}]
    matches = {name: image_match.match_records(records, by_source[name], sup, cfg["matching"])
               for name in order}
    actions, held, skipped = [], [], Counter()
    for rec in sorted(records, key=lambda r: r.get("SKU") or ""):
        rid, sku = rec["id"], rec.get("SKU")
        blank = [t for t in ("swatch", "room", "detail", "product_page")
                 if is_blank(rec.get(targets[t]["name"]))]
        if not any(t in blank for t in ("swatch", "room", "detail")):
            skipped["all_targets_filled"] += 1
            continue
        chosen_pages, whys, candidates, colour, vetoes = [], [], [], "", {}
        for name in order:
            m = matches[name][rid]
            colour = colour or m["colour"]
            candidates += [c["url"] for c in m["candidates"]]
            for k, n in m["vetoes"].items():
                vetoes[k] = vetoes.get(k, 0) + n
            url, tier_s, why_s = choose_page(rid, m, judgements, pages)
            if url:
                chosen_pages.append((name, url, tier_s))
            else:
                whys.append(why_s)
        base = {"sku": sku, "record_id": rid, "product_name": rec.get("Product name") or "",
                "candidate_pages": candidates}
        if not chosen_pages:
            why = next((w for w in ("model_rejected", "ambiguous_match") if w in whys), "no_match")
            held.append({**base, "reason": why, "detail": f"colour '{colour}'; vetoes {vetoes}"})
            continue
        tier = "model_confirmed" if any(t == "model_confirmed" for _, _, t in chosen_pages) else "exact"
        picked, problems, rank = [], Counter(), {name: i for i, name in enumerate(order)}
        for name, url, _ in chosen_pages:
            got, prob = usable_images(pages[url], judgements, rules, record_laying(rec))
            picked += [(t, {**img, "_page": url, "_rank": rank[name]}) for t, img in got]
            problems.update(prob)
        # Best first: larger long edge, then the preferred source.
        picked.sort(key=lambda ti: (-ti[1]["long_edge"], ti[1]["_rank"]))
        fields, images, kept_hashes = {}, [], []
        for target in ("swatch", "room", "detail"):
            if target not in blank:
                continue
            chosen = []
            for t, img in picked:
                if t != target or len(chosen) >= targets[target]["cap"]:
                    continue
                h = ahash(img.get("read_path") or img.get("path") or "")
                if any(near_same(h, k) for k in kept_hashes):
                    continue  # the same photo from another site
                kept_hashes.append(h)
                chosen.append(img)
            if chosen:
                fields[targets[target]["name"]] = [
                    {"url": img["url"], "filename": seo_filename(rec, target, i + 1, img["url"], sup, cfg["matching"])}
                    for i, img in enumerate(chosen)]
                images += [{"target": target, "url": img["url"], "sha1": img["sha1"], "page": img["_page"],
                            "width": img.get("width"), "height": img.get("height")} for img in chosen]
        if not fields:
            reason = ("host_blocked" if problems.get("host_blocked") else
                      "not_judged" if problems.get("not_judged") else
                      "low_res_swatch" if problems.get("low_res_swatch") else "no_usable_image")
            held.append({**base, "reason": reason,
                         "detail": f"pages {[u for _, u, _ in chosen_pages]}; {dict(problems)}"})
            continue
        lead = next((i for i in images if i["target"] == "swatch"), images[0])
        page_url = lead["page"]
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
            "source_page": page_url, "source": pages[page_url].get("source"),
            "product_page_source": pp_source, "match_tier": tier,
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
    by_source = {}
    for pg in pages.values():
        by_source.setdefault(pg.get("source") or "main", []).append(pg)
    per_source = [image_match.match_records(records, pgs, sup, cfg["matching"]) for pgs in by_source.values()]
    by_id = {r["id"]: r for r in records}
    judged = set((judgements or {}).get("images", {}))
    decided = set((judgements or {}).get("matches", {}))
    images, ambiguous, need_pages = {}, [], set()
    for rid, m in ((rid, m) for matches in per_source for rid, m in matches.items()):
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


OLD_RUN_NAME = re.compile(r"^(?P<sku>.+)-(?P<kind>swatch|room|detail)-(?P<n>\d+)\.[a-z]+$")


def rename_plan(records, cfg, supplier, scope, source_plan=None):
    """Give files an earlier /image-fill run named `<SKU>-<kind>-<n>.<ext>` the SEO name
    (2026-09-29).

    Airtable ignores a new filename sent with an existing attachment id (tried 2026-09-29:
    the write succeeds, the name does not change), so a rename is a RE-ATTACH: the same
    source image URL the run attached, under the new name, which replaces the file. That
    is only allowed for a field whose every file carries that run's name pattern for THIS
    record, so a person's upload is never replaced; the writer compares the live ids and
    filenames with `expect` first. `source_plan` (the run's image plan) gives the URLs."""
    sup = cfg["suppliers"][supplier]
    targets = cfg["targets"]
    sources = {}
    for a in (source_plan or {}).get("actions", []):
        for name, value in a["fields"].items():
            if isinstance(value, list):
                sources[(a["record_id"], name)] = [v["url"] for v in value]
    actions = []
    for rec in sorted(records, key=lambda r: r.get("SKU") or ""):
        fields, expect = {}, {}
        for target in ("swatch", "room", "detail"):
            name = targets[target]["name"]
            atts = rec.get(name) or []
            if not atts:
                continue
            urls = sources.get((rec["id"], name))
            ours = all((m := OLD_RUN_NAME.match(a.get("filename") or "")) and m["sku"] == rec.get("SKU")
                       and m["kind"] == target for a in atts)
            if not ours or not urls or len(urls) != len(atts):
                continue  # a person's file is in the field, or the source URLs are unknown
            new = [{"url": urls[i], "filename": seo_filename(rec, target, i + 1, att["filename"], sup, cfg["matching"])}
                   for i, att in enumerate(atts)]
            changed = any(n["filename"] != a["filename"] for n, a in zip(new, atts))
            if changed:
                fields[name] = new
                expect[name] = [{"id": a["id"], "filename": a.get("filename")} for a in atts]
        if fields:
            actions.append({"id": action_id(rec.get("SKU"), {"rename": fields}), "seq": len(actions) + 1,
                            "target_system": "airtable", "op": "reattach_renamed",
                            "record_id": rec["id"], "sku": rec.get("SKU"),
                            "product_name": rec.get("Product name") or "", "fields": fields,
                            "field_ids": {n: next(t["id"] for t in targets.values()
                                                  if isinstance(t, dict) and t["name"] == n) for n in fields},
                            "expect": expect})
    return {"contract_version": PLAN_VERSION, "scope": scope, "supplier": supplier, "op": "reattach_renamed",
            "run_at": now().isoformat(), "expires": now().strftime("%Y-%m-%dT23:59:59%z"),
            "summary": {"records": len(actions), "files": sum(len(v) for a in actions for v in a["fields"].values())},
            "actions": actions, "held": []}


def approval(plan, cfg, plan_path):
    pol = cfg["policy"]
    ok = [a for a in plan["actions"]
          if a.get("op") == "reattach_renamed" or a.get("match_tier") in pol["auto_approve_tiers"]]
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
    ap.add_argument("--pages", type=Path, help="Required except with --rename-to-seo")
    ap.add_argument("--judgements", type=Path)
    ap.add_argument("--product-pages", type=Path)
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--source-plan", type=Path, help="With --rename-to-seo: the image plan that attached the files")
    ap.add_argument("--rename-to-seo", action="store_true",
                    help="Plan renaming this pipeline's earlier <SKU>-<kind>-<n> files to SEO names "
                         "(needs a snapshot that includes the image fields)")
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
    if not args.pages and not args.rename_to_seo:
        print("error: --pages is required", file=sys.stderr)
        return 2
    pages_file = {**load_json(args.pages), "_path": str(args.pages)} if args.pages else {"pages": []}
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

    if args.rename_to_seo:
        if args.write_approval and cfg["write_mode"]["mode"] != "write":
            print("error: write_mode is plan_only", file=sys.stderr)
            return 4
        plan = rename_plan(records, cfg, args.supplier, args.scope, load_json(args.source_plan))
        plans = REPO_ROOT / "plans" / date
        plans.mkdir(parents=True, exist_ok=True)
        path = plans / f"image-rename-{args.scope}.json"
        path.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n")
        print(path, plan["summary"])
        if args.write_approval:
            ap_path = plans / f"image-rename-approval-{args.scope}.json"
            ap_path.write_text(json.dumps(approval(plan, cfg, path.relative_to(REPO_ROOT)), indent=1) + "\n")
            print("  approval ->", ap_path)
        return 0

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
