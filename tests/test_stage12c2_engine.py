from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
sys.path.insert(0, str(ROOT))

from phase2_engine import AnnualCompetitionInput, DataRepository, TournamentEngine
from phase2_engine.cli import (
    _aomori_autumn_demo,
    _chiba_autumn_demo,
    _hokkaido_autumn_demo,
    _kanagawa_demo,
)


class Stage12C2EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.engine = TournamentEngine(cls.repo)

    def test_supported_format_models_include_four_new_families(self):
        for mid in ["FMT001", "FMT005", "FMT006", "FMT018", "FMT019", "FMT020", "FMT021"]:
            self.assertIn(mid, TournamentEngine.SUPPORTED_FORMAT_MODELS)

    def test_kanagawa_spring_round_robin_path(self):
        entrants, direct = _kanagawa_demo(self.repo, "CMP000095")
        run = self.engine.run(AnnualCompetitionInput(
            competition_id="CMP000095", year=2026, entrant_school_ids=entrants,
            direct_main_entry_school_ids=direct, rng_seed=2026100402,
        ))
        stage = run.stage_executions[0]
        self.assertEqual("FMT006", stage.format_model_id)
        self.assertEqual(162, len(stage.entrant_school_ids))
        self.assertEqual(81, len(stage.output_school_ids))
        self.assertEqual(82, len(run.main_entrant_school_ids))
        self.assertEqual(1, len(direct))
        self.assertNotIn(direct[0], stage.entrant_school_ids)
        self.assertIn(direct[0], run.main_entrant_school_ids)
        self.assertEqual([], run.warnings)
        self.assertTrue(any(m.phase_code == "POOL_RR" for m in stage.matches))
        self.assertTrue(any(m.phase_code == "CROSS_PLAYOFF" for m in stage.matches))

    def test_kanagawa_pool_plan_matches_output_slots(self):
        entrants, direct = _kanagawa_demo(self.repo, "CMP000095")
        run = self.engine.run(AnnualCompetitionInput(
            competition_id="CMP000095", year=2026, entrant_school_ids=entrants,
            direct_main_entry_school_ids=direct, rng_seed=7,
        ))
        meta = run.stage_executions[0].metadata["group_metadata"]
        # 46 -> ten 4-team pools + two 3-team pools -> 23 qualifiers.
        first = meta["SGR000083"]
        self.assertEqual(10, first["four_team_pool_count"])
        self.assertEqual(2, first["three_team_pool_count"])
        self.assertEqual(23, first["output_slots"])
        # 36 -> nine 4-team pools -> 18 qualifiers.
        third = meta["SGR000085"]
        self.assertEqual(9, third["four_team_pool_count"])
        self.assertEqual(0, third["three_team_pool_count"])
        self.assertEqual(18, third["output_slots"])

    def test_chiba_autumn_global_primary_and_repechage(self):
        entrants, direct = _chiba_autumn_demo(self.repo)
        run = self.engine.run(AnnualCompetitionInput(
            competition_id="CMP000093", year=2026, entrant_school_ids=entrants,
            direct_main_entry_school_ids=direct, rng_seed=2026100403,
        ))
        stage = run.stage_executions[0]
        self.assertEqual("FMT005", stage.format_model_id)
        self.assertEqual(140, len(stage.entrant_school_ids))
        self.assertEqual(28, stage.metadata["primary_qualifier_count"])
        self.assertEqual(112, stage.metadata["primary_nonqualifier_count"])
        self.assertEqual(19, stage.metadata["repechage_qualifier_count"])
        self.assertEqual(47, len(stage.output_school_ids))
        self.assertEqual(48, len(run.main_entrant_school_ids))
        self.assertEqual([], run.warnings)
        self.assertTrue(any(m.phase_code == "PRIMARY_GLOBAL" for m in stage.matches))
        self.assertTrue(any(m.phase_code == "REPECHAGE_GLOBAL" for m in stage.matches))

    def test_chiba_match_ids_are_unique_across_phases(self):
        entrants, direct = _chiba_autumn_demo(self.repo)
        run = self.engine.run(AnnualCompetitionInput(
            competition_id="CMP000093", year=2026, entrant_school_ids=entrants,
            direct_main_entry_school_ids=direct, rng_seed=3,
        ))
        ids = [m.match_id for m in run.stage_executions[0].matches]
        self.assertEqual(len(ids), len(set(ids)))

    def test_hokkaido_autumn_block_winner_path(self):
        entrants, direct = _hokkaido_autumn_demo(self.repo)
        self.assertEqual([], direct)
        run = self.engine.run(AnnualCompetitionInput(
            competition_id="CMP000013", year=2026, entrant_school_ids=entrants,
            rng_seed=2026100404,
        ))
        stage = run.stage_executions[0]
        self.assertEqual("FMT001", stage.format_model_id)
        self.assertEqual(192, len(stage.entrant_school_ids))
        self.assertEqual(20, len(stage.output_school_ids))
        self.assertEqual(20, len(run.main_entrant_school_ids))
        self.assertEqual(10, stage.metadata["group_count"])
        block_total = sum(x["representative_block_count"] for x in stage.metadata["group_metadata"].values())
        self.assertEqual(20, block_total)
        self.assertEqual([], run.warnings)

    def test_aomori_autumn_mixed_seed_models(self):
        entrants, direct = _aomori_autumn_demo(self.repo)
        self.assertEqual([], direct)
        run = self.engine.run(AnnualCompetitionInput(
            competition_id="CMP000073", year=2026, entrant_school_ids=entrants,
            rng_seed=2026100405,
        ))
        stage = run.stage_executions[0]
        self.assertEqual(53, len(stage.entrant_school_ids))
        self.assertEqual(16, len(run.seed_assignments))
        self.assertEqual(53, len(run.main_entrant_school_ids))
        self.assertEqual(set(entrants), set(run.main_entrant_school_ids))
        self.assertEqual(
            {"FMT018", "FMT019", "FMT020", "FMT021"},
            set(stage.metadata["group_models"].values()),
        )
        tiers = {}
        for a in run.seed_assignments:
            tiers[a.seed_tier] = tiers.get(a.seed_tier, 0) + 1
        self.assertEqual(4, tiers.get("seed_rank_1"))
        self.assertEqual(4, tiers.get("seed_rank_2"))
        self.assertEqual(8, tiers.get("seed_rank_3"))

    def test_aomori_contains_knockout_and_league_phases(self):
        entrants, _ = _aomori_autumn_demo(self.repo)
        run = self.engine.run(AnnualCompetitionInput(
            competition_id="CMP000073", year=2026, entrant_school_ids=entrants, rng_seed=11,
        ))
        phases = {m.phase_code for m in run.stage_executions[0].matches}
        self.assertIn("PRIMARY_SEED_KO", phases)
        self.assertIn("SEED_REPECHAGE", phases)
        self.assertIn("THIRD_SEED", phases)
        self.assertIn("PRIMARY_LEAGUES", phases)
        self.assertIn("RANKING", phases)
        self.assertIn("DISTRICT_RR", phases)
        self.assertIn("CROSS_DECIDERS", phases)

    def test_new_format_seed_reproducibility(self):
        entrants, direct = _chiba_autumn_demo(self.repo)
        a = self.engine.run(AnnualCompetitionInput(
            competition_id="CMP000093", year=2026, entrant_school_ids=entrants,
            direct_main_entry_school_ids=direct, rng_seed=1234,
        )).to_dict()
        b = self.engine.run(AnnualCompetitionInput(
            competition_id="CMP000093", year=2026, entrant_school_ids=entrants,
            direct_main_entry_school_ids=direct, rng_seed=1234,
        )).to_dict()
        self.assertEqual(a, b)

    def test_direct_main_entry_must_be_competition_entrant(self):
        entrants, direct = _chiba_autumn_demo(self.repo)
        with self.assertRaises(ValueError):
            self.engine.run(AnnualCompetitionInput(
                competition_id="CMP000093", year=2026, entrant_school_ids=entrants[:-1],
                direct_main_entry_school_ids=direct, rng_seed=1,
            ))

    def test_cli_chiba_demo(self):
        proc = subprocess.run(
            [sys.executable, "-m", "phase2_engine.cli", "--data-dir", str(ROOT),
             "--demo", "chiba-autumn", "--seed", "2026100406"],
            cwd=ROOT, text=True, capture_output=True, check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual("CMP000093", payload["competition_id"])
        self.assertEqual(48, len(payload["main_entrant_school_ids"]))


if __name__ == "__main__":
    unittest.main()
