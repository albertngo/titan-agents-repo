# Website inventory — method

Governs `analysis/website_inventory.py` (tier 1: pages hundreds of records, needs a
cache, re-run at cutover). Companion to `methods/website-architecture.md`, which this
feeds — the redirect map it produces is what makes cutover safe.

## What counts as a real page

A published page or post that a human could land on from Google, a bookmark, or an ad —
i.e. anything with `status: publish`. Drafts, revisions, and Elementor's own internal
screenshot attachments are not real pages and are excluded from the redirect map (they
never had a public URL to preserve).

Distinguish three families explicitly, because they get different treatment:

1. **Real content** — blog posts, the core pages (home, about, contact, FAQ, the two
   service hubs). These migrate as MDX files with identical slugs. No redirect needed
   unless the slug itself changes.
2. **Programmatic city pages** — the LPagery "{service} × {city}" template. These
   collapse into one template + `data/cities.json` in the new site. A city page's URL is
   preserved if the city survives the keep/consolidate decision (see below); otherwise it
   301s to its parent city or service hub.
3. **Dead weight** — WooCommerce product/category URLs, leftover theme-demo pages
   (`/furniture-04-2/`, `/columns/`, `/cart-2/`, `/wishlist1/`, and similar), and any page
   with zero organic traffic in the Search Console export. These get a single 301 to the
   nearest live equivalent (the new catalogue for products, the homepage for demo pages)
   — never left as a 404, and never silently dropped without a rule recorded in the
   redirects CSV.

## Slug-typo rule

A URL that is plainly a typo of the intended one (`lamiante-flooring-mississauga`,
`vinyl_flooring_oakville` with an underscore where every sibling uses a hyphen) is
corrected in the new site and 301-redirected from the old, broken spelling. The old,
broken spelling is never reproduced on purpose — Google has already indexed it and the
redirect is what carries that credit forward, not the typo itself.

## Redirect precedence

When more than one rule could apply to the same old URL, apply the first that matches,
in this order:

1. An explicit slug-typo fix (above) — always wins, since the destination is unambiguous.
2. A programmatic city page whose city survives — redirect to the same city page,
   regenerated on the new template (same final URL where possible; otherwise the closest
   equivalent path).
3. A programmatic city page whose city does not survive (Search Console shows no
   clicks) — redirect to its parent city's page for the same service, or to the service
   hub if no parent city page exists.
4. A WooCommerce product URL (`/product/*`) — redirect to the category-level page in the
   new catalogue (product-level redirects aren't possible; Woo SKUs don't match Airtable
   SKUs, so there's no reliable one-to-one target).
5. A WooCommerce category URL (`/product-category/*`) — redirect to the matching
   category in the new product finder.
6. A leftover theme-demo page — redirect to the homepage.
7. Anything unmatched by the above — flag in the CSV as `needs_manual_call`, never
   silently dropped.

## Search Console join method

Search Console access could not be read through this session's WordPress connection
(Site Kit requires a Google-session OAuth scope this connector doesn't carry). Until
Albert exports it manually:

1. In Google Search Console, export **Performance → Pages** for the maximum available
   window (up to 16 months).
2. Save the export into `analysis/cache/website/search-console-pages.csv` (gitignored —
   it's raw external data, not a repo artifact).
3. Re-run `analysis/website_inventory.py --gsc analysis/cache/website/search-console-pages.csv`
   to join click counts onto the inventory and populate the "keep vs. consolidate"
   column in the redirects CSV.

Until that export exists, every city page defaults to "keep" in the redirects CSV — the
script never consolidates a page on its own guess.

## Output files

- `analysis/output/website-inventory-<date>.json` — the full crawl: pages, posts,
  products (with SKU/category/image as a crosswalk against the old WooCommerce catalogue,
  useful only as a hint since Woo SKUs don't match Airtable's), media (with an alt-text
  flag), categories, menus, and Rank Math title/description where the public REST
  exposes them.
- `analysis/output/website-redirects-<date>.csv` — one row per old URL: the URL, the
  rule that matched it (from the precedence list above), the proposed target, and
  (once the Search Console join has run) whether it's a keep or a consolidate candidate.

Both are committed — they're small, text, and exactly the kind of "reviewable diff"
artifact this repo already keeps for other pipelines.
