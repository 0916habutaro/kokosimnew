from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_longitudinal_read import (
    CareerHistoryViewConflict, CareerLongitudinalReadModel,
)
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService,
)
from phase2_engine.career_preview_checkpoint import CareerPreviewSaveError, _checksum
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_year_continuity import (
    CareerYearContinuityBlocked, CareerYearContinuityService,
)
from phase2_engine.career_year_operation import CareerYearOperationService
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.live_season_save import (
    SAVE_SCHEMA_VERSION, rechecksum_live_season_save_payload,
)
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026100701


def historical_game(year, school1, school2):
    return {
        "competition_id": "CMP000086",
        "match_id": f"TEST-ARCHIVED-{year}",
        "competition_name": "ゲーム用保存済み大会",
        "match_date": f"{year}-05-01",
        "completed_on": f"{year}-05-01",
        "date_source": "game_projection_v1",
        "status": "completed", "stage_code": "MAIN",
        "phase_code": "MAIN_BRACKET", "round_no": 1,
        "team1_id": school1, "team2_id": school2,
        "team1_score": 5, "team2_score": 3,
        "winner_id": school1, "loser_id": school2,
        "score_source": "generated_v1",
    }


def legacy_save(year=2026):
    body = {
        "schema_version": SAVE_SCHEMA_VERSION,
        "year": year, "rng_seed": SEED,
        "resolver_contract": "default_deterministic_v1",
        "plan_fingerprint": "not-equivalent-to-career-plan",
        "start_date": f"{year}-01-01",
        "current_date": f"{year}-01-01",
        "processed_dates": [],
        "completed_match_results": {},
        "status_by_competition": {},
        "activated_on": {},
        "runtime_summary": {"scope": "legacy_fixture_only"},
        "public_snapshot_fingerprint": "fixture-snapshot",
        "history": [],
    }
    return rechecksum_live_season_save_payload(body)


class Stage43G12YearContinuityAndReadModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.fixture = tempfile.TemporaryDirectory()
        root = Path(cls.fixture.name)
        cls.source_history = root / "history.sqlite3"
        cls.source_rosters = root / "rosters.sqlite3"
        cls.schools = {}
        for cid, prefecture in (
            ("CMP000086", "09"), ("CMP000088", "10"),
        ):
            selected = sorted(
                sid for sid in cls.repo.school_to_program
                if cls.repo.schools[sid]["prefecture_code"] == prefecture
            )[:8]
            assert len(selected) == 8
            cls.schools[cid] = selected
        cls.specs = [
            {
                "competition_id": cid,
                "entry_mode": "kanto_direct_main_v1",
                "entrant_school_ids": schools,
                "group_entrant_school_ids": {},
            }
            for cid, schools in cls.schools.items()
        ]
        first, second = cls.schools["CMP000086"][:2]
        archive = HistoricalMatchArchive(cls.source_history)
        archive.sync(
            year=2026, rng_seed=SEED, resolver_contract="game_v1",
            plan_fingerprint="stage43g12-sealed-prior",
            completed=[historical_game(2026, first, second)],
        )
        archive.seal_year(2026, expected_match_count=1)
        rosters = CareerRosterArchive(cls.source_rosters)
        generator = PlayerRosterGenerator()
        for sid in sorted({x for group in cls.schools.values() for x in group}):
            rosters.save_initial_roster(
                generator.generate_for_school_id(cls.repo, sid, 2026, SEED)
            )
            rosters.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=SEED,
            )

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.slot = self.root / "testslot"
        self.slot.mkdir()
        shutil.copy2(
            self.source_history, self.slot / "historical_matches.sqlite3",
        )
        shutil.copy2(
            self.source_rosters, self.slot / "career_rosters.sqlite3",
        )
        self.multi = CareerMultiPreviewCheckpointService(
            self.repo, ROOT / "data", save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.continuity = CareerYearContinuityService(self.multi)
        self.read = CareerLongitudinalReadModel(
            self.slot / "historical_matches.sqlite3",
            self.slot / "career_rosters.sqlite3",
        )

    def tearDown(self):
        self.temp.cleanup()

    def start(self):
        return self.multi.start(
            "testslot", year=2027,
            competitions=self.specs,
            base_seed=SEED, career_seed=SEED,
        )

    def test_linked_sealed_year_roster_graduates_and_returnees_are_proven(self):
        self.start()
        body = self.continuity.register("testslot", year=2027)
        self.assertEqual(2026, body["previous_year"])
        self.assertEqual(16, body["verified_school_count"])
        self.assertEqual(16 * 20, body["current_year_player_count"])
        self.assertEqual(16 * 12, body["returning_player_count"])
        self.assertEqual(16 * 8, body["graduated_from_previous_roster_count"])
        self.assertEqual(16 * 8, body["newcomer_player_count"])
        self.assertFalse(body["original_2026_live_results_imported"])
        self.assertFalse(body["original_2026_and_career_simulation_equivalent"])
        self.assertEqual(body, self.continuity.load("testslot", year=2027))
        ready = self.continuity.readiness("testslot", year=2027)
        self.assertTrue(ready["roster_lineage_verified"])
        self.assertFalse(ready["automatic_next_year_start_ready"])
        self.assertFalse(ready["legacy_save_results_migrated"])
        operational = CareerYearOperationService(self.multi).audit(
            "testslot", year=2027,
        )
        self.assertTrue(operational["career_year_continuity_verified"])
        self.assertTrue(operational["historical_school_player_index_ready"])
        self.assertFalse(operational["full_year_gameplay_available"])
        self.assertFalse(operational["original_2026_live_save_imported"])

    def test_2026_live_save_must_remain_read_only_not_mistaken_for_career_source(self):
        self.start()
        raw = legacy_save()
        path = self.slot / "manual.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        body = self.continuity.register(
            "testslot", year=2027, legacy_source="manual",
        )
        self.assertTrue(body["original_2026_save"]["reference_only"])
        self.assertEqual("manual", body["original_2026_save"]["source"])
        self.assertEqual(raw["payload_checksum"],
                         body["original_2026_save"]["payload_checksum"])
        self.assertFalse(body["original_2026_live_results_imported"])
        self.assertEqual(raw, json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(body, self.continuity.load("testslot", year=2027))
        raw["rng_seed"] = SEED + 1
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(CareerYearContinuityBlocked):
            self.continuity.load("testslot", year=2027)

    def test_wrong_legacy_year_and_no_legacy_file_fail_closed(self):
        self.start()
        with self.assertRaises(CareerYearContinuityBlocked):
            self.continuity.register(
                "testslot", year=2027, legacy_source="manual",
            )
        (self.slot / "manual.json").write_text(
            json.dumps(legacy_save(2025)), encoding="utf-8",
        )
        with self.assertRaises(CareerYearContinuityBlocked):
            self.continuity.register(
                "testslot", year=2027, legacy_source="manual",
            )
        self.assertFalse(
            self.continuity._path("testslot", 2027).exists()
        )

    def test_registered_link_is_immutable_and_checksum_rewrite_is_rejected(self):
        self.start()
        original = self.continuity.register("testslot", year=2027)
        with self.assertRaisesRegex(CareerYearContinuityBlocked, "locked"):
            self.continuity.register(
                "testslot", year=2027, legacy_source="manual",
            )
        target = self.continuity._path("testslot", 2027)
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["roster_lineage_sha256"] = "TAMPERED"
        payload["payload_checksum"] = _checksum(payload)
        target.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(CareerYearContinuityBlocked):
            self.continuity.load("testslot", year=2027)
        self.assertNotEqual(original, payload)

    def test_previous_sealed_ledger_modification_is_detected(self):
        self.start()
        self.continuity.register("testslot", year=2027)
        archive = self.slot / "historical_matches.sqlite3"
        with sqlite3.connect(archive) as conn:
            conn.execute(
                "UPDATE historical_matches SET record_sha256='ALTERED' "
                "WHERE year=2026"
            )
        with self.assertRaises(CareerPreviewSaveError):
            self.continuity.load("testslot", year=2027)

    def test_school_results_across_year_and_player_history_uses_index(self):
        self.start()
        session = self.multi.load("testslot", year=2027)
        self.multi.play_next_date(session)
        first, second = self.schools["CMP000086"][:2]
        scores = self.read.school_results(
            first, start_year=2026, end_year=2027,
        )
        self.assertGreaterEqual(scores["total_groups"], 2)
        self.assertEqual(2026, scores["records"][0]["year"])
        self.assertTrue(any(row["year"] == 2027 for row in scores["records"]))
        self.assertTrue(all(row["games"] == row["wins"] + row["losses"]
                            for row in scores["records"]))
        self.assertFalse(scores["rankings_inferred"])
        roster = self.multi.solo._rosters("testslot").roster(2026, first)
        survivor = next(p for p in roster.players if p.academic_year == 1)
        years = self.read.player_years(survivor.player_id)
        self.assertEqual([2026, 2027], [row["year"] for row in years])
        self.assertEqual([1, 2], [row["academic_year"] for row in years])

    def test_player_index_pages_include_former_players_without_name_heuristics(self):
        self.start()
        school = self.schools["CMP000086"][0]
        first = self.read.school_player_index(school, limit=17)
        second = self.read.school_player_index(school, limit=17, offset=17)
        self.assertEqual(28, first["total"])
        self.assertEqual(17, len(first["players"]))
        self.assertEqual(11, len(second["players"]))
        all_players = first["players"] + second["players"]
        self.assertEqual(28, len({p["player_id"] for p in all_players}))
        self.assertEqual(
            8, sum(p["latest_roster_status"] == "not_on_latest_saved_roster"
                   for p in all_players),
        )
        self.assertFalse(first["status_is_graduation_proof"])
        self.assertEqual([], self.read.school_player_index(
            school, limit=17, offset=200,
        )["players"])

    def test_tampered_school_game_and_player_identity_refused(self):
        self.start()
        school = self.schools["CMP000086"][0]
        with sqlite3.connect(
            self.slot / "historical_matches.sqlite3"
        ) as conn:
            conn.execute(
                "UPDATE historical_matches SET record_sha256='FAKE' "
                "WHERE year=2026"
            )
        with self.assertRaises(CareerHistoryViewConflict):
            self.read.school_results(
                school, start_year=2026, end_year=2027,
            )
        with sqlite3.connect(
            self.slot / "career_rosters.sqlite3"
        ) as conn:
            conn.execute(
                "UPDATE career_player_identities SET identity_sha256='FAKE' "
                "WHERE player_id=(SELECT player_id FROM career_player_identities "
                "WHERE school_id=? ORDER BY entry_year, player_id LIMIT 1)",
                (school,),
            )
        with self.assertRaises(CareerHistoryViewConflict):
            self.read.school_player_index(school)

    def test_history_read_page_and_year_validation(self):
        self.start()
        school = self.schools["CMP000086"][0]
        page = self.read.school_results(
            school, start_year=2026, end_year=2027, limit=1,
        )
        self.assertEqual(1, len(page["records"]))
        self.assertEqual(1, page["total_groups"])
        self.assertEqual([], self.read.school_results(
            school, start_year=2026, end_year=2027, limit=1, offset=1,
        )["records"])
        for opts in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
            with self.subTest(opts=opts), self.assertRaises(ValueError):
                self.read.school_player_index(school, **opts)
        with self.assertRaises(ValueError):
            self.read.school_results(
                school, start_year=2027, end_year=2026,
            )


if __name__ == "__main__":
    unittest.main()
