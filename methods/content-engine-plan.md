<!-- Plan document, grilled with Albert 2026-10-07. Not yet built: no command, contract, registry or script below exists until Phase 0 is approved. Source of truth for the design until methods/content-engine.md replaces it. -->

# Titan AEO Content Engine — plan

## Context

Albert wants a self-improving content engine for titanfloors.ca: a large standing topic
backlog, configurable ranking, AEO-structured blog posts (brief → draft → human review →
publish on the Next.js site), video repurposing after the blog, and a feedback loop that
learns which topic clusters win deals (UTM `campaign` → GoHighLevel → Notion Titan Projects)
and raises those clusters in the queue. This plan fixes where it lives, the data model,
the scoring formula, the agents, the human gates, the build order, and the costs/risks.
It was grilled with Albert on 2026-10-07 (24 decisions, all recorded below) and must be
re-grilled before any later re-plan ("run grilling when planning" — Albert, 2026-10-07; a
CLAUDE.md line for that goes in the Phase 0 PR).

**Facts established (verified live 2026-10-06/07):**
- Notion **Blog Posts** `collection://9680aaf5-3233-4563-a866-592bf49541f1` (db `137596a4-505f-803b-a1ba-d430df016c79`, under page Blog Content `130596a4-505f-808a-8484-c3a33df890e7`): 106 Posted rows, all with WordPress `Direct URL`, `Primary Keyword` blank on all, 11 with `Related Video` (legacy relation → old "Blog Series" db), 1 Drafting vinyl `Pillar Page`. Fields: Status (Idea/Drafting/Posted), Material (Vinyl/Laminate/Engineered/Solid/Tile), SubTopic, Content Type (incl. Pillar Page / Supporting Content), Search Intent (`Commericial` is the live spelling), Publish Date, Linked, Blog Post Tracking relation.
- **Blog Post Tracking** `collection://2c8596a4-505f-8079-83f2-000b8d30b8a8` (monthly GSC rows) fed by Make 4458997 "GSC -> Notion (Blogs)", currently OFF; GSC connection "GSC - titanfloors.ca" exists in Make.
- Albert's design pages: "AEO Blog Post Structure" (`3f1596a4-505f-81f3-9899-cb75edd0d9ce`) and "AEO Site Architecture Blueprint" (`3f1596a4-505f-816f-8c0d-cc5a3c5951dd`): H1 = the question as typed; 40–60-word direct answer first; question H2s; local + trust layer; 3–5 FAQ; pillar-and-spoke per material; **flat URLs**; hierarchy in links/nav/Notion, never the URL; ≤2 levels; video embedded below the snippet.
- **Titan Projects** `collection://1b4596a4-505f-81ca-b1d5-000bb73ecbe1` already carries `Source`, `Opportunity ID`, `Opportunity Link`, `Value Approx`, `Date Won`; rows are created by Make **3710214 "Stage: Project Won (w/ Celebrate)"** (webhook from GHL; module 5 getAContact, 6 getAnOpportunity; maps `Source = {{1.opportunity_source}}`). No Campaign field.
- **GHL**: contact custom fields `UTM_Source/Medium/Campaign/Content/Term` exist (`contact.utm_campaign` = `BOUMRUjWjZ69sYv9cOyv`) but are **empty on every won contact sampled**; `attributions[].utmCampaign` is populated only on Meta-ad leads; no opportunity-level UTM field; opportunities cannot be searched by custom field. `scripts/ghl_client.py` is GET-only and `.env` holds the read token.
- **titan-website** (`albertngo/titan-website`, cloned read-only at `/home/user/albertngo/titan-website`): Next.js 16 / React 19 / TS, Vercel, homepage only; nav already links `/blog/`; its README points at `methods/website-architecture.md` and `platform-settings/website.json` in the agents repo — **neither exists**.
- **OpenSEO** (every-app/open-seo, MIT): Node app on Drizzle (any Postgres URL or Cloudflare D1); Docker = app + postgres, port 3001; hosted openseo.so $10/mo with own DataForSEO key and remote MCP `app.openseo.so/mcp`; ships an MCP (keyword research with volume/difficulty/CPC, live SERP, rank tracker, domain keywords/gap, backlinks, AI-visibility) plus a separate GSC MCP. DataForSEO: pay-as-you-go, $50 min prepay, ~$0.20 per 200 keywords + 96 PAA. The cloud session's egress proxy blocked github.com, railway.com, openseo.so today.
- Repo conventions (modelled on `/style-tag`, `/image-fill`, `/content-feedback`): read-only pull → judgement file → deterministic plan script → approval file only under `write_mode: write` → `*-actions-agent` executes only `approved` ids → `ingest/<date>/actions-log.json` → PushNotification → `scripts/publish_run.py`. Names `/content-*` are taken.

## Decisions (grilled 2026-10-07, Albert)

| # | Decision |
|---|---|
| 1 | Engine lives in **titan-agents-repo**; titan-website receives only rendered posts; OpenSEO is a deployment. |
| 2 | **Two axes**: `Material` = pillar/site axis; `Topic Cluster` = scoring + `utm_campaign` axis (8 clusters). |
| 3 | Publish to **Next.js only**; Phase 1 builds the blog route. |
| 4 | The **106 legacy posts are in scope**: one-time import via public WP REST API, slugs preserved, media copied into the repo. |
| 5 | Post body is **Notion until publish, then MDX is canonical**. |
| 6 | **Topic Backlog = new Notion DB** beside Blog Posts. |
| 7 | **One human gate**: Status `Review → Approved` in Notion; PR merge is the mechanical second gate. Zero-gate only as a dated `write_mode` flip. |
| 8 | Titan-only facts from a **curated `platform-settings/titan-facts.md`** + read-only Airtable product names. |
| 9 | Seeds **mined from call transcripts/inquiries, question only, Albert confirms** (Backlog rows at Status `Proposed`). |
| 10/17 | OpenSEO **hosted openseo.so now**; self-host path later = Cloudflare Workers + Albert's existing Supabase Postgres. |
| 11 | **2 posts/week**; harvest + rank weekly; sweep daily; attribution monthly. |
| 12 | UTM path: **site CTAs stamp UTMs → GHL contact `UTM_*` fields → Make 3710214 writes a new `Campaign` on Titan Projects**; analysis also reads `attributions[].utmCampaign`. |
| 13 | Scoring v1 defaults accepted (below). |
| 14 | **Flat root slugs** `app/[slug]` with trailing slash, `/blog/` index; **Vercel production URL counts as live** until DNS cut-over, rewritten to titanfloors.ca in one pass then. |
| 15 | Blog Posts gets a unique **ID (BP-###)**; **rename `Posted` → `Published`**; vocabulary Idea/Proposed(n/a here)/Briefed/Drafting/Review/Approved/Published. |
| 16 | Video embed: **YouTube only** (Shorts count); legacy `Related Video` untouched. |
| 18 | Attribution = **`Value Approx` share, trailing 12 months**, plus GHL lead counts incl. never-closed. |
| 19 | **Weekly routine drafts 2 posts into Review**; never opens a PR. |
| 21 | Gap-analysis domains: The Floor Box, Word of Mouth Floors, Speers, **plus national publishers** ("the more the merrier", within the budget cap). |
| 23 | Phase 1 posts are **text-only**; images later. |
| 24 | DataForSEO **$1/harvest, $20/month hard cap** in the registry. |

## Architecture

```
SEEDS                      OPENSEO (hosted, MCP)          GSC (OpenSEO GSC MCP)
 call transcripts ─┐        related · PAA · autocomplete    queries · clicks · position
 inquiries/quotes  ├─► /topic-harvest ──► Topic Backlog (Notion, Status Proposed→Backlog)
 Albert confirms  ─┘            │
                                ▼
                     /topic-rank  (scripts/topic_rank.py, deterministic)
                                │  Score, Score inputs
                                ▼
   weekly routine ──► /blog-brief + /blog-draft ──► Blog Posts row (Notion)  Status Review
                                                          │
                                        Albert reviews in Notion, sets Approved   ◄── GATE 1
                                                          │
                     /blog-publish ──► blog_render.py ──► MDX ──► PR on titan-website
                                                          │        (Vercel preview)
                                        Albert merges                              ◄── GATE 2
                                                          │
   daily  ──► /blog-sweep: URL live? → Direct URL, Status Published; YouTube Live URL → videoUrl
                                                          │
   titan-website CTAs: ?utm_source=blog&utm_medium=organic&utm_campaign=<cluster>
        → GHL form → contact UTM_* fields → opportunity → Project Won
        → Make 3710214 → Titan Projects {Source, Campaign, Value Approx}
                                                          │
   monthly ──► /content-attribution (analysis/content_attribution.py) ──► per-cluster report
                 → proposed cluster_performance ──► dated decision ──► registry  ◄── GATE 3
                                                          │
   weekly  ──► /topic-track: OpenSEO rank + GSC → Blog Post Tracking rows
```

All writes go through **`blog-actions-agent`** (Notion + GitHub PR) gated by
`plans/<date>/blog-approval-<scope>.json`. Scripts never touch a platform.

## Data model

### New Notion DB: Topic Backlog (beside Blog Posts, under Blog Content)
`Topic / Question` (title) · `ID` (TB-###) · `Cluster` (select, 8) · `Material` (multi, mirrors Blog Posts) ·
`Source of idea` (seed / transcript / openseo-related / paa / autocomplete / gap / gsc / reddit / manual) ·
`Volume` · `Difficulty` · `CPC` · `Intent` (Informational/Commericial/Navigation/Transaction) ·
`Local` (checkbox) · `Score` · `Score inputs` (text JSON) · `Last scored` ·
`Status` (**Proposed** / Backlog / Briefed / Drafting / Published / Retired) · `Retired reason` ·
`Canonical key` (normalised query; dedupe key) · `Blog Post` (relation).

### Blog Posts — additions
`ID` (BP-###) · `Topic Cluster` (select, 8) · `Pillar` (self-relation, one) · `Content Idea` (relation → Titan Content Ideas) ·
`Topic` (relation → Backlog) · `Slug` · `Snippet` (40–60 words) · `Video URL` · `PR URL`.
Status: Idea / Briefed / Drafting / Review / **Approved** (person-only) / Published (renamed from Posted).
Never written by the run: Assignee, Payout Date, Neuron URL, Related Video, Linked, Status Approved, body once Status ≥ Review.

### Titan Content Ideas — addition
`Topic Cluster` (select, 8). Reverse relation of `Content Idea`. Series is chosen when the video is scripted from the blog; ideas never originate from Series.

### Titan Projects — addition
`Campaign` (text), written by Make 3710214 from the contact's `utm_campaign` custom field. Blueprint re-snapshotted to `platform-settings/blueprints/project-won-3710214.json` and pinned by a test.

### Taxonomy & UTM
Clusters (slug = `utm_campaign` = select label's slug): `basement-flooring`, `waterproof`, `vinyl-laminate`, `hardwood`, `installation-cost`, `installation-process`, `comparison`, `maintenance`.
`utm_source` = blog/email/social · `utm_medium` = organic/paid/nurture · `utm_campaign` = cluster slug. Other UTMs stay on the contact.

## Scoring (`scripts/topic_rank.py`, v1 accepted)

```
V = min(1, log10(1+volume)/log10(1+5000))         volume null → 0.25 (flag volume_unknown)
D = 1 − clamp(difficulty/100)                      null → 0.5
L = min(1, local_prior[cluster] + 0.5·has_local_token)
C = (1−r)·commercial_prior[cluster] + r·perf[cluster]
    r = 0.6·min(1, wins_attributed/20);  perf = clamp((won_value_share/published_share)/2, 0, 1); perf null → C = prior
I = intent score (Transaction 1.0 / Commericial 0.8 / Informational 0.5)
score = 100·(0.30V + 0.20D + 0.15L + 0.25C + 0.10I)
diversity = clamp(1 + 0.15·[nothing published in cluster] − 0.10·open_in_cluster, 0.5, 1.15)
effective = round(min(100, score·diversity), 1);  order by (−effective, −volume, canonical_key)
```
Only `Status = Backlog` rows are scored; `Score inputs` stores every term so a number can be explained later.
Worked examples pinned by tests: "how much does vinyl plank cost to install in mississauga" (320/mo, uncovered cluster) → **95.9**; "is laminate flooring waterproof" (2,400/mo, 3 in flight) → **43.5**.
Priors (registry, tunable): installation-cost 0.90/0.60 · basement 0.80/0.30 · vinyl-laminate 0.70/0.20 · hardwood 0.70/0.20 · waterproof 0.60/0.20 · comparison 0.60/0.10 · installation-process 0.50/0.50 · maintenance 0.30/0.10 (commercial/local).
Feedback: `/content-attribution` proposes `cluster_performance.values` + `wins_attributed`; a dated vault decision + registry PR applies them. Never written by a run.

## Files — titan-agents-repo

**Registry** `platform-settings/content-engine.json` — `_comment`, `_maintenance`, `config_version`, `write_mode` (`plan_only` → `write` by dated decision), `clusters` (priors, materials), `cluster_rules` (first-match keyword → cluster), `local_tokens`, `intent_rules`, `scoring`, `cluster_performance`, `campaign_aliases`, `sources` {topic_backlog, blog_posts, blog_post_tracking, titan_content_ideas, titan_projects (+ make_scenario 3710214)}, `ghl` (utm field ids), `openseo` {deployment: hosted, mcp url, budget {usd_per_harvest 1, usd_per_month 20}, gap_domains}, `aeo_structure` (snippet 40–60, FAQ 3–5, H2 questions, min body 700), `website` {repo, base branch, `content/blog`, slug regex, Vercel production host, legacy host, never_merge}, `policy`, `outputs`, `held_reasons`, `flagged_reasons`. Every id lives here, never in a prompt.

**Facts** `platform-settings/titan-facts.md` — Albert-owned: price ranges per material, install ranges, Ontario/basement/moisture facts, policies. Brief builder quotes only from here + Airtable product names.

**Commands** (`.claude/commands/`, modelled on `style-tag.md`): `topic-harvest.md` (`--mode seed|transcript|openseo|gsc`), `topic-rank.md`, `blog-brief.md`, `blog-draft.md`, `blog-publish.md`, `blog-sweep.md`, `content-attribution.md`, `topic-track.md`, `blog-import.md` (one-time legacy import, Phase 1b).

**Agent** `.claude/agents/blog-actions-agent.md` — tools: Read, Write, Bash, Notion create/update/fetch/query, GitHub `create_branch`, `push_files`, `create_pull_request`, `list_pull_requests`, `get_file_contents`. **No merge, no delete.** Modelled on `airtable-actions-agent.md` + `social-actions-agent.md` prime rules (approval file is the approval; log before reporting; CAS on Status; stop the batch on failure).

| Action type | Policy | Rule |
|---|---|---|
| `notion_create_topic` | auto | search `Canonical key` first; ≤50/batch, ≤150/run; Status `Proposed` for transcript seeds, `Backlog` otherwise |
| `notion_update_topic_score` | auto | CAS `Status == Backlog` |
| `notion_retire_topic` | auto for `covered`/`duplicate`; person for `out_of_scope`/`no_volume` | |
| `notion_create_blog_post` | auto | refuse if topic already has a Blog Post; sets topic Briefed |
| `notion_update_blog_post` | auto | closed field list; Status only Briefed/Drafting/Review/Published; **never Approved** |
| `notion_append_blog_body` | auto while Status ∈ {Briefed, Drafting} | append-only under `## Draft <date>`; Status ≥ Review → refused `body_is_a_persons` |
| `website_open_post_pr` / `website_update_post_pr` | auto with precondition | re-read Status must be `Approved` at write time; sha1 of MDX in plan; reuse open PR; writes `PR URL` |
| `notion_create_tracking_row` | auto | idempotent on post + Month |
| `notion_update_content_idea_cluster` | auto | blank-only `Topic Cluster` on an idea, nothing else |

Refused always: merge, delete/archive, write `Approved`, touch captions/`Next: Post To`/`Post Date`, edit a Published body, edit `cluster_performance`.

**Contracts** `contracts/blog-plan-schema.md` (`blog-plan-1` plan per stage + `blog-approval-1`; ids `blg-<sha1[:12]>` over system+op+target key+field names+content hash; `held[]` without ids; plans expire end of day; "no approval file means nothing is approved") and `contracts/blog-mdx-schema.md` (`blog-mdx-1` frontmatter, below). `contracts/actions-log-schema.md` gains the type row.

**Scripts** (stdlib, no network, no-write-verb tested): `scripts/topic_harvest.py` (normalise + cluster-map + dedupe, Jaccard 0.8 dup / 0.6 overlap vs backlog + 106 titles), `scripts/topic_rank.py`, `scripts/blog_plan.py --stage harvest|rank|brief|draft|publish|track` (planner; `--write-approval` refused under `plan_only`), `scripts/blog_render.py` (Notion export → MDX + frontmatter + PR body; `--check`), `scripts/blog_sweep.py` (pure decider), `scripts/blog_import.py` (WP REST JSON → MDX + media manifest), `analysis/content_attribution.py` (uses `GhlClient` GET-only; pages all opportunities, filters client-side; cache in gitignored `analysis/cache/`).

**Methods** `methods/content-engine.md` (meaning of the score, AEO structure, pillar rules, state machine, decision log), `methods/content-attribution-framework.md`, `methods/website-architecture.md` (the file titan-website's README already links), plus `platform-settings/website.json` (NAP/nav the site copies from).

**Tests** (`python3 -m unittest discover -s tests`): `test_topic_rank.py` (weights sum to 1; both worked examples; determinism; diversity floor; ramp 0/10/20), `test_blog_plan.py` (envelope; stable ids; held has no id; approval refused under plan_only; PR never planned unless Approved; `Approved` never in a write; no write verbs in the five scripts), `test_blog_render.py` (frontmatter keys; snippet 40–60; flat slug regex; FAQ 3–5; pillar null only for Pillar Page), `test_blog_sweep.py`, `test_content_engine_registry.py` (8 slugs; write_mode by decision; status vocab; actions-log vocabulary; commands registered in `departments.json`; CLAUDE.md names the engine), `test_content_attribution.py` (aliases; never-closed counted; 12-month window; clipping; no PII), `test_project_won_blueprint.py` (Phase 3 snapshot pins the Campaign mapping), `test_blog_import.py` (slug preserved; media rewritten; count 106).

**Edits** `platform-settings/departments.json` (marketing `owns.commands` += the nine commands, `specialists.actions` += `blog-actions-agent`, keywords blog/seo/aeo/keyword/topic/backlog/cluster/pillar), `contracts/actions-log-schema.md`, `CLAUDE.md` (new "AEO content engine" section + the grilling-when-planning line), `.mcp.json` (openseo), `.env.example` (`OPENSEO_MCP_URL`, `OPENSEO_API_KEY`, `GH_TOKEN` for the Mac PR path), `.claude/skills/titan-content-scripts/SKILL.md` (Phase 4 "from blog" mode).

## Files — titan-website

`content/blog/<slug>.mdx` (the only thing the agent writes) · `lib/blog-schema.ts` (validate frontmatter, hand-rolled) · `lib/blog.ts` (`getAllPosts`, `getPost`, `getPillarChildren`, `getSiblings`; gray-matter) · `app/[slug]/page.tsx` (flat URL, `generateStaticParams`, metadata, DirectAnswer → VideoEmbed → body → FAQ → PillarLinks → JSON-LD) · `app/blog/page.tsx` (index by cluster, pillars first) · `components/blog/{DirectAnswer,VideoEmbed,Faq,PillarLinks,JsonLd,CtaLink}.tsx` (`CtaLink` appends the UTM triple) · `app/sitemap.ts` · `scripts/validate-content.mjs` wired into `build` so a bad PR fails the Vercel check · `next.config.ts` `trailingSlash: true` · `public/blog/<slug>/` for imported media · deps `gray-matter`, `next-mdx-remote` (verify vs Next 16 / React 19; fallback `@next/mdx`), `remark-gfm`.

Frontmatter `blog-mdx-1`: `schema, blogId (BP-###), notionPageId, title, slug, description (≤160), snippet (40–60 words), keyword, intent, cluster, material[], contentType, pillar (slug | null only for Pillar Page), siblings[3–6], publishDate, updatedDate, videoUrl, faq[{q,a}], legacy: {wpId, importedAt} (import only)`.
JSON-LD `@graph`: Article (publisher = Titan NAP from `lib/site.ts`), FAQPage, VideoObject when `videoUrl`, BreadcrumbList. Pillar/spoke links render from frontmatter: a spoke shows one up-link + siblings; a pillar lists `getPillarChildren` so adding a spoke never edits the pillar file.

PR transport: cloud session → `add_repo titan-website access:push`, then GitHub MCP `push_files` + `create_pull_request` on branch `blog/<slug>`; Mac → `scripts/blog_publish_pr.py` (sibling of `publish_run.py`, `GH_TOKEN`). Both commit the identical `ingest/<date>/blog-mdx/<slug>.mdx` whose sha1 is in the plan.

## Human checkpoints

1. **Seeds**: Backlog rows at `Proposed` → Albert flips to `Backlog` or retires.
2. **Review**: Blog Posts `Review → Approved` — the only content gate; the run can never write `Approved`.
3. **Publish**: PR merge on titan-website (Vercel preview is the visual check).
4. **Cluster weights / performance**: dated vault decision + registry PR, never a run.
5. **`write_mode` flip** `plan_only → write` after the Phase 1 dry run; **routine** enablement; GHL/Make edits (Albert does them in-platform, repo re-snapshots).

## Phases

| Phase | Deliverables | Albert's decisions / tasks | Pinned by |
|---|---|---|---|
| **0 — Schema + registry** | Topic Backlog DB; Blog Posts additions + `Posted→Published` + ID; `content-engine.json` with real ids; `titan-facts.md` skeleton; `methods/content-engine.md`; `departments.json`; stub commands; CLAUDE.md section + grilling line; vault decision note. | Confirm the 8 labels/priors; create the ID property if the API cannot; fill `titan-facts.md`. | registry + departments tests |
| **1 — Smallest slice** | `/topic-harvest --mode seed` (hand-written 10–20 seeds, no OpenSEO) → `/topic-rank` → `/blog-brief` + `/blog-draft` on one topic → titan-website blog route + validator + `website.json`/`website-architecture.md` → `/blog-publish` PR → merge → `/blog-sweep` marks Published on the Vercel URL. Starts `plan_only`; closes with the `write` flip. | Approve the first draft in Notion; merge the PR; flip `write_mode` (dated decision). | rank/plan/render/sweep tests; `validate-content.mjs` in CI |
| **1b — Legacy import** | `/blog-import`: WP REST → 106 MDX files, slugs + trailing slash preserved, media into `public/blog/<slug>/`, Notion rows gain `ID`, `Slug`, `Topic Cluster`, `Pillar` (proposed, Albert confirms); vinyl pillar draft wired to its spokes. One PR. | Confirm cluster/pillar assignments for the 106; DNS cut-over date (outside this plan, but the sweep's "live" host flips then). | `test_blog_import.py` |
| **2 — OpenSEO** | Hosted openseo.so account + DataForSEO prepay; `.mcp.json` entry; harvest modes related/PAA/autocomplete/gap (Floor Box, Word of Mouth, Speers, national publishers); transcript seed mining (`--mode transcript`, question-only, PII-free, lands as `Proposed`); budget cap; `/topic-track` (OpenSEO rank + GSC → Blog Post Tracking; Make 4458997 stays off). | Sign up; allowlist `app.openseo.so` in the cloud environment (or run harvests from the Mac); prepay DataForSEO. | harvest/dedupe cases; budget pins |
| **3 — Feedback loop** | GHL: form hidden fields → `UTM_*` contact fields (Albert, in GHL); Make 3710214 adds `Campaign` (Albert); blueprint snapshot + test; `/content-attribution` + analysis script + framework doc; first `cluster_performance` decision; titan-website `CtaLink` UTM stamping. | GHL form/workflow edit; Make edit; accept first proposed values. | attribution + blueprint tests; ramp cases |
| **4 — Video layer** | `Content Idea` relation used; titan-content-scripts "from blog" mode (sets `Topic Cluster`, picks Series then); `/blog-sweep` embeds the YouTube Live URL via `website_update_post_pr`; VideoObject JSON-LD. | None beyond approving the skill change. | skill prose test; sweep embed case |
| **5 — Automation** | Routine: weekly harvest + rank + brief/draft 2 into Review; daily sweep; monthly attribution report; weekly track. Publishing stays person-triggered. Routine prompt stored as a pointer under `methods/` (price-list precedent). | Enable the routine; confirm Notion MCP is in `.mcp.json` for unattended runs. | routine prompt test |

## Costs

| Item | Estimate |
|---|---|
| OpenSEO hosted | $10 / month |
| DataForSEO | $50 prepay; ~$0.25 per 200-keyword harvest; capped $1/harvest, $20/month |
| Vercel | current plan (static blog adds no cost) |
| Model spend | ~2 drafts + 1 harvest/rank + 1 sweep per week in Claude Code sessions |

## Risks

1. **Nothing reaches titanfloors.ca until DNS cuts over**; until then "live" = Vercel production URL (decision 14) and rankings start only after the migration. The 106-post import (1b) is the gating work.
2. **GHL UTM fields are empty today**; attribution is blind until the form/workflow writes them (Phase 3 is Albert's GHL work, not repo work). Campaign values from Meta ads won't be cluster slugs → `campaign_aliases` absorbs, unmapped are reported never guessed.
3. **Egress**: cloud sessions blocked openseo.so/railway/github today; harvests need an allowlist or run on the Mac.
4. **Notion body fidelity**: MCP export loses callouts/toggles/embeds and uses expiring image URLs → text-only Phase 1 (decision 23).
5. **Body divergence after publish**: Notion edits after `/blog-publish` don't reach MDX; sweep flags `body_changed_after_publish` via the export hash stored in the plan.
6. **Root dynamic route** `app/[slug]` will collide with future product-category paths → `reserved_slugs` in the registry.
7. **`next-mdx-remote` vs Next 16 / React 19** unverified → fallback `@next/mdx`.
8. **Overlap detection on titles only** (Primary Keyword blank on all 106) → `/blog-import` proposes keywords, Albert confirms.
9. **GHL cannot filter by custom field** → attribution pages all opportunities; cache; both the contact field and `attributions[]` are read and can disagree.
10. **FAQPage rich results** are restricted by Google; the JSON-LD serves answer engines, not SERP stars (set expectation in the method doc).
11. **Public repo**: attribution output is per-cluster aggregates only; GHL cache stays under gitignored `analysis/cache/`.
12. **Unattended Notion writes in Phase 5** need the Notion MCP in `.mcp.json`, not a session connector.

## Open questions (not blocking Phase 0–1)

- DNS cut-over date for titanfloors.ca → Vercel (sets when rankings start).
- Whether `Value Approx` on Titan Projects is reliably filled on store-pipeline wins (affects attribution share).
- Whether to add `Proposed` seed review to a Notion view (yes by default: a "Seeds to confirm" view on Topic Backlog).

## Verification

- **Phase 0**: `python3 -m unittest discover -s tests -v` green; `notion-fetch` on the new Backlog data source shows every registry property; `departments.json` test passes with the nine commands present.
- **Phase 1 dry run (plan_only)**: `/topic-harvest --mode seed` → `plans/<date>/blog-plan-harvest.json` with no approval file; `/topic-rank` output matches the two worked examples when the seeds include them; `/blog-brief` + `/blog-draft` produce a judgement file that `blog_plan.py --stage draft` validates (snippet 40–60, H2 questions, FAQ 3–5); `blog_render.py --check` passes on the draft.
- **Phase 1 live**: after the `write` flip, one real post: Notion row BP-001 reaches Review → Albert sets Approved → `/blog-publish` opens a PR whose Vercel check runs `validate-content.mjs` → merge → `/blog-sweep` writes Direct URL (Vercel host) + Published, logged in `ingest/<date>/actions-log.json`; `curl -I` the URL returns 200 and the JSON-LD validates (Rich Results Test / schema validator).
- **Phase 1b**: 106 MDX files build; `app/[slug]` serves each legacy slug with trailing slash; no hotlinked WordPress images remain (`grep -L titanfloors.ca/wp-content` is empty).
- **Phase 2**: a harvest ends under $1 and the registry's monthly counter increments; dedupe refuses a known title; a transcript seed lands at `Proposed` with no PII (test fixture).
- **Phase 3**: a test win with `utm_campaign=basement-flooring` on the contact produces a Titan Projects row with `Campaign` set (Make run log) and `/content-attribution` counts it; the proposed `cluster_performance` changes the ranking in a re-run of `/topic-rank` only after the registry decision is applied.
