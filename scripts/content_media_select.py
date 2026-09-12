#!/usr/bin/env python3
"""Choose the postable asset from a content folder listing — and refuse when unclear.

This is the *decision* half of media resolution. It does no I/O against any
platform: it takes a folder listing as JSON and returns a choice or a refusal.

WHY IT IS SHAPED THIS WAY. The predecessor (content_media_resolve.py, Graph) both
fetched and decided, because an Entra app-only token let it. Google Drive has no
equivalent here: this repo holds no Google credential, and a service account would
not see Albert's personal My Drive without per-file sharing anyway. Fetching
therefore happens through the Drive MCP connector, which is user-delegated and held
by `/content-schedule` and `content-ingest-agent`.

Splitting fetch from decide turned out to be worth doing on its own merits. The
refusals below are the part that matters -- they are what stops the wrong clip going
out to a live feed -- and as a pure function they are unit-testable with no network,
no credential and no fixture server. See tests/test_content_media_select.py.

    <listing json> | python3 scripts/content_media_select.py --mode find-final
    <listing json> | python3 scripts/content_media_select.py --mode select-media

The caller supplies the listing. Both modes read stdin (or --listing FILE) and print
JSON. Exit 0 = a choice; exit 2 = a refusal, with the reason on stderr and as JSON on
stdout so a caller can log it verbatim; exit 1 = bad input.

Folder layout it understands (see platform-settings/content-sources.json):

    TC-170_QA What Is the Most Scratch Resistant Flooring/
        01_RAW/  02_EDIT/  03_FINAL/  04_PUBLISHED/
                           ^^^^^^^^ the only directory this pipeline reads
"""

import argparse
import json
import re
import sys
from pathlib import Path

FINAL_DIR = "03_FINAL"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
COVER_TOKENS = ("cover", "thumb", "thumbnail")

# Metricool accepts jpg/jpeg/png for a cover and nothing else. A .heic or .webp
# cover is not a smaller problem than a missing one -- sending it rejects the whole
# post -- so it is never silently chosen.
COVER_EXT = {".jpg", ".jpeg", ".png"}

FOLDER_MIME = "application/vnd.google-apps.folder"


class Refusal(Exception):
    """Not an error. A deliberate stop, carrying a reason and the fix."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def notion_id_from(name: str) -> int | None:
    """Pull the Notion id out of a folder name, whatever prefix it carries.

    Matches TC-170_x, TFC-170_x and TFC170_x alike: during the migration all three
    exist at once. Deliberately keys on the integer, never the prefix -- the prefix
    is decoration and it is changing.
    """
    m = re.match(r"^[A-Za-z]+[-_]?(\d+)(?:[_\s-]|$)", name.strip())
    return int(m.group(1)) if m else None


def classify(name: str) -> str | None:
    ext = Path(name).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    return None


def normalize(listing) -> list[dict]:
    """Accept what the Drive MCP returns, or a plain list, without fuss."""
    if isinstance(listing, dict):
        listing = listing.get("files", listing.get("value", []))
    out = []
    for e in listing:
        name = e.get("title") or e.get("name") or ""
        if not name:
            continue
        out.append({
            "id": e.get("id") or e.get("fileId") or "",
            "name": name,
            "mime_type": e.get("mimeType") or e.get("mime_type") or "",
            "size": e.get("size"),
            "is_folder": (e.get("mimeType") or e.get("mime_type") or "") == FOLDER_MIME
                         or bool(e.get("folder")),
        })
    return out


def find_final(entries: list[dict]) -> dict:
    """Given the content folder's children, locate 03_FINAL."""
    folders = [e for e in entries if e["is_folder"]]
    match = [e for e in folders if e["name"].strip().upper() == FINAL_DIR]
    if not match:
        names = ", ".join(sorted(e["name"] for e in folders)) or "nothing"
        raise Refusal(
            "no_final_dir",
            f"no {FINAL_DIR}/ in this folder (has: {names}). The asset is not exported "
            "yet, or this row nests its content in a TC-<n>_<name> subfolder -- resolve "
            "that subfolder instead.")
    if len(match) > 1:
        raise Refusal("ambiguous_final_dir",
                      f"{len(match)} folders named {FINAL_DIR} -- resolve by hand.")
    return {"final_dir_id": match[0]["id"], "final_dir_name": match[0]["name"]}


def select_media(entries: list[dict]) -> dict:
    """Given 03_FINAL's children, choose the asset and any cover.

    Refuses rather than guesses. Which clip goes out is a person's decision, and this
    one is irreversible once posted.
    """
    files = [e for e in entries if not e["is_folder"]]
    if not files:
        raise Refusal("empty_final_dir",
                      f"{FINAL_DIR}/ is empty -- nothing has been exported. The Notion "
                      "row should not be 'Ready To Post'.")

    videos = [e for e in files if classify(e["name"]) == "video"]
    images = [e for e in files if classify(e["name"]) == "image"]
    unknown = [e for e in files if classify(e["name"]) is None]

    if len(videos) > 1:
        names = ", ".join(sorted(e["name"] for e in videos))
        raise Refusal("multiple_videos",
                      f"{len(videos)} videos in {FINAL_DIR}/ ({names}). Which one posts "
                      "is a human decision -- this never guesses. Leave one, or split "
                      "the Notion row.")

    if videos:
        media = videos[0]
    elif len(images) == 1:
        media = images[0]
    elif len(images) > 1:
        names = ", ".join(sorted(e["name"] for e in images))
        raise Refusal("multiple_images_no_video",
                      f"{len(images)} images and no video ({names}) -- a carousel's order "
                      "is a human decision. Resolve by hand.")
    else:
        raise Refusal("no_postable_asset",
                      f"no video or image in {FINAL_DIR}/ ({len(unknown)} other file(s)).")

    cover, warnings = _pick_cover(images, media)
    if unknown:
        warnings.append(f"{len(unknown)} unrecognised file(s) ignored: "
                        + ", ".join(sorted(e['name'] for e in unknown)))

    return {"media": media, "cover": cover, "warnings": warnings}


def _pick_cover(images: list[dict], media: dict) -> tuple[dict | None, list[str]]:
    """A cover is an image in 03_FINAL that is not the media itself.

    Ambiguity here yields NO cover plus a warning, never a guess: an unintended cover
    is worse than none, and on some surfaces sending a bad one rejects the whole post.
    """
    warnings: list[str] = []
    pool = [e for e in images if e["id"] != media["id"]]
    if not pool:
        return None, warnings

    usable = [e for e in pool if Path(e["name"]).suffix.lower() in COVER_EXT]
    rejected = [e for e in pool if e not in usable]
    if rejected:
        warnings.append(
            "ignored as cover (Metricool accepts jpg/jpeg/png only): "
            + ", ".join(sorted(e["name"] for e in rejected)))
    if not usable:
        return None, warnings

    named = [e for e in usable if any(t in e["name"].lower() for t in COVER_TOKENS)]
    if len(named) == 1:
        return named[0], warnings
    if len(named) > 1:
        warnings.append(f"{len(named)} images named cover/thumb -- none chosen, set one by hand")
        return None, warnings
    if len(usable) == 1:
        return usable[0], warnings
    warnings.append(f"{len(usable)} candidate cover images and none named "
                    f"{'/'.join(COVER_TOKENS)} -- none chosen, set one by hand")
    return None, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=("find-final", "select-media"))
    ap.add_argument("--listing", type=Path, help="JSON file; default stdin")
    args = ap.parse_args()

    try:
        raw = args.listing.read_text() if args.listing else sys.stdin.read()
        entries = normalize(json.loads(raw))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"bad listing input: {exc}", file=sys.stderr)
        return 1

    try:
        result = find_final(entries) if args.mode == "find-final" else select_media(entries)
    except Refusal as r:
        print(json.dumps({"refused": True, "reason": r.reason, "detail": r.detail}, indent=2))
        print(f"refused ({r.reason}): {r.detail}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
