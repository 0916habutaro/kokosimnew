from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
sys.path.insert(0, str(ROOT))

from phase2_engine import DataRepository, SeasonOrchestrator


class Stage12HPrefecturalStructureFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.orch = SeasonOrchestrator(cls.repo, DATA_ROOT)
        cls.season = cls.orch.run_structural_season(2026, 2026100501)

    def test_tokyo_spring_preliminary_then_111_team_main(self):
        stages = self.repo.stages("CMP000094")
        self.assertEqual(
            ["PRELIMINARY_QUALIFIER", "MAIN"],
            [s["stage_code"] for s in stages],
        )
        run = self.season.competition_runs["CMP000094"]
        self.assertEqual("PRELIMINARY_QUALIFIER", run.stage_executions[0].stage_code)
        self.assertEqual(47, len(run.stage_executions[0].output_school_ids))
        self.assertEqual(64, len(set(run.main_entrant_school_ids) - set(run.stage_executions[0].output_school_ids)))
        self.assertEqual(111, len(run.main_entrant_school_ids))

    def test_tokyo_spring_prior_autumn_64_are_direct_entries(self):
        rows = [r for r in self.season.access_resolutions if r.destination_competition_id == "CMP000094"]
        self.assertEqual(1, len(rows))
        self.assertEqual(64, len(rows[0].resolved_school_ids))
        self.assertEqual("prior_year_structural_bootstrap", rows[0].resolution_source)
        prelim = set(self.season.competition_runs["CMP000094"].stage_executions[0].entrant_school_ids)
        self.assertFalse(prelim & set(rows[0].resolved_school_ids))

    def test_wakayama_autumn_four_plus_four_equals_eight(self):
        stages = self.repo.stages("CMP000128")
        self.assertEqual(
            ["PRELIMINARY_QUALIFIER", "MAIN"],
            [s["stage_code"] for s in stages],
        )
        run = self.season.competition_runs["CMP000128"]
        self.assertEqual(4, len(run.stage_executions[0].output_school_ids))
        rows = [r for r in self.season.access_resolutions if r.destination_competition_id == "CMP000128"]
        self.assertEqual(1, len(rows))
        self.assertEqual(4, len(rows[0].resolved_school_ids))
        self.assertEqual("current_year_structural_event_bootstrap", rows[0].resolution_source)
        self.assertEqual(8, len(run.main_entrant_school_ids))

    def test_ehime_autumn_seed_preliminary_main_graph(self):
        stages = self.repo.stages("CMP000144")
        self.assertEqual(
            ["SEED_EVENT", "PRELIMINARY_QUALIFIER", "MAIN"],
            [s["stage_code"] for s in stages],
        )
        run = self.season.competition_runs["CMP000144"]
        self.assertEqual(
            ["SEED_EVENT", "PRELIMINARY_QUALIFIER", "MAIN"],
            [s.stage_code for s in run.stage_executions],
        )
        self.assertEqual(13, len(run.seed_assignments))
        self.assertEqual(13, run.stage_executions[1].metadata["protected_seed_count"])
        self.assertEqual(16, len(run.stage_executions[1].output_school_ids))
        self.assertEqual(16, len(run.main_entrant_school_ids))
        self.assertEqual(0, run.stage_executions[-1].metadata["seed_count"])

    def test_ehime_summer_champion_bypasses_seed_event_but_enters_preliminary(self):
        access = [r for r in self.season.access_resolutions if r.destination_competition_id == "CMP000144"]
        self.assertEqual(1, len(access))
        self.assertEqual(1, len(access[0].resolved_school_ids))
        summer_champ = self.season.competition_runs["CMP000062"].outcome.champion_school_id
        self.assertEqual([summer_champ], access[0].resolved_school_ids)
        run = self.season.competition_runs["CMP000144"]
        self.assertNotIn(summer_champ, run.stage_executions[0].entrant_school_ids)
        self.assertIn(summer_champ, run.stage_executions[1].entrant_school_ids)
        self.assertIn(summer_champ, {a.school_id for a in run.seed_assignments})

    def test_all_22_access_rules_and_94_prefectural_runs_pass(self):
        self.assertEqual(22, len(self.season.access_resolutions))
        self.assertTrue(all(r.status == "PASS" for r in self.season.access_resolutions))
        self.assertEqual(94, len(self.season.prefectural_rows))
        self.assertEqual(94, sum(r.status == "PASS" for r in self.season.prefectural_rows))
        self.assertEqual(0, len(self.season.internal_structure_gaps))
        self.assertEqual(0, len(self.season.calendar_gaps))

    def test_same_seed_reproduces_three_fixed_competitions(self):
        again = self.orch.run_structural_season(2026, 2026100501)
        for cid in ("CMP000094", "CMP000128", "CMP000144"):
            with self.subTest(competition_id=cid):
                self.assertEqual(
                    self.season.competition_runs[cid].to_dict(),
                    again.competition_runs[cid].to_dict(),
                )


if __name__ == "__main__":
    unittest.main()
