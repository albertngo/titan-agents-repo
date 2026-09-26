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


def person_approved(approval):
    """True when the approval names a person, not the policy rubric.

    The policy auto-approval writes `approved_by` starting "policy"; anything a
    person signs says who. Used to keep deletes out of every unattended path.
    """
    by = (approval.get("approved_by") or "").strip().lower()
    return bool(by) and not by.startswith("policy") and "auto-approval" not in by


class Lookups:
    """Name -> id, read live. Never creates anything."""

    def __init__(self, client):
        self.c = client
        self._cache = {}

    def _table(self, path, label):
        """name -> [id, ...]. A list, because Lightspeed allows duplicate names.

        Keeping every id rather than the first one is the point: `LAMINATE`,
        `TILE`, `VINYL` and `OTHER` each exist twice in Titan's product types
        (verified live 2026-09-20). Collapsing those to whichever row the API
        happened to return first would silently file a product under the wrong
        one, and nothing downstream would show it.
        """
        if label not in self._cache:
            rows = self.c.get(path).get("data", [])
            index = {}
            for r in rows:
                name = (r.get("name") or "").strip()
                if name:
                    index.setdefault(name.casefold(), []).append(r["id"])
                # A nested product type is also indexed by its full path, so
                # "FLOORING / TILE" names exactly one of the two live TILEs
                # (Albert, 2026-09-23: "use the TILE that is nested in FLOORING").
                # A bare duplicated leaf still refuses below.
                path = [(p.get("name") or "").strip() for p in r.get("category_path") or []]
                if len(path) > 1 and all(path):
                    index.setdefault(" / ".join(path).casefold(), []).append(r["id"])
            self._cache[label] = index
        return self._cache[label]

    def resolve(self, kind, name):
        paths = {"product_type": ("/api/2.0/product_types", "product type"),
                 "brand": ("/api/2.0/brands", "brand"),
                 "supplier": ("/api/2.0/suppliers", "supplier"),
                 "attribute": ("/api/2.0/variant_attributes", "variant attribute")}
        path, label = paths[kind]
        index = self._table(path, kind)
        raw = (name or "").strip()

        # The LS upload CSV carries a category PATH ("FLOORING / VINYL / WPC"),
        # per ls-upload-instructions. Lightspeed's product types are named by the
        # LEAF alone ("WPC"). Try the whole string first, so a type that really is
        # named with slashes ("CEMENT | SEALANT | GLUE" has none, but the shape is
        # allowed) still resolves, then fall back to the last segment.
        candidates = [raw]
        if "/" in raw:
            candidates.append(raw.rsplit("/", 1)[-1].strip())

        for cand in candidates:
            got = index.get(cand.casefold())
            if not got:
                continue
            if len(got) > 1:
                raise LightspeedError(
                    f"{label} {cand!r} is ambiguous — {len(got)} exist in Lightspeed "
                    f"with that name. Refusing to guess which one to file this "
                    f"product under; a person has to de-duplicate them, or the "
                    f"category has to name the right one unambiguously."
                )
            return got[0]

        raise LightspeedError(
            f"no {label} named {raw!r} exists in Lightspeed"
            + (f" (also tried {candidates[-1]!r})" if len(candidates) > 1 else "")
            + f". Refusing to create one — {label}s are added by a person, "
            f"deliberately. Known values include: {sorted(list(index))[:8]}"
        )


def _member_fields(action, lookups, cfg):
    """The per-product half of a create payload: sku, prices, tax, attributes."""
    f = action["fields"]
    outlet = cfg["outlet"]
    member = {"sku": f["sku"],
              # Titan is a tax-exclusive store, so outlet_taxes, never all_outlets_tax.
              "outlet_taxes": [{"outlet_id": outlet["id"],
                                "tax_id": outlet["default_tax_id"]}]}
    for k in ("supply_price", "price_excluding_tax"):
        if f.get(k) is not None:
            member[k] = f[k]
    opt = f.get("variant_option")
    if opt:
        member["variant_definitions"] = [
            {"attribute_id": lookups.resolve("attribute", opt["name"]),
             "value": opt["value"]}
        ]
    return member


def build_family_payload(actions, lookups, cfg):
    """One POST body for one product, or one variant family. Every id resolved or it raises.

    A standalone product is NOT a family of one on the write side. The registry's
    read-model note says otherwise -- every product carries a `family_id`, so
    "there is no separate simple product shape to handle" -- and that is true of
    what comes back from a GET and false of what a POST accepts. Sending a
    `variants` array whose single entry has no `variant_definitions` is rejected:
    422 `Each variant must have at least one variant definition` (2026-09-21).

    So a lone product with no variant attribute carries its sku and prices at the
    TOP level and sends no `variants` key at all. Per the reference, `name` is the
    only required field.

    The tempting way to satisfy that error is to invent a one-option variant. Do
    not: ls-upload-instructions forbids it -- "a variant group with only one option
    is noise, not structure" -- and it would put junk attributes on the product
    permanently, to work around a key that simply should not have been sent.

    One action that DOES carry a variant_option keeps the array. That is a
    deliberate family of one with real structure, and it validates.
    """
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

    members = [_member_fields(a, lookups, cfg) for a in actions]

    if len(members) == 1 and "variant_definitions" not in members[0]:
        payload.update(members[0])
        return payload

    payload["variants"] = members
    return payload


def write_backfill(path, supplier, plan_path, pairs):
    """Merge sku -> Lightspeed id pairs into the backfill file, atomically.

    Merged, never overwritten: a resumed run only holds the pairs IT created, and
    overwriting dropped ACC-OAKL-0001 on 2026-09-11 (fix ccab66f, never merged).
    Written through a temp file and a rename so a crash mid-write cannot leave
    half a file behind for the Airtable side to read.
    """
    if not pairs:
        return 0
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text()).get("sku_to_lightspeed_id", {}) or {}
        except (ValueError, OSError):
            existing = {}
    merged = {**existing, **pairs}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({
        "contract_version": "catalog-backfill-1",
        "supplier": supplier, "written_at": now(),
        "plan": str(plan_path), "sku_to_lightspeed_id": merged,
    }, indent=1) + "\n")
    tmp.replace(path)
    return len(merged)


def pairs_from_log(log, plan_actions):
    """sku -> Lightspeed id for every create of THIS plan already executed.

    A run that died before writing the backfill file left its UUIDs only in the
    actions-log (raw_ref). A resume skips those ids as done, so without this they
    would never reach the file, and the Airtable side would come up short.
    """
    creates = {a["id"]: a["sku"] for a in plan_actions
               if a["target_system"] == "lightspeed" and a["op"] == "create"}
    return {creates[e["raw_ref_action_id"]]: e["raw_ref"]
            for e in log.data["entries"]
            if e.get("result") == "executed" and e.get("raw_ref")
            and e.get("raw_ref_action_id") in creates}


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
        if not args.dry_run:
            recovered = pairs_from_log(log, plan["actions"])
            if recovered:
                out = args.plan.with_name(f"catalog-backfill-{slug}.json")
                total = write_backfill(out, supplier, args.plan, recovered)
                print(f"{out.name} — rebuilt from the actions-log ({total} UUIDs)")
        return 0

    cfg = load_config()
    writer = LightspeedWriter(config=cfg, dry_run=args.dry_run, verbose=args.verbose)
    lookups = Lookups(writer)
    approved_by = f"{approval.get('approved_by', 'unknown')} via {approval_path.name}"

    updates = [a for a in todo if a["op"] == "update"]
    creates = [a for a in todo if a["op"] == "create"]
    deletes = [a for a in todo if a["op"] == "delete"]
    markers = [a for a in todo if a["op"] == "promo_marker"]
    unknown = [a for a in todo if a["op"] not in ("update", "create", "delete", "promo_marker")]
    if unknown:
        print(f"error: unknown op(s) {sorted({a['op'] for a in unknown})}; nothing was sent.",
              file=sys.stderr)
        return 1
    if deletes and not person_approved(approval):
        print(f"error: {len(deletes)} delete action(s) under a policy approval "
              f"({approval.get('approved_by')!r}). A delete is only ever a person's "
              "decision; policy auto-approval can never carry one. Nothing was sent.",
              file=sys.stderr)
        return 1
    backfill_path = args.plan.with_name(f"catalog-backfill-{slug}.json")
    # Start from what earlier runs of this plan already created, so the file is
    # complete even when the run that created them died before writing it.
    backfill = {} if args.dry_run else pairs_from_log(log, plan["actions"])
    current = {"type": "lightspeed_update_product", "target": f"batch for {supplier}"}
    unresolved = []

    def save_backfill():
        if not args.dry_run and backfill:
            write_backfill(backfill_path, supplier, args.plan, backfill)

    try:
        for a in sorted(updates, key=lambda a: a["seq"]):
            current.update(type="lightspeed_update_product", target=f"{a['sku']} ({a['ls_id']})")
            writer.update_variant(a["ls_id"], details=a["fields"])
            if not args.dry_run:
                log.append(a["id"], "lightspeed_update_product",
                           f"{a['sku']} ({a['ls_id']})",
                           f"Set {', '.join(f'{k}={v}' for k, v in a['fields'].items())}.",
                           approved_by, "executed", raw_ref=a["ls_id"])
            print(f"  update {a['sku']:20} {a['ls_id']}")

        # The promo lane (scripts/promo_sweep.py, Albert 2026-09-26): the name prefix
        # only, guarded in set_promo_marker(), and confirmed by re-reading.
        for a in sorted(markers, key=lambda a: a["seq"]):
            current.update(type="lightspeed_update_product", target=f"{a['sku']} ({a['ls_id']})")
            f = a["fields"]
            writer.set_promo_marker(a["ls_id"], f["expect_sku"], f["expect_name"], f["name"])
            if not args.dry_run:
                after = writer.read_product(a["ls_id"])
                if after.get("name") != f["name"] or after.get("sku") != f["expect_sku"]:
                    raise LightspeedError(
                        f"promo marker on {a['sku']}: re-read shows name "
                        f"{after.get('name')!r}, sku {after.get('sku')!r}")
                log.append(a["id"], "lightspeed_update_product",
                           f"{a['sku']} ({a['ls_id']})",
                           f"Promo marker {'on' if a.get('reason') == 'promo_marker_on' else 'off'}: "
                           f"name {f['expect_name']!r} -> {f['name']!r}; confirmed by re-read.",
                           approved_by, "executed", raw_ref=a["ls_id"])
            print(f"  marker {a['sku']:20} {f['name'][:60]}")

        for a in sorted(deletes, key=lambda a: a["seq"]):
            current.update(type="lightspeed_delete_product", target=f"{a['sku']} ({a['ls_id']})")
            writer.delete_product(a["ls_id"], expect_sku=a["fields"]["expect_sku"])
            if not args.dry_run:
                try:
                    gone = writer.read_product(a["ls_id"])
                except LightspeedError as e:
                    if "404" not in str(e):
                        raise
                    gone = None  # not found at all: removed
                if gone and not gone.get("deleted_at"):
                    raise LightspeedError(
                        f"deleted {a['sku']} but a re-read still shows it live (no deleted_at)")
                log.append(a["id"], "lightspeed_delete_product",
                           f"{a['sku']} ({a['ls_id']})",
                           f"Deleted (archived) and confirmed by re-read. Reason: {a.get('reason')}.",
                           approved_by, "executed", raw_ref=a["ls_id"])
            print(f"  delete {a['sku']:20} {a['ls_id']}")

        families = defaultdict(list)
        for a in creates:
            families[a["fields"].get("name")].append(a)
        for name, group in families.items():
            current.update(type="lightspeed_create_product", target=f"family {name!r}")
            if args.dry_run:
                # The dry run is the Lightspeed pre-flight: it resolves every
                # supplier, brand, category and attribute name against the live
                # account. Report ALL that fail, not just the first, so one run
                # names every SKU to hold.
                try:
                    payload = build_family_payload(
                        sorted(group, key=lambda a: a["seq"]), lookups, cfg)
                except LightspeedError as e:
                    unresolved.append((name, [a["sku"] for a in group], str(e)))
                    print(f"  create {name!r}: UNRESOLVED — {e}")
                    continue
            else:
                payload = build_family_payload(
                    sorted(group, key=lambda a: a["seq"]), lookups, cfg)
            ids = writer.create_family(payload)
            # Say which shape was sent. "1 variant(s)" on a standalone is exactly the
            # output that made the payload bug invisible for a run and a half.
            shape = (f"{len(payload['variants'])} variant(s)" if "variants" in payload
                     else "standalone, no variants array")
            print(f"  create {name!r}: {shape}")
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
            # Saved per family, not at the end: a later family failing must not
            # cost the UUIDs this one already minted.
            save_backfill()
    except (LightspeedError, Exception) as e:  # noqa: BLE001 — stop the batch on anything
        if not args.dry_run:
            log.append(None, current["type"], current["target"],
                       f"Batch stopped: {e}", approved_by, "failed", error=str(e))
        save_backfill()
        print(f"\nSTOPPED: {e}", file=sys.stderr)
        print("Nothing after this point was attempted. Everything already applied is in "
              f"{log_path.name}; re-running skips it.", file=sys.stderr)
        if backfill and not args.dry_run:
            print(f"UUIDs created before the stop are saved in {backfill_path.name} "
                  f"({len(backfill)} so far).", file=sys.stderr)
        return 1

    save_backfill()
    if backfill and not args.dry_run:
        print(f"\n{backfill_path.name} — {len(backfill)} UUIDs for the Airtable backfill")

    print(f"\n{json.dumps(writer.write_stats())}")
    if args.dry_run:
        print("DRY RUN — nothing was sent and nothing was logged.")
        if unresolved:
            print(f"\nPRE-FLIGHT FAILED: {len(unresolved)} famil"
                  f"{'y' if len(unresolved) == 1 else 'ies'} cannot be created as planned. "
                  "Hold these SKUs on BOTH systems (drop their Lightspeed and Airtable ids "
                  "from the approval file, report them as held) before the live run:",
                  file=sys.stderr)
            for name, skus, err in unresolved:
                print(f"  {name!r} [{', '.join(skus)}]: {err}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
