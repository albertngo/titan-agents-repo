# Meta Ads ROI method — spend joined to what the leads did

Governs `analysis/meta_ads_roi.py` (tier 1). Companion to
`ghl-analysis-framework.md` (lead-age vs cycle definitions), `lead-funnel.md`
(source normalization) and `appt-funnel.md` (appointment signals). Extend the
script, don't fork it.

Built 2026-08-23 for "what is the recent ROI on Meta ads — conversations,
appointments, response rates". First run needs a cached multi-hundred-contact
conversation pull, which is the tier-1 trigger on its own.

## Two windows, two questions — never quote one as ROI

| View | Population | Answers |
|---|---|---|
| **Lead cohort** (`funnel`, `rates`, `cost_per`, `response`) | GHL contacts *created* in the window, Meta-attributed | What did this window's spend buy |
| **Closed wins** (`closed_wins`, `value.roas_closed_in_window`) | Meta-attributed opportunities *closed won* in the window, whatever their lead date | What the ad channel paid back during the window |

The cohort's wins are structurally immature: median Meta lead→win lag is ~20
days, p90 ~377 (repeat/nurtured buyers). A 30-day cohort therefore shows ~0
wins and that is not a result — `maturity` reports the cohort's age so the
zero can't be misread. The cash-period view has the mirror flaw: most of its
wins were bought with earlier windows' money. Report both, labelled.

## Attribution — the attribution array beats the source label

Precedence, first hit wins (`meta_attribution()`):

1. `contact.attributions[]` — `adSource` / `medium` / `utmSource` /
   `utmSessionSource` containing facebook / instagram / meta / "paid social",
   or `utmCampaignId` matching a campaign id from the Meta pull.
2. `meta-ad*` tags (`meta-ad-b&a`, `meta-ad-squeeky`), `facebook*` tags.
3. The source label, bucketed through `lead_funnel.normalize_source()`.

Label-first would lose real ad leads: a lead-form contact was observed
(2026-08-23) carrying `source: "Direct"` while its first attribution read
Paid Social / facebook with the live campaign id. The attribution array also
carries `utmCampaign`, `utmAdId` and `utmContent`, which is where the
per-creative breakdown comes from — GHL has creative-level attribution even
though `scripts/meta_ads_pull.py` only pulls campaign-level spend, so
creative rows carry funnel counts but no cost.

Carriers disagree at the opportunity level too: a win whose *opportunity*
source reads `Meta Ad` may sit on a contact with no Meta attribution at all
(seen once, a $0 record). `attribution.by_signal` reports the mix; treat
attributed counts as the floor.

## Meta's lead count ≠ GHL's contact count

Meta counted 85 leads for 2026-07-23..08-21 where GHL held 75 attributed
contacts. Expected, not a bug: Meta counts form submissions (duplicates
included, per its overlapping lead action types — see the trap table in
`.claude/agents/meta-ads-ingest-agent.md`), GHL dedupes to contacts by
phone/email. Report both and derive CPL from the GHL count for anything
downstream of the lead.

## Automation vs a person — use `message.source`, never `messageType`

The workflow's instant follow-up is a plain `TYPE_SMS`/`TYPE_EMAIL`, so the
`AUTOMATED_TYPES` set inherited from `ghl_win_timeline.py` classifies it as
human. GHL stamps each message with `source`: `workflow` / `campaign` / `api`
= automation, `app` = a person sending from the app. That field is the
discriminator; `AUTOMATED_TYPES` is kept only as a fallback for messages with
no `source`.

This single distinction moves the headline number: median speed-to-lead is
0.2 min counting all outbound, 28 h counting only human sends.

## Metric definitions (beyond the shared framework)

| Metric | Definition |
|---|---|
| `contacted` | Any outbound message, automated included |
| `conversations` | Contact has ≥1 communication message. Automation guarantees one, so this equals leads — the meaningful cut is `two_way` |
| `two_way_conversations` | ≥1 inbound AND ≥1 outbound: the lead actually engaged |
| `reply_rate` | `two_way / contacted` |
| `speed_to_lead_min` | Contact created → first outbound. Ad leads never message first, so the clock starts at creation, not at an inbound |
| `speed_to_lead_manual_min` | Same, first `source: app` outbound only |
| `first_response_min` / `_manual_` | First inbound → next outbound (any / human) |
| `appt_booked` | Conversation `TYPE_ACTIVITY_APPOINTMENT` OR `appt-*` tag OR a non-deleted calendar event for the contact. `appt_signal` records which fired |
| `cost_per.*` | Window spend ÷ the counted step |
| `roas_won` | Cohort won `monetaryValue` ÷ spend. `roas_closed_in_window` uses the cash-period wins |

Appointment lookback is zero days (unlike the opportunity-anchored analyses'
`REPEAT_GAP_DAYS`): an ad lead has no pre-history, so any booking counts from
contact creation forward. The scheduled visit may fall after the window —
calendar events are pulled 90 days past the window end for that reason.

## Cautions

- **`monetaryValue` is quoted/booked deal value in GHL, not collected
  revenue.** Every ROAS figure here inherits that. Open-pipeline ROAS is
  unrealized and belongs nowhere near a payback claim.
- **Phone calls placed outside GHL don't log**, so "no human message ever" is
  "no human message", not "nobody called". `TYPE_CAMPAIGN_CALL` rows are
  workflow-dialed and may still have connected a person.
- **Speed→outcome cuts are correlational.** An engaged lead attracts a faster
  human reply; the arrow runs both ways.
- Partial weeks bookend `by_week`; the newest weeks also under-report
  appointments (a lead booking next week hasn't booked yet).
- Cross-source comparison belongs in `lead_funnel.py`, which counts
  opportunities per source, not contacts. The two count different things and
  will not reconcile exactly — direction only.

## Re-run

```
python3 analysis/meta_ads_roi.py --days 30 --compare      # recent + prior period
python3 analysis/meta_ads_roi.py --days 90 --label 90d    # maturing cohort
python3 analysis/meta_ads_roi.py --refresh                # drop the cache
```

Cache: `analysis/cache/meta_roi/` (gitignored, regenerable; the Meta pull is
cached per window so re-runs cost no Marketing API calls). Committed outputs:
`analysis/output/meta_roi_rows[_label].csv`, `meta_roi_stats[_label].json`.
