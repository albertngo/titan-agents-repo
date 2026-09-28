# Price List URL evidence — shared brief (read-only job)

Goal: every active Airtable product gets a link to the **newest currently-effective price list
file that actually contains it**. You are gathering the evidence only. **Write nothing to
Notion, Airtable, SharePoint or any repo.** Only write files under this scratch folder:
`/tmp/claude-0/-home-user/76d57711-847c-5283-bc9a-14bed1b0f8d4/scratchpad/pl/`.

## Inputs
- `airtable_active.json` (this folder): all 7,852 active products:
  `{rec, sku, supplier, eff, url, collection, supplier_sku, name}`. `url` non-null = already linked, skip.
- Notion **Price Lists** data source `collection://e2dc37bc-63da-42e9-b6c0-63ff48d72e6b`
  (query with `mcp__Notion__notion-query-data-sources`, SQL; fetch a row with `mcp__Notion__notion-fetch`).
  Useful columns: `Company`, `Email Subject`, `date:Email Date:start`, `date:Effective Date:start`, `Tags`,
  `Notes`, `userDefined:ID` (PL number), `Extracted Files`, `Files & media`.
  - SQL returns `Files & media` only as file ids. **Fetch the page** to get the link: the property is
    `file://<url-encoded JSON>`; URL-decode it and take `.source` — an
    `https://flooruca-my.sharepoint.com/...` share link. That link is what gets written. Never invent one.
  - One email with several attachments = several rows (one file each). Each row is its own list.
- Committed upload CSVs in `/home/user/titan-agents-repo/ingest/**/*airtable_upload*.csv` (columns `SKU`,
  `Supplier SKU`, …). The Notion row's `Extracted Files` / `Notes` name the CSV it produced.
- The files themselves: `flooruca-my.sharepoint.com` is blocked by this container's network, so **do not
  curl it**. Read files through the Microsoft 365 connector instead: `mcp__Microsoft_365__sharepoint_search`
  (e.g. query the supplier name, folder `Price List (Attachments)`), then `mcp__Microsoft_365__read_resource`
  with the returned `file:///…` URI (PDF pages via startPage/endPage). Pair a drive file to its Notion row
  by supplier + name + date (drive `lastModifiedDateTime` ≈ Email Date); say how you paired it.
  Load deferred tools with ToolSearch (`select:mcp__Microsoft_365__read_resource,...`) first.

## Which lists count
- Tags `Regular List` (or a clearly-priced list tagged otherwise — say why). Skip marketing flyers,
  vanity/door/non-flooring lists unless the supplier's Airtable products are those items.
- **Effective on or before 2026-09-28.** A list effective later (e.g. TRIFOREST PL-382, Oct 1) is excluded.
- `list_date`: the row's Effective Date if set; else the date printed in the file or subject
  ("Effective Aug 1, 2026" → 2026-08-01; month only → the 1st); else the Email Date. Record which.

## Output — one file per Airtable supplier: `evidence/<SUPPLIER>.json`
```json
{
  "supplier": "OLYMPIA TILE",
  "lists": [
    {"pl_id": "PL-288", "notion_url": "https://app.notion.com/...", "sharepoint_url": "https://flooruca-my.sharepoint.com/...",
     "list_date": "2026-01-26", "list_date_source": "printed", "subject": "...",
     "evidence": "upload_csv:ingest/2026-09-09/x.csv | notion_note | file_read:<drive file name>",
     "match_by": "sku" | "supplier_sku" | "all_supplier_products",
     "codes": ["..."]}
  ],
  "unmatched_note": "what you could not place and why"
}
```
- Order `lists` newest first. `codes` = the product codes that list carries, in the form `match_by` names
  (Airtable `sku` from a CSV, or supplier codes read from the file — normalise to upper case, trimmed;
  keep Airtable's own punctuation where the file differs only by it, and say so).
- `all_supplier_products` only when a Notion note states the list was verified to cover every live
  product of that supplier (e.g. Olympia PL-288), with `codes: []`.
- Before you finish, check your `codes` actually hit: count how many of this supplier's unlinked products
  in `airtable_active.json` match each list, and put the counts in `unmatched_note`.
- Report back in under 200 words: per supplier, lists found, products matched / unlinked, anything odd.
  Do not paste file contents back.
