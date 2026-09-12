#!/usr/bin/env python3
"""Read-only crawl of titanfloors.ca's public WordPress REST API.

Produces the inventory and redirect-map seed that methods/website-architecture.md's
migration plan depends on. GET-only, public endpoints only — no WordPress credential
of any kind, because Application Passwords are unscopable and this script has no
business holding write access to anything. See methods/website-inventory.md for the
rules this script implements (what counts as a real page, redirect precedence, the
Search Console join).

Endpoints used (all public, no auth):
    /wp-json/wp/v2/pages        (status=publish, paginated)
    /wp-json/wp/v2/posts        (status=publish, paginated)
    /wp-json/wp/v2/media        (paginated, for the alt-text audit)
    /wp-json/wp/v2/categories   (blog categories)
    /wp-json/wp/v2/product_cat  (WooCommerce categories, if the endpoint is public)
    /wp-json/wc/store/v1/products  (WooCommerce Store API — public, no key needed)

Usage:
    python3 analysis/website_inventory.py [--refresh] [--gsc PATH]

Raw pulls cache under analysis/cache/website/ (gitignored, regenerable with --refresh).
Derived output lands in analysis/output/ and is committed.
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

BASE = "https://titanfloors.ca/wp-json"
ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache" / "website"
OUT = ROOT / "output"

TODAY = time.strftime("%Y-%m-%d")

# Old theme-demo pages left over from the site's original template, never real content.
DEMO_PAGE_SLUGS = {
    "furniture-04-2", "our-product", "wishlist1", "landing-page", "wishlist",
    "my-account-2", "cart-2", "checkout-2", "faq-2", "my-account-2-2", "my-account",
    "checkout", "cart", "columns", "blog-columns", "services-2", "call-to-action",
}

# A URL that is plainly a typo of the intended one — see methods/website-inventory.md,
# "Slug-typo rule". Mapping is old-slug-fragment -> corrected-slug-fragment.
SLUG_TYPO_FIXES = {
    "lamiante-flooring-mississauga": "laminate-flooring-mississauga",
    "vinyl_flooring_oakville": "vinyl-flooring-oakville",
}
# This one is a wrong-parent defect, not a spelling typo: it lives under
# /stair-refinishing/ but serves vinyl-flooring content that belongs under
# /flooring-install/.
WRONG_PARENT = {
    "stair-refinishing/vinyl-flooring-hamilton": "flooring-install/vinyl-flooring-hamilton",
}


def _get(path, params=None, retries=3):
    """GET a public REST endpoint. No auth header, ever — see the module docstring."""
    url = f"{BASE}{path}"
    if params:
        url += "?" + urlencode(params)
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": "titan-website-inventory/1"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 400 and "rest_post_invalid_page_number" in e.read().decode("utf-8", "ignore"):
                return []
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    return []


def paginate(path, params, per_page=100):
    """Walk every page of a WP REST collection until an empty/short page ends it."""
    page = 1
    out = []
    while True:
        batch = _get(path, {**params, "per_page": per_page, "page": page})
        if not batch:
            break
        out.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return out


def load_cache(name):
    f = CACHE / f"{name}.json"
    if f.exists():
        return json.loads(f.read_text())
    return None


def save_cache(name, data):
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{name}.json").write_text(json.dumps(data, indent=2))


def crawl(refresh):
    """Pull (or reuse cached) pages, posts, products, media, categories."""
    parts = {}
    for name, path, params in [
        ("pages", "/wp/v2/pages", {"status": "publish",
            "_fields": "id,link,title,date,parent,slug"}),
        ("posts", "/wp/v2/posts", {"status": "publish",
            "_fields": "id,link,title,date,categories,slug"}),
        ("media", "/wp/v2/media", {"_fields": "id,source_url,alt_text,mime_type"}),
        ("categories", "/wp/v2/categories", {"_fields": "id,name,slug,count"}),
        ("product_categories", "/wp/v2/product_cat", {"_fields": "id,name,slug,count,parent"}),
    ]:
        cached = None if refresh else load_cache(name)
        if cached is not None:
            parts[name] = cached
            continue
        data = paginate(path, params)
        parts[name] = data
        save_cache(name, data)

    cached = None if refresh else load_cache("products")
    if cached is not None:
        parts["products"] = cached
    else:
        products, page = [], 1
        while True:
            batch = _get("/wc/store/v1/products", {"per_page": 100, "page": page,
                "_fields": "id,slug,sku,name,permalink,categories,images"})
            if not batch:
                break
            products.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        parts["products"] = products
        save_cache("products", products)

    return parts


def classify_redirect(old_path):
    """Apply the precedence order in methods/website-inventory.md."""
    slug = old_path.strip("/")
    for bad, good in SLUG_TYPO_FIXES.items():
        if bad in slug:
            return slug.replace(bad, good), "slug_typo_fix"
    for bad, good in WRONG_PARENT.items():
        if slug == bad:
            return good, "wrong_parent_fix"
    if slug.startswith("product-category/"):
        return f"catalogue/category/{slug.split('/', 1)[1]}", "woo_category_to_catalogue"
    if slug.startswith("product/"):
        return "catalogue/", "woo_product_to_catalogue_root"
    last_seg = slug.split("/")[-1]
    if last_seg in DEMO_PAGE_SLUGS or slug in DEMO_PAGE_SLUGS:
        return "", "demo_page_to_home"
    return None, "needs_manual_call"


def load_gsc(path):
    """Optional Search Console page-performance export. See methods/website-inventory.md."""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        print(f"warning: --gsc file not found: {p}", file=sys.stderr)
        return {}
    clicks_by_url = {}
    with p.open(newline="") as f:
        for row in csv.DictReader(f):
            url = row.get("Page") or row.get("page") or ""
            clicks = row.get("Clicks") or row.get("clicks") or "0"
            try:
                clicks_by_url[url] = int(clicks)
            except ValueError:
                pass
    return clicks_by_url


def build_inventory(parts, gsc_clicks):
    return {
        "generated": TODAY,
        "source": "public WP REST API (no credential) — see methods/website-inventory.md",
        "counts": {
            "pages_published": len(parts["pages"]),
            "posts_published": len(parts["posts"]),
            "woocommerce_products": len(parts["products"]),
            "media_items": len(parts["media"]),
        },
        "pages": parts["pages"],
        "posts": parts["posts"],
        "products": parts["products"],
        "media_alt_text_audit": {
            "missing_alt_text": sum(1 for m in parts["media"] if not m.get("alt_text")),
            "total": len(parts["media"]),
        },
        "categories": parts["categories"],
        "product_categories": parts["product_categories"],
        "gsc_join": "loaded" if gsc_clicks else "not loaded — every page defaults to keep",
    }


def build_redirects(parts, gsc_clicks):
    rows = []
    for p in parts["pages"] + parts["posts"]:
        link = p.get("link", "")
        old_path = re.sub(r"^https?://[^/]+", "", link)
        target, rule = classify_redirect(old_path)
        clicks = gsc_clicks.get(link)
        disposition = "keep" if (clicks is None or clicks > 0) else "consolidate_candidate"
        rows.append({
            "old_url": link,
            "rule": rule,
            "proposed_target": target if target is not None else "",
            "gsc_clicks": clicks if clicks is not None else "",
            "disposition": disposition,
        })
    for cat in parts["product_categories"]:
        rows.append({
            "old_url": f"/product-category/{cat['slug']}/",
            "rule": "woo_category_to_catalogue",
            "proposed_target": f"/catalogue/category/{cat['slug']}",
            "gsc_clicks": "",
            "disposition": "keep",
        })
    for prod in parts["products"]:
        rows.append({
            "old_url": prod.get("permalink", ""),
            "rule": "woo_product_to_catalogue_root",
            "proposed_target": "/catalogue/",
            "gsc_clicks": "",
            "disposition": "keep",
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="ignore the cache, re-pull everything")
    ap.add_argument("--gsc", help="path to a Search Console page-performance CSV export")
    args = ap.parse_args()

    parts = crawl(args.refresh)
    gsc_clicks = load_gsc(args.gsc)

    OUT.mkdir(parents=True, exist_ok=True)
    inventory = build_inventory(parts, gsc_clicks)
    (OUT / f"website-inventory-{TODAY}.json").write_text(json.dumps(inventory, indent=2))

    redirects = build_redirects(parts, gsc_clicks)
    with (OUT / f"website-redirects-{TODAY}.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "old_url", "rule", "proposed_target", "gsc_clicks", "disposition"])
        writer.writeheader()
        writer.writerows(redirects)

    print(f"pages={inventory['counts']['pages_published']} "
          f"posts={inventory['counts']['posts_published']} "
          f"products={inventory['counts']['woocommerce_products']} "
          f"redirect_rows={len(redirects)}")


if __name__ == "__main__":
    main()
