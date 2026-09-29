#!/usr/bin/env python3
"""Match catalogue records to supplier web pages for /image-fill. Pure functions, no I/O.

A page matches a record only when the record's colour name appears in the page's
TITLE (title, h1, og:title, product name; the URL slug only when a page has no
title at all). Body text never counts: a generic colour ('Natural') appears on
every page. Width, species, pattern and grade then agree, say nothing, or VETO.

Tiers (platform-settings/supplier-sites.json -> matching):
  exact      the supplier's own code equals the record's Supplier SKU, or exactly
             one page holds the top score
  ambiguous  more than one page ties at the top; the model picks at most one
  none       no page

Used by scripts/supplier_site_pull.py (which pages' images to download),
scripts/image_fill_plan.py (the plan) and the product-page index match.
"""

import re

SPACE = re.compile(r"\s+")
WIDTH_IN_TEXT = re.compile(
    r"(?<![\d./])(\d{1,2}(?:\.\d{1,2})?|\d{1,2} ?\d/\d)\s*(?:''|\"|″|”|in\b|inch|-inch|\s*collection)", re.I)
FRACTIONS = {"1/4": .25, "1/2": .5, "3/4": .75, "1/3": 1 / 3, "2/3": 2 / 3, "½": .5, "¼": .25, "¾": .75}


def norm(text):
    """Lower-case words: 'Naked-Oak™ & Co.' -> 'naked oak and co'."""
    text = (text or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9.]+", " ", text)
    text = re.sub(r"(?<![0-9])\.|\.(?![0-9])", " ", text)
    return SPACE.sub(" ", text).strip()


def has_phrase(haystack, phrase):
    """Whole-word phrase match that forgives a joined or split word: `Day Break` finds
    `Daybreak` and `Snowwhite` finds `Snow White` (both spellings are in the catalogue)."""
    phrase, hay = norm(phrase), norm(haystack)
    if not phrase:
        return False
    if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", hay):
        return True
    compact, words = phrase.replace(" ", ""), hay.split()
    return any("".join(words[i:i + n]) == compact
               for n in (1, 2, 3) for i in range(len(words) - n + 1))


def to_width(token):
    token = token.strip().replace(" ", " ")
    m = re.fullmatch(r"(\d{1,2}) ?(\d/\d)", token)
    if m:
        return float(m.group(1)) + FRACTIONS.get(m.group(2), 0)
    try:
        return float(token)
    except ValueError:
        return None


def widths_in(text):
    """Widths in inches, rounded to 2 places (`11 2/3"` -> 11.67, matching the catalogue).
    A bare fraction is a thickness, never a width: `3/4" (18mm)` yields nothing."""
    return {round(w, 2) for w in (to_width(m.group(1)) for m in WIDTH_IN_TEXT.finditer(text or "")) if w}


def colour_of(product_name):
    """'Vidar 7.5" AWO — Naked Oak (Character)' -> 'Naked Oak'; 'Vidar Laminate — NK25' -> 'NK25'."""
    name = product_name or ""
    if " — " not in name:
        return ""
    seg = re.sub(r"\s*\(.*$", "", name.split(" — ")[1]).strip()
    # A size (`4"x10"`, an accessory's segment) is not a colour: a colour has letters.
    return seg if re.search(r"[A-Za-z]{2}", seg) else ""


def grade_of(rec):
    return (rec.get("Grade") or "").strip()


def record_features(rec, supplier_cfg, matching):
    name = rec.get("Product name") or ""
    head = name.split(" — ")[0]
    species = None
    for code in (supplier_cfg.get("species_words") or {}):
        if re.search(rf"(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])", head, re.I):
            species = code
            break
    allowed_widths, exact_width = set(), None
    if rec.get("Width (in)"):
        exact_width = round(float(rec["Width (in)"]), 2)
        allowed_widths.add(exact_width)
    for n in re.findall(r"(?<![\d.])(\d{1,2}(?:\.\d)?)(?![\d.])", rec.get("Collection") or ""):
        allowed_widths.add(float(n))
    head_and_collection = f"{head} {rec.get('Collection') or ''} {rec.get('Category') or ''}"
    patterns = {p for p in matching.get("pattern_words", []) if has_phrase(head_and_collection, p)}
    return {
        "record_id": rec.get("id") or rec.get("record_id"),
        "sku": rec.get("SKU"),
        "colour": colour_of(name),
        "supplier_sku": (rec.get("Supplier SKU") or "").strip(),
        "species": species,
        "widths": allowed_widths,
        "exact_width": exact_width,
        "patterns": patterns,
        "grade": grade_of(rec),
    }


def page_title_text(page):
    parts = [page.get(k) or "" for k in ("title", "h1", "og_title", "product_name")]
    text = " | ".join(p for p in parts if p)
    if not text:
        slug = (page.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
        text = slug.replace("-", " ").replace("_", " ")
    return text


def colour_segment_exact(title, colour):
    """True when a dash-separated segment of the title IS the colour: '...-Naked Oak'."""
    segs = re.split(r"\s*[-–—|:]\s*", title or "")
    return any(norm(s).replace(" ", "") == norm(colour).replace(" ", "") for s in segs if s)


def score(feat, page, supplier_cfg, matching):
    """(score, veto) for one record against one page. score 0 means no match."""
    codes = {c.upper() for c in page.get("codes") or []}
    if feat["supplier_sku"] and feat["supplier_sku"].upper() in codes:
        return 100, None
    title = page_title_text(page)
    if not feat["colour"] or not has_phrase(title, feat["colour"]):
        return 0, None
    s = 10 + (5 if colour_segment_exact(title, feat["colour"]) else 0)
    page_widths = widths_in(title)
    if page_widths:
        # A record's own width must be on the page. The collection number (`7 Collection`)
        # stands in only for a record with no width: the catalogue holds 7" and 7.5" records
        # of the same colour, so a 7" listing is not a 7.5" record's product.
        allowed = {feat["exact_width"]} if feat["exact_width"] else feat["widths"]
        if allowed and not (page_widths & allowed):
            return 0, "width"
        s += 3
    species_words = supplier_cfg.get("species_words") or {}
    page_species = {code for code, words in species_words.items() if any(has_phrase(title, w) for w in words)}
    if page_species and feat["species"]:
        if feat["species"] not in page_species:
            return 0, "species"
        s += 2
    page_patterns = {p for p in matching.get("pattern_words", []) if has_phrase(title, p)}
    if page_patterns != feat["patterns"] and (page_patterns or feat["patterns"]):
        return 0, "pattern"
    if feat["patterns"]:
        s += 1
    page_grades = {g for g in matching.get("grade_words", []) if has_phrase(title, g)}
    # Longest match wins: `Select & Better` on the page is not also `Select`.
    page_grades = {norm(g) for g in page_grades}  # `Select & Better` == `Select and Better`
    page_grades = {g for g in page_grades
                   if not any(g != h and has_phrase(h, g) for h in page_grades)}
    if page_grades and feat["grade"]:
        if not any(norm(g) == norm(feat["grade"]) for g in page_grades):
            return 0, "grade"
        s += 1
    return s, None


def match_records(records, pages, supplier_cfg, matching):
    """{record_id: {"tier", "candidates": [{"url", "score"}], "vetoes": {reason: n}}}"""
    out = {}
    for rec in records:
        feat = record_features(rec, supplier_cfg, matching)
        scored, vetoes = [], {}
        for page in pages:
            s, veto = score(feat, page, supplier_cfg, matching)
            if veto:
                vetoes[veto] = vetoes.get(veto, 0) + 1
            if s:
                scored.append({"url": page["url"], "score": s})
        scored.sort(key=lambda c: (-c["score"], c["url"]))
        if not scored:
            tier = "none"
        elif scored[0]["score"] >= 100 or len(scored) == 1 or scored[0]["score"] > scored[1]["score"]:
            tier = "exact"
        else:
            tier = "ambiguous"
        top = [c for c in scored if c["score"] == scored[0]["score"]] if scored else []
        out[feat["record_id"]] = {"tier": tier, "colour": feat["colour"],
                                  "candidates": (top if tier == "ambiguous" else scored)[:3],
                                  "vetoes": vetoes}
    return out
