#!/usr/bin/env python3
"""Pull the /style-tag candidates from a saved Airtable snapshot. READ ONLY.

Reads the raw `list_records_for_table` output the command saved, applies the
eligibility rule in platform-settings/style-tags.json, and writes one candidates
file per scope:

    ingest/YYYY-MM-DD/style-candidates-<scope>.json

Per candidate: the record id, the specs the rule tables read, which target fields
are blank, and an image manifest that says which Airtable field each attachment
sits in. The KIND of an image is a fact from its field (Swatch images / Room scene
images / Detail images), never a guess — that is what lets a room scene be kept
away from the colour tags structurally rather than by judgement.

With --download it fetches every attachment's ORIGINAL (`url`, never a thumbnail:
thumbnails are re-encoded and can shift colour) to

    ingest/YYYY-MM-DD/style-images/<sku>/<kind>/<attachment_id>-<filename>

and writes a downscaled `<attachment_id>-read.jpg` beside it for the model to
read. The directory is gitignored. Attachment URLs are signed and expire within
hours, so the manifest stores ids and filenames, never URLs, and the download
happens here, in the same step as the snapshot.

Fails SOFT on the one environment problem found while planning (2026-09-26): the
cloud proxy refuses CONNECT to v5.airtableusercontent.com. That sets
`images.status: host_blocked` on the file and the run carries on spec-only; the
plan then holds the colour tags as image_host_blocked instead of guessing.

This script holds no credentials and writes nothing to any platform.

Usage:
    python3 scripts/style_tag_pull.py \
        --snapshot ingest/<date>/<scope>_style_snapshot.json --scope faw \
        [--download] [--sku ENG-FAWK-0060,ENG-FAWK-0065] [--out ...]
"""

import argparse
import json
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "platform-settings" / "style-tags.json"
TZ = ZoneInfo("America/Toronto")
CONTRACT_VERSION = "style-candidates-1"
READ_LONG_EDGE = 1568  # px; keeps a swatch's colour, drops the token cost of a 4000px original
SPEC_KEYS = ("Finish type", "Grade", "Species", "Colour / tone", "Collection",
             "Product name", "Salesperson notes")
SIGNAL_KEYS = ("Finish type", "Grade", "Species", "Colour / tone")


def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_") or "unknown"


def load_registry(path=REGISTRY):
    return json.loads(Path(path).read_text())


def target_names(reg):
    return [t for t in reg["targets"] if not t.startswith("_")]


def field_names(reg):
    """Field id -> the name this script uses for it, for every field a snapshot may carry."""
    names = {}
    for key, fid in reg["inputs"].items():
        if key.startswith("_"):
            continue
        names[fid] = reg["image_fields"][key]["name"] if key in reg["image_fields"] else key
    for name in target_names(reg):
        names[reg["targets"][name]["id"]] = name
    names[reg["status_field"]["id"]] = reg["status_field"]["name"]
    names[reg["evidence_field"]["id"]] = reg["evidence_field"]["name"]
    return names


def flatten(value):
    """Selects come back as {id, name, color}; keep attachments (they carry a filename) as dicts."""
    if isinstance(value, dict):
        return value["name"] if "name" in value and "filename" not in value else value
    if isinstance(value, list):
        return [flatten(v) for v in value]
    return value


def load_snapshot(paths, reg):
    """Records from one or more saved list_records_for_table outputs, cells keyed by field NAME."""
    names = field_names(reg)
    records = []
    for path in paths:
        data = json.loads(Path(path).read_text())
        recs = data["records"] if isinstance(data, dict) and "records" in data else data
        for rec in recs:
            cells = {}
            raw = rec.get("cellValuesByFieldId")
            if raw is None:
                raw = rec.get("fields") or {}
            for key, value in raw.items():
                cells[names.get(key, key)] = flatten(value)
            records.append({"record_id": rec.get("id"), "cells": cells})
    return records


def is_blank(field, value):
    if value in (None, "", [], {}):
        return True
    return field == "Tone depth" and value == 0  # an unset rating reads as 0


def manifest(rec, reg):
    """One entry per attachment across the three image fields. `_url` is stripped before writing."""
    out = []
    for key, meta in reg["image_fields"].items():
        if key.startswith("_"):
            continue
        for att in rec["cells"].get(meta["name"]) or []:
            if not isinstance(att, dict):
                continue
            out.append({
                "field": meta["kind"],
                "field_name": meta["name"],
                "attachment_id": att.get("id"),
                "filename": att.get("filename"),
                "type": att.get("type"),
                "size": att.get("size"),
                "width": att.get("width"),
                "height": att.get("height"),
                "path": None,
                "read_path": None,
                "status": "not_downloaded",
                "_url": att.get("url"),
            })
    return out


def candidate_from(rec, reg, sku_filter=None):
    """(candidate, None) when the record is eligible, else (None, exclusion reason)."""
    cells = rec["cells"]
    sku = (cells.get("SKU") or "").strip()
    if sku_filter is not None and sku not in sku_filter:
        return None, "not_in_sku_filter"
    if not sku:
        return None, "sku_missing"
    if not cells.get("Active"):
        return None, "inactive"
    if cells.get("Category") not in reg["eligible_categories"]:
        return None, "category"
    status = cells.get(reg["status_field"]["name"])
    if status == reg["status_field"]["never_touch"]:
        return None, "staff_confirmed"
    blank_fields = [t for t in target_names(reg) if is_blank(t, cells.get(t))]
    if not blank_fields:
        return None, "nothing_blank"
    images = manifest(rec, reg)
    if not images and not any(cells.get(k) for k in SIGNAL_KEYS):
        return None, "no_signal"
    return {
        "record_id": rec["record_id"],
        "sku": sku,
        "product_name": cells.get("Product name") or "",
        "supplier": cells.get("Supplier") or "",
        "category": cells.get("Category"),
        "status": status,
        "evidence_existing": cells.get(reg["evidence_field"]["name"]) or "",
        "specs": {k: cells.get(k) for k in SPEC_KEYS},
        "blank_fields": blank_fields,
        "images": images,
    }, None


def classify_fetch_error(exc):
    text = str(exc)
    if "403" in text or "Tunnel connection failed" in text:
        return "host_blocked"
    return "failed"


def fetch(url, timeout=120):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def make_read_copy(path, read_path):
    """A <= READ_LONG_EDGE JPEG for the model. (read_path, None) or (None, status)."""
    try:
        from PIL import Image
    except ImportError:
        return None, "pillow_unavailable"
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = READ_LONG_EDGE / max(w, h)
            if scale < 1:
                im = im.resize((round(w * scale), round(h * scale)))
            im.save(read_path, "JPEG", quality=90)
        return str(read_path), None
    except Exception as exc:  # HEIC and anything Pillow cannot decode land here
        return None, f"unsupported_format: {exc.__class__.__name__}"


def download_all(candidates, images_dir, fetcher=fetch):
    """Fetch every original into images_dir. Returns per-status counts. Never raises on a
    single failure: a blocked host marks every image host_blocked and the pull carries on."""
    counts = Counter()
    for cand in candidates:
        for img in cand["images"]:
            url = img.get("_url")
            if not url or not img.get("attachment_id"):
                img["status"] = "no_url"
                counts["no_url"] += 1
                continue
            folder = Path(images_dir) / cand["sku"] / img["field"]
            folder.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", img.get("filename") or "image")
            path = folder / f"{img['attachment_id']}-{safe_name}"
            try:
                data = fetcher(url)
            except Exception as exc:
                img["status"] = classify_fetch_error(exc)
                img["error"] = str(exc)[:200]
                counts[img["status"]] += 1
                continue
            path.write_bytes(data)
            img["path"] = str(path)
            read_path, problem = make_read_copy(path, folder / f"{img['attachment_id']}-read.jpg")
            if read_path:
                img["read_path"] = read_path
                img["status"] = "downloaded"
            elif problem == "pillow_unavailable":
                img["read_path"] = str(path)  # the original is still readable for common types
                img["status"] = "downloaded"
            else:
                img["status"] = "unsupported_format"
                img["error"] = problem
            counts[img["status"]] += 1
    return counts


def images_status(candidates, requested, counts):
    total = sum(len(c["images"]) for c in candidates)
    if total == 0:
        return "none"
    if not requested:
        return "not_requested"
    if counts.get("host_blocked", 0) and counts.get("host_blocked", 0) == sum(counts.values()):
        return "host_blocked"
    if counts.get("downloaded", 0) == total:
        return "downloaded"
    return "partial"


def build(records, reg, scope, snapshot_paths, sku_filter=None, download=False,
          images_dir=None, fetcher=fetch, supplier=None):
    candidates, excluded = [], Counter()
    for rec in records:
        cand, why = candidate_from(rec, reg, sku_filter)
        if cand:
            candidates.append(cand)
        else:
            excluded[why] += 1
    counts = Counter()
    if download:
        counts = download_all(candidates, images_dir, fetcher)
    status = images_status(candidates, download, counts)
    blank_by_field = Counter(f for c in candidates for f in c["blank_fields"])
    for cand in candidates:
        for img in cand["images"]:
            img.pop("_url", None)  # signed and short-lived; never persisted
    supplier = supplier or next((c["supplier"] for c in candidates if c["supplier"]), "")
    return {
        "contract_version": CONTRACT_VERSION,
        "scope": scope,
        "supplier": supplier,
        "pulled_at": datetime.now(TZ).isoformat(),
        "registry": "platform-settings/style-tags.json",
        "inputs": [{"file": str(p)} for p in snapshot_paths],
        "images": {"status": status, "counts": dict(counts),
                   "dir": str(images_dir) if images_dir else None},
        "summary": {"records_in": len(records), "candidates": len(candidates),
                    "with_images": sum(1 for c in candidates if c["images"]),
                    "blank_by_field": dict(blank_by_field), "excluded": dict(excluded)},
        "candidates": candidates,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", action="append", required=True, type=Path,
                    help="Saved list_records_for_table output. Repeatable")
    ap.add_argument("--scope", required=True, help="Scope slug, e.g. faw; names every output")
    ap.add_argument("--supplier", help="Airtable Supplier value; default read from the records")
    ap.add_argument("--sku", help="Comma-separated SKUs to restrict the run to")
    ap.add_argument("--download", action="store_true", help="Fetch image originals to --images-dir")
    ap.add_argument("--images-dir", type=Path,
                    help="Default ingest/<today>/style-images (gitignored)")
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    ap.add_argument("--out", type=Path, help="Default ingest/<today>/style-candidates-<scope>.json")
    args = ap.parse_args(argv)

    reg = load_registry(args.registry)
    records = load_snapshot(args.snapshot, reg)
    if not records:
        print("error: the snapshot holds no records", file=sys.stderr)
        return 2
    sku_filter = {s.strip() for s in args.sku.split(",") if s.strip()} if args.sku else None
    images_dir = args.images_dir or (REPO_ROOT / "ingest" / today() / reg["outputs"]["images_dir"])
    out = build(records, reg, slugify(args.scope), args.snapshot, sku_filter, args.download,
                images_dir, supplier=args.supplier)
    path = args.out or (REPO_ROOT / "ingest" / today() /
                        reg["outputs"]["candidates"].format(scope=slugify(args.scope)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")

    s = out["summary"]
    print(path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path)
    print(f"  records in   {s['records_in']}")
    print(f"  candidates   {s['candidates']}   (with images: {s['with_images']})")
    for field, n in sorted(s["blank_by_field"].items()):
        print(f"    blank {field:12} {n}")
    for why, n in sorted(s["excluded"].items()):
        print(f"  excluded {why:18} {n}")
    print(f"  images       {out['images']['status']} {out['images']['counts'] or ''}")
    if out["images"]["status"] == "host_blocked":
        print("\n  The image host refused every download (proxy CONNECT 403). The plan will hold the\n"
              "  colour tags as image_host_blocked; spec tags still proceed. Allow the host in the\n"
              "  environment's Network access, or run this step on Albert's Mac.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
