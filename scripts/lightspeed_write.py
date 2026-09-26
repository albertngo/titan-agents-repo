#!/usr/bin/env python3
"""Lightspeed (X-Series) write transport. THIS MODULE CHANGES THE LIVE POS.

Separate from scripts/lightspeed_client.py on purpose. The read path — the daily
catalogue pull — stays reviewable on its own, and anyone scanning the repo can tell
which scripts are capable of changing the store: exactly this one and its caller,
scripts/lightspeed_push.py.

What it can do, and nothing more:

    create_family(payload)          POST   /api/2.0/products
    update_variant(id, details)     PUT    /api/2.1/products/{id}
    set_promo_marker(id, ...)       PUT    /api/2.1/products/{id}  (name prefix only)
    set_variant_marker(id, ...)     PUT    /api/2.1/products/{id}  (variant value prefix only)
    delete_product(id, expect_sku)  DELETE /api/2.0/products/{id}
    read_family(id)                 GET    /api/3.0/products/{id}

**Delete exists since 2026-09-24, and only as a person's decision.** Until then there
was none, deliberately. Albert reversed that for products a supplier's newest list no
longer carries (FAW PL-377: the old T&G Toffee / Warm Honey, "If they don't exist in
the newest, delete them"). What still holds: removing a product is never the
pipeline's idea. lightspeed_push.py refuses a delete action unless the approval
names a person (a policy auto-approval can never carry one), and delete_product()
re-reads the product first, refusing unless its live sku is the one the plan meant.
It also refuses a variant family, because deleting a parent takes its variants with it.
Lightspeed's delete archives the product (`deleted_at`); its sales history stays.

Three versions are in play and that is not an accident of ours — creates are 2.0,
updates are 2.1, reading a whole family is 3.0. Paths come from
platform-settings/lightspeed.json rather than being written inline.

## The two rules that carry the safety

**`name` groups a variant family.** Per the API reference, two products can share a
name only if they are in the same family. So writing a name is never a rename — it
can pull unrelated products into one family. update_variant() therefore refuses to
send a `common` section unless the caller passes allow_common=True and says why.

**A create response is a flat array of ids in Lightspeed's own sort order** — by
attribute value, not by payload order, and not keyed by sku. Pairing ids to SKUs
positionally is precisely the mistake that produced the Grandeur incident.
create_family() will not return a mapping; use read_family() afterwards and pair on
sku. That is enforced, not advised.

Dry run is enforced in the transport, not in the caller: with dry_run=True no
request that could change anything is ever built.

Environment: LIGHTSPEED_DOMAIN_PREFIX, LIGHTSPEED_PERSONAL_TOKEN.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lightspeed_client import LightspeedClient, LightspeedError  # noqa: E402

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

# `(P YYYY-MM-DD) `, `(R YYYY-MM-DD) `, `(P) ` or `(R) ` at the very start of a name
# or variant value — the promo / rep-rate marker (ls-upload-instructions, "Marking a
# promo"). Same pattern as scripts/promo_sweep.py; a test holds the two together.
PROMO_MARKER = re.compile(r"^\([PR](?: \d{4}-\d{2}-\d{2})?\)\s*")


def strip_promo_marker(name):
    return PROMO_MARKER.sub("", name or "", count=1)


class LightspeedWriter(LightspeedClient):
    """Adds create, update and a guarded delete to the read-only client."""

    def __init__(self, *args, dry_run=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.dry_run = dry_run
        self.planned = []   # what a dry run would have sent
        self.sent = []      # what a live run actually sent

    def _send(self, method, path, params=None, body=None):
        if method not in WRITE_METHODS:
            return super()._send(method, path, params=params, body=body)

        record = {"method": method, "path": path, "body": body}
        if self.dry_run:
            self.planned.append(record)
            print(f"DRY RUN {method} {self.base_url.rstrip('/')}{path}")
            print(json.dumps(body, indent=2))
            # A sentinel, not a fake id. Anything that tries to use this as a real
            # response fails loudly instead of quietly writing a placeholder.
            return {"dry_run": True, "data": None}

        self.sent.append(record)
        return super()._send(method, path, params=params, body=body)

    # -- creates -----------------------------------------------------------

    def create_family(self, payload):
        """Create a product, or a whole variant family, and return the raw ids.

        Returns the response's id list AS GIVEN. It is deliberately not paired with
        anything: Lightspeed orders it by attribute value, so position tells you
        nothing reliable about which sku got which id. Call read_family() on any
        returned id and pair on sku.
        """
        if not payload.get("name"):
            raise LightspeedError("create_family needs a `name`; it is the only required "
                                  "field and it is what groups a variant family")
        _NO_SKU = ("needs an explicit sku. Lightspeed mints one from its own "
                   "sequence when omitted, and RULE 0 makes the Airtable SKU the source of "
                   "truth — a generated sku would orphan the row.")
        if "variants" in payload:
            for variant in payload["variants"]:
                if not variant.get("sku"):
                    raise LightspeedError(f"every variant {_NO_SKU}")
        elif not payload.get("sku"):
            # A standalone product omits `variants` and carries sku at the top level,
            # so the loop above never sees it. Same rule, different place to look.
            raise LightspeedError(f"a standalone product {_NO_SKU}")
        body = self._send("POST", self.cfg["api"]["endpoints"]["products"], body=payload)
        if body.get("dry_run"):
            return None
        ids = body.get("data")
        if not isinstance(ids, list) or not ids:
            raise LightspeedError(f"unexpected create response: {json.dumps(body)[:300]}")
        return ids

    def add_variant(self, family_name, sku, variant_attribute_values, details=None):
        """Add one variant to a family that ALREADY exists.

        A third endpoint again: POST /api/2.1/products/, distinct from the 2.0 POST
        that creates a family and from the 2.1 PUT that updates one and cannot
        create variants at all.

        The family is found by `common.name` — more confirmation that name, not
        handle, is the family key on the API side. `variant_attribute_values` must
        cover every attribute the family uses, and must not repeat a combination
        another member already holds, or Lightspeed rejects it as a duplicate
        variant.
        """
        if not family_name:
            raise LightspeedError("add_variant needs the EXISTING family name; that is "
                                  "how Lightspeed finds the family to join")
        if not sku:
            raise LightspeedError("add_variant needs an explicit sku — Lightspeed would "
                                  "otherwise mint one, and RULE 0 forbids that")
        if not variant_attribute_values:
            raise LightspeedError("add_variant needs variant_attribute_values covering "
                                  "every attribute the family uses")

        body = {
            "common": {"name": family_name},
            "details": {
                "product_codes": [{"code": sku, "type": "CUSTOM"}],
                "variant_attribute_values": variant_attribute_values,
                **(details or {}),
            },
        }
        resp = self._send("POST", self.cfg["api"]["endpoints"]["variant_add"], body=body)
        return None if resp.get("dry_run") else resp

    # -- updates -----------------------------------------------------------

    def update_variant(self, product_id, details, common=None, allow_common_reason=None):
        """Update ONE product's own fields — prices, product codes.

        `details` is per-product. `common` is family-wide and would rewrite every
        member, so it is refused unless the caller states a reason, which then gets
        logged. Nothing in the catalogue sync passes it.

        Callers speak the READ vocabulary (`supply_price`, `price_excluding_tax`),
        because that is what the 2.0 pull returns and what the plan is written in.
        The 2.1 update endpoint does not accept `supply_price` at all, so this
        method translates it — see _supply_price_to_product_suppliers().
        """
        if common and not allow_common_reason:
            raise LightspeedError(
                "refusing to write a `common` section: it updates EVERY member of the "
                "variant family, and `name` in particular regroups families. Pass "
                "allow_common_reason=... if this is genuinely intended.")
        if not details and not common:
            raise LightspeedError("update_variant called with nothing to write")

        payload = {}
        if details:
            payload["details"] = self._to_update_details(product_id, details)
        if common:
            payload["common"] = common
        path = self.cfg["api"]["endpoints"]["product_update"].format(id=product_id)
        body = self._send("PUT", path, body=payload)
        return None if body.get("dry_run") else body

    # Placeholder the dry run prints where a live run resolves the real supplier.
    # Deliberately not a uuid: anything that mistakes it for one fails loudly.
    SUPPLIER_AT_WRITE_TIME = "<supplier resolved at write time>"

    def _to_update_details(self, product_id, details):
        """Canonical field names -> the 2.1 `details` wire format.

        `supply_price` is the one that does not survive the trip. The 2.0 list
        endpoint RETURNS it, so the whole codebase reads and plans in it, but it
        is a convenience projection: the cost is really stored on the join row
        between a product and its supplier. The 2.1 update schema has no
        `supply_price` key and rejects the whole request with
        `422 Unknown field in payload` when it sees one — verified live
        2026-09-21 against ENG-FAWK-0054, which is what stopped the first real
        push of this pipeline.

        The accepted shape is `product_suppliers: [{supplier_id, price}]`, so the
        supplier has to be known before the cost can be written. It is not in the
        plan, so it is read from the live product here. `price_excluding_tax` was
        always correct and passes through untouched.

        The WHOLE array goes back, with only the product's own supplier's price
        changed (ported 2026-09-23 from b44e192, which had verified it live on
        ENG-FAWK-0010 but was never merged). Sending a one-element array is
        correct for a product with one supplier and, on a product with two, risks
        dropping the second: `product_suppliers` replaces rows. Which row is
        "ours" is decided by the product's own `supplier_id`, never by position.
        """
        details = dict(details)
        if "sku" in details:
            details["product_codes"] = self._product_codes_with_sku(product_id, details.pop("sku"))
        if "supply_price" not in details:
            return details

        supply_price = details.pop("supply_price")
        if self.dry_run:
            details["product_suppliers"] = [
                {"supplier_id": self.SUPPLIER_AT_WRITE_TIME, "price": supply_price}]
            return details
        details["product_suppliers"] = self._product_suppliers_with_price(
            product_id, supply_price)
        return details

    def set_promo_marker(self, product_id, expect_sku, expect_name, new_name):
        """Put the promo marker on, or take it off, ONE standalone product's name.

        Albert, 2026-09-26: the `(P YYYY-MM-DD)` prefix goes on when a promo starts
        and comes off when it ends, during the morning sweep. A name is written
        through `common`, and name is what groups a variant family, so this is the
        narrowest name write that can exist:

        - only the marker may differ — with it stripped, old and new are identical;
        - the product is re-read first and must still carry `expect_sku` and
          `expect_name` (a name someone changed since the pull is not overwritten);
        - a variant family or a member of one is refused: its name is shared.
        """
        if not strip_promo_marker(new_name).strip():
            raise LightspeedError(f"refusing an empty product name for {expect_sku}")
        if strip_promo_marker(new_name) != strip_promo_marker(expect_name):
            raise LightspeedError(
                f"refusing to rename {expect_sku}: only the promo marker may change "
                f"({expect_name!r} -> {new_name!r})")
        product = self.read_product(product_id)
        if product.get("sku") != expect_sku:
            raise LightspeedError(
                f"refusing the promo marker on {product_id}: its live sku is "
                f"{product.get('sku')!r}, the plan expected {expect_sku!r}")
        if product.get("name") != expect_name:
            raise LightspeedError(
                f"refusing the promo marker on {expect_sku}: its name changed since the "
                f"pull ({product.get('name')!r}, plan expected {expect_name!r})")
        if product.get("has_variants") or product.get("variant_parent_id"):
            raise LightspeedError(
                f"refusing the promo marker on {expect_sku}: it is in a variant family, "
                "whose name is shared by every member")
        return self.update_variant(
            product_id, {}, common={"name": new_name},
            allow_common_reason="promo marker on a standalone product (Albert, 2026-09-26)")

    def set_variant_marker(self, product_id, expect_sku, attribute_id, expect_value, new_value):
        """Put the marker on, or take it off, ONE variant member's own variant value.

        A family shares one name, so a member's marker lives in its variant value —
        column 11 in the CSV, `(P 2026-09-30) Character` (ls-upload-instructions).
        Albert, 2026-09-26: "the P marker can go on variant names, not the parent one.
        So it should still have a marker." Guarded like set_promo_marker():

        - only the marker may differ between the old and new value;
        - the product is re-read and must still carry `expect_sku` and, on
          `attribute_id`, `expect_value`;
        - it must be a family member (a standalone product takes the name marker);
        - no sibling may already hold the new value — a Duplicate Variants rejection;
        - every attribute the member has goes back, only the marked one changed.
        """
        if not strip_promo_marker(new_value).strip():
            raise LightspeedError(f"refusing an empty variant value for {expect_sku}")
        if strip_promo_marker(new_value) != strip_promo_marker(expect_value):
            raise LightspeedError(
                f"refusing to change {expect_sku}'s variant value beyond the marker "
                f"({expect_value!r} -> {new_value!r})")
        product = self.read_product(product_id)
        if product.get("sku") != expect_sku:
            raise LightspeedError(
                f"refusing the variant marker on {product_id}: its live sku is "
                f"{product.get('sku')!r}, the plan expected {expect_sku!r}")
        if not (product.get("has_variants") or product.get("variant_parent_id")):
            raise LightspeedError(
                f"refusing the variant marker on {expect_sku}: it is not in a variant "
                "family (a standalone product carries the marker in its name)")
        options = product.get("variant_options") or []
        target = [o for o in options if o.get("id") == attribute_id]
        if len(target) != 1 or target[0].get("value") != expect_value:
            raise LightspeedError(
                f"refusing the variant marker on {expect_sku}: attribute {attribute_id} "
                f"reads {[o.get('value') for o in target]!r}, the plan expected "
                f"{expect_value!r}")
        for vid, values in self.family_attribute_values(product_id).items():
            if vid != product_id and any(v.get("attribute_id") == attribute_id
                                         and v.get("value") == new_value for v in values):
                raise LightspeedError(
                    f"refusing the variant marker on {expect_sku}: sibling {vid} already "
                    f"holds {new_value!r}")
        values = [{"attribute_id": o["id"],
                   "attribute_value": new_value if o is target[0] else o.get("value")}
                  for o in options]
        return self.update_variant(product_id, {"variant_attribute_values": values})

    def delete_product(self, product_id, expect_sku):
        """Delete (archive) ONE standalone product, after proving it is the one meant.

        Re-reads the product and refuses unless its live sku equals `expect_sku`, so
        a stale or mistyped UUID cannot remove a different product. Refuses a variant
        family or a member of one: deleting a parent removes every variant with it,
        and deleting one member of a family is a family edit, not a removal.
        """
        product = self.read_product(product_id)
        live_sku = product.get("sku")
        if not product or live_sku != expect_sku:
            raise LightspeedError(
                f"refusing to delete {product_id}: its live sku is {live_sku!r}, "
                f"the plan expected {expect_sku!r}")
        if product.get("has_variants") or product.get("variant_parent_id") \
                or (product.get("variant_count") or 0) > 1:
            raise LightspeedError(
                f"refusing to delete {expect_sku} ({product_id}): it belongs to a "
                "variant family, and a delete there removes more than one product")
        path = f"{self.cfg['api']['endpoints']['products']}/{product_id}"
        body = self._send("DELETE", path)
        return None if body.get("dry_run") else body

    def read_product(self, product_id):
        """GET one product from the 2.0 endpoint — carries product_suppliers[] with prices."""
        path = f"{self.cfg['api']['endpoints']['products']}/{product_id}"
        body = self.get(path)
        data = body.get("data", body)
        if isinstance(data, list):
            data = data[0] if data else {}
        return data or {}

    SKU_AT_WRITE_TIME = "<existing CUSTOM code id resolved at write time>"

    def _product_codes_with_sku(self, product_id, sku):
        """Correct a product's sku to `sku` — RULE 0: when Lightspeed and Airtable
        disagree about a SKU, the Lightspeed record is what gets corrected.

        The 2.1 update has no `sku` key (422 "Unknown field in payload", verified
        live 2026-09-24 on Vizion 11476). A product's sku IS its single `CUSTOM`
        entry in `product_codes`, and `product_codes` replaces the whole list, so
        every existing code goes back and only the CUSTOM one is rewritten, in
        place by its own id. Anything but exactly one CUSTOM code is refused.
        """
        if not sku:
            raise LightspeedError("refusing to set an empty sku")
        if self.dry_run:
            return [{"id": self.SKU_AT_WRITE_TIME, "type": "CUSTOM", "code": sku}]
        product = self.read_product(product_id)
        codes = product.get("product_codes") or []
        custom = [c for c in codes if c.get("type") == "CUSTOM"]
        if len(custom) != 1:
            raise LightspeedError(
                f"product {product.get('sku') or product_id} carries {len(custom)} CUSTOM "
                "product codes; refusing to guess which one is its sku.")
        out = []
        for c in codes:
            entry = {k: c[k] for k in ("id", "type", "code") if c.get(k) is not None}
            if c is custom[0]:
                entry["code"] = sku
            out.append(entry)
        return out

    def _product_suppliers_with_price(self, product_id, price):
        """Every existing supplier row, carried through, with only ours repriced.

        Never invents a supplier. 1,440 of the 14,525 live products carry none,
        and a cost cannot be written without one; picking a supplier to make the
        write succeed would invent a purchasing relationship, so that stops the
        batch. Nor does it guess between two rows that could both be ours.
        """
        product = self.read_product(product_id)
        rows = [r for r in (product.get("product_suppliers") or []) if r.get("supplier_id")]
        label = product.get("sku") or product_id
        if not rows:
            raise LightspeedError(
                f"product {label} has no supplier on record, and a 2.1 update "
                "writes the cost as product_suppliers[].price — there is nothing to "
                "attach it to. Refusing to pick a supplier: that would invent a "
                "purchasing relationship. Set the supplier in Lightspeed first.")
        own = product.get("supplier_id") or (product.get("supplier") or {}).get("id")
        targets = [r for r in rows if r["supplier_id"] == own] if own else rows
        if len(targets) != 1:
            raise LightspeedError(
                f"product {label} carries {len(rows)} supplier rows and {len(targets)} "
                f"match its own supplier {own!r}. Refusing to guess which one the "
                "cost belongs to.")
        out = []
        for r in rows:
            entry = {"supplier_id": r["supplier_id"],
                     "price": price if r is targets[0] else r.get("price")}
            # product_suppliers replaces the row, so a supplier code must be
            # carried through or it is blanked as a side effect.
            if r.get("code"):
                entry["code"] = r["code"]
            out.append(entry)
        return out

    # -- reads (inherited transport, listed here for callers) --------------

    def read_family(self, product_id):
        """GET the whole family. Any member id resolves to the family in 3.0."""
        path = self.cfg["api"]["endpoints"]["product_family"].format(id=product_id)
        body = self.get(path)
        return body.get("data", body)

    def family_by_sku(self, product_id):
        """{sku: variant} for a family. The only safe way to learn what was created.

        The 3.0 family read names things differently from the 2.0 product list: a
        variant carries `primary_sku_code`, not `sku`, and the authoritative code is
        the CUSTOM entry in `product_codes`. Verified against a live family
        2026-09-10 — reading `sku` alone returns nothing at all.

        A STANDALONE product is not a family of one here either (verified live
        2026-09-21 on db9e9a99, the first product created through this path): 3.0
        returns `variants: []` and carries the code at the TOP level, in
        `sku_number` and `product_codes`. Iterating `variants` alone returned {},
        which read as "the product I just created is not there" and stopped a batch
        whose write had in fact succeeded. Same read/write asymmetry as the create
        payload, one call later.
        """
        data = self.read_family(product_id)
        members = data.get("variants") or [data]
        out = {}
        for v in members:
            sku = v.get("primary_sku_code") or v.get("sku") or v.get("sku_number")
            for code in (v.get("product_codes") or []):
                if code.get("type") == "CUSTOM" and code.get("code"):
                    sku = code["code"]
                    break
            if sku:
                out[str(sku).strip()] = v
        return out

    def family_attribute_values(self, product_id):
        """[{attribute_id, name, value}] already used by each member of a family.

        Needed before adding a variant: repeating a combination another member holds
        is a Duplicate Variants rejection. The 3.0 read calls this
        `variant_definitions` — NOT `variant_attribute_values` (the write-side name)
        and NOT `variant_options` (the 2.0 read-side name). Three names for one
        concept; reading the wrong one silently returns an empty list, which would
        make a duplicate check pass when it should fail.
        """
        data = self.read_family(product_id)
        out = {}
        for v in (data.get("variants") or []):
            defs = v.get("variant_definitions") or v.get("variant_options") or []
            out[v.get("id")] = [{"attribute_id": d.get("attribute_id"),
                                 "name": d.get("name"),
                                 "value": d.get("value") or d.get("attribute_value")}
                                for d in defs]
        return out

    def write_stats(self):
        return {"dry_run": self.dry_run,
                "writes_planned": len(self.planned),
                "writes_sent": len(self.sent),
                **self.stats()}
