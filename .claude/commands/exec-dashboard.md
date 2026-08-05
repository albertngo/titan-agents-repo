---
description: Render the admin exec dashboard as an HTML artifact from the latest ingest data. Read-only; no platform calls; no writes outside the artifact.
---

Render the Titan Flooring **exec dashboard** — the whole-business admin view.
This is a different altitude from `manager-dashboard` (sales-floor action list,
GHL-only, plain text): cross-source, glanceable, HTML.

Read-only: no writes to the vault, the repo, GHL, Notion, or Outlook. No live
API/MCP calls — files under `ingest/` are the only data source.

## Audience & sensitivity — hard rule

This is the **admin view**. It contains private-provenance items (Outlook,
bookkeeper) and must never be shared with staff or exported to a staff surface.
The rendered header always carries the "admin view — do not share with staff"
line. A staff variant, if ever built, is a separate command that filters by
`sensitivity`/provenance per `contracts/ingest-schema.md` — never this one with
sections deleted by hand.

## Input

- Date argument `<DATE>` (else today, America/Toronto).
- **Per-source freshness, not a single day** — days can be partial. For each
  source (`ghl`, `outlook`, `bookkeeper`, `notion`), use the newest
  `ingest/<D>/<source>.json` with `status: ok` where `<D>` is within 7 days
  ending at `<DATE>`. Every section is labeled with the data date(s) it renders
  from — mixed dates are expected and must be visible, never blended silently.
- `ingest/run-ledger.json` for the footer. If absent, the footer says
  "run ledger not available" — do not reconstruct it from directory listings.
- Trend window for process leaks: the GHL files of up to 5 most recent runs
  (including the primary). Missing days are gaps, not zeroes.
- The day's `DAILY-BRIEF.md` (if present) as a cross-check for section 1 — the
  merged `needs_attention` arrays from the source files are the ground truth.

## Global rules (shared with manager-dashboard)

- Counts come from `extensions.ghl.reporting` / `metrics`, never from counting
  `items` (50-cap + rollups).
- Project pipeline and STORE: Material pipeline are separate businesses.
  Separate lines everywhere. Never sum their counts or values.
- Rank urgency by percentage of stage threshold consumed, never raw days.
- Never fabricate. A section with no data shows an explicit empty/offline state
  — not zeroes, not estimates.
- Money renders from `amount_cents`; display CAD.

## Sections, in THIS order

1. **Needs attention** — merged `needs_attention` from all fresh sources,
   deduped, top 6, severity-striped (critical/warning), each item tagged with
   source + data date. Most urgent first.
2. **Money** — tiles: won this week (Project headline; STORE on its own line,
   never summed), money in (Outlook window and/or Notion payments, labeled),
   any card/statement due. **Outstanding/overdue AR renders as a greyed
   "bookkeeper offline" tile until bookkeeper reports** — the category stays
   visible; include the last manually-known figure with its source date if one
   exists in a recent brief. Once bookkeeper reports, this tile goes live.
3. **Pipeline health (GHL)** — open leads with hot/warm/cold split,
   stale-tagged and untagged counts, new leads net of exclusions (show raw −
   excluded), unanswered conversations (raw − excluded), appointments +
   pipeline moves, Meeting-stage count + avg age. One "At risk" line naming the
   worst 2–3 items by % of threshold consumed (negative `effective_window_days`
   always ranks first — it means the window expired before the visit).
4. **Process leaks (trended)** — one row per drift type from
   `extensions.ghl.workflow_drift`: today's count, prior-runs average,
   spark-bar over the trend window (missing days = gap, current run
   emphasized), and a rising / flat / falling badge (rising = today > prior
   average by more than ~20%; badge text always accompanies the color). Then a
   "standing items" line for known structural findings (e.g. bulk-import
   backlog) that shouldn't re-count as daily news.
5. **Operations (Notion)** — QA work orders open/in-error, stale tactical tasks
   count with duplicate clusters named, next status meeting + processed state.
   **No stale-task trend line** until the counting scope is pinned (counts
   jumped 35→41→16 on definition changes, not reality — say so in the note).
6. **Admin inbox (Outlook)** — supplier price lists pending, bounces, unread
   quotes, upcoming holidays/deliveries, professional-services threads.
   Marked admin-only.
7. **System health footer** — run-ledger strip, one cell per day in the window,
   four squares per cell (GHL · Outlook · Bookkeeper · Notion: ok / error /
   no-file), missed-run days highlighted. One-line legend including any
   source that has never reported.

## Rendering

- Follow `templates/exec-dashboard.html` — same token system, classes, and
  layout; replace the data. Brand accent RiderBlue `#1e6fff`; status colors
  (critical/warn/ok) are separate from the accent. Both light and dark themes
  via the token pattern already in the template (`prefers-color-scheme` +
  `data-theme` overrides).
- Title: `Titan Exec Dashboard — <DATE>`. Header subline: build date, "admin
  view" warning, and one source-status chip per source with its data date.
- Publish with the Artifact tool, favicon `📊`. **Update the existing artifact**
  — pass `url: https://claude.ai/code/artifact/ba397eef-f2f8-44b2-9033-ac438bf1add8`
  when this session didn't publish it — so Albert keeps one stable link. Only
  mint a new URL if Albert asks for a separate copy.
- If the template drifts from what a change needs, update
  `templates/exec-dashboard.html` in the same session so command and template
  never diverge.

## Do not

- No metric that doesn't change a decision this week — if unsure, cut it.
- No IDs, field names, or jargon in rendered output. Names and plain English.
- No blending of data dates without labels.
- Never render this command's output to a staff-visible destination.
