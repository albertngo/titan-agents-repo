#!/usr/bin/env python3
"""Execute an APPROVED catalogue plan against Lightspeed. THIS CHANGES THE LIVE POS.

    python3 scripts/lightspeed_push.py --plan plans/2026-09-10/catalog-plan-lee_flooring.json --dry-run
    python3 scripts/lightspeed_push.py --plan plans/2026-09-10/catalog-plan-lee_flooring.json

Reads three files and refuses to act without all of them:

  the plan       plans/<date>/catalog-plan-<supplier>.json
  the approval   plans/<date>/catalog-approval-<supplier>.json  — see the contract
  today's log    ingest/<date>/actions-log.json                 — for resume

An action runs only if its id appears in the approval with status "approved" AND is
not already recorded `executed` in today's actions-log. Absence of an approval file
means nothing is approved; it never means "go ahead". Partial approval is normal.

## Resume and idempotency

Action ids are a stable hash of supplier + sku + system + op, so a re-run produces
the same ids. A run stopped by a rate limit or a failure resumes by being run again:
anything already logged `executed` is skipped. There is no separate state file.

## Stop the batch

On any failure the run stops rather than continuing. That is the house rule for
actions agents, and it matters more here than usual: a half-applied family is harder
to reason about than an un-applied one.

## Creates

Grouped into one POST per family, keyed on `name` — the field Lightspeed uses to
group a variant family. Names for category, brand and supplier are resolved to ids
against the live account, and an unresolved name STOPS the run. Nothing here creates
a brand, a supplier, a category or a variant attribute: the account already carries
116 supplier names for far fewer real suppliers, and adding to that mess
automatically would be worse than stopping.

The created ids come back as a flat array in Lightspeed's own order, so they are
never paired positionally. The family is re-read and paired on sku, and the result
is written to plans/<date>/catalog-backfill-<supplier>.json for the Airtable side to
consume.
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lightspeed_client import LightspeedError, load_config  # noqa: E402
from lightspeed_write import LightspeedWriter  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/Toronto")
AGENT = "lightspeed-actions-agent"


def today():
    return datetime.now(TZ).date().isoformat()


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


class Log:
    """Today's actions-log. Appended to as work happens, never at the end."""

    def __init__(self, path):
        self.path = path
        self.data = (json.loads(path.read_text()) if path.exists()
                     else {"contract_version": "1", "entries": []})

    def executed_ids(self):
        return {e.get("raw_ref_action_id") for e in self.data["entries"]
                if e.get("result") == "executed"}

    def append(self, action_id, type_, target, summary, approved_by,
               result, error=None, raw_ref=None):
        self.data["entries"].append({
            "logged_at": now(), "agent": AGENT, "type": type_, "target": target,
            "content_summary": summary, "approved_by": approved_by,
            "result": result, "error": error, "raw_ref": raw_ref,
            "raw_ref_action_id": action_id,
        })
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1) + "\n")


def load_approval(path, plan_path):
    if not path.exists():
        raise SystemExit(
            f"error: no approval file at {path}.\n"
            "Nothing is approved. An approval file names the action ids a person "
            "signed off; its absence never means proceed. See "
            "contracts/catalog-plan-schema.md."
        )
    approval = json.loads(path.read_text())
    named = approval.get("plan")
    if named and Path(named).name != Path(plan_path).name:
        raise SystemExit(
            f"error: approval is for {named}, not {plan_path}.\n"
            "Action ids are stable across re-runs by design, so matching ids do NOT "
            "mean matching plans. Re-approve against this plan."
        )
    return approval, {d["id"] for d in approval.get("decisions", [])
                      if d.get("status") == "approved"}


class Lookups:
    """Name -> id, read live. Never creates anything."""

    def __init__(self, client):
        self.c = client
        self._cache = {}

    def _table(self, path, label):
        if label not in self._cache:
            rows = self.c.get(path).get("data", [])
            index = {}
            for r in rows:
                name = (r.get("name") or "").strip()
                if name:
                    index.setdefault(name.casefold(), r["id"])
            self._cache[label] = index
        return self._cache[label]

    def resolve(self, kind, name):
        paths = {"product_type": ("/api/2.0/product_types", "product type"),
                 "brand": ("/api/2.0/brands", "brand"),
                 "supplier": ("/api/2.0/suppliers", "supplier"),
                 "attribute": ("/api/2.0/variant_attributes", "variant attribute")}
        path, label = paths[kind]
        index = self._table(path, kind)
        got = index.get((name or "").strip().casefold())
        if got is None:
            raise LightspeedError(
                f"no {label} named {name!r} exists in Lightspeed. Refusing to create "
                f"one — {label}s are added by a person, deliberately. Known values "
                f"include: {sorted(list(index))[:8]}"
            )
        return got


def build_family_payload(actions, lookups, cfg):
    """One POST body for one variant family. Every id resolved or it raises."""
    first = actions[0]["fields"]
    payload = {"name": first["name"]}
    if first.get("handle"):
        payload["handle"] = first["handle"]
    if first.get("description"):
        payload["description"] = first["description"]
    if first.get("product_category"):
        payload["product_type_id"] = lookups.resolve("product_type", first["product_category"])
    if first.get("brand_name"):
        payload["brand_id"] = lookups.resolve("brand", first["brand_name"])
    if first.get("supplier_name"):
        payload["supplier_id"] = lookups.resolve("supplier", first["supplier_name"])

    outlet = cfg["outlet"]
    variants = []
    for a in actions:
        f = a["fields"]
        v = {"sku": f["sku"],
             # Titan is a tax-exclusive store, so outlet_taxes, never all_outlets_tax.
             "outlet_taxes": [{"outlet_id": outlet["id"], "tax_id": outlet["default_tax_id"]}]}
        for k in ("supply_price", "price_excluding_tax"):
            if f.get(k) is not None:
                v[k] = f[k]
        opt = f.get("variant_option")
        if opt:
            v["variant_definitions"] = [
                {"attribute_id": lookups.resolve("attribute", opt["name"]),
                 "value": opt["value"]}
            ]
        variants.append(v)
    payload["variants"] = variants
    return payload


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--approval", type=Path)
    ap.add_argument("--actions-log", type=Path)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print every request without sending it. Nothing is logged.")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    plan = json.loads(args.plan.read_text())
    supplier = plan["supplier"]
    slug = args.plan.stem.replace("catalog-plan-", "")
    approval_path = args.approval or args.plan.with_name(f"catalog-approval-{slug}.json")
    approval, approved = load_approval(approval_path, args.plan)

    log_path = args.actions_log or (REPO_ROOT / "ingest" / today() / "actions-log.json")
    log = Log(log_path)
    done = log.executed_ids()

    ls_actions = [a for a in plan["actions"] if a["target_system"] == "lightspeed"]
    todo = [a for a in ls_actions if a["id"] in approved and a["id"] not in done]
    skipped_unapproved = [a for a in ls_actions if a["id"] not in approved]
    skipped_done = [a for a in ls_actions if a["id"] in approved and a["id"] in done]

    print(f"plan       {args.plan}")
    print(f"approval   {approval_path}  ({len(approved)} approved ids)")
    print(f"supplier   {supplier}")
    print(f"lightspeed actions: {len(ls_actions)} in plan, {len(todo)} to run, "
          f"{len(skipped_unapproved)} not approved, {len(skipped_done)} already executed")
    if not todo:
        print("nothing to do")
        return 0

    cfg = load_config()
    writer = LightspeedWriter(config=cfg, dry_run=args.dry_run, verbose=args.verbose)
    lookups = Lookups(writer)
    approved_by = f"{approval.get('approved_by', 'unknown')} via {approval_path.name}"

    updates = [a for a in todo if a["op"] == "update"]
    creates = [a for a in todo if a["op"] == "create"]
    backfill = {}

    try:
        for a in sorted(updates, key=lambda a: a["seq"]):
            writer.update_variant(a["ls_id"], details=a["fields"])
            if not args.dry_run:
                log.append(a["id"], "lightspeed_update_product",
                           f"{a['sku']} ({a['ls_id']})",
                           f"Set {', '.join(f'{k}={v}' for k, v in a['fields'].items())}.",
                           approved_by, "executed", raw_ref=a["ls_id"])
            print(f"  update {a['sku']:20} {a['ls_id']}")

        families = defaultdict(list)
        for a in creates:
            families[a["fields"].get("name")].append(a)
        for name, group in families.items():
            payload = build_family_payload(sorted(group, key=lambda a: a["seq"]), lookups, cfg)
            ids = writer.create_family(payload)
            print(f"  create family {name!r}: {len(group)} variant(s)")
            if args.dry_run:
                continue
            # Never pair positionally — re-read and match on sku.
            paired = writer.family_by_sku(ids[0])
            for a in group:
                variant = paired.get(a["sku"])
                if variant is None:
                    raise LightspeedError(
                        f"created the family but {a['sku']} did not come back in it. "
                        f"Re-read returned {sorted(paired)}. Not guessing which id is "
                        "which — resolve by hand before re-running.")
                backfill[a["sku"]] = variant["id"]
                log.append(a["id"], "lightspeed_create_product",
                           f"{a['sku']} in family {name!r}",
                           f"Created and confirmed by re-reading the family and matching "
                           f"on sku; Lightspeed assigned {variant['id']}.",
                           approved_by, "executed", raw_ref=variant["id"])
                print(f"    {a['sku']:20} -> {variant['id']}")
    except (LightspeedError, Exception) as e:  # noqa: BLE001 — stop the batch on anything
        if not args.dry_run:
            log.append(None, "lightspeed_update_product", f"batch for {supplier}",
                       f"Batch stopped: {e}", approved_by, "failed", error=str(e))
        print(f"\nSTOPPED: {e}", file=sys.stderr)
        print("Nothing after this point was attempted. Everything already applied is in "
              f"{log_path.name}; re-running skips it.", file=sys.stderr)
        return 1

    if backfill:
        out = args.plan.with_name(f"catalog-backfill-{slug}.json")
        out.write_text(json.dumps({
            "contract_version": "catalog-backfill-1",
            "supplier": supplier, "written_at": now(),
            "plan": str(args.plan), "sku_to_lightspeed_id": backfill,
        }, indent=1) + "\n")
        print(f"\n{out.name} — {len(backfill)} new UUIDs for the Airtable backfill")

    print(f"\n{json.dumps(writer.write_stats())}")
    if args.dry_run:
        print("DRY RUN — nothing was sent and nothing was logged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
