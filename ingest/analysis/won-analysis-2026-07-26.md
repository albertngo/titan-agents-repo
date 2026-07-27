# Won Analysis — all historical wins (run 2026-07-26)

## Method

- **Data:** all 297 opportunities with `status: "won"`, pulled live via
  `analysis/ghl_win_timeline.py` (cold cache, full re-pull today), plus full
  conversation histories for all 257 distinct contacts. Anomaly block clean:
  0 missing close dates, 0 negative durations, 0 negative cycles.
- **Dates:** `lead_date` = min(contact created, opportunity created).
  `close_date` = `lastStatusChangeAt` (the moment status flipped to won).
  **Every duration below is labelled either `cycle` (opportunity created → won: how
  long the deal took) or `duration` (lead age: how long the person has been in our
  world).** Repeat customers (24% overall) make these differ by months — an
  unlabelled number is unreadable.
- **First contact** = first message in either direction on any of the contact's
  conversations. Touches = communication messages only (`TYPE_ACTIVITY_*` events and
  internal comments excluded); all touch metrics are pre-close only.
- **Appointment mode** = body prefix of the first `TYPE_ACTIVITY_APPOINTMENT` event
  (`Visit:` → in-home, `Store:` → in-store). This is the script's method — it can
  disagree with the `appt-home`/`appt-store` tags the daily ingester reads. 30 wins
  have an appointment whose body has neither prefix ("unknown" mode).
- **Pipelines are reported separately**: `(2) PROJECT: Sales Pipeline` (290 wins) vs
  `STORE: Material Pipeline` (6 wins). One win sits in `(1) PROJECT: Lead
  Qualification` (Elena Pass, $0, closed 2026-06-26) — a misfiled record, excluded
  from both groups and flagged below.
- **This is a won-only view.** Durations describe deals that closed, not conversion
  odds. The missing denominator is huge: ~1,132 abandoned opportunities — a "fast"
  source may simply abandon its slow leads rather than close them. Nothing here says
  what fraction of leads win.
- Percentiles are inclusive (`statistics.quantiles(..., method="inclusive")`).

## Headline

| | PROJECT pipeline | STORE material |
|---|---|---|
| Wins | **290** | 6 |
| Total value | **$2,377,447 CAD** | $22,799 CAD |
| Deal cycle (`cycle`), median / p75 | **13.9 d / 31.0 d** | 11.1 d / 23.9 d (n=6) |
| Lead age (`duration`), median | 25.9 d | 549.8 d (n=6 — mostly repeat customers) |
| Repeat rate (>30 d contact→opp gap) | 23% | 50% |
| Appointment rate | **60%** | 0% |
| Pre-close touches, median / p75 | 37 / 67 | 40.5 / 62.8 |

Store rows are 6 data points — directional at best. Everything below is
**PROJECT pipeline only** unless marked.

## By source

Sources with ≥3 wins. 12 more source labels (16 wins total) excluded as long-tail
(<3 wins each) — including the casing/concatenation variants `store`, `referral`,
`Referral`, `onlineMeta Ad`, `online`, `Preliminary Mobile Quote`, `facebook`,
`website`. Source labels in GHL are messy; `Store` vs `store` are almost certainly
the same channel split by data entry.

| Source | n | Value | Cycle med / p75 | Repeat | Appt rate | Touches med | First resp med |
|---|---|---|---|---|---|---|---|
| Store | 197 | $1,581,472 | 12.8 / 28.5 d | 25% | 52% | 35 | 109 min |
| Meta Ad | 60 | $490,868 | **20.0 / 51.0 d** | 12% | **83%** | **54.5** | 87 min |
| tradeshow | 4 | $57,918 | 135.4 / 250.4 d (n=4 — 4 data points, not a window) | 0% | 100% | 56 | 7,872 min |
| store (lowercase) | 4 | $21,153 | 5.6 / 8.4 d (n=4) | 25% | 50% | 12 | — |
| Pourya | 3 | $25,183 | 5.0 / 8.1 d (n=3) | 33% | 0% | 4 | — |
| onlinePreliminary Mobile Quote | 3 | $39,444 | 14.7 / 16.9 d (n=3) | 0% | 100% | 23 | 22 min |
| Contractor | 3 | $20,800 | 0.1 / 1.0 d (n=3) | 67% | 0% | 148 | 2 min |

The story: **Store walk-ins close in ~2 weeks with ~35 touches; Meta Ads close in
~3 weeks (p75: 7 weeks) with ~55 touches and almost always need an appointment.**
Contractors are relationship deals — near-zero cycle (the deal is agreed before the
opportunity exists), enormous lead age.

## By month (close month, PROJECT, last 13 months)

| Month | n | Value | Cycle med | Duration med | Top sources |
|---|---|---|---|---|---|
| 2025-07 | 13 | $95,243 | 16.2 | 49.0 | Store 9, Meta Ad 3 |
| 2025-08 | 14 | $89,355 | 6.3 | 8.1 | Store 6, Meta Ad 6 |
| 2025-09 | 12 | $126,350 | 7.2 | 12.9 | Store 9, Meta Ad 3 |
| 2025-10 | 13 | $124,820 | 6.9 | 14.0 | Store 8, Meta Ad 3 |
| 2025-11 | 10 | $83,855 | 1.4 | 52.2 | Store 6, Meta Ad 2 |
| 2025-12 | 8 | $81,371 | 0.0 | 23.6 | Store 7 |
| 2026-01 | 9 | $72,924 | 12.3 | 19.1 | Store 6, Meta Ad 3 |
| 2026-02 | 12 | $135,330 | 9.9 | 17.5 | Store 8, Meta Ad 3 |
| 2026-03 | 9 | $71,694 | 7.1 | 17.0 | Store 7 |
| 2026-04 | 12 | $118,822 | 8.2 | 22.9 | Store 6, Meta Ad 3 |
| 2026-05 | 15 | $125,227 | 11.1 | 20.2 | Store 10, Meta Ad 3 |
| 2026-06 | 12 | $111,068 | 24.6 | 117.2 | store 3, tradeshow 2 |
| 2026-07 | 11 | $119,500 | 8.3 | 12.4 | Meta Ad 2, PMQ 2, online 2 |

Steady ~9–15 wins/month, ~$70–135K/month for the past year. Full history back to
2023-07 in `analysis/output/stats.json`. Note the source-label drift starting
2026-06 (`store`, `onlinePreliminary Mobile Quote`, `online`) — new intake paths
writing new source strings.

## Appointment analysis — the sequence window

PROJECT wins by appointment mode (event-body-prefix method):

| Mode | n | Value (avg/deal) | Cycle med / p75 | Lead→appt med / p75 | Appt→won med / p75 | Touches before / after appt (med) |
|---|---|---|---|---|---|---|
| No appointment | 115 | $861K ($7.5K) | 10.8 / 28.5 d | — | — | — |
| In-home only | 94 | $696K ($7.4K) | 13.3 / 32.4 d | 1.6 / 12.2 d | **15.9 / 50.1 d** | 5 / 26.5 |
| In-home + in-store | 31 | $338K (**$10.9K**) | 14.9 / 21.1 d | 0.1 / 2.0 d | 15.4 / 22.1 d | 3 / 27 |
| Unknown mode | 30 | $236K ($7.9K) | 16.0 / 41.3 d | 0.2 / 1.1 d | 15.9 / 40.6 d | 2 / 36 |
| In-store only | 5 | $87K ($17.3K, n=5) | 9.1 / 10.1 d | 1.6 / 4.0 d | 8.1 / 8.3 d | 4 / 20 |
| Other combos | 15 | $158K | — small groups | — | — | — |

All appointment modes pooled (n=175): lead→appt median **0.9 d** (p75 6.6),
appt→won median **16.0 d** (p75 **42.1**), touches before appt median 4, after
median **30**.

What this says:

1. **The appointment happens almost immediately** — half of appointed wins booked
   within a day of the lead. If a lead hasn't booked within ~a week (p75 6.6 d),
   it is outside the pattern that wins follow.
2. **The close happens weeks after the appointment, after heavy contact.** The
   appointment→won stretch — the exact window the Meeting-scheduled sequence must
   cover — runs **~16 days at the median and ~42 days at p75**, and winning deals
   log a median of **30 more touches after the appointment** (p75 51; includes
   inbound — the data can't split outbound-only after the appointment).
3. **Deals that visit the store close bigger.** In-home+in-store combos average
   $10.9K/deal vs $7.4K for in-home only, with a *tighter* p75 (22 vs 50 days).
   Getting an in-home lead into the showroom looks like the highest-leverage move
   in the data.
4. **40% of wins never had an appointment at all** ($861K) — the sequence must not
   be the only follow-up path.

## Contact-point analysis (PROJECT)

- Channel mix across all pre-close touches: **SMS 11,582 (76%) · calls 2,930
  (19%) · email 683 (4.5%) · WhatsApp 44**. SMS is the business's native channel;
  email is marginal.
- Outbound:inbound = **1.19 : 1** (7,958 : 6,680) — winning threads are
  conversations, not broadcasts. Roughly every outbound gets an answer.
- Automated share of touches: **2%** — wins are almost entirely manual effort
  today. A sequence automating even the routine half of the 30 post-appointment
  touches is a large workload win.
- First response to a lead's first inbound: median **103 min**, p75 **25.5 h**.
  The tail is the problem: a quarter of eventual *wins* still waited a day+ for a
  first reply.

## Recommended sequence — `*Meeting (Scheduled)* CCAM|GHL`

Every number cites the analysis; the shape is: heavy in weeks 1–2 (median close at
16 d), taper to day 42 (p75), explicit exit.

| Day (post-appointment) | Channel | Why |
|---|---|---|
| 0 (same day) | SMS recap + quote link | Winning cadence starts immediately; median gap between outbound touches on won deals is <1 day |
| 2 | Call, SMS fallback | Calls are 19% of winning touch volume; early window is where touch density is highest |
| 5 | SMS (quote question prompt) | Keeps pace with the ~30-touch post-appt median without spamming |
| 9 | Call + SMS | Store-visit invite — in-home+in-store deals average $10.9K vs $7.4K and close tighter (p75 22 d vs 50 d) |
| 16 | SMS check-in | The median win closes here (appt→won median 16.0 d) — this touch lands at peak close probability |
| 23 | SMS | Bridge the median-to-p75 gap |
| 30 | Call | Second half of the p75 window; Meta Ad wins (p75 cycle 51 d) are still live here |
| 42 | Final call + "should I close your file?" SMS | p75 appt→won is 42.1 d — this is the evidence-backed end of the active window |
| Exit | — | No inbound in the full 42-day window → `stale_lead` tag, Postponed stage. **Do not auto-abandon Meeting-stage deals before ~day 45 post-appointment** — a quarter of historical wins were still open at day 42 |

`[FILL: needs Albert's judgment]`: message copy and tone; which touches are
automated vs assigned to the record's `ghl_assigned_to` user; whether day-23/30
touches skip when the client has an active inbound thread; and the parallel path
for the 40% of wins that never book an appointment (this data can't anchor a
sequence for them — their anchor would be quote-sent date, which the mobile-quote
5-day follow-up already partially covers).

Wider abandonment implication (beyond this stage): the current 7-day hot-stage
threshold is far inside the winning window for ad leads — Meta Ad wins have a
median cycle of 20 days and a p75 of **51 days**. Today's auto-abandonment of a
quoted $29,690 hot lead (Bushra Masoom) at ~2 weeks is exactly the failure mode
this table predicts. Source-aware thresholds (Store ~4 weeks, Meta Ad ~7 weeks)
would fit the data; a single global timer does not.

## Caveats

- **Won-only bias**: every figure describes deals that closed. ~1,132 abandoned
  opportunities are the unmeasured denominator; fast-looking sources may just
  abandon slow leads. Nothing here is a conversion rate.
- **GHL-logged touches only**: walk-ins, off-platform calls, and in-person store
  conversations undercount — `Store` wins especially will show fewer touches than
  actually happened.
- **Repeat customers inflate lead age**: 23% of project wins had a contact record
  >30 days older than the deal; that is why `duration` ≫ `cycle` and why `cycle`
  is the number to plan follow-up around.
- **Mode classification**: 30 appointed wins have unknown mode (no `Visit:`/`Store:`
  prefix); tag-based classification would bucket some differently.
- **Anomaly**: Elena Pass (`bCf7u68k6fbEI6VcO1hB`), won 2026-06-26, $0, sits in the
  Lead Qualification pipeline — misfiled, excluded, needs a manual fix in GHL.
- Data pulled live 2026-07-26; numbers shift as records are edited in GHL.
