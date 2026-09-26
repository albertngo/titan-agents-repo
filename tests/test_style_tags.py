#!/usr/bin/env python3
"""Tests for the /style-tag pipeline: the pull, the plan, the policy, and the prose.

    python3 -m unittest discover -s tests -v

Stdlib unittest, no pytest, fixtures inline — matching the repo's convention.

The cases Albert named when he asked for the flow (2026-09-26): contract validation;
never overwrites a non-blank field or a Staff confirmed record; a spec-vs-image
conflict is held; a spec-only record fills Texture and Busyness but holds the colour
tags. Plus the ones his same-day image-field rule added: a room scene never reaches
Undertone or Tone depth at any confidence, a detail close-up informs Texture and
nothing else, and a swatch the model says is not a swatch is reported, not read.

The prose guards at the end do for the style contracts what
tests/test_troubled_skus_contract.py does for the price-list one: the expensive
failure is a correct-looking document describing a behaviour nothing implements.
"""

import copy
import csv
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pull = _load("style_tag_pull")
plan = _load("style_tag_plan")

REGISTRY_PATH = REPO_ROOT / "platform-settings" / "style-tags.json"
REG = json.loads(REGISTRY_PATH.read_text())
FIELD_MAP = json.loads((REPO_ROOT / "platform-settings" / "airtable-master-catalogue-fields.json").read_text())
TARGETS = [t for t in REG["targets"] if not t.startswith("_")]

# Live options as read 2026-09-26 (get_table_schema), the shape the pre-flight consumes.
LIVE_OPTIONS = {"tables": [{"tableId": REG["table_id"], "fields": [
    {"id": REG["targets"][name]["id"], "type": "singleSelect",
     "config": {"choices": [{"id": f"sel{i}", "name": o} for i, o in enumerate(REG["targets"][name]["options"])]}}
    for name in TARGETS if "options" in REG["targets"][name]
] + [
    {"id": REG["status_field"]["id"], "type": "singleSelect",
     "config": {"choices": [{"id": "selA", "name": "AI suggested"}, {"id": "selS", "name": "Staff confirmed"}]}},
    {"id": REG["targets"]["Tone depth"]["id"], "type": "rating", "config": {"max": 5}},
]}]}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def image(kind, att="att1", filename="swatch.jpg", status="downloaded"):
    return {"field": kind, "field_name": REG["image_fields"][f"{kind}_images" if kind != "room" else "room_scene_images"]["name"],
            "attachment_id": att, "filename": filename, "type": "image/jpeg", "size": 1000,
            "width": 2000, "height": 1500, "path": f"/tmp/{att}", "read_path": f"/tmp/{att}-read.jpg",
            "status": status}


def cand(sku="ENG-TEST-0001", finish=None, grade=None, species=None, colour_tone=None,
         name="Test Oak", collection="", images=(), status=None, blanks=None):
    return {"record_id": "rec" + sku[-4:], "sku": sku, "product_name": name, "supplier": "TEST",
            "category": "Engineered hardwood", "status": status, "evidence_existing": "",
            "specs": {"Finish type": finish, "Grade": grade, "Species": species,
                      "Colour / tone": colour_tone, "Collection": collection,
                      "Product name": name, "Salesperson notes": None},
            "blank_fields": list(blanks) if blanks is not None else list(TARGETS),
            "images": list(images)}


def doc(*cands, images_status="none"):
    return {"contract_version": "style-candidates-1", "scope": "test", "supplier": "TEST",
            "images": {"status": images_status}, "candidates": list(cands)}


def judgement(sku="ENG-TEST-0001", images=(), **obs):
    j = {"sku": sku, "images": list(images)}
    j.update(obs)
    return {"contract_version": "style-judgements-1", "records": [j]}


def jimg(att="att1", looks_like="swatch", usable=True):
    return {"attachment_id": att, "looks_like": looks_like, "usable_for_colour": usable, "note": ""}


def obs(value, confidence, src="att1", evidence="seen"):
    return {"value": value, "confidence": confidence, "from": src, "evidence": evidence}


def build(candidates, judgements=None, answers=None, reg=REG):
    return plan.build_plan(candidates, judgements, answers, reg, "test", "plans/2026-09-26/style-plan-test.json")


def only_action(p):
    return p["actions"][0] if p["actions"] else None


def held_for(p, field, sku="ENG-TEST-0001"):
    return [r for r in p["held"] if r["field"] == field and r["sku"] == sku]


# ---------------------------------------------------------------------------
# 1. contract
# ---------------------------------------------------------------------------

class TestContract(unittest.TestCase):
    def test_envelope_and_tag_shape(self):
        p = build(doc(cand(finish="Wire brushed", grade="Character")))
        for key in ("contract_version", "scope", "supplier", "run_at", "write_mode", "approved_by",
                    "inputs", "summary", "actions", "held", "flagged"):
            self.assertIn(key, p)
        self.assertEqual(p["contract_version"], "style-plan-1")
        a = only_action(p)
        self.assertEqual((a["target_system"], a["op"]), ("airtable", "update_style_tags"))
        for tag in a["tags"].values():
            for key in ("value", "confidence", "source", "evidence"):
                self.assertIn(key, tag)
            self.assertIn(tag["source"], {"spec", "image", "both", "reviewer"})
        self.assertRegex(a["id"], r"^sty-[0-9a-f]{12}$")
        self.assertEqual(a["seq"], 1)

    def test_ids_are_stable_and_change_with_the_field_set(self):
        a = only_action(build(doc(cand(finish="Wire brushed", grade="Character"))))
        b = only_action(build(doc(cand(finish="Wire brushed", grade="Character"))))
        self.assertEqual(a["id"], b["id"])
        c = only_action(build(doc(cand(finish="Wire brushed"))))
        self.assertNotEqual(a["id"], c["id"])
        self.assertEqual(plan.action_id("X", ["Texture", "Busyness"]), plan.action_id("X", ["Busyness", "Texture"]))

    def test_held_rows_carry_no_id(self):
        p = build(doc(cand(finish="Wire brushed")))
        self.assertTrue(p["held"])
        for row in p["held"]:
            self.assertNotIn("id", row)
            self.assertEqual(row["action_id"], "")
            self.assertIn(row["reason"], REG["held_reasons"])


# ---------------------------------------------------------------------------
# 2-3. never overwrite, never touch Staff confirmed
# ---------------------------------------------------------------------------

def record(sku="ENG-TEST-0001", active=True, category="Engineered hardwood", status=None,
           finish=None, grade=None, undertone=None, tone_depth=None, swatches=(), rooms=(), details=()):
    ids = REG["inputs"]
    cells = {ids["SKU"]: sku, ids["Active"]: active,
             ids["Product name"]: "Test Oak", ids["Supplier"]: {"id": "s", "name": "TEST", "color": "x"}}
    if category:
        cells[ids["Category"]] = {"id": "c", "name": category, "color": "x"}
    if finish:
        cells[ids["Finish type"]] = {"id": "f", "name": finish, "color": "x"}
    if grade:
        cells[ids["Grade"]] = {"id": "g", "name": grade, "color": "x"}
    if status:
        cells[REG["status_field"]["id"]] = {"id": "st", "name": status, "color": "x"}
    if undertone:
        cells[REG["targets"]["Undertone"]["id"]] = {"id": "u", "name": undertone, "color": "x"}
    if tone_depth is not None:
        cells[REG["targets"]["Tone depth"]["id"]] = tone_depth
    for key, atts in (("swatch_images", swatches), ("room_scene_images", rooms), ("detail_images", details)):
        if atts:
            cells[ids[key]] = [{"id": a, "url": f"https://v5.airtableusercontent.com/{a}", "filename": f"{a}.jpg",
                                "type": "image/jpeg", "size": 10, "width": 2000, "height": 1500} for a in atts]
    return {"id": "rec" + sku[-4:], "cellValuesByFieldId": cells}


class TestBlankOnlyAndStaffConfirmed(unittest.TestCase):
    def test_a_filled_field_is_never_planned(self):
        recs = pull.load_snapshot([self._save([record(undertone="Cool", finish="Wire brushed", swatches=("att1",))])], REG)
        c, why = pull.candidate_from(recs[0], REG)
        self.assertIsNone(why)
        self.assertNotIn("Undertone", c["blank_fields"])
        c["images"][0]["status"] = "downloaded"
        p = build(doc(c), judgement(images=[jimg()], undertone=obs("Warm", 0.95)))
        a = only_action(p)
        self.assertNotIn("Undertone", (a or {}).get("fields", {}))

    def test_a_set_rating_is_not_blank_but_zero_is(self):
        recs = pull.load_snapshot([self._save([record(sku="ENG-TEST-0002", tone_depth=3, finish="Wire brushed"),
                                               record(sku="ENG-TEST-0003", tone_depth=0, finish="Wire brushed")])], REG)
        c2, _ = pull.candidate_from(recs[0], REG)
        c3, _ = pull.candidate_from(recs[1], REG)
        self.assertNotIn("Tone depth", c2["blank_fields"])
        self.assertIn("Tone depth", c3["blank_fields"])

    def test_staff_confirmed_is_excluded_even_with_everything_blank(self):
        recs = pull.load_snapshot([self._save([record(status="Staff confirmed", finish="Wire brushed",
                                                      grade="Character", swatches=("att1",))])], REG)
        c, why = pull.candidate_from(recs[0], REG)
        self.assertIsNone(c)
        self.assertEqual(why, "staff_confirmed")

    def test_ai_suggested_record_with_a_remaining_blank_is_a_candidate_and_keeps_its_status(self):
        recs = pull.load_snapshot([self._save([record(status="AI suggested", finish="Wire brushed")])], REG)
        c, why = pull.candidate_from(recs[0], REG)
        self.assertIsNone(why)
        a = only_action(build(doc(c)))
        self.assertIsNone(a["status_write"])  # already AI suggested: leave it

    def test_ineligible_records(self):
        for kw, why in (({"active": False}, "inactive"), ({"category": "Tile / Stone"}, "category"),
                        ({"category": None}, "category")):
            recs = pull.load_snapshot([self._save([record(finish="Wire brushed", **kw)])], REG)
            self.assertEqual(pull.candidate_from(recs[0], REG), (None, why), kw)
        recs = pull.load_snapshot([self._save([record()])], REG)
        self.assertEqual(pull.candidate_from(recs[0], REG)[1], "no_signal")

    def _save(self, records):
        fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"records": records, "metadata": {"totalRecordCount": len(records)}}, fh)
        fh.close()
        return fh.name


# ---------------------------------------------------------------------------
# 4. conflict
# ---------------------------------------------------------------------------

class TestConflict(unittest.TestCase):
    def test_spec_vs_detail_image_conflict_holds_texture(self):
        c = cand(finish="Wire brushed", grade="Character", images=[image("detail", "d1", "closeup.jpg")])
        p = build(doc(c, images_status="downloaded"),
                  judgement(images=[jimg("d1", "detail")], texture_seen=obs("Smooth", 0.8, "d1")))
        rows = held_for(p, "Texture")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "spec_image_conflict")
        self.assertEqual(rows[0]["proposed"], "Brushed|Smooth")
        self.assertNotIn("Texture", only_action(p)["fields"])
        self.assertIn("Busyness", only_action(p)["fields"])  # the rest of the record still writes

    def test_agreement_raises_confidence_and_sources_both(self):
        c = cand(finish="Wire brushed", images=[image("detail", "d1", "closeup.jpg")])
        p = build(doc(c, images_status="downloaded"),
                  judgement(images=[jimg("d1", "detail")], texture_seen=obs("Brushed", 0.8, "d1")))
        tag = only_action(p)["tags"]["Texture"]
        self.assertEqual((tag["value"], tag["source"]), ("Brushed", "both"))
        self.assertAlmostEqual(tag["confidence"], 0.95)

    def test_busyness_image_only_conflict_checks(self):
        c = cand(grade="Select", images=[image("swatch", "att1")])
        p = build(doc(c, images_status="downloaded"),
                  judgement(images=[jimg()], busyness_seen=obs("Busy", 0.9)))
        self.assertEqual(held_for(p, "Busyness")[0]["reason"], "spec_image_conflict")
        c = cand(images=[image("swatch", "att1")])  # no grade: the image cannot decide alone
        p = build(doc(c, images_status="downloaded"),
                  judgement(images=[jimg()], busyness_seen=obs("Busy", 0.9)))
        self.assertEqual(held_for(p, "Busyness")[0]["reason"], "spec_unmapped")
        self.assertEqual(held_for(p, "Busyness")[0]["proposed"], "Busy")


# ---------------------------------------------------------------------------
# 5. spec-only
# ---------------------------------------------------------------------------

class TestSpecOnly(unittest.TestCase):
    def test_fills_texture_and_busyness_holds_colour(self):
        p = build(doc(cand(finish="Wire brushed", grade="Character")))
        a = only_action(p)
        self.assertEqual(a["fields"], {"Texture": "Brushed", "Busyness": "Moderate"})
        self.assertEqual(a["status_write"], "AI suggested")
        for field in ("Undertone", "Tone depth"):
            rows = held_for(p, field)
            self.assertEqual(len(rows), 1, field)
            self.assertEqual(rows[0]["reason"], "no_swatch")
        self.assertEqual(held_for(p, "Style"), [])  # nothing proposed, nothing to report
        self.assertEqual(p["summary"]["no_information"], {"Style": 1})

    def test_style_from_specs_alone_is_held_needs_image(self):
        p = build(doc(cand(finish="Wire brushed", grade="Select")),
                  judgement(style={"values": ["Modern", "Scandinavian"], "confidence": 0.9, "evidence": "light oak"}))
        rows = held_for(p, "Style")
        self.assertEqual(rows[0]["reason"], "needs_image")
        self.assertEqual(rows[0]["proposed"], ["Modern", "Scandinavian"])
        self.assertLessEqual(rows[0]["confidence"], REG["policy"]["spec_only_style_cap"])

    def test_finish_normalisation_and_provisional(self):
        for finish, texture in (("Wire Brushed; UV Oil", "Brushed"), ("Light Wirebrushed UV Lacquered", "Brushed"),
                                ("Smoked & Wirebrushed", "Brushed"), ("Hand Scraped & Distressed", "Rustic"),
                                ("Matte UV Bona", "Smooth"), ("Semi-Gloss", "Smooth")):
            self.assertEqual(plan.texture_from_finish(finish, REG)["value"], texture, finish)
        eir = plan.texture_from_finish("Matte EIR", REG)
        self.assertTrue(eir["provisional"])
        p = build(doc(cand(finish="Matte EIR")))
        self.assertEqual(held_for(p, "Texture")[0]["reason"], "low_confidence")
        self.assertIsNone(plan.texture_from_finish("Reactive colour", REG))
        p = build(doc(cand(finish="Reactive colour")))
        self.assertEqual(held_for(p, "Texture")[0]["reason"], "spec_unmapped")

    def test_busyness_grade_map_and_modifiers(self):
        self.assertEqual(plan.busyness_from_specs({"Grade": "ABCD"}, REG)["value"], "Moderate")
        self.assertEqual(plan.busyness_from_specs({"Grade": "Select & Better"}, REG)["value"], "Calm")
        b = plan.busyness_from_specs({"Grade": "Select", "Finish type": "Smoked & Wirebrushed"}, REG)
        self.assertEqual(b["value"], "Moderate")
        b = plan.busyness_from_specs({"Grade": "Rustic", "Finish type": "Hand scraped"}, REG)
        self.assertEqual(b["value"], "Busy")  # capped at the top of the ladder
        self.assertIsNone(plan.busyness_from_specs({"Grade": "Grade"}, REG))  # the placeholder option
        p = build(doc(cand(grade="BCDE")))
        self.assertEqual(only_action(p)["fields"]["Busyness"], "Busy")
        self.assertEqual(p["flagged"][0]["reason"], "spec_rule_provisional")
        self.assertEqual(p["flagged"][0]["action_id"], only_action(p)["id"])


# ---------------------------------------------------------------------------
# 6. threshold
# ---------------------------------------------------------------------------

class TestThreshold(unittest.TestCase):
    def _colour(self, confidence):
        c = cand(images=[image("swatch", "att1")])
        return build(doc(c, images_status="downloaded"),
                     judgement(images=[jimg()], undertone=obs("Warm", confidence)))

    def test_boundary(self):
        self.assertEqual(only_action(self._colour(0.7))["fields"]["Undertone"], "Warm")
        p = self._colour(0.699)
        self.assertIsNone(only_action(p))
        row = held_for(p, "Undertone")[0]
        self.assertEqual((row["reason"], row["proposed"]), ("low_confidence", "Warm"))

    def test_hint_agreement_lifts_and_disagreement_only_notes(self):
        c = cand(name="Test Oak — Honey Gold", images=[image("swatch", "att1")])
        p = build(doc(c, images_status="downloaded"), judgement(images=[jimg()], undertone=obs("Warm", 0.65)))
        tag = only_action(p)["tags"]["Undertone"]
        self.assertEqual(tag["source"], "both")
        self.assertAlmostEqual(tag["confidence"], 0.75)
        p = build(doc(c, images_status="downloaded"), judgement(images=[jimg()], undertone=obs("Cool", 0.8)))
        tag = only_action(p)["tags"]["Undertone"]
        self.assertEqual((tag["value"], tag["source"]), ("Cool", "image"))  # no conflict from a hint
        self.assertIn("differs", tag["evidence"])

    def test_hint_never_writes_alone(self):
        p = build(doc(cand(name="Espresso Oak", colour_tone="Dark")))
        row = held_for(p, "Tone depth")[0]
        self.assertEqual(row["reason"], "no_swatch")
        self.assertEqual(row["proposed"], 4)
        self.assertIsNone(only_action(p))


# ---------------------------------------------------------------------------
# 7. image sources — the field decides
# ---------------------------------------------------------------------------

class TestImageSources(unittest.TestCase):
    def test_room_scene_never_reaches_colour_but_informs_style(self):
        c = cand(images=[image("room", "r1", "living.jpg")])
        p = build(doc(c, images_status="downloaded"),
                  judgement(images=[jimg("r1", "room")], undertone=obs("Warm", 0.95, "r1"),
                            tone_depth=obs(3, 0.95, "r1"),
                            style={"values": ["Modern"], "confidence": 0.8, "evidence": "clean lines"}))
        for field in ("Undertone", "Tone depth"):
            self.assertEqual(held_for(p, field)[0]["reason"], "no_swatch", field)
        self.assertEqual(only_action(p)["fields"], {"Style": ["Modern"]})

    def test_detail_image_informs_texture_and_nothing_else(self):
        c = cand(finish="Wire brushed", images=[image("detail", "d1", "closeup.jpg")])
        p = build(doc(c, images_status="downloaded"),
                  judgement(images=[jimg("d1", "detail")], texture_seen=obs("Brushed", 0.8, "d1"),
                            undertone=obs("Warm", 0.95, "d1"),
                            style={"values": ["Modern"], "confidence": 0.9, "evidence": "x"}))
        a = only_action(p)
        self.assertEqual(a["tags"]["Texture"]["source"], "both")
        self.assertEqual(held_for(p, "Undertone")[0]["reason"], "no_swatch")
        self.assertEqual(held_for(p, "Style")[0]["reason"], "needs_image")

    def test_misfiled_swatch_is_reported_and_not_read(self):
        c = cand(images=[image("swatch", "att1", "kitchen.jpg")])
        p = build(doc(c, images_status="downloaded"),
                  judgement(images=[jimg("att1", "room")], undertone=obs("Warm", 0.95)))
        self.assertEqual(held_for(p, "Undertone")[0]["reason"], "no_swatch")
        mis = [r for r in p["held"] if r["reason"] == "image_misfiled"]
        self.assertEqual(len(mis), 1)
        self.assertEqual(mis[0]["field"], "Swatch images")
        self.assertIn("kitchen.jpg", mis[0]["detail"])
        self.assertIsNone(only_action(p))

    def test_swatch_writes_colour(self):
        c = cand(images=[image("swatch", "att1", "sw.jpg")])
        p = build(doc(c, images_status="downloaded"),
                  judgement(images=[jimg()], undertone=obs("Warm", 0.85), tone_depth=obs(3, 0.8)))
        self.assertEqual(only_action(p)["fields"], {"Undertone": "Warm", "Tone depth": 3})

    def test_tone_depth_must_be_an_int_in_range(self):
        c = cand(images=[image("swatch", "att1")])
        p = build(doc(c, images_status="downloaded"), judgement(images=[jimg()], tone_depth=obs(7, 0.9)))
        self.assertEqual(held_for(p, "Tone depth")[0]["reason"], "low_confidence")
        self.assertIsNone(plan.canonical_option("Tone depth", "x", REG))
        self.assertEqual(plan.canonical_option("Undertone", " warm ", REG), "Warm")


# ---------------------------------------------------------------------------
# 8. host blocked, 9. all held
# ---------------------------------------------------------------------------

class TestEnvironmentHolds(unittest.TestCase):
    def test_host_blocked_holds_colour_and_writes_spec(self):
        c = cand(finish="Wire brushed", grade="Select", images=[image("swatch", "att1", status="host_blocked")])
        p = build(doc(c, images_status="host_blocked"))
        self.assertEqual(only_action(p)["fields"], {"Texture": "Brushed", "Busyness": "Calm"})
        self.assertEqual(held_for(p, "Undertone")[0]["reason"], "image_host_blocked")

    def test_heic_only_holds_format(self):
        c = cand(images=[image("swatch", "att1", "IMG.HEIC", status="unsupported_format")])
        p = build(doc(c, images_status="partial"))
        self.assertEqual(held_for(p, "Undertone")[0]["reason"], "image_format_unsupported")

    def test_all_held_means_no_write_at_all(self):
        p = build(doc(cand(name="Test Oak")))  # no specs, no images: only colour rows
        self.assertEqual(p["actions"], [])
        self.assertEqual(p["summary"]["actions_total"], 0)
        self.assertTrue(all(r["reason"] == "no_swatch" for r in p["held"]))


# ---------------------------------------------------------------------------
# 10. answers
# ---------------------------------------------------------------------------

class TestAnswers(unittest.TestCase):
    def test_field_value_answer_writes_as_reviewer(self):
        p = build(doc(cand()), None, [{"sku": "ENG-TEST-0001", "field": "Undertone", "action": "Undertone: warm"}])
        tag = only_action(p)["tags"]["Undertone"]
        self.assertEqual((tag["value"], tag["source"], tag["confidence"]), ("Warm", "reviewer", 1.0))
        self.assertEqual(p["summary"]["answers_applied"], 1)

    def test_several_answers_in_one_cell(self):
        p = build(doc(cand()), None, [{"sku": "ENG-TEST-0001", "field": "Undertone",
                                       "action": "Undertone: Warm; Tone depth: 3"}])
        self.assertEqual(only_action(p)["fields"], {"Undertone": "Warm", "Tone depth": 3})

    def test_bare_value_unambiguous_ok_ambiguous_unparsed(self):
        p = build(doc(cand()), None, [{"sku": "ENG-TEST-0001", "field": "Undertone", "action": "Cool"}])
        self.assertEqual(only_action(p)["fields"], {"Undertone": "Cool"})
        p = build(doc(cand()), None, [{"sku": "ENG-TEST-0001", "field": "Texture", "action": "Rustic"}])
        row = held_for(p, "Texture")[0]
        self.assertEqual(row["reason"], "answer_unparsed")
        self.assertIn("several fields", row["detail"])

    def test_skip_and_garbage(self):
        p = build(doc(cand()), None, [{"sku": "ENG-TEST-0001", "field": "Undertone", "action": "skip"},
                                      {"sku": "ENG-TEST-0001", "field": "Tone depth", "action": "yes go ahead"}])
        self.assertEqual(held_for(p, "Undertone")[0]["reason"], "reviewer_skipped")
        self.assertEqual(held_for(p, "Tone depth")[0]["reason"], "answer_unparsed")
        self.assertIsNone(only_action(p))

    def test_answer_for_a_filled_field_is_reported_not_applied(self):
        c = cand(blanks=["Texture", "Busyness", "Style", "Tone depth"])  # Undertone already set
        p = build(doc(c), None, [{"sku": "ENG-TEST-0001", "field": "Undertone", "action": "Undertone: Warm"}])
        self.assertIsNone(only_action(p))
        self.assertEqual(p["summary"]["answers_unmatched"], ["ENG-TEST-0001/Undertone"])

    def test_action_column_is_carried_forward_by_sku_and_field(self):
        p = build(doc(cand(finish="Wire brushed")))
        prior = [{"sku": "ENG-TEST-0001", "field": "Undertone", "action": "will photograph Monday"},
                 {"sku": "ENG-TEST-9999", "field": "Undertone", "action": "gone"}]
        rows = plan.troubled_rows(p, prior)
        by_field = {r["field"]: r for r in rows}
        self.assertEqual(by_field["Undertone"]["Action"], "will photograph Monday")
        self.assertEqual(by_field["Tone depth"]["Action"], "")
        self.assertEqual(list(rows[0].keys()), REG["troubled_columns"])
        self.assertEqual(rows[0]["disposition"], "held")


# ---------------------------------------------------------------------------
# 11. evidence, approval, troubled CSV
# ---------------------------------------------------------------------------

class TestOutputs(unittest.TestCase):
    def test_every_written_tag_has_an_evidence_line(self):
        c = cand(finish="Wire brushed", grade="Character", images=[image("swatch", "att1", "sw.jpg")])
        p = build(doc(c, images_status="downloaded"), judgement(images=[jimg()], undertone=obs("Warm", 0.9)))
        a = only_action(p)
        lines = a["evidence_append"].splitlines()
        self.assertTrue(lines[0].startswith("AI suggested "))
        self.assertIn("plans/2026-09-26/style-plan-test.json", lines[0])
        for field, value in a["fields"].items():
            line = next(l for l in lines[1:] if l.startswith(f"{field}: "))
            self.assertIn(str(value), line)
            self.assertRegex(line, r"\(\d\.\d\d, ")
        self.assertIn("image: sw.jpg", a["evidence_append"])

    def test_approval_refused_under_plan_only_and_lists_every_id_under_write(self):
        p = build(doc(cand(finish="Wire brushed", grade="Character")))
        with self.assertRaises(PermissionError):
            plan.approval_for(p, "plans/x.json", REG)
        reg = copy.deepcopy(REG)
        reg["write_mode"]["mode"] = "write"
        approval = plan.approval_for(p, "plans/x.json", reg)
        self.assertEqual(approval["contract_version"], "style-approval-1")
        self.assertEqual([d["id"] for d in approval["decisions"]], [a["id"] for a in p["actions"]])
        self.assertTrue(all(d["status"] == "approved" for d in approval["decisions"]))
        self.assertEqual(approval["approved_by"], REG["policy"]["approved_by"])
        self.assertNotEqual(approval["approved_by"].lower(), "albert")

    def test_troubled_csv_written_only_when_rows_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.csv"
            clean = build(doc(cand(finish="Wire brushed", grade="Character", blanks=["Texture", "Busyness"])))
            self.assertEqual(plan.write_troubled_csv(clean, path, REG), 0)
            self.assertFalse(path.exists())
            p = build(doc(cand(finish="Wire brushed")))
            n = plan.write_troubled_csv(p, path, REG, [{"sku": "ENG-TEST-0001", "field": "Undertone", "action": "a|b"}])
            self.assertGreater(n, 0)
            with open(path, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(list(rows[0].keys()), REG["troubled_columns"])
            self.assertEqual({r["Action"] for r in rows if r["field"] == "Undertone"}, {"a|b"})

    def test_preflight_names_missing_options(self):
        self.assertEqual(plan.check_options(LIVE_OPTIONS, REG), [])
        broken = copy.deepcopy(LIVE_OPTIONS)
        for f in broken["tables"][0]["fields"]:
            if f["id"] == REG["targets"]["Undertone"]["id"]:
                f["config"]["choices"] = [c for c in f["config"]["choices"] if c["name"] != "Warm"]
        missing = plan.check_options(broken, REG)
        self.assertEqual(len(missing), 1)
        self.assertIn("'Warm'", missing[0])


# ---------------------------------------------------------------------------
# pull: manifest and download
# ---------------------------------------------------------------------------

class TestPull(unittest.TestCase):
    def test_manifest_kind_comes_from_the_field(self):
        recs = pull.load_snapshot([_save_records([record(finish="Wire brushed", swatches=("s1",), rooms=("r1",), details=("d1",))])], REG)
        c, _ = pull.candidate_from(recs[0], REG)
        self.assertEqual({i["attachment_id"]: i["field"] for i in c["images"]}, {"s1": "swatch", "r1": "room", "d1": "detail"})
        self.assertTrue(all(i["status"] == "not_downloaded" for i in c["images"]))

    def test_blocked_host_fails_soft_and_urls_are_never_persisted(self):
        recs = pull.load_snapshot([_save_records([record(finish="Wire brushed", swatches=("s1",))])], REG)

        def refuse(url):
            raise OSError("Tunnel connection failed: 403 Forbidden")
        with tempfile.TemporaryDirectory() as tmp:
            out = pull.build(recs, REG, "test", ["snap.json"], download=True, images_dir=tmp, fetcher=refuse)
        self.assertEqual(out["images"]["status"], "host_blocked")
        img = out["candidates"][0]["images"][0]
        self.assertEqual(img["status"], "host_blocked")
        self.assertNotIn("_url", img)
        self.assertNotIn("airtableusercontent", json.dumps(out))

    def test_download_writes_original_and_read_copy(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        buf = io.BytesIO()
        Image.new("RGB", (3200, 1600), (200, 150, 100)).save(buf, "PNG")
        recs = pull.load_snapshot([_save_records([record(finish="Wire brushed", swatches=("s1",))])], REG)
        with tempfile.TemporaryDirectory() as tmp:
            out = pull.build(recs, REG, "test", ["snap.json"], download=True, images_dir=tmp,
                             fetcher=lambda url: buf.getvalue())
            img = out["candidates"][0]["images"][0]
            self.assertEqual(out["images"]["status"], "downloaded")
            self.assertTrue(Path(img["path"]).exists())
            with Image.open(img["read_path"]) as im:
                self.assertLessEqual(max(im.size), pull.READ_LONG_EDGE)
            self.assertIn("/ENG-TEST-0001/swatch/", img["path"])

    def test_undecodable_bytes_mark_unsupported_format(self):
        recs = pull.load_snapshot([_save_records([record(finish="Wire brushed", swatches=("s1",))])], REG)
        with tempfile.TemporaryDirectory() as tmp:
            out = pull.build(recs, REG, "test", ["snap.json"], download=True, images_dir=tmp,
                             fetcher=lambda url: b"not an image")
        self.assertEqual(out["candidates"][0]["images"][0]["status"], "unsupported_format")

    def test_sku_filter(self):
        recs = pull.load_snapshot([_save_records([record(sku="ENG-TEST-0001", finish="Wire brushed"),
                                                  record(sku="ENG-TEST-0002", finish="Wire brushed")])], REG)
        out = pull.build(recs, REG, "test", ["snap.json"], sku_filter={"ENG-TEST-0002"})
        self.assertEqual([c["sku"] for c in out["candidates"]], ["ENG-TEST-0002"])
        self.assertEqual(out["summary"]["excluded"], {"not_in_sku_filter": 1})


def _save_records(records):
    fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump({"records": records}, fh)
    fh.close()
    return fh.name


# ---------------------------------------------------------------------------
# 12. registry <-> schema, write_mode guard, read-only guard
# ---------------------------------------------------------------------------

class TestRegistry(unittest.TestCase):
    def test_every_id_is_in_the_catalogue_field_map_with_its_type(self):
        fields = FIELD_MAP["fields"]
        for name in TARGETS:
            t = REG["targets"][name]
            self.assertIn(t["id"], fields, name)
            self.assertEqual(fields[t["id"]]["name"], name)
            self.assertEqual(fields[t["id"]]["type"], t["type"])
        for key in ("status_field", "evidence_field"):
            self.assertEqual(fields[REG[key]["id"]]["name"], REG[key]["name"])
        for key, fid in REG["inputs"].items():
            if key.startswith("_"):
                continue
            self.assertIn(fid, fields, key)
            expected = REG["image_fields"][key]["name"] if key in REG["image_fields"] else key
            self.assertEqual(fields[fid]["name"], expected, key)
        for key, meta in REG["image_fields"].items():
            if not key.startswith("_"):
                self.assertEqual(fields[REG["inputs"][key]]["type"], "multipleAttachments", key)

    def test_write_mode_is_plan_only_until_deliberately_changed(self):
        self.assertEqual(REG["write_mode"]["mode"], "plan_only",
                         "staged rollout: flipping this is a dated decision recorded in the vault, "
                         "and this assertion is updated in the same commit")

    def test_image_sources_keep_colour_on_swatches_only(self):
        for key, uses in REG["image_sources"].items():
            if key.startswith("_"):
                continue
            if key != "swatch_images":
                self.assertNotIn("colour", uses, key)
        self.assertEqual(REG["source_rules"]["Undertone"]["primary"], ["swatch_images"])
        self.assertEqual(REG["source_rules"]["Tone depth"]["primary"], ["swatch_images"])

    def test_scripts_carry_no_airtable_write_verb(self):
        for name in ("style_tag_pull.py", "style_tag_plan.py"):
            text = (REPO_ROOT / "scripts" / name).read_text()
            for verb in ("update_records", "create_records", "delete_records", "api.airtable.com"):
                self.assertNotIn(verb, text, f"{name} must stay read-only ({verb})")

    def test_held_and_flagged_vocabularies_cover_what_the_script_emits(self):
        emitted = set(re.findall(r'_held\("([a-z_]+)"', (REPO_ROOT / "scripts" / "style_tag_plan.py").read_text()))
        self.assertEqual(emitted - set(REG["held_reasons"]), set())


# ---------------------------------------------------------------------------
# 13. prose guards
# ---------------------------------------------------------------------------

def _columns_table(markdown):
    body = markdown.split("## Columns", 1)[1].split("\n## ", 1)[0]
    names = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        first = line.split("|")[1].strip()
        if first.startswith("---") or first == "Column":
            continue
        m = re.match(r"`([^`]+)`", first)
        if m:
            names.append(m.group(1))
    return names


class TestProse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan_contract = (REPO_ROOT / "contracts" / "style-plan-schema.md").read_text()
        cls.troubled = (REPO_ROOT / "contracts" / "troubled-tags-schema.md").read_text()
        cls.agent = (REPO_ROOT / ".claude" / "agents" / "airtable-actions-agent.md").read_text()
        cls.actions_log = (REPO_ROOT / "contracts" / "actions-log-schema.md").read_text()
        cls.command = (REPO_ROOT / ".claude" / "commands" / "style-tag.md").read_text()
        cls.departments = json.loads((REPO_ROOT / "platform-settings" / "departments.json").read_text())
        cls.claude_md = (REPO_ROOT / "CLAUDE.md").read_text()

    def test_troubled_tags_columns_match_the_registry_and_end_with_action(self):
        cols = _columns_table(self.troubled)
        self.assertEqual(cols, REG["troubled_columns"])
        self.assertEqual(cols[-1], "Action")

    def test_troubled_tags_keeps_the_action_column_rules(self):
        section = self.troubled.split("## The `Action` column", 1)[1]
        self.assertIn("never writes into an `Action` cell", section)
        self.assertIn("never clears one", section)
        self.assertIn("prose is not an approval", section)
        self.assertIn("style-approval-", section)
        self.assertIn("`sku`", section)
        self.assertIn("`field`", section)
        self.assertIn("carry nothing", section)

    def test_plan_contract_states_the_gate_and_the_policy(self):
        self.assertIn("style-plan-1", self.plan_contract)
        self.assertIn("style-approval-1", self.plan_contract)
        self.assertIn("Absence of an approval file means nothing is approved", self.plan_contract)
        self.assertIn("Staff confirmed", self.plan_contract)
        self.assertIn("min_confidence", self.plan_contract)
        for reason in REG["held_reasons"]:
            self.assertIn(f"`{reason}`", self.plan_contract, reason)

    def test_agent_has_the_new_type_with_its_guards(self):
        self.assertIn("`airtable_update_style_tags`", self.agent)
        section = self.agent.split("airtable_update_style_tags", 1)[1]
        self.assertIn("Read before write", section)
        self.assertIn("never upsert", section.lower())
        self.assertIn("Staff confirmed", section)
        self.assertIn("style-tags.json", section)

    def test_actions_log_vocabulary_lists_the_type(self):
        self.assertIn("`airtable_update_style_tags`", self.actions_log)

    def test_command_reads_answers_first_and_reports_last(self):
        self.assertIn("## 0.", self.command)
        self.assertLess(self.command.index("## 0."), self.command.index("## 1."))
        self.assertIn("style_tag_pull.py", self.command)
        self.assertIn("style_tag_plan.py", self.command)
        self.assertIn("PushNotification", self.command)
        self.assertIn("write_mode", self.command)
        self.assertIn("airtable-actions-agent", self.command)

    def test_registered_with_the_catalogue_department(self):
        cat = self.departments["departments"]["catalogue"]
        self.assertIn("style-tag", cat["owns"]["commands"])
        self.assertTrue((REPO_ROOT / ".claude" / "commands" / "style-tag.md").exists())

    def test_claude_md_points_at_the_flow(self):
        self.assertIn("/style-tag", self.claude_md)
        self.assertIn("methods/style-tags.md", self.claude_md)

    def test_images_dir_is_gitignored(self):
        self.assertIn("style-images", (REPO_ROOT / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
