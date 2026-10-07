# 2026-10-07 — content engine Phase 1 dry run (write_mode: plan_only)

Nothing in this folder touched a platform. Files named `-simulated` are what Notion
*would* hold after the matching plan under `plans/2026-10-07/` executes; their urls are
placeholders. `blog-posts-sql.json` is the live Blog Posts query (107 rows) transcribed
from the Notion MCP result; `topic-backlog-sql.json` is the live, empty Topic Backlog.

| Step | Input | Output |
|---|---|---|
| snapshot | the two SQL results | `topic-backlog-snapshot.json`, `blog-posts-snapshot.json` |
| harvest | `topic-seeds.json` (15 hand-written) | `topic-candidates-seed.json` → `plans/…/blog-plan-harvest-seed.json` (15 create_topic; approval refused, exit 4) |
| rank | simulated backlog | `topic-scores-preview.json`, `topic-scores-simulated.json` → `blog-plan-rank-all-simulated.json` |
| brief | `blog-brief-TB-3.json` | `blog-brief-TB-3.md` → `blog-plan-brief-TB-3.json` (flags: titan_facts_missing, pillar_not_required_yet) |
| draft | `blog-body-BP-108.md` | `blog-plan-draft-BP-108.json` (append + Status Review) |
| render | `blog-row-BP-108.json` + body | `blog-mdx/best-flooring-for-basement-ontario.mdx` (passes `blog_render.py --check` and the site's `validate-content.mjs`) |
| publish | posts at Briefed / at Approved | held `not_approved` (exit 3) / `blog-plan-publish-BP-108.json` (one open_post_pr) |
| sweep | `blog-sweep-checks.json` (no host, no PR) | `blog-sweep.json` → `blog-plan-sweep-all.json` (warning: no PR yet) |

The top-ranked topics are pricing questions; every price in `platform-settings/titan-facts.md`
is still `TODO`, so the dry-run brief took the basement topic, which needs no number.
