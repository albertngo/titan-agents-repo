#!/usr/bin/env python3
"""Turn triage candidates + the model's judgements into a plan. Deterministic, READ ONLY.

    python3 scripts/ghl_unread_plan.py --dir analysis/cache/ghl-triage/<date>/<run_id>
        [--write-approval] [--approved-by "Albert, this session"]

Reads <dir>/candidates.json and <dir>/judgements.json (absent is fine when todo.json was
empty) and writes <dir>/plan.json and <dir>/run.json (the record ghl_triage_log.py
appends to the log branch). For each conversation, in order:

1. a hold from the pull wins (the model never saw it);
2. else a cached model verdict for the same batch and rubric version;
3. else this run's judgement — missing -> held `unjudged`, unknown -> `invalid_verdict`;
4. then the guards, only ever toward a human: CLOSER with a '?' or a message over
   max_message_chars -> UNSURE; SPAM from anyone but a stranger -> UNSURE.

CLOSER and SPAM rows are `clear`. They become actions only in sweep mode, on a conversation
still unread, when the verdict is in policy.approve_verdicts (empty during the pilot). More
actions than policy.max_mark_read_per_run makes the plan `needs_person` and approves
NOTHING (Albert, 2026-10-08: all-or-nothing).

--write-approval writes <dir>/approval.json. Refused (exit 4) in brief mode, under
write_mode plan_only, with the kill switch on, or while policy.exception_date is null for a
policy approval; exit 5 when the plan is needs_person. Exit 2: bad or mismatched input.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "platform-settings" / "ghl-unread-triage.json"
TZ = ZoneInfo("America/Toronto")
PLAN_VERSION = "ghl-triage-plan-1"
APPROVAL_VERSION = "ghl-triage-approval-1"
JUDGEMENTS_VERSION = "ghl-triage-judgements-1"
CANDIDATES_VERSION = "ghl-triage-candidates-1"
PHONE_OR_EMAIL = (r"[\w.+-]+@[\w-]+\.[\w.]+", r"\+?\d[\d\s().-]{6,}\d")


class InputError(ValueError):
    pass


def load_registry(path=REGISTRY):
    return json.loads(Path(path).read_text())


def sanitize_reason(text, limit):
    text = " ".join(str(text or "").split())
    for pat in PHONE_OR_EMAIL:
        text = re.sub(pat, "[redacted]", text)
    return text[:limit]


def action_id(conversation_id, key, last_message_id):
    raw = f"{conversation_id}|{key}|{last_message_id}"
    return "gmr-" + hashlib.sha1(raw.encode()).hexdigest()[:12]


def check_inputs(candidates, judgements, reg):
    if candidates.get("contract_version") != CANDIDATES_VERSION:
        raise InputError(f"candidates contract {candidates.get('contract_version')!r} "
                         f"!= {CANDIDATES_VERSION}")
    rv = str(reg["rubric"]["version"])
    if str(candidates.get("rubric_version")) != rv:
        raise InputError(f"candidates were pulled under rubric {candidates.get('rubric_version')}, "
                         f"registry is {rv}")
    if judgements is not None:
        if judgements.get("contract_version") != JUDGEMENTS_VERSION:
            raise InputError(f"judgements contract {judgements.get('contract_version')!r} "
                             f"!= {JUDGEMENTS_VERSION}")
        if str(judgements.get("rubric_version")) != rv:
            raise InputError(f"judgements were made under rubric {judgements.get('rubric_version')}, "
                             f"registry is {rv}")


def resolve(c, verdicts, reg):
    """One row of the plan, before actions."""
    vocab = set(reg["verdicts"])
    limit = reg["reason_max_chars"]
    row = {k: c.get(k) for k in ("conversation_id", "contact_id", "contact", "channel", "unread",
                                 "batch_key", "waiting_hours", "last_inbound_hours", "excerpt")}
    row.update(model_verdict=None, verdict=None, verdict_source=None, guard=None,
               hold_reason=c.get("hold_reason"), reason="", disposition=None,
               age_flag=False, action_id=None)
    if row["hold_reason"]:
        row.update(verdict="HELD", verdict_source="hold")
    elif c.get("cached"):
        row.update(model_verdict=c["cached"]["verdict"], verdict_source="cache",
                   reason=sanitize_reason(c["cached"].get("reason"), limit))
    else:
        j = verdicts.get(c.get("batch_key"))
        if j is None:
            row.update(verdict="HELD", verdict_source="hold", hold_reason="unjudged")
        elif j.get("verdict") not in vocab:
            row.update(verdict="HELD", verdict_source="hold", hold_reason="invalid_verdict")
        else:
            row.update(model_verdict=j["verdict"], verdict_source="model",
                       reason=sanitize_reason(j.get("reason"), limit))

    if row["verdict_source"] in ("model", "cache"):
        v = row["model_verdict"]
        g = reg["guards"]
        batch = c.get("batch") or {}
        if v == "CLOSER":
            if g["closer_veto"]["question_mark"] and batch.get("has_question"):
                v, row["guard"] = "UNSURE", "closer_veto:question"
            elif batch.get("max_message_chars", 0) > g["closer_veto"]["max_message_chars"]:
                v, row["guard"] = "UNSURE", "closer_veto:length"
        elif v == "SPAM" and g["spam_stranger_only"] and not c.get("stranger"):
            v, row["guard"] = "UNSURE", "spam_not_stranger"
        row["verdict"] = v

    if row["hold_reason"] == "no_customer_text":
        row["disposition"] = "not_ours"
    elif row["verdict"] in reg["clearable_verdicts"]:
        row["disposition"] = "clear"
    else:
        row["disposition"] = "waiting"
        wh = row["waiting_hours"]
        if wh is not None:
            row["age_flag"] = wh >= reg["age"]["flag_hours"]
    return row


def build_plan(candidates, judgements, reg):
    check_inputs(candidates, judgements, reg)
    verdicts = (judgements or {}).get("verdicts", {})
    mode = candidates["mode"]
    approve = set(reg["policy"]["approve_verdicts"]) & set(reg["clearable_verdicts"])
    run_at = datetime.fromisoformat(candidates["run_at"])
    rows, actions = [], []
    by_id = {c["conversation_id"]: c for c in candidates["conversations"]}
    for c in candidates["conversations"]:
        row = resolve(c, verdicts, reg)
        # Backlog = the customer has gone quiet for backlog_days, judged by their LATEST
        # message: someone who wrote 20 days ago and again yesterday is live, not backlog.
        quiet = row["last_inbound_hours"] if row["last_inbound_hours"] is not None else row["waiting_hours"]
        if mode == "brief" and row["disposition"] == "waiting" and quiet is not None \
                and quiet > reg["age"]["backlog_days"] * 24:
            row["disposition"] = "backlog"
        rows.append(row)

    if mode == "sweep":
        clear = [r for r in rows if r["disposition"] == "clear" and r["unread"]
                 and r["verdict"] in approve]
        clear.sort(key=lambda r: -(r["waiting_hours"] or 0))
        for i, r in enumerate(clear, 1):
            c = by_id[r["conversation_id"]]
            r["action_id"] = action_id(r["conversation_id"], r["batch_key"], c["last_message_id"])
            actions.append({"id": r["action_id"], "seq": i, "op": "mark_read",
                            "conversation_id": r["conversation_id"], "contact_id": r["contact_id"],
                            "contact": r["contact"], "verdict": r["verdict"], "reason": r["reason"],
                            "batch_key": r["batch_key"],
                            "expect": {"last_message_id": c["last_message_id"]}})

    cap = reg["policy"]["max_mark_read_per_run"]
    status = "needs_person" if len(actions) > cap else "ready"

    def count(key):
        out = {}
        for r in rows:
            if r.get(key):
                out[r[key]] = out.get(r[key], 0) + 1
        return out

    waiting = [r for r in rows if r["disposition"] == "waiting"]
    return {
        "contract_version": PLAN_VERSION, "run_id": candidates["run_id"], "mode": mode,
        "run_at": candidates["run_at"],
        "expires": (run_at + timedelta(minutes=reg["writer"]["max_plan_age_minutes"])).isoformat(),
        "write_mode": reg["write_mode"]["mode"], "rubric_version": reg["rubric"]["version"],
        "approve_verdicts": sorted(approve), "status": status,
        "kill_switch": (candidates.get("log") or {}).get("kill_switch"),
        "summary": {
            "conversations": len(rows),
            "by_verdict": count("verdict"),
            "held_by_reason": count("hold_reason"),
            "guarded": count("guard"),
            "by_source": count("verdict_source"),
            "would_clear": sum(1 for r in rows if r["disposition"] == "clear"),
            "would_clear_by_verdict": {v: sum(1 for r in rows if r["disposition"] == "clear"
                                              and r["verdict"] == v) for v in reg["clearable_verdicts"]},
            "actions": len(actions), "cap": cap,
            "waiting": len(waiting),
            "waiting_24h_plus": sum(1 for r in waiting if r["age_flag"]),
            "backlog": sum(1 for r in rows if r["disposition"] == "backlog"),
            "not_ours": sum(1 for r in rows if r["disposition"] == "not_ours"),
        },
        "rows": rows,
        "actions": actions,
    }


RUN_ROW_KEYS = ("conversation_id", "contact_id", "batch_key", "model_verdict", "verdict",
                "verdict_source", "guard", "hold_reason", "reason", "disposition",
                "waiting_hours", "action_id", "excerpt")


def run_record(plan, approval=None):
    """What goes to the log branch: no contact names, no message text (excerpt only when the
    registry's log.excerpts is on)."""
    return {"run_id": plan["run_id"], "run_at": plan["run_at"], "mode": plan["mode"],
            "write_mode": plan["write_mode"], "rubric_version": plan["rubric_version"],
            "status": plan["status"], "approved_by": (approval or {}).get("approved_by"),
            "approved_ids": [d["id"] for d in (approval or {}).get("decisions", [])],
            "summary": plan["summary"],
            "rows": [{k: r.get(k) for k in RUN_ROW_KEYS} for r in plan["rows"]],
            "notified": []}


def approval_for(plan, plan_path, reg, approved_by=None):
    """The approval file. PermissionError = refused (exit 4); LookupError = needs a person (5)."""
    if plan["mode"] != "sweep":
        raise PermissionError("brief mode never approves anything — the sweep is the only writer")
    if reg["write_mode"]["mode"] != "write":
        raise PermissionError(f"write_mode is {reg['write_mode']['mode']!r}: no approval file is "
                              "written and nothing is marked read (the pilot)")
    if plan.get("kill_switch"):
        raise PermissionError(f"the kill switch is on: {plan['kill_switch']}")
    if approved_by is None and not reg["policy"].get("exception_date"):
        raise PermissionError("policy.exception_date is null: the dated CLAUDE.md exception for "
                              "ghl-actions-agent does not exist yet, so policy cannot approve")
    if approved_by is not None and approved_by.lower().startswith("policy"):
        raise PermissionError("--approved-by names a person, never a policy")
    if plan["status"] == "needs_person" and approved_by is None:
        raise LookupError(f"{plan['summary']['actions']} conversations to clear, over the cap of "
                          f"{plan['summary']['cap']}: nothing approved, a person decides")
    now = datetime.now(TZ).isoformat(timespec="seconds")
    return {"contract_version": APPROVAL_VERSION, "run_id": plan["run_id"], "plan": str(plan_path),
            "approved_by": approved_by or reg["policy"]["approved_by"],
            "decisions": [{"id": a["id"], "status": "approved", "at": now} for a in plan["actions"]]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, required=True, help="The run directory the pull printed")
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    ap.add_argument("--write-approval", action="store_true")
    ap.add_argument("--approved-by", help="A person approving a needs_person plan, supervised only")
    args = ap.parse_args(argv)
    reg = load_registry(args.registry)
    candidates = json.loads((args.dir / "candidates.json").read_text())
    jpath = args.dir / "judgements.json"
    judgements = json.loads(jpath.read_text()) if jpath.exists() else None
    try:
        plan = build_plan(candidates, judgements, reg)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    plan_path = args.dir / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n")

    s = plan["summary"]
    print(f"  plan         {plan_path}")
    print(f"  mode         {plan['mode']}   write_mode {plan['write_mode']}   status {plan['status']}")
    print(f"  verdicts     {s['by_verdict']}   sources {s['by_source']}")
    print(f"  held         {s['held_by_reason']}   guarded {s['guarded']}")
    print(f"  would clear  {s['would_clear']} {s['would_clear_by_verdict']}   actions {s['actions']}/{s['cap']}")
    print(f"  waiting      {s['waiting']}   24h+ {s['waiting_24h_plus']}   backlog {s['backlog']}   "
          f"not ours {s['not_ours']}")

    code, approval = 0, None
    if args.write_approval:
        try:
            approval = approval_for(plan, plan_path, reg, args.approved_by)
        except PermissionError as exc:
            print(f"  approval NOT written: {exc}", file=sys.stderr)
            code = 4
        except LookupError as exc:
            print(f"  approval NOT written: {exc}", file=sys.stderr)
            code = 5
        else:
            (args.dir / "approval.json").write_text(json.dumps(approval, indent=1) + "\n")
            print(f"  approval     {len(approval['decisions'])} ids -> {args.dir / 'approval.json'}")
    (args.dir / "run.json").write_text(
        json.dumps(run_record(plan, approval), indent=1, ensure_ascii=False) + "\n")
    print(f"  run record   {args.dir / 'run.json'}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
