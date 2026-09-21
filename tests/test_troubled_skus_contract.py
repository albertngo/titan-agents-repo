#!/usr/bin/env python3
"""Structural tests for the troubled-SKUs contract and its `Action` column.

Stdlib unittest, no pytest -- matching the repo's convention.

    python3 -m unittest discover -s tests -v

No script writes the troubled CSV. It is written by a model following
`contracts/troubled-skus-schema.md`, which means the only thing standing between
the contract and a run that quietly drops a column is prose agreeing with prose.
These tests are that check.

`Action` is the column worth guarding. It is the one a person fills in, it is
carried across an overwrite that regenerates every other column, and both failure
modes are silent: a run that omits it leaves the reviewer nowhere to answer, and a
run that regenerates it destroys an answer already given. Neither shows up as an
error anywhere -- the next run just proceeds as though nobody had said anything.

Same job tests/test_content_folder_registry.py does for the content registry: the
expensive mistake has never been a broken file, it has been a correct-looking
document describing a behaviour nothing implements any more.
"""

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT = REPO_ROOT / "contracts" / "troubled-skus-schema.md"
ACTIONS_LOG = REPO_ROOT / "contracts" / "actions-log-schema.md"
REGISTRY = REPO_ROOT / "platform-settings" / "pricelist-sources.json"
CATALOG_SYNC = REPO_ROOT / ".claude" / "commands" / "catalog-sync.md"
PROCESS_PRICE_LIST = REPO_ROOT / ".claude" / "commands" / "process-price-list.md"

# The canonical CSV header, in order. A run writes exactly these, and `Action`
# is last because it is appended by the reviewer's eye, not by the extractor.
EXPECTED_COLUMNS = [
    "supplier",
    "sku",
    "product_name",
    "stage",
    "reason",
    "disposition",
    "detail",
    "action_id",
    "source_row",
    "col_printed",
    "value_used",
    "Action",
]


def _columns_table(markdown: str) -> list:
    """Return the first column of the contract's `## Columns` table, in order."""
    body = markdown.split("## Columns", 1)[1].split("\n## ", 1)[0]
    names = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        first = line.split("|")[1].strip()
        if first.startswith("---") or first == "Column":
            continue
        match = re.match(r"`([^`]+)`", first)
        if match:
            names.append(match.group(1))
    return names


class TroubledSkusContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = CONTRACT.read_text()
        cls.actions_log = ACTIONS_LOG.read_text()
        cls.registry = json.loads(REGISTRY.read_text())
        cls.catalog_sync = CATALOG_SYNC.read_text()
        cls.process_price_list = PROCESS_PRICE_LIST.read_text()

    def test_columns_are_the_canonical_twelve_in_order(self):
        self.assertEqual(EXPECTED_COLUMNS, _columns_table(self.contract))

    def test_action_is_the_last_column(self):
        # Appending anywhere else shifts every downstream column in a file whose
        # reader is a spreadsheet, which fails as garbled data rather than as an error.
        self.assertEqual("Action", _columns_table(self.contract)[-1])

    def test_contract_forbids_a_run_writing_into_action(self):
        section = self.contract.split("## The `Action` column", 1)[1]
        self.assertIn("never writes into an `Action` cell", section)
        self.assertIn("never clears one", section)

    def test_contract_states_an_action_is_not_an_approval(self):
        # The invariant that lets this pipeline run unattended: an actions agent
        # executes an id that is `approved` in the approval file, and nothing else.
        # A free-text cell on a Notion page must never be able to satisfy that.
        section = self.contract.split("## The `Action` column", 1)[1]
        self.assertIn("prose is not an approval", section)
        self.assertIn("catalog-approval-", section)

    def test_contract_keeps_the_pricing_carve_outs_out_of_reach(self):
        section = self.contract.split("## The `Action` column", 1)[1]
        self.assertIn("ambiguous_pricing", section)
        self.assertIn("bert-airtable-schema", section)

    def test_contract_defines_the_carry_forward_match_key(self):
        section = self.contract.split("### Carrying answers forward", 1)[1]
        self.assertIn("`sku`", section)
        self.assertIn("`source_row`", section)
        # Zero or many matches must refuse, never guess.
        self.assertIn("carry nothing", section)

    def test_catalog_sync_reads_the_answers_before_it_plans(self):
        # Step 0, not step 6: reading after the plan is built means either
        # re-deriving the plan or ignoring the answer.
        self.assertIn("## 0. Read back the reviewer's answers", self.catalog_sync)
        self.assertLess(
            self.catalog_sync.index("## 0. Read back the reviewer's answers"),
            self.catalog_sync.index("## 1. Pull the live Lightspeed catalogue"),
        )

    def test_catalog_sync_carries_the_column_forward_when_it_rewrites_the_file(self):
        section = self.catalog_sync.split("## 6a.", 1)[1]
        self.assertIn("Always emit the `Action` column", section)
        self.assertIn("Carry forward every `Action` value", section)
        self.assertIn("notion_write_troubled_table", section)

    def test_process_price_list_emits_the_column_too(self):
        # Stage 1 opens the file, so it is where the column has to first exist.
        section = self.process_price_list.split("### 5a.", 1)[1]
        self.assertIn("Always emit the `Action` column", section)

    def test_page_table_write_is_a_logged_action_type(self):
        self.assertIn("`notion_write_troubled_table`", self.actions_log)

    def test_registry_records_twelve_columns(self):
        note = self.registry["outputs"]["_troubled_action_column"]
        self.assertIn("12 columns", note)
        self.assertIn("Action", note)

    def test_registry_still_names_the_troubled_output(self):
        self.assertEqual(
            "{supplier_slug}_troubled_{date}.csv",
            self.registry["outputs"]["troubled"],
        )
        self.assertEqual(
            "Troubled Files",
            self.registry["price_lists"]["write_properties"]["troubled_files"],
        )


if __name__ == "__main__":
    unittest.main()
