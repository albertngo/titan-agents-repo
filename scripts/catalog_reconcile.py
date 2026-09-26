#!/usr/bin/env python3
"""Reconcile a processed price list against Airtable and Lightspeed. READ ONLY.

Produces the single reviewable diff the pipeline's approval gate acts on, per
contracts/catalog-plan-schema.md:

    plans/YYYY-MM-DD/catalog-plan-<supplier-slug>.json

This writes no platform and holds no credentials. It reads three files and emits
one. Executing the plan is a separate, approved step.

## What it does and does not do

It does NOT re-implement extraction or the Airtable fuzzy match — /process-price-list
already does that, over 8+ suppliers, and its `MatchStatus` column is taken as
given. What it adds is the check that column cannot make: verifying every identity
claim in the upload against the LIVE Lightspeed catalogue, and turning the result
into an executable plan.

That check is the point. On 2026-09-03 a Grandeur backfill matched on colour alone
and Lightspeed rejected 9 products with "handle already exists for your retailer,
sku already exists for your retailer". Every one of those rows carried a UUID
belonging to a different SKU, and four also shared a UUID with a second row in the
same file. Neither is visible from the upload file alone; both are obvious once the
live catalogue is joined on `sku`.

A blank `Lightspeed ID` on a row whose SKU already exists in Lightspeed is the same
bug facing the other way — it makes Lightspeed create a duplicate instead of
updating. That one is repairable rather than fatal: the SKU join recovers the real
UUID, and the plan records it as `uuid_recovered`.

Usage:
    python3 scripts/catalog_reconcile.py \
        --upload ingest/2026-09-09/lee_airtable_upload_2026-09-09.csv

    # explicit inputs, and a live-Airtable snapshot for before/after
    python3 scripts/catalog_reconcile.py \
        --upload ingest/2026-09-03/grandeur_airtable_upload_2026-09-03.csv \
        --lightspeed ingest/2026-09-10/lightspeed-products.json \
        --airtable-existing ingest/2026-09-03/grandeur_airtable_existing.json

Config: platform-settings/lightspeed.json, platform-settings/airtable-destinations.json.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/Toronto")
CONTRACT_VERSION = "catalog-plan-1"

SKU = "SKU"
LS_ID = "Lightspeed ID"
HANDLE = "LS Handle / Parent ID"
MATCH_STATUS = "MatchStatus"
LS_MATCH_STATUS = "LS Match status"
MATCHED_REC = "MatchedRecId"
SUPPLIER = "Supplier"

# Fields worth diffing against the live Airtable record. Keys are upload-CSV
# column names; values are the aliases a live-record snapshot may use instead.
#
# EVERY KEY HERE MUST BE PRESENT IN THE SNAPSHOT. live_value() returns
# readable=False for a key the snapshot lacks, and the caller then writes the
# field anyway and records it as unreadable -- correct when a record is genuinely
# new, and a blanket write on every matched row when the snapshot is simply
# missing the column. So widening this dict without widening the snapshot turns a
# diff into an overwrite. /catalog-sync step 2 names the required field list and
# tests/test_catalog_reconcile.py holds the two to each other.
DIFF_FIELDS = {
    "Product name": ("ProductName", "Product name"),
    "Supplier SKU": ("SupplierSKU", "Supplier SKU"),
    "Category": ("Category",),
    "Cost/unit": ("Cost", "Cost/unit"),
    "Retail price/unit": ("Retail", "Retail price/unit"),
    # Added 2026-09-22 (Albert asked "can we diff it?"). Before this, a supplier
    # marking a colourway clearance, or putting one on promo, produced NO Airtable
    # action at all: the reconciler only looked at the five fields above, so the
    # change was invisible. On FAW PL-377 that meant ~56 CLEARANCE SALE colourways
    # went unwritten, and a laminate promo reached Lightspeed with nothing in
    # Airtable to ever clear it -- the POS would have held the promo price forever.
    "Stock status": ("StockStatus", "Stock status"),
    "Promo cost ($/sf)": ("PromoCost", "Promo cost ($/sf)"),
    "Promo end date": ("PromoEndDate", "Promo end date"),
    LS_ID: ("LightspeedID", "Lightspeed ID"),
}
PRICE_FIELDS = ("Cost/unit", "Retail price/unit")
# Not in DIFF_FIELDS: written by the rule below them in reconcile() (Albert,
# 2026-09-25). `Effective Date` is the EFFECTIVE DATE of the newest list that
# carries the product, taken from the upload row (extraction fills it: the date
# printed on the list, else the email subject's, else the email's received date).
# `Price last changed by` says WHO last changed the price: "Agent" for any write
# this pipeline makes, "Manual" for a person editing in Airtable. Before this, an
# UPDATE moved the price and left both fields at their old values, so a Weiss
# record re-priced from the Sept 21 list still read 2026-08-01 and the
# Stale-pricing view (older than 90 days) would have flagged it.
PRICE_DATE = "Effective Date"
# The same field's name until Albert renamed it in Airtable on 2026-09-25 (same id,
# fld67650y8QClqoMc). Upload CSVs and snapshots written before then carry this
# header, so it is still read — and renamed on the way out, since Airtable rejects a
# write to a field name it no longer has.
LEGACY_PRICE_DATE = "Last price update"
CHANGED_BY = "Price last changed by"
AGENT = "Agent"
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# The list itself, one click from the record (Albert, 2026-09-25): the SharePoint
# share link off the Notion row's `Files & media`, carried as an extra upload-CSV
# column. It travels with `Effective Date` — the record points at the same list
# its date names — and is never written on its own except to fill a blank.
PRICE_URL = "Price List URL"
PROMO_COST = "Promo cost ($/sf)"
PROMO_END = "Promo end date"
# The list that set the PROMO, one click from the record (Albert, 2026-09-26). A SKU
# can be priced by a regular list and put on promo by a separate sheet in the same
# month, so one link cannot name both: `Price List URL` stays the regular list and
# this names the promo's source (a promo sheet, or a regular list that printed the
# promo). It travels with the two promo fields and, like them, is never cleared — an
# ended promo keeps its link, which is what lets a person ask the rep about it later.
PROMO_URL = "Promo List URL"

# MatchStatus / LS Match status values that must never reach a write.
AMBIGUOUS = {"ambiguous", "AMBIGUOUS", "DUPLICATE"}

BOX_SIZE = "Box size (sf)"


def today():
    return datetime.now(TZ).date().isoformat()


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", (name or "unknown").lower()).strip("_")


def clean(value):
    """Upload-CSV cell -> a value, or None.

    Blank means genuinely empty. Never 0, never "", never a sentinel — the
    ls-id-backfill skill is explicit about this and the writers depend on it.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_number(value):
    try:
        return round(float(str(value).strip()), 4)
    except (TypeError, ValueError):
        return None


def comparable(field, value):
    """Normalise for change detection: prices numerically, everything else as text."""
    if value is None:
        return None
    if field in PRICE_FIELDS or field.endswith(("($/sf)", "(in)", "(mm)")):
        num = as_number(value)
        if num is not None:
            return num
    return str(value).strip()


def action_id(supplier, sku, target_system, op):
    """Stable across re-runs — that is what makes actions-log idempotency work."""
    raw = f"{supplier}|{sku}|{target_system}|{op}".encode()
    return "cat-" + hashlib.sha1(raw).hexdigest()[:12]


def load_lightspeed(path):
    """Index the LS pull by sku and by id.

    Both are unique across the live catalogue (verified 2026-09-10: 14,525
    products, 0 blank skus, 0 duplicates), which is what makes sku a safe join
    key. If that ever stops being true, say so loudly rather than silently
    picking a winner.
    """
    payload = json.loads(Path(path).read_text())
    products = payload.get("products", payload)
    by_sku, by_id, by_handle = {}, {}, defaultdict(list)
    collisions = []
    for product in products:
        sku, pid = clean(product.get("sku")), clean(product.get("id"))
        if sku:
            if sku in by_sku:
                collisions.append(sku)
            by_sku[sku] = product
        if pid:
            by_id[pid] = product
        handle = clean(product.get("handle"))
        if handle:
            by_handle[handle].append(product)
    return {"by_sku": by_sku, "by_id": by_id, "by_handle": by_handle,
            "sku_collisions": collisions, "count": len(products),
            "pulled_at": payload.get("pulled_at")}


def load_airtable_existing(path):
    if not path:
        return {}
    records = json.loads(Path(path).read_text())
    if isinstance(records, dict):
        records = list(records.values())
    return {clean(r.get(SKU)): r for r in records if clean(r.get(SKU))}


FIELD_ALIASES = {PRICE_DATE: (PRICE_DATE, LEGACY_PRICE_DATE)}


def live_value(record, field):
    """(value, readable). `readable` False means the snapshot carries no such key.

    The distinction matters: a reviewer approving a diff must be able to tell
    "this field was empty" from "we could not read this field", and null renders
    both the same.
    """
    for alias in DIFF_FIELDS.get(field, FIELD_ALIASES.get(field, (field,))):
        if alias in record:
            return record[alias], True
    return None, False


def reconcile(upload_rows, ls, existing, supplier, categories, ls_upload=None,
              airtable_snapshot=True, select_options=None, as_of=None):
    """Every row -> an action or a block. Never both, never neither.

    Warnings are separate: things worth a reader's attention that are not a
    reason to withhold a write.

    `as_of` (YYYY-MM-DD, default today in Toronto) is the effective-date gate
    (Albert, 2026-09-25): a row whose list takes effect after it is blocked
    `not_yet_effective` on both systems, so a list received early is staged and
    applied by /price-list-sweep on the day, never written ahead of it.

    `select_options` ({field: set of live option names}) is the pre-flight. A row
    whose Airtable write would name a select value Airtable does not have is
    blocked on BOTH systems, before either is written. Without it, a first-time
    supplier wrote Lightspeed and then had every Airtable write refused:
    HOMESPRO and IMPRESSIVE on 2026-09-14, IMPRESSIVE again on 2026-09-22, which
    left 99 products in the POS with no catalogue record.
    """
    actions, blocked, warnings = [], [], []
    ls_upload = ls_upload or {}

    def block(sku, reason, detail, rows=None):
        blocked.append({"sku": sku, "reason": reason, "detail": detail,
                        **({"rows": rows} if rows else {})})

    def warn(sku, reason, detail):
        warnings.append({"sku": sku, "reason": reason, "detail": detail})

    # Pass 1 — UUIDs reused within this one file. Four of the nine Grandeur
    # rejections were this, and it is detectable without touching Lightspeed.
    uuid_rows = defaultdict(list)
    for row in upload_rows:
        uuid = clean(row.get(LS_ID))
        if uuid:
            uuid_rows[uuid].append(clean(row.get(SKU)))
    collided = {u: skus for u, skus in uuid_rows.items() if len(skus) > 1}

    # Pass 1b — box sizes per handle group. Whether a group is uniform or mixed is
    # a property of the data, not of the brand, and it decides where sf/b has to
    # appear. A row cannot answer this about itself.
    group_boxes = box_sizes_by_handle(upload_rows)

    as_of = as_of or today()

    # Pass 2 — per row.
    for row in upload_rows:
        sku = clean(row.get(SKU))
        effective = clean(row.get(PRICE_DATE)) or clean(row.get(LEGACY_PRICE_DATE))
        if effective and ISO_DATE.match(effective) and effective > as_of:
            block(sku, "not_yet_effective",
                  f"the list takes effect {effective}; nothing is written to either "
                  f"system before then (as of {as_of}). /price-list-sweep applies it "
                  "on the day, against a fresh pull of both systems")
            continue
        if not sku:
            name = clean(row.get("Product name")) or "<unnamed>"
            if clean(row.get(MATCH_STATUS)) == "new":
                detail = (f"{name} is a new product still awaiting a minted SKU. Under "
                          "RULE 0 the SKU is minted by Titan at record creation and is "
                          "never generated by an automated process, so this row cannot "
                          "be joined or written until it has one.")
            else:
                detail = f"{name} carries no SKU, and nothing can be joined on"
            block(None, "sku_missing", detail)
            continue

        uuid = clean(row.get(LS_ID))
        handle = clean(row.get(HANDLE))
        match_status = clean(row.get(MATCH_STATUS))
        ls_match_status = clean(row.get(LS_MATCH_STATUS))
        rec_id = clean(row.get(MATCHED_REC))

        if match_status in AMBIGUOUS or ls_match_status in AMBIGUOUS:
            block(sku, "ambiguous_match",
                  f"MatchStatus={match_status!r} LS Match status={ls_match_status!r}; "
                  "resolve by hand, never guess")
            continue

        if uuid and uuid in collided:
            owner = ls["by_id"].get(uuid)
            owner_sku = clean(owner.get("sku")) if owner else None
            detail = (f"Lightspeed ID {uuid} is claimed by {len(collided[uuid])} rows in this "
                      f"file: {', '.join(sorted(s or '?' for s in collided[uuid]))}")
            if owner_sku:
                detail += (f". Lightspeed holds it against {owner_sku}"
                           + (" — this row" if owner_sku == sku
                              else f", so {sku} is not its owner"))
            block(sku, "uuid_collision", detail, rows=collided[uuid])
            continue

        # A row's Lightspeed identity is normally its Airtable SKU: that's what a
        # CREATE writes into Lightspeed's own `sku` field (ls_create_fields), so
        # for anything this pipeline minted, LS sku == Airtable SKU. IMPRESSIVE
        # (2026-09-14) exposed the case that invariant does not cover: RULE 0a's
        # "third state" (new to Airtable, already live in Lightspeed) where the
        # live product predates this pipeline and Lightspeed's own sku field is
        # still the supplier's raw code — the exact value /process-price-list
        # matched against and recorded in `Supplier SKU`, never the Airtable SKU.
        # Accept either as valid identity; this stays an exact-match check (no
        # fuzzy join is reintroduced), so it does not touch what the Grandeur
        # regression guards against — a UUID that belongs to a genuinely
        # different product, under either identifier.
        supplier_sku = clean(row.get("Supplier SKU"))
        sku_candidates = {sku} | ({supplier_sku} if supplier_sku else set())

        ls_by_id = ls["by_id"].get(uuid) if uuid else None
        ls_by_sku = ls["by_sku"].get(sku) or (ls["by_sku"].get(supplier_sku) if supplier_sku else None)

        if uuid and ls_by_id is None:
            block(sku, "uuid_not_in_lightspeed",
                  f"row carries {uuid}, which Lightspeed does not hold")
            continue

        if uuid and clean(ls_by_id.get("sku")) not in sku_candidates:
            block(sku, "uuid_belongs_to_other_sku",
                  f"{uuid} belongs to {clean(ls_by_id.get('sku'))} "
                  f"({clean(ls_by_id.get('name')) or ''}) — writing it would overwrite that product")
            continue

        # A blank UUID whose SKU already lives in Lightspeed: repairable, and the
        # bug that otherwise makes Lightspeed create a duplicate.
        recovered = None
        if not uuid and ls_by_sku:
            recovered = clean(ls_by_sku.get("id"))
            uuid = recovered

        if not uuid and handle:
            clash = [p for p in ls["by_handle"].get(handle, [])
                     if clean(p.get("sku")) != sku]
            if clash:
                block(sku, "handle_collision_on_create",
                      f"handle {handle} is already held by "
                      f"{', '.join(sorted(clean(p.get('sku')) or '?' for p in clash)[:4])}")
                continue

        # sf/b must be readable in Lightspeed on every row that has a box size.
        # Enforced always, including variant groups (Albert, 2026-09-10). The rule
        # was already written in ls-upload-instructions; nothing checked it, and
        # ENG-VIDR-0038 sat in Lightspeed for months with no sf/b in its name.
        #
        # Only on a CREATE (uuid still blank here): an UPDATE never writes `name`
        # (ls_update_fields — "prices, and nothing else"), so the skill-built
        # ls_upload row's name is never sent for a matched product and checking
        # it proves nothing about what a person sees at the POS. IMPRESSIVE
        # (2026-09-14) was the first supplier with matched/update rows to reach
        # this check and it blocked 187 of 220 on that never-sent placeholder
        # name — every existing test for this function uses a blank Lightspeed
        # ID (create), so this gap had no coverage either.
        if not uuid:
            sfb_problem = sfb_not_exposed(row, ls_upload.get(sku),
                                          group_boxes.get(handle) if handle else None)
            if sfb_problem:
                block(sku, "sfb_not_exposed", sfb_problem)
                continue

        category = clean(row.get("Category"))
        if category and not category_resolves(category, categories):
            warn(sku, "category_unresolved",
                 f"Airtable category {category!r} does not map to a Lightspeed leaf on its "
                 "own — LVP/LVT are formats, and Lightspeed classifies vinyl by core and "
                 "install (SPC / WPC / GLUE DOWN / LOOSE LAY). Needs Material type and "
                 "Install method. Not blocking: no write path sets a category yet.")

        # ---- Airtable side ----
        # Without a live snapshot there is no honest way to say what Airtable needs.
        # The upload CSV shows the base as it was when the price list was processed,
        # and on 2026-09-10 that difference was 50 rows against a real gap of 5.
        # Emitting nothing is correct; emitting a guess and warning about it is not.
        live = existing.get(sku) if airtable_snapshot else None
        is_new_in_airtable = (match_status == "new") or (live is None and match_status != "matched")
        fields, before, unreadable = {}, {}, []
        if is_new_in_airtable:
            # There is no live record to diff against, so DIFF_FIELDS (which
            # exists to write only what actually changed on an UPDATE) does not
            # apply here — it would leave a brand-new record with ~5 of 57
            # columns populated and everything else blank. A create writes the
            # whole row: every non-empty column from the upload CSV except the
            # merge key and the reviewer helper columns, neither of which is a
            # real field. Found 2026-09-13: this path had never been exercised
            # against a genuine new-to-Airtable supplier before HOMESPRO.
            for field, new_raw in row.items():
                if field in (SKU, MATCH_STATUS, MATCHED_REC, LS_MATCH_STATUS):
                    continue
                new = clean(new_raw)
                if new is not None:
                    fields[PRICE_DATE if field == LEGACY_PRICE_DATE else field] = new
        else:
            for field in DIFF_FIELDS:
                new = clean(row.get(field))
                if new is None:
                    continue
                if live is None:
                    old, readable = None, False
                else:
                    raw, readable = live_value(live, field)
                    old = clean(raw)
                if not readable:
                    # No prior value to compare against, so write it and say so
                    # rather than implying it was empty.
                    fields[field] = new
                    unreadable.append(field)
                    continue
                if comparable(field, new) != comparable(field, old):
                    fields[field] = new
                    before[field] = old

        if is_new_in_airtable:
            if fields:
                fields[CHANGED_BY] = AGENT
        else:
            # `Effective Date` = the date of the NEWEST list that carries this
            # product (Albert, 2026-09-25): a list that repeats the same price still
            # moves the date forward, because the price is confirmed current. It never
            # moves backward on a confirmation — an older list processed late must not
            # make a record look staler than it is. A price change always writes the
            # list's date, and only a price change writes the author: a confirmation
            # changed nobody's price.
            price_moved = any(f in PRICE_FIELDS for f in fields)
            raw_date = clean(row.get(PRICE_DATE)) or clean(row.get(LEGACY_PRICE_DATE))
            effective = raw_date if raw_date and ISO_DATE.match(raw_date) else None
            if raw_date and not effective:
                warn(sku, "price_date_invalid",
                     f"Effective Date {raw_date!r} is not YYYY-MM-DD, so the date "
                     "was left as it was")
            old_date, date_readable = (live_value(live, PRICE_DATE) if live
                                       else (None, False))
            old_date = clean(old_date)
            if price_moved:
                if effective:
                    fields[PRICE_DATE] = effective
                    before[PRICE_DATE] = old_date if date_readable else None
                elif not raw_date:
                    warn(sku, "price_date_missing",
                         "cost/retail changed but the upload row has no Effective "
                         "Date (the list's effective date), so the date was left "
                         "as it was")
                fields[CHANGED_BY] = AGENT
                old_by, readable = live_value(live, CHANGED_BY) if live else (None, False)
                before[CHANGED_BY] = clean(old_by) if readable else None
            elif effective and date_readable and (old_date is None
                                                  or effective > str(old_date)):
                # Unreadable (the snapshot lacks the column) writes nothing here: a
                # blind write could move a newer date backward.
                fields[PRICE_DATE] = effective
                before[PRICE_DATE] = old_date
            url = clean(row.get(PRICE_URL))
            if url:
                old_url, url_readable = (live_value(live, PRICE_URL) if live
                                         else (None, False))
                old_url = clean(old_url)
                same_list = (effective and date_readable
                             and str(old_date or "") == effective)
                if PRICE_DATE in fields or (same_list and url_readable
                                            and old_url != url):
                    if old_url != url:
                        fields[PRICE_URL] = url
                        before[PRICE_URL] = old_url if url_readable else None
            promo_url = clean(row.get(PROMO_URL))
            carries_promo = clean(row.get(PROMO_COST)) or clean(row.get(PROMO_END))
            if promo_url and carries_promo:
                old_purl, purl_readable = (live_value(live, PROMO_URL) if live
                                           else (None, False))
                old_purl = clean(old_purl)
                promo_moved = PROMO_COST in fields or PROMO_END in fields
                # Same promo re-run: both promo fields were read and neither moved.
                # Fill or repoint the link only then, and only when the snapshot
                # carried the link — a blind write could repoint an ended promo at a
                # list that never set it.
                same_promo = (live is not None and not promo_moved
                              and live_value(live, PROMO_COST)[1]
                              and live_value(live, PROMO_END)[1])
                if (promo_moved or (same_promo and purl_readable)) and old_purl != promo_url:
                    fields[PROMO_URL] = promo_url
                    before[PROMO_URL] = old_purl if purl_readable else None

        if airtable_snapshot and select_options:
            missing = missing_select_options(fields, select_options)
            if missing:
                field, value, near = missing[0]
                reason = ("supplier_option_missing" if field == SUPPLIER
                          else "select_option_missing")
                hint = (f" The live option {near!r} differs only in case: fix the upload "
                        "CSV, never the option." if near else
                        " Add the option in Airtable, then re-run; nothing was written "
                        "to either system for this SKU.")
                extra = (f" ({len(missing) - 1} more: "
                         + ", ".join(f"{f}={v!r}" for f, v, _ in missing[1:]) + ")"
                         if len(missing) > 1 else "")
                block(sku, reason,
                      f"{field}={value!r} is not a live Airtable option.{hint}{extra}")
                continue

        if recovered:
            fields[LS_ID] = recovered
            before[LS_ID] = None
            if LS_ID in unreadable:
                unreadable.remove(LS_ID)

        uuid_source = ("recovered_by_sku" if recovered
                       else "upload" if uuid else "lightspeed_on_create")

        # Resolved up front: a row that cannot be created must block before any
        # action is emitted for it. Every row yields actions or a block, never both.
        create_fields = None if uuid else ls_create_fields(row, ls_upload.get(sku))
        if not uuid and create_fields is None:
            block(sku, "ls_payload_unavailable",
                  "this SKU is new to Lightspeed, and a create needs the skill-built "
                  "row from <supplier>_ls_upload_<date>.csv — the product name and "
                  "category cannot be derived from the Airtable columns alone. "
                  "Pass --ls-upload.")
            continue

        if fields and not airtable_snapshot:
            fields = {}
        if fields:
            price_moved = any(f in PRICE_FIELDS for f in fields)
            reason = ("new_product" if is_new_in_airtable
                      else "price_change" if price_moved else "field_update")
            action = {
                "id": action_id(supplier, sku, "airtable", "upsert"),
                "target_system": "airtable",
                "op": "upsert",
                "sku": sku,
                "airtable_rec_id": rec_id,
                "ls_id": uuid,
                "handle": handle,
                "fields": fields,
                "before": None if is_new_in_airtable else before,
                "reason": reason,
                "uuid_source": uuid_source,
            }
            if unreadable and not is_new_in_airtable:
                action["before_unreadable"] = sorted(unreadable)
            actions.append(action)

        # ---- Lightspeed side ----
        if uuid:
            ls_fields_out = ls_update_fields(row)
            live = ls_by_id or ls_by_sku
            before = ls_before(live)
            if before and all(
                    comparable(k, ls_fields_out.get(k)) == comparable(k, before.get(k))
                    for k in ls_fields_out):
                pass  # prices already agree; no Lightspeed write needed
            else:
                actions.append({
                    "id": action_id(supplier, sku, "lightspeed", "update"),
                    "target_system": "lightspeed", "op": "update", "sku": sku,
                    "airtable_rec_id": rec_id, "ls_id": uuid, "handle": handle,
                    "fields": ls_fields_out, "before": before,
                    "reason": "price_change", "uuid_source": uuid_source,
                })
        else:
            actions.append({
                "id": action_id(supplier, sku, "lightspeed", "create"),
                "target_system": "lightspeed", "op": "create", "sku": sku,
                "airtable_rec_id": rec_id, "ls_id": None, "handle": handle,
                "fields": create_fields, "before": None, "reason": "new_product",
                "uuid_source": "lightspeed_on_create",
            })
            actions.append({
                "id": action_id(supplier, sku, "airtable", "backfill_ls_id"),
                "target_system": "airtable", "op": "backfill_ls_id", "sku": sku,
                "airtable_rec_id": rec_id, "ls_id": None, "handle": handle,
                "fields": {LS_ID: "<assigned by Lightspeed on create>"},
                "before": {LS_ID: None}, "reason": "uuid_from_create",
                "uuid_source": "lightspeed_on_create",
            })

    return order(actions), blocked, warnings


def missing_select_options(fields, select_options):
    """[(field, value, case-only near match or None)] for values Airtable lacks.

    Exact match, because writes run with typecast OFF: a value that differs only
    in case is refused at write time (or, with typecast on, silently becomes a
    duplicate option, which is how the base collected its placeholder junk).
    Multi-select values are checked one by one, split on commas.
    """
    out = []
    for field, value in fields.items():
        live = select_options.get(field)
        if not live or value is None:
            continue
        parts = [p.strip() for p in str(value).split(",")] if "," in str(value) else [str(value).strip()]
        for part in parts:
            if part and part not in live:
                near = next((o for o in live if o.casefold() == part.casefold()), None)
                out.append((field, part, near))
    return out


FIELD_MAP = Path(__file__).resolve().parent.parent / "platform-settings/airtable-master-catalogue-fields.json"


def field_names_by_id():
    try:
        return {fid: f["name"] for fid, f in json.loads(FIELD_MAP.read_text())["fields"].items()}
    except (OSError, KeyError, ValueError):
        return {}


def load_select_options(path):
    """{field name: set(option names)} from either of two shapes.

    - The plain map `{"Supplier": ["FLOORS AT WORK", ...], ...}`.
    - The raw Airtable MCP `get_table_schema` result, from which every
      singleSelect / multipleSelects field is taken.
    """
    if not path:
        return None
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict) and data and all(isinstance(v, list) for v in data.values()):
        if not any(isinstance(x, dict) for v in data.values() for x in v):
            return {k: set(v) for k, v in data.items()}
    found = {}
    # get_table_schema as served on 2026-09-23 carries field ids and `config.choices`
    # but no field names; names resolve through the committed id map. Older payloads
    # carried `name` and `options.choices`; both shapes are read.
    names = field_names_by_id()

    def walk(node):
        if isinstance(node, dict):
            name = node.get("name") or names.get(node.get("id"))
            if node.get("type") in ("singleSelect", "multipleSelects") and name:
                holder = node.get("options") or node.get("config") or {}
                choices = holder.get("choices") or []
                found[name] = {c["name"] for c in choices if c.get("name")}
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(data)
    if not found:
        raise SystemExit(f"error: {path} holds no select options in either known shape")
    return found


def two_dp(value):
    """A box size as the two-decimal string every sf/b token is written with."""
    try:
        return f"{float(clean(value)):.2f}"
    except (TypeError, ValueError):
        return None


def box_sizes_by_handle(upload_rows):
    """handle -> sorted distinct two-decimal box sizes, for the rows that have one.

    Uniform vs mixed is the whole question this answers, so rows with no readable
    box size contribute nothing rather than an implicit extra value.
    """
    groups = defaultdict(set)
    for row in upload_rows:
        handle = clean(row.get(HANDLE))
        box = two_dp(row.get(BOX_SIZE))
        if handle and box:
            groups[handle].add(box)
    return {h: sorted(v, key=float) for h, v in groups.items()}


def combined_sfb(boxes):
    """The shared-name token for a mixed group: `18.19/20.18sf/b`.

    Ascending, two decimals, unit once. Identical on every row in the group, which
    is what lets it sit in a name Lightspeed requires to be identical.
    """
    return "/".join(boxes) + "sf/b"


def contains(haystack, needle):
    return needle in haystack or needle in haystack.replace(" ", "")


def sfb_not_exposed(upload_row, ls_row, group_boxes=None):
    """Return a reason string if this row's sf/b would be unreadable in Lightspeed.

    The invariant, from ls-upload-instructions: every row carrying a `Box size (sf)`
    must expose it where a person can read it at the POS. Lightspeed requires one
    name per variant family, so where it goes depends on the group:

      singleton / no-grade / uniform group -> the shared name
      mixed-box-size GRADE group           -> BOTH: the combined `18.19/20.18sf/b`
                                              in the shared name, and this row's own
                                              value in variant_option_one_value
      SIZE group (tile)                    -> variant_option_one_value only

    The mixed grade case is both because the two carry different facts (Albert,
    2026-09-10). The name says the family boxes two ways — a standing prompt to
    confirm with the supplier which one this product really is — and a combined
    string is identical across the group, so name identity still holds. Column 11
    says which of the two *this* grade is, which is what a staff member needs to
    convert the box in front of them. Neither substitutes for the other.

    Tile is exempt from the name half: there the variant dimension IS size, so box
    sizes differ by construction, nothing is ambiguous, and a six-size family would
    carry six numbers in its name.

    Per-piece items — accessories, STONE, mosaics — legitimately have no box size and
    are exempt. A FLOORING row with no box size is a data defect, but that is caught
    upstream in extraction, not here.

    Checked against the skill-built LS row, since that is what actually gets sent.
    Without one there is nothing to check and nothing to send.
    """
    box = clean(upload_row.get(BOX_SIZE))
    needle = two_dp(box)
    if needle is None or ls_row is None:
        return None
    name = clean(ls_row.get("name")) or ""
    value = clean(ls_row.get("variant_option_one_value")) or ""
    dimension = (clean(ls_row.get("variant_option_one_name")) or "").lower()

    boxes = list(group_boxes or [])
    mixed = len(boxes) > 1

    if mixed and dimension != "size":
        expected = combined_sfb(boxes)
        if not contains(name, expected):
            return (f"handle group boxes {len(boxes)} ways ({', '.join(boxes)}), so the "
                    f"shared Lightspeed name must state {expected} — it reads "
                    f"{name[:70]!r}. Two box sizes under one grade group is normally an "
                    "ambiguous price list, and the name is what prompts someone to "
                    "confirm with the supplier which one this is.")
        if not contains(value, needle):
            return (f"Box size (sf) is {box}, and the name correctly states the group's "
                    f"{expected}, but the variant value ({value!r}) does not say which "
                    f"of them this row is. Staff selling this grade need {needle}sf/b at "
                    "the point of selection; the combined name cannot give it to them.")
        return None

    if contains(name, needle) or contains(value, needle):
        return None
    return (f"Box size (sf) is {box}, but {needle}sf/b appears in neither the Lightspeed "
            f"name ({name[:60]!r}) nor the variant value ({value!r}). Staff convert boxes "
            "to square feet off one of those two, so a row exposing it in neither is "
            "unusable at the POS. Uniform groups and singletons carry it in the name; "
            "tile size groups carry it in the variant value.")


def category_resolves(category, leaves):
    """Does an Airtable category correspond, unambiguously, to a Lightspeed leaf?

    Compared on the final path segment because the two systems disagree on form:
    the API returns leaf names alone ('SPC', 'ENGINEERED HARDWOOD') while the CSV
    importer takes ' / '-separated paths.

    'Laminate', 'Engineered hardwood' and 'Solid hardwood' resolve. 'LVP' and
    'LVT' do NOT, and that is correct rather than a gap in this function: they name
    a FORMAT, while Lightspeed classifies vinyl by core and install method — the
    live catalogue holds SPC, WPC, GLUE DOWN and LOOSE LAY as separate leaves.
    Deriving the right one needs Material type and Install method, and the live
    catalogue also uses leaves the documented list does not cover. That mapping is
    an open question for the Phase 3 spike, so a miss here is a warning.
    """
    want = category.strip().lower().replace("-", " ")
    return any(want == leaf.split("/")[-1].strip().lower() for leaf in leaves)


def ls_update_fields(row, as_of=None):
    """What a Lightspeed UPDATE writes: prices, and nothing else.

    Deliberately minimal, because the obvious wider payload is destructive.

    `name` is NOT Airtable's `Product name`. Lightspeed holds a constructed name —
    "GRNDENG - Scandinavia European White Oak (Bora Bora) T&G | 6.5" x 19.05mm x RL
    - 1.2mm top - 20.83sf/b - Select" — built by the ls-upload-instructions skill
    from a dozen columns, against Airtable's "Grandeur 6.5" EWO — Bora Bora (ABC)".
    Writing the Airtable value would rename every product in the POS, and
    Lightspeed identifies products BY NAME.

    `supplier_name` is likewise not safe to write: Airtable says "Grandeur" where
    Lightspeed says "GRANDEUR", and the live account already carries 116 supplier
    names for far fewer real suppliers. Writing it risks renaming or forking one.

    `product_category` is unresolved — see category_resolves().

    So an update moves prices, which are verified 315/315, and leaves every field
    whose correct value this script cannot construct alone.

    The API reference vindicates this exactly. Updates go to PUT /api/2.1/products/{id}
    with a `common` section (fields shared by a whole variant family — name,
    description) and a `details` section (fields belonging to one product — prices,
    product codes). This payload is `details` alone, so an update touches nothing
    family-wide. And `name` turns out to be worse than a rename: the reference states
    that name IS what groups a variant family, and that two products can only share a
    name if they are in the same family. Writing Airtable's name onto a Lightspeed
    product could therefore merge unrelated products into one family.

    Which cost, though, depends on whether a promo is running (Albert, 2026-09-10):

      supply_price        = `Promo cost ($/sf)` when populated, else `Cost/unit`
      price_excluding_tax = `Retail price/unit`, always

    `supply_price` is what Titan actually pays, and during a promo that is the promo
    cost. `Cost/unit` still holds the regular cost — it is what the price reverts to
    when the promo ends, and a populated `Promo cost` clearing itself on
    `Promo end date` is what puts supply_price back without a second decision.

    Retail deliberately does NOT follow the promo. It stays `Cost/unit + $ 1.00` off
    the REGULAR cost, so a change in the regular cost still moves it. Adjusting retail
    during a promo remains a manual act. The consequence, stated so nobody is
    surprised: a hand-set promo retail in Lightspeed WILL be rewritten by the next
    sync. That is visible rather than silent — it appears as a before/after on the
    plan a person approves — but it is not preserved.

    ## The sync moves the promo PRICE, not the promo MARKER — deliberately

    An update writes prices and nothing else, so it cannot set or clear the two
    visible promo markers — `tags: PROMO` (column 16) and the `(P YYYY-MM-DD)` prefix
    on `variant_option_one_value` (column 11). On an existing product those reach
    Lightspeed only through a rebuilt CSV import.

    That asymmetry is the right way round (Albert, 2026-09-10). `(P …)` means "verify
    this promo before quoting", not "this is on sale today"; it carries the end date,
    so a stale marker exposes its own staleness; and a salesperson checks the date
    before committing to a quote regardless. A lagging marker costs a lookup. The
    price is the part that has to be right without anyone thinking about it, and it
    is — in both directions, since clearing `Promo cost ($/sf)` on `Promo end date`
    puts `supply_price` back on the next sync.

    Making the marker self-clearing would mean letting an update write
    `variant_attribute_values` and tags: a real widening of a payload kept
    deliberately narrow, against a 2.1 attribute shape that has already bitten once
    (a guard read the wrong key and returned [] where a `Select` existed). Worth
    doing only on the evidence of a live API check. Not urgent.

    Done since, and NOT here (2026-09-26): scripts/promo_sweep.py, the sweep's promo
    lane, writes the name prefix on standalone products after a live check on
    LAM-FAWK-0004. This function still moves prices only.

    ## A lapsed promo is not what Titan pays (2026-09-23)

    The paragraphs above assume `Promo cost` clears itself on `Promo end date`.
    Nothing does that: no promo-expiry mechanism exists anywhere, and Albert ruled
    on 2026-09-23 that no sweep should clear them. So a row can carry a promo that
    ended weeks ago (28 FAW records still held August's on 2026-09-23). Read "as
    written", this function would push that dead price into Lightspeed as today's
    supply_price. It surfaced the first time a CSV was re-rendered from live
    Airtable (scripts/catalog_export.py), which carries those stale values
    faithfully. So a promo whose end date is before `as_of` is ignored here and the
    regular cost is used. The Airtable fields are untouched: this is not the sweep.
    A promo with no end date still applies, since clearance "while stock lasts"
    prints none.
    """
    promo = as_number(row.get(PROMO_COST))
    end = clean(row.get(PROMO_END))
    if promo is not None and end and end[:10] < (as_of or today()):
        promo = None
    cost = as_number(row.get("Cost/unit"))
    return {k: v for k, v in (
        ("supply_price", promo if promo is not None else cost),
        ("price_excluding_tax", as_number(row.get("Retail price/unit"))),
    ) if v is not None}


def ls_create_fields(row, ls_upload_row):
    """What a Lightspeed CREATE writes.

    A create needs the full product — name, category, description — and this
    script cannot construct those correctly. They come from the LS upload CSV that
    /process-price-list already built with the ls-upload-instructions skill, keyed
    by sku. Without that file a create is blocked rather than guessed.
    """
    if not ls_upload_row:
        return None
    fields = {
        "sku": clean(ls_upload_row.get("sku")),
        "handle": clean(ls_upload_row.get("handle")),
        "name": clean(ls_upload_row.get("name")),
        "supply_price": as_number(ls_upload_row.get("supply_price")),
        # The CSV column is `retail_price`; the API field is price_excluding_tax.
        "price_excluding_tax": as_number(ls_upload_row.get("retail_price")),
    }
    # `tags` (CSV column 16, `PROMO`) is deliberately NOT carried yet. The API field
    # name and whether it wants names or resolved tag ids are unverified — the
    # credential was dead when this was written — and an unverified key 422s the whole
    # create. See the promo-marker gap in ls_update_fields.
    for csv_col, api_key in (("description", "description"),
                             ("brand_name", "brand_name"),
                             ("supplier_name", "supplier_name")):
        value = clean(ls_upload_row.get(csv_col))
        if value:
            fields[api_key] = value

    # `product_category` is carried as the CSV's path form ('FLOORING / TILE'),
    # verbatim. lightspeed_push.Lookups.resolve() matches it against a nested
    # type's full path first, then falls back to the leaf ('SPC'). Stripping to the
    # leaf here (as on 2026-09-18, before that fallback existed) threw away the one
    # thing that tells Titan's two live TILEs apart — PL-372, 2026-09-23, 42 creates
    # refused as ambiguous until the path was kept (Albert: "use the TILE that is
    # nested in FLOORING").
    category = clean(ls_upload_row.get("product_category"))
    if category:
        fields["product_category"] = category

    # Variant grouping. The CSV carries the option as a name/value pair; the API
    # wants {attribute_id, value}, resolved against the live attribute list at
    # write time. Carried through as names here so the plan stays readable and the
    # push step does the resolution — it must never invent an attribute.
    opt_name = clean(ls_upload_row.get("variant_option_one_name"))
    opt_value = clean(ls_upload_row.get("variant_option_one_value"))
    if opt_name and opt_value:
        fields["variant_option"] = {"name": opt_name, "value": opt_value}
    return {k: v for k, v in fields.items() if v is not None}


def ls_before(product):
    if not product:
        return None
    return {k: product.get(k) for k in
            ("name", "handle", "sku", "supply_price", "price_including_tax",
             "price_excluding_tax", "category", "supplier_name", "active")
            if k in product}


def order(actions):
    """Forced dependency order: Airtable state, then Lightspeed, then backfill."""
    rank = {("airtable", "upsert"): 0, ("lightspeed", "update"): 1,
            ("lightspeed", "create"): 1, ("airtable", "backfill_ls_id"): 2}
    actions.sort(key=lambda a: (rank[(a["target_system"], a["op"])], a["sku"]))
    for seq, action in enumerate(actions, 1):
        action["seq"] = seq
    return actions


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upload", type=Path, required=True,
                    help="Airtable upload CSV from /process-price-list")
    ap.add_argument("--lightspeed", type=Path,
                    help="LS pull JSON. Default ingest/<today>/lightspeed-products.json")
    ap.add_argument("--airtable-existing", type=Path,
                    help="JSON of live Airtable records, for before/after")
    ap.add_argument("--ls-upload", type=Path,
                    help="The <supplier>_ls_upload_<date>.csv built by "
                         "/process-price-list. Required for any row that is new to "
                         "Lightspeed: a create needs the skill-built name and "
                         "category, which cannot be derived from the Airtable columns.")
    ap.add_argument("--airtable-options", type=Path,
                    help="Live Airtable select options (plain {field: [names]} or the raw "
                         "get_table_schema output). The pre-flight: a value Airtable lacks "
                         "blocks that SKU on both systems before anything is written.")
    ap.add_argument("--supplier", help="Override the Supplier read from the CSV")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--cost-basis", help="e.g. 'dealer'. Recorded, never inferred.")
    ap.add_argument("--confirmed-by", help="Who confirmed the cost basis, and when")
    ap.add_argument("--as-of", help="YYYY-MM-DD for the effective-date gate. Default: "
                    "today in Toronto. A row whose list takes effect later is blocked "
                    "not_yet_effective; only a person passes a later date on purpose.")
    args = ap.parse_args()

    ls_path = args.lightspeed or (REPO_ROOT / "ingest" / today() / "lightspeed-products.json")
    if not ls_path.exists():
        print(f"error: no Lightspeed pull at {ls_path}. Run scripts/lightspeed_pull.py first — "
              "the identity checks are not possible without the live catalogue.", file=sys.stderr)
        return 2

    with open(args.upload, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print(f"error: {args.upload} has no rows", file=sys.stderr)
        return 2

    supplier = args.supplier or clean(rows[0].get(SUPPLIER)) or "unknown"
    ls = load_lightspeed(ls_path)
    if ls["sku_collisions"]:
        print(f"error: the Lightspeed pull has duplicate SKUs "
              f"({ls['sku_collisions'][:5]}...). sku is the join key; resolve before "
              "reconciling.", file=sys.stderr)
        return 2

    existing = load_airtable_existing(args.airtable_existing)
    ls_upload = {}
    if args.ls_upload:
        if not args.ls_upload.exists():
            print(f"error: no such file {args.ls_upload}. Rows new to Lightspeed will "
                  "block without it.", file=sys.stderr)
            return 2
        with open(args.ls_upload, newline="", encoding="utf-8") as fh:
            ls_upload = {clean(r.get("sku")): r for r in csv.DictReader(fh)
                         if clean(r.get("sku"))}
    categories = json.loads(
        (REPO_ROOT / "platform-settings" / "lightspeed.json").read_text()
    )["product_categories"]["leaves"]

    have_snapshot = bool(args.airtable_existing)
    select_options = load_select_options(args.airtable_options)
    actions, blocked, warnings = reconcile(rows, ls, existing, supplier, categories,
                                          ls_upload, airtable_snapshot=have_snapshot,
                                          select_options=select_options,
                                          as_of=args.as_of)
    if have_snapshot and select_options is None:
        warnings.insert(0, {
            "sku": None,
            "reason": "select_options_not_checked",
            "detail": ("No --airtable-options were supplied, so no Airtable select value "
                       "on this plan was checked against the live base. A value Airtable "
                       "lacks will be refused at write time, after Lightspeed has already "
                       "been written for that SKU."),
        })

    if not have_snapshot:
        warnings.insert(0, {
            "sku": None,
            "reason": "airtable_side_not_planned",
            "detail": ("No live Airtable snapshot was supplied, so this plan contains NO "
                       "Airtable actions. The upload CSV records the base as it stood when "
                       "the price list was processed, not now — on 2026-09-10 planning from "
                       "it claimed 50 Lee rows needed a Lightspeed ID when the live base was "
                       "missing 5. Pass --airtable-existing with a snapshot exported through "
                       "the Airtable MCP tools; the Lightspeed side below is unaffected, "
                       "since it is reconciled against the live catalogue pull."),
        })

    kinds = Counter(f"{a['target_system']}_{a['op']}" for a in actions)
    recovered = len({a["sku"] for a in actions if a.get("uuid_source") == "recovered_by_sku"})
    plan = {
        "contract_version": CONTRACT_VERSION,
        "supplier": supplier,
        "run_at": datetime.now(TZ).isoformat(),
        "status": "partial" if blocked else "ok",
        "inputs": [
            {"file": str(args.upload), "rows": len(rows)},
            {"file": str(ls_path), "products": ls["count"], "run_at": ls["pulled_at"]},
        ] + ([{"file": str(args.airtable_existing), "records": len(existing)}]
             if args.airtable_existing else [])
          + ([{"file": str(args.airtable_options), "select_fields": len(select_options)}]
             if select_options else [])
          + ([{"file": str(args.ls_upload), "rows": len(ls_upload)}]
             if args.ls_upload else []),
        "cost_basis": ({"value": args.cost_basis, "confirmed_by": args.confirmed_by}
                       if args.cost_basis else None),
        "as_of": args.as_of or today(),
        "effective_dates": sorted({d for r in rows
                                   for d in [clean(r.get(PRICE_DATE))
                                             or clean(r.get(LEGACY_PRICE_DATE))] if d}),
        "summary": {**dict(sorted(kinds.items())),
                    "actions_total": len(actions),
                    "uuid_recovered_by_sku": recovered,
                    "blocked": len(blocked),
                    "warnings": len(warnings),
                    "rows_in": len(rows)},
        "actions": actions,
        "blocked": blocked,
        "warnings": warnings,
    }

    out = args.out or (REPO_ROOT / "plans" / today() /
                       f"catalog-plan-{slugify(supplier)}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=1) + "\n")

    print(f"{out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out}")
    print(f"  supplier   {supplier}")
    print(f"  rows in    {len(rows)}")
    for kind, n in sorted(kinds.items()):
        print(f"  {kind:24} {n}")
    if recovered:
        print(f"  {'uuid recovered by sku':24} {recovered}   "
              f"(blank in the upload, found live — would have duplicated)")
    print(f"  blocked    {len(blocked)}")
    for reason, n in Counter(b["reason"] for b in blocked).most_common():
        print(f"    {reason:28} {n}")
    if warnings:
        print(f"  warnings   {len(warnings)}")
        for reason, n in Counter(w["reason"] for w in warnings).most_common():
            print(f"    {reason:28} {n}")
    if any(w["reason"] == "airtable_side_not_planned" for w in warnings):
        print("\n  NO Airtable actions planned: no live snapshot was supplied, and the "
              "upload\n  CSV is not the current state of the base. Pass --airtable-existing.")
    if blocked:
        print("\n  Blocked rows are NOT approvable and never reach a write. Fix the data "
              "and re-run.")
    if plan["cost_basis"] is None and any(a["reason"] == "new_product" for a in actions):
        print("\n  This plan creates products and carries no cost basis. Pass --cost-basis "
              "once Albert confirms it; it is never inferred.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
