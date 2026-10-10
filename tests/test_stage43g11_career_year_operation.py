from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService,
)
from phase2_engine.career_preview_checkpoint import (
    CareerPreviewSaveError, _checksum,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_year_operation import (
    CareerYearOperationService, CareerYearPolicyBlocked,
    EXPECTED_2026_KANTO,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository


ROOT = Path(__file__).resolve().parents[1]
SEED = 2026100701


class Stage43G11YearOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.history_source = root / "history.sqlite3"
        cls.roster_source = root / "rosters.sqlite3"
        history = HistoricalMatchArchive(cls.history_source)
        history.sync(
            year=2026, rng_seed=SEED, resolver_contract="game_v1",
            plan_fingerprint="stage43g11-sealed-year", completed=[],
        )
        history.seal_year(2026, expected_match_count=0)
        rosters = CareerRosterArchive(cls.roster_source)
        factory = PlayerRosterGenerator()
        cls.specs = []
        for cid, pref in (("CMP000086", "09"), ("CMP000088", "10")):
            school_ids = sorted(
                sid for sid in cls.repo.school_to_program
                if cls.repo.schools[sid]["prefecture_code"] == pref
            )[:8]
            assert len(school_ids) == 8
            cls.specs.append({
                "competition_id": cid, "entry_mode": "kanto_direct_main_v1",
                "entrant_school_ids": school_ids,
                "group_entrant_school_ids": {},
            })
            for sid in school_ids:
                rosters.save_initial_roster(
                    factory.generate_for_school_id(cls.repo, sid, 2026, SEED)
                )
                rosters.advance_and_save(
                    cls.repo.team(sid), next_year=2027, career_seed=SEED,
                )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.tmp_run = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_run.name)
        self.slot = self.root / "slot"
        self.slot.mkdir()
        shutil.copy2(
            self.history_source, self.slot / "historical_matches.sqlite3",
        )
        shutil.copy2(
            self.roster_source, self.slot / "career_rosters.sqlite3",
        )
        self.multi = CareerMultiPreviewCheckpointService(
            self.repo, ROOT / "data", save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.service = CareerYearOperationService(self.multi)

    def tearDown(self):
        self.tmp_run.cleanup()

    def start(self):
        return self.multi.start(
            "slot", year=2027, competitions=self.specs,
            base_seed=SEED, career_seed=SEED,
        )

    def test_registration_requires_committed_same_year_save(self):
        with self.assertRaises(CareerPreviewSaveError):
            self.service.register(
                "slot", year=2027, host_prefecture_code="12",
            )
        self.start()
        result = self.service.register(
            "slot", year=2027, host_prefecture_code="12",
        )
        self.assertTrue(result["regional_game_projection_supported"])
        self.assertEqual(EXPECTED_2026_KANTO,
                         result["region_berth_quota_by_prefecture"])
        self.assertEqual(17, result["region_expected_school_count"])
        self.assertEqual(2026, result["region_source_structure_year"])
        self.assertFalse(result["year_official_rules_verified"])
        self.assertFalse(result["full_year_runtime_enabled"])
        self.assertEqual(result, self.service.load("slot", year=2027))
        self.assertEqual(result, self.service.register(
            "slot", year=2027, host_prefecture_code="12",
        ))

    def test_venue_change_blocks_stale_quota_without_guessing_next_host_slots(self):
        self.start()
        alternate = self.service.register(
            "slot", year=2027, host_prefecture_code="11",
        )
        self.assertFalse(alternate["regional_game_projection_supported"])
        self.assertTrue(alternate["regional_rule_refresh_required"])
        self.assertIsNone(alternate["region_berth_quota_by_prefecture"])
        self.assertIsNone(alternate["region_expected_school_count"])
        status = self.service.audit("slot", year=2027)
        self.assertIn("host_or_regional_berths_require_rule_refresh",
                      status["blockers"])
        self.assertFalse(status["regional_runtime_ready"])
        with self.assertRaisesRegex(CareerYearPolicyBlocked, "revalidated"):
            self.service.start_regional("slot", year=2027)
        with self.assertRaisesRegex(CareerYearPolicyBlocked, "locked differently"):
            self.service.register(
                "slot", year=2027, host_prefecture_code="12",
            )

    def test_unselected_host_is_not_assumed_to_be_2026_chiba(self):
        self.start()
        policy = self.service.register("slot", year=2027)
        self.assertIsNone(policy["host_prefecture_code"])
        self.assertIsNone(policy["region_berth_quota_by_prefecture"])
        self.assertEqual("unresolved", policy["host_choice_source"])
        with self.assertRaises(CareerYearPolicyBlocked):
            self.service.start_regional("slot", year=2027)

    def test_invalid_host_rejected_and_no_rulebook_written(self):
        self.start()
        for host in ("01", "47", "", 12, True):
            with self.subTest(host=host), self.assertRaises(
                CareerYearPolicyBlocked,
            ):
                self.service.register(
                    "slot", year=2027, host_prefecture_code=host,
                )
        self.assertFalse(self.service._path("slot", 2027).exists())

    def test_partial_annual_game_never_promotes_regional_or_full_year(self):
        self.start()
        self.service.register("slot", year=2027, host_prefecture_code="12")
        status = self.service.audit("slot", year=2027)
        self.assertEqual(
            ["CMP000086", "CMP000088"],
            status["registered_competition_ids"],
        )
        self.assertEqual([], status["completed_competition_ids"])
        self.assertIn("yearly_registered_competitions_incomplete",
                      status["blockers"])
        self.assertFalse(status["regional_runtime_ready"])
        self.assertFalse(status["full_year_gameplay_available"])
        with self.assertRaises(CareerYearPolicyBlocked):
            self.service.start_regional("slot", year=2027)
        ready = self.service.next_year_readiness("slot", year=2027)
        self.assertEqual(2028, ready["next_year"])
        self.assertFalse(ready["auto_rollover_ready"])
        self.assertFalse(ready["unbounded_years_implemented"])

    def test_resume_one_game_day_preserves_2026_history_and_existing_save(self):
        existing = self.slot / "autosave.json"
        existing.write_bytes(b"original 2026 save")
        self.start()
        self.service.register("slot", year=2027, host_prefecture_code="12")
        result = self.service.next_date("slot", year=2027)
        self.assertEqual("2027-04-11", result["date"])
        self.assertGreater(result["played_match_count"], 0)
        replay = self.multi.load("slot", year=2027)
        self.assertEqual(["2027-04-11"], replay.processed_dates)
        self.assertEqual(b"original 2026 save", existing.read_bytes())
        self.assertEqual(
            "sealed",
            HistoricalMatchArchive(
                self.slot / "historical_matches.sqlite3"
            ).list_years()[0]["status"],
        )
        self.assertEqual(
            self.service.load("slot", year=2027)["host_prefecture_code"], "12",
        )

    def test_completed_subset_without_kanagawa_or_chiba_still_not_region(self):
        self.start()
        self.service.register("slot", year=2027, host_prefecture_code="12")
        session = self.multi.load("slot", year=2027)
        for _ in range(10):
            if all(p.scheduled.is_complete for p in session.previews.values()):
                break
            self.multi.play_next_date(session)
        self.assertEqual(2, len(session.completed_runs()))
        audit = self.service.audit("slot", year=2027)
        self.assertIn("same_year_kanagawa_qualification_not_registered",
                      audit["blockers"])
        self.assertFalse(audit["regional_runtime_ready"])
        self.assertFalse(self.service.next_year_readiness(
            "slot", year=2027,
        )["auto_rollover_ready"])

    def test_recomputed_checksum_cannot_change_venue_or_annual_binding(self):
        self.start()
        self.service.register("slot", year=2027, host_prefecture_code="12")
        path = self.service._path("slot", 2027)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["host_prefecture_code"] = "11"
        raw["payload_checksum"] = _checksum(raw)
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(CareerYearPolicyBlocked, "no longer matches"):
            self.service.load("slot", year=2027)
        # A stale annual plan is likewise not accepted as an unchanged rulebook.
        raw["host_prefecture_code"] = "12"
        raw["annual_plan_fingerprint"] = "FAKE"
        raw["payload_checksum"] = _checksum(raw)
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(CareerYearPolicyBlocked):
            self.service.load("slot", year=2027)

    def test_rule_csv_drift_is_detected_without_rewriting_existing_save(self):
        self.start()
        self.service.register("slot", year=2027, host_prefecture_code="12")
        original = self.service._feeder_rules()
        changed = [dict(row) for row in original]
        changed[0]["primary_source_id"] = "TAMPERED"
        with patch.object(self.service, "_feeder_rules", return_value=changed):
            with self.assertRaisesRegex(CareerYearPolicyBlocked, "no longer matches"):
                self.service.load("slot", year=2027)
        self.assertEqual(
            "12", self.service.load("slot", year=2027)["host_prefecture_code"],
        )


if __name__ == "__main__":
    unittest.main()
