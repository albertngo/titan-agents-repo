# Website architecture — titanfloors.ca on Next.js

> The file `titan-website/README.md` has pointed at since its first commit. Written
> 2026-10-07 in Phase 1 of the content engine; the earlier "full architecture, rationale
> and migration plan" it promised never landed in this repo.

## What it is

`albertngo/titan-website` is the rebuild of titanfloors.ca off WordPress: Next.js 16,
React 19, TypeScript, deployed on Vercel. Phase 1 of the site (2026-09) shipped the
homepage. Phase 1 of the content engine (2026-10-07) adds the blog.

## Two thin data modules, no live platform reads

The public site reads **nothing live**. Facts it shows are copied by hand from this repo:

- `lib/site.ts` ← `platform-settings/website.json` (NAP, nav, taglines, core values).
- `content/blog/*.mdx` ← written by the content engine's `blog-actions-agent` through a
  pull request, from a Notion Blog Posts row (`contracts/blog-mdx-schema.md`).

A page therefore never depends on Notion, Airtable or GoHighLevel being up, and a bad
value is a reviewable diff, not a live mystery.

## Blog

- **URLs are flat**: `/<slug>/`, trailing slash, never `/blog/<slug>/` (Albert's "AEO Site
  Architecture Blueprint", 2026-10-06; decision Q14). `/blog/` is the index. The 106
  WordPress posts keep their slugs when imported (Phase 1b), so nothing ranking moves.
- **Hierarchy lives in links**, not folders: a spoke's `pillar` and `siblings` come from
  frontmatter; a pillar lists its spokes by scanning every post whose `pillar` is its
  slug, so adding a spoke never edits the pillar file.
- **Render order on a post**: title → the 40–60-word direct answer (`snippet`) → YouTube
  embed if `videoUrl` → body → FAQ → "Part of our … guide" + related posts → JSON-LD
  (`Article`, `FAQPage`, `VideoObject`, `BreadcrumbList`).
- **No dependencies added** for the blog (2026-10-07): the cloud environment's npm access
  is blocked, so the loader, a strict frontmatter reader (one JSON value per line) and a
  small Markdown renderer for the subset the engine emits live in `lib/`. Swapping in a
  real MDX toolchain later is a loader change; the files do not change.
- **`scripts/validate-content.mjs`** runs before `next build` and fails the build on any
  file that breaks the contract (bad slug, snippet length, FAQ count, unknown cluster).
  That is what makes the pull-request check meaningful.
- **Reserved slugs** (`platform-settings/content-engine.json` → `website.reserved_slugs`)
  can never be a post: the root dynamic segment would otherwise shadow a real page.

## Until DNS cuts over

Vercel's production URL is "live" for the engine's sweep (decision Q14); `Direct URL` on
a Blog Posts row carries that host until cut-over, then is rewritten to titanfloors.ca in
one pass. The 106 legacy posts must be imported (Phase 1b) before the cut-over can happen.

The site's canonical origin (`<link rel="canonical">`, sitemap, JSON-LD) is `siteUrl` in
`lib/site.ts`: `NEXT_PUBLIC_SITE_URL` if set in Vercel, else Vercel's own
`VERCEL_PROJECT_PRODUCTION_URL`, else `https://titanfloors.ca`. The sweep compares the
page's canonical with `website.production_host` in `content-engine.json`, so the two are
changed together: set the env var to the Vercel host now, and flip both to titanfloors.ca
in the cut-over pass. A mismatch is reported as `url_mismatch`, never written.

## UTM stamping (Phase 3)

Every call-to-action on a post goes through a `CtaLink` that appends
`utm_source=blog&utm_medium=organic&utm_campaign=<cluster slug>`, so a lead that comes
in through the GoHighLevel form carries the cluster into the contact's `UTM_*` fields and,
on a won deal, into Titan Projects `Campaign`.

## Log

- 2026-10-07 — created with the blog route (content engine Phase 1). Route built the same
  day on titan-website branch `claude/titan-content-engine-plan-1qyhr6`: `app/[slug]/`,
  `app/blog/`, `lib/blog.ts`, `lib/blog-schema.mjs` (+ `.d.mts`), `lib/markdown.ts`,
  `components/blog/*`, `app/sitemap.ts`, `scripts/validate-content.mjs` wired into
  `build`, `trailingSlash: true`. Typechecked against stub declarations only (npm registry
  blocked in the cloud environment); the first Vercel build is the real check.
