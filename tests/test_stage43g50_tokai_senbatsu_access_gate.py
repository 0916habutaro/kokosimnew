"""Stage43G-50: a complete saved same-year Senbatsu certifies Tokai byes.

The 2027 player/game selections here are fabricated simulation fixtures,
never actual national invitational participant or match results.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_tokai_senbatsu_access_gate import (
    CareerTokaiSenbatsuAccessService, TokaiSenbatsuNotReady,
    certify_saved_tokai_senbatsu, SENBATSU_ID,
)
from phase2_engine.historical_match_archive import (
    HistoricalMatchArchive, HistoricalMatchConflictError,
)
from phase2_engine.repository import DataRepository
from phase2_engine.career_preview_checkpoint import CareerPreviewSaveError

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026101150
AICHI = "CMP000113"
MIE = "CMP000115"


class Stage43G50TokaiSenbatsuAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.fixture = tempfile.TemporaryDirectory()
        folder = Path(cls.fixture.name)
        cls.history = folder / "historical_matches.sqlite3"
        cls.rosters = folder / "career_rosters.sqlite3"
        source = HistoricalMatchArchive(cls.history)
        source.sync(
            year=2026, rng_seed=SEED,
            resolver_contract="game_v1",
            plan_fingerprint="stage43g50-sealed-previous",
            completed=[],
        )
        source.seal_year(2026, expected_match_count=0)
        aichi = sorted(s for s in cls.repo.school_to_program
                       if cls.repo.schools[s]["prefecture_code"] == "23")[:2]
        mie = sorted(s for s in cls.repo.school_to_program
                     if cls.repo.schools[s]["prefecture_code"] == "24")[:2]
        others = sorted(s for s in cls.repo.school_to_program
                        if cls.repo.schools[s]["prefecture_code"] not in {"23", "24"})[:32]
        tochigi = sorted(s for s in cls.repo.school_to_program
                         if cls.repo.schools[s]["prefecture_code"] == "09")[:8]
        gunma = sorted(s for s in cls.repo.school_to_program
                       if cls.repo.schools[s]["prefecture_code"] == "10")[:8]
        assert len(aichi) == len(mie) == 2
        assert len(others) == 32
        cls.aichi = aichi
        cls.mie = mie
        cls.with_two_each = [*others[:28], *aichi, *mie]
        cls.zero = others
        cls.companion = {
            "competition_id": "CMP000086",
            "entry_mode": "kanto_direct_main_v1",
            "entrant_school_ids": tochigi,
            "group_entrant_school_ids": {},
        }
        cls.gunma_companion = {
            "competition_id": "CMP000088",
            "entry_mode": "kanto_direct_main_v1",
            "entrant_school_ids": gunma,
            "group_entrant_school_ids": {},
        }
        rosters = CareerRosterArchive(cls.rosters)
        generator = PlayerRosterGenerator()
        for sid in sorted(set(others+aichi+mie+tochigi+gunma)):
            rosters.save_initial_roster(
                generator.generate_for_school_id(cls.repo, sid, 2026, SEED)
            )
            rosters.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=SEED
            )

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.slot = self.root / "tokai"
        self.slot.mkdir()
        shutil.copy2(self.history, self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.rosters, self.slot / "career_rosters.sqlite3")
        self.multi = CareerMultiPreviewCheckpointService(
            self.repo, ROOT / "data", save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.gate = CareerTokaiSenbatsuAccessService(self.multi)
        self.hist = HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")

    def _start(self, *, school_ids=None, national=True):
        source = {
            "competition_id": SENBATSU_ID,
            "entry_mode": "national_invitational_main_v1",
            "entrant_school_ids": self.with_two_each if school_ids is None else school_ids,
            "group_entrant_school_ids": {},
        }
        specs = [source, self.companion] if national else [
            self.companion, self.gunma_companion,
        ]
        return self.multi.start(
            "tokai", year=2027, competitions=specs,
            base_seed=SEED, career_seed=SEED,
        )

    def _finish(self, *, school_ids=None):
        session = self._start(school_ids=school_ids)
        for _ in range(18):
            if SENBATSU_ID in session.completed_runs():
                break
            step = self.multi.play_next_date(session)
            self.assertGreater(step["played_match_count"], 0)
        self.assertIn(SENBATSU_ID, session.completed_runs())
        return self.multi.load("tokai", year=2027)

    def test_complete_31_A_games_certifies_two_prefectures_and_reports_overlap(self):
        manual = self.slot / "manual.json"
        manual.write_bytes(b"existing save")
        session = self._start()
        pending = self.gate.audit("tokai", year=2027)
        self.assertEqual("complete_saved_senbatsu_required", pending["status"])
        self.assertIsNone(pending["participants_by_prefecture"])
        self.assertFalse(pending["zero_senbatsu_entrants_confirmed"])
        self.assertFalse(pending["automatic_bypass_enabled"])
        with sqlite3.connect(self.hist.db_path) as db:
            prior_sha = db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0]
            year_metadata = db.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0]
        self.multi.play_next_date(session)
        still_pending = self.gate.audit("tokai", year=2027)
        self.assertEqual("complete_saved_senbatsu_required", still_pending["status"])
        for _ in range(17):
            if SENBATSU_ID in session.completed_runs():
                break
            self.multi.play_next_date(session)
        self.assertIn(SENBATSU_ID, session.completed_runs())
        proof = self.gate.audit("tokai", year=2027)
        self.assertEqual("complete_same_year_saved_senbatsu_verified", proof["status"])
        self.assertTrue(proof["full_same_year_saved_A_games_verified"])
        self.assertEqual(31, proof["source_match_count"])
        self.assertEqual(32, proof["source_entrant_count"])
        self.assertGreaterEqual(proof["source_last_game_date"], "2027-03-20")
        self.assertLess(proof["source_last_game_date"], "2027-04-11")
        self.assertEqual(64, len(proof["source_games_sha256"]))
        self.assertEqual(self.aichi, proof["prefectures"][AICHI][
            "eligible_direct_main_school_ids"])
        self.assertEqual(self.mie, proof["prefectures"][MIE][
            "eligible_direct_main_school_ids"])
        self.assertEqual(2, proof["prefectures"][AICHI]["verified_participant_count"])
        self.assertEqual(2, proof["prefectures"][MIE]["verified_participant_count"])
        self.assertEqual("ACR000012", proof["prefectures"][AICHI]["access_rule_id"])
        self.assertEqual("ACR000013", proof["prefectures"][MIE]["access_rule_id"])
        self.assertEqual("FMT010", proof["prefectures"][AICHI]["qualifier_format"])
        self.assertEqual("FMT016", proof["prefectures"][MIE]["qualifier_format"])
        self.assertEqual("2027-03-20", proof["prefectures"][AICHI][
            "qualifier_first_projected_date"])
        self.assertTrue(proof["schedule_conflict_requires_separate_activation_contract"])
        self.assertFalse(proof["automatic_bypass_enabled"])
        self.assertFalse(proof["regional_runtime_ready"])
        self.assertEqual([], proof["prefectures"][AICHI]["main_seed_school_ids"])
        self.assertEqual(proof, self.gate.audit("tokai", year=2027))
        records = [m for m in self.hist.list_matches(2027, limit=200)
                   if m["competition_id"] == SENBATSU_ID]
        self.assertEqual(31, len(records))
        self.assertTrue(all(
            m["inning_scores"] and m["batter_stats"] and m["pitcher_stats"]
            for m in records
        ))
        with sqlite3.connect(self.hist.db_path) as db:
            self.assertEqual(prior_sha, db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0])
            self.assertEqual(year_metadata, db.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0])
        self.assertEqual(manual.read_bytes(), b"existing save")
        self.assertFalse((self.slot / "career_regional_previews" /
                          "2027_CMP000008.json").exists())

    def test_complete_source_can_prove_true_zero_not_missing_source(self):
        source = self._finish(school_ids=self.zero)
        proof = self.gate.audit("tokai", year=2027)
        self.assertEqual([], proof["prefectures"][AICHI][
            "eligible_direct_main_school_ids"])
        self.assertEqual([], proof["prefectures"][MIE][
            "eligible_direct_main_school_ids"])
        self.assertTrue(proof["full_same_year_saved_A_games_verified"])
        self.assertFalse(proof["automatic_bypass_enabled"])

    def test_missing_senbatsu_does_not_imply_zero(self):
        self._start(national=False)
        result = self.gate.audit("tokai", year=2027)
        self.assertEqual("complete_saved_senbatsu_required", result["status"])
        self.assertIsNone(result["participants_by_prefecture"])
        self.assertFalse(result["zero_senbatsu_entrants_confirmed"])

    def test_different_year_partial_run_and_tampered_SQLite_are_rejected(self):
        session = self._finish()
        run = session.completed_runs()[SENBATSU_ID]
        with self.assertRaises(TokaiSenbatsuNotReady):
            certify_saved_tokai_senbatsu(
                self.repo, self.hist, run, year=2028,
            )
        partial = deepcopy(run)
        main = next(s for s in partial.stage_executions if s.stage_code == "MAIN")
        main.matches.pop()
        with self.assertRaises(TokaiSenbatsuNotReady):
            certify_saved_tokai_senbatsu(
                self.repo, self.hist, partial, year=2027,
            )
        with sqlite3.connect(self.hist.db_path) as db:
            mid = db.execute(
                "SELECT match_id FROM historical_matches "
                "WHERE year=2027 AND competition_id=? LIMIT 1",
                (SENBATSU_ID,),
            ).fetchone()[0]
            db.execute(
                "UPDATE historical_matches SET payload_json=? "
                "WHERE year=2027 AND competition_id=? AND match_id=?",
                ('{"tampered":true}', SENBATSU_ID, mid),
            )
        with self.assertRaises(TokaiSenbatsuNotReady):
            certify_saved_tokai_senbatsu(
                self.repo, self.hist, run, year=2027,
            )
        with self.assertRaises((
            TokaiSenbatsuNotReady, CareerPreviewSaveError,
            HistoricalMatchConflictError, ValueError,
        )):
            self.gate.audit("tokai", year=2027)


if __name__ == "__main__":
    unittest.main()
