#!/usr/bin/env python3
"""Fetch a supplier price list from its Notion-held SharePoint share link.

The Notion "Price Lists" database holds an anonymous SharePoint share link for
every price list Titan has received. Those links look downloadable but are not:
a plain GET returns OneDrive viewer HTML, and following redirects without a
cookie jar returns 403. See methods/pricelist-extraction.md for why.

This wraps the one call shape that works, so nobody re-derives it.

    python3 scripts/pricelist_fetch.py "<share-link>" out.pdf
    python3 scripts/pricelist_fetch.py "<share-link>" out.pdf --text

Read-only against SharePoint. Writes only the output file.
"""

import argparse
import subprocess
import sys
from pathlib import Path

PDF_MAGIC = b"%PDF-"


def fetch(share_link: str, dest: Path, timeout: int = 120) -> Path:
    """Download a SharePoint share link to dest, returning the path.

    Two non-obvious requirements, both mandatory:
      * ?download=1  — without it SharePoint serves the viewer page, not the file.
      * a cookie jar — the redirect chain sets a FedAuth cookie that the final
        hop requires; plain `curl -L` drops it and gets 403.
    """
    dest = Path(dest)
    jar = dest.with_suffix(dest.suffix + ".cookies")
    sep = "&" if "?" in share_link else "?"
    url = f"{share_link}{sep}download=1"

    try:
        subprocess.run(
            ["curl", "-sSL", "-c", str(jar), "-b", str(jar),
             "--max-time", str(timeout), "-o", str(dest), url],
            check=True,
        )
    finally:
        jar.unlink(missing_ok=True)

    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"download produced no bytes: {dest}")

    head = dest.read_bytes()[:2048]
    if head.lstrip().startswith((b"<!DOCTYPE", b"<html")):
        raise RuntimeError(
            f"got HTML, not a file ({dest.stat().st_size} bytes) — the share link "
            "likely lost its ?download=1, or the link has expired/been revoked"
        )
    if head.startswith(b"403") or b"FORBIDDEN" in head[:64].upper():
        raise RuntimeError("403 from SharePoint — cookie jar was not honoured")

    return dest


def page_text(pdf_path: Path) -> list[str]:
    """Extract per-page text with pdfplumber. Empty pages come back as ''."""
    import pdfplumber  # imported lazily so fetching works without it installed

    with pdfplumber.open(pdf_path) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("share_link", help="SharePoint share link from the Notion row")
    ap.add_argument("dest", type=Path, help="where to write the file")
    ap.add_argument("--text", action="store_true",
                    help="also print pdfplumber per-page text (PDF only)")
    args = ap.parse_args()

    try:
        path = fetch(args.share_link, args.dest)
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1

    is_pdf = path.read_bytes()[:5] == PDF_MAGIC
    kind = "PDF" if is_pdf else "non-PDF (check the file type before parsing)"
    print(f"{path} — {path.stat().st_size} bytes, {kind}")

    if args.text:
        if not is_pdf:
            print("--text only applies to PDFs", file=sys.stderr)
            return 1
        for i, text in enumerate(page_text(path), start=1):
            print(f"\n===== page {i} =====\n{text}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
