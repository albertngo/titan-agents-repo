# Blog post file contract (`blog-mdx-1`)

The one file the content engine writes into `albertngo/titan-website`:
`content/blog/<slug>.mdx`. Produced by `scripts/blog_render.py` from a Blog Posts row and
its body; validated by the same script (`--check`) and again by the site's own
`scripts/validate-content.mjs` at build time, so a bad file fails the Vercel check before
anyone looks at a preview.

The body is plain Markdown (an `.mdx` file with no JSX). The site renders a controlled
subset: `##` / `###` headings, paragraphs, `-` lists, `1.` lists, `**bold**`, `*italic*`,
`[text](url)`, pipe tables, and `>` quotes. Nothing else is emitted and nothing else is
rendered.

## Frontmatter

YAML, one key per line, **every value JSON-encoded** (strings quoted, arrays and objects
inline). YAML is a superset of JSON, so any YAML reader accepts it, and the site's loader
needs only `JSON.parse` per line.

```yaml
---
schema: "blog-mdx-1"
blogId: "BP-7"
notionPageId: "2f3596a4-…"
title: "Is laminate flooring waterproof?"
slug: "is-laminate-flooring-waterproof"
description: "Most laminate is water-resistant, not waterproof. Here is what that means for a GTA kitchen or basement."
snippet: "…40–60 words, the direct answer…"
keyword: "laminate flooring waterproof"
intent: "Informational"
cluster: "waterproof"
material: ["Laminate"]
contentType: "Supporting Content"
pillar: null
siblings: []
publishDate: "2026-10-14"
updatedDate: null
videoUrl: null
faq: [{"q": "…", "a": "…"}, {"q": "…", "a": "…"}, {"q": "…", "a": "…"}]
legacy: null
---
```

| Key | Rule |
|---|---|
| `schema` | exactly `blog-mdx-1` |
| `blogId` | `BP-<n>`; the round-trip key to Notion |
| `notionPageId` | the page id |
| `title` | the H1, the question as typed; ≤ 110 chars |
| `slug` | `^[a-z0-9]+(?:-[a-z0-9]+)*$`, ≤ 70, not in the registry's `reserved_slugs`; equals the file name |
| `description` | ≤ 160 chars, the meta description |
| `snippet` | 40–60 words |
| `keyword` | non-empty |
| `intent` | `Informational` / `Commercial` / `Navigation` / `Transaction` (the registry spelling, not Notion's) |
| `cluster` | one of the 8 slugs |
| `material` | subset of Vinyl / Laminate / Engineered / Solid / Tile |
| `contentType` | `Pillar Page` or `Supporting Content` |
| `pillar` | a slug, or `null` only when `contentType` is `Pillar Page` (while `aeo_structure.pillar_rules.required` is false a null on a spoke is flagged, not refused) |
| `siblings` | 0–6 slugs (3–6 once `pillar_rules.required` is true) |
| `publishDate` | `YYYY-MM-DD` |
| `updatedDate` | `YYYY-MM-DD` or null |
| `videoUrl` | a YouTube URL or null |
| `faq` | 3–5 `{q, a}` objects, `q` ends with `?` |
| `legacy` | null, or `{"wpId": n, "importedAt": "YYYY-MM-DD"}` on an imported post |

## Body

The H1 and the snippet paragraph are **not** in the body: the page renders `title` and
`snippet` first (the direct-answer block), then the body, then `faq`, then pillar and
sibling links, then JSON-LD. `## FAQ` is removed from the body because it lives in
`faq[]`. Every remaining `##` heading is a question.

## JSON-LD the site emits

One `<script type="application/ld+json">` with a `@graph`: `Article` (headline =
`title`, description, datePublished / dateModified, `about` = cluster label, publisher =
Titan Flooring Inc. with the NAP from `lib/site.ts`), `FAQPage` from `faq[]`,
`VideoObject` when `videoUrl` is set, and `BreadcrumbList` (Home › Blog › Pillar › Post).
