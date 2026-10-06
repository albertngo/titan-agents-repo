#!/usr/bin/env python3
"""Pull supplier order confirmations, invoices and credit memos from email. READ ONLY.

For the payout flow (methods/payouts.md, Decision 17-18): what was ordered is the
truth for flooring, and the supplier invoice net of credit memos is the FINAL cost
on a Flooring Line Item. This script reads those documents where staff already
file them (platform-settings/supplier-docs.json -> info@ PURCHASE ORDERS/PO Confirmed,
INVOICE, CREDIT), extracts the PDF text, and joins them into orders.

    python3 scripts/supplier_docs_pull.py               # window_days from the registry
    python3 scripts/supplier_docs_pull.py --days 60

Output: ingest/YYYY-MM-DD/supplier-docs.json per contracts/supplier-docs-schema.md:
  * `documents` — one per PDF: type, number, date, PO / estimate number, lines;
  * `orders`    — keyed by the supplier's estimate (sales order) number: the latest
                  confirmation, every invoice, attributed credit memos, and per
                  product code the confirmed, invoiced, credited and NET sqft and
                  dollars with the actual rate per sqft and a cost `stage`.

Read only: Graph GETs on messages and attachments with the app-only token
(GRAPH_TENANT_ID / GRAPH_CLIENT_ID / GRAPH_CLIENT_SECRET from .env, the same app
scripts/outlook_pull.py uses). Nothing is moved, flagged, marked read or sent.
PDF text comes from `pdftotext -layout` (poppler-utils). Only Vidar today; another
supplier is a registry entry plus a parser for its document format.
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import outlook_pull as op  # noqa: E402
from ls_sales_pull import REPO_ROOT, TZ  # noqa: E402

CONTRACT = "supplier-docs-1"
REGISTRY = REPO_ROOT / "platform-settings" / "supplier-docs.json"
GRAPH = "https://graph.microsoft.com/v1.0"


# -- parsing (pure) -----------------------------------------------------------

def _money(s):
    if s is None:
        return None
    return float(str(s).replace("$", "").replace(",", ""))


def _find(pattern, text, flags=0):
    m = re.search(pattern, text, flags)
    return m.group(1) if m else None


_LINE_QB = re.compile(  # estimate / invoice:  "1.  CODE   desc   qty   $rate   $amount   HST ON"
    r"^\s*(?:\d+\.\s+)?(\S+)\s{2,}(.*?)\s{2,}(-?\d+(?:\.\d+)?)\s+\$?(-?[\d,]*\.\d+)"
    r"\s+\$?(-?[\d,]+\.\d{2})\s*(HST\s*ON|HST|Exempt|Zero-rated)?\s*$")
_LINE_CM = re.compile(  # credit memo:  "CODE   desc   HST   qty   rate   amount"
    r"^\s*(\S+)\s{2,}(.*?)\s{2,}(HST|Exempt|Zero-rated)\s+(-?\d+(?:\.\d+)?)\s+(-?[\d,]*\.\d+)"
    r"\s+(-?[\d,]+\.\d{2})\s*$")
_STOP = re.compile(r"Subtotal|SUBTOTAL|Note to customer|TAX SUMMARY|Total\b")


def parse_lines(text, credit=False):
    lines, cur = [], None
    for ln in text.splitlines():
        m = (_LINE_CM if credit else _LINE_QB).match(ln)
        if m and not _STOP.match(m.group(1)) and m.group(1) not in ("#", "ACTIVITY"):
            if credit:
                code, desc, _tax, qty, rate, amount = m.groups()
            else:
                code, desc, qty, rate, amount, _tax = m.groups()
            cur = {"code": code, "desc": desc.strip(), "qty": float(qty),
                   "rate": _money(rate), "amount": _money(amount)}
            lines.append(cur)
            continue
        if cur is None:
            continue
        if _STOP.search(ln):
            cur = None
            continue
        chunk = re.split(r"\s{3,}", ln.strip())[0] if ln.strip() else ""
        if re.match(r"^\d+\.(\s|$)", chunk):   # a numbered note, not this line's description
            cur = None
            continue
        if chunk and chunk not in ("ON", "HST", "HST ON"):
            cur["desc"] += " " + chunk
    for l in lines:
        sfb = _find(r"([\d.]+)\s*SF\s*/\s*BOX", l["desc"], re.I)
        l["sf_per_box"] = float(sfb) if sfb else None
        l["restocking_fee"] = bool(re.search(r"restocking", l["desc"], re.I))
        if l["sf_per_box"]:
            l["sqft"] = round(l["qty"] * l["sf_per_box"], 2)
            l["rate_per_sqft"] = round(l["rate"] / l["sf_per_box"], 4)
        else:
            l["sqft"] = l["rate_per_sqft"] = None
    return lines


def parse_quickbooks(text, doc_type, subject=""):
    """One QuickBooks estimate / invoice / credit memo PDF's text -> document dict."""
    d = {"doc_type": doc_type, "po_number": None, "estimate_no": None, "revision": None}
    if doc_type == "credit_memo":
        d["doc_no"] = _find(r"CREDIT #\s*(Cr\d+)", text)
        dm = re.search(r"DATE\s+(\d\d)/(\d\d)/(\d{4})", text)
        d["date"] = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}" if dm else None
        d["subtotal"] = _money(_find(r"SUBTOTAL\s+([\d,]+\.\d\d)", text))
        d["tax"] = _money(_find(r"HST \(ON\) @ 13%\s+([\d,]+\.\d\d)", text))
        d["total"] = _money(_find(r"\bTOTAL\s+([\d,]+\.\d\d)", text))
    else:
        label = "Invoice" if doc_type == "invoice" else "Estimate"
        d["doc_no"] = _find(rf"{label} no\.:\s*(\d+)", text)
        d["date"] = _find(rf"{label} date:\s*([\d-]+)", text)
        if doc_type == "invoice":
            d["estimate_no"] = _find(r"Estimate No\.:\s*(\d+)", text)
        else:
            d["estimate_no"] = d["doc_no"]
            s = subject.upper()
            d["revision"] = ("cancelled" if "CANCEL" in s else "revised" if "REVISED" in s
                             else "update" if "UPDATE" in s else "original")
        d["subtotal"] = _money(_find(r"Subtotal\s+\$?([\d,]+\.\d\d)", text))
        d["total"] = _money(_find(r"(?<![A-Za-z])Total\s+\$?(-?[\d,]+\.\d\d)", text))
        sub = d["subtotal"]
        d["tax"] = round(d["total"] - sub, 2) if d["total"] is not None and sub is not None else None
    d["po_number"] = _find(r"P\.?O\.? (?:Number|No\.?|#):?\s*(?:PO-?)?(\d+)", text, re.I)
    d["lines"] = parse_lines(text, credit=doc_type == "credit_memo")
    return d


# -- orders (pure) ------------------------------------------------------------

def _sum(xs):
    return round(sum(x or 0 for x in xs), 2)


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def build_orders(docs, lookback_days=90):
    """documents -> (orders keyed by estimate number, unattributed credits, notes)."""
    orders = {}

    def order(key):
        return orders.setdefault(key, {"estimate_no": key, "po_number": None, "supplier": None,
                                       "status": "open", "confirmations": [], "invoices": [],
                                       "credits": [], "flags": []})

    for d in sorted(docs, key=lambda x: (x.get("date") or "", x.get("received_at") or "")):
        if d["doc_type"] == "confirmation":
            o = order(d["estimate_no"])
            o["confirmations"].append(d)
        elif d["doc_type"] == "invoice":
            o = order(d["estimate_no"] or f"INV{d['doc_no']}")
            if not any(i["doc_no"] == d["doc_no"] for i in o["invoices"]):
                o["invoices"].append(d)
        else:
            continue
        o["supplier"] = o["supplier"] or d.get("supplier")
        o["po_number"] = o["po_number"] or d.get("po_number")

    unattributed = []
    for d in [x for x in docs if x["doc_type"] == "credit_memo"]:
        cdate = _d(d.get("date"))
        codes = {l["code"] for l in d["lines"]}
        cands = []
        for o in orders.values():
            for inv in o["invoices"]:
                idate = _d(inv.get("date"))
                if (idate and cdate and timedelta(0) <= cdate - idate <= timedelta(days=lookback_days)
                        and codes & {l["code"] for l in inv["lines"]}):
                    cands.append(o["estimate_no"])
                    break
        if len(cands) == 1:
            o = orders[cands[0]]
            if not any(c["doc_no"] == d["doc_no"] for c in o["credits"]):
                o["credits"].append(dict(d, attribution="supplier code + date (only candidate)"))
        else:
            unattributed.append({"doc_no": d["doc_no"], "date": d.get("date"), "total": d.get("total"),
                                 "codes": sorted(codes), "candidates": cands,
                                 "reason": "no invoice for this code before the credit" if not cands
                                 else "more than one order invoiced this code — not picked"})

    # a PO re-confirmed under a new estimate number: the older, never-invoiced one is superseded
    newest_on_po = {}
    for o in orders.values():
        if o["po_number"] and o["confirmations"]:
            d0 = o["confirmations"][0].get("date") or ""
            if d0 >= newest_on_po.get(o["po_number"], ("", None))[0]:
                newest_on_po[o["po_number"]] = (d0, o["estimate_no"])

    for o in orders.values():
        latest = o["confirmations"][-1] if o["confirmations"] else None
        if latest and latest.get("revision") == "cancelled":
            o["status"] = "cancelled"
        newest = newest_on_po.get(o["po_number"], (None, None))[1]
        if newest and newest != o["estimate_no"] and not o["invoices"] and o["status"] != "cancelled":
            o["status"] = "superseded"
            o["flags"].append(f"superseded_by:{newest}")
        o["confirmation"] = ({k: latest[k] for k in ("doc_no", "date", "revision")}
                             | {"versions": len(o["confirmations"])}) if latest else None
        o["products"] = products(latest, o["invoices"], o["credits"], o["status"])
        o["invoiced_total_pretax"] = _sum(i.get("subtotal") for i in o["invoices"])
        o["credited_total_pretax"] = _sum(c.get("subtotal") for c in o["credits"])
        if latest and not o["invoices"] and o["status"] == "open":
            o["flags"].append("confirmed_not_invoiced")
        if any(c.get("attribution") for c in o["credits"]):
            o["flags"].append("credit_attributed_by_product")
        if any(l.get("restocking_fee") for c in o["credits"] for l in c["lines"]):
            o["flags"].append("restocking_fee")
        if not o["po_number"]:
            o["flags"].append("no_po_number")
        conf_rates = {c: p["confirmed_rate_sqft"] for c, p in o["products"].items()}
        for c, p in o["products"].items():
            cr, ir = conf_rates.get(c), p["invoiced_rate_sqft"]
            if cr is not None and ir is not None and abs(cr - ir) > 0.005:
                o["flags"].append(f"rate_changed_after_confirmation:{c}")
        o["invoices"] = [_slim(i) for i in o["invoices"]]
        o["credits"] = [_slim(c) | {"attribution": c.get("attribution")} for c in o["credits"]]
        del o["confirmations"]
    return orders, unattributed


def _slim(d):
    return {k: d.get(k) for k in ("doc_no", "date", "subtotal", "tax", "total")}


def products(conf, invoices, credits, status):
    """Per supplier code: confirmed / invoiced / credited / net, and the cost stage."""
    out = {}

    def p(line):
        return out.setdefault(line["code"], {
            "desc": line["desc"][:160], "sf_per_box": line["sf_per_box"],
            "confirmed_qty": 0.0, "confirmed_sqft": None, "confirmed_rate_sqft": None,
            "invoiced_qty": 0.0, "invoiced_sqft": 0.0, "invoiced_amount": 0.0,
            "credited_qty": 0.0, "credited_sqft": 0.0, "credited_amount": 0.0})

    for l in (conf or {}).get("lines", []):
        r = p(l)
        r["confirmed_qty"] += l["qty"]
        r["confirmed_amount"] = round(r.get("confirmed_amount", 0) + l["amount"], 2)
        if l["sqft"]:
            r["confirmed_sqft"] = round((r["confirmed_sqft"] or 0) + l["sqft"], 2)
            r["confirmed_rate_sqft"] = round(r["confirmed_amount"] / r["confirmed_sqft"], 4)
    for inv in invoices:
        for l in inv["lines"]:
            r = p(l)
            r["invoiced_qty"] += l["qty"]
            r["invoiced_sqft"] = round(r["invoiced_sqft"] + (l["sqft"] or 0), 2)
            r["invoiced_amount"] = round(r["invoiced_amount"] + l["amount"], 2)
    for cm in credits:
        for l in cm["lines"]:
            r = p(l)
            r["credited_qty"] += l["qty"]
            r["credited_sqft"] = round(r["credited_sqft"] + (l["sqft"] or 0), 2)
            r["credited_amount"] = round(r["credited_amount"] + l["amount"], 2)
    for r in out.values():
        r["net_qty"] = round(r["invoiced_qty"] - r["credited_qty"], 4)
        r["net_sqft"] = round(r["invoiced_sqft"] - r["credited_sqft"], 2) if r["sf_per_box"] else None
        r["net_amount"] = round(r["invoiced_amount"] - r["credited_amount"], 2)
        r["invoiced_rate_sqft"] = (round(r["invoiced_amount"] / r["invoiced_sqft"], 4)
                                   if r["invoiced_sqft"] else None)
        r["actual_rate_sqft"] = (round(r["net_amount"] / r["net_sqft"], 4)
                                 if r["net_sqft"] else r["invoiced_rate_sqft"])
        if status in ("cancelled", "superseded"):
            stage = status
        elif r["invoiced_qty"] and r["invoiced_qty"] + 1e-6 >= r["confirmed_qty"]:
            stage = "invoice_final"
        elif r["invoiced_qty"]:
            stage = "invoice_partial"
        else:
            stage = "confirmation"
        r["stage"] = stage
    return out


# -- Graph (GET only) ---------------------------------------------------------

class Graph:
    def __init__(self, token):
        self.token, self.requests = token, 0

    def get(self, path, params=None):
        url = path if path.startswith("http") else GRAPH + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        self.requests += 1
        return op.graph_get(url, self.token)

    def all(self, path, params=None, max_pages=40):
        out, data, pages = [], self.get(path, params), 0
        while True:
            out += data.get("value", [])
            pages += 1
            nxt = data.get("@odata.nextLink")
            if not nxt or pages >= max_pages:
                return out
            data = self.get(nxt)

    def folder_id(self, mailbox, path):
        parent, fid = f"/users/{urllib.parse.quote(mailbox)}/mailFolders", None
        for part in path.split("/"):
            kids = self.all(parent, {"$top": "200", "$select": "id,displayName"})
            hit = [k for k in kids if k["displayName"].strip().lower() == part.strip().lower()]
            if not hit:
                raise LookupError(f"folder '{path}' not found in {mailbox} (missing '{part}')")
            fid = hit[0]["id"]
            parent = f"/users/{urllib.parse.quote(mailbox)}/mailFolders/{fid}/childFolders"
        return fid


def pdf_text(raw):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "doc.pdf"
        p.write_bytes(raw)
        r = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"pdftotext failed: {r.stderr.decode('utf-8', 'replace')[:200]}")
        return r.stdout.decode("utf-8", "replace")


def classify(msg, reg):
    """(supplier_key, doc_type, number) when a message is a known supplier document."""
    sender = ((msg.get("from") or {}).get("emailAddress") or {})
    for key, s in reg["suppliers"].items():
        if (sender.get("address") or "").lower() not in s["sender_addresses"]:
            continue
        if not re.search(s["sender_name_regex"], sender.get("name") or ""):
            continue
        for doc_type, pat in s["subjects"].items():
            m = re.search(pat, msg.get("subject") or "")
            if m:
                return key, doc_type, m.group(1)
    return None


def pull(graph, reg, since_iso):
    mb = reg["mailbox"]
    docs, errors, seen = [], [], set()
    for doc_type, paths in reg["folders"].items():
        for path in paths:
            try:
                fid = graph.folder_id(mb, path)
                msgs = graph.all(f"/users/{urllib.parse.quote(mb)}/mailFolders/{fid}/messages", {
                    "$filter": f"receivedDateTime ge {since_iso}", "$top": "100",
                    "$select": "id,subject,from,receivedDateTime,hasAttachments"})
            except (LookupError, urllib.error.HTTPError, urllib.error.URLError) as e:
                errors.append({"folder": path, "error": f"{type(e).__name__}: {e}"[:300]})
                continue
            for m in msgs:
                hit = classify(m, reg)
                if not hit or not m.get("hasAttachments"):
                    continue
                supplier, dtype, _num = hit
                atts = graph.get(f"/users/{urllib.parse.quote(mb)}/messages/{m['id']}/attachments",
                                 {"$select": "id,name,contentType,size"}).get("value", [])
                for a in atts:
                    if not (a.get("name") or "").lower().endswith(".pdf"):
                        continue
                    try:
                        full = graph.get(f"/users/{urllib.parse.quote(mb)}/messages/{m['id']}"
                                         f"/attachments/{a['id']}")
                        text = pdf_text(base64.b64decode(full["contentBytes"]))
                    except Exception as e:  # one bad PDF never stops the pull
                        errors.append({"folder": path, "subject": m.get("subject"),
                                       "error": f"{type(e).__name__}: {e}"[:300]})
                        continue
                    d = parse_quickbooks(text, dtype, m.get("subject") or "")
                    d.update({"supplier": supplier, "folder": path,
                              "received_at": m.get("receivedDateTime"),
                              "message_id_tail": m["id"][-16:]})
                    key = (d["doc_type"], d["doc_no"], d.get("revision"), d.get("total"))
                    if key in seen:
                        continue
                    seen.add(key)
                    if not d["lines"]:
                        errors.append({"folder": path, "subject": m.get("subject"),
                                       "error": "no line items parsed"})
                    docs.append(d)
    return docs, errors


def build(docs, errors, reg, window):
    orders, unattributed = build_orders(docs, reg["credit_attribution"]["lookback_days"])
    by_po = {}
    for k, o in orders.items():
        if o["po_number"]:
            by_po.setdefault(o["po_number"], []).append(k)
    counts = {"documents": len(docs), "orders": len(orders), "errors": len(errors),
              "unattributed_credits": len(unattributed)}
    for t in ("confirmation", "invoice", "credit_memo"):
        counts[t] = sum(1 for d in docs if d["doc_type"] == t)
    return {"contract": CONTRACT, "source": "supplier-docs",
            "pulled_at": datetime.now(TZ).isoformat(), "window": window, "counts": counts,
            "orders": dict(sorted(orders.items())), "orders_by_po": by_po,
            "unattributed_credits": unattributed, "documents": docs, "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, help="Window in days (default registry window_days)")
    ap.add_argument("--out", type=Path, help="Default ingest/<today>/supplier-docs.json")
    args = ap.parse_args(argv)
    op.load_dotenv(str(REPO_ROOT / ".env"))
    missing = [k for k in ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET")
               if not os.environ.get(k)]
    if missing:
        print(f"error: missing {', '.join(missing)} in .env", file=sys.stderr)
        return 2
    reg = json.loads(REGISTRY.read_text())
    days = args.days or reg["window_days"]
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    graph = Graph(op.get_token(os.environ["GRAPH_TENANT_ID"], os.environ["GRAPH_CLIENT_ID"],
                               os.environ["GRAPH_CLIENT_SECRET"]))
    docs, errors = pull(graph, reg, since)
    out = build(docs, errors, reg, {"since": since[:10], "days": days})
    out["api_stats"] = {"requests": graph.requests}
    path = args.out or REPO_ROOT / "ingest" / datetime.now(TZ).date().isoformat() / "supplier-docs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    c = out["counts"]
    print(f"{c['documents']} documents ({c['confirmation']} confirmations, {c['invoice']} invoices, "
          f"{c['credit_memo']} credits) -> {c['orders']} orders, {c['errors']} errors -> {path}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
