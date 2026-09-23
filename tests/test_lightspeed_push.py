#!/usr/bin/env python3
"""Drive scripts/lightspeed_push.py main() end to end against a stub writer.

    python3 -m unittest discover -s tests -v

Nothing here talks to Lightspeed. The stub records what would have been sent and
can be told to fail on a given family, which is the case that used to lose UUIDs:
the backfill file was written only after the whole batch, so a failure on family
two dropped everything family one had already created (found 2026-09-23 while
reviewing the pipeline; the overwrite half of the same bug lost ACC-OAKL-0001 on
2026-09-11).
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lsc = _load("lightspeed_client", "scripts/lightspeed_client.py")
lpush = _load("lightspeed_push", "scripts/lightspeed_push.py")

CFG = {"outlet": {"id": "outlet-1", "default_tax_id": "tax-1"}}


class StubWriter:
    """Stands in for LightspeedWriter. Mints `uuid-<sku>` for every create."""

    fail_on_family = None
    instances = []

    def __init__(self, config=None, dry_run=False, verbose=False):
        self.dry_run = dry_run
        self.created = []
        self.updated = []
        StubWriter.instances.append(self)

    def get(self, path):
        return {"data": []}

    def update_variant(self, product_id, details):
        self.updated.append(product_id)

    def create_family(self, payload):
        if payload["name"] == self.fail_on_family:
            raise lsc.LightspeedError(f"stubbed failure on {payload['name']}")
        skus = [payload["sku"]] if "sku" in payload else [v["sku"] for v in payload["variants"]]
        self.created.extend(skus)
        self._last = skus
        return [f"uuid-{skus[0]}"]

    def family_by_sku(self, product_id):
        return {s: {"id": f"uuid-{s}"} for s in self._last}

    def write_stats(self):
        return {"created": len(self.created), "updated": len(self.updated)}


def create(sku, family, seq):
    return {"id": f"cat-{sku}", "target_system": "lightspeed", "op": "create",
            "sku": sku, "seq": seq, "fields": {"name": family, "sku": sku,
                                                "supply_price": 1.0,
                                                "price_excluding_tax": 2.0}}


class PushCase(unittest.TestCase):

    def setUp(self):
        StubWriter.fail_on_family = None
        StubWriter.instances = []
        self.tmp = Path(tempfile.mkdtemp())
        self.plan_path = self.tmp / "catalog-plan-test.json"
        self.approval_path = self.tmp / "catalog-approval-test.json"
        self.backfill_path = self.tmp / "catalog-backfill-test.json"
        self.log_path = self.tmp / "actions-log.json"
        self.actions = [create("A-1", "Family A", 1), create("B-1", "Family B", 2)]
        self.plan_path.write_text(json.dumps({"supplier": "TEST", "actions": self.actions}))
        self.approval_path.write_text(json.dumps({
            "plan": str(self.plan_path), "approved_by": "policy: test",
            "decisions": [{"id": a["id"], "status": "approved"} for a in self.actions]}))

    def run_push(self, *extra):
        argv = ["lightspeed_push.py", "--plan", str(self.plan_path),
                "--approval", str(self.approval_path),
                "--actions-log", str(self.log_path), *extra]
        with mock.patch.object(lpush, "LightspeedWriter", StubWriter), \
             mock.patch.object(lpush, "load_config", lambda: CFG), \
             mock.patch.object(sys, "argv", argv), \
             mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            return lpush.main()

    def backfill(self):
        return json.loads(self.backfill_path.read_text())["sku_to_lightspeed_id"]

    def log_entries(self):
        return json.loads(self.log_path.read_text())["entries"]


class TestBackfillSurvivesAFailure(PushCase):

    def test_first_family_uuid_is_saved_when_the_second_family_fails(self):
        StubWriter.fail_on_family = "Family B"
        self.assertEqual(1, self.run_push())
        self.assertEqual({"A-1": "uuid-A-1"}, self.backfill())

    def test_the_failure_is_logged_as_a_create_naming_the_family(self):
        StubWriter.fail_on_family = "Family B"
        self.run_push()
        failed = [e for e in self.log_entries() if e["result"] == "failed"]
        self.assertEqual(1, len(failed))
        self.assertEqual("lightspeed_create_product", failed[0]["type"])
        self.assertIn("Family B", failed[0]["target"])

    def test_a_resume_completes_the_file_instead_of_replacing_it(self):
        StubWriter.fail_on_family = "Family B"
        self.run_push()
        StubWriter.fail_on_family = None
        self.assertEqual(0, self.run_push())
        self.assertEqual({"A-1": "uuid-A-1", "B-1": "uuid-B-1"}, self.backfill())
        self.assertEqual(["B-1"], StubWriter.instances[-1].created,
                         "the resume must not create A-1 a second time")


class TestBackfillIsRebuiltFromTheLog(PushCase):

    def test_a_lost_file_is_rebuilt_when_everything_already_ran(self):
        self.run_push()
        self.backfill_path.unlink()
        self.assertEqual(0, self.run_push())
        self.assertEqual({"A-1": "uuid-A-1", "B-1": "uuid-B-1"}, self.backfill())

    def test_existing_pairs_from_another_run_are_kept(self):
        self.backfill_path.write_text(json.dumps(
            {"sku_to_lightspeed_id": {"OLD-1": "uuid-old"}}))
        self.run_push()
        self.assertEqual({"OLD-1": "uuid-old", "A-1": "uuid-A-1", "B-1": "uuid-B-1"},
                         self.backfill())


class TestDryRunWritesNothing(PushCase):

    def test_no_backfill_and_no_log(self):
        self.assertEqual(0, self.run_push("--dry-run"))
        self.assertFalse(self.backfill_path.exists())
        self.assertFalse(self.log_path.exists())


class TestApprovalIsTheGate(PushCase):

    def test_an_unapproved_create_is_not_sent(self):
        self.approval_path.write_text(json.dumps({
            "plan": str(self.plan_path), "approved_by": "policy: test",
            "decisions": [{"id": "cat-A-1", "status": "approved"}]}))
        self.run_push()
        self.assertEqual(["A-1"], StubWriter.instances[-1].created)

    def test_an_approval_for_another_plan_is_refused(self):
        self.approval_path.write_text(json.dumps({
            "plan": "plans/x/catalog-plan-other.json", "approved_by": "policy: test",
            "decisions": [{"id": a["id"], "status": "approved"} for a in self.actions]}))
        with self.assertRaises(SystemExit):
            self.run_push()


if __name__ == "__main__":
    unittest.main()
