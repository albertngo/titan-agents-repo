# Image plan, judgements and approval — `/image-fill`

Contract for the three files between the read-only scripts and the one write
(`airtable-actions-agent`, type `airtable_attach_images`). Registry:
`platform-settings/supplier-sites.json`. Method: `methods/image-fill.md`.

## `ingest/<date>/supplier-pages-<scope>.json` — `supplier-pages-1`

Written by `scripts/supplier_site_pull.py`. `status` is `ok`, `empty`, `challenged` (the
site answered with a bot challenge — never worked around) or `host_blocked` (the
environment's network policy). `pages[]`: `url`, `title`, `h1`, `og_title`,
`product_name`, `is_product`, `codes[]`, `images[]` (`url`, `alt`, and after download
`sha1`, `width`, `height`, `read_path`, `status`). Local paths point into the gitignored
`ingest/<date>/supplier-images/<scope>/`.

## `ingest/<date>/product-page-index-<scope>.json` — optional

The manufacturer's own product pages, from the search index when its site cannot be read
directly. `{"source": "WebSearch", "queries": [...], "results": [{"title", "url"}]}`.
Only URLs under the supplier's `product_pages.hosts` + `path_prefix` are used.

## `ingest/<date>/image-judgements-<scope>.json` — `image-judgements-1`

Written by the session model after reading `image-todo-<scope>.json`:

```json
{
  "contract_version": "image-judgements-1",
  "images": {
    "<sha1>": {"kind": "swatch|room|detail|spec_sheet|other",
               "watermarked": false, "colour_matches_page": true, "note": "short"}
  },
  "matches": {
    "<record_id>": {"page": "<one candidate url>" , "why": "short"}
  }
}
```

- `kind` is what the picture IS: `swatch` = a clean flat plank/tile face, no room;
  `room` = installed or lifestyle; `detail` = close-up of texture, edge, bevel, profile,
  cross-section or box; `spec_sheet` / `other` go nowhere.
- `colour_matches_page: false` when the photo plainly is not the colour the page names.
- `matches` only for records the todo lists as ambiguous. `"page": null` means none of
  the candidates is this product — a valid, preferred answer when unsure.

## `plans/<date>/image-plan-<scope>.json` — `image-plan-1`

Top level: `scope`, `supplier`, `run_at`, `expires` (end of day), `write_mode`,
`inputs`, `summary`, `actions[]`, `held[]`.

Action:

| key | meaning |
|---|---|
| `id` | `img-` + sha1(`sku` + fields)[:12] — stable across re-runs |
| `op` | `attach_images` |
| `record_id`, `sku`, `product_name` | the target record (SKU is never written) |
| `fields` | field NAME → value: attachment fields get `[{url, filename}]`, `Supplier product page` a URL |
| `field_ids` | the same fields by id |
| `expect_blank` | every field in `fields`; the writer drops any that is no longer blank |
| `source_page`, `match_tier` | where the images came from; `exact` or `model_confirmed` |
| `product_page_source` | `manufacturer` (search-index match) or `image_page` |
| `images` | `target`, `url`, `sha1`, `width`, `height` per attached image |
| `flags` | `no_swatch`, `model_matched`, `product_page_not_manufacturer` |

`held[]`: `sku`, `record_id`, `product_name`, `reason` (a key of the registry's
`held_reasons`), `detail`, `candidate_pages`. Held rows carry no `id` and cannot be approved.
They are also written to `image-troubled-<scope>.csv`, and `image-contact-<scope>.html`
shows every action's images beside its record for review.

## `plans/<date>/image-approval-<scope>.json` — `image-approval-1`

`{plan, approved_by, decisions: [{id, status: "approved", at}]}`. Written only by
`scripts/image_fill_plan.py --write-approval`, only while `write_mode` is `write`, and only
for tiers in `policy.auto_approve_tiers`, capped at `policy.max_actions_per_run`.
**No approval file means nothing is approved.**
