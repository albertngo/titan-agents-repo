#!/usr/bin/env python3
"""Tests for the read-only website inventory script and its redirect output.

Stdlib unittest, no pytest — matching the repo's stdlib-first script convention.

    python3 -m unittest discover -s tests -v
"""

import csv
import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "analysis"))


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


wi = _load("website_inventory", "analysis/website_inventory.py")

REDIRECTS_CSV = REPO_ROOT / "analysis" / "output" / "website-redirects-2026-09-12.csv"


class TestNoWritePath(unittest.TestCase):
    """This script only ever reads a public API. It must never grow a write verb."""

    def test_no_write_verbs(self):
        src = (REPO_ROOT / "analysis" / "website_inventory.py").read_text()
        for verb in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertNotIn(f'"{verb}"', src,
                              f"website_inventory.py contains a {verb} literal — the "
                              "read-only guarantee in its docstring is no longer true")

    def test_no_wp_credential_used(self):
        # Checks for actual credential *usage* (a header, an env var read) — not the
        # module's own explanatory comments, which legitimately name these terms.
        src = (REPO_ROOT / "analysis" / "website_inventory.py").read_text()
        for forbidden in ("add_header(\"Authorization\"", "WP_APP_PASSWORD", "os.environ"):
            self.assertNotIn(forbidden, src,
                              "this script must only call public, unauthenticated "
                              "WordPress REST endpoints")


class TestRedirectClassification(unittest.TestCase):
    def test_slug_typo_fix(self):
        target, rule = wi.classify_redirect("/flooring-install/lamiante-flooring-mississauga/")
        self.assertEqual(rule, "slug_typo_fix")
        self.assertIn("laminate-flooring-mississauga", target)

    def test_underscore_typo_fix(self):
        target, rule = wi.classify_redirect("/flooring-install/vinyl_flooring_oakville/")
        self.assertEqual(rule, "slug_typo_fix")
        self.assertNotIn("_", target)

    def test_wrong_parent_fix(self):
        target, rule = wi.classify_redirect("/stair-refinishing/vinyl-flooring-hamilton/")
        self.assertEqual(rule, "wrong_parent_fix")
        self.assertTrue(target.startswith("flooring-install/"))

    def test_woo_category_redirect(self):
        target, rule = wi.classify_redirect("/product-category/laminate/")
        self.assertEqual(rule, "woo_category_to_catalogue")
        self.assertIn("catalogue/category/laminate", target)

    def test_woo_product_redirect(self):
        target, rule = wi.classify_redirect("/product/some-product-slug/")
        self.assertEqual(rule, "woo_product_to_catalogue_root")

    def test_demo_page_redirect(self):
        target, rule = wi.classify_redirect("/cart-2/")
        self.assertEqual(rule, "demo_page_to_home")

    def test_real_content_page_is_unmatched_by_default(self):
        # A real page (or a city page, pending the Search Console review) matches none
        # of the explicit rules — it keeps its own URL. See methods/website-inventory.md.
        target, rule = wi.classify_redirect("/about-us/")
        self.assertEqual(rule, "needs_manual_call")
        self.assertIsNone(target)


class TestRedirectsCsv(unittest.TestCase):
    """The committed redirect CSV must contain only rows that actually redirect
    somewhere — a page that keeps its own URL has no business in this file."""

    def setUp(self):
        if not REDIRECTS_CSV.exists():
            self.skipTest("redirects CSV not generated yet")
        with REDIRECTS_CSV.open(newline="") as f:
            self.rows = list(csv.DictReader(f))

    def test_no_self_redirects(self):
        for row in self.rows:
            self.assertNotEqual(
                row["old_url"], row["proposed_target"],
                f"{row['old_url']} redirects to itself — that's not a redirect")

    def test_every_row_has_a_rule(self):
        for row in self.rows:
            self.assertNotEqual(row["rule"], "", f"{row['old_url']} has no rule recorded")

    def test_no_duplicate_old_urls(self):
        urls = [row["old_url"] for row in self.rows if "*" not in row["old_url"]]
        self.assertEqual(len(urls), len(set(urls)),
                          "a URL appears more than once in the redirect map")

    def test_no_manual_call_rows_leak_into_the_csv(self):
        # needs_manual_call rows belong in the inventory JSON's "kept as-is" list, not
        # here — see the split performed when this file was generated.
        for row in self.rows:
            self.assertNotEqual(row["rule"], "needs_manual_call")


if __name__ == "__main__":
    unittest.main()
