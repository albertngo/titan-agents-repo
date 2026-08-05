# Missed-call volume & response quality (per rep)

Measures how many inbound calls a GHL user misses and how well the misses get
followed up. Implemented by `analysis/pourya_missed_calls.py` (read-only;
cache under `analysis/cache/pourya_calls/`, gitignored). Tier 1 on first run
because the pull needs caching (~780 conversations / ~1,500 requests for a
2-month window).

## Run it

```
python3 analysis/pourya_missed_calls.py            # incremental (uses cache)
python3 analysis/pourya_missed_calls.py --refresh  # full re-pull
python3 analysis/pourya_missed_calls.py --days 61  # window length
```

Requires `GHL_PIT_TOKEN` + `GHL_LOCATION_ID` (source `.env` — the process env
can hold a stale token; see the 2026-08-04 log entry in the vault GHL note).
Outputs: `analysis/output/pourya_missed_calls.csv` (one row per missed-call
episode) + `pourya_missed_calls_summary.json`.

## Definitions (the traps)

- **A call belongs to the rep** when the inbound `TYPE_CALL` message carries
  his `userId` OR its `to` number is his direct GHL line. Pourya =
  `rAMFCiXbAjJOEjtyyvmn` / +16476060295. (Calls to the main line answered by
  him still carry his userId; calls that only *rang* his line unanswered can
  carry no userId, which is why the `to`-number fallback exists.)
- **Missed** = `meta.call.status` ∈ {no-answer, voicemail, busy, failed,
  canceled}. `completed` = answered. A lone `ringing` status is an in-flight
  record at pull time — excluded from both.
- **Episode**: consecutive missed calls from the same contact ≤ 60 min apart
  collapse into one episode (one caller ringing three times is one miss to
  respond to). Weekly *missed calls* and *episodes* are both reported.
- **Response**: first outbound touch (call/SMS/email/WhatsApp, any user, any
  conversation of that contact) after the episode's last attempt, within 72 h.
  An inbound `completed` call arriving first = "caller reached us again" —
  a recovery, not a response by us. Responses are searched across all of the
  contact's conversations because GHL sometimes splits calls and SMS into
  sibling conversations.
- Only GHL-logged calls count. Calls to Pourya's personal cell or walk-in
  conversations never appear; the miss rate describes the GHL line only.

## First run — 2026-08-04, Pourya, window 2026-06-05 → 2026-08-05

91 inbound calls (10.4/wk), 37 missed (4.2/wk, 41%), 33 episodes (3.8/wk).
Of the 33: 19 responded by us (median 7.5 min, 16/19 within 1 h — 14 callback
connected, 5 SMS), 9 recovered by the caller ringing back, 5 (15%) got no
response within 72 h. Findings note: vault `09_analyses/` (pending approval).
