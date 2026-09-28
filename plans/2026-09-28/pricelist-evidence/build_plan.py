"""Build the 2026-09-28 Price List URL / Price List Date backfill plan.

Albert, 2026-09-28: every product links to the NEWEST currently-effective list file that
actually carries it (checked by SKU or supplier SKU), with that list's date beside it.
Evidence per supplier is in evidence/<SUPPLIER>.json (see BRIEF.md). Products already
linked on 2026-09-25 keep their link and gain its date. Anything not placed is reported,
never guessed. Read-only: writes the plan, the approval file and a report.
"""
import csv, hashlib, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
TODAY = "2026-09-28"
RUN_AT = sys.argv[1] if len(sys.argv) > 1 else "2026-09-28T00:00:00-04:00"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "out"
SHAREPOINT = "https://flooruca-my.sharepoint.com/"
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
APPROVED_BY = ("Albert, chat 2026-09-28 ('please add the \"link to price list\" into each product ... "
               "useful for re-verifying the details'; chose: newest list file that actually "
               "carries the product, with its date); Price List URL + Price List Date only")

# The 2026-09-25 backfill: link -> (list, date). Its dates are that plan's newest_list dates.
SEPT25 = {
    "IQAsadcCzKtWR67hLJoJtAuWAepiJawdrtIB-T6BmbyZqSE": ("FAW PL-377", "2026-09-19"),
    "IQAIA8eKDFNvSZOc60-vLdCvASykV64hTSAR9gsZs8YVmUA": ("WEISS PL-376", "2026-09-21"),
    "IQA9-jgaDiE9R7-rYkY73M2qAUZO1UmNLvyjyZSLAgOrXMo": ("HOMESPRO PL-242", "2026-03-02"),
    "IQBK4QrwNcseTa1OiQDxaS9cAcPEaw0R-hF9ALzLuK-akIs": ("VIZION PL-373", "2026-08-01"),
    "IQC7Rh4J0x2BR6u3_Hum6SdsAckDNM6zKCmQdMYJMY0-PQ4": ("JL TILE PL-372", "2026-09-11"),
    "EeW3PtqKncNNtSQDiWcFk9QBhDoxN0u3Ymw0i6H83-jnwA": ("FLOOR & DECOR PL-47", "2025-01-03"),
    "EevP2jP90vRGp_hzeS7TzDQBJtceWNe-KpD_7mnhEj6e3w": ("BALTIC PL-170", "2025-10-09"),
    "IQCypsmkJeleQIdTK2oAn5ZMASnUDZEHOogLofHsJcuJX68": ("IMPRESSIVE PL-381", "2026-09-01"),
}


def norm(code):
    return re.sub(r"\s+", " ", str(code)).strip().upper() if code else None


def action_id(sku):
    return "cat-" + hashlib.sha1(f"pricelist-0928|{sku}|airtable|upsert".encode()).hexdigest()[:12]


def load_lists():
    by_supplier = {}
    for f in sorted((HERE / "evidence").glob("*.json")):
        ev = json.loads(f.read_text())
        lists = []
        for i, l in enumerate(ev.get("lists", [])):
            url, date = l.get("sharepoint_url"), l.get("list_date")
            if not (url and url.startswith(SHAREPOINT) and date and ISO.match(date)):
                print(f"skip {f.name} list {l.get('pl_id')}: bad url/date", file=sys.stderr)
                continue
            if date > TODAY:
                continue  # not yet effective
            lists.append({**l, "_order": i, "_codes": {norm(c) for c in l.get("codes", []) if c}})
        # newest first; ties keep the evidence file's order
        lists.sort(key=lambda l: (l["list_date"], -l["_order"]), reverse=True)
        by_supplier[ev["supplier"]] = {"lists": lists, "note": ev.get("unmatched_note", "")}
    return by_supplier


def carries(l, rec):
    how = l.get("match_by")
    if how == "all_supplier_products":
        return True
    if how == "sku":
        return norm(rec["sku"]) in l["_codes"]
    if how == "supplier_sku":
        return rec["supplier_sku"] is not None and norm(rec["supplier_sku"]) in l["_codes"]
    return False


def main():
    recs = json.loads((HERE / "airtable_active.json").read_text())
    by_supplier = load_lists()
    actions, unplaced, kept = [], [], []
    per_list = Counter()
    for rec in sorted(recs, key=lambda r: (r["supplier"] or "", r["sku"])):
        if rec["url"]:
            token = next((t for t in SEPT25 if t in rec["url"]), None)
            if token:
                name, date = SEPT25[token]
                fields = {"Price List Date": date}
                before = {"Price List Date": None}
                reason, lst = "price_list_date_for_existing_link", name
            else:
                kept.append(rec)  # a link set by a person; not ours to date or move
                continue
        else:
            ev = by_supplier.get(rec["supplier"])
            hit = next((l for l in (ev or {}).get("lists", []) if carries(l, rec)), None)
            if not hit:
                unplaced.append(rec)
                continue
            fields = {"Price List URL": hit["sharepoint_url"], "Price List Date": hit["list_date"]}
            before = {"Price List URL": None, "Price List Date": None}
            reason, lst = "price_list_link", f"{rec['supplier']} {hit.get('pl_id')}"
        per_list[lst] += 1
        actions.append({"id": action_id(rec["sku"]), "target_system": "airtable", "op": "upsert",
                        "sku": rec["sku"], "airtable_rec_id": rec["rec"], "ls_id": None, "handle": None,
                        "fields": fields, "before": before, "reason": reason, "list": lst})
    for i, a in enumerate(actions, 1):
        a["seq"] = i
    assert len({a["id"] for a in actions}) == len(actions), "duplicate action id"

    OUT.mkdir(parents=True, exist_ok=True)
    plan = {
        "contract_version": "catalog-plan-1", "supplier": "MULTI (price list links, all suppliers)",
        "run_at": RUN_AT, "status": "ready",
        "cost_basis": {"value": "n/a", "confirmed_by": "no price field is written"},
        "summary": {"airtable_upsert": len(actions),
                    "by_reason": dict(Counter(a["reason"] for a in actions)),
                    "by_list": dict(sorted(per_list.items())),
                    "unplaced": len(unplaced), "kept_manual_link": len(kept)},
        "blocked": [], "warnings": [],
        "_note": ("Albert 2026-09-28: 'please add the \"link to price list\" into each product and into "
                  "supabase and the web app. This is useful for re-verifying the details in the platform in "
                  "the early stages.' Chose: link each product to the newest currently-effective list FILE "
                  "that actually carries it (upload CSV SKU, Notion-noted full coverage, or its supplier code "
                  "read from the file), and write that list's date to the new Price List Date field. Where "
                  "Price List Date differs from Effective Date the price came from another list: that is the "
                  "re-verification signal, not an error. Products linked 2026-09-25 gain their list's date. "
                  "Lists effective after today (TRIFOREST PL-382) are excluded. Evidence: "
                  "plans/2026-09-28/pricelist-evidence/."),
        "actions": actions,
    }
    approval = {"contract_version": "catalog-approval-1", "supplier": plan["supplier"],
                "plan": "plans/2026-09-28/catalog-plan-pricelist-0928.json", "approved_by": APPROVED_BY,
                "decisions": [{"id": a["id"], "status": "approved", "at": RUN_AT} for a in actions]}
    (OUT / "catalog-plan-pricelist-0928.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n")
    (OUT / "catalog-approval-pricelist-0928.json").write_text(json.dumps(approval, indent=1, ensure_ascii=False) + "\n")
    with open(OUT / "pricelist_unplaced_2026-09-28.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Supplier", "SKU", "Supplier SKU", "Product name", "Effective Date", "Why"])
        for r in unplaced:
            why = ("no list evidence for this supplier" if r["supplier"] not in by_supplier
                   else "not found in any current list file")
            w.writerow([r["supplier"], r["sku"], r["supplier_sku"] or "", r["name"] or "", r["eff"] or "", why])
    tot = Counter(r["supplier"] for r in recs)
    supplier_of = {r["sku"]: r["supplier"] for r in recs}
    got = Counter(r["supplier"] for r in recs if r["url"]) + Counter(
        supplier_of[a["sku"]] for a in actions if a["reason"] == "price_list_link")
    print(f"actions {len(actions)}  unplaced {len(unplaced)}  kept {len(kept)}")
    for s, n in tot.most_common():
        print(f"{n:5} linked {got[s]:5}  {s}")


if __name__ == "__main__":
    main()
