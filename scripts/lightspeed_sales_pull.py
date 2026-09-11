#!/usr/bin/env python3
"""Pull Lightspeed (X-Series) sales for the finance reconciliation. READ ONLY.

GET only. This script imports scripts/lightspeed_client.py, which exposes GET and
pagination and nothing else, so the read-only guarantee is structural rather than
permission-based — an LS personal token carries admin-level data access and has no
read-only variant. tests/test_lightspeed.py fails if a write verb ever appears here.

This is the Lightspeed half of methods/finance-reconciliation.md. The QuickBooks
half only ever sees a register-closeout aggregate, so per-sale detail and tender
state exist nowhere else.

What makes the reconciliation mechanical is the sale `status` field. Verified
2026-09-11 against the live account (55,820 sales, 56 requests, no throttling):

    CLOSED 51,976 · VOIDED 1,438 · SAVED 1,020 · ONACCOUNT_CLOSED 843
    LAYBY_CLOSED 506 · ONACCOUNT 31 · LAYBY 3 · PICKED_UP_CLOSED 2 · QUOTE 1

So layaway and on-account are a filter on a field, not an inference. The open
positions (ONACCOUNT, LAYBY) are the ones that exist nowhere in QuickBooks.

Pagination is the same `version` cursor the product pull uses, oldest first. There
is no server-side date filter on the sales endpoint, so a period pull walks and
filters locally; the cursor is cached so a daily run does not re-walk history.

Usage:
    # Run this first against a live account. Describes the envelope and one sale,
    # writes nothing, caches nothing.
    python3 scripts/lightspeed_sales_pull.py --probe

    # Incremental: resume from the cached cursor -> ingest/<today>/lightspeed-sales.json
    python3 scripts/lightspeed_sales_pull.py

    # Full history walk (ignores the cursor), refreshing the cache
    python3 scripts/lightspeed_sales_pull.py --full-walk

    # One accounting period, from cache where possible
    python3 scripts/lightspeed_sales_pull.py --period 2026-08

    # Reconciliation summary only: closeout totals by day/register, open positions
    python3 scripts/lightspeed_sales_pull.py --period 2026-08 --stats

Environment: LIGHTSPEED_DOMAIN_PREFIX, LIGHTSPEED_PERSONAL_TOKEN — see .env.example.
Config: platform-settings/lightspeed.json (`sales` block carries the verified
status vocabulary; `api.endpoints.sales` the path).
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lightspeed_client import LightspeedClient, LightspeedError, load_config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "analysis" / "cache"
TZ = ZoneInfo("America/Toronto")

# The project reference Albert records in the sale note, e.g. "@Pack Allen PP-416".
# Resolves to Notion Titan Projects' auto-increment ID and the Airtable Project Log
# `Project ID`. Kept in sync with project_sale_identification.join_key.pattern in
# platform-settings/finance.json — if you change one, change both.
PP_PATTERN = re.compile(r"\bPP[-\s]?(\d{2,5})\b", re.IGNORECASE)

# Statuses that are neither revenue nor a receivable and must be excluded from
# both sides of every figure. VOIDED is cancelled; SAVED is a parked, untendered
# sale; QUOTE is not a sale at all.
EXCLUDED_STATUSES = frozenset({"VOIDED", "SAVED", "QUOTE"})

# Open positions — the ones QuickBooks cannot see. See Gaps A and B in the method.
OPEN_LAYAWAY = "LAYBY"
OPEN_ON_ACCOUNT = "ONACCOUNT"


def today():
    return datetime.now(TZ).date().isoformat()


def sale_day(record):
    """The calendar day a sale belongs to, America/Toronto.

    Lightspeed returns `sale_date` in UTC (verified live: '2018-07-30T17:47:44+00:00').
    Slicing the first ten characters would therefore file a sale rung at 20:00
    Toronto under the NEXT day, because that is 00:00 UTC. A register closeout is a
    day-grain event and the whole reconciliation identity is asserted per day, so an
    off-by-one here silently moves money between closeouts. Convert, then take the
    date.
    """
    raw = record.get("sale_date")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:10] or None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ).date().isoformat()


def project_ref(record):
    """The PP-### project reference on a sale, or None.

    Returned WITHOUT the PP- prefix normalisation applied to the digits, so
    'PP416', 'PP-416' and 'PP 416' all yield '416' and join to the same project.
    """
    m = PP_PATTERN.search(record.get("note") or "")
    return m.group(1) if m else None


def paid_cents(record):
    """Cash actually taken on this sale, in integer cents.

    This is what separates a layaway DEPOSIT from a layaway SALE: an open LAYBY
    carries payments without having recognised revenue. Summing `payments[]` is
    the only way to see the deposit — the sale total is the eventual price, not
    the money received.
    """
    total = 0
    for p in record.get("payments") or []:
        total += to_cents(p.get("amount"))
    return total


def to_cents(value):
    """Money to integer cents. No float arithmetic survives this function.

    Lightspeed returns money as JSON numbers, so the float exists on the way in;
    it is rounded once, here, and everything downstream is integer cents per
    CLAUDE.md conventions.
    """
    if value is None:
        return 0
    return int(round(float(value) * 100))


SLIM_FIELDS = ("id", "invoice_number", "receipt_number", "sale_date", "created_at",
               "updated_at", "status", "state", "customer_id", "user_id",
               "register_id", "outlet_id", "note", "source", "version",
               "accounts_transaction_id", "has_unsynced_on_account_payments",
               "return_for")

LINE_FIELDS = ("product_id", "quantity", "price", "cost", "price_total",
               "total_tax", "discount", "status")


def slim(record):
    """One sale, reduced to what the reconciliation reads.

    Money is converted to integer cents here so no consumer has to remember to.
    Line items are kept but projected — the full nested form carries per-line tax
    components and promotion detail that nothing downstream reads, and the whole
    sales history is large enough that it matters.
    """
    out = {k: record.get(k) for k in SLIM_FIELDS}
    out["total_price_cents"] = to_cents(record.get("total_price"))
    out["total_price_incl_cents"] = to_cents(record.get("total_price_incl"))
    out["total_tax_cents"] = to_cents(record.get("total_tax"))
    out["paid_cents"] = paid_cents(record)
    out["sale_day"] = sale_day(record)
    out["project_ref"] = project_ref(record)
    out["payments"] = [
        {"id": p.get("id"), "payment_type_id": p.get("retailer_payment_type_id"),
         "amount_cents": to_cents(p.get("amount")), "payment_date": p.get("payment_date")}
        for p in (record.get("payments") or [])
    ]
    lines = []
    for ln in record.get("line_items") or []:
        item = {k: ln.get(k) for k in LINE_FIELDS if k not in ("price", "cost",
                                                               "price_total", "total_tax",
                                                               "discount")}
        item["price_cents"] = to_cents(ln.get("price"))
        item["cost_cents"] = to_cents(ln.get("cost"))
        item["price_total_cents"] = to_cents(ln.get("price_total"))
        item["total_tax_cents"] = to_cents(ln.get("total_tax"))
        item["discount_cents"] = to_cents(ln.get("discount"))
        lines.append(item)
    out["line_items"] = lines
    return out


def cache_path():
    return CACHE_DIR / "lightspeed-sales.json"


def load_cache():
    p = cache_path()
    if not p.exists():
        return {"cursor": None, "walked_at": None, "sales": []}
    return json.loads(p.read_text())


def save_cache(sales, cursor):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path().write_text(json.dumps(
        {"cursor": cursor, "walked_at": datetime.now(TZ).isoformat(), "sales": sales}))


def walk(client, path, start_after=None, max_pages=None, page_size=None):
    """Walk the sales collection, returning (slim records, last version seen).

    The cursor is the max `version` observed, which is what the next run passes as
    `after`. It is tracked here rather than read back off the last record because
    the records are slimmed and a projection that dropped `version` would silently
    break resumption.
    """
    records, cursor = [], start_after
    for raw in client.paginate(path, page_size=page_size, start_after=start_after,
                               max_pages=max_pages):
        v = raw.get("version")
        if isinstance(v, int) and (cursor is None or v > cursor):
            cursor = v
        records.append(slim(raw))
    return records, cursor


def probe(client, path, page_size):
    """Fetch one page, describe what came back, exit. Writes and caches nothing."""
    body = client.get(path, {client.page_size_param: min(page_size, 5)})
    print(f"=== envelope keys ===\n  {sorted(body.keys())}")
    data = body.get("data") or []
    print(f"\n=== returned {len(data)} sales ===")
    if not data:
        print("No records — cannot describe a sale.")
        return 1
    first = data[0]
    print(f"\n=== first sale: {len(first)} fields ===")
    for k in sorted(first):
        v = first[k]
        if isinstance(v, list):
            desc = f"list[{len(v)}]"
        elif isinstance(v, dict):
            desc = f"dict({', '.join(sorted(v)[:4])}...)"
        else:
            desc = repr(v)[:60]
        print(f"  {k:38} {desc}")
    print("\n=== status values on this page ===")
    for s, n in Counter(r.get("status") for r in data).most_common():
        print(f"  {s!r:22} {n}")
    print("\nCompare against the `sales.statuses` block in "
          "platform-settings/lightspeed.json. A status not recorded there is a "
          "finding: it means the reconciliation has a case it does not handle.")
    return 0


def in_period(record, period):
    day = record.get("sale_day")
    return bool(day) and day.startswith(period)


def within_days(record, days):
    """Sales on or after (today - days + 1), America/Toronto.

    The default output window. ingest/ is tracked by git and the full slim history
    is ~108 MB, so writing everything there by default would put a nine-figure
    byte count into a commit the first time anyone ran this without arguments.
    """
    day = record.get("sale_day")
    if not day:
        return False
    cutoff = (datetime.now(TZ).date() - timedelta(days=days - 1)).isoformat()
    return day >= cutoff


def reconciliation_stats(all_sales, scoped_sales):
    """The numbers methods/finance-reconciliation.md's identity is asserted from.

    Two inputs, deliberately. `scoped_sales` is the output window; closeout totals
    are grouped by (day, register) from it, because that is the grain QuickBooks
    receives — a register closeout, not a sale — and a closeout is an event that
    belongs to a day.

    `all_sales` is everything, and open layaway and on-account positions come from
    it regardless of window. They are BALANCES, and a balance has no period: a
    layaway opened in 2025 and still open today is money held today. Scoping them
    was this script's own first bug — it reported 1 open layaway for August when 3
    were open, and 7 on-account when 32 were. That is exactly the grain confusion
    the method doc warns about, and why the period contract keeps balances in their
    own block.
    """
    in_scope = scoped_sales
    closeouts = defaultdict(lambda: {"sales": 0, "total_incl_cents": 0, "paid_cents": 0})
    open_layaway = {"count": 0, "deposits_cents": 0, "eventual_value_cents": 0}
    open_on_account = {"count": 0, "charged_cents": 0, "paid_cents": 0}
    excluded = Counter()
    by_status = Counter()
    project_sales = {"count": 0, "total_incl_cents": 0, "refs": set()}
    unsynced_flagged = 0
    with_accounts_txn = 0

    # Period-scoped: events that belong to a day.
    for s in in_scope:
        status = s.get("status")
        by_status[status] += 1
        if s.get("has_unsynced_on_account_payments"):
            unsynced_flagged += 1
        if s.get("accounts_transaction_id"):
            with_accounts_txn += 1
        if s.get("project_ref"):
            project_sales["count"] += 1
            project_sales["total_incl_cents"] += s["total_price_incl_cents"]
            project_sales["refs"].add(s["project_ref"])
        if status in EXCLUDED_STATUSES:
            excluded[status] += 1
            continue
        if status in (OPEN_LAYAWAY, OPEN_ON_ACCOUNT):
            continue  # a balance, counted below over all dates
        key = (s.get("sale_day"), s.get("register_id"))
        c = closeouts[key]
        c["sales"] += 1
        c["total_incl_cents"] += s["total_price_incl_cents"]
        c["paid_cents"] += s["paid_cents"]

    # As-of balances: every open position, whatever window it was opened in.
    for s in all_sales:
        status = s.get("status")
        if status == OPEN_LAYAWAY:
            open_layaway["count"] += 1
            open_layaway["deposits_cents"] += s["paid_cents"]
            open_layaway["eventual_value_cents"] += s["total_price_incl_cents"]
        elif status == OPEN_ON_ACCOUNT:
            open_on_account["count"] += 1
            open_on_account["charged_cents"] += s["total_price_incl_cents"]
            open_on_account["paid_cents"] += s["paid_cents"]

    project_sales["refs"] = sorted(project_sales["refs"])
    return {
        "closeouts": [
            {"date": d, "register_id": r, **v}
            for (d, r), v in sorted(closeouts.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or ""))
        ],
        "open_layaway": open_layaway,
        "open_on_account": open_on_account,
        "_balances_are_as_of_not_period": ("open_layaway and open_on_account count "
            "EVERY open position regardless of `period`. They are balances, not "
            "period events. The closeouts array is period-scoped."),
        "excluded": dict(excluded),
        "by_status": dict(by_status),
        "project_sales": project_sales,
        "sync_signals": {
            "has_unsynced_on_account_payments_true": unsynced_flagged,
            "accounts_transaction_id_present": with_accounts_txn,
            "_note": ("Both were ZERO across all 55,820 sales on 2026-09-11. If the "
                      "Lightspeed-to-QuickBooks accounts integration were running and "
                      "stamping the sale record, something would be non-zero. Read "
                      "alongside the QBO P&L. Not proof on its own."),
        },
    }


def print_stats(stats, label):
    print(f"=== reconciliation stats — {label} ===\n")
    print(f"{'date':12} {'register':38} {'sales':>6} {'total incl':>14} {'tendered':>14}")
    for c in stats["closeouts"]:
        print(f"{c['date'] or '?':12} {(c['register_id'] or '?'):38} {c['sales']:>6} "
              f"{c['total_incl_cents']/100:>14,.2f} {c['paid_cents']/100:>14,.2f}")
    ol, oa = stats["open_layaway"], stats["open_on_account"]
    print(f"\n-- balances below are AS-OF, across all dates, not scoped to {label} --")
    print(f"OPEN LAYAWAY      {ol['count']:>4} sales | deposits held "
          f"${ol['deposits_cents']/100:,.2f} | eventual value ${ol['eventual_value_cents']/100:,.2f}")
    print(f"   -> a deposit is a LIABILITY until redemption, and none of it is in QuickBooks.")
    print(f"OPEN ON-ACCOUNT   {oa['count']:>4} sales | charged "
          f"${oa['charged_cents']/100:,.2f} | paid ${oa['paid_cents']/100:,.2f} | "
          f"outstanding ${(oa['charged_cents']-oa['paid_cents'])/100:,.2f}")
    ps = stats["project_sales"]
    print(f"\nPROJECT-TAGGED    {ps['count']:>4} sales | ${ps['total_incl_cents']/100:,.2f} | "
          f"{len(ps['refs'])} distinct PP refs")
    if stats["excluded"]:
        print(f"\nexcluded: " + ", ".join(f"{k}={v}" for k, v in sorted(stats["excluded"].items())))
    sig = stats["sync_signals"]
    print(f"\nsync signals: unsynced_flag={sig['has_unsynced_on_account_payments_true']} "
          f"accounts_txn_present={sig['accounts_transaction_id_present']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", action="store_true",
                    help="Fetch one page, describe the envelope and a sale, exit. "
                         "Writes and caches nothing. Run this first.")
    ap.add_argument("--full-walk", action="store_true",
                    help="Walk the whole history, ignoring the cached cursor.")
    ap.add_argument("--period", help="Scope output to one YYYY-MM accounting period.")
    ap.add_argument("--days", type=int, default=1,
                    help="Scope output to the last N days (default 1, the daily "
                         "ingest window). Ignored when --period or --all is given.")
    ap.add_argument("--all", dest="dump_all", action="store_true",
                    help="Write the ENTIRE history. ~108 MB — ingest/ is tracked by "
                         "git, so this is opt-in for a reason.")
    ap.add_argument("--stats", action="store_true",
                    help="Print the reconciliation summary instead of writing a file.")
    ap.add_argument("--out", type=Path,
                    help="Output path. Default ingest/<today>/lightspeed-sales.json")
    ap.add_argument("--no-cache", action="store_true",
                    help="Do not read or write the cursor cache.")
    ap.add_argument("--max-pages", type=int, help="Stop after N pages (testing).")
    ap.add_argument("--page-size", type=int, help="Override api.pagination.page_size.")
    ap.add_argument("--verbose", action="store_true", help="Log each page to stderr.")
    args = ap.parse_args()

    cfg = load_config()
    try:
        client = LightspeedClient(config=cfg, verbose=args.verbose)
    except LightspeedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    path = cfg["api"]["endpoints"]["sales"]
    page_size = args.page_size or cfg["api"]["pagination"]["page_size"]

    try:
        if args.probe:
            return probe(client, path, page_size)

        cache = {"cursor": None, "sales": []} if args.no_cache else load_cache()
        start_after = None if args.full_walk else cache.get("cursor")
        fresh, cursor = walk(client, path, start_after=start_after,
                             max_pages=args.max_pages, page_size=page_size)
    except LightspeedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.full_walk or not cache.get("sales"):
        sales = fresh
    else:
        # An updated sale comes back again under a higher version — a layaway
        # closing is exactly that. Later wins, keyed on sale id.
        merged = {s["id"]: s for s in cache["sales"]}
        merged.update({s["id"]: s for s in fresh})
        sales = list(merged.values())

    print(f"walked {len(fresh)} sales in {client.request_count} requests "
          f"({'full history' if start_after is None else f'since version {start_after}'}); "
          f"{len(sales)} total after merge", file=sys.stderr)

    if not args.no_cache:
        save_cache(sales, cursor)

    if args.dump_all:
        selected, label = sales, "all history"
    elif args.period:
        selected, label = [s for s in sales if in_period(s, args.period)], args.period
    else:
        selected = [s for s in sales if within_days(s, args.days)]
        label = f"last {args.days}d"
    # Closeouts scope to the output window; balances never do.
    stats = reconciliation_stats(sales, selected)

    if args.stats:
        print_stats(stats, label)
        return 0

    out = args.out or (REPO_ROOT / "ingest" / today() / "lightspeed-sales.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "source": "lightspeed-sales",
        "pulled_at": datetime.now(TZ).isoformat(),
        "window": label,
        "period": args.period,
        "cursor": cursor,
        "count": len(selected),
        "stats": stats,
    }
    out.write_text(json.dumps({**envelope, "sales": selected}, indent=2))

    # The body is gitignored — it carries per-line cost, customer ids and notes
    # containing real customer names, and this repo is public. The summary is the
    # committed record of the pull: totals, balances and distributions, no per-sale
    # rows. Same split the product pull already uses, for the same reason plus that.
    summary = out.with_name(out.stem + "-summary.json")
    summary.write_text(json.dumps(envelope, indent=2))

    print(f"wrote {len(selected)} sales ({label}) -> {out}")
    print(f"       summary (committed) -> {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
