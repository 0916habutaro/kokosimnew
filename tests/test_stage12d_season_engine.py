from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
sys.path.insert(0, str(ROOT))

from phase2_engine import DataRepository, SeasonOrchestrator


class Stage12DSeasonEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.orchestrator = SeasonOrchestrator(cls.repo, DATA_ROOT)
        cls.season = cls.orchestrator.run_structural_season(2026, 2026100501)

    def test_all_prefectural_spring_autumn_execute(self):
        rows = self.season.prefectural_rows
        self.assertEqual(94, len(rows))
        self.assertEqual(47, sum(r.season_segment == "spring" for r in rows))
        self.assertEqual(47, sum(r.season_segment == "autumn" for r in rows))
        self.assertTrue(all(r.champion_school_id for r in rows))

    def test_prefectural_structural_pass_is_94_after_tokyo_preliminary(self):
        passed = [r for r in self.season.prefectural_rows if r.status == "PASS"]
        gaps = [r for r in self.season.prefectural_rows if r.status != "PASS"]
        self.assertEqual(94, len(passed))
        self.assertEqual(0, len(gaps))
        self.assertEqual(0, len(self.season.internal_structure_gaps))
        tokyo = next(r for r in self.season.prefectural_rows if r.competition_id == "CMP000016")
        self.assertEqual(232, tokyo.entrant_count)
        self.assertEqual(64, tokyo.main_entrant_count)

    def test_all_19_access_rules_resolve(self):
        self.assertEqual(19, len(self.season.access_resolutions))
        self.assertTrue(all(r.status == "PASS" for r in self.season.access_resolutions))
        self.assertFalse(any(r.date_status == "FAIL" for r in self.season.access_resolutions))

    def test_current_summer_results_feed_autumn_access(self):
        summer_rules = [
            r for r in self.season.access_resolutions
            if r.source_event_kind == "summer_local_qualifier"
        ]
        self.assertTrue(summer_rules)
        for r in summer_rules:
            self.assertEqual("current_season_competition_result", r.resolution_source)
            source_run = self.season.competition_runs[r.source_competition_id]
            self.assertEqual([source_run.outcome.champion_school_id], r.resolved_school_ids)

    def test_mie_summer_champion_bypasses_seed_event_and_becomes_eighth_seed(self):
        summer_champ = self.season.competition_runs["CMP000045"].outcome.champion_school_id
        mie = self.season.competition_runs["CMP000116"]
        self.assertEqual(8, len(mie.seed_assignments))
        self.assertIn(summer_champ, {x.school_id for x in mie.seed_assignments})
        self.assertEqual(1, mie.stage_executions[0].metadata.get("forced_seed_count"))
        self.assertEqual([summer_champ], mie.stage_executions[0].metadata.get("seed_event_bypass_school_ids"))

    def test_all_49_summer_local_qualifiers_and_national_run(self):
        self.assertEqual(49, len(self.season.summer_local_competition_ids))
        self.assertTrue(all(cid in self.season.competition_runs for cid in self.season.summer_local_competition_ids))
        self.assertIn("CMP000002", self.season.competition_runs)
        national = self.season.competition_runs["CMP000002"]
        self.assertEqual(49, len(national.entrant_school_ids))
        self.assertEqual(49, len(set(national.entrant_school_ids)))

    def test_qualification_graph_resolves_summer_and_all_jingu_routes(self):
        rows = self.season.qualification_resolutions
        self.assertEqual(59, len(rows))
        self.assertEqual(59, sum(r.status == "PASS" for r in rows))
        self.assertEqual(0, sum(r.status != "PASS" for r in rows))
        self.assertFalse(any(r.date_status == "FAIL" for r in rows))

    def test_regional_feeder_gap_is_closed_by_stage12e(self):
        self.assertEqual(0, len(self.season.regional_bridge_gaps))
        self.assertEqual(16, len(self.season.regional_rows))
        self.assertTrue(all(r.status == "PASS" for r in self.season.regional_rows))

    def test_senbatsu_structural_bootstrap_has_32_and_access_prefectures(self):
        ids = self.season.senbatsu_participant_school_ids
        self.assertEqual(32, len(ids))
        self.assertEqual(32, len(set(ids)))
        pcodes = {self.repo.schools[sid]["prefecture_code"] for sid in ids}
        self.assertTrue({"01", "14", "23", "24"}.issubset(pcodes))

    def test_prefectural_calendar_gaps_are_explicit(self):
        self.assertEqual(65, len(self.season.calendar_gaps))
        official = 94 - len(self.season.calendar_gaps)
        self.assertEqual(29, official)

    def test_same_seed_reproduces_season_champions_and_dependencies(self):
        again = self.orchestrator.run_structural_season(2026, 2026100501)
        champions_a = [(r.competition_id, r.champion_school_id) for r in self.season.prefectural_rows]
        champions_b = [(r.competition_id, r.champion_school_id) for r in again.prefectural_rows]
        self.assertEqual(champions_a, champions_b)
        access_a = [(r.access_rule_id, r.resolved_school_ids) for r in self.season.access_resolutions]
        access_b = [(r.access_rule_id, r.resolved_school_ids) for r in again.access_resolutions]
        self.assertEqual(access_a, access_b)


if __name__ == "__main__":
    unittest.main()
