"""Pre-write and post-write steps for the 2026-09-28 price-list backfill, under the
airtable-actions-agent rules: read before write, write only approved ids, never clear or
overwrite a link someone set, one actions-log entry per record.

  python3 execute.py prewrite  <plan> <approval> <fresh_snapshot.json> <batch_dir>
  python3 execute.py postwrite <plan> <approval> <after_snapshot.json> <batch_dir> <actions_log>

A snapshot is the raw list_records_for_table result ({records:[{id, cellValuesByFieldId}]})
for active records with fields Price List URL + Price List Date.
"""
import json, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

URL_F, DATE_F = "fldEmZtBFeNQcVa0I", "fldaNa7RkFvhYKqnZ"
FIELD_ID = {"Price List URL": URL_F, "Price List Date": DATE_F}
SHAREPOINT = "https://flooruca-my.sharepoint.com/"
BATCH = 50


def load(plan_p, appr_p):
    plan = json.loads(Path(plan_p).read_text())
    appr = json.loads(Path(appr_p).read_text())
    ok = {d["id"] for d in appr["decisions"] if d["status"] == "approved"}
    return plan, appr, [a for a in plan["actions"] if a["id"] in ok]


def snapshot(p):
    d = json.loads(Path(p).read_text())
    return {r["id"]: r.get("cellValuesByFieldId", {}) for r in d["records"]}


def still_holds(a, live):
    """The action's `before` must still be true; otherwise the record changed since the plan."""
    if live is None:
        return "record not in the fresh read (archived or deleted?)"
    for name, old in a["before"].items():
        if (live.get(FIELD_ID[name]) or None) != old:
            return f"{name} is no longer blank"
    url = a["fields"].get("Price List URL")
    if url is not None and not url.startswith(SHAREPOINT):
        return "link is not a flooruca-my.sharepoint.com link"
    if url is None and not live.get(URL_F):
        return "date without a link"
    return None


def prewrite(plan_p, appr_p, snap_p, out):
    _, _, actions = load(plan_p, appr_p)
    live = snapshot(snap_p)
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    todo, dropped = [], []
    for a in actions:
        why = still_holds(a, live.get(a["airtable_rec_id"]))
        (dropped if why else todo).append((a, why))
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    for n, b in enumerate(batches, 1):
        recs = [{"id": a["airtable_rec_id"], "fields": {FIELD_ID[k]: v for k, v in a["fields"].items()}} for a, _ in b]
        (out / f"batch_{n:03d}.json").write_text(json.dumps(recs, separators=(",", ":")))
    (out / "dropped.json").write_text(json.dumps([{"id": a["id"], "sku": a["sku"], "why": w} for a, w in dropped], indent=1))
    print(f"approved {len(actions)}  to write {len(todo)} in {len(batches)} batches  dropped {len(dropped)}")


def postwrite(plan_p, appr_p, snap_p, batch_dir, log_p):
    plan, appr, actions = load(plan_p, appr_p)
    live = snapshot(snap_p)
    dropped = {d["id"]: d["why"] for d in json.loads((Path(batch_dir) / "dropped.json").read_text())}
    now = datetime.now(ZoneInfo("America/Toronto")).isoformat(timespec="seconds")
    log_p = Path(log_p)
    log = json.loads(log_p.read_text()) if log_p.exists() else {"contract_version": 1, "entries": []}
    done = {e.get("raw_ref_action_id") for e in log["entries"] if e.get("result") == "executed"}
    tally = {"executed": 0, "refused": 0, "failed": 0, "skipped_duplicate": 0}
    for a in actions:
        if a["id"] in done:
            tally["skipped_duplicate"] += 1
            continue
        rec = live.get(a["airtable_rec_id"], {})
        if a["id"] in dropped:
            result, err = "refused", None
            summary = f"NOT written: {dropped[a['id']]} (read before write)."
        elif all((rec.get(FIELD_ID[k]) or None) == v for k, v in a["fields"].items()):
            result, err = "executed", None
            summary = (f"Price List URL (empty) -> {a['list']} link; Price List Date -> {a['fields']['Price List Date']}"
                       if "Price List URL" in a["fields"] else
                       f"Price List Date (empty) -> {a['fields']['Price List Date']} ({a['list']}, link unchanged)")
        elif all((rec.get(FIELD_ID[k]) or None) is None for k in a["fields"]):
            # untouched: its batch has not been sent yet; nothing to log until it is
            tally["pending"] = tally.get("pending", 0) + 1
            continue
        else:
            result, err = "failed", "read-back does not show the written value"
            summary = f"Write not confirmed by read-back for {a['list']}."
        tally[result] += 1
        log["entries"].append({
            "logged_at": now, "agent": "airtable-actions-agent", "type": "airtable_upsert_product",
            "target": f"Master Flooring Catalogue {a['sku']} (record {a['airtable_rec_id']})",
            "content_summary": summary, "approved_by": appr["approved_by"], "result": result, "error": err,
            "raw_ref": a["airtable_rec_id"], "raw_ref_action_id": a["id"]})
    log_p.parent.mkdir(parents=True, exist_ok=True)
    log_p.write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")
    print(tally)


if __name__ == "__main__":
    {"prewrite": prewrite, "postwrite": postwrite}[sys.argv[1]](*sys.argv[2:])
