from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_invitational_manifest import (
    CareerInvitationalManifestService, InvitationalManifestConflict,
)
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService, CareerPreviewSaveError,
)
from phase2_engine.career_preview_checkpoint import _checksum
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026100701


class Stage43G8SameYearSenbatsuManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.fixture = tempfile.TemporaryDirectory()
        cls.histfile = Path(cls.fixture.name) / "history.sqlite3"
        cls.rosterfile = Path(cls.fixture.name) / "rosters.sqlite3"
        hist = HistoricalMatchArchive(cls.histfile)
        hist.sync(
            year=2026, rng_seed=SEED, resolver_contract="game_v1",
            plan_fingerprint="stage43g8-previous-year-sealed",
            completed=[],
        )
        hist.seal_year(2026, expected_match_count=0)
        non_kanagawa = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] != "14"
        )[:32]
        kanagawa = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "14"
        )[:2]
        tochigi = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "09"
        )[:8]
        gunma = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "10"
        )[:8]
        assert len(non_kanagawa) == 32 and len(kanagawa) == 2
        assert len(gunma) == 8
        assert len(tochigi) == 8
        cls.kanagawa = kanagawa
        cls.source32 = non_kanagawa[:30] + kanagawa
        cls.zero32 = non_kanagawa
        cls.national = {
            "competition_id": "CMP000001",
            "entry_mode": "national_invitational_main_v1",
            "entrant_school_ids": cls.source32,
            "group_entrant_school_ids": {},
        }
        cls.tochigi = {
            "competition_id": "CMP000086",
            "entry_mode": "kanto_direct_main_v1",
            "entrant_school_ids": tochigi,
            "group_entrant_school_ids": {},
        }
        cls.gunma = {
            "competition_id": "CMP000088",
            "entry_mode": "kanto_direct_main_v1",
            "entrant_school_ids": gunma,
            "group_entrant_school_ids": {},
        }
        generator = PlayerRosterGenerator()
        roster_db = CareerRosterArchive(cls.rosterfile)
        for sid in sorted(set(non_kanagawa + kanagawa + tochigi + gunma)):
            original = generator.generate_for_school_id(cls.repo, sid, 2026, SEED)
            roster_db.save_initial_roster(original)
            roster_db.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=SEED,
            )

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.slot = self.root / "career_slot"
        self.slot.mkdir()
        shutil.copy2(self.histfile, self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.rosterfile, self.slot / "career_rosters.sqlite3")
        self.service = CareerMultiPreviewCheckpointService(
            self.repo, ROOT / "data", save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.manifests = CareerInvitationalManifestService(self.service)

    def tearDown(self):
        self.temp.cleanup()

    def start(self, specs=None):
        return self.service.start(
            "career_slot", year=2027,
            competitions=[self.national, self.tochigi] if specs is None else specs,
            base_seed=SEED, career_seed=SEED,
        )

    def test_manifest_remains_unresolved_until_complete_game_source_is_saved(self):
        pending = self.manifests.audit_kanagawa("career_slot", year=2027)
        self.assertEqual(
            "requires_same_year_verified_invitational_participants",
            pending["status"],
        )
        self.assertEqual([], pending["direct_main_school_ids"])
        self.start()
        still_pending = self.manifests.audit_kanagawa("career_slot", year=2027)
        self.assertEqual(pending["status"], still_pending["status"])
        self.assertFalse(still_pending["runtime_ready"])
        self.assertFalse(
            (self.slot / "career_invitational_manifests" /
             "2027_CMP000001.json").exists()
        )

    def test_verified_full_manifest_has_two_kanagawa_exemptions_not_seed_rights(self):
        session = self.start()
        manifest = self.manifests.record("career_slot", year=2027)
        self.assertEqual(32, manifest["expected_participant_count"])
        self.assertEqual(self.source32, manifest["entrant_school_ids"])
        self.assertEqual("CMP000001", manifest["competition_id"])
        self.assertFalse(manifest["official_participants_verified"])
        self.assertFalse(manifest["automatic_senbatsu_selection"])
        audit = self.manifests.audit_kanagawa("career_slot", year=2027)
        self.assertEqual(
            "complete_same_year_sandbox_participant_manifest",
            audit["status"],
        )
        self.assertEqual(self.kanagawa, audit["direct_main_school_ids"])
        self.assertEqual(self.kanagawa, audit["preliminary_exempt_school_ids"])
        self.assertEqual(32, audit["source_school_count"])
        self.assertTrue(audit["game_participant_manifest_verified"])
        self.assertFalse(audit["runtime_ready"])
        self.assertFalse(audit["automatic_bypass_enabled"])
        self.assertFalse(audit["future_official_participants_confirmed"])
        self.assertEqual([], audit["main_seed_school_ids"])
        self.assertEqual(
            self.manifests.record("career_slot", year=2027), manifest,
        )
        self.assertEqual(
            sorted(["CMP000001", "CMP000086"]),
            session.summary()["competition_ids"],
        )

    def test_full_32_can_prove_zero_where_missing_record_cannot(self):
        no_kanagawa = dict(self.national, entrant_school_ids=self.zero32)
        self.start([no_kanagawa, self.tochigi])
        self.manifests.record("career_slot", year=2027)
        audit = self.manifests.audit_kanagawa("career_slot", year=2027)
        self.assertEqual(
            "complete_same_year_sandbox_participant_manifest",
            audit["status"],
        )
        self.assertEqual([], audit["direct_main_school_ids"])
        self.assertTrue(audit["game_participant_manifest_verified"])
        self.assertFalse(audit["no_record_interpreted_as_zero_participants"])

    def test_incomplete_wrong_and_duplicated_source_rejected_before_save(self):
        for bad_source in (
            dict(self.national, entrant_school_ids=self.source32[:-1]),
            dict(self.national, entrant_school_ids=self.source32[:-1]+[self.source32[0]]),
            dict(self.national, entry_mode="kanto_direct_main_v1"),
            dict(self.national, group_entrant_school_ids={"WRONG": [self.source32[0]]}),
            dict(self.national, prior_source_competition_id="CMP000002"),
        ):
            with self.subTest(bad=bad_source):
                with self.assertRaises((CareerPreviewSaveError, ValueError)):
                    self.start([bad_source, self.tochigi])
                self.assertFalse(
                    (self.slot / "career_multi_previews" / "2027.json").exists()
                )

    def test_senbatsu_results_share_A_archive_and_load_does_not_change_manifest(self):
        original = self.slot / "manual.json"
        original.write_bytes(b"2026 original save")
        session = self.start()
        manifest = self.manifests.record("career_slot", year=2027)
        first = self.service.play_next_date(session)
        self.assertEqual("2027-03-19", first["date"])
        self.assertIn("CMP000001", first["competition_match_counts"])
        saved = [m for m in HistoricalMatchArchive(
            self.slot / "historical_matches.sqlite3"
        ).list_matches(2027) if m["competition_id"] == "CMP000001"]
        self.assertTrue(saved and saved[0]["batter_stats"] and saved[0]["pitcher_stats"])
        self.assertEqual(manifest, self.manifests.record("career_slot", year=2027))
        replay = self.service.load("career_slot", year=2027)
        self.assertEqual(session.processed_dates, replay.processed_dates)
        self.assertEqual(
            self.kanagawa,
            self.manifests.audit_kanagawa("career_slot", year=2027)[
                "direct_main_school_ids"
            ],
        )
        self.assertEqual(b"2026 original save", original.read_bytes())
        self.assertEqual(
            "sealed", HistoricalMatchArchive(
                self.slot / "historical_matches.sqlite3"
            ).list_years()[0]["status"],
        )

    def test_manifest_and_annual_input_mutation_are_refused(self):
        self.start()
        self.manifests.record("career_slot", year=2027)
        path = self.slot / "career_invitational_manifests" / "2027_CMP000001.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["entrant_school_ids"][0] = self.kanagawa[0]
        raw["payload_checksum"] = _checksum(raw)
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(InvitationalManifestConflict, "differs"):
            self.manifests.audit_kanagawa("career_slot", year=2027)
        with self.assertRaisesRegex(InvitationalManifestConflict, "changed"):
            self.manifests.record("career_slot", year=2027)
        original = self.slot / "career_multi_previews" / "2027.json"
        annual = json.loads(original.read_text(encoding="utf-8"))
        annual["inputs"][0]["entrant_school_ids"][0] = "FAKE-SCHOOL"
        original.write_text(json.dumps(annual), encoding="utf-8")
        with self.assertRaises(CareerPreviewSaveError):
            self.manifests.audit_kanagawa("career_slot", year=2027)

    def test_other_competitions_without_senbatsu_do_not_establish_zero(self):
        self.start([self.tochigi, self.gunma])
        pending = self.manifests.audit_kanagawa("career_slot", year=2027)
        self.assertEqual(
            "requires_same_year_verified_invitational_participants",
            pending["status"],
        )
        with self.assertRaisesRegex(
            InvitationalManifestConflict, "entry plan is missing",
        ):
            self.manifests.record("career_slot", year=2027)


if __name__ == "__main__":
    unittest.main()
