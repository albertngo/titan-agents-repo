#!/usr/bin/env python3
"""Tests for /image-fill: the matcher, the site pull's parsing and refusal handling, the
planner's blank-only and image rules, the policy gate, and the prose.

    python3 -m unittest discover -s tests -v

Stdlib unittest, fixtures inline. No network: fetches go through a fake opener.
"""

import copy
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import image_fill_plan as plan  # noqa: E402
import image_match as im  # noqa: E402
import supplier_site_pull as pull  # noqa: E402

REG = json.loads((REPO_ROOT / "platform-settings" / "supplier-sites.json").read_text())
FIELDS = json.loads((REPO_ROOT / "platform-settings" / "airtable-master-catalogue-fields.json").read_text())["fields"]
VIDAR = REG["suppliers"]["VIDAR"]


def rec(rid, name, collection, width, grade="Select", **extra):
    return {"id": rid, "SKU": f"ENG-VIDR-{rid[-4:]}", "Product name": name, "Collection": collection,
            "Width (in)": width, "Grade": grade, **extra}


NAKED_75 = rec("rec0000000000001", 'Vidar 7.5" AWO — Naked Oak (Character)', "7 Collection", 7.5, "Character")
NAKED_9 = rec("rec0000000000002", 'Vidar 9" AWO — Naked Oak (Select)', "9 Collection", 9)
NAKED_HB = rec("rec0000000000003", 'Vidar HB 5" AWO — Naked Oak (Character)', "Herringbone Collection", 5)
WALNUT = rec("rec0000000000004", 'Vidar 6" ABW — Natural (Select)', "Black Walnut Collection", 6)


def page(url, title, images=(), source="floorbox"):
    return {"url": url, "title": title, "h1": "", "og_title": "", "product_name": "",
            "codes": [], "images": list(images), "source": source}


def img(sha, url, w=2400, h=1600):
    return {"url": url, "sha1": sha, "width": w, "height": h, "status": "downloaded", "read_path": f"/x/{sha}.jpg"}


class TestMatcher(unittest.TestCase):
    def m(self, records, pages):
        return im.match_records(records, pages, VIDAR, REG["matching"])

    def test_colour_must_be_in_the_title(self):
        out = self.m([NAKED_9], [page("https://x/a", "Daybreak", ()), page("https://x/b", "9'' Collection American White Oak-Naked Oak")])
        self.assertEqual(out[NAKED_9["id"]]["tier"], "exact")
        self.assertEqual(out[NAKED_9["id"]]["candidates"][0]["url"], "https://x/b")

    def test_slug_is_ignored_when_a_title_exists(self):
        """vidarflooring.com's Daybreak page lives at /naked-oak-daybreak."""
        out = self.m([NAKED_9], [page("https://x/naked-oak-daybreak", "9'' Collection American White Oak-Daybreak")])
        self.assertEqual(out[NAKED_9["id"]]["tier"], "none")

    def test_the_records_own_width_must_be_on_the_page(self):
        """2026-09-29: a 7.5" record took a 7" listing via its `7 Collection` number; the
        catalogue holds both widths, so the collection number only counts with no width."""
        pages = [page("https://x/6", "American Oak 6 Collection-Naked Oak"),
                 page("https://x/7", "American White Oak 7 Collection - Naked Oak"),
                 page("https://x/75", "7 1/2'' Collection American White Oak-Naked Oak")]
        out = self.m([NAKED_75, NAKED_9], pages)
        self.assertEqual([c["url"] for c in out[NAKED_75["id"]]["candidates"]], ["https://x/75"])
        self.assertEqual(out[NAKED_9["id"]]["tier"], "none")
        no_width = {**NAKED_75, "id": "rec0000000000099", "Width (in)": None}
        out = self.m([no_width], pages[:2])
        self.assertEqual([c["url"] for c in out[no_width["id"]]["candidates"]], ["https://x/7"])

    def test_pattern_must_agree_both_ways(self):
        pages = [page("https://x/plank", "Naked Oak"), page("https://x/hb", "Herringbone Naked Oak")]
        out = self.m([NAKED_HB, NAKED_9], pages)
        self.assertEqual([c["url"] for c in out[NAKED_HB["id"]]["candidates"]], ["https://x/hb"])
        self.assertEqual([c["url"] for c in out[NAKED_9["id"]]["candidates"]], ["https://x/plank"])

    def test_species_vetoes(self):
        out = self.m([WALNUT], [page("https://x/o", "White Oak - Natural"), page("https://x/w", "Black Walnut - Natural")])
        self.assertEqual([c["url"] for c in out[WALNUT["id"]]["candidates"]], ["https://x/w"])

    def test_a_size_is_not_a_colour(self):
        """2026-09-29: `Vidar Hardwood Vent — 4"x10"` matched a walnut plank listing."""
        self.assertEqual(im.colour_of('Vidar Hardwood Vent — 4"x10"'), "")
        self.assertEqual(im.colour_of("Vidar Laminate — NK25"), "NK25")

    def test_joined_and_split_spellings_match(self):
        self.assertTrue(im.has_phrase("9'' Collection American White Oak-Daybreak", "Day Break"))
        self.assertTrue(im.has_phrase("7 Collection - Snow White", "Snowwhite"))
        self.assertFalse(im.has_phrase("Naked Oak", "Oak Naked"))

    def test_a_tie_is_ambiguous(self):
        out = self.m([NAKED_9], [page("https://x/a", "Naked Oak"), page("https://x/b", "Naked Oak")])
        self.assertEqual(out[NAKED_9["id"]]["tier"], "ambiguous")

    def test_supplier_code_is_exact(self):
        r = {**NAKED_9, "Supplier SKU": "NK25", "Product name": "Vidar Laminate — NK25"}
        p = {**page("https://x/c", "Something else"), "codes": ["NK25"]}
        self.assertEqual(self.m([r], [p])[r["id"]]["candidates"][0]["score"], 100)


class FakeResp(io.BytesIO):
    def __init__(self, body, status=200, headers=""):
        super().__init__(body)
        self.status, self.headers = status, headers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestProductLine(unittest.TestCase):
    """BiYork reuses colour names across lines and shares them with other brands."""
    BIYORK = REG["suppliers"]["BIYORK"]

    def m(self, records, pages):
        return im.match_records(records, pages, self.BIYORK, REG["matching"])

    def test_line_number_stands_alone(self):
        self.assertEqual(im.product_line("BiYork Hydrogen PRO 3mm Oak", self.BIYORK), ("hydrogen pro", None))
        self.assertEqual(im.product_line("biyork hydrogen 8 brume air", self.BIYORK), ("hydrogen", "8"))

    def test_a_page_naming_no_line_is_vetoed(self):
        r = {"id": "recB000000000001", "SKU": "LVT-BIYK-0001", "Product name": "Biyork Hydrogen PRO Tile 3mm — Chalk"}
        p = page("https://x/fuzion-vinyl-tiles-smartdrop-elite-chalk-18x36", "Fuzion Vinyl Tiles Smartdrop Elite Chalk 18x36")
        self.assertEqual(self.m([r], [p])[r["id"]]["tier"], "none")

    def test_another_line_number_is_vetoed(self):
        r = {"id": "recB000000000002", "SKU": "LVP-BIYK-0002", "Product name": "Biyork Hydrogen 8 — Brume Air"}
        good = page("https://x/biyork-hydrogen-8-brume-air", "BiYork Hydrogen 8 Brume Air 9 x 72 x 8mm", source="speers")
        other = page("https://x/biyork-hydrogen-6-brume-air", "BiYork Hydrogen 6 Brume Air", source="speers")
        out = self.m([r], [good, other])[r["id"]]
        self.assertEqual([c["url"] for c in out["candidates"]], [good["url"]])


    def test_shopify_tags_name_the_line_a_bare_title_leaves_out(self):
        r = {"id": "recB000000000003", "SKU": "LVP-BIYK-0003", "Product name": "Biyork Hydrogen 8 — Brume Air"}
        p = {**page("https://brand/products/brume-air-sample", "Brume Air Sample*", source="official"),
             "tags": ["Hydrogen 8", "SPC Floors", "SPC Plank"], "product_type": "WaterProof Floors | Plank"}
        self.assertEqual(self.m([r], [p])[r["id"]]["tier"], "exact")  # SPC tags are not a pattern
        wrong = {**p, "tags": ["HydroGen 6"]}
        self.assertEqual(self.m([r], [wrong])[r["id"]]["tier"], "none")

    def test_hickory_is_biyorks_species_not_a_pattern(self):
        r = {"id": "recB000000000004", "SKU": "ENG-BIYK-0004", "Product name": 'Biyork Nouveau 7 7.5" — Derby'}
        p = {**page("https://brand/products/derby-sample", "Hickory - Derby Sample*", source="official"),
             "tags": ["7-1/2 Inch", "Hickory", "Nouveau 7"], "product_type": "Engineered Hardwood | Hickory"}
        self.assertEqual(self.m([r], [p])[r["id"]]["tier"], "exact")

class TestRelink(unittest.TestCase):
    """Albert, 2026-09-29: move Vidar's Speers links to Word of Mouth, else The Floor Box;
    never clear one."""

    def plan(self, pages):
        rec = dict(NAKED_9)
        src = {"actions": [{"id": "img-1", "record_id": rec["id"], "sku": rec["SKU"], "product_name": rec["Product name"],
                            "fields": {"Supplier product page": "https://www.speersflooring.com/products/naked-oak-9"}}]}
        return plan.relink_plan([rec], {"pages": pages}, REG, "VIDAR", "vidar", src)

    def test_word_of_mouth_first_then_the_floor_box(self):
        wom = page("https://www.wordofmouthfloors.com/products/vidar-9-naked-oak", "VIDAR 9'' American White Oak - Naked Oak", source="wordofmouth")
        fb = page("https://thefloorbox.ca/products/x", "9'' American White Oak Naked Oak", source="floorbox")
        a = self.plan([fb, wom])["actions"][0]
        self.assertEqual(a["fields"]["Supplier product page"], wom["url"])
        self.assertEqual(a["expect"]["Supplier product page"], "https://www.speersflooring.com/products/naked-oak-9")
        self.assertEqual(self.plan([fb])["actions"][0]["source"], "floorbox")

    def test_a_vinyl_listing_never_links_an_engineered_record(self):
        rec = {**NAKED_9, "Category": "Engineered hardwood"}
        vinyl = {**page("https://w/vidar-luxury-rigid-core-vinyl-plank-naked-oak", "VIDAR Luxury Rigid Core Vinyl Plank - Naked Oak",
                        source="wordofmouth"), "product_type": "SPC RIGID CORE VINYL"}
        self.assertEqual(im.match_records([rec], [vinyl], VIDAR, REG["matching"])[rec["id"]]["tier"], "none")

    def test_trim_named_after_the_floor_is_not_the_floor(self):
        rec = {"id": "recB000000000009", "SKU": "LVP-BIYK-0009", "Product name": "Biyork Traktion — Afterburn", "Category": "LVP"}
        trim = page("https://w/afterburn-reducer", "Traktion Afterburn Reducer", source="wordofmouth")
        self.assertEqual(im.match_records([rec], [trim], REG["suppliers"]["BIYORK"], REG["matching"])[rec["id"]]["tier"], "none")

    def test_no_alternative_keeps_the_link(self):
        p = self.plan([])
        self.assertEqual(p["actions"], [])
        self.assertEqual(p["held"][0]["reason"], "no_alternative_link")

    def test_a_lower_quality_photo_beats_none(self):
        # Albert, 2026-10-03: "Having it is better than none." Only icons and thumbnails are cut.
        self.assertEqual(REG["image_rules"]["min_swatch_long_edge_px"], 300)
        self.assertEqual(REG["image_rules"]["min_any_long_edge_px"], 300)


class TestFloorBoxSizes(unittest.TestCase):
    def test_width_by_length_slugs(self):
        self.assertEqual(pull.slug_title("vinyl-planks-tfl62-series-627-honey-birch-loose-lay-7-38-x-48-38"),
                         'Vinyl Planks TFL62 Series 627 Honey Birch Loose Lay — 7.375"')
        self.assertTrue(pull.slug_title("laminate-flooring-tf66-series-6603-santa-fe-7-34-x-47").endswith('7.75"'))
        self.assertTrue(pull.slug_title("click-vinyl-planks-spc7-series-710-oyster-bay-click-lock-6-x-48").endswith('— 6"'))

    def test_rounded_catalogue_widths_match(self):
        rec = {"id": "recT000000000001", "SKU": "LVP-TRIF-0001", "Product name": 'Toucan Looselay Vinyl — Honey Birch (7.4" x 5.0mm)',
               "Width (in)": 7.4, "Category": "LVP"}
        p = page("https://thefloorbox.ca/products/x", 'Vinyl Planks TFL62 Series 627 Honey Birch Loose Lay — 7.375"')
        self.assertEqual(im.match_records([rec], [p], REG["suppliers"]["TRIFOREST"], REG["matching"])[rec["id"]]["tier"], "exact")


class TestPull(unittest.TestCase):
    def fetcher(self, routes):
        def opener(req, timeout=0):
            body = routes.get(req.full_url)
            if body is None:
                raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b""))
            if isinstance(body, FakeResp):
                return body
            return FakeResp(body)
        f = pull.Fetcher({"fetch": {"delay_seconds": 0}}, opener=opener)
        return f

    def test_siteground_challenge_is_refused_not_parsed(self):
        f = self.fetcher({"https://s/en": FakeResp(b'<meta http-equiv="refresh" content="0;/.well-known/sgcaptcha/?r=">', 202, "sg-captcha: challenge")})
        with self.assertRaises(pull.Blocked) as cm:
            f.get("https://s/en")
        self.assertEqual(cm.exception.status, "challenged")

    def test_sitemap_images_map_to_products_without_loading_pages(self):
        xml = (b'<urlset><url><loc>https://s/p/vidar-naked-oak</loc><image:image><image:loc>https://cdn/s/naked.jpg'
               b'</image:loc><image:title>Vidar Naked Oak</image:title></image:image></url>'
               b'<url><loc>https://s/p/other-brand</loc><image:image><image:loc>https://cdn/o.jpg</image:loc>'
               b'<image:title>Other</image:title></image:image></url></urlset>')
        f = self.fetcher({"https://s/robots.txt": b"Sitemap: https://cdn/sm.xml", "https://cdn/sm.xml": xml})
        pages = pull.list_sitemap(f, "https://s/brands/vidar", ["vidar"])
        self.assertEqual([p["url"] for p in pages], ["https://s/p/vidar-naked-oak"])
        self.assertEqual(pages[0]["images"][0]["url"], "https://cdn/s/naked.jpg")
        self.assertEqual(pages[0]["title"], "Vidar Naked Oak")

    def test_html_page_takes_jsonld_and_largest_srcset(self):
        html = ('<html><head><title>Naked Oak | Shop</title><script type="application/ld+json">'
                '{"@type":"Product","name":"Naked Oak","sku":"NK25","image":["/a.jpg"]}</script></head>'
                '<body><h1>Naked Oak</h1><img srcset="/s.jpg 300w, /l.jpg 2000w" src="/s.jpg"></body></html>')
        p = pull.page_from_html("https://s/p", html)
        urls = [i["url"] for i in p["images"]]
        self.assertIn("https://s/a.jpg", urls)
        self.assertIn("https://s/l.jpg", urls)
        self.assertIn("NK25", p["codes"])
        self.assertTrue(p["is_product"])

    def test_logos_and_svgs_are_skipped(self):
        rules = REG["image_rules"]
        self.assertFalse(pull.keep_image("https://s/logo.png", rules))
        self.assertFalse(pull.keep_image("https://s/x.svg", rules))
        self.assertTrue(pull.keep_image("https://s/naked-oak.jpg", rules))


class TestFloorBoxSitemap(unittest.TestCase):
    """2026-09-29: The Floor Box's pages are Cloudflare-challenged; its CDN sitemap is not."""

    def test_slug_titles(self):
        cases = {
            "engineered-hardwood-american-oak-7-macaroon-select-better-7-12-34-2532-sqftbox":
                'Engineered Hardwood American Oak 7 Macaroon — Select & Better — 7.5"',
            "engineered-hardwood-american-oak-6-naked-oak-select-6-34":
                'Engineered Hardwood American Oak 6 Naked Oak — Select — 6"',
            "engineered-hardwood-click-moon-light-character-5-12":
                'Engineered Hardwood Click Moon Light — Character — 5"',
            "engineered-hardwood-naked-oak-character-9-34-2030-sqft":
                'Engineered Hardwood Naked Oak — Character — 9"',
            "laminate-nk25-7-12-12": 'Laminate NK25 — 7.5"',
        }
        for slug, title in cases.items():
            self.assertEqual(pull.slug_title(slug), title, slug)

    def test_the_slug_title_matches_the_right_record(self):
        s75 = rec("rec0000000000011", 'Vidar 7.5" AWO — Macaroon (Select & Better)', "7 Collection", 7.5, "Select & Better")
        s75_sel = rec("rec0000000000012", 'Vidar 7.5" AWO — Macaroon (Select)', "7 Collection", 7.5, "Select")
        p = page("https://fb/products/x/2b686265-333c-11ef-baed-f6968cef729a",
                 pull.slug_title("engineered-hardwood-american-oak-7-macaroon-select-better-7-12-34-2532-sqftbox"))
        out = im.match_records([s75, s75_sel], [p], VIDAR, REG["matching"])
        self.assertEqual(out[s75["id"]]["tier"], "exact")
        self.assertEqual(out[s75_sel["id"]]["tier"], "none")  # Select never takes Select & Better

    def test_french_duplicates_and_accessories_are_dropped(self):
        xml = (b'<urlset>'
               b'<url><loc>https://s/products/engineered-hardwood-naked-oak-select-6-34/2b6bd755-333c-11ef-baed-f6968cef729a</loc>'
               b'<image:image><image:loc>https://cdn/a</image:loc></image:image></url>'
               b'<url><loc>https://s/fr/produits/bois-naked-oak-select-6-34/2b6bd755-333c-11ef-baed-f6968cef729a</loc>'
               b'<image:image><image:loc>https://cdn/a</image:loc></image:image></url>'
               b'<url><loc>https://s/products/hardwood-american-oak-naked-oak-matte-floor-vent-4-x-10/06a4e7bb-9981-11f0-bc10-f6968cef729a</loc>'
               b'<image:image><image:loc>https://cdn/v</image:loc></image:image></url></urlset>')
        f = pull.Fetcher({"fetch": {"delay_seconds": 0}},
                         opener=lambda req, timeout=0: FakeResp(b"Sitemap: https://cdn/sm.xml" if req.full_url.endswith("robots.txt") else xml))
        pages = pull.list_sitemap(f, "https://s/brands/vidar", [], listing=REG["retailers"]["floorbox"]["listing"])
        self.assertEqual(len(pages), 1)
        self.assertIn("/products/engineered-hardwood-naked-oak", pages[0]["url"])
        self.assertEqual(pages[0]["title"], 'Engineered Hardwood Naked Oak — Select — 6"')

    def test_brand_batches_keep_only_the_suppliers_imports(self):
        def pg(slug, batch):
            return page(f"https://s/products/{slug}/2b6bd755-{batch}-baed-f6968cef729a", "")
        pages = [pg("eh-naked-oak-select-6-34", "333c-11ef"), pg("eh-toffee-crunch-select-6-34", "333c-11ef"),
                 pg("eh-wheat-berry-select-6-34", "333c-11ef"), pg("eh-natural-select-6-34", "333c-11ef"),
                 pg("eh-naked-oak-select-6-34", "fb0e-11eb"), pg("eh-natural-select-6-34", "fb0e-11eb")]
        kept, report = pull.brand_batches(pages, {"Naked Oak", "Toffee Crunch", "Wheat Berry", "Natural"}, 3)
        self.assertEqual(len(kept), 4)
        self.assertEqual(list(report), ["333c-11ef"])
        self.assertEqual(report["333c-11ef"]["colours"], ["naked oak", "toffee crunch", "wheat berry"])


class TestPlan(unittest.TestCase):
    def build(self, records, pages, judgements, product_pages=None):
        pf = {"pages": pages}
        return plan.build(records, pf, judgements, product_pages, REG, "VIDAR", "vidar")

    def setUp(self):
        self.pages = [page("https://fb/naked-9", "9'' Collection American White Oak-Naked Oak",
                           [img("s1", "https://cdn/sw.jpg"), img("r1", "https://cdn/room.jpg"),
                            img("s2", "https://cdn/small.jpg", 1000, 800)])]
        self.j = {"contract_version": "image-judgements-1",
                  "images": {"s1": {"kind": "swatch"}, "r1": {"kind": "room"}, "s2": {"kind": "swatch"}}}

    def test_blank_only(self):
        filled = {**NAKED_9, "Swatch images": [{"id": "att1"}]}
        p = self.build([filled], self.pages, self.j)
        a = p["actions"][0]
        self.assertNotIn("Swatch images", a["fields"])
        self.assertEqual([x["url"] for x in a["fields"]["Room scene images"]], ["https://cdn/room.jpg"])
        self.assertNotIn("no_swatch", a["flags"])

    def test_everything_filled_is_skipped(self):
        full = {**NAKED_9, **{REG["targets"][t]["name"]: [{"id": "a"}] for t in ("swatch", "room", "detail")}}
        p = self.build([full], self.pages, self.j)
        self.assertEqual(p["actions"], [])
        self.assertEqual(p["summary"]["skipped"], {"all_targets_filled": 1})

    def test_filled_earlier_with_nothing_new_is_skipped_not_held(self):
        # Olympia 2026-10-28: a record batch 1 gave a swatch, whose page has no room or detail
        # photo, is fine; it must not land in the troubled CSV as no_usable_image.
        swatch_only = [page("https://fb/naked-9", "9'' Collection American White Oak-Naked Oak",
                            [img("s1", "https://cdn/sw.jpg")])]
        filled = {**NAKED_9, "Swatch images": [{"id": "att1"}], "Supplier product page": "https://fb/naked-9"}
        p = self.build([filled], swatch_only, self.j)
        self.assertEqual((p["actions"], p["held"], p["summary"]["skipped"]), ([], [], {"nothing_new": 1}))
        self.assertEqual(self.build([NAKED_9], [page("https://fb/naked-9", "9'' Collection American White Oak-Naked Oak")],
                                    self.j)["held"][0]["reason"], "no_usable_image")  # a blank record still reports

    def test_a_smaller_swatch_lands_after_the_larger_one(self):
        # 2026-10-03: a lower quality photo is better than none; the larger still goes first.
        p = self.build([NAKED_9], self.pages, self.j)
        self.assertEqual([x["url"] for x in p["actions"][0]["fields"]["Swatch images"]],
                         ["https://cdn/sw.jpg", "https://cdn/small.jpg"])

    def test_a_thumbnail_never_lands(self):
        pages = [page("https://fb/t", "9'' Collection American White Oak-Naked Oak", [img("t1", "https://cdn/thumb.jpg", 200, 150)])]
        p = self.build([NAKED_9], pages, {"contract_version": "image-judgements-1", "images": {"t1": {"kind": "swatch"}}})
        self.assertEqual(p["actions"], [])

    def test_unjudged_images_are_held(self):
        p = self.build([NAKED_9], self.pages, {"contract_version": "image-judgements-1", "images": {}})
        self.assertEqual(p["held"][0]["reason"], "not_judged")

    def test_watermarked_and_wrong_colour_are_dropped(self):
        j = {"contract_version": "image-judgements-1", "images": {
            "s1": {"kind": "swatch", "watermarked": True}, "r1": {"kind": "room", "colour_matches_page": False},
            "s2": {"kind": "swatch"}}}
        p = self.build([NAKED_9], self.pages, j)
        a = p["actions"][0]
        self.assertEqual([x["url"] for x in a["fields"]["Swatch images"]], ["https://cdn/small.jpg"])
        self.assertNotIn("Room scene images", a["fields"])

    def test_a_sister_companys_named_watermark_is_kept_and_no_other(self):
        # Evergreen, 2026-10-28 (Albert): Simba's overlay is fine on Evergreen; an unnamed or
        # other company's watermark still drops the photo.
        reg = copy.deepcopy(REG)
        reg["suppliers"]["VIDAR"]["image_rules"] = {"watermark_ok": ["Simba"]}
        j = {"contract_version": "image-judgements-1", "images": {
            "s1": {"kind": "swatch", "watermarked": True, "watermark_by": "Simba"},
            "r1": {"kind": "room", "watermarked": True, "watermark_by": "Speers"},
            "s2": {"kind": "swatch", "watermarked": True}}}
        a = plan.build([NAKED_9], {"pages": self.pages}, j, None, reg, "VIDAR", "vidar")["actions"][0]
        self.assertEqual([x["url"] for x in a["fields"]["Swatch images"]], ["https://cdn/sw.jpg"])
        self.assertNotIn("Room scene images", a["fields"])
        self.assertEqual(self.build([NAKED_9], self.pages, j)["actions"], [])  # no watermark_ok: all dropped

    def test_ambiguous_needs_a_verdict_and_null_is_respected(self):
        pages = self.pages + [page("https://fb/naked-9b", "9'' Collection American White Oak-Naked Oak", [img("s3", "https://cdn/b.jpg")])]
        self.assertEqual(self.build([NAKED_9], pages, self.j)["held"][0]["reason"], "ambiguous_match")
        j = {**self.j, "matches": {NAKED_9["id"]: {"page": None}}}
        self.assertEqual(self.build([NAKED_9], pages, j)["held"][0]["reason"], "model_rejected")
        j = {**self.j, "matches": {NAKED_9["id"]: {"page": "https://fb/naked-9"}}}
        a = self.build([NAKED_9], pages, j)["actions"][0]
        self.assertEqual(a["match_tier"], "model_confirmed")
        self.assertIn("model_matched", a["flags"])

    def test_a_photo_laid_in_another_pattern_is_dropped(self):
        """The Floor Box reused a herringbone room shot on a plank listing (2026-09-29)."""
        j = {"contract_version": "image-judgements-1", "images": {
            "s1": {"kind": "swatch", "laying": "plank"}, "r1": {"kind": "room", "laying": "herringbone"},
            "s2": {"kind": "swatch", "laying": "plank"}}}
        a = self.build([NAKED_9], self.pages, j)["actions"][0]
        self.assertIn("Swatch images", a["fields"])
        self.assertNotIn("Room scene images", a["fields"])

    def test_a_tie_between_identical_photos_is_not_a_choice(self):
        pages = self.pages + [page("https://fb/naked-9-dup", "9'' Collection American White Oak-Naked Oak",
                                   [img("s1", "https://cdn/sw2.jpg"), img("r1", "https://cdn/room2.jpg"),
                                    img("s2", "https://cdn/small2.jpg", 1000, 800)])]
        a = self.build([NAKED_9], pages, self.j)["actions"][0]
        self.assertEqual(a["match_tier"], "exact")

    def test_product_page_prefers_the_manufacturer(self):
        idx = {"results": [
            {"title": "9'' Collection American White Oak-Naked Oak - Vidar Flooring",
             "url": "https://www.vidarflooring.com/en/product/engineered-hardwood/american-oak-naked-oak"},
            {"title": "American White Oak 9 Collection - Naked Oak",
             "url": "https://www.vidarflooring.com/test-page/item/72-naked-oak"}]}
        reg = copy.deepcopy(REG)
        reg["suppliers"]["VIDAR"]["product_pages"]["enabled"] = True
        a = plan.build([NAKED_9], {"pages": self.pages}, self.j, idx, reg, "VIDAR", "vidar")["actions"][0]
        self.assertEqual(a["fields"]["Supplier product page"],
                         "https://www.vidarflooring.com/en/product/engineered-hardwood/american-oak-naked-oak")
        self.assertEqual(a["product_page_source"], "manufacturer")

    def test_disabled_product_pages_are_never_used(self):
        """2026-09-29: the search-index Vidar links were dead (Albert: 'go to 404')."""
        self.assertIs(VIDAR["product_pages"]["enabled"], False)
        idx = {"results": [{"title": "9'' Collection American White Oak-Naked Oak",
                            "url": "https://www.vidarflooring.com/en/product/engineered-hardwood/american-oak-naked-oak"}]}
        a = self.build([NAKED_9], self.pages, self.j, idx)["actions"][0]
        self.assertEqual(a["fields"]["Supplier product page"], "https://fb/naked-9")
        self.assertNotIn("vidarflooring.com", json.dumps(a))
        a = self.build([NAKED_9], self.pages, self.j)["actions"][0]
        self.assertEqual(a["fields"]["Supplier product page"], "https://fb/naked-9")
        self.assertIn("product_page_not_manufacturer", a["flags"])

    def test_ids_are_stable(self):
        a1 = self.build([NAKED_9], self.pages, self.j)["actions"][0]["id"]
        a2 = self.build([NAKED_9], self.pages, self.j)["actions"][0]["id"]
        self.assertEqual(a1, a2)
        self.assertTrue(a1.startswith("img-"))

    def test_approval_is_refused_while_plan_only(self):
        reg = copy.deepcopy(REG)
        reg["write_mode"]["mode"] = "plan_only"
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "reg.json").write_text(json.dumps(reg))
            snap = Path(d) / "snap.json"
            snap.write_text(json.dumps({"records": [{"id": NAKED_9["id"], "cellValuesByFieldId": {}}]}))
            pages = Path(d) / "pages.json"
            pages.write_text(json.dumps({"pages": []}))
            rc = plan.main(["--supplier", "VIDAR", "--scope", "t", "--snapshot", str(snap),
                            "--pages", str(pages), "--write-approval", "--date", "1999-01-01",
                            "--registry", str(Path(d) / "reg.json")])
        self.assertEqual(rc, 4)

    def test_policy_approves_only_its_tiers(self):
        p = {"supplier": "VIDAR", "scope": "t", "actions": [
            {"id": "img-a", "match_tier": "exact"}, {"id": "img-b", "match_tier": "model_confirmed"},
            {"id": "img-c", "match_tier": "other"}]}
        appr = plan.approval(p, REG, "plans/x.json")
        self.assertEqual([d["id"] for d in appr["decisions"]], ["img-a", "img-b"])
        self.assertTrue(appr["approved_by"].startswith("policy:"))


class TestTwoSources(unittest.TestCase):
    """Albert, 2026-09-29: 'if the image is clearer or better, use it instead of the floorbox'."""

    def setUp(self):
        from PIL import Image
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        def pic(name, pattern):
            im = Image.new("L", (64, 64))
            im.putdata([(255 if pattern(x, y) else 0) for y in range(64) for x in range(64)])
            im.save(d / name)
            return str(d / name)
        self.stripes = pic("a.png", lambda x, y: (x // 8) % 2 == 0)
        self.stripes2 = pic("b.png", lambda x, y: (x // 8) % 2 == 0 and not (x == 3 and y == 3))
        self.checks = pic("c.png", lambda x, y: ((x // 16) + (y // 16)) % 2 == 0)
        self.reg = copy.deepcopy(REG)

    def tearDown(self):
        self.tmp.cleanup()

    def pg(self, source, url, imgs):
        return {**page(url, "9'' Collection American White Oak-Naked Oak", imgs), "source": source}

    def img(self, sha, w, path):
        return {**img(sha, f"https://cdn/{sha}.jpg", w, round(w * .75)), "read_path": path}

    def build(self, pages, judged):
        j = {"contract_version": "image-judgements-1", "images": judged}
        return plan.build([NAKED_9], {"pages": pages}, j, None, self.reg, "VIDAR", "vidar")

    def test_the_bigger_photo_wins_across_sources(self):
        pages = [self.pg("speers", "https://sp/p", [self.img("sp", 1800, self.checks)]),
                 self.pg("floorbox", "https://fb/p", [self.img("fb", 2100, self.stripes)])]
        a = self.build(pages, {"sp": {"kind": "swatch"}, "fb": {"kind": "swatch"}})["actions"][0]
        self.assertEqual([i["sha1"] for i in a["images"]], ["fb", "sp"])
        self.assertEqual(a["source"], "floorbox")
        self.assertEqual(a["fields"]["Supplier product page"], "https://fb/p")

    def test_a_tie_goes_to_the_earlier_source_and_duplicates_collapse(self):
        """Order is official, The Floor Box, Speers (Albert, 2026-09-29)."""
        pages = [self.pg("speers", "https://sp/p", [self.img("sp", 2100, self.stripes2),
                                                    self.img("rm", 2100, self.checks)]),
                 self.pg("floorbox", "https://fb/p", [self.img("fb", 2100, self.stripes)])]
        a = self.build(pages, {"sp": {"kind": "swatch"}, "fb": {"kind": "swatch"}, "rm": {"kind": "room"}})["actions"][0]
        self.assertEqual([i["sha1"] for i in a["images"] if i["target"] == "swatch"], ["fb"])
        self.assertEqual([i["sha1"] for i in a["images"] if i["target"] == "room"], ["rm"])
        self.assertEqual(a["fields"]["Supplier product page"], "https://fb/p")

    def test_speers_photos_may_be_used_but_speers_is_never_linked(self):
        """'I would not want speers because it is a local shop to ours' (Albert, 2026-09-29)."""
        pages = [self.pg("speers", "https://sp/p", [self.img("sp", 2100, self.checks)])]
        a = self.build(pages, {"sp": {"kind": "swatch"}})["actions"][0]
        self.assertEqual([i["sha1"] for i in a["images"]], ["sp"])
        self.assertNotIn("Supplier product page", a["fields"])
        self.assertIn("no_product_page", a["flags"])

    def test_the_official_site_is_the_first_link(self):
        pages = [self.pg("floorbox", "https://fb/p", [self.img("fb", 2100, self.stripes)]),
                 self.pg("official", "https://brand/p", [self.img("of", 1800, self.checks)])]
        a = self.build(pages, {"fb": {"kind": "swatch"}, "of": {"kind": "swatch"}})["actions"][0]
        self.assertEqual(a["fields"]["Supplier product page"], "https://brand/p")

    def test_sources_follow_the_policy_order(self):
        names = [s["name"] for s in pull.supplier_sources(REG["suppliers"]["BIYORK"], REG)]
        self.assertEqual(names, ["official", "floorbox", "wordofmouth", "speers"])  # Speers last
        self.assertEqual(REG["source_policy"]["product_page_sources"], ["official", "floorbox", "wordofmouth"])
        by = {s["name"]: s for s in pull.supplier_sources(REG["suppliers"]["BIYORK"], REG)}
        self.assertEqual(by["speers"]["listing"]["vendor"], "BiYork")
        self.assertEqual(by["wordofmouth"]["listing"]["vendor"], "BIYORK")

    def test_the_shopify_vendor_filter(self):
        body = json.dumps({"products": [
            {"handle": "a", "title": "Vidar Naked Oak 9\"", "vendor": "Vidar Design Flooring", "images": [], "variants": []},
            {"handle": "b", "title": "Other Naked Oak", "vendor": "Mirage Floors", "images": [], "variants": []}]}).encode()
        f = pull.Fetcher({"fetch": {"delay_seconds": 0}},
                         opener=lambda req, timeout=0: FakeResp(body if req.full_url.endswith("page=1") else b'{"products": []}'))
        self.assertEqual([p["url"] for p in pull.list_shopify(f, "https://sp", "Vidar Design Flooring")],
                         ["https://sp/products/a"])

    def test_split_variants_gives_each_colour_its_own_page_and_photo(self):
        # Floors At Work, 2026-10-22: one listing per collection, a variant per colour.
        prod = {"handle": "9mm-aqua-platinum", "title": "9mm Aqua Platinum", "vendor": "Floors",
                "variants": [{"id": 1, "option1": "Gemini", "sku": None}, {"id": 2, "option1": "Leo", "sku": "L2"},
                             {"id": 3, "option1": "Libra"}],
                "images": [{"src": "https://cdn/gemini.jpg", "variant_ids": [1], "width": 750, "height": 563},
                           {"src": "https://cdn/leo.jpg", "variant_ids": [2]},
                           {"src": "https://cdn/room-all-colours.jpg", "variant_ids": []}]}
        body = json.dumps({"products": [prod]}).encode()
        f = pull.Fetcher({"fetch": {"delay_seconds": 0}},
                         opener=lambda req, timeout=0: FakeResp(body if req.full_url.endswith("page=1") else b'{"products": []}'))
        pages = pull.list_shopify(f, "https://faw", split_variants=True)
        self.assertEqual([(p["title"], p["url"]) for p in pages],
                         [("9mm Aqua Platinum - Gemini", "https://faw/products/9mm-aqua-platinum?variant=1"),
                          ("9mm Aqua Platinum - Leo", "https://faw/products/9mm-aqua-platinum?variant=2")])
        # Only the variant's own photo; the collection-wide one is nobody's. Libra has none: no page.
        self.assertEqual([i["url"] for i in pages[0]["images"]], ["https://cdn/gemini.jpg"])
        self.assertEqual(pages[1]["codes"], ["L2"])
        self.assertEqual(len(pull.list_shopify(f, "https://faw")), 1)  # off by default

    def test_code_only_supplier_never_matches_on_a_colour_title(self):
        # Olympia Tile, 2026-10-22: `White` is in ~200 collections; code or nothing.
        sup = {**REG["suppliers"]["OLYMPIA TILE"]}
        r = {"id": "recOLYMPIA000001", "SKU": "TIL-OLYM-0001", "Product name": "Olympia Motif — White — 48 x 48 (Matte)",
             "Supplier SKU": "IM.MT.WHT.4848.MT", "Category": "Tile / Stone"}
        by_title = page("https://w/p1", "OLYMPIA TILE + STONE - Other Series - Porcelain Tile - White - 48\" x 48\"")
        by_code = {**page("https://w/p2", "OLYMPIA TILE + STONE - Motif Series - Porcelain Tile - White"), "codes": ["IM.MT.WHT.4848.MT"]}
        self.assertEqual(im.match_records([r], [by_title], sup, REG["matching"])[r["id"]]["tier"], "none")
        m = im.match_records([r], [by_title, by_code], sup, REG["matching"])[r["id"]]
        self.assertEqual((m["tier"], m["candidates"][0]["url"]), ("exact", "https://w/p2"))

    def test_tile_sizes_must_agree(self):
        # Gracious, 2026-10-22: one design on a 24x24 page and a 24x48 page.
        r = {"id": "recGRACIOUS00001", "SKU": "TIL-GRAC-0001", "Product name": "Gracious — EUT-35 — 24 x 24", "Category": "Tile / Stone"}
        p24 = page("https://g/p24", "White Matte Tile 24×24 — EUT-35")
        p48 = page("https://g/p48", "White Matte Tile 24×48 — EUT-35")
        m = im.match_records([r], [p24, p48], {}, REG["matching"])[r["id"]]
        self.assertEqual((m["tier"], m["candidates"][0]["url"]), ("exact", "https://g/p24"))
        self.assertEqual(im.match_records([r], [p48], {}, REG["matching"])[r["id"]]["tier"], "none")
        self.assertEqual(im.sizes_in('Royale 23.62 x 23.62'), {(23.62, 23.62)})
        self.assertTrue(im.sizes_agree({(24, 24)}, {(23.62, 23.62)}))

    def test_require_collection_keeps_generic_colours_in_their_collection(self):
        # CIF, 2026-10-22: `Midtown — Bianco` had found `Aldo Bianco 24"x24"`.
        sup = {"require_collection": True}
        r = {"id": "recCIF0000000001", "SKU": "TIL-CIF-0001", "Product name": "CIF Midtown — Bianco — 24 x 24 (Glossy)",
             "Collection": "Midtown", "Category": "Tile / Stone"}
        aldo, mid = page("https://c/aldo", 'Aldo Bianco 24"x24"'), page("https://c/mid", 'Midtown Bianco 24"x24"')
        self.assertEqual(im.match_records([r], [aldo], sup, REG["matching"])[r["id"]]["tier"], "none")
        self.assertEqual(im.match_records([r], [aldo, mid], sup, REG["matching"])[r["id"]]["candidates"][0]["url"], "https://c/mid")
        coded = {**r, "Product name": "CIF Crackle Glass Mosaic — FAOC-5 (Black) — 1 x 1", "Collection": "Crackle Glass Mosaic"}
        self.assertEqual(im.match_records([coded], [page("https://c/f", "Black Crackle Glass 1x1 - FAOC-5")], sup,
                                          REG["matching"])[r["id"]]["tier"], "exact")  # a code colour is enough

    def test_slug_codes_match_a_numbered_record(self):
        # Woden, 2026-10-22: a Wix site whose slugs are the product numbers.
        r = {"id": "recWODEN00000001", "SKU": "LVP-WODN-0001", "Product name": 'Woden SPC 6mm 7" — 603', "Category": "LVP"}
        pages = [page("https://w/product-page/603", ""), page("https://w/product-page/6030-other", "")]
        m = im.match_records([r], pages, {"slug_codes": True}, REG["matching"])[r["id"]]
        self.assertEqual((m["tier"], m["candidates"][0]["url"]), ("exact", "https://w/product-page/603"))
        self.assertEqual(im.code_hint('Woden SPC 11mm 9" — 1105 Silver Mist'), "1105")
        self.assertEqual(im.code_hint('Woden Vermont 6.5" — Charcoal'), "")

    def test_gallery_gives_each_image_its_own_page(self):
        # Canadian Standard / Evergreen, 2026-10-22: a collection page of named colour photos.
        p = {"url": "https://cs/origins/", "title": "Canadian Standard | Origins", "h1": "", "codes": [], "images": [
            {"url": "https://cs/up/Origins-American-Hickory-Greysmith.jpg", "alt": ""},
            {"url": "https://cs/up/Oak-Clay-e1706290826221-qiw0iztihwgft905a9fabjxpxftdrh1rmjulkiekvc.jpg", "alt": ""},
            {"url": "https://cs/up/CanadianStandard_Final-01_white.png", "alt": "Logo"}]}
        out = pull.gallery_pages([p])
        self.assertEqual([x["title"] for x in out], ["Canadian Standard | Origins - Origins American Hickory Greysmith",
                                                     "Canadian Standard | Origins - Oak Clay"])  # the logo is skipped
        self.assertEqual([x["url"] for x in out], ["https://cs/origins/#img0", "https://cs/origins/#img1"])
        self.assertEqual([len(x["images"]) for x in out], [1, 1])

    def test_oakel_series_carry_a_width_and_a_hyphenated_width_reads(self):
        # Oakel City, 2026-10-28: records name `7 Series` and no width; pages say `7-1/2″`.
        self.assertEqual((im.widths_in("Essence 7-1/2″"), im.widths_in("Naked Oak 9-1/4″")), ({7.5}, {9.25}))
        self.assertEqual(im.widths_in('3/4" (18mm)'), set())  # still a thickness
        sup = {"series_widths": {"6": 6, "7": 7.5, "9": 9.25}}
        r = {"id": "recOAKELCITY0001", "SKU": "ENG-OAK-1", "Product name": "Oakel European Oak 3-Ply 7 Series — Essence (Select)",
             "Category": "Engineered hardwood"}
        pages = [page("https://o/essence-6", "Essence 6″"), page("https://o/essence-7", "Essence 7-1/2″")]
        m = im.match_records([r], pages, sup, REG["matching"])[r["id"]]
        self.assertEqual((m["tier"], m["candidates"][0]["url"]), ("exact", "https://o/essence-7"))
        self.assertEqual(im.match_records([r], pages[:1], sup, REG["matching"])[r["id"]]["tier"], "none")

    def test_gallery_label_codes_carry_the_photos_own_code(self):
        # Golden Choice, 2026-10-28: `Laminate 1010's` shows GC1010, GC1011 ... as photos.
        p = {"url": "https://gc/product/laminate-1010s/", "title": "Laminate 1010's", "h1": "", "codes": [], "images": [
            {"url": "https://gc/up/GC1011-scaled.jpg", "alt": ""}, {"url": "https://gc/up/Bronze-scaled.jpg", "alt": ""}]}
        out = pull.gallery_pages([p], label_codes=True)
        self.assertEqual([x["codes"] for x in out], [["1011"], []])
        self.assertEqual(pull.gallery_pages([p])[0]["codes"], [])  # off unless the listing asks
        r = {"id": "recGOLDENCHOICE1", "SKU": "LAM-GC-1011", "Product name": "Golden Choice Laminate 1010's — Solar Oak",
             "Supplier SKU": "1011", "Category": "Laminate"}
        m = im.match_records([r], out, {}, REG["matching"])[r["id"]]
        self.assertEqual((m["tier"], m["candidates"][0]["url"]), ("exact", "https://gc/product/laminate-1010s/#img0"))

    def test_a_label_only_gallery_links_the_labels_own_page_or_none(self):
        # Grandeur, 2026-10-28: each colour page also shows other colours' thumbnails, and 144
        # of 147 links in the first plan went to a different colour's page.
        sard = {"url": "https://g/sardinia.html", "title": "Grandeur Hardwood Flooring", "h1": "", "codes": [], "images": [
            {"url": "https://g/thumb/bora-bora.jpg", "alt": "Bora Bora"},
            {"url": "https://g/thumb/st-lucia.jpg", "alt": "St. Lucia"},
            {"url": "https://g/thumb/wisconsin.jpg", "alt": "Wisconsin(7mm)"}]}
        bora = {"url": "https://g/bora-bora.html", "title": "Grandeur Hardwood Flooring", "h1": "", "codes": [], "images": []}
        lucia = {"url": "https://g/st-lucia.html", "title": "Grandeur Hardwood Flooring", "h1": "", "codes": [], "images": []}
        out = pull.gallery_pages([sard, bora, lucia], label_only=True, alt_only=True)
        self.assertEqual([(x["title"], x["link_url"]) for x in out],
                         [("Bora Bora", "https://g/bora-bora.html"), ("St. Lucia", "https://g/st-lucia.html"),
                          ("Wisconsin(7mm)", None)])  # no crawled page is Wisconsin's: no link
        self.assertNotIn("link_url", pull.gallery_pages([sard])[0])  # a brochure page links itself

    def test_the_suppliers_code_in_the_url_slug_is_a_code_match(self):
        # Floordi, 2026-10-22: `/ashen-breeze-spc-flooring-avr655/` for SKU AVR655.
        r = {"id": "recFLOORDI000001", "SKU": "LVP-FLRD-0001", "Product name": 'Floordi 6.5mm AVO-ROX EASE 7.19" — Ashen Breeze',
             "Supplier SKU": "AVR655", "Category": "LVP"}
        en = page("https://f/ashen-breeze-spc-flooring-avr655/", "Ashen Breeze 6,5mm - Luxury Vinyl Plank")
        tile = page("https://f/ashen-breeze-3mm-glue-down/", "Ashen Breeze 3mm - Glue Down LVT")
        m = im.match_records([r], [tile, en], {}, REG["matching"])[r["id"]]
        self.assertEqual((m["tier"], m["candidates"][0]["url"]), ("exact", "https://f/ashen-breeze-spc-flooring-avr655/"))

    def test_codes_that_disagree_veto_and_a_grade_suffix_still_agrees(self):
        # Impressive, 2026-10-22: Classic Oak Natural 91513-M had taken Paramount NATURAL (91009).
        r = {"id": "recIMPRESSIVE001", "SKU": "91513-M", "Product name": "Impressive Classic Oak — Natural (3-1/4, Select & Better)",
             "Supplier SKU": "91513-M", "Category": "Solid hardwood"}
        other = {**page("https://i/natural/", "NATURAL"), "codes": ["91009"]}
        self.assertEqual(im.match_records([r], [other], {}, REG["matching"])[r["id"]]["tier"], "none")
        ridge = {**r, "Supplier SKU": "91507-M", "Product name": "Impressive Classic Oak — Ridge (3-1/4, Select & Better)"}
        pages = [{**page("https://i/ridge/", "RIDGE"), "codes": ["91507"]}, {**page("https://i/ridge-2/", "RIDGE"), "codes": ["4608"]}]
        m = im.match_records([ridge], pages, {}, REG["matching"])[r["id"]]
        self.assertEqual((m["tier"], m["candidates"][0]["url"]), ("exact", "https://i/ridge/"))

    def test_elementor_background_slideshow_images_are_page_images(self):
        # Purelux, 2026-10-22: a colour's photos live only in Elementor's data-settings.
        html = ('<html><head><title>CARDIFF</title></head><body><div data-settings="{&quot;background_slideshow_gallery'
                '&quot;:[{&quot;id&quot;:1,&quot;url&quot;:&quot;https:\\/\\/p.com\\/up\\/Cardiff-2.jpg&quot;}]}"></div>'
                '<img src="/up/logo.png"></body></html>')
        urls = [i["url"] for i in pull.page_from_html("https://p.com/cardiff/", html)["images"]]
        self.assertIn("https://p.com/up/Cardiff-2.jpg", urls)

    def test_browser_listing_is_asked_for_never_automatic(self):
        tosca = REG["suppliers"]["TOSCA"]["official"]["listing"]
        self.assertEqual(tosca["method"], "browser")
        self.assertTrue(tosca["list_url"].startswith("https://toscaflooring.com/"))
        self.assertTrue((REPO_ROOT / "scripts" / "browser_list.js").exists())

    def test_a_disabled_official_site_is_not_read(self):
        self.assertEqual([s["name"] for s in pull.supplier_sources(REG["suppliers"]["OLYMPIA TILE"], REG)],
                         ["wordofmouth"])


class TestSeoNames(unittest.TestCase):
    """Albert, 2026-09-29: file names for search and AI answers, built from the record."""

    def rec(self, **kw):
        base = {"id": "recAAAAAAAAAAAAAA", "SKU": "ENG-VIDR-0087", "Brand": "Vidar", "Supplier": "VIDAR",
                "Product name": 'Vidar 9" AWO — Wheat Berry (Select & Better)', "Collection": "9 Collection",
                "Category": "Engineered hardwood", "Width (in)": 9, "Grade": "Select & Better"}
        return {**base, **kw}

    def name(self, rec, target="swatch", n=1, url="https://x/a.jpg"):
        return plan.seo_filename(rec, target, n, url, VIDAR, REG["matching"])

    def test_descriptive_name_without_the_internal_sku(self):
        n = self.name(self.rec())
        self.assertEqual(n, "vidar-wheat-berry-american-white-oak-engineered-hardwood-9in-select-and-better-swatch.jpg")
        self.assertNotIn("eng-vidr", n)

    def test_pattern_width_code_and_kind(self):
        hb = self.rec(**{"Product name": 'Vidar HB 5" AWO — Naked Oak (Character)', "Collection": "Herringbone Collection",
                         "Width (in)": 5, "Grade": "Character"})
        self.assertEqual(self.name(hb, "room", 2, "https://x/a.png?v=1"),
                         "vidar-naked-oak-american-white-oak-engineered-hardwood-herringbone-5in-character-room-scene-2.png")
        lam = self.rec(**{"Product name": "Vidar Laminate — NK25", "Category": "Laminate", "Width (in)": 7.5,
                          "Grade": None, "Supplier SKU": "NK25", "Collection": "Laminate Collection"})
        self.assertEqual(self.name(lam), "vidar-nk25-laminate-7-5in-swatch.jpg")

    def test_reattach_plan_touches_only_this_pipelines_files(self):
        ours = self.rec(**{"Swatch images": [{"id": "att1", "filename": "ENG-VIDR-0087-swatch-1.jpg"}],
                           "Room scene images": [{"id": "att2", "filename": "my-own-photo.jpg"}]})
        src = {"actions": [{"record_id": ours["id"], "fields": {
            "Swatch images": [{"url": "https://cdn/s.jpg", "filename": "ENG-VIDR-0087-swatch-1.jpg"}],
            "Room scene images": [{"url": "https://cdn/r.jpg", "filename": "x"}]}}]}
        p = plan.rename_plan([ours], REG, "VIDAR", "t", src)
        a = p["actions"][0]
        self.assertEqual(a["op"], "reattach_renamed")
        self.assertEqual(list(a["fields"]), ["Swatch images"])
        self.assertEqual(a["fields"]["Swatch images"][0]["url"], "https://cdn/s.jpg")
        self.assertEqual(a["expect"]["Swatch images"], [{"id": "att1", "filename": "ENG-VIDR-0087-swatch-1.jpg"}])


class TestRegistryAndProse(unittest.TestCase):
    def test_target_ids_match_the_live_field_registry(self):
        for key, t in REG["targets"].items():
            if key.startswith("_"):
                continue
            self.assertIn(t["id"], FIELDS, key)
            self.assertEqual(FIELDS[t["id"]]["name"], t["name"])
            self.assertEqual(FIELDS[t["id"]]["type"], t["type"])
        for fid in REG["snapshot_fields"]["ids"]:
            self.assertIn(fid, FIELDS)

    def test_write_mode_is_pinned(self):
        # Flipped 2026-09-29 (Albert: "go for it" after the Vidar pilot); change only with a dated decision.
        self.assertEqual(REG["write_mode"]["mode"], "write")

    def test_held_reasons_cover_what_the_planner_emits(self):
        text = (REPO_ROOT / "scripts" / "image_fill_plan.py").read_text()
        for reason in ("no_match", "ambiguous_match", "model_rejected", "no_usable_image",
                       "low_res_swatch", "not_judged", "host_blocked", "all_targets_filled", "nothing_new"):
            self.assertIn(f'"{reason}"', text)
            self.assertIn(reason, REG["held_reasons"])

    def test_scripts_carry_no_airtable_write_verb(self):
        for name in ("supplier_site_pull.py", "image_fill_plan.py", "image_match.py"):
            text = (REPO_ROOT / "scripts" / name).read_text()
            for verb in ("update_records", "create_records", "delete_records", "api.airtable.com"):
                self.assertNotIn(verb, text, f"{name} must stay read-only ({verb})")

    def test_site_urls_live_only_in_the_registry(self):
        cmd = (REPO_ROOT / ".claude" / "commands" / "image-fill.md").read_text()
        self.assertNotIn("thefloorbox.ca", cmd)
        self.assertNotIn("vidarflooring.com", cmd)

    def test_images_are_gitignored(self):
        self.assertIn("ingest/*/supplier-images/", (REPO_ROOT / ".gitignore").read_text())

    def test_agent_log_departments_and_claude_md_agree(self):
        agent = (REPO_ROOT / ".claude" / "agents" / "airtable-actions-agent.md").read_text()
        section = agent.split("### `airtable_attach_images`")[1].split("### ")[0]
        for phrase in ("never upsert", "Read before write", "supplier-sites.json", "stale_not_blank"):
            self.assertIn(phrase, section)
        self.assertIn("`airtable_attach_images`", (REPO_ROOT / "contracts" / "actions-log-schema.md").read_text())
        depts = json.loads((REPO_ROOT / "platform-settings" / "departments.json").read_text())
        cmds = [c for d in depts["departments"].values() if isinstance(d, dict)
                for c in (d.get("owns") or {}).get("commands", [])] if isinstance(depts.get("departments"), dict) else \
            [c for d in depts["departments"] for c in (d.get("owns") or {}).get("commands", [])]
        self.assertIn("image-fill", cmds)
        claude = (REPO_ROOT / "CLAUDE.md").read_text()
        self.assertIn("/image-fill", claude)
        self.assertIn("methods/image-fill.md", claude)


if __name__ == "__main__":
    unittest.main()
