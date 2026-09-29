#!/usr/bin/env python3
"""Pull a supplier website's product pages and images for /image-fill. READ ONLY.

Lists the supplier's products from the site named in
platform-settings/supplier-sites.json, keeps each product's title, codes and
full-resolution image URLs, matches them to the saved Airtable snapshot
(scripts/image_match.py), and — with --download — fetches the images of the
pages that matched a record:

    ingest/YYYY-MM-DD/supplier-pages-<scope>.json
    ingest/YYYY-MM-DD/supplier-images/<scope>/<sha1>.<ext>   (+ <sha1>-read.jpg)

The images directory is gitignored. The pages file is the input to
scripts/image_fill_plan.py.

Listing methods, tried in order under `auto` (the first that yields products wins):
  shopify      /products.json            (title, handle, images with sizes, variant SKUs)
  woocommerce  /wp-json/wc/store/v1/products
  sitemap      robots.txt Sitemap: lines, sitemap indexes, <image:image> entries —
               a product sitemap's image titles map images to products without
               loading a single product page
  crawl        same-site pages from `site`, following links whose URL or anchor
               text holds one of `follow_words`

A site that answers with a bot challenge (Cloudflare `cf-mitigated: challenge`,
SiteGround `sg-captcha`) or a proxy refusal is reported as `challenged` /
`host_blocked` and the run stops for that source. It never tries to get past a
challenge: the site is saying no to automated readers.

This script holds no credentials and writes nothing to any platform.

Usage:
    python3 scripts/supplier_site_pull.py --supplier VIDAR --scope vidar \
        --snapshot ingest/<date>/vidar_image_snapshot.json [--download] [--max-pages N]
"""

import argparse
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import image_match  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "platform-settings" / "supplier-sites.json"
FIELDS = REPO_ROOT / "platform-settings" / "airtable-master-catalogue-fields.json"
TZ = ZoneInfo("America/Toronto")
CONTRACT_VERSION = "supplier-pages-1"
READ_LONG_EDGE = 1568
CODE_TOKEN = re.compile(r"\b[A-Z]{1,4}-?\d{2,5}[A-Z]?\b")


class Blocked(Exception):
    """The site refused automated reading (challenge) or the proxy refused the host."""

    def __init__(self, status, detail):
        super().__init__(f"{status}: {detail}")
        self.status = status


def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def load_registry(path=REGISTRY):
    return json.loads(Path(path).read_text())


# --------------------------------------------------------------------------- fetch

def classify(exc_or_headers, body=b""):
    text = str(exc_or_headers)
    low = text.lower()
    if "cf-mitigated" in low or "sg-captcha" in low or b"sgcaptcha" in body[:2000] \
            or b"challenges.cloudflare.com" in body[:6000]:
        return "challenged"
    if "tunnel connection failed" in low or "403" in text and "CONNECT" in text:
        return "host_blocked"
    return None


class Fetcher:
    def __init__(self, cfg, opener=None):
        f = cfg.get("fetch", {})
        self.ua = f.get("user_agent", "TitanFlooringCatalogueBot/1.0")
        self.delay = float(f.get("delay_seconds", 0.5))
        self.timeout = float(f.get("timeout_seconds", 30))
        self.opener = opener or urllib.request.urlopen
        self.count = 0

    def get(self, url):
        """Bytes, or raises Blocked / urllib errors."""
        if self.count:
            time.sleep(self.delay)
        self.count += 1
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept": "*/*"})
        try:
            with self.opener(req, timeout=self.timeout) as resp:
                body = resp.read()
                headers = str(getattr(resp, "headers", ""))
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as exc:
            body = exc.read() if hasattr(exc, "read") else b""
            why = classify(f"{exc.headers} {exc}", body)
            if why:
                raise Blocked(why, url) from exc
            raise
        except urllib.error.URLError as exc:
            why = classify(exc)
            if why:
                raise Blocked(why, url) from exc
            raise
        why = classify(headers, body) if status in (202, 403, 503) or b"sgcaptcha" in body[:2000] else None
        if why:
            raise Blocked(why, url)
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        return body


# --------------------------------------------------------------------------- parse

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.h1, self._in = "", "", None
        self.meta, self.jsonld, self.images, self.links = {}, [], [], []
        self._buf, self._a = [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("title", "h1") and not getattr(self, tag):
            self._in, self._buf = tag, []
        elif tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._in, self._buf = "jsonld", []
        elif tag == "meta":
            key = a.get("property") or a.get("name")
            if key and a.get("content"):
                self.meta.setdefault(key.lower(), a["content"])
        elif tag in ("img", "source"):
            src = a.get("data-src") or a.get("data-lazy-src") or a.get("src")
            best = best_from_srcset(a.get("data-srcset") or a.get("srcset"))
            url = best or src
            if url:
                self.images.append({"url": url, "alt": a.get("alt") or "",
                                    "width_hint": to_int(a.get("width"))})
        elif tag == "a" and a.get("href"):
            self._a = {"href": a["href"], "text": []}

    def handle_endtag(self, tag):
        if self._in == tag or (self._in == "jsonld" and tag == "script"):
            text = " ".join("".join(self._buf).split())
            if self._in == "jsonld":
                self.jsonld.append("".join(self._buf))
            else:
                setattr(self, self._in, text)
            self._in = None
        if tag == "a" and self._a:
            self.links.append({"href": self._a["href"], "text": " ".join("".join(self._a["text"]).split())})
            self._a = None

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)
        if self._a is not None:
            self._a["text"].append(data)


def to_int(v):
    try:
        return int(str(v).strip().rstrip("px"))
    except (TypeError, ValueError):
        return None


def best_from_srcset(srcset):
    if not srcset:
        return None
    best, best_w = None, -1
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = to_int(bits[1][:-1]) if len(bits) > 1 and bits[1].endswith("w") else 0
        if (w or 0) > best_w:
            best, best_w = bits[0], w or 0
    return best


def jsonld_products(blocks):
    out = []
    for raw in blocks:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if "@graph" in node:
                    stack.extend(node["@graph"])
                t = node.get("@type")
                if t == "Product" or (isinstance(t, list) and "Product" in t):
                    out.append(node)
            elif isinstance(node, list):
                stack.extend(node)
    return out


def page_from_html(url, html):
    p = PageParser()
    p.feed(html.decode("utf-8", "replace") if isinstance(html, bytes) else html)
    products = jsonld_products(p.jsonld)
    prod = products[0] if products else {}
    images = []
    for img in ([{"url": u} for u in as_list(prod.get("image"))]
                + ([{"url": p.meta["og:image"]}] if p.meta.get("og:image") else []) + p.images):
        u = img["url"]
        if isinstance(u, dict):
            u = u.get("url") or u.get("contentUrl")
        if not u:
            continue
        images.append({**img, "url": urllib.parse.urljoin(url, u)})
    codes = set(CODE_TOKEN.findall(f"{p.title} {p.h1}"))
    if prod.get("sku"):
        codes.add(str(prod["sku"]))
    return {
        "url": url,
        "title": p.title,
        "h1": p.h1,
        "og_title": p.meta.get("og:title", ""),
        "product_name": prod.get("name", "") if isinstance(prod.get("name"), str) else "",
        "is_product": bool(products) or p.meta.get("og:type", "").lower() == "product",
        "codes": sorted(codes),
        "images": dedupe_images(images),
        "_links": [{"href": urllib.parse.urljoin(url, l["href"]), "text": l["text"]} for l in p.links],
    }


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def dedupe_images(images):
    seen, out = set(), []
    for img in images:
        key = img["url"].split("?")[0]
        if key not in seen:
            seen.add(key)
            out.append(img)
    return out


def keep_image(url, rules):
    low = url.lower().split("?")[0]
    if any(low.endswith(ext) for ext in rules.get("skip_extensions", [])):
        return False
    if low.startswith("data:"):
        return False
    return not any(s in low for s in rules.get("skip_url_substrings", []))


# --------------------------------------------------------------------------- listing methods

def list_shopify(fetch, root, vendor=None):
    """Every product in a Shopify store's public products.json; `vendor` keeps one brand
    (Shopify's own brand field, e.g. `Vidar Design Flooring` at Speers)."""
    base = f"{urllib.parse.urlsplit(root).scheme}://{urllib.parse.urlsplit(root).netloc}"
    pages, n = [], 1
    while n <= 40:
        data = json.loads(fetch.get(f"{base}/products.json?limit=250&page={n}"))
        items = data.get("products") or []
        if not items:
            break
        for p in items:
            if vendor and (p.get("vendor") or "").strip().lower() != vendor.strip().lower():
                continue
            pages.append({
                "url": f"{base}/products/{p['handle']}", "title": p.get("title", ""), "h1": "",
                "og_title": "", "product_name": p.get("title", ""), "is_product": True,
                "codes": sorted({v["sku"] for v in p.get("variants", []) if v.get("sku")}),
                "images": [{"url": i["src"], "alt": i.get("alt") or "", "width_hint": i.get("width"),
                            "height_hint": i.get("height")} for i in p.get("images", [])],
            })
        n += 1
    return pages


def list_woocommerce(fetch, root):
    base = f"{urllib.parse.urlsplit(root).scheme}://{urllib.parse.urlsplit(root).netloc}"
    pages, n = [], 1
    while n <= 40:
        items = json.loads(fetch.get(f"{base}/wp-json/wc/store/v1/products?per_page=100&page={n}"))
        if not items:
            break
        for p in items:
            pages.append({
                "url": p.get("permalink", ""), "title": p.get("name", ""), "h1": "", "og_title": "",
                "product_name": p.get("name", ""), "is_product": True,
                "codes": [p["sku"]] if p.get("sku") else [],
                "images": [{"url": i["src"], "alt": i.get("alt") or ""} for i in p.get("images", [])],
            })
        n += 1
    return pages


SITEMAP_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)
URL_BLOCK = re.compile(r"<url>(.*?)</url>", re.I | re.S)
IMAGE_BLOCK = re.compile(r"<image:image>(.*?)</image:image>", re.I | re.S)
IMAGE_LOC = re.compile(r"<image:loc>\s*([^<]+?)\s*</image:loc>", re.I)
IMAGE_TITLE = re.compile(r"<image:(?:title|caption)>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</image:(?:title|caption)>", re.I | re.S)


def sitemap_roots(fetch, root):
    base = f"{urllib.parse.urlsplit(root).scheme}://{urllib.parse.urlsplit(root).netloc}"
    roots = []
    try:
        robots = fetch.get(f"{base}/robots.txt").decode("utf-8", "replace")
        roots = [l.split(":", 1)[1].strip() for l in robots.splitlines() if l.lower().startswith("sitemap:")]
    except Blocked:
        raise
    except Exception:
        pass
    return roots or [f"{base}/sitemap.xml"]


FRACTIONS = {"12": .5, "14": .25, "34": .75, "38": .375, "58": .625, "916": .5625}
GRADE_TOKENS = {"select", "character", "rustic", "premium", "prime", "cabin"}
UUID_V1 = re.compile(r"[0-9a-f]{8}-([0-9a-f]{4}-1[0-9a-f]{3})-[0-9a-f]{4}-[0-9a-f]{12}")
SLUG_CODE = re.compile(r"^[a-z]{1,4}\d{2,5}[a-z]?$")


def slug_title(slug):
    """A readable title from a slug-only sitemap entry (The Floor Box):
    `engineered-hardwood-american-oak-7-macaroon-select-better-7-12-34-2532-sqftbox`
      -> `Engineered Hardwood American Oak 7 Macaroon — Select & Better — 7.5"`.
    The width is the number right after the grade (a number earlier in the slug is a
    collection, `american-oak-7`); with no grade, the trailing run of numbers. A fraction
    token after the width adds to it (7-12-34 = 7 1/2" wide, 3/4" thick). Thickness is
    left out: the matcher would read `3/4"` as a width."""
    tokens = [t for t in slug.lower().split("-") if t]
    while tokens and tokens[-1] in ("sqft", "sqftbox", "box", "sf", "sqftcarton"):
        tokens.pop()
    grade, g_start, n = "", None, None
    for i in range(len(tokens) - 1, 0, -1):
        if tokens[i] in GRADE_TOKENS | {"better"} and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            n = i + 1
            if tokens[i - 1:i + 1] == ["select", "better"]:
                grade, g_start = "Select & Better", i - 1
                if tokens[i - 2:i] == ["select", "and"]:
                    g_start = i - 2
            elif tokens[i] == "better":
                continue
            else:
                grade, g_start = tokens[i].title(), i
            break
    if n is None:
        n = len(tokens)
        while n > 1 and tokens[n - 1].isdigit():
            n -= 1
        g_start = n
        if n == len(tokens):
            n = None
    words = tokens[:g_start] if g_start is not None else tokens
    width = None
    if n is not None:
        width = float(tokens[n])
        rest = tokens[n + 1:]
        if len(rest) >= 2 and rest[0] in FRACTIONS and rest[1] in FRACTIONS:
            width += FRACTIONS[rest[0]]
    name = " ".join(w.upper() if SLUG_CODE.match(w) else w.title() for w in words)
    parts = [name] + ([grade] if grade else []) + ([f'{width:g}"'] if width else [])
    return " — ".join(parts)


def slug_codes(slug):
    return sorted({t.upper() for t in slug.lower().split("-") if SLUG_CODE.match(t)})


def brand_batches(pages, colours, min_distinct):
    """Keep only pages from import batches that carry the supplier's colour names.

    A version-1 UUID's time field groups the products a site imported together; a batch
    holding at least `min_distinct` of the supplier's distinctive (multi-word) colour names
    is taken to be that supplier's. Returns (kept_pages, {batch: {"products", "colours"}})."""
    variants = {}
    for c in colours:
        low = c.lower().strip()
        if " " not in low:
            continue
        for v in (low.replace(" ", "-"), low.replace(" ", "")):
            variants[v] = low
    info, by_batch = {}, {}
    for p in pages:
        m = UUID_V1.search(p["url"])
        key = m.group(1) if m else None
        by_batch.setdefault(key, []).append(p)
        slug = urllib.parse.urlsplit(p["url"]).path.rstrip("/").split("/")[-2 if m else -1]
        hits = {variants[v] for v in variants if re.search(rf"(^|-){re.escape(v)}(-|$)", slug)}
        rec = info.setdefault(key, {"products": 0, "colours": set()})
        rec["products"] += 1
        rec["colours"] |= hits
    keep = {k for k, v in info.items() if k and len(v["colours"]) >= min_distinct}
    kept = [p for k in keep for p in by_batch[k]]
    report = {k: {"products": v["products"], "colours": sorted(v["colours"])}
              for k, v in sorted(info.items(), key=lambda kv: -len(kv[1]["colours"])) if k in keep}
    return kept, report


def list_sitemap(fetch, root, follow_words, max_sitemaps=60, listing=None):
    """Product entries from sitemaps. Uses <image:image> blocks when present, so no product
    page needs loading; otherwise returns bare URLs for the crawl step to load.

    `listing` (the supplier's registry `listing`) may set `path_contains` (keep only these
    URLs, e.g. `/products/` to drop the French duplicates), `skip_words` (slug tokens that
    mark an accessory), and `slug_parser: "floorbox"` (a title from the slug, for sitemaps
    whose images carry no title)."""
    listing = listing or {}
    keep_path = listing.get("path_contains")
    skip = set(listing.get("skip_words") or [])
    parse = listing.get("slug_parser") == "floorbox"
    queue, seen, pages = sitemap_roots(fetch, root), set(), []
    while queue and len(seen) < max_sitemaps:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        xml = fetch.get(sm).decode("utf-8", "replace")
        if "<sitemapindex" in xml:
            children = SITEMAP_LOC.findall(xml)
            prod = [c for c in children if "product" in c.lower()]
            queue.extend(prod or children)
            continue
        for block in URL_BLOCK.findall(xml):
            locs = SITEMAP_LOC.findall(block)
            if not locs:
                continue
            url = locs[0]
            if keep_path and keep_path not in url:
                continue
            path_parts = urllib.parse.urlsplit(url).path.rstrip("/").split("/")
            slug = path_parts[-2] if UUID_V1.fullmatch(path_parts[-1] or "") else path_parts[-1]
            if skip and skip & set(slug.lower().split("-")):
                continue
            imgs = []
            for ib in IMAGE_BLOCK.findall(block):
                loc = IMAGE_LOC.search(ib)
                if loc:
                    t = IMAGE_TITLE.search(ib)
                    imgs.append({"url": loc.group(1), "alt": (t.group(1).strip() if t else "")})
            title = next((i["alt"] for i in imgs if i["alt"]), "") or (slug_title(slug) if parse else "")
            hay = f"{url} {title}".lower()
            if follow_words and not any(w in hay for w in follow_words):
                continue
            pages.append({"url": url, "title": title, "h1": "", "og_title": "", "product_name": "",
                          "is_product": "product" in url.lower(),
                          "codes": slug_codes(slug) if parse else [], "images": imgs,
                          "_needs_page": not imgs})
    return pages


def crawl(fetch, root, follow_words, max_pages, start_urls=None):
    host = urllib.parse.urlsplit(root).netloc
    queue, seen, pages = list(start_urls or [root]), set(), []
    while queue and len(seen) < max_pages:
        url = queue.pop(0).split("#")[0]
        if url in seen or urllib.parse.urlsplit(url).netloc != host:
            continue
        seen.add(url)
        page = page_from_html(url, fetch.get(url))
        links = page.pop("_links")
        if page["images"]:
            pages.append(page)
        if start_urls is None:
            for l in links:
                hay = f"{l['href']} {l['text']}".lower()
                if l["href"] not in seen and (not follow_words or any(w in hay for w in follow_words)):
                    queue.append(l["href"])
    return pages


def supplier_sources(sup, cfg=None):
    """The supplier's sources in the registry's `source_policy.order` (Albert, 2026-09-29:
    "search the main website -> externals (floorbox and speers)"): its `official` site,
    then each shared retailer it lists under `retailers`, with the supplier's overrides
    (e.g. Speers' `vendor` string) merged into that retailer's listing. Each is
    {name, site, listing}. Older entries with a bare `site` still work."""
    cfg = cfg or {}
    order = (cfg.get("source_policy") or {}).get("order") or ["official", *(cfg.get("retailers") or {})]
    out = []
    for name in order:
        if name == "official":
            off = sup.get("official")
            if off:
                out.append({"name": "official", "site": off["site"], "listing": off.get("listing") or {},
                            "follow_words": off.get("follow_words", [])})
        elif name in (sup.get("retailers") or {}):
            base = (cfg.get("retailers") or {}).get(name) or {}
            over = sup["retailers"][name] or {}
            out.append({"name": name, "site": over.get("site") or base["site"],
                        "listing": {**(base.get("listing") or {}), **{k: v for k, v in over.items() if k != "site"}},
                        "follow_words": over.get("follow_words", [])})
    if not out and sup.get("site"):  # an entry from before source_policy
        out = [*(sup.get("extra_sources") or []),
               {"name": sup.get("source_name", "main"), "site": sup["site"],
                "listing": sup.get("listing") or {}, "follow_words": sup.get("follow_words", [])}]
    return out


def list_pages(fetch, cfg, supplier_cfg, max_pages):
    root = supplier_cfg["site"]
    listing = supplier_cfg.get("listing") or {}
    method = listing.get("method", "auto")
    follow = [] if listing.get("brand_batches") else [w.lower() for w in supplier_cfg.get("follow_words", [])]
    order = ["shopify", "woocommerce", "sitemap", "crawl"] if method == "auto" else [method]
    tried = {}
    for m in order:
        try:
            if m == "shopify":
                pages = list_shopify(fetch, root, listing.get("vendor"))
            elif m == "woocommerce":
                pages = list_woocommerce(fetch, root)
            elif m == "sitemap":
                pages = list_sitemap(fetch, root, follow, listing=listing)
                bare = [p["url"] for p in pages if p.get("_needs_page")]
                if bare:
                    loaded = crawl(fetch, root, follow, max_pages, start_urls=bare[:max_pages])
                    pages = [p for p in pages if not p.get("_needs_page")] + loaded
            else:
                pages = crawl(fetch, root, follow, max_pages)
        except Blocked as exc:
            tried[m] = exc.status
            if exc.status == "host_blocked" or m == order[-1]:
                return m, [], tried
            continue
        except Exception as exc:  # a method the site does not speak: 404, bad JSON
            tried[m] = f"unavailable: {exc.__class__.__name__}"
            continue
        if pages:
            tried[m] = "ok"
            return m, pages, tried
        tried[m] = "empty"
    return None, [], tried


# --------------------------------------------------------------------------- snapshot + download

def load_snapshot(paths):
    reg = json.loads(FIELDS.read_text())
    names = {fid: f["name"] for fid, f in reg.get("fields", reg).items() if isinstance(f, dict) and "name" in f}
    records = []
    for path in paths:
        page = json.loads(Path(path).read_text())
        for r in page.get("records", page if isinstance(page, list) else []):
            row = {"id": r["id"]}
            for fid, value in (r.get("cellValuesByFieldId") or r.get("fields") or {}).items():
                if isinstance(value, dict) and "name" in value:
                    value = value["name"]
                row[names.get(fid, fid)] = value
            records.append(row)
    return records


def make_read_copy(path, read_path):
    """(width, height, read_path or None, problem or None)."""
    try:
        from PIL import Image
    except ImportError:
        return None, None, str(path), None
    try:
        with Image.open(path) as im:
            w, h = im.size
            im = im.convert("RGB")
            scale = READ_LONG_EDGE / max(w, h)
            if scale < 1:
                im = im.resize((round(w * scale), round(h * scale)))
            im.save(read_path, "JPEG", quality=90)
        return w, h, str(read_path), None
    except Exception as exc:
        return None, None, None, f"unsupported_format: {exc.__class__.__name__}"


def download(pages, wanted_urls, images_dir, fetch, rules):
    counts = Counter()
    images_dir = Path(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    done = {}
    for page in pages:
        if page["url"] not in wanted_urls:
            continue
        for img in page["images"]:
            if not keep_image(img["url"], rules):
                img["status"] = "skipped_by_rule"
                counts["skipped_by_rule"] += 1
                continue
            if img["url"] in done:
                img.update(done[img["url"]])
                continue
            try:
                data = fetch.get(img["url"])
            except Blocked as exc:
                img["status"] = exc.status
                counts[exc.status] += 1
                continue
            except Exception as exc:
                img["status"], img["error"] = "failed", str(exc)[:200]
                counts["failed"] += 1
                continue
            sha = hashlib.sha1(data).hexdigest()
            ext = (Path(urllib.parse.urlsplit(img["url"]).path).suffix or ".jpg").lower()[:6]
            path = images_dir / f"{sha}{ext}"
            path.write_bytes(data)
            w, h, read_path, problem = make_read_copy(path, images_dir / f"{sha}-read.jpg")
            info = {"sha1": sha, "path": str(path), "read_path": read_path, "width": w, "height": h,
                    "status": "unsupported_format" if problem else "downloaded"}
            if problem:
                info["error"] = problem
            img.update(info)
            done[img["url"]] = info
            counts[info["status"]] += 1
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--supplier", required=True, help="Key under `suppliers` in the registry, e.g. VIDAR")
    ap.add_argument("--scope", required=True)
    ap.add_argument("--snapshot", action="append", required=True, type=Path)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--max-pages", type=int)
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    cfg = load_registry(args.registry)
    sup = cfg["suppliers"].get(args.supplier)
    if not sup:
        print(f"error: {args.supplier} has no entry under `suppliers` in {args.registry}", file=sys.stderr)
        return 2
    records = load_snapshot(args.snapshot)
    fetch = Fetcher(cfg)
    max_pages = args.max_pages or cfg["fetch"]["max_pages"]
    colours = {image_match.colour_of(r.get("Product name")) for r in records}
    pages, sources, wanted = [], {}, set()
    for src in supplier_sources(sup, cfg):
        method, src_pages, tried = list_pages(fetch, cfg, src, max_pages)
        batches = None
        bb = (src.get("listing") or {}).get("brand_batches")
        if bb and src_pages:
            src_pages, batches = brand_batches(src_pages, colours, bb.get("min_distinct_colours", 3))
        for p in src_pages:
            p.pop("_needs_page", None)
            p["source"] = src["name"]
            p["images"] = [i for i in p["images"] if keep_image(i["url"], cfg["image_rules"])]
        # Matched per source: the same product on two sites is two candidates, not a tie.
        m = image_match.match_records(records, src_pages, sup, cfg["matching"])
        wanted |= {c["url"] for x in m.values() for c in x["candidates"]}
        sources[src["name"]] = {"site": src["site"], "method": method, "tried": tried,
                                "pages": len(src_pages), "batches": batches,
                                "tiers": dict(Counter(x["tier"] for x in m.values()))}
        pages += src_pages
    status = "ok" if pages else next((v for s in sources.values() for v in s["tried"].values()
                                      if v in ("challenged", "host_blocked")), "empty")
    method = {k: v["method"] for k, v in sources.items()}
    tried = {k: v["tried"] for k, v in sources.items()}
    batches = {k: v["batches"] for k, v in sources.items() if v["batches"]}
    counts = Counter()
    images_dir = REPO_ROOT / "ingest" / today() / cfg["outputs"]["images_dir"] / args.scope
    if args.download and pages:
        counts = download(pages, wanted, images_dir, fetch, cfg["image_rules"])
    out = {
        "contract_version": CONTRACT_VERSION,
        "scope": args.scope,
        "supplier": args.supplier,
        "site": sup["site"],
        "pulled_at": datetime.now(TZ).isoformat(),
        "status": status,
        "listing": {"method": method, "tried": tried, "requests": fetch.count},
        "batches": batches,
        "images": {"dir": str(images_dir.relative_to(REPO_ROOT)), "counts": dict(counts)},
        "sources": sources,
        "summary": {"records": len(records), "pages": len(pages), "pages_matched": len(wanted),
                    "tiers": {k: v["tiers"] for k, v in sources.items()}},
        "pages": pages,
    }
    path = args.out or (REPO_ROOT / "ingest" / today() / cfg["outputs"]["pages"].format(scope=args.scope))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(path)
    print(f"  status {status}; listing {method} {tried}; {fetch.count} requests")
    print(f"  {len(pages)} pages; {len(wanted)} matched a record; tiers {out['summary']['tiers']}")
    if counts:
        print(f"  images {dict(counts)}")
    if status in ("challenged", "host_blocked"):
        print(f"\n  The site refused automated reading ({status}). Not worked around: allow the host in the\n"
              "  environment's Network access (host_blocked), or use another source (challenged).")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
