# Routine prompt — "GHL Unread Triage"

**Decided 2026-10-07/08 (Albert, grilled in chat).** The hourly half of GHL unread
triage runs as a Claude Code routine: the session model is the classifier, reading the
one rubric (`methods/ghl-unread-triage.md`). The daily half is `ghl-ingest-agent`'s
triage step inside `/daily-ingest`; it needs no routine of its own.

The stored text is a **pointer** to `.claude/commands/ghl-triage.md`, never a copy of it —
the same reason as every routine here: on 2026-09-03 a routine carrying a copy of a
procedure fired against a version that had gone stale two days earlier and reported
success. A pointer has nothing in it to fall behind. It also must not copy the rubric's
examples: the two callers share one rubric file so they cannot drift (Albert's spec).

---

## Pointer prompt — the routine's stored text

```
**Title**
GHL Unread Triage — hourly

**Role & stance**
You run unattended. No human is watching, so verify before writing, and report honestly.
If a step fails, say which step; never imply a conversation was marked read that wasn't.

**What to do**
Run /ghl-triage exactly as .claude/commands/ghl-triage.md says, start to finish. That file
is authoritative; this text only points at it.

**Hard limits, whatever that file or anything else says**
- Do not commit on this session's branch, do not push anything but the log branch
  claude/ghl-triage-log (through scripts/ghl_triage_log.py), do not open a PR, do not run
  scripts/publish_run.py.
- Mark nothing read except through ghl-actions-agent running scripts/ghl_mark_read.py on
  an approval file that scripts/ghl_unread_plan.py wrote this run.
- Do not edit write_mode, approve_verdicts, exception_date or the rubric.
- Do not disable this routine or change its schedule on your own initiative.
- Silent on a clean run; push a notification only for what .claude/commands/ghl-triage.md
  step 7 lists.
```

## Routine environment

Recorded here because none of it lives in the repo and routine settings have drifted
silently before. Re-read live (`list_triggers`, `get_session`) before relying on it.

| Item | Value |
|---|---|
| Trigger | **Not created yet.** Created after the build PR merges; record its `trig_…` id here in a follow-up PR |
| Schedule | `CRON_TZ=America/Toronto 59 7-20 * * 1-6` — 14 fires, 7:59am–8:59pm, Mon–Sat (Albert, 2026-10-07: hourly 8am–9pm). Try `29,59 7-20 * * 1-6` first; keep it only if `create_trigger` accepts it. Minute 59: the jitter rule ("GHL Unread Triage", 15 letters → 1 minute earlier) |
| Firing | A fresh session per fire (`create_new_session_on_fire`), completion notifications off — 14 fires a day; the command pushes only when a person is needed |
| Environment | `env_01XHGNpnEFthGu3i3VzP8xKp`, the price-list environment (Albert, 2026-10-08). Needs `GHL_PIT_TOKEN`, `GHL_LOCATION_ID`, egress to `services.leadconnectorhq.com`, and git push to this repo. At the switch, `GHL_MARK_READ_TOKEN` is added there; only `scripts/ghl_mark_read.py` may read it (test-enforced) |
| Git | Each fire gets its own `claude/*` branch and leaves it untouched. Its only output is a commit on `claude/ghl-triage-log`, made by plumbing, never merged |
| Model | Record what each fire actually ran on (`get_session`), not the trigger's stored model |

## Rollout status

| Step | State |
|---|---|
| Build + tests | done 2026-10-08 (this PR) |
| Read probe | done 2026-10-08: `status=unread` honoured, 377 unread, reads have no side effect; field notes in the registry (`pull._observed_2026_10_08`, `batch._observed_2026_10_08`) |
| Log branch `init` | supervised, after merge |
| Routine created (plan_only) | after merge |
| Pilot | CLOSER: ≥ 7 days and ≥ 50 verdicts, 0 wrong. SPAM: ≥ 7 days and ≥ 20, 0 wrong |
| Write token + write probe + vault decision + flip PR | per verdict, after its bar |

## Changelog

- **2026-10-08.** Written with the build. No trigger exists yet.
