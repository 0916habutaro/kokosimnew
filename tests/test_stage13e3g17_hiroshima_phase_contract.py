from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g17 import (
    CROSSWALK_FILE, GROUP_CONTRACT_FILE, ROUTE_FILE,
    default_primary_slots, audit_2026_hiroshima_stage13e3g17,
)
from phase2_engine.hiroshima_stage13e3g16 import STRUCTURE_FILE, EVENT_FILE
from phase2_engine.hiroshima_qualification_timeline_2026 import TIMELINE_FILE
from phase2_engine.hiroshima_berth_roster_2026 import ROSTER_FILE, STAGE_GROUP_FILE
from phase2_engine.hiroshima_stage13e3g17 import (
    FORMAT_PHASE_FILE, FORMAT_OVERRIDE_FILE, FORMAT_PARAMETER_FILE,
)

ROOT = Path(__file__).resolve().parents[1] / "data"
FILES = (CROSSWALK_FILE,GROUP_CONTRACT_FILE,ROUTE_FILE,STRUCTURE_FILE,EVENT_FILE,
         TIMELINE_FILE,ROSTER_FILE,STAGE_GROUP_FILE,FORMAT_PHASE_FILE,
         FORMAT_OVERRIDE_FILE,FORMAT_PARAMETER_FILE)


def copy_fixtures(root):
    for p in FILES:
        to = root / p
        to.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT / p,to)


def edit(root, path, change):
    dst=root/path
    with dst.open(encoding="utf-8-sig",newline="") as f:
        r=csv.DictReader(f)
        cols,rows=r.fieldnames,list(r)
    change(rows)
    with dst.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class Stage13E3G17HiroshimaPhaseMapping(unittest.TestCase):
    def test_full_87_routes_map_to_fmt025_phases(self):
        report=audit_2026_hiroshima_stage13e3g17(ROOT)
        self.assertTrue(report["ok"],report["errors"])
        self.assertEqual(87,report["published_child_route_count"])
        self.assertEqual((38,35,14),(
            report["fmt025_primary_child_event_count"],
            report["fmt025_repechage_zone_child_event_count"],
            report["fmt025_cross_zone_entry_gate_count"]))
        self.assertEqual(15,report["publisher_result_events_mapped_to_route"])

    def test_group_slots_include_direct_senbatsu_exemption(self):
        report=audit_2026_hiroshima_stage13e3g17(ROOT)
        self.assertEqual((64,1,63,38,25),(
            report["all_group_quota"],report["direct_main_exempt_slots"],
            report["nonexempt_qualification_slots"],
            report["expected_first_place_award_slots"],
            report["remaining_nonprimary_award_slots"]))

    def test_four_generic_runtime_primary_quota_discrepancies(self):
        report=audit_2026_hiroshima_stage13e3g17(ROOT)
        self.assertEqual(["SGR000140","SGR000142","SGR000145","SGR000146"],
                         report["generic_primary_split_mismatch_groups"])
        self.assertEqual(3,default_primary_slots(6))
        self.assertEqual(5,default_primary_slots(9))
        self.assertEqual(3,default_primary_slots(6))

    def test_draw_accuracy_and_ranking_are_fail_closed(self):
        r=audit_2026_hiroshima_stage13e3g17(ROOT)
        self.assertEqual(0,r["verified_annual_draw_edges"])
        self.assertFalse(r["exact_path_runtime_ready"])
        self.assertFalse(r["ranking_only_route_verified"])
        self.assertFalse(r["fmt025_optional_ranking_release_allowed"])
        self.assertEqual(0,r["official_pdf_bodies_inspected"])

    def test_observed_2026_scores_are_not_turned_into_runtime_outcomes(self):
        r=audit_2026_hiroshima_stage13e3g17(ROOT)
        self.assertFalse(r["historical_fixtures_are_runtime_generated"])
        with (ROOT/CROSSWALK_FILE).open(encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        self.assertTrue(all(x["can_materialize_draw_accurate_runtime"]=="no" for x in rows))

    def test_cross_zone_event_reassigned_to_wrong_result_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_fixtures(root)
            edit(root,CROSSWALK_FILE,lambda r:next(
                x for x in r if x["matched_publisher_event_check_id"]
            ).update(matched_qualification_decider_match_id="HT20260001"))
            res=audit_2026_hiroshima_stage13e3g17(root)
            self.assertFalse(res["ok"])
            self.assertTrue(any("unsupported publisher result" in e for e in res["errors"]))

    def test_runner_up_zone_match_is_not_mislabeled_as_cross_gate(self):
        with (ROOT/CROSSWALK_FILE).open(encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        event=next(x for x in rows if x["matched_publisher_event_check_id"]=="HPE2026007")
        self.assertEqual("HR20260043",event["route_id"])
        self.assertEqual("REPECHAGE_ZONE",event["phase_execution_role"])
        self.assertEqual("HT20260044",event["matched_qualification_decider_match_id"])

    def test_repeated_or_removed_route_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_fixtures(root)
            edit(root,CROSSWALK_FILE,lambda r:r.pop())
            res=audit_2026_hiroshima_stage13e3g17(root)
            self.assertFalse(res["ok"])
            self.assertTrue(any("87" in x for x in res["errors"]))

    def test_primary_zone_misclassified_as_repechage_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_fixtures(root)
            edit(root,CROSSWALK_FILE,lambda r:r[0].update(model_phase_id="FPH050"))
            res=audit_2026_hiroshima_stage13e3g17(root)
            self.assertFalse(res["ok"])
            self.assertTrue(any("phase/selector/zone contract mismatch" in x for x in res["errors"]))

    def test_unreviewed_draw_cannot_be_claimed_ready(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_fixtures(root)
            edit(root,CROSSWALK_FILE,lambda r:r[0].update(
                can_materialize_draw_accurate_runtime="yes"))
            res=audit_2026_hiroshima_stage13e3g17(root)
            self.assertFalse(res["ok"])
            self.assertTrue(any("unverified draw edge" in x for x in res["errors"]))

    def test_exemption_must_not_consume_a_simulated_match(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_fixtures(root)
            edit(root,GROUP_CONTRACT_FILE,lambda r:next(
                x for x in r if x["stage_group_id"]=="SGR000140"
            ).update(required_qualifier_awards="7"))
            res=audit_2026_hiroshima_stage13e3g17(root)
            self.assertFalse(res["ok"])
            self.assertTrue(any("phase split crosswalk mismatch" in x for x in res["errors"]))

    def test_prefecture_output_slot_parameter_must_match(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_fixtures(root)
            edit(root,FORMAT_PARAMETER_FILE,lambda r:next(
                x for x in r if x["stage_group_id"]=="SGR000145"
                and x["parameter_name"]=="output_slots"
            ).update(parameter_value="7"))
            res=audit_2026_hiroshima_stage13e3g17(root)
            self.assertFalse(res["ok"])
            self.assertTrue(any("group quota" in x for x in res["errors"]))

    def test_rank_order_cannot_be_enabled_without_proof(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_fixtures(root)
            def poison(rows):
                template=next(x for x in rows if x["stage_group_id"]=="SGR000140")
                record=template.copy()
                record["parameter_id"]="PAR999999"
                record["parameter_name"]="rank_order_required"
                record["parameter_value"]="true"
                record["value_type"]="boolean"
                rows.append(record)
            edit(root,FORMAT_PARAMETER_FILE,poison)
            res=audit_2026_hiroshima_stage13e3g17(root)
            self.assertFalse(res["ok"])
            self.assertTrue(any("ranking-only event enabled" in x for x in res["errors"]))

    def test_stage_group_primary_count_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_fixtures(root)
            edit(root,GROUP_CONTRACT_FILE,lambda r:r[0].update(
                observed_first_place_event_slots="99"))
            res=audit_2026_hiroshima_stage13e3g17(root)
            self.assertFalse(res["ok"])
            self.assertTrue(any("phase split crosswalk mismatch" in x for x in res["errors"]))


if __name__=="__main__":
    unittest.main()
