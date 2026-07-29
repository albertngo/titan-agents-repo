# GHL Appointment Funnel (all opportunities)

Repeatable method for measuring lead→appointment behaviour across the ENTIRE
opportunity list — open, won, lost, abandoned — not just wins. Built 2026-07-29
after the won-only view raised two questions the won corpus can't answer: is
opp→appt really ~0 days, and what happens to booked appointments that don't win?
Implemented by `analysis/ghl_appt_funnel.py` (read-only against GHL;
`analysis/output/` committed, `analysis/cache/` gitignored).

## Run it

```
python3 analysis/ghl_appt_funnel.py            # incremental (uses cache)
python3 analysis/ghl_appt_funnel.py --refresh  # re-pull opps/calendars (keeps contacts)
```

Requires `GHL_PIT_TOKEN` + `GHL_LOCATION_ID` and the `requests` package.
Outputs: `analysis/output/appt_funnel_rows.csv` (one row per opportunity),
`analysis/output/appt_funnel_stats.json` (aggregates by status/source/pipeline).

## How it differs from the won analysis

| | `ghl_win_timeline.py` | `ghl_appt_funnel.py` |
|---|---|---|
| Population | Won only (~300) | All (~2,000) |
| Appointment source | Conversation `TYPE_ACTIVITY_APPOINTMENT` events | **Calendars API** (`/calendars/events` per calendar, month-windowed) |
| Touch/workload metrics | Yes (needs conversations) | No — that's why it can afford the full population |
| Deal window | `[opp created − 30 d, close]` | Same; open opps use *now* as window end |

Appointment timing uses the **booking moment** (`event.dateAdded`), not the
scheduled visit (`startTime`) — same semantics as the conversation events, so
figures are comparable across the two analyses. `days_booked_to_visit` carries
the gap between the two. Deleted calendar events are skipped;
`appointmentStatus` (confirmed/cancelled/showed/noshow) is kept per row, not
filtered — a cancelled booking still evidences the lead reaching the booking
step.

## The coverage caveat — read this before quoting appointment rates

Calendar coverage is validated against the won corpus, where conversation
events exist for the same contacts (`calendar_coverage_of_won_corpus` in the
stats JSON). Store walk-ins may be logged as conversation appointment events
without ever touching a calendar; if coverage is materially below 100%, treat
calendar-derived `appt_rate` as a floor, and expect the undercount to
concentrate in the Store source, not ads. Cross-source comparisons of
*timing* (opp→appt on booked rows) are robust to this; comparisons of *rates*
are not.

## Metric definitions

Shared definitions (deal window, `REPEAT_GAP_DAYS`, repeat customer, inclusive
percentiles, opportunity-anchored clocks) are in
`methods/ghl-analysis-framework.md` — this analysis follows them exactly.
New fields here:

| Metric | Definition |
|---|---|
| `status` | Opportunity status verbatim: open / won / lost / abandoned. |
| `pipeline` | Pipeline name resolved from `pipelineId` via `/opportunities/pipelines`. |
| `source` | Normalized: case/whitespace variants collapsed (`store`→`Store`, `meta ad`→`Meta Ad`); other labels kept verbatim. |
| `appt_booked` | A non-deleted calendar event booked inside the deal window. |
| `days_opp_to_appt` | Opportunity created → booking moment. Negative ≥ −30 means booked just before the opp record. |
| `days_contact_to_appt` | Contact created → booking moment. The nurture-inclusive clock; compare with `days_opp_to_appt` to see pre-opportunity runway. |
| `days_booked_to_visit` | Booking moment → scheduled visit start. |
| `days_appt_to_close` | Booking moment → `lastStatusChangeAt`, closed rows only. |
| `cycle_days` | Opportunity created → `lastStatusChangeAt`, closed rows only. |

Multi-opportunity contacts: an appointment can fall inside two overlapping
deal windows (e.g. a repeat customer with back-to-back deals) and will then
count for both rows. Rare; accepted.

## Reading the results

- **The won-only bias check** = compare `opp_to_appt` for won vs lost vs
  abandoned rows with an appointment. If losing deals book at the same speed,
  booking speed is a property of the funnel, not of winning.
- **The nurture window** = `contact_to_appt` minus `opp_to_appt` medians per
  source; that difference is time spent before an opportunity existed.
- **Appointment leverage** = `appt_rate` by status: what share of abandoned
  opps ever booked, vs won ones.

## Cautions

- Calendar events before a calendar's creation date obviously don't exist;
  early-2024 opportunities may predate the booking calendars entirely — check
  the earliest event per calendar before reading old cohorts as "no
  appointment".
- `appointmentStatus` vocabulary is GHL's, not ours; "confirmed" ≠ showed.
- Open opportunities' windows end at run time, so their `appt_rate` climbs as
  they age. Don't compare open vs closed rates directly.
