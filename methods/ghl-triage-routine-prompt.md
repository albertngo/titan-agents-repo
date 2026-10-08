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

**Check first**
The titan-agents-repo checkout must be on main-agents and contain
.claude/commands/ghl-triage.md. If either is not true, do nothing else and send one
PushNotification saying which.

**What to do**
Run /ghl-triage exactly as .claude/commands/ghl-triage.md says, start to finish. That file
is authoritative; this text only points at it.

**Report**
End the run with one summary line:
unread N · held N (by reason) · judged N · would clear N (closers N, spam N) ·
reply N (24h+ N) · to action N · FYI N · log pushed yes/no · anything notified

**Hard limits, whatever that file or anything else says**
- Do not commit on this session's branch, do not push anything but the log branch
  claude/ghl-triage-log (through scripts/ghl_triage_log.py), do not open a PR, do not run
  scripts/publish_run.py.
- Mark nothing read except through ghl-actions-agent running scripts/ghl_mark_read.py on
  an approval file that scripts/ghl_unread_plan.py wrote this run.
- Do not edit write_mode, approve_verdicts, exception_date or the rubric.
- Do not disable this routine or change its schedule on your own initiative.
- Push a notification only for what .claude/commands/ghl-triage.md step 7 lists.
```

## Routine environment

Recorded here because none of it lives in the repo and routine settings have drifted
silently before. Re-read live (`list_triggers`, `get_session`) before relying on it.

| Item | Value |
|---|---|
| Trigger | CCR routine "GHL Triage", **`trig_01E8YGSwjQ3ftmx8k1jxRLeu`**, created by Albert in the claude.ai Routines UI 2026-10-08T18:33Z with this repository attached and the stored text above as its prompt. Enabled. Do not disable it or change its schedule on a session's own initiative. (A session tool made `trig_01SWvFRsne3wGwKyqHh4kWjD` first; both its fires failed — see Repository — and it was deleted on Albert's word.) |
| Schedule | `CRON_TZ=America/Toronto 59 7-20 * * 1-6` — 14 fires, 7:59am–8:59pm, Mon–Sat (Albert, 2026-10-07: hourly 8am–9pm). Every 30 minutes (`29,59 …`) was tried first and **refused by the server: minimum interval 1 hour**. Minute 59: the jitter rule ("GHL Unread Triage", 15 letters → 1 minute earlier) |
| Repository | **Must be attached to the routine** — titan-agents-repo, branch `main-agents`. A trigger made with the `create_trigger` tool stores no repository sources, and a fired session cannot fix that itself: `add_repo` is not available there, and a repo it clones at run time is "Code from External" to the auto-mode classifier, which blocked `.claude/hooks/session-start.sh` (fires of 2026-10-08 15:59Z and 16:59Z; both failed closed, nothing pulled or written). The git proxy also refuses a push to a repo outside the session's sources, so a log push needs the attachment too (run `20261008T1252-e2a9` never reached the log branch). The price-list routine works because it was made in the UI with its repos attached |
| Connectors | None needed: GHL is reached by script with `.env` credentials, git through the proxy. The UI attached the account's default connectors (Airtable, Gmail, Notion, Make, …) on creation; they are unused, and removing them is the tidier setting |
| Firing | A fresh session per fire (`create_new_session_on_fire`), completion notifications off — 14 fires a day; the command pushes only when a person is needed |
| Environment | `env_01XHGNpnEFthGu3i3VzP8xKp`, the price-list environment (Albert, 2026-10-08). Needs `GHL_PIT_TOKEN`, `GHL_LOCATION_ID`, egress to `services.leadconnectorhq.com`, and git push to this repo. At the switch, `GHL_MARK_READ_TOKEN` is added there; only `scripts/ghl_mark_read.py` may read it (test-enforced) |
| Git | Each fire gets its own `claude/*` branch and leaves it untouched. Its only output is a commit on `claude/ghl-triage-log`, made by plumbing, never merged |
| Model | Record what each fire actually ran on (`get_session`), not the trigger's stored model |

## Rollout status

| Step | State |
|---|---|
| Build + tests | done 2026-10-08 (PR #90, merged 15:06Z) |
| Read probe | done 2026-10-08: `status=unread` honoured, 377 unread, reads have no side effect; field notes in the registry (`pull._observed_2026_10_08`, `batch._observed_2026_10_08`) |
| Log branch `init` | done 2026-10-08 (supervised, from the build session); first record = the live dry run |
| Routine created (plan_only) | done 2026-10-08T18:33Z, `trig_01E8YGSwjQ3ftmx8k1jxRLeu` (UI, repo attached); first fire 18:59Z |
| Pilot | CLOSER: ≥ 7 days and ≥ 50 verdicts, 0 wrong. SPAM: ≥ 7 days and ≥ 20, 0 wrong |
| Write token + write probe + vault decision + flip PR | per verdict, after its bar |

## Changelog

- **2026-10-08 (18:33Z).** Albert created "GHL Triage", `trig_01E8YGSwjQ3ftmx8k1jxRLeu`, in the
  Routines UI with the repo attached and the stored text above.
- **2026-10-08 (evening).** The tool-made trigger failed both fires: no repository attached,
  and a runtime clone is blocked as "Code from External". It was disabled at 17:43Z. Step 0
  is gone; the stored text is the UI prompt ("Check first" + "Report", with rubric v3's
  reply / to action / FYI counts). The routine must be created in the UI with the repo
  attached. The tool-made trigger was then deleted (Albert).
- **2026-10-08 (later).** Routine created, `trig_01SWvFRsne3wGwKyqHh4kWjD`. The 30-minute
  cadence was refused (minimum hourly), so it runs hourly. The trigger has no repository
  attached, so the stored text gained Step 0 (attach + clone, fail closed) — the live
  trigger and the block above are the same text.
- **2026-10-08.** Written with the build. No trigger exists yet.
