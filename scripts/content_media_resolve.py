#!/usr/bin/env python3
"""Resolve a Notion 'Link to Files' folder link to the postable media file.

The Titan Content Ideas rows do NOT link to a file. Every 'Link to Files' value
is a SharePoint *folder* share link -- note the ':f:' segment:

    https://flooruca-my.sharepoint.com/:f:/g/personal/albert_titanfloors_ca/Ig...
                                       ^^^  f = folder (b = file, v = video, i = image)

Behind it is Albert's standard per-content scaffold, keyed on the Notion row's
auto-increment ID (Notion ID 170 -> folder 'TFC-170_...'):

    TFC-170_QA What Is the Most Scratch Resistant Flooring/
        01_RAW/          raw camera files
        02_EDIT/         project files, mid-edit
        03_FINAL/        <- the finished, postable asset lives here
        04_PUBLISHED/    post-publish archive
        (04_PHOTOS/, and nested TFC-<n>_<name>/ sub-content on some rows)

So resolving a row to something postable is: folder -> 03_FINAL -> the media file.
This module is the only place that walks that convention, so nobody re-derives it.

    python3 scripts/content_media_resolve.py "<folder-share-link>"
    python3 scripts/content_media_resolve.py "<folder-share-link>" --json

Read-only against SharePoint. Writes nothing.

NETWORK REQUIREMENT (2026-09-12): this needs BOTH
  * login.microsoftonline.com  (to mint the token)
  * graph.microsoft.com        (to read)
The cloud/VM session's network policy currently blocks login.microsoftonline.com
(CONNECT answered 403) while allowing graph.microsoft.com, so this script cannot
run unattended there until that host is allowed. It runs fine on Albert's Mac.

WHY NOT REUSE scripts/pricelist_fetch.py: that fetches a *file* share link with
curl + a cookie jar, because SharePoint's viewer redirect needs FedAuth. That
approach cannot enumerate a folder, and its cookie requirement is exactly why a
share link cannot be handed to a third party (Metricool) as a media URL -- the
third party has no cookie jar and gets 403. Graph's @microsoft.graph.downloadUrl
is pre-authenticated and needs no header or cookie, which is why we use it here.
Its one catch is a short life (~1h): see FINAL_DIR notes in the module docstring
of the consuming command before scheduling far in advance.
"""

import argparse
import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

GRAPH = "https://graph.microsoft.com/v1.0"
FINAL_DIR = "03_FINAL"
PUBLISHED_DIR = "04_PUBLISHED"

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
# Albert names covers with one of these tokens; anything else in 03_FINAL that is
# an image is treated as a candidate cover only if exactly one exists.
COVER_TOKENS = ("cover", "thumb", "thumbnail")


class ResolveError(RuntimeError):
    """Raised with a message that names the fix, not just the failure."""


def load_env(path: str = ".env") -> dict:
    """Read .env. Per CLAUDE.md a credential must come from .env, not the shell."""
    out = {}
    p = Path(path)
    if not p.exists():
        raise ResolveError(f"{path} not found -- see .env.example for required keys")
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def get_token(env: dict) -> str:
    missing = [k for k in ("GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET", "GRAPH_TENANT_ID")
               if not env.get(k)]
    if missing:
        raise ResolveError(f"missing from .env: {', '.join(missing)}")

    body = urllib.parse.urlencode({
        "client_id": env["GRAPH_CLIENT_ID"],
        "client_secret": env["GRAPH_CLIENT_SECRET"],
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode()
    url = f"https://login.microsoftonline.com/{env['GRAPH_TENANT_ID']}/oauth2/v2.0/token"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body), timeout=30) as r:
            return json.load(r)["access_token"]
    except urllib.error.URLError as exc:
        raise ResolveError(
            f"could not reach login.microsoftonline.com ({exc}). If this is a cloud "
            "session, that host is blocked by the environment's network policy -- "
            "allow it, or run this on Albert's Mac."
        ) from exc


def share_id(share_url: str) -> str:
    """Graph's sharing-URL encoding: 'u!' + unpadded base64url of the URL."""
    return "u!" + base64.urlsafe_b64encode(share_url.encode()).decode().rstrip("=")


def graph_get(path: str, token: str) -> dict:
    req = urllib.request.Request(f"{GRAPH}{path}",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise ResolveError(f"Graph {exc.code} on {path}: {detail}") from exc


def _kids(drive_id: str, item_id: str, token: str) -> list[dict]:
    return graph_get(f"/drives/{drive_id}/items/{item_id}/children", token).get("value", [])


def classify(name: str) -> str | None:
    ext = Path(name).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    return None


def resolve(share_url: str, token: str) -> dict:
    sid = share_id(share_url)
    root = graph_get(f"/shares/{sid}/driveItem", token)

    if not root.get("folder"):
        raise ResolveError(
            f"'{root.get('name')}' is a file, not a folder. Every Titan 'Link to Files' "
            "value is expected to be a folder share link (':f:' in the URL). Either this "
            "row is shaped differently, or the link points straight at an asset -- "
            "handle it by hand and note the row."
        )

    drive_id = root["parentReference"]["driveId"]
    top = _kids(drive_id, root["id"], token)
    by_name = {c["name"].strip().upper(): c for c in top}

    final = by_name.get(FINAL_DIR)
    if final is None:
        subs = sorted(c["name"] for c in top if c.get("folder"))
        raise ResolveError(
            f"no {FINAL_DIR}/ under '{root['name']}' (has: {', '.join(subs) or 'nothing'}). "
            "The asset is not finished, or this row nests its content in a TFC-<n>_<name> "
            "subfolder -- resolve that subfolder's link instead."
        )

    entries = [c for c in _kids(drive_id, final["id"], token) if c.get("file")]
    if not entries:
        raise ResolveError(
            f"{FINAL_DIR}/ is empty under '{root['name']}' -- nothing has been exported "
            "yet. The Notion row should not be 'Ready To Post'."
        )

    videos = [c for c in entries if classify(c["name"]) == "video"]
    images = [c for c in entries if classify(c["name"]) == "image"]
    unknown = [c for c in entries if classify(c["name"]) is None]

    if len(videos) > 1:
        names = ", ".join(sorted(c["name"] for c in videos))
        raise ResolveError(
            f"{len(videos)} videos in {FINAL_DIR}/ ({names}). Which one posts is a "
            "human decision -- this never guesses. Leave one video in 03_FINAL, or "
            "split the row."
        )

    media = videos[0] if videos else (images[0] if len(images) == 1 else None)
    if media is None:
        raise ResolveError(
            f"no single postable asset in {FINAL_DIR}/ "
            f"({len(images)} images, {len(unknown)} other files) -- resolve by hand."
        )

    # A cover is an image that is NOT the media itself, preferring an explicit name.
    cover_pool = [c for c in images if c["id"] != media["id"]]
    named = [c for c in cover_pool
             if any(t in c["name"].lower() for t in COVER_TOKENS)]
    cover = named[0] if len(named) == 1 else (cover_pool[0] if len(cover_pool) == 1 else None)

    published = by_name.get(PUBLISHED_DIR)

    return {
        "folder_name": root["name"],
        "drive_id": drive_id,
        "media": _describe(media),
        "cover": _describe(cover) if cover else None,
        "published_dir_id": published["id"] if published else None,
        "warnings": _warnings(videos, images, unknown, cover_pool, cover),
    }


def _describe(item: dict) -> dict:
    return {
        "name": item["name"],
        "item_id": item["id"],
        "size_bytes": item.get("size"),
        "size_mb": round(item.get("size", 0) / 1048576, 1),
        "mime_type": (item.get("file") or {}).get("mimeType"),
        "kind": classify(item["name"]),
        # Pre-authenticated and short-lived (~1h). No auth header, no cookie.
        "download_url": item.get("@microsoft.graph.downloadUrl"),
    }


def _warnings(videos, images, unknown, cover_pool, cover) -> list[str]:
    w = []
    if unknown:
        w.append(f"{len(unknown)} unrecognised file(s) in {FINAL_DIR}/ ignored: "
                 + ", ".join(sorted(c["name"] for c in unknown)))
    if len(cover_pool) > 1 and cover is None:
        w.append(f"{len(cover_pool)} candidate cover images and none named "
                 f"{'/'.join(COVER_TOKENS)} -- no cover chosen, set one by hand")
    if videos and images and cover is None and len(images) == 1:
        w.append("one image alongside the video but it was not treated as a cover")
    return w


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("share_link", help="the row's 'Link to Files' folder share URL")
    ap.add_argument("--json", action="store_true", help="emit JSON for a caller")
    ap.add_argument("--env", default=".env", help="path to .env (default: .env)")
    args = ap.parse_args()

    try:
        token = get_token(load_env(args.env))
        result = resolve(args.share_link, token)
    except ResolveError as exc:
        print(f"resolve failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    m = result["media"]
    print(f"folder : {result['folder_name']}")
    print(f"media  : {m['name']}  [{m['mime_type']}] {m['size_mb']}MB ({m['kind']})")
    c = result["cover"]
    print(f"cover  : {c['name']} ({c['size_mb']}MB)" if c else "cover  : none")
    print(f"dl url : {'resolved (expires ~1h)' if m['download_url'] else 'MISSING'}")
    for warn in result["warnings"]:
        print(f"warn   : {warn}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
