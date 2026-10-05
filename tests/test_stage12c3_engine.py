from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
sys.path.insert(0, str(ROOT))

from phase2_engine import AnnualCompetitionInput, DataRepository, TournamentEngine


class Stage12C3EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.engine = TournamentEngine(cls.repo)

    def _input_for(self, competition_id: str, seed: int = 2026100407):
        stages = self.repo.stages(competition_id)
        event_groups = []
        entrants = set()
        for stage in stages:
            if stage["stage_id"] not in self.repo.assignments_by_stage:
                continue
            for group in self.repo.groups_by_stage.get(stage["stage_id"], []):
                event_groups.append(group)
                entrants |= self.repo.group_school_ids(group, 2026)

        group_override = {}
        if not entrants:
            prefecture_code = self.repo.competition(competition_id).get("prefecture_code")
            candidates = sorted(
                school_id for school_id, row in self.repo.schools.items()
                if row.get("prefecture_code") == prefecture_code
            )
            entrants = set(candidates)
            self.assertTrue(event_groups)
            for idx, school_id in enumerate(candidates):
                gid = event_groups[idx % len(event_groups)]["stage_group_id"]
                group_override.setdefault(gid, []).append(school_id)

        # Tournament-internal annual-draw qualifier groups have no permanent
        # federation-area membership.  When another stage supplies the entrant set
        # (Ehime autumn seed event), feed that same annual set to the preliminary.
        for group in event_groups:
            if (
                group.get("stage_code") == "PRELIMINARY_QUALIFIER"
                and not self.repo.group_school_ids(group, 2026)
                and group["stage_group_id"] not in group_override
            ):
                group_override[group["stage_group_id"]] = sorted(entrants)

        return AnnualCompetitionInput(
            competition_id=competition_id,
            year=2026,
            entrant_school_ids=sorted(entrants),
            rng_seed=seed,
            group_entrant_school_ids=group_override,
        )

    def test_all_26_format_models_are_registered(self):
        self.assertEqual(
            {f"FMT{i:03d}" for i in range(1, 27)},
            TournamentEngine.SUPPORTED_FORMAT_MODELS,
        )

    def test_remaining_23_stage_competitions_execute(self):
        expected_main = {
            "CMP000074": 24,
            "CMP000075": 22,
            "CMP000076": 25,
            "CMP000077": 27,
            "CMP000082": 28,
            "CMP000083": 31,
            "CMP000085": 34,
            "CMP000107": 16,
            "CMP000108": 24,
            "CMP000109": 20,
            "CMP000111": 39,
            "CMP000112": 39,
            "CMP000113": 48,
            "CMP000114": 49,
            "CMP000115": 25,
            "CMP000116": 63,
            "CMP000124": 53,
            "CMP000134": 20,
            "CMP000135": 32,
            "CMP000136": 32,
            "CMP000140": 30,
            "CMP000160": 68,
            "CMP000162": 62,
        }
        covered_models = set()
        for cid, expected in expected_main.items():
            with self.subTest(competition_id=cid):
                run = self.engine.run(self._input_for(cid))
                self.assertEqual(expected, len(run.main_entrant_school_ids))
                self.assertEqual(len(run.main_entrant_school_ids), len(set(run.main_entrant_school_ids)))
                for execution in run.stage_executions:
                    covered_models.add(execution.format_model_id)
                    covered_models.update(execution.metadata.get("group_models", {}).values())
        remaining = {
            "FMT002", "FMT003", "FMT004", "FMT007", "FMT008",
            "FMT010", "FMT011", "FMT012", "FMT013", "FMT014",
            "FMT015", "FMT016", "FMT017", "FMT022", "FMT023",
            "FMT024", "FMT025",
        }
        self.assertTrue(remaining.issubset(covered_models))

    def test_multiphase_mechanisms_emit_expected_phase_codes(self):
        checks = {
            "CMP000074": {"PRIMARY", "REPECHAGE"},
            "CMP000076": {"PRIMARY", "SECONDARY"},
            "CMP000085": {"PRIMARY_TOP4", "SECONDARY"},
            "CMP000108": {"MAIN_KO", "REP_DECIDERS"},
            "CMP000113": {"PRIMARY_BLOCKS", "PRIMARY_LEAGUE", "PRIMARY_ZONES", "PRIMARY", "SECONDARY"},
            "CMP000114": {"PRIMARY_REPECHAGE"},
            "CMP000134": {"ZONE_RR", "FIRST_PLACE_PLAYOFF", "SECOND_PLACE_PLAYOFF"},
        }
        for cid, expected_phases in checks.items():
            with self.subTest(competition_id=cid):
                run = self.engine.run(self._input_for(cid, seed=2026100411))
                phases = {m.phase_code for execution in run.stage_executions for m in execution.matches}
                self.assertTrue(expected_phases.issubset(phases), (cid, expected_phases - phases))

    def test_new_seed_event_models_execute(self):
        for cid, expected_seed_count, phase in [
            ("CMP000140", 4, "CENTRAL_KO"),
            ("CMP000160", 8, "DISTRICT_KO"),
            ("CMP000162", 4, "CENTRAL_KO"),
        ]:
            with self.subTest(competition_id=cid):
                run = self.engine.run(self._input_for(cid, seed=2026100412))
                self.assertEqual(expected_seed_count, len(run.seed_assignments))
                self.assertEqual(len(run.entrant_school_ids), len(run.main_entrant_school_ids))
                self.assertIn(phase, {m.phase_code for m in run.stage_executions[0].matches})

    def test_mie_annual_group_override_allows_missing_membership_master(self):
        annual = self._input_for("CMP000116")
        self.assertTrue(annual.group_entrant_school_ids)
        run = self.engine.run(annual)
        self.assertEqual(7, len(run.seed_assignments))
        self.assertEqual(63, len(run.main_entrant_school_ids))
        self.assertTrue(all(a.school_id in annual.entrant_school_ids for a in run.seed_assignments))

    def test_group_entrant_override_must_be_subset_of_competition_entrants(self):
        annual = self._input_for("CMP000116")
        gid = next(iter(annual.group_entrant_school_ids))
        annual.group_entrant_school_ids[gid] = annual.group_entrant_school_ids[gid] + ["SCH_DOES_NOT_EXIST"]
        with self.assertRaises(ValueError):
            self.engine.run(annual)

    def test_new_models_are_seed_reproducible(self):
        for cid in ["CMP000074", "CMP000085", "CMP000113", "CMP000134", "CMP000160"]:
            with self.subTest(competition_id=cid):
                a = self.engine.run(self._input_for(cid, seed=314159)).to_dict()
                b = self.engine.run(self._input_for(cid, seed=314159)).to_dict()
                self.assertEqual(a, b)

    def test_fmt001_seed_context_is_supported(self):
        run = self.engine.run(self._input_for("CMP000144", seed=271828))
        self.assertEqual(12, len(run.seed_assignments))
        self.assertEqual(["SEED_EVENT", "PRELIMINARY_QUALIFIER", "MAIN"],
                         [x.stage_code for x in run.stage_executions])
        self.assertEqual(16, len(run.main_entrant_school_ids))
        self.assertEqual(12, run.stage_executions[1].metadata["protected_seed_count"])
        self.assertEqual(0, run.stage_executions[-1].metadata["seed_count"])
        self.assertIn("SEED_BLOCK_KO", {m.phase_code for m in run.stage_executions[0].matches})


if __name__ == "__main__":
    unittest.main()
