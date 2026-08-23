# Titan Agents — Roadmap

Written 2026-08-23. Supersedes nothing; CLAUDE.md remains the architecture authority.
Decisions recorded here were made by Albert on 2026-08-23 and are cited inline.

## Where things actually stand

The system sees well and does not act. Ingest runs fired **every morning** 2026-08-15
through 2026-08-22 (08:14–08:51 each day) — scheduling is not the problem. Three things
are:

1. **Artifacts didn't persist.** All eight days sat complete on unmerged `claude/*`
   branches. `main-agents` last saw 2026-08-14. Every brief for a week reported "no run
   at all" for days that had in fact run, the Notion ingester cold-started off an 8-day-old
   snapshot, GHL/Outlook/Meta all ran multi-day catch-up windows, and 29 logged
   `notion-sync` actions were invisible to the vault (which recorded "Actions taken: None"
   on days that had 3, 6, 10 and 10).

2. **Connector auth is the dominant failure mode**, and it fails silently.
   - QuickBooks: 16+ consecutive failed runs since 2026-07-26. The agent reported "no QBO
     server configured in `.mcp.json`". That was wrong — the connector is a session-level
     claude.ai connector and always existed. Its **OAuth token was expired**. A month
     blind on cash because the error named the wrong thing.
   - GHL: lost 2026-08-15, 08-18 and 08-19 entirely. Root cause found on 08-19 — the `ghl`
     MCP server was in `Pending approval`, a state a non-interactive scheduled run cannot
     clear. 08-21 then degraded to `partial` under a forced 7-day catch-up window.

3. **Nothing closes the loop.** `ghl-actions-agent` has never executed once (no
   write-scoped token, no write tools granted). `planner-agent` is parked. The result is
   visible in the vault: Sowmya's material question unanswered before an Aug 27 install,
   Sabrina Agard's deposit sent and install date unconfirmed 4+ days, Michael Camara asked
   twice for a quote, Felix D'Souza silent 6 days, Phuong Nguyen confirmed cash-ready and
   waiting. Tactical Tasks sit at 92% stale — "flagged 4 runs running, growing not shrinking."

## Goal

**Financial visibility** (Albert, 2026-08-23). Titan has been blind on cash-in, A/R and
A/P for a month. Close that first; reply-latency work follows behind it.

---

## Phase 0 — Persistence and honesty · DONE 2026-08-23

- [x] Recovered `ingest/2026-08-15` … `2026-08-22` from their eight unmerged branches.
- [x] Rebuilt `run-ledger.json` with truthful per-source status for those days, each entry
      naming the branch it was recovered from and the real failure cause.
- [x] `daily-ingest` step 6: **commit ingest artifacts straight to `main-agents`, no PR**
      (Albert, 2026-08-23). Ingest output is data, not code. Code changes still go via
      session branch + PR.
- [x] `daily-ingest` step 1: check unmerged branches before declaring a day missed.
- [x] `daily-ingest` step 4: **Connector health** — an auth/approval failure is a
      first-class `needs_attention` bullet naming who fixes it and the streak length.

## Phase 1 — Financial visibility · IN PROGRESS

**Blocked on Albert:** re-authorize the Intuit QuickBooks connector in claude.ai connector
settings. ~2 minutes. Nothing in this repo can substitute for it, and every day it waits
adds to a 16-run streak.

- [x] `bookkeeper-ingest-agent` v2 rewritten:
      - correct connector story (session-level, not `.mcp.json`) with the wrong diagnosis
        called out explicitly so it can't recur;
      - a four-way **failure taxonomy** (`qbo_not_authorized` / `qbo_not_granted` /
        `qbo_api_error` / `qbo_partial`) that names who owns the fix;
      - scope widened from v1's three item types to five — adding `receivable` (A/R aging,
        customers over $5k past 60 days) and `payable` (bills newly overdue or due within
        7 days, the class that caught BlueAnt Media only via Outlook);
      - eight metrics, the three v1 keys preserved;
      - **read-only tools only in the `tools:` grant** — the QBO connector also exposes
        invoice-send, invoice-delete, transaction-import and full payroll writes. Not
        granting them is the enforcement, not the instruction.
- [ ] First green run. Confirm cents conversion, accrual-basis labelling, and that A/R
      totals reconcile against Notion's Master Payments Log.
- [ ] Add a cash line to `DAILY-BRIEF.md` "Numbers" — today the brief has no cash figure at all.
- [ ] Reconcile the Notion-vs-QBO value conflict class. Precedent: the Sonia win reported
      at $2,938.90 on 08-19 and $2,347.00 on 08-20 for the identical record, with the brief
      total silently adopting the new number and nobody reconciling it.

## Phase 2 — Connector health as a system property

Phase 0 makes a dead connector *visible*. This makes it *hard to ignore*.

- [ ] Preflight in `daily-ingest`: probe each connector before spawning ingesters, so a
      dead connector is known in seconds rather than inferred from an empty result.
- [ ] Resolve the GHL `Pending approval` state so scheduled non-interactive runs stop
      losing days. This is a provisioning fix, not a code fix.
- [ ] Escalation rule: 3 consecutive auth failures on any source → the brief leads with it.
- [ ] Check the Make.com **"Website Inquiry Ingester"**, erroring since 2026-08-19 and still
      unpaused. If it's dropping website leads that is revenue lost, and nobody owns Make
      monitoring today. A `make-ingest-agent` covering scenario health is the candidate fix.

## Phase 3 — Reply latency (the money problem)

Deferred behind Phase 1 by choice, not because it's smaller. **Draft-only autonomy**
(Albert, 2026-08-23): the planner drafts, Albert approves each batch in chat, the actions
agent sends. No message reaches a customer unread.

- [ ] Un-park `planner-agent` with **one rule only**: R1 `meeting_no_followup` →
      `draft_followup`. Its documented ranking-field gap only blocks ranking *across* all
      six drift types; a single-rule v1 never hits it. Un-parking criteria 1 and 2 still
      apply and can now be checked against 8 recovered real ingest days.
- [ ] Issue a write-scoped GHL Private Integration Token (separate from the read-only
      `$GHL_PIT_TOKEN`).
- [ ] Grant `ghl-actions-agent` exactly two tools: `conversations_send-a-new-message`,
      `contacts_add-tags`. Nothing else. Widen only on evidence.
- [ ] Success metric, in the brief: unanswered-conversation count trending down. It has sat
      between 9 and 45 all month.

## Phase 4 — Identity spine and dedup memory

Both cause daily, compounding waste.

- [ ] **Crosswalk.** `Sabrina Agard` vs "Sabrina Crvik", `Felix D'Souza` vs "Basil Felix Da
      Souza", `Sonia` vs "Sonia Rocha" have been unresolved for a week because Outlook emits
      no GHL contact ID. This is joinable today on email and phone — nobody has joined it. A
      `contacts/crosswalk.json` keyed on `(ghl_contact_id, email, phone, notion_page_id,
      vault_note)`, appended to when a match is confirmed, ends the class.
- [ ] **Per-source `seen` memory.** A win from 08-16 was re-reported on 08-19, 08-20, 08-21
      and 08-22. Dedup currently happens downstream, in prose, in the vault-writer, at full
      reasoning cost, every day. Ingesters should carry the IDs they've already emitted.

---

## Explicitly not doing yet

- **More sources.** Adding ingesters compounds the act-on-it gap rather than closing it.
- **Auto-send to customers.** Rejected for now in favour of draft-only.
- **`create_task` in GHL.** No MCP write tool exists; it stays refused.
- **Tier-3 promotion for analyses.** The ladder in CLAUDE.md holds — the bar is joining the
  scheduled daily flow, and nothing currently qualifies.

## Open, needs Albert

1. **Re-auth QuickBooks.** Phase 1 cannot start without it.
2. **Tactical Tasks backlog** — 92% stale, oldest 138 days, flagged four runs running with
   no decision ever recorded. Batch-archive, or accept the backlog and stop flagging it?
   Either is fine; the current state (flag forever, decide never) is the one that isn't.
3. **The 25 stale `claude/*` branches** on the remote. Now that ingest commits go direct to
   `main-agents`, they hold nothing unique except the eight recovered days. Delete after
   this merges?
4. **Damian** — same `ghl_contact_id` as a won/complete Innisfil stairs job, but an active
   "hot lead, in-home visit booked" conversation. Genuine second engagement or a GHL data
   problem? Unresolved since 08-20 and only checkable in the GHL UI.
