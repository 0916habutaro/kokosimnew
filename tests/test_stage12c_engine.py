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
from phase2_engine.cli import _gifu_demo_entrants


class Stage12CEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.entrants = _gifu_demo_entrants(cls.repo)

    def run_engine(self, seed=2026100401):
        return TournamentEngine(self.repo).run(AnnualCompetitionInput(
            competition_id="CMP000110",
            year=2026,
            entrant_school_ids=self.entrants,
            rng_seed=seed,
        ))

    def test_repository_gifu_groups(self):
        stage = self.repo.stage_by_code("CMP000110", "SEED_EVENT")
        groups = self.repo.groups_by_stage[stage["stage_id"]]
        self.assertEqual(4, len(groups))
        self.assertEqual([6, 3, 4, 3], [int(x["seed_slots_generated"]) for x in groups])

    def test_demo_has_58_unique_entrants(self):
        self.assertEqual(58, len(self.entrants))
        self.assertEqual(58, len(set(self.entrants)))

    def test_gifu_2026_observed_stage_counts(self):
        run = self.run_engine()
        self.assertEqual(16, len(run.seed_assignments))
        gate = run.stage_executions[1]
        self.assertEqual(42, len(gate.entrant_school_ids))
        self.assertEqual(21, len(gate.matches))
        self.assertEqual(21, len(gate.output_school_ids))
        self.assertEqual(0, gate.metadata["bye_count"])
        self.assertEqual(37, len(run.main_entrant_school_ids))
        self.assertEqual([], run.warnings)

    def test_seed_tiers_follow_rules(self):
        run = self.run_engine()
        tiers = {}
        for a in run.seed_assignments:
            tiers[a.seed_tier] = tiers.get(a.seed_tier, 0) + 1
        self.assertEqual(4, tiers.get("seed_rank_1"))
        self.assertEqual(4, tiers.get("seed_rank_2"))
        self.assertEqual(8, tiers.get("other_seed"))

    def test_seeded_teams_bypass_gate(self):
        run = self.run_engine()
        seeded = {x.school_id for x in run.seed_assignments}
        gate = set(run.stage_executions[1].entrant_school_ids)
        main = set(run.main_entrant_school_ids)
        self.assertTrue(seeded.isdisjoint(gate))
        self.assertTrue(seeded.issubset(main))

    def test_seed_reproducibility(self):
        a = self.run_engine(seed=12345).to_dict()
        b = self.run_engine(seed=12345).to_dict()
        self.assertEqual(a, b)

    def test_different_seed_changes_draw_or_results(self):
        a = self.run_engine(seed=12345)
        b = self.run_engine(seed=54321)
        self.assertNotEqual(a.main_entrant_school_ids, b.main_entrant_school_ids)

    def test_membership_not_implicitly_participation(self):
        with self.assertRaises(ValueError):
            TournamentEngine(self.repo).run(AnnualCompetitionInput(
                competition_id="CMP000110", year=2026, entrant_school_ids=[], rng_seed=1
            ))

    def test_odd_gate_count_gets_single_bye(self):
        run = TournamentEngine(self.repo).run(AnnualCompetitionInput(
            competition_id="CMP000110",
            year=2026,
            entrant_school_ids=self.entrants[:-1],
            rng_seed=99,
        ))
        gate = run.stage_executions[1]
        self.assertEqual(1, gate.metadata["bye_count"])

    def test_annual_group_ranking_override(self):
        stage = self.repo.stage_by_code("CMP000110", "SEED_EVENT")
        group = self.repo.groups_by_stage[stage["stage_id"]][0]
        eligible = sorted(set(self.entrants) & self.repo.group_school_ids(group, 2026))
        supplied = list(reversed(eligible))
        run = TournamentEngine(self.repo).run(AnnualCompetitionInput(
            competition_id="CMP000110",
            year=2026,
            entrant_school_ids=self.entrants,
            rng_seed=1,
            group_rankings={group["stage_group_id"]: supplied},
        ))
        group_seeds = [x for x in run.seed_assignments if x.group_id == group["stage_group_id"]]
        ranked_ids = [x.school_id for x in sorted(group_seeds, key=lambda x: x.source_rank)]
        self.assertEqual(supplied[:6], ranked_ids)

    def test_unknown_school_is_rejected(self):
        with self.assertRaises(ValueError):
            TournamentEngine(self.repo).run(AnnualCompetitionInput(
                competition_id="CMP000110",
                year=2026,
                entrant_school_ids=self.entrants + ["SCH_DOES_NOT_EXIST"],
                rng_seed=1,
            ))

    def test_cli_demo(self):
        proc = subprocess.run(
            [sys.executable, "-m", "phase2_engine.cli", "--data-dir", str(ROOT), "--gifu-demo", "--seed", "2026100401"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(37, len(payload["main_entrant_school_ids"]))


if __name__ == "__main__":
    unittest.main()
