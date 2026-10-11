"""Stage43G-45: Akita's third representative needs a saved placement game.

The 2027 qualifier input and its match results are entirely simulated.
Six-prefecture Tohoku is NOT runnable until all six feeders are verified.
"""
from __future__ import annotations

import json
from pathlib import Path
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
    AkitaThirdPlaceCheckpointService,
    ChibaThirdPlaceNotReady,
)
from phase2_engine.future_akita_direct_main_bridge import (
    prepare_future_akita_direct_main_preview,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository
from phase2_engine.same_year_regional_feeder_gate import (
    RegionalFeederNotReady, project_same_year_regional_feeders,
)

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026101145
AKITA = "CMP000078"
TOKUSHIMA = "CMP000139"
TOHOKU = "CMP000005"


class Stage43G45AkitaThirdPlaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.fixture = tempfile.TemporaryDirectory()
        base = Path(cls.fixture.name)
        cls.history = base / "history.sqlite3"
        cls.rosters = base / "rosters.sqlite3"
        hist = HistoricalMatchArchive(cls.history)
        hist.sync(
            year=2026, rng_seed=SEED, resolver_contract="game_v1",
            plan_fingerprint="stage43g45-sealed-test-previous-year",
            completed=[],
        )
        hist.seal_year(2026, expected_match_count=0)
        rosters = CareerRosterArchive(cls.rosters)
        generator = PlayerRosterGenerator()
        cls.akita_ids = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "05"
        )[:8]
        cls.tokushima_ids = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "36"
        )[:8]
        assert len(cls.akita_ids) == len(cls.tokushima_ids) == 8
        cls.specs = [
            {
                "competition_id": AKITA,
                "entry_mode": "akita_direct_main_v1",
                "entrant_school_ids": cls.akita_ids,
                "group_entrant_school_ids": {},
            },
            {
                "competition_id": TOKUSHIMA,
                "entry_mode": "shikoku_direct_main_v1",
                "entrant_school_ids": cls.tokushima_ids,
                "group_entrant_school_ids": {},
            },
        ]
        for sid in sorted(set(cls.akita_ids + cls.tokushima_ids)):
            rosters.save_initial_roster(
                generator.generate_for_school_id(cls.repo, sid, 2026, SEED),
            )
            rosters.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=SEED,
            )

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.slot = self.root / "akita"
        self.slot.mkdir()
        shutil.copy2(self.history, self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.rosters, self.slot / "career_rosters.sqlite3")
        self.multi = CareerMultiPreviewCheckpointService(
            self.repo, ROOT / "data", save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.third = AkitaThirdPlaceCheckpointService(self.multi)
        self.hist = HistoricalMatchArchive(
            self.slot / "historical_matches.sqlite3",
        )

    def _start(self):
        return self.multi.start(
            "akita", year=2027, competitions=self.specs,
            base_seed=SEED, career_seed=SEED,
        )

    def _finish(self):
        session = self._start()
        for _ in range(20):
            if len(session.completed_runs()) == 2:
                break
            self.multi.play_next_date(session)
        self.assertEqual(2, len(session.completed_runs()))
        self.assertEqual(14, session.summary()["completed_match_count"])
        return self.multi.load("akita", year=2027)

    def test_akita_third_decider_saved_A_stats_and_partial_tohoku_entitlement(self):
        original = self.slot / "manual.json"
        original.write_bytes(b"manual 2026 original")
        session = self._start()
        with self.assertRaisesRegex(ChibaThirdPlaceNotReady, "MAIN"):
            self.third.start("akita", year=2027)
        for _ in range(20):
            if len(session.completed_runs()) == 2:
                break
            self.multi.play_next_date(session)
        replay = self.multi.load("akita", year=2027)
        self.assertEqual(2, len(replay.completed_runs()))
        no_decider = project_same_year_regional_feeders(
            self.multi, replay, TOHOKU,
        )
        self.assertEqual(6, no_decider["feeder_rule_count"])
        self.assertFalse(no_decider["all_feeder_results_verified"])
        before = next(
            r for r in no_decider["feeder_rules"]
            if r["source_competition_id"] == AKITA
        )
        self.assertEqual("ranking_cutoff_requires_tiebreak_rule", before["status"])
        self.assertEqual(0, no_decider["verified_entrant_count"])

        with sqlite3.connect(self.hist.db_path) as db:
            old_ledger = db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0]
            identity = db.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0]
        third = self.third.start("akita", year=2027)
        self.assertEqual(AKITA, third["competition_id"])
        self.assertEqual(TOHOKU, third["destination_competition_id"])
        self.assertEqual("2027-05-24", third["match_date"])
        self.assertIn(third["third_place_school_id"], self.akita_ids)
        self.assertEqual(2, len(third["semifinal_loser_school_ids"]))
        self.assertIn(
            third["third_place_school_id"],
            third["semifinal_loser_school_ids"],
        )
        self.assertEqual(third, self.third.load("akita", year=2027))
        games = self.hist.list_matches(2027, limit=500)
        extra = next(r for r in games if r["match_id"] == third["match_id"])
        self.assertEqual("THIRD_PLACE", extra["phase_code"])
        self.assertEqual("PLACEMENT", extra["stage_code"])
        self.assertEqual("ability_model_v1", extra["score_source"])
        self.assertEqual("game_projection_v1", extra["date_source"])
        self.assertTrue(extra["inning_scores"])
        self.assertTrue(extra["batter_stats"])
        self.assertTrue(extra["pitcher_stats"])
        self.assertEqual(15, len(games))
        qualified = project_same_year_regional_feeders(
            self.multi, replay, TOHOKU,
            placement_decider_match_ids={AKITA: third["match_id"]},
        )
        self.assertFalse(qualified["all_feeder_results_verified"])
        self.assertEqual(3, qualified["verified_entrant_count"])
        self.assertEqual(5, len(qualified["unresolved_feeder_rule_ids"]))
        akita_rule = next(
            r for r in qualified["feeder_rules"]
            if r["source_competition_id"] == AKITA
        )
        actual_top_two = replay.completed_runs()[AKITA].outcome.final_ranking_school_ids[:2]
        self.assertEqual(
            [*actual_top_two, third["third_place_school_id"]],
            akita_rule["school_ids"],
        )
        self.assertEqual("verified_game_qualification", akita_rule["status"])
        self.assertEqual(64, len(akita_rule["evidence_sha256"]))
        self.assertFalse(qualified["regional_runtime_ready"])
        with sqlite3.connect(self.hist.db_path) as db:
            self.assertEqual(old_ledger, db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0])
            self.assertEqual(identity, db.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0])
        self.assertEqual(original.read_bytes(), b"manual 2026 original")

    def test_bad_match_id_cross_region_injection_and_double_creation_rejected(self):
        self._finish()
        decider = self.third.start("akita", year=2027)
        with self.assertRaisesRegex(ChibaThirdPlaceNotReady, "already"):
            self.third.start("akita", year=2027)
        replay = self.multi.load("akita", year=2027)
        with self.assertRaisesRegex(RegionalFeederNotReady, "missing|modified"):
            project_same_year_regional_feeders(
                self.multi, replay, TOHOKU,
                placement_decider_match_ids={AKITA: "FAKE-THIRD-ID"},
            )
        with self.assertRaisesRegex(RegionalFeederNotReady, "another destination"):
            project_same_year_regional_feeders(
                self.multi, replay, "CMP000011",
                placement_decider_match_ids={AKITA: decider["match_id"]},
            )
        with self.assertRaisesRegex(RegionalFeederNotReady, "unrecognized"):
            project_same_year_regional_feeders(
                self.multi, replay, TOHOKU,
                placement_decider_match_ids={"CMP000077": decider["match_id"]},
            )

    def test_placement_tampering_and_untracked_rank_order_rejected(self):
        session = self._finish()
        third = self.third.start("akita", year=2027)
        # A complete MAIN ranking by itself cannot supply a unique third.
        self.assertFalse(project_same_year_regional_feeders(
            self.multi, session, TOHOKU,
        )["all_feeder_results_verified"])
        with sqlite3.connect(self.hist.db_path) as db:
            db.execute(
                "UPDATE historical_matches SET payload_json=? "
                "WHERE year=2027 AND competition_id=? AND match_id=?",
                ('{"malicious": true}', AKITA, third["match_id"]),
            )
        with self.assertRaisesRegex(RegionalFeederNotReady, "missing|modified"):
            project_same_year_regional_feeders(
                self.multi, session, TOHOKU,
                placement_decider_match_ids={AKITA: third["match_id"]},
            )
        with self.assertRaises(ChibaThirdPlaceNotReady):
            self.third.load("akita", year=2027)

    def test_akita_school_membership_is_enforced(self):
        from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
        with self.assertRaisesRegex(FutureCompetitionNotReady, "outside"):
            prepare_future_akita_direct_main_preview(
                data_root=ROOT / "data", year=2027,
                competition_id=AKITA,
                entrant_school_ids=[
                    *self.akita_ids[:7], self.tokushima_ids[0],
                ],
                roster_archive=CareerRosterArchive(
                    self.slot / "career_rosters.sqlite3",
                ),
                repo=self.repo, base_seed=SEED, career_seed=SEED,
            )


if __name__ == "__main__":
    unittest.main()
