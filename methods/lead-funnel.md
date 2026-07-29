# Lead-funnel method — sources, appointments, daily counts

Governs `analysis/lead_funnel.py` (tier 1). Companion to
`ghl-analysis-framework.md`, which defines lead-age vs cycle metrics; this file
adds the funnel-specific rules. Extend the script, don't fork it.

## Population

All opportunities of ALL four statuses (`open`, `won`, `lost`, `abandoned`)
whose `createdAt` falls in the window (default 60 days). Abandoned dominates
the historical base (1,137 all-time vs 303 open) — excluding it silently would
overstate every conversion rate. Project pipelines (`(1)`, `(2)`) and
`STORE: Material Pipeline` are reported as separate businesses, same rule as
won-analysis.

## Lead date

`min(contact.dateAdded, opportunity.createdAt)` — contacts usually predate
their opportunity. Daily trend buckets use `opp_created_date`; per-lead timing
(`days_lead_to_appt`) uses the min. Do not mix (see
ghl-analysis-framework.md).

## Source normalization (the dirty-label trap)

GHL carries source in FOUR places that disagree; ~20 raw label variants exist
(`Meta Ad` / `onlineMeta Ad` / `facebook` / `facebook form lead`, `Store` /
`store` / `lightspeed`, `Referral` / `referral` / `Recommended`…).

Precedence: `opportunity.source` → `contact.source` → source tags
(`meta-ad-b&a`, `google lead`, …, per ghl-ingest-agent.md's tag vocabulary) →
first attribution (`utmSessionSource`/`medium`). The bucket map lives in
`normalize_source()` in the script — buckets: Meta Ads, Mobile Quote,
Store / Walk-in, Referral, Contractor, Tradeshow, Google, Website,
Booked appointment (direct), Flyers / Door hangers, Inbound call,
Rep / Manual, Other, Unknown. `source_raw` and `source_carrier` columns keep
the pre-normalization truth in every row.

## Booked appointment

Three signals exist and disagree (known from won-analysis):
conversation `TYPE_ACTIVITY_APPOINTMENT` events (primary — works historically),
`appt-home`/`appt-store`/`appt-call` tags (corroboration), calendar events
(daily ingest's signal, not queryable historically per-contact).

`appt_booked` = event OR tag. `appt_signal` records which fired
(`event`/`tag`/`both`) — never present the signals as one field.
`appt-cancelled` alone is NOT booked (counted in `anomalies.cancel_only_appt`).
Mode from event body prefix `Visit:` → in-home, `Store:` → in-store, else
unknown; tag fallback when no event. Events count from 30 days before opp
creation (walk-in booking precedes the opp record), mirroring
`REPEAT_GAP_DAYS`.

## Why daily counts ≠ the ingest's `new_leads`

The daily brief's `leads_by_source` counts new CONTACTS in a 24h run window —
including voicemail callers with no opportunity yet. This analysis counts
OPPORTUNITIES per calendar day. Jul 27 measured 6 here vs 9 in the ingest;
both are right. Cross-check direction only, never exact equality.

## Charts

`analysis/lead_funnel_charts.py`. Categorical palette `#1e6fff` (RiderBlue),
`#e8710a`, `#00a38d`, `#8c4fd6` — validated with the dataviz skill's
`validate_palette.js` (all six checks pass, light surface); "Other"/"Unknown"
render in recessive neutral `#9aa1ab`, deliberately outside the categorical
set. One axis per chart; top-4 sources + Other in the stacked daily chart.

## Re-run

```
.venv/bin/python analysis/lead_funnel.py [--refresh] [--days N]
.venv/bin/python analysis/lead_funnel_charts.py
```

Cache: `analysis/cache/lead_funnel/` (gitignored, regenerable). Committed
outputs: `lead_rows.csv`, `lead_stats.json`, `chart*.png` in
`analysis/output/`.
