#!/usr/bin/env python3
"""Tests for /image-fill: the matcher, the site pull's parsing and refusal handling, the
planner's blank-only and image rules, the policy gate, and the prose.

    python3 -m unittest discover -s tests -v

Stdlib unittest, fixtures inline. No network: fetches go through a fake opener.
"""

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


def page(url, title, images=()):
    return {"url": url, "title": title, "h1": "", "og_title": "", "product_name": "",
            "codes": [], "images": list(images)}


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

    def test_width_vetoes_and_collection_number_counts(self):
        pages = [page("https://x/6", "American Oak 6 Collection-Naked Oak"),
                 page("https://x/7", "American White Oak 7 Collection - Naked Oak")]
        out = self.m([NAKED_75, NAKED_9], pages)
        self.assertEqual(out[NAKED_75["id"]]["candidates"][0]["url"], "https://x/7")
        self.assertEqual(out[NAKED_9["id"]]["tier"], "none")

    def test_pattern_must_agree_both_ways(self):
        pages = [page("https://x/plank", "Naked Oak"), page("https://x/hb", "Herringbone Naked Oak")]
        out = self.m([NAKED_HB, NAKED_9], pages)
        self.assertEqual([c["url"] for c in out[NAKED_HB["id"]]["candidates"]], ["https://x/hb"])
        self.assertEqual([c["url"] for c in out[NAKED_9["id"]]["candidates"]], ["https://x/plank"])

    def test_species_vetoes(self):
        out = self.m([WALNUT], [page("https://x/o", "White Oak - Natural"), page("https://x/w", "Black Walnut - Natural")])
        self.assertEqual([c["url"] for c in out[WALNUT["id"]]["candidates"]], ["https://x/w"])

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

    def test_small_swatch_never_lands(self):
        p = self.build([NAKED_9], self.pages, self.j)
        self.assertEqual([x["url"] for x in p["actions"][0]["fields"]["Swatch images"]], ["https://cdn/sw.jpg"])

    def test_unjudged_images_are_held(self):
        p = self.build([NAKED_9], self.pages, {"contract_version": "image-judgements-1", "images": {}})
        self.assertEqual(p["held"][0]["reason"], "not_judged")

    def test_watermarked_and_wrong_colour_are_dropped(self):
        j = {"contract_version": "image-judgements-1", "images": {
            "s1": {"kind": "swatch", "watermarked": True}, "r1": {"kind": "room", "colour_matches_page": False},
            "s2": {"kind": "swatch"}}}
        p = self.build([NAKED_9], self.pages, j)
        self.assertEqual(p["held"][0]["reason"], "low_res_swatch")

    def test_ambiguous_needs_a_verdict_and_null_is_respected(self):
        pages = self.pages + [page("https://fb/naked-9b", "9'' Collection American White Oak-Naked Oak", [img("s3", "https://cdn/b.jpg")])]
        self.assertEqual(self.build([NAKED_9], pages, self.j)["held"][0]["reason"], "ambiguous_match")
        j = {**self.j, "matches": {NAKED_9["id"]: {"page": None}}}
        self.assertEqual(self.build([NAKED_9], pages, j)["held"][0]["reason"], "model_rejected")
        j = {**self.j, "matches": {NAKED_9["id"]: {"page": "https://fb/naked-9"}}}
        a = self.build([NAKED_9], pages, j)["actions"][0]
        self.assertEqual(a["match_tier"], "model_confirmed")
        self.assertIn("model_matched", a["flags"])

    def test_product_page_prefers_the_manufacturer(self):
        idx = {"results": [
            {"title": "9'' Collection American White Oak-Naked Oak - Vidar Flooring",
             "url": "https://www.vidarflooring.com/en/product/engineered-hardwood/american-oak-naked-oak"},
            {"title": "American White Oak 9 Collection - Naked Oak",
             "url": "https://www.vidarflooring.com/test-page/item/72-naked-oak"}]}
        a = self.build([NAKED_9], self.pages, self.j, idx)["actions"][0]
        self.assertEqual(a["fields"]["Supplier product page"],
                         "https://www.vidarflooring.com/en/product/engineered-hardwood/american-oak-naked-oak")
        self.assertEqual(a["product_page_source"], "manufacturer")
        a = self.build([NAKED_9], self.pages, self.j)["actions"][0]
        self.assertEqual(a["fields"]["Supplier product page"], "https://fb/naked-9")
        self.assertIn("product_page_not_manufacturer", a["flags"])

    def test_ids_are_stable(self):
        a1 = self.build([NAKED_9], self.pages, self.j)["actions"][0]["id"]
        a2 = self.build([NAKED_9], self.pages, self.j)["actions"][0]["id"]
        self.assertEqual(a1, a2)
        self.assertTrue(a1.startswith("img-"))

    def test_approval_is_refused_while_plan_only(self):
        with tempfile.TemporaryDirectory() as d:
            snap = Path(d) / "snap.json"
            snap.write_text(json.dumps({"records": [{"id": NAKED_9["id"], "cellValuesByFieldId": {}}]}))
            pages = Path(d) / "pages.json"
            pages.write_text(json.dumps({"pages": []}))
            rc = plan.main(["--supplier", "VIDAR", "--scope", "t", "--snapshot", str(snap),
                            "--pages", str(pages), "--write-approval", "--date", "1999-01-01"])
        self.assertEqual(rc, 4)

    def test_policy_approves_only_its_tiers(self):
        p = {"supplier": "VIDAR", "scope": "t", "actions": [
            {"id": "img-a", "match_tier": "exact"}, {"id": "img-b", "match_tier": "model_confirmed"},
            {"id": "img-c", "match_tier": "other"}]}
        appr = plan.approval(p, REG, "plans/x.json")
        self.assertEqual([d["id"] for d in appr["decisions"]], ["img-a", "img-b"])
        self.assertTrue(appr["approved_by"].startswith("policy:"))


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
        self.assertEqual(REG["write_mode"]["mode"], "plan_only")

    def test_held_reasons_cover_what_the_planner_emits(self):
        text = (REPO_ROOT / "scripts" / "image_fill_plan.py").read_text()
        for reason in ("no_match", "ambiguous_match", "model_rejected", "no_usable_image",
                       "low_res_swatch", "not_judged", "host_blocked", "all_targets_filled"):
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
