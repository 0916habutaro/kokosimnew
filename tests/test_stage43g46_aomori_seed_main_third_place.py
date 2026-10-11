"""Stage43G-46: four Aomori FMT018-21 seed groups, MAIN and third-place proof."""
from __future__ import annotations

from pathlib import Path
import json
import shutil
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService, CareerPreviewSaveError,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.chiba_third_place_checkpoint import (
    AomoriThirdPlaceCheckpointService, ChibaThirdPlaceNotReady,
)
from phase2_engine.future_aomori_seed_main_bridge import (
    AOMORI_SPRING, prepare_future_aomori_seed_main_preview,
)
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository
from phase2_engine.same_year_regional_feeder_gate import (
    RegionalFeederNotReady, project_same_year_regional_feeders,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEED = 2026101146
TOHOKU = "CMP000005"
TOKUSHIMA = "CMP000139"


class Stage43G46AomoriSeedMainThirdPlaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.initial = tempfile.TemporaryDirectory()
        original = Path(cls.initial.name)
        cls.history = original / "historical_matches.sqlite3"
        cls.rosters = original / "career_rosters.sqlite3"
        archive = HistoricalMatchArchive(cls.history)
        archive.sync(
            year=2026, rng_seed=SEED,
            resolver_contract="game_v1",
            plan_fingerprint="stage43g46-sealed-empty-prior-year",
            completed=[],
        )
        archive.seal_year(2026, expected_match_count=0)
        roster = CareerRosterArchive(cls.rosters)
        generator = PlayerRosterGenerator()
        seed_stage = cls.repo.stage_by_code(AOMORI_SPRING, "SEED_EVENT")
        cls.group_inputs = {}
        selected = []
        cls.expected_formats = set()
        groups = cls.repo.groups_by_stage[seed_stage["stage_id"]]
        assert len(groups) == 4
        for group in groups:
            gid = group["stage_group_id"]
            schools = sorted(cls.repo.group_school_ids(group, 2026))
            assert len(schools) >= 5, (gid, len(schools))
            chosen = schools[:min(len(schools), 8)]
            cls.group_inputs[gid] = chosen
            cls.expected_formats.add(cls.repo.group_format[gid]["format_model_id"])
            selected.extend(chosen)
        assert cls.expected_formats == {
            "FMT018", "FMT019", "FMT020", "FMT021"
        }
        assert len(selected) == len(set(selected))
        cls.aomori_ids = selected
        cls.tokushima_ids = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "36"
        )[:8]
        assert len(cls.tokushima_ids) == 8
        cls.specs = [
            {
                "competition_id": AOMORI_SPRING,
                "entry_mode": "aomori_seed_main_v1",
                "entrant_school_ids": selected,
                "group_entrant_school_ids": cls.group_inputs,
            },
            {
                "competition_id": TOKUSHIMA,
                "entry_mode": "shikoku_direct_main_v1",
                "entrant_school_ids": cls.tokushima_ids,
                "group_entrant_school_ids": {},
            },
        ]
        for sid in sorted(set(cls.aomori_ids + cls.tokushima_ids)):
            roster.save_initial_roster(
                generator.generate_for_school_id(
                    cls.repo, sid, 2026, SEED,
                )
            )
            roster.advance_and_save(
                cls.repo.team(sid), next_year=2027,
                career_seed=SEED,
            )

    @classmethod
    def tearDownClass(cls):
        cls.initial.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.slot = self.root / "aomori"
        self.slot.mkdir()
        shutil.copy2(self.history, self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.rosters, self.slot / "career_rosters.sqlite3")
        self.service = CareerMultiPreviewCheckpointService(
            self.repo, DATA, save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.third = AomoriThirdPlaceCheckpointService(self.service)
        self.archive = HistoricalMatchArchive(
            self.slot / "historical_matches.sqlite3",
        )

    def _start(self, specs=None):
        return self.service.start(
            "aomori", year=2027,
            competitions=self.specs if specs is None else specs,
            base_seed=SEED, career_seed=SEED,
        )

    def _finished(self):
        session = self._start()
        for _ in range(45):
            if AOMORI_SPRING in session.completed_runs():
                break
            step = self.service.play_next_date(session)
            self.assertGreater(step["played_match_count"], 0)
        self.assertIn(AOMORI_SPRING, session.completed_runs())
        return self.service.load("aomori", year=2027)

    def test_four_seed_group_models_to_main_save_replay_then_third(self):
        manual = self.slot / "manual.json"
        manual.write_bytes(b"2026 original is read-only")
        session = self._start()
        with self.assertRaisesRegex(ChibaThirdPlaceNotReady, "MAIN"):
            self.third.start("aomori", year=2027)
        first_seed_day = ""
        seed_dates = set()
        for _ in range(45):
            if AOMORI_SPRING in session.completed_runs():
                break
            step = self.service.play_next_date(session)
            if AOMORI_SPRING in step["competition_match_counts"]:
                if not first_seed_day:
                    first_seed_day = step["date"]
                    self.assertLess(first_seed_day, "2027-05-08")
                    before = self.service.load("aomori", year=2027)
                    self.assertEqual(
                        session.previews[AOMORI_SPRING].scheduled.public_snapshot(),
                        before.previews[AOMORI_SPRING].scheduled.public_snapshot(),
                    )
                seed_dates.add(step["date"])
        self.assertIn(AOMORI_SPRING, session.completed_runs())
        self.assertTrue(first_seed_day)
        self.assertGreater(len(seed_dates), 4)
        run = session.completed_runs()[AOMORI_SPRING]
        self.assertEqual(
            len(self.aomori_ids), len(run.main_entrant_school_ids),
        )
        self.assertEqual(
            len(self.aomori_ids) - 1, run.outcome.match_count,
        )
        self.assertGreater(len(run.seed_assignments), 0)
        self.assertTrue(any(
            stage.stage_code == "SEED_EVENT"
            for stage in run.stage_executions
        ))
        source = self.service.load("aomori", year=2027)
        records = self.archive.list_matches(2027, limit=1000)
        seed_games = [
            row for row in records
            if row["competition_id"] == AOMORI_SPRING
            and row["stage_code"] == "SEED_EVENT"
        ]
        main_games = [
            row for row in records
            if row["competition_id"] == AOMORI_SPRING
            and row["stage_code"] == "MAIN"
        ]
        self.assertGreater(len(seed_games), 0)
        self.assertEqual(len(self.aomori_ids) - 1, len(main_games))
        self.assertTrue(all(
            r["match_date"] < "2027-05-08" for r in seed_games
        ))
        self.assertTrue(all(
            r["match_date"] >= "2027-05-08" for r in main_games
        ))
        self.assertTrue(all(
            row["date_source"] == "game_projection_v1"
            and row["score_source"] == "ability_model_v1"
            and row["inning_scores"] and row["batter_stats"]
            and row["pitcher_stats"] for row in seed_games + main_games
        ))
        unresolved = project_same_year_regional_feeders(
            self.service, source, TOHOKU,
        )
        aomori = next(
            r for r in unresolved["feeder_rules"]
            if r["source_competition_id"] == AOMORI_SPRING
        )
        self.assertEqual("ranking_cutoff_requires_tiebreak_rule", aomori["status"])
        self.assertFalse(unresolved["all_feeder_results_verified"])

        with sqlite3.connect(self.archive.db_path) as db:
            prev = db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0]
            identity = db.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0]
        third = self.third.start("aomori", year=2027)
        self.assertEqual(AOMORI_SPRING, third["competition_id"])
        self.assertEqual(TOHOKU, third["destination_competition_id"])
        self.assertEqual("2027-05-24", third["match_date"])
        self.assertEqual(third, self.third.load("aomori", year=2027))
        actual_third = next(
            x for x in self.archive.list_matches(2027, limit=1000)
            if x["match_id"] == third["match_id"]
        )
        self.assertEqual("THIRD_PLACE", actual_third["phase_code"])
        self.assertTrue(actual_third["inning_scores"])
        self.assertTrue(actual_third["batter_stats"])
        self.assertTrue(actual_third["pitcher_stats"])
        gate = project_same_year_regional_feeders(
            self.service, source, TOHOKU,
            placement_decider_match_ids={
                AOMORI_SPRING: third["match_id"],
            },
        )
        qualified = next(
            r for r in gate["feeder_rules"]
            if r["source_competition_id"] == AOMORI_SPRING
        )
        self.assertEqual("verified_game_qualification", qualified["status"])
        self.assertEqual(3, len(qualified["school_ids"]))
        self.assertEqual(
            [*run.outcome.final_ranking_school_ids[:2],
             third["third_place_school_id"]],
            qualified["school_ids"],
        )
        self.assertEqual(3, gate["verified_entrant_count"])
        self.assertFalse(gate["all_feeder_results_verified"])
        self.assertEqual(5, len(gate["unresolved_feeder_rule_ids"]))
        with sqlite3.connect(self.archive.db_path) as db:
            self.assertEqual(prev, db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0])
            self.assertEqual(identity, db.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0])
        self.assertEqual(b"2026 original is read-only", manual.read_bytes())

    def test_bad_seed_membership_and_unarchived_game_rejected(self):
        bad = [{
            **x,
            "group_entrant_school_ids": {
                k: list(v) for k, v in x["group_entrant_school_ids"].items()
            },
        } for x in self.specs]
        gid = next(iter(bad[0]["group_entrant_school_ids"]))
        bad[0]["group_entrant_school_ids"][gid][0] = self.tokushima_ids[0]
        with self.assertRaises((CareerPreviewSaveError, FutureCompetitionNotReady)):
            self._start(bad)
        self.assertFalse(
            (self.slot / "career_multi_previews" / "2027.json").exists()
        )
        self._finished()
        with sqlite3.connect(self.archive.db_path) as db:
            row = db.execute(
                "SELECT match_id FROM historical_matches "
                "WHERE year=2027 AND competition_id=? "
                "AND json_extract(payload_json, '$.stage_code')='MAIN' LIMIT 1",
                (AOMORI_SPRING,),
            ).fetchone()
            db.execute(
                "DELETE FROM historical_matches WHERE year=2027 "
                "AND competition_id=? AND match_id=?",
                (AOMORI_SPRING, row[0]),
            )
        with self.assertRaises(ChibaThirdPlaceNotReady):
            self.third.start("aomori", year=2027)

    def test_third_place_checksum_and_cross_region_injection_fail(self):
        finished = self._finished()
        third = self.third.start("aomori", year=2027)
        with self.assertRaises(ChibaThirdPlaceNotReady):
            self.third.start("aomori", year=2027)
        with self.assertRaises(RegionalFeederNotReady):
            project_same_year_regional_feeders(
                self.service, finished, "CMP000011",
                placement_decider_match_ids={
                    AOMORI_SPRING: third["match_id"],
                },
            )
        with sqlite3.connect(self.archive.db_path) as db:
            db.execute(
                "UPDATE historical_matches SET payload_json=? "
                "WHERE year=2027 AND competition_id=? AND match_id=?",
                ('{"tampered":true}', AOMORI_SPRING, third["match_id"]),
            )
        with self.assertRaises(RegionalFeederNotReady):
            project_same_year_regional_feeders(
                self.service, finished, TOHOKU,
                placement_decider_match_ids={
                    AOMORI_SPRING: third["match_id"],
                },
            )


if __name__ == "__main__":
    unittest.main()
