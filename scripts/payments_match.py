#!/usr/bin/env python3
"""Suggest which project an unlinked customer payment belongs to. READ ONLY.

Decision 12 (Albert, 2026-10-05): payments are SUGGESTED, never linked — Albert
accepts each one. Make 4280466 creates a Master Payments Log row per Interac email
with no project; this proposes one, with a confidence and a plain reason.

Signals, strongest first:
  * memo carries the project's street number + street name, or its phone digits;
  * sender's name shares a surname-length token with the project's client name;
  * amount equals an installment of the post-discount `Value Approx` (35/35/30, data
    in payout-policy.json) or the remaining balance, within amount_tolerance_cents.

High  = address/phone hit, or name AND amount.  Medium = name alone, or amount alone
on a project with a name hit elsewhere.  Nothing below Medium is suggested.

The memo (`Message`) often holds a customer's address and phone: it is read for
matching and NEVER written into a reason, plan or log — reasons name the signal only.

Used by scripts/project_costs_sync.py; also a CLI over a snapshot:
    python3 scripts/payments_match.py --snapshot ingest/<date>/notion-finance.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import payout_run as pr  # noqa: E402

STOP = {"the", "and", "inc", "ltd", "mr", "mrs", "ms", "dr", "from", "for", "flooring"}


def tokens(text):
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) >= 3 and t not in STOP}


def street_key(addr):
    """'123 Maple Ave, Unit 4' -> ('123', 'maple'); None when no number."""
    m = re.search(r"\b(\d{1,6})\s+([A-Za-z][A-Za-z'\-]+)", addr or "")
    return (m.group(1), m.group(2).lower()) if m else None


def digits(s):
    d = re.sub(r"\D", "", s or "")
    return d[-10:] if len(d) >= 10 else None


def expected_amounts(project, paid_so_far, policy):
    value = pr.money(project.get("value"))
    if not value:
        return []
    out = []
    for split in policy["payments_match"]["installment_splits"]:
        out += [round(value * s, 2) for s in split]
    bal = round(value - paid_so_far, 2)
    if bal > 0:
        out.append(bal)
    return out


def score(payment, project, paid_so_far, policy):
    reasons, strong = [], False
    memo = payment.get("message") or ""
    sk = street_key(project.get("street_address"))
    if sk and re.search(rf"\b{sk[0]}\s+{re.escape(sk[1])}", memo.lower()):
        reasons.append("memo carries the project's street address")
        strong = True
    ph = digits(project.get("contact"))
    if ph and ph in re.sub(r"\D", "", memo):
        reasons.append("memo carries the project's phone number")
        strong = True
    name_hit = bool(tokens(payment.get("senders_name")) &
                    (tokens(project.get("client_name")) | tokens(project.get("title"))))
    if name_hit:
        reasons.append("sender's name matches the client")
    amt = pr.money(payment.get("amount"))
    tol = policy["payments_match"]["amount_tolerance_cents"] / 100
    amount_hit = amt is not None and any(abs(amt - e) <= tol for e in expected_amounts(project, paid_so_far, policy))
    if amount_hit:
        reasons.append("amount matches an installment or the balance")
    if strong or (name_hit and amount_hit):
        return "High", reasons
    if name_hit:
        return "Medium", reasons
    return None, reasons


def suggest(snapshot, reg, policy):
    """One suggestion per unlinked payment that has a Medium-or-better match."""
    n = pr.normalize_snapshot(snapshot, reg)
    paid = {}
    for pay in n["payments"]:
        for p in pr.as_list(pay.get("projects")):
            paid[pr.page_id(p)] = paid.get(pr.page_id(p), 0) + (pr.money(pay.get("amount")) or 0)
    out = []
    for pay in n["payments"]:
        if pr.as_list(pay.get("projects")) or pr.as_list(pay.get("suggested_project")):
            continue
        best = []
        for proj in n["projects"]:
            pid = pr.page_id(proj["url"])
            conf, reasons = score(pay, proj, paid.get(pid, 0), policy)
            if conf:
                best.append((0 if conf == "High" else 1, conf, reasons, proj))
        best.sort(key=lambda b: b[0])
        if not best:
            continue
        top = best[0]
        if len(best) > 1 and best[1][0] == top[0]:
            out.append({"payment_url": pay["url"], "suggested_project_url": None,
                        "confidence": "Low", "reason": f"{len([b for b in best if b[0] == top[0]])} projects match "
                                                      f"equally ({top[1]}) — pick by hand"})
            continue
        out.append({"payment_url": pay["url"], "suggested_project_url": top[3]["url"],
                    "pp": pr.pp_label(top[3]), "confidence": top[1], "reason": "; ".join(top[2])})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--snapshot", required=True, type=Path)
    args = ap.parse_args(argv)
    s = pr.SETTINGS
    res = suggest(pr.load_json(args.snapshot), pr.load_json(s / "notion-finance.json"),
                  pr.load_json(s / "payout-policy.json"))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
