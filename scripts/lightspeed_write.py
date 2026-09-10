#!/usr/bin/env python3
"""Lightspeed (X-Series) write transport. THIS MODULE CHANGES THE LIVE POS.

Separate from scripts/lightspeed_client.py on purpose. The read path — the daily
catalogue pull — stays reviewable on its own, and anyone scanning the repo can tell
which scripts are capable of changing the store: exactly this one and its caller,
scripts/lightspeed_push.py.

What it can do, and nothing more:

    create_family(payload)          POST /api/2.0/products
    update_variant(id, details)     PUT  /api/2.1/products/{id}
    read_family(id)                 GET  /api/3.0/products/{id}

There is no delete and no deactivate, deliberately and permanently. Removing a
product from a live POS is a human decision made in the Lightspeed UI; nothing in
this pipeline may do it, so the capability simply does not exist here.

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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lightspeed_client import LightspeedClient, LightspeedError  # noqa: E402

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


class LightspeedWriter(LightspeedClient):
    """Adds create and update to the read-only client. No delete, ever."""

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
        for variant in payload.get("variants") or []:
            if not variant.get("sku"):
                raise LightspeedError(
                    "every variant needs an explicit sku. Lightspeed mints one from its own "
                    "sequence when omitted, and RULE 0 makes the Airtable SKU the source of "
                    "truth — a generated sku would orphan the row.")
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
            payload["details"] = details
        if common:
            payload["common"] = common
        path = self.cfg["api"]["endpoints"]["product_update"].format(id=product_id)
        body = self._send("PUT", path, body=payload)
        return None if body.get("dry_run") else body

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
        """
        data = self.read_family(product_id)
        out = {}
        for v in (data.get("variants") or []):
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
