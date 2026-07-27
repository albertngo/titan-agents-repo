---
description: Print the daily sales-manager dashboard for Titan Flooring. Read-only; no writes.
---

Print the daily sales-manager dashboard for Titan Flooring.
Read-only: no writes to the vault, the repo, or GHL. Do not call the `ghl` MCP server.

## Input
Primary: `ingest/<DATE>/ghl.json` (<DATE> = argument, else today).
Trend window: also read `ingest/<D>/ghl.json` for the 7 days before <DATE>.
Missing days in the window are fine — note "N of 7 prior days available" once
and trend on what exists. If the PRIMARY day is missing or its `status` is not
ok, print one line saying so and stop.

Plan: also check for `plans/<DATE>/plan.json` (contract:
`contracts/plan-schema.md`). If present AND its `status` is ok, section 1
renders from it. If absent, malformed, or `status` is not ok, section 1 falls
back to its interim logic — and when the file exists but is unusable, print
one line noting the plan file was unusable (a broken plan must be visible,
never silently ignored). When rendering from a plan, also read
`plans/<DATE>/approvals.json` for decision statuses (reference shape in the
plan contract). These are the ONLY additional files this command may read
beyond the ingest window above. Still no other files, no live API calls.

## Global rules
- Counts come from `reporting`, never from counting `items` (50-cap + rollup).
- Project pipeline and STORE: Material pipeline are separate businesses.
  Separate lines everywhere. Never sum their counts or values.
- Trim stage names before any comparison (ingest emits them byte-exact,
  trailing spaces included).
- Rank urgency by percentage of stage threshold consumed, never raw days.
- Never fabricate. A section with no data prints "no data" — not zeroes,
  not estimates.

## Output — plain text, sections in THIS order, most urgent first

### 1. DO TODAY (the whole point — get this right)
**INTERIM LOGIC BELOW — superseded by planner output when available.**

If `plans/<DATE>/plan.json` is usable: render its `actions` ordered by
`rank`, top 5, then "+N more pending". Per line:
  Name — action_type in plain English — one-line why, taken from the
  action's `note` (fall back to naming its `basis.drift_type` in plain
  English if note is empty).
Mark any action whose id appears in `plans/<DATE>/approvals.json` as
(approved) or (rejected); unlisted ids show as (pending). If
approvals.json doesn't exist, all show (pending) — do not remark on
the file's absence, that's the normal starting state.
Do not re-rank, filter, or merge in your own findings — the plan is
authoritative for this section. Findings you'd have flagged that the
plan lacks belong in section 4, not here.

Fallback (no usable plan file): ranked list from `workflow_drift` +
`stragglers_ranked`, ordered by % of stage threshold consumed,
descending. Cap at 5, then "+N more". Per line:
  Name — pipeline/stage — X% of threshold (Nd of Md) — one suggested
  action.
Suggested actions in fallback mode are advisory display text ONLY —
they are not a contract, carry no rule_id, and nothing may ever
execute from them. Meeting-scheduled items rank on appointment-date
anchor as ingest computes it. A warm lead at 85% outranks a cold lead
at 40% regardless of raw days.

### 2. NEW LEADS
Real count (raw N; X excluded: spam/supplier — from `reporting.exclusions`).
Speed to first contact, using the `first_contact` definition (first message
either direction): average when all under 24h; per-lead callout lines for any
lead over 24h or not yet contacted. If per-lead first_contact timing is not
present in the file, print: "speed-to-contact: not captured by ingest" —
do not derive it from anything else.

### 3. MOVEMENT (not a snapshot)
Two blocks: PROJECT, then STORE. Per block: entered / advanced / won /
postponed-or-lost yesterday, from `opportunities` + `won_records`.
Won lines include value (project only in headline; store value on its own
line) and cycle_days where present. Then: count of opportunities past their
appointment date with no follow-up (`meeting_no_followup`), with names.

### 4. PROCESS LEAKS (trended)
Count per drift type for <DATE> vs. the average of available prior days.
Flag any type where today > prior average with "RISING". List individual
cases only for drift items whose stable ID does not appear in any prior
day's file — label them "NEW". Flat counts get one summary line, no detail.

### 5. WINS & CYCLE
Every win from <DATE>: name, business, value, cycle_days (created→won),
repeat_customer flag. One trailing line: median cycle_days across the
8-day window, per business, only if n ≥ 3 for that business — else
"n too small". Never quote percentiles on fewer than 3 wins.

## Do not
- No conversation-count headline. No sentiment scores without a name attached.
- No metric that doesn't change an action before noon — if unsure, cut it.
- No IDs, field names, or jargon in output. Names and plain English.
- Target under 350 words; section 1 is never the section that gets trimmed.
