# GHL Win-Timeline & Activity Framework

Repeatable method for measuring how long won deals take, what activity moves
them, and how much work a close costs. Implemented by
`analysis/ghl_win_timeline.py` (read-only against GHL; `analysis/output/` is
committed during the build phase, `analysis/cache/` stays gitignored — see
`.gitignore`).

## Run it

```
python3 analysis/ghl_win_timeline.py            # incremental (uses cache)
python3 analysis/ghl_win_timeline.py --refresh  # full re-pull
```

Requires `GHL_PIT_TOKEN` (read-only PIT) + `GHL_LOCATION_ID`. Outputs:
`analysis/output/won_rows.csv` (one row per won opportunity),
`analysis/output/stats.json` (aggregates).

## Metric definitions (v2)

v2 (2026-07-28): appointment and touch metrics are **opportunity-anchored** —
scoped to the deal window `[opp_created − 30 d, close]` — instead of running over
the contact's whole history. `days_lead_to_appt` was replaced by
`days_opp_to_appt`. Rationale under "Lead age vs sales cycle" below.

| Metric | Definition |
|---|---|
| `lead_date` | Earliest credible start: `min(contact.dateAdded, opportunity.createdAt)`. |
| `opp_created_date` | `opportunity.createdAt` on its own. |
| `close_date` | `opportunity.lastStatusChangeAt` (moment status flipped to won); fallback `updatedAt`. |
| `duration_days` | **Lead age.** `close_date − lead_date`, in days. Negative durations are excluded and counted as anomalies. |
| `cycle_days` | **Sales-cycle time.** `close_date − opp_created_date`. Not the same as `duration_days` and usually much shorter — see below. |
| `days_contact_to_opp` | `opp_created_date − contact.dateAdded`. The repeat-customer signal. |
| `repeat_customer` | `days_contact_to_opp > 30`. The 30-day threshold is a judgment call, not a GHL field; it lives in `REPEAT_GAP_DAYS` in the script. Changing it changes every repeat figure. |
| `source` | `opportunity.source`, fallback `contact.source`, else `Unknown`. `attribution_first` (first-touch UTM session source) kept as a secondary column. |
| Deal window | `[opp_created_date − REPEAT_GAP_DAYS, close_date]`. Activity outside it belongs to a prior relationship, not this deal. Reuses the 30-day repeat threshold deliberately — one line defines both "repeat customer" and "whose deal is this activity". |
| Touch | One communication message (SMS, email, call, WhatsApp, social, chat — incl. campaign/automated variants). `TYPE_ACTIVITY_*` events and internal comments are not touches. |
| Pre-close | Touches inside the deal window. All workload metrics use these only. |
| `first_response_min` | First inbound message → next outbound message, minutes. |
| `outbound_cadence_days` | Median gap between consecutive outbound touches. |
| Appointment | First `TYPE_ACTIVITY_APPOINTMENT` event **inside the deal window** (not first-ever in the contact's history). Body prefix classifies mode: `Visit:` → in-home, `Store:` → in-store. |
| `days_opp_to_appt` / `days_appt_to_close` | Opportunity created → first in-window appointment; that appointment → close. Slightly negative `days_opp_to_appt` (≥ −30) is real: the appointment was booked just before the opp record was created. |
| Workload index | Pre-close outbound touches (calls, SMS, emails our side sent). Compare per source to see cost-per-close. |

Buckets for duration distribution: 0–1, 1–3, 3–7, 7–14, 14–30, 30–60, 60–90,
90–180, 180+ days. Months bucket by close date, America/Toronto.

### Lead age vs sales cycle — do not mix them

`duration_days` measures from the earlier of contact-creation and
opportunity-creation. Repeat customers have a contact record months or years older
than the deal, so their lead age is enormous while the actual sale took days. Both
numbers are real and they answer different questions:

- **How long has this person been in our world?** → `duration_days`
- **How long did this deal take to close?** → `cycle_days`

Quote `cycle_days` for anything about sales-cycle length or pipeline forecasting, and
say which one you used. `repeat_rate` per source explains most of the gap between them.

The same trap applies to **every per-deal metric**, which is why appointments and
touches are scoped to the deal window (v2). Before that, a repeat customer's row
used the first appointment and full message history of the *contact* — SALIH's
fourth win reported a 905-day "lead → appointment" because the appointment
belonged to a deal three years earlier. Opportunity `createdAt` is the default
clock for anything measuring this deal; `contact.dateAdded` is only a lead-age /
repeat-customer signal. In the 2026-07-26 corpus the v2 window dropped 13
prior-relationship first-appointments (6 rows had a later in-window appointment
that took over; 7 correctly flipped to no-appointment) and kept all 12
appointments booked within 30 days before their opp record.

### Percentiles are inclusive

`five_num` uses `statistics.quantiles(..., method="inclusive")`, so p25 and p75 always
land inside the observed range. The default `"exclusive"` method estimates a wider
parent population and extrapolates past both ends — harmless at n=200, badly wrong on
the 3-to-4-win sources in the by-source table, where it can report a p75 longer than
any deal in the group and a negative p25. These percentiles are descriptive claims
about wins that actually happened, so inclusive is the matching estimator.

**Any figure computed before this change will shift slightly on re-run** — most
visibly the small-n sources.

## Reading the results

- **Follow-up window per source** = that source's p75 `cycle` (not `duration` —
  see above). If a source's p75 is 21 days, keep leads from it in active follow-up
  at least 3 weeks before deprioritizing.
- **Expected workload** = median pre-close outbound touches for the source.
- **Appointment leverage** = compare `cycle_days` and touch counts for
  deals with vs without a booked appointment, and in-home vs in-store.

## Cautions

- Won-only view: durations describe deals that closed, not conversion odds.
  A source can look "fast" because its slow leads die instead of closing.
- Conversation history reflects what GHL logged; walk-ins or off-platform
  calls undercount touches.
- Data is pulled live; numbers shift as opportunities get edited in GHL.
