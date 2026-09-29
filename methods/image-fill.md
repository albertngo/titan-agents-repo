# Method — filling product images from supplier websites (`/image-fill`)

**Why (Albert, 2026-09-29):** "comb through the supplier's website (I can supply) to find
the product images; analyze them; and then download and attach them into the swatch,
room, details airtable rows itself. This way the database starts filling itself out."
On that date `Swatch images`, `Room scene images` and `Detail images` were empty on all
8,253 catalogue records, and `/style-tag` holds every colour tag until a swatch exists.

## Decisions (2026-09-29, Albert)

| Question | Answer |
|---|---|
| Pilot supplier | A wood/vinyl supplier → **Vidar** |
| After the pilot | **Auto-attach, report held** — policy approves confident matches; the rest goes to the held CSV + push |
| Record where images came from | **Yes** — new URL field `Supplier product page` (`flduFw93z4YwnOA3I`), created that day |
| Which page goes in that field | "the product image page should still be from vidar's main site if possible" |

## What the sites allowed (2026-09-29)

- `vidarflooring.com` answers every automated request — pages and image files — with
  SiteGround's anti-bot challenge (`sg-captcha: challenge`, HTTP 202). Airtable's servers
  would meet the same wall fetching an image to attach. **The run does not try to get
  past a challenge.**
- Its product pages ARE in the search index, with titles like
  `9'' Collection American White Oak-Naked Oak` at `/en/product/engineered-hardwood/<slug>`.
  So the manufacturer's page for `Supplier product page` comes from the index
  (WebSearch, allowed to Vidar's hosts), matched by title — reading an index, not the site.
- Albert pointed the images at **The Floor Box** (`thefloorbox.ca`), a retailer. Its
  pages are behind Cloudflare's challenge too (`cf-mitigated: challenge`); its robots.txt
  allows all and names a sitemap on `cdn.thefloorbox.ca`, which is the route the pull
  uses (sitemap `<image:image>` entries map images to products without loading a page).
  Status of that host at the time of writing: being added to the environment's allowlist.
- A retailer's photo may be the retailer's own rather than the manufacturer's. Every
  written record carries its source link, so a later swap is traceable.

## Matching (why colour-in-title, and why vetoes)

Vidar publishes no codes for engineered or laminate, so the key is the colour from
`Product name` (`Vidar 7.5" AWO — Naked Oak (Character)` → `Naked Oak`). It must appear
in a page's **title** — never body text, where a generic colour like `Natural` is
everywhere, and never the URL slug when a title exists (`/naked-oak-daybreak` is the
Daybreak page). Then:

- **Width** — the page's widths (`9''`, `6 Collection`) must include the record's width
  or its collection number (`7 Collection` covers a 7.5" plank), else veto.
- **Species** — `AWO` / `EWO` / `ABW` / `HICKORY` words per the registry; a page naming a
  different species is vetoed.
- **Pattern** — herringbone, chevron, click, versailles, SPC, laminate must agree both
  ways: a herringbone record never takes a plank page, and vice versa.
- **Grade** — only vetoes when the page names a grade the record is not.

One page's images may go to every grade record of that colour and width, because the
site shows one photo per colour. The contact sheet shows the grouping.

## Image rules

The model looks at every downloaded image (a 1568 px read copy) and says what it is.
`swatch` needs a long edge ≥ 1600 px (the field's own description). Watermarked images
and ones that are plainly not the page's colour are dropped. Duplicates collapse by
content hash; largest first; caps 2 swatch / 4 room / 4 detail.

## What it never does

Replace or append to a filled image field; write anything but the four target fields;
write while `write_mode` is `plan_only`; get past a bot challenge; guess a URL.

## Log

- 2026-09-29 — built; registry, contract, scripts, agent type `airtable_attach_images`,
  field `Supplier product page`. `plan_only`. Pilot pending the CDN host.
