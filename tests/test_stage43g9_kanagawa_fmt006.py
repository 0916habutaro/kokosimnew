from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_invitational_manifest import CareerInvitationalManifestService
from phase2_engine.career_kanagawa_spring_checkpoint import (
    CareerKanagawaSpringCheckpointService, KanagawaSpringNotReady,
)
from phase2_engine.career_multi_preview_checkpoint import CareerMultiPreviewCheckpointService
from phase2_engine.career_preview_checkpoint import _checksum
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026100701
QUOTAS = (23, 23, 18, 17)
SIZES = (46, 46, 36, 34)


class Stage43G9KanagawaSameYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.fixture = tempfile.TemporaryDirectory()
        scratch = Path(cls.fixture.name)
        cls.history = scratch / "historical.sqlite3"
        cls.rosters = scratch / "rosters.sqlite3"
        db = HistoricalMatchArchive(cls.history)
        db.sync(
            year=2026, rng_seed=SEED, resolver_contract="game_v1",
            plan_fingerprint="stage43g9-sealed-sandbox-2026",
            completed=[],
        )
        db.seal_year(2026, expected_match_count=0)
        source_kanagawa = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "14"
        )
        outside = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] != "14"
        )
        tochigi = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "09"
        )[:8]
        assert len(source_kanagawa) >= sum(SIZES) + 2
        cls.recommended = source_kanagawa[:2]
        cls.eligible = source_kanagawa[2:sum(SIZES)+2]
        groups = cls.repo.groups_by_stage["STG000177"]
        groups = sorted(groups, key=lambda r: int(r["group_order"]))
        assert [int(row["advance_slots_to_next"]) for row in groups] == list(QUOTAS)
        cls.groups = {}
        offset = 0
        for row, count in zip(groups, SIZES):
            cls.groups[row["stage_group_id"]] = cls.eligible[offset:offset+count]
            offset += count
        cls.entrants = cls.recommended + cls.eligible
        cls.national32 = outside[:30] + cls.recommended
        cls.upstream = [
            {
                "competition_id": "CMP000001",
                "entry_mode": "national_invitational_main_v1",
                "entrant_school_ids": cls.national32,
                "group_entrant_school_ids": {},
            },
            {
                "competition_id": "CMP000086",
                "entry_mode": "kanto_direct_main_v1",
                "entrant_school_ids": tochigi,
                "group_entrant_school_ids": {},
            },
        ]
        stored = CareerRosterArchive(cls.rosters)
        factory = PlayerRosterGenerator()
        for sid in sorted(set(cls.entrants + cls.national32 + tochigi)):
            prior = factory.generate_for_school_id(cls.repo, sid, 2026, SEED)
            stored.save_initial_roster(prior)
            stored.advance_and_save(
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
        shutil.copy2(self.history, self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.rosters, self.slot / "career_rosters.sqlite3")
        self.multi = CareerMultiPreviewCheckpointService(
            self.repo, ROOT / "data", save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.manifest = CareerInvitationalManifestService(self.multi)
        self.service = CareerKanagawaSpringCheckpointService(self.multi)

    def tearDown(self):
        self.temp.cleanup()

    def setup_year(self, *, record=True):
        self.multi.start(
            "career_slot", year=2027, competitions=self.upstream,
            base_seed=SEED, career_seed=SEED,
        )
        if record:
            self.manifest.record("career_slot", year=2027)

    def start_kanagawa(self, *, entrants=None, groups=None):
        return self.service.start(
            "career_slot", year=2027,
            entrant_school_ids=self.entrants if entrants is None else entrants,
            group_entrant_school_ids=self.groups if groups is None else groups,
        )

    def test_no_complete_manifest_keeps_kanagawa_closed(self):
        self.setup_year(record=False)
        with self.assertRaisesRegex(KanagawaSpringNotReady, "complete Senbatsu"):
            self.start_kanagawa()
        self.assertFalse(self.service._path("career_slot", 2027).exists())
        self.assertEqual(
            "requires_same_year_verified_invitational_participants",
            self.manifest.audit_kanagawa("career_slot", year=2027)["status"],
        )

    def test_2027_two_senbatsu_recommendations_excluded_from_all_four_districts(self):
        self.setup_year()
        session = self.start_kanagawa()
        self.assertEqual(164, session.summary()["school_count"])
        self.assertEqual(2, session.summary()["recommended_count"])
        self.assertEqual(162, session.summary()["qualifier_count"])
        self.assertEqual(self.recommended, session.preview.annual.direct_main_entry_school_ids)
        self.assertEqual([], session.preview.annual.main_seed_school_ids)
        self.assertFalse(
            set(self.recommended) & set(session.preview.scheduled.runtime.qualifier_entrant_school_ids)
        )
        self.assertEqual(4, len(session.preview.scheduled.runtime.qualifier_groups))
        self.assertEqual("2027-03-20", session.preview.scheduled.next_scheduled_date())
        self.assertEqual(
            self.service.load("career_slot", year=2027).summary(),
            session.summary(),
        )

    def test_unknown_wrong_group_and_senbatsu_duplicates_rejected(self):
        self.setup_year()
        group0 = next(iter(self.groups))
        bad_groups = {key:list(v) for key,v in self.groups.items()}
        bad_groups[group0][0] = self.recommended[0]
        cases = (
            (self.entrants, bad_groups),
            (self.entrants, {group0: self.groups[group0]}),
            (self.entrants[:-1], self.groups),
            (self.entrants + [self.entrants[-1]], self.groups),
            (self.entrants[:-1] + ["NOT-A-SCHOOL"], self.groups),
            (self.entrants, {**self.groups, group0: self.groups[group0][:-1]}),
        )
        for schools, groups in cases:
            with self.subTest(length=len(schools), group_count=len(groups)):
                with self.assertRaises((FutureCompetitionNotReady, ValueError)):
                    self.start_kanagawa(entrants=schools,groups=groups)
                self.assertFalse(self.service._path("career_slot", 2027).exists())

    def test_full_fmt006_pool_playoff_main_and_common_A_history_resume(self):
        original = self.slot / "manual.json"
        original.write_bytes(b"sealed 2026 original save")
        self.setup_year()
        session = self.start_kanagawa()
        days = []
        phases = set()
        counts = {}
        for _ in range(45):
            result = self.service.play_next_global_date(session)
            days.append(result["date"])
            for comp, count in result["competition_match_counts"].items():
                counts[comp] = counts.get(comp, 0) + count
            if result["all_registered_events_complete"]:
                break
        self.assertTrue(result["all_registered_events_complete"])
        self.assertEqual(days, sorted(set(days)))
        self.assertTrue(session.preview.scheduled.is_complete)
        self.assertEqual(81 + len(self.recommended),
                         len(session.preview.scheduled.runtime.main_entrant_school_ids))
        for row in session.preview.scheduled.matches.values():
            if row.status == "completed":
                phases.add(row.phase_code)
        self.assertIn("POOL_RR", phases)
        self.assertIn("CROSS_PLAYOFF", phases)
        self.assertIn("MAIN_BRACKET", phases)
        run = session.preview.scheduled.to_competition_run()
        self.assertEqual("CMP000095", run.competition_id)
        self.assertEqual(83, len(run.main_entrant_school_ids))
        self.assertEqual(82, run.outcome.match_count)
        self.assertEqual(81, len(
            next(s for s in run.stage_executions
                 if s.stage_code == "BRANCH_QUALIFIER").output_school_ids
        ))
        self.assertTrue(set(self.recommended).issubset(run.main_entrant_school_ids))
        history = HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")
        # list_matches defaults to 200 rows; historical A data is NOT capped
        # at 200 matches. Exercise pagination across the 200-record boundary.
        first_page = history.list_matches(2027, limit=200, offset=0)
        second_page = history.list_matches(2027, limit=200, offset=200)
        saved = first_page + second_page
        self.assertEqual(200, len(first_page))
        self.assertGreater(len(second_page), 0)
        self.assertEqual(sum(counts.values()), len(saved))
        spring = [row for row in saved if row["competition_id"] == "CMP000095"]
        self.assertTrue(spring)
        self.assertTrue(any(row["stage_code"] == "BRANCH_QUALIFIER" and row["inning_scores"]
                            and row["batter_stats"] and row["pitcher_stats"]
                            for row in spring))
        self.assertTrue(any(row["stage_code"] == "MAIN" for row in spring))
        self.assertEqual("sealed", history.list_years()[0]["status"])
        self.assertEqual(b"sealed 2026 original save", original.read_bytes())
        restored = self.service.load("career_slot", year=2027)
        self.assertEqual(session.preview.scheduled.public_snapshot(),
                         restored.preview.scheduled.public_snapshot())
        self.assertEqual(
            self.manifest.audit_kanagawa("career_slot", year=2027)["direct_main_school_ids"],
            self.recommended,
        )

    def test_manifest_mutation_and_stale_spring_session_refused(self):
        self.setup_year()
        self.start_kanagawa()
        a = self.service.load("career_slot", year=2027)
        stale = self.service.load("career_slot", year=2027)
        first = self.service.play_next_global_date(a)
        self.assertEqual("2027-03-19", first["date"])
        second = self.service.play_next_global_date(a)
        self.assertEqual("2027-03-20", second["date"])
        self.assertIn("CMP000095", second["competition_match_counts"])
        with self.assertRaisesRegex(KanagawaSpringNotReady, "stale"):
            self.service.play_next_global_date(stale)
        path = self.slot / "career_invitational_manifests" / "2027_CMP000001.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["entrant_school_ids"][0] = "FAKE"
        payload["payload_checksum"] = _checksum(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.service.load("career_slot", year=2027)

    def test_no_retroactive_qualifier_after_senbatsu_was_advanced(self):
        self.setup_year()
        session = self.multi.load("career_slot", year=2027)
        # At least two national dates have been processed (Mar19 then Mar20).
        self.multi.play_next_date(session)
        self.multi.play_next_date(session)
        with self.assertRaisesRegex(KanagawaSpringNotReady, "retroactively"):
            self.start_kanagawa()


if __name__ == "__main__":
    unittest.main()
