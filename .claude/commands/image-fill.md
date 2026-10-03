---
description: Fill a supplier's blank Swatch / Room scene / Detail image fields in Airtable from supplier and retailer websites, with descriptive SEO file names. Builds a reviewable plan, applies policy, writes only what is approved (write mode since 2026-09-29).
---

# /image-fill `<SUPPLIER>`

Albert, 2026-09-29: "comb through the supplier's website … find the product images;
analyze them; and then download and attach them into the swatch, room, details airtable
rows itself. This way the database starts filling itself out."

Registry `platform-settings/supplier-sites.json` · contract `contracts/image-plan-schema.md`
· method `methods/image-fill.md`. Same shape as `/style-tag`. Not scheduled, not part of
`/daily-ingest`.

`<SUPPLIER>` is a key under the registry's `suppliers` (e.g. `VIDAR`); `<scope>` is its
lower-case slug. No entry → stop and ask Albert for the site URL; never put a URL in a prompt.

## Before you start

1. `curl -sS -o /dev/null -w "%{http_code}" <site>` for the supplier's `site` and each
   `hosts` entry. A proxy refusal (`CONNECT tunnel failed, 403`) → name the host and stop:
   it goes in the environment's Network access. A bot challenge (`cf-mitigated: challenge`,
   `sg-captcha`, HTTP 202/403 with a challenge page) → stop and report it; **never try to
   get past a challenge**, and do not suggest ways to.
2. `write_mode` in the registry: `plan_only` (default) ends at the contact sheet.

## Steps

1. **Snapshot.** MCP `list_records_for_table`, base/table from the registry, `fieldIds` =
   `snapshot_fields.ids`, filtered to the supplier's `Supplier` option (choice id from
   `get_table_schema`). Save the raw output as `ingest/<date>/<scope>_image_snapshot.json`.
2. **Pull.** `python3 scripts/supplier_site_pull.py --supplier <SUPPLIER> --scope <scope>
   --snapshot <snapshot> --download`. Exit 3 = challenged / host_blocked (any source the
   environment refuses, the official site included) → report, stop.
3. **Manufacturer pages** (only if the supplier entry has `product_pages`). Its site may be
   unreadable directly, so use **WebSearch** with `allowed_domains` = `product_pages.hosts`,
   one query per collection and colour family, and save every result's title + url to
   `ingest/<date>/product-page-index-<scope>.json` (contract). Record only what the index
   returned; never invent or pattern-guess a URL.
4. **Prepare.** `python3 scripts/image_fill_plan.py --supplier <SUPPLIER> --scope <scope>
   --snapshot <snapshot> --pages ingest/<date>/supplier-pages-<scope>.json --prepare`.
5. **Judge.** Read `ingest/<date>/image-todo-<scope>.json`. Open every `read_path` image
   (Read tool) and write `ingest/<date>/image-judgements-<scope>.json` per the contract:
   kind, watermarked, colour_matches_page. For each ambiguous record pick at most one
   candidate page, or `null`. Unsure is `null`; a wrong photo is worse than none.
6. **Plan.** Same command without `--prepare`, plus `--judgements` and (if step 3 ran)
   `--product-pages`, plus `--write-approval` only when `write_mode` is `write`. Writes the
   plan, `image-contact-<scope>.html` and `image-troubled-<scope>.csv` under `plans/<date>/`.
7. **Act** (write mode only). Hand the plan + approval file to `airtable-actions-agent`
   (type `airtable_attach_images`), ≤50 records per batch. It logs to
   `ingest/<date>/actions-log.json`.
8. **Report.** Counts per field, held by reason, the contact sheet path; PushNotification
   when anything is held. Commit the pages file, judgements, index, plan, contact sheet,
   troubled CSV and log (the images folder is gitignored), push, and open the PR per the
   repo's git workflow.

## Names, alt text and schema (SEO / AEO, Albert 2026-09-29)

- Files are named from the record's fields by `seo_filename`:
  `brand-colour-species-category-pattern-width-grade-code-kind[-n].ext`
  (`vidar-naked-oak-american-white-oak-engineered-hardwood-9in-select-swatch.jpg`). The
  internal SKU is never in a file name; the supplier's own code is.
- Files attached before this rule: `--rename-to-seo --source-plan <that run's plan>`
  plans a re-attach of the same source images under the new names (Airtable's API ignores
  a rename). Only fields whose every file carries the old `<SKU>-<kind>-<n>` name are
  touched; the writer checks the live files against `expect` first.
- The website should build **alt text** and **Product JSON-LD** from the same fields;
  the recipe is in bert-airtable-schema, "Product images". Those carry more weight than
  the file name.

## Sources, in order (Albert, 2026-09-29)

"search the main website -> externals (floorbox and speers) but the link to the product url
page should be from the official company website; otherwise pick the floorbox as the
backup. I would not want speers because it is a local shop to ours."

Then, same night: "lets use wordofmouthfloors.com as the 2nd/third backup same level as
floorbox. and speers as the very last."

- Registry `source_policy.order`: the supplier's `official` site, then The Floor Box and
  Word of Mouth Floors (peers), then Speers last (`retailers`, shared; a supplier names only
  the retailers that carry it and its overrides, e.g. the Shopify `vendor` string).
- Each source is matched on its own; per field the larger photo wins, a tie goes to the
  earlier source, and the same photo from two sites (visual fingerprint within 6 bits) is
  kept once. Speers photos may be used; **a Speers page is never linked**.
- `Supplier product page` = the official page, else The Floor Box, else Word of Mouth
  (`source_policy.product_page_sources`). None → left blank, flag `no_product_page`.
- A lower quality photo beats none (Albert, 2026-10-03): the size bar is 300 px, against icons
  and thumbnails only. A supplier may still set its own `image_rules`.
- Links an earlier run put on a source that may no longer be linked: `--relink-product-page-from
  speers --source-plan <that run's plan>` (op `relink_product_page`, compare-and-swap; no
  alternative keeps the old link).
- A Shopify store's tags and product type count for line and species (BiYork's own shop
  titles products `Brume Air Sample*`); of their pattern words only `tag_pattern_words`
  count, since a `SPC Floors` tag is a department, not a pattern.
- An official site the **environment** refuses (`host_blocked`) stops the run: the retailers
  would fill the blank fields first and blank-only means the official photos could never
  replace them. Allow the host and re-run. An official site behind a **bot challenge**
  (Vidar) is permanent, so the retailers run alone.
- Accessories (`image_rules.skip_categories`) are skipped. A supplier that reuses colour
  names across product lines lists `lines` (BiYork); the page must name the record's line
  and number, or it is vetoed.

## Rules that do not bend

- **Blank only.** A field that holds anything — a person's upload, an earlier run's — is
  never replaced or appended to. The writer re-checks at write time.
- The kind comes from looking at the image; the largest photo per field goes first.
- Never write `SKU`, `Colour / tone`, style tags, or any field outside the closed list.
- `Supplier product page` is never a Speers page (see Sources).
