---
description: Fill a supplier's blank Swatch / Room scene / Detail image fields in Airtable from the supplier's website. Builds a reviewable plan, applies policy, writes only what is approved. plan_only until deliberately flipped.
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
   --snapshot <snapshot> --download`. Exit 3 = challenged / host_blocked → report, stop.
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

## Rules that do not bend

- **Blank only.** A field that holds anything — a person's upload, an earlier run's — is
  never replaced or appended to. The writer re-checks at write time.
- The kind comes from looking at the image; a swatch must meet `min_swatch_long_edge_px`.
- Never write `SKU`, `Colour / tone`, style tags, or any field outside the closed list.
- `Supplier product page` is the manufacturer's page when the index matched it, else the
  page the images came from (flag `product_page_not_manufacturer`).
