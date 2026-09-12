# Website architecture — titanfloors.ca rebuild

If this drifts from `CLAUDE.md`, `CLAUDE.md` wins. Written 2026-09-12 (Albert, via
Claude) after reviewing an earlier headless-WordPress plan against this repo's rules
and the live site. Supersedes that plan's "Catalogue Sync Architecture" section, which
predates `/catalog-sync` and conflicts with it.

## Decision

Retire WordPress entirely (not headless). Rebuild as **Next.js 16 on Vercel**, content
as MDX files in a new `titan-web` repo, catalogue as a **read-only, whitelisted
projection** out of the existing Airtable Master Flooring Catalogue — never a live
read of Airtable or Lightspeed from the public site.

## Why

**The live site is smaller and more disposable than it looked.** WordPress 7.1 /
Elementor 4.2.3, 61 plugins (25 active), WooCommerce active but dead (~179 stale 2022
products, USD currency, zero orders/customers ever). Of ~147 published pages, ~120 are
one LPagery "{service} × {city}" template across ~20 cities, plus ~10 leftover
theme-demo pages. ~133 blog posts are the real content. The content worth keeping is
small; "keep WordPress because the content's already there" does not hold once you look.

**Governance and security trend is negative and this week got worse.** WP Engine v.
Automattic is an active lawsuit; Patchstack logged +42% YoY vulnerabilities across the
WordPress ecosystem in 2025, 91% in plugins; WordPress 7.0 shipped late with a cut
feature. On 2026-09-09 Automattic's board put Mullenweg on leave; by 09-11 he said he
was back in control — unresolved. None of this touches a site with no WordPress.

**The repo is public, and that changes the pricing plan.** This repo publishes the
markup rule `Retail price/unit = Cost/unit + $ 1.00`
(`.claude/skills/bert-airtable-schema/SKILL.md:293`) plus per-supplier list-to-cost
multipliers. A synced SKU-level price on the public website would let any competing
dealer back out Titan's cost from every supplier's public price list — defeating rules
like Grandeur's "never quote Cost to customers." **Phase 1 therefore shows no
SKU-level prices.** The current site's model — pick flooring, request a quote — is kept
and done properly (finder + calculator + quote request), not replaced with a price list.
Showing prices later requires one of: a `Web price` field driven by a markup that is
*not* in this public repo, category-level "from" ranges only, or making the repo
private. That is Albert's call when it comes up, and it needs a per-supplier
MAP-vs-MSRP map first (`MAP price ($/sf)` holds either a MAP or an MSRP with no flag to
tell which — `SKILL.md:1171`).

**Booking, not checkout, is the site's job today.** Across all sources, leads that book
an appointment win far more often than leads that don't, and in-store/in-home wins run
noticeably higher than remote-only. The STORE (retail material) pipeline is a small
fraction of revenue next to the project pipeline. Full ecommerce is not what this
business needs from a website right now.

## What the site never reads live

- **Lightspeed**: never. The personal token is admin-equivalent and unscopable
  (`platform-settings/lightspeed.json` → `auth._scoped_alternative`); no website process
  may hold it. `Lightspeed ID` non-blank in the projection is the "exists at the POS"
  signal — nothing more is needed from LS.
- **Airtable base directly**: never. 5 req/s per-base hard cap on every plan, attachment
  URLs expire ~2 h, and the base holds `Cost/unit`. The site reads a projection built by
  a separate, read-only, scoped script.
- **GHL, with a write token, on the public site**: not in phase 1. Lead capture uses
  GHL's own embedded forms/calendar, which need no token on the site at all.

## Credential table (planned; none issued yet)

| Credential | Holder | Scope | Blast radius if leaked |
|---|---|---|---|
| `AIRTABLE_PAT_READ` | agents repo (build step only) | one base, `data.records:read` | Read of the whole catalogue including `Cost/unit` — still bad, but bounded and read-only |
| `SITE_PUBLISH_TOKEN` | agents repo (push step only) | write access to `titan-web`'s data file / revalidate endpoint | Can publish a bad catalogue projection to the live site; cannot touch Airtable, Lightspeed, or GHL |
| GHL form/calendar embed | `titan-web` (public, no secret) | none — public embed code | None; it's not a credential |
| Stripe (phase 1 samples, later) | `titan-web` server route | Checkout + webhook signing secret only | Can create test charges; scoped to Stripe, not Titan's other platforms |

Two tokens, two blast radii, per `methods/architecture.md`: the read step and the push
step are separate files, neither with write access to Airtable or Lightspeed.

## The projection (catalogue → website)

1. **Build** (`scripts/web_catalogue_build.py`, planned, read-only, no write verbs —
   tested the same way `tests/test_lightspeed.py::TestNoWritePath` tests the LS pull
   path): reads Airtable rows where `Active` ✓, a new `Show on website` ✓, and
   `Lightspeed ID` is non-blank. Applies a **whitelist** (`contracts/web-catalogue-schema.md`,
   planned) — never `Cost/unit`, `Promo cost ($/sf)`, `Pallet price ($/sf)`,
   `MAP price ($/sf)`, `Retail price/unit`, `Salesperson notes`, `Internal notes`, or any
   supplier-internal field. Downloads and rehosts images (Airtable attachment URLs
   expire in ~2 h).
2. **Push** (`scripts/web_publish_push.py`, planned, the only file holding
   `SITE_PUBLISH_TOKEN`): dry-run diff first in `plans/<date>/web-publish-<date>.json`,
   same pattern as `/catalog-sync` step 4. Carve-outs that hold a SKU back: it appears in
   a `held`/`wrote_flagged` troubled row since the last publish, it carries a
   non-whitelisted field, or the batch would remove more than a set share of SKUs in one
   run. Every publish is a new `actions-log.json` entry type. The projection body
   (`web-catalogue.json`) lives in the `titan-web` repo, **never** in
   `ingest/<date>/` — the orchestrator reads every `*.json` there, and this file is not a
   daily ingest source.
3. **Gate**: `/web-publish` runs manually until `/catalog-sync` has one verified
   end-to-end run (see `CLAUDE.md`, "Scheduling status" — it has never completed one as
   of this writing). Only after that may it chain, unattended, off the end of
   `/catalog-sync`.
4. **Airtable side** (deferred, needs Albert's go-ahead before the fields are created):
   `Show on website`, `Web name`, `Web description`, `Web images` added in the UI; ids
   recorded in `airtable-destinations.json`; `scripts/bert_schema_export.py` re-run; the
   57-column canonical upload CSV explicitly excludes the new fields so a price-list
   import never blanks them; `contracts/catalog-plan-schema.md` gains a `web_enrich` op
   so `airtable-actions-agent` can write Claude-drafted web copy through the existing
   approval path — never a second writer. `ls-upload-instructions/SKILL.md:1078`
   ("Website names managed separately") should point at `Web name` once it exists.

## Lead capture

Straight to GHL. Embed GHL's own forms and calendar (no token needed) on every service,
city and product page: *book a store visit* / *book an in-home measure* / *request a
mobile quote*. Source lands as the literal `website` — the value
`analysis/lead_funnel.py`'s `normalize_source()` already buckets into. Page/city/UTM in
one custom field, not four. Website form telemetry belongs in `ghl-ingest-agent`'s
already-reserved but unbuilt `form_submissions` extension — GHL stays the one lead
store; no second one on the website side.

**Known live issue, tracked separately from this migration:** two Make.com scenarios
that currently feed the site's contact and delivery-request forms
("Website Inquiry Ingester", "Delivery Request Form") have been erroring for weeks while
still running (titan-vault daily notes, 2026-08-19 and 2026-09-02 onward) — inbound
website leads may be getting silently dropped right now, independent of any rebuild.

## Samples (phase 1 commerce)

Stripe Checkout; **Stripe is the order record**, not Airtable. A website-held Airtable
write token would scope to the whole catalogue base, which is not acceptable for a
public-facing process — so the sample flow never writes Airtable. Contact and a
`sample-order` tag go to GHL through GHL's own hosted form/inbound endpoint. Later, an
ingester can read Stripe with a restricted read-only key and report sample orders in the
daily brief under the STORE pipeline — never summed with the project pipeline, ids only
in `raw_ref`, no customer names committed to this repo.

## Full ecommerce (phase 2, only when carts are real)

Shopify via Storefront API, not WooCommerce or Lightspeed eCom. Lightspeed X-Series ships
a first-party Shopify connector (products, inventory both ways, customers, sales) that
keeps the POS as inventory master; Shopify auto-provisions a Storefront MCP server per
store and speaks the Universal Commerce Protocol, which is how a catalogue reaches
Google AI Mode, Gemini, Copilot and ChatGPT. Rule for that day: Shopify products are
created by the LS connector and enriched from the projection by SKU into metafields,
never hand-edited directly.

## Migration and redirects

WordPress and SiteGround retire after a 60-day 301 verification window (watched via
Search Console), then cancel SiteGround, Elementor Pro, Unlimited Elements Pro, LPagery
Pro, WP Media Folder and the YITH licences. DNS: only the web records move to Vercel —
**MX stays on Microsoft 365** (`@titanfloors.ca` mailboxes; `outlook-ingest-agent`
depends on it). See `methods/website-inventory.md` and
`analysis/website_inventory.py` for how the redirect map is built and verified.

Known defects to fix during migration, not carry forward: the contact page's map embed
points at the old 991 Matheson Blvd E address (text already says 1060 Britannia Rd E
#2); three page slugs have typos or wrong parents
(`lamiante-flooring-mississauga`, `vinyl_flooring_oakville`,
`/stair-refinishing/vinyl-flooring-hamilton/`); the Meta Ads landing page's destination
URL must be preserved exactly or re-verified with Meta before cutover (changing an ad
destination breaks attribution and can re-trigger ad review) — extend
`scripts/meta_ads_pull.py` to capture creative link URLs before cutover, per the
"extend, don't fork" rule.

## Open questions (Albert)

- `[FILL: per-supplier MAP vs MSRP semantics — which suppliers' `MAP price ($/sf)` is a
  real floor vs. an MSRP]`
- `[FILL: samples paid or free — decides whether phase 1 needs Stripe at all]`
- `[FILL: Search Console export for the city-page keep/consolidate decision — this
  session's WP connector could not read Site Kit's data (missing OAuth scope)]`
- `[FILL: Make scenario ids for the two erroring form pipes, once investigated]`

## Assumptions

- Albert (with Claude) is the only website content editor for now; no non-technical
  editor UI is being built in phase 1 (Keystatic is the fallback if that changes).
- Next.js/Vercel is the front-end choice already made in an earlier conversation;
  this document is where that choice is now recorded, since `05_decisions/` had no
  note for it before today.
- Product photography (none exists in Airtable or Lightspeed today) is treated as a
  separate asset-sourcing task, not solved by this architecture.
