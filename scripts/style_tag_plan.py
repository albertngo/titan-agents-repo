#!/usr/bin/env python3
"""Plan the style-tag writes for one scope. READ ONLY.

Turns three inputs into the single reviewable plan the approval gate acts on, per
contracts/style-plan-schema.md:

    candidates   scripts/style_tag_pull.py output — specs, blank fields, image manifest
    judgements   the model's structured read of each candidate's images + specs
                 (contracts/style-plan-schema.md, "The judgement file"); optional
    answers      reviewer `Action` cells read back from the Notion page table; optional

and emits

    plans/YYYY-MM-DD/style-plan-<scope>.json      one action per record, held rows
    ingest/YYYY-MM-DD/<scope>_style_troubled_<date>.csv   (--troubled-out)
    plans/YYYY-MM-DD/style-approval-<scope>.json  (--write-approval; refused under
                                                   write_mode plan_only)

Every decision is deterministic and lives in platform-settings/style-tags.json:
which source may decide which field (a room scene never reaches the colour tags at
any confidence), the finish -> Texture and grade -> Busyness tables, the threshold,
the agreement bonus. The model contributes observations through the judgement
file; this script decides what they are worth.

Policy, stated once: a tag writes only if the field is blank, the record is not
Staff confirmed, confidence >= min_confidence after caps, no spec-vs-image conflict,
and the value is a live option. Everything else is a held row with a fixed reason.
Held rows carry no id; a reviewer resolves them through the `Action` column (which
supplies a value) or by fixing the cause, then re-runs.

This script holds no credentials and writes nothing to any platform.

Usage:
    python3 scripts/style_tag_plan.py --candidates ingest/<date>/style-candidates-faw.json \
        --judgements ingest/<date>/style-judgements-faw.json \
        --answers ingest/<date>/faw_style_answers.json \
        --options ingest/<date>/faw_style_options.json \
        --troubled-out ingest/<date>/faw_style_troubled_<date>.csv
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "platform-settings" / "style-tags.json"
TZ = ZoneInfo("America/Toronto")
CONTRACT_VERSION = "style-plan-1"
APPROVAL_VERSION = "style-approval-1"
TARGET_SYSTEM = "airtable"
OP = "update_style_tags"
COLOUR_FIELDS = ("Undertone", "Tone depth")
SWATCH, ROOM, DETAIL = "swatch", "room", "detail"


def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def load_registry(path=REGISTRY):
    return json.loads(Path(path).read_text())


def target_names(reg):
    return [t for t in reg["targets"] if not t.startswith("_")]


def norm(text):
    """lowercase, letters and digits only, single spaces — `Wire Brushed; UV Oil` -> `wire brushed uv oil`."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower())).strip()


def words(text):
    return set(re.findall(r"[a-z]+", (text or "").lower()))


def action_id(sku, fields):
    raw = f"{sku}|{TARGET_SYSTEM}|{OP}|{','.join(sorted(fields))}".encode()
    return "sty-" + hashlib.sha1(raw).hexdigest()[:12]


def canonical_option(field, value, reg):
    """The live spelling of `value` for `field`, an int for Tone depth, or None."""
    target = reg["targets"][field]
    if target["type"] == "rating":
        try:
            n = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return n if target["min"] <= n <= target["max"] else None
    for opt in target["options"]:
        if str(value).strip().lower() == opt.lower():
            return opt
    return None


# ---------------------------------------------------------------------------
# Spec rules
# ---------------------------------------------------------------------------

def texture_from_finish(finish, reg):
    """{value, confidence, provisional, detail} from the finish -> Texture table, or None."""
    text = norm(finish)
    if not text:
        return None
    for rule in reg["spec_rules"]["texture_from_finish"]:
        if any(norm(needle) in text for needle in rule["contains"]):
            return {"value": rule["texture"], "confidence": rule["confidence"],
                    "provisional": bool(rule.get("provisional")),
                    "detail": f'Finish type "{finish}" -> {rule["texture"]} ({rule.get("why", "rule table")})'}
    return None


def busyness_from_specs(specs, reg):
    """Grade -> base busyness, then the modifiers, one step busier each. None when Grade is blank
    or not in the table."""
    rules = reg["spec_rules"]
    grade = (specs.get("Grade") or "").strip()
    if not grade:
        return None
    canonical = rules["grade_letter_map"].get(grade.upper(), grade)
    base = rules["busyness_from_grade"].get(canonical)
    if not base:
        return None
    ladder = rules["busyness_ladder"]
    level = ladder.index(base["busyness"])
    confidence = base["confidence"]
    provisional = bool(base.get("provisional"))
    notes = [f'Grade "{grade}" -> {base["busyness"]}']
    finish = norm(specs.get("Finish type"))
    for mod in rules["busyness_modifiers"]:
        hit = None
        if "finish_contains" in mod and finish and any(norm(n) in finish for n in mod["finish_contains"]):
            hit = f'finish "{specs.get("Finish type")}"'
        elif "colour_tone_in" in mod and (specs.get("Colour / tone") or "") in mod["colour_tone_in"]:
            hit = f'Colour / tone "{specs.get("Colour / tone")}"'
        elif "species_in" in mod and (specs.get("Species") or "") in mod["species_in"]:
            hit = f'Species "{specs.get("Species")}"'
        if hit and level < len(ladder) - 1:
            level = min(len(ladder) - 1, level + mod["step"])
            confidence = min(confidence, mod["confidence"])
            notes.append(f"{hit} +{mod['step']} ({mod.get('why', 'modifier')})")
    return {"value": ladder[level], "confidence": confidence, "provisional": provisional,
            "detail": "; ".join(notes)}


def name_text(specs):
    return f"{specs.get('Product name') or ''} {specs.get('Collection') or ''}"


def undertone_hint(specs, reg):
    """Supplier colour words as a hint at hint_confidence. None if no word hits, or words disagree."""
    found = words(name_text(specs))
    cw = reg["spec_rules"]["colour_words"]
    hits = {tone: sorted(found & set(cw[tone])) for tone in ("warm", "cool", "neutral")}
    hits = {t: w for t, w in hits.items() if w}
    if len(hits) != 1:
        return None
    tone, matched = next(iter(hits.items()))
    return {"value": tone.capitalize(), "confidence": reg["policy"]["hint_confidence"],
            "detail": f"colour words {matched} in the product name"}


def tone_depth_hint(specs, reg):
    """`Colour / tone` (canonical values only) or light/dark words, at hint_confidence."""
    table = reg["spec_rules"]["tone_depth_from_colour_tone"]
    ct = specs.get("Colour / tone")
    if ct in table and not str(ct).startswith("_"):
        return {"value": table[ct]["proposed"], "range": table[ct]["range"],
                "confidence": reg["policy"]["hint_confidence"], "detail": f'Colour / tone "{ct}"'}
    found = words(name_text(specs))
    cw = reg["spec_rules"]["colour_words"]
    light, dark = sorted(found & set(cw["light"])), sorted(found & set(cw["dark"]))
    if light and not dark:
        return {"value": 2, "range": [1, 2], "confidence": reg["policy"]["hint_confidence"],
                "detail": f"light words {light} in the product name"}
    if dark and not light:
        return {"value": 4, "range": [4, 5], "confidence": reg["policy"]["hint_confidence"],
                "detail": f"dark words {dark} in the product name"}
    return None


# ---------------------------------------------------------------------------
# Judgement lookups — the image's FIELD decides what it may inform
# ---------------------------------------------------------------------------

def image_index(cand):
    return {img["attachment_id"]: img for img in cand.get("images", []) if img.get("attachment_id")}


def misfiled(cand, judgement):
    """Swatch attachments the model says are not swatches. Never read for colour."""
    out = []
    index = image_index(cand)
    for jimg in (judgement or {}).get("images", []):
        img = index.get(jimg.get("attachment_id"))
        if not img or img["field"] != SWATCH:
            continue
        looks = jimg.get("looks_like")
        if looks and looks != SWATCH:
            out.append({"attachment_id": img["attachment_id"], "filename": img.get("filename"),
                        "looks_like": looks, "note": jimg.get("note", "")})
    return out


def usable_images(cand, judgement, kinds):
    """Downloaded attachments in `kinds` that the model did not flag as misfiled."""
    bad = {m["attachment_id"] for m in misfiled(cand, judgement)}
    unusable = {j["attachment_id"] for j in (judgement or {}).get("images", [])
                if j.get("usable_for_colour") is False}
    return [img for img in cand.get("images", [])
            if img["field"] in kinds and img.get("status") == "downloaded"
            and img["attachment_id"] not in bad
            and (SWATCH not in kinds or img["attachment_id"] not in unusable)]


def observation(judgement, key, cand, kinds):
    """judgement[key] if it cites a usable image in `kinds`; else None."""
    obs = (judgement or {}).get(key)
    if not obs or obs.get("value") in (None, ""):
        return None
    usable = {img["attachment_id"]: img for img in usable_images(cand, judgement, kinds)}
    src = obs.get("from")
    if src not in usable:
        return None
    return {"value": obs["value"], "confidence": float(obs.get("confidence", 0)),
            "evidence": obs.get("evidence", ""), "filename": usable[src].get("filename"),
            "attachment_id": src, "kind": usable[src]["field"]}


# ---------------------------------------------------------------------------
# Answers — a reviewer's `Action` cell is input, never authorisation
# ---------------------------------------------------------------------------

def field_by_name(name, reg):
    key = norm(name)
    for field in target_names(reg):
        if norm(field) == key:
            return field
    return None


def parse_answer(raw, row_field, reg):
    """One cell -> [(field, {"kind": value|skip|unparsed, ...})]. Grammar:
    `Field: Value`, several joined by `;`, `skip`, or a bare option name that belongs to exactly
    one target field. Anything else is unparsed — never fuzzy-matched."""
    out = []
    text = (raw or "").strip()
    if not text:
        return out
    for part in [p.strip() for p in text.split(";") if p.strip()]:
        if part.lower() == "skip":
            out.append((row_field, {"kind": "skip", "raw": part}))
            continue
        if ":" in part:
            fname, value = [x.strip() for x in part.split(":", 1)]
            field = field_by_name(fname, reg)
            if not field:
                out.append((row_field, {"kind": "unparsed", "raw": part,
                                        "detail": f"no target field named {fname!r}"}))
                continue
            canon = canonical_option(field, value, reg)
            if canon is None:
                out.append((field, {"kind": "unparsed", "raw": part,
                                    "detail": f"{value!r} is not a live option of {field}"}))
            else:
                out.append((field, {"kind": "value", "value": canon, "raw": part}))
            continue
        matches = [f for f in target_names(reg) if canonical_option(f, part, reg) is not None]
        if len(matches) == 1:
            out.append((matches[0], {"kind": "value", "value": canonical_option(matches[0], part, reg),
                                     "raw": part}))
        else:
            why = "belongs to several fields" if matches else "matches no option"
            out.append((row_field, {"kind": "unparsed", "raw": part, "detail": f"{part!r} {why}"}))
    return out


def parse_answers(rows, reg):
    """[{sku, field, action}] -> {(sku, field): answer}. A later answer for the same key wins."""
    parsed = {}
    for row in rows or []:
        sku = (row.get("sku") or "").strip()
        if not sku or not (row.get("action") or "").strip():
            continue
        for field, answer in parse_answer(row["action"], row.get("field"), reg):
            if field:
                parsed[(sku, field)] = answer
    return parsed


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def _held(reason, proposed=None, confidence=None, source="", detail=""):
    return {"reason": reason, "proposed": proposed, "confidence": confidence,
            "source": source, "detail": detail}


def _tag(value, confidence, source, evidence, image=None, provisional=False, rule=""):
    return {"value": value, "confidence": round(min(1.0, confidence), 3), "source": source,
            "evidence": evidence, "image": image, "provisional": provisional, "rule": rule}


def _combine_primary_secondary(spec, img, reg, image_label):
    """Spec decides; a same-kind image can confirm (bonus), conflict (both >= threshold) or be noted."""
    thr, bonus = reg["policy"]["min_confidence"], reg["policy"]["agreement_bonus"]
    if spec and img:
        if str(spec["value"]) == str(img["value"]):
            return "tag", _tag(spec["value"], max(spec["confidence"], img["confidence"]) + bonus, "both",
                               f"{spec['detail']}; {image_label} {img['filename']} agrees ({img['evidence']})",
                               image=img["filename"], provisional=spec["provisional"], rule=spec["detail"])
        if spec["confidence"] >= thr and img["confidence"] >= thr:
            return "held", _held("spec_image_conflict", f"{spec['value']}|{img['value']}",
                                 max(spec["confidence"], img["confidence"]), "both",
                                 f"spec says {spec['value']} ({spec['detail']}); {image_label} "
                                 f"{img['filename']} says {img['value']} ({img['evidence']})")
        return "tag", _tag(spec["value"], spec["confidence"], "spec",
                           f"{spec['detail']}; {image_label} {img['filename']} differs below threshold "
                           f"({img['value']} at {img['confidence']:.2f})",
                           provisional=spec["provisional"], rule=spec["detail"])
    if spec:
        return "tag", _tag(spec["value"], spec["confidence"], "spec", spec["detail"],
                           provisional=spec["provisional"], rule=spec["detail"])
    return None, None


def _threshold(kind, payload, reg):
    if kind != "tag":
        return kind, payload
    if payload["confidence"] < reg["policy"]["min_confidence"]:
        return "held", _held("low_confidence", payload["value"], payload["confidence"],
                             payload["source"], payload["evidence"])
    return kind, payload


def resolve_texture(cand, judgement, reg):
    specs = cand["specs"]
    spec = texture_from_finish(specs.get("Finish type"), reg)
    img = observation(judgement, "texture_seen", cand, {DETAIL})
    if spec is None:
        if specs.get("Finish type"):
            return "held", _held("spec_unmapped", img["value"] if img else None,
                                 img["confidence"] if img else None, "detail_images" if img else "",
                                 f'Finish type "{specs["Finish type"]}" is not in the texture table'
                                 + (f"; detail image {img['filename']} proposes {img['value']}" if img else ""))
        if img:
            return "held", _held("spec_unmapped", img["value"], img["confidence"], "detail_images",
                                 f"no Finish type; detail image {img['filename']} proposes {img['value']} "
                                 f"({img['evidence']}) — a detail image cannot decide Texture alone")
        return None, None
    kind, payload = _combine_primary_secondary(spec, img, reg, "detail image")
    return _threshold(kind, payload, reg)


def resolve_busyness(cand, judgement, reg):
    specs = cand["specs"]
    spec = busyness_from_specs(specs, reg)
    seen = observation(judgement, "busyness_seen", cand, {SWATCH, DETAIL})
    if spec is None:
        grade = (specs.get("Grade") or "").strip()
        if grade:
            return "held", _held("spec_unmapped", seen["value"] if seen else None,
                                 seen["confidence"] if seen else None, "image" if seen else "",
                                 f'Grade "{grade}" is not in the busyness table')
        if seen:
            return "held", _held("spec_unmapped", seen["value"], seen["confidence"], "image",
                                 f"no Grade; image {seen['filename']} proposes {seen['value']} "
                                 f"({seen['evidence']}) — an image cannot decide Busyness alone")
        return None, None
    kind, payload = _combine_primary_secondary(spec, seen, reg, "image")
    return _threshold(kind, payload, reg)


def _colour_hold_reason(cand, judgement, images_status):
    swatches = [img for img in cand.get("images", []) if img["field"] == SWATCH]
    if not swatches:
        return "no_swatch", "no attachment in Swatch images"
    statuses = {img.get("status") for img in swatches}
    if images_status == "host_blocked" or statuses <= {"host_blocked"}:
        return "image_host_blocked", "Swatch images exist but the image host refused the download"
    if statuses <= {"unsupported_format", "host_blocked", "failed"} and "unsupported_format" in statuses:
        return "image_format_unsupported", "the only swatches are in a format the reader cannot decode (HEIC?)"
    if statuses <= {"not_downloaded"}:
        return "no_swatch", "swatches were not downloaded on this run (no --download)"
    if misfiled(cand, judgement) and not usable_images(cand, judgement, {SWATCH}):
        return "no_swatch", "every Swatch images attachment looks misfiled (see image_misfiled rows)"
    return "no_swatch", "no usable swatch judgement for this record"


def resolve_colour(field, cand, judgement, reg, images_status):
    key = "undertone" if field == "Undertone" else "tone_depth"
    img = observation(judgement, key, cand, {SWATCH})
    hint = undertone_hint(cand["specs"], reg) if field == "Undertone" else tone_depth_hint(cand["specs"], reg)
    if img is None:
        reason, why = _colour_hold_reason(cand, judgement, images_status)
        return "held", _held(reason, hint["value"] if hint else None, hint["confidence"] if hint else None,
                             "hint" if hint else "", why + (f"; hint: {hint['detail']}" if hint else ""))
    value = canonical_option(field, img["value"], reg)
    if value is None:
        return "held", _held("low_confidence", img["value"], img["confidence"], "image",
                             f"model value {img['value']!r} is not a live option of {field}")
    confidence, source = img["confidence"], "image"
    evidence = f"swatch {img['filename']}: {img['evidence']}"
    if hint:
        agrees = (value in hint["range"]) if "range" in hint else (hint["value"] == value)
        if agrees:
            confidence += reg["policy"]["agreement_bonus"]
            source = "both"
            evidence += f"; {hint['detail']} agrees"
        else:
            evidence += f"; {hint['detail']} differs (hint only)"
    return _threshold("tag", _tag(value, confidence, source, evidence, image=img["filename"]), reg)


def resolve_style(cand, judgement, reg):
    sj = (judgement or {}).get("style")
    if not sj or not sj.get("values"):
        return None, None
    values, dropped = [], []
    for v in sj["values"]:
        canon = canonical_option("Style", v, reg)
        (values if canon else dropped).append(canon or v)
    if not values:
        return "held", _held("low_confidence", sj["values"], float(sj.get("confidence", 0)), "image",
                             f"none of {sj['values']} is a live Style option")
    confidence = float(sj.get("confidence", 0))
    evidence = sj.get("evidence", "")
    if dropped:
        evidence += f"; dropped non-options {dropped}"
    usable = usable_images(cand, judgement, {SWATCH, ROOM})
    if not usable:
        return "held", _held("needs_image", values, min(confidence, reg["policy"]["spec_only_style_cap"]),
                             "spec", f"no swatch or room scene to judge style from; specs alone propose {values}")
    names = ", ".join(sorted({img["filename"] or "" for img in usable}))
    return _threshold("tag", _tag(values, confidence, "both", f"{evidence} (images: {names})",
                                  image=names), reg)


def resolve_record(cand, judgement, answers, reg, images_status):
    """(approved {field: tag}, held rows, no_information fields) for one candidate."""
    approved, held, quiet = {}, [], []
    for m in misfiled(cand, judgement):
        held.append({"field": "Swatch images", **_held(
            "image_misfiled", None, None, "image",
            f"{m['filename']} looks like a {m['looks_like']}, not a swatch; nothing was read from it. "
            f"Move it to the right field. {m['note']}".strip())})
    for field in cand["blank_fields"]:
        answer = answers.get((cand["sku"], field))
        if answer:
            if answer["kind"] == "skip":
                held.append({"field": field, **_held("reviewer_skipped", None, None, "reviewer",
                                                     "reviewer wrote skip; not proposed again")})
            elif answer["kind"] == "unparsed":
                held.append({"field": field, **_held("answer_unparsed", None, None, "reviewer",
                                                     f"{answer['raw']!r}: {answer['detail']}")})
            else:
                approved[field] = _tag(answer["value"], 1.0, "reviewer",
                                       f"reviewer answer {answer['raw']!r} on the troubled table")
            continue
        if field == "Texture":
            kind, payload = resolve_texture(cand, judgement, reg)
        elif field == "Busyness":
            kind, payload = resolve_busyness(cand, judgement, reg)
        elif field in COLOUR_FIELDS:
            kind, payload = resolve_colour(field, cand, judgement, reg, images_status)
        elif field == "Style":
            kind, payload = resolve_style(cand, judgement, reg)
        else:
            kind, payload = None, None
        if kind == "tag":
            approved[field] = payload
        elif kind == "held":
            held.append({"field": field, **payload})
        else:
            quiet.append(field)
    return approved, held, quiet


# ---------------------------------------------------------------------------
# Plan assembly
# ---------------------------------------------------------------------------

def value_text(value):
    return "|".join(value) if isinstance(value, list) else str(value)


def source_label(tag):
    if tag["source"] == "spec":
        return "spec"
    if tag["source"] == "reviewer":
        return "reviewer"
    if tag["source"] == "image":
        return f"image: {tag.get('image') or ''}".rstrip(": ")
    return f"spec + image {tag.get('image') or ''}".rstrip()


def evidence_block(plan_path, tags, reg):
    lines = [f"AI suggested {today()} — {plan_path}"]
    for field in target_names(reg):
        if field in tags:
            t = tags[field]
            lines.append(f"{field}: {value_text(t['value'])} ({t['confidence']:.2f}, {source_label(t)}) — {t['evidence']}")
    return "\n".join(lines)


def build_plan(candidates_doc, judgements_doc, answers_rows, reg, scope=None, plan_path=None):
    scope = scope or candidates_doc.get("scope") or "unknown"
    plan_path = plan_path or reg["outputs"]["plan"].format(date=today(), scope=scope)
    judgements = {j["sku"]: j for j in (judgements_doc or {}).get("records", []) if j.get("sku")}
    answers = parse_answers(answers_rows, reg)
    images_status = (candidates_doc.get("images") or {}).get("status", "none")
    supplier = candidates_doc.get("supplier", "")

    actions, held_rows, flagged_rows = [], [], []
    quiet_total, used_answers = Counter(), set()
    for cand in candidates_doc.get("candidates", []):
        approved, held, quiet = resolve_record(cand, judgements.get(cand["sku"]), answers, reg, images_status)
        for field in cand["blank_fields"]:
            if (cand["sku"], field) in answers:
                used_answers.add((cand["sku"], field))
        quiet_total.update(quiet)
        base = {"supplier": cand.get("supplier") or supplier, "sku": cand["sku"],
                "product_name": cand.get("product_name", "")}
        for row in held:
            held_rows.append({**base, **row, "disposition": "held", "action_id": ""})
        if not approved:
            continue
        aid = action_id(cand["sku"], approved.keys())
        action = {
            "id": aid,
            "seq": len(actions) + 1,
            "target_system": TARGET_SYSTEM,
            "op": OP,
            "record_id": cand["record_id"],
            "sku": cand["sku"],
            "product_name": cand.get("product_name", ""),
            "supplier": base["supplier"],
            "fields": {f: approved[f]["value"] for f in target_names(reg) if f in approved},
            "tags": {f: approved[f] for f in target_names(reg) if f in approved},
            "status_write": None if cand.get("status") else reg["status_field"]["run_writes"],
            "evidence_append": evidence_block(plan_path, approved, reg),
            "flags": [],
        }
        for field, tag in approved.items():
            if tag.get("provisional"):
                action["flags"].append("spec_rule_provisional")
                flagged_rows.append({**base, "field": field, "reason": "spec_rule_provisional",
                                     "disposition": "wrote_flagged", "proposed": tag["value"],
                                     "confidence": tag["confidence"], "source": tag["source"],
                                     "detail": tag["evidence"], "action_id": aid})
        actions.append(action)

    tags_by_field = Counter(f for a in actions for f in a["fields"])
    unmatched = sorted(f"{s}/{f}" for (s, f) in answers if (s, f) not in used_answers)
    return {
        "contract_version": CONTRACT_VERSION,
        "scope": scope,
        "supplier": supplier,
        "run_at": datetime.now(TZ).isoformat(),
        "write_mode": reg["write_mode"]["mode"],
        "approved_by": reg["policy"]["approved_by"],
        "inputs": [],
        "summary": {
            "records_in": len(candidates_doc.get("candidates", [])),
            "actions_total": len(actions),
            "tags_total": sum(tags_by_field.values()),
            "tags_by_field": dict(tags_by_field),
            "held": len(held_rows),
            "held_by_reason": dict(Counter(r["reason"] for r in held_rows)),
            "flagged": len(flagged_rows),
            "no_information": dict(quiet_total),
            "images_status": images_status,
            "answers_applied": len(used_answers),
            "answers_unmatched": unmatched,
        },
        "actions": actions,
        "held": held_rows,
        "flagged": flagged_rows,
    }


def troubled_rows(plan, prior_answers=None):
    """CSV rows per contracts/troubled-tags-schema.md, held first, `Action` carried forward by sku+field."""
    prior = {((r.get("sku") or "").strip(), r.get("field")): (r.get("action") or "")
             for r in (prior_answers or [])}
    rows = []
    for r in sorted(plan["held"], key=lambda r: (r["sku"], r["field"])) + \
             sorted(plan["flagged"], key=lambda r: (r["sku"], r["field"])):
        rows.append({
            "supplier": r.get("supplier", ""), "sku": r["sku"], "product_name": r.get("product_name", ""),
            "field": r["field"], "reason": r["reason"], "disposition": r["disposition"],
            "proposed": value_text(r["proposed"]) if r.get("proposed") not in (None, "") else "",
            "confidence": f"{r['confidence']:.2f}" if isinstance(r.get("confidence"), (int, float)) else "",
            "source": r.get("source", ""), "detail": r.get("detail", ""),
            "action_id": r.get("action_id", ""),
            "Action": prior.get((r["sku"], r["field"]), ""),
        })
    return rows


def write_troubled_csv(plan, path, reg, prior_answers=None):
    rows = troubled_rows(plan, prior_answers)
    if not rows:
        return 0  # a clean run writes no file — never a headers-only CSV
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=reg["troubled_columns"], quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def approval_for(plan, plan_path, reg):
    """The policy approval file. Refused under write_mode plan_only — that is the staged rollout."""
    if reg["write_mode"]["mode"] != "write":
        raise PermissionError(
            f"write_mode is {reg['write_mode']['mode']!r}: no approval file is written and nothing "
            "executes. Flipping it is a dated decision (platform-settings/style-tags.json write_mode).")
    now = datetime.now(TZ).isoformat()
    return {
        "contract_version": APPROVAL_VERSION,
        "scope": plan["scope"],
        "plan": str(plan_path),
        "approved_by": reg["policy"]["approved_by"],
        "decisions": [{"id": a["id"], "status": "approved", "at": now} for a in plan["actions"]],
    }


def check_options(options_doc, reg):
    """Every option string the registry expects must exist live. Returns the missing ones."""
    live = {}
    tables = options_doc.get("tables", [options_doc]) if isinstance(options_doc, dict) else []
    for table in tables:
        for field in table.get("fields", []):
            cfg = field.get("config") or field.get("options") or {}
            if isinstance(cfg, dict) and "choices" in cfg:
                live[field["id"]] = {c.get("name") for c in cfg["choices"]}
    missing = []
    for name in target_names(reg):
        t = reg["targets"][name]
        if "options" not in t:
            continue
        if t["id"] not in live:
            missing.append(f"{name}: field {t['id']} not in the options read")
            continue
        for opt in t["options"]:
            if opt not in live[t["id"]]:
                missing.append(f"{name}: option {opt!r} missing live")
    sf = reg["status_field"]
    if sf["id"] in live:
        for opt in sf["options"]:
            if opt not in live[sf["id"]]:
                missing.append(f"{sf['name']}: option {opt!r} missing live")
    else:
        missing.append(f"{sf['name']}: field {sf['id']} not in the options read")
    return missing


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", required=True, type=Path)
    ap.add_argument("--judgements", type=Path, help="The model's judgement file; optional (spec-only run)")
    ap.add_argument("--answers", type=Path, help="[{sku, field, action}] read back from the page table")
    ap.add_argument("--options", type=Path, help="get_table_schema output for the pre-flight")
    ap.add_argument("--no-preflight", action="store_true", help="Skip the live-option check (tests only)")
    ap.add_argument("--scope")
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    ap.add_argument("--out", type=Path, help="Default plans/<today>/style-plan-<scope>.json")
    ap.add_argument("--troubled-out", type=Path, help="Write the troubled CSV here (only if rows exist)")
    ap.add_argument("--write-approval", action="store_true",
                    help="Write the policy approval file. Refused under write_mode plan_only")
    ap.add_argument("--approval-out", type=Path)
    args = ap.parse_args(argv)

    reg = load_registry(args.registry)
    candidates = json.loads(args.candidates.read_text())
    judgements = json.loads(args.judgements.read_text()) if args.judgements else None
    answers = json.loads(args.answers.read_text()) if args.answers else []
    scope = args.scope or candidates.get("scope") or "unknown"

    if not args.no_preflight:
        if not args.options:
            print("error: --options (a fresh get_table_schema read) is required; a value Airtable "
                  "lacks must stop the run before anything is planned. --no-preflight is for tests.",
                  file=sys.stderr)
            return 2
        missing = check_options(json.loads(args.options.read_text()), reg)
        if missing:
            print("error: the registry names options the base does not have. Never add the option; "
                  "a person does:", file=sys.stderr)
            for m in missing:
                print(f"  - {m}", file=sys.stderr)
            return 3

    plan_path = args.out or (REPO_ROOT / "plans" / today() / f"style-plan-{scope}.json")
    rel = plan_path.relative_to(REPO_ROOT) if plan_path.is_relative_to(REPO_ROOT) else plan_path
    plan = build_plan(candidates, judgements, answers, reg, scope, str(rel))
    plan["inputs"] = [{"file": str(p)} for p in (args.candidates, args.judgements, args.answers, args.options) if p]
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n")

    s = plan["summary"]
    print(rel)
    print(f"  write_mode   {plan['write_mode']}")
    print(f"  records in   {s['records_in']}")
    print(f"  actions      {s['actions_total']}   tags {s['tags_total']} {s['tags_by_field']}")
    print(f"  held         {s['held']} {s['held_by_reason']}")
    print(f"  flagged      {s['flagged']}")
    if s["no_information"]:
        print(f"  no info      {s['no_information']}   (blank field, nothing to say; no row)")
    if s["answers_unmatched"]:
        print(f"  answers not matched to a blank field: {s['answers_unmatched']}")

    if args.troubled_out:
        n = write_troubled_csv(plan, args.troubled_out, reg, answers)
        print(f"  troubled     {n} rows -> {args.troubled_out}" if n else "  troubled     clean run, no file written")

    if args.write_approval:
        try:
            approval = approval_for(plan, rel, reg)
        except PermissionError as exc:
            print(f"\n  approval NOT written: {exc}", file=sys.stderr)
            return 4
        apath = args.approval_out or (REPO_ROOT / "plans" / today() / f"style-approval-{scope}.json")
        apath.write_text(json.dumps(approval, indent=1) + "\n")
        print(f"  approval     {len(approval['decisions'])} ids -> {apath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
