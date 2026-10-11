"""Stage43G-51: preseason frozen Senbatsu list and Tokai group declarations.

No 2027 school participant or game result in this fixture is official.
"""
from __future__ import annotations

from pathlib import Path
import json
import shutil
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_invitational_manifest import (
    CareerInvitationalManifestService,
)
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_tokai_concurrent_preflight import (
    CareerTokaiConcurrentPreflight, TokaiPreflightNotReady,
    _reference_group_members,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEED = 2026101151
NATIONAL = "CMP000001"
AICHI = "CMP000113"
MIE = "CMP000115"


class Stage43G51TokaiPreseasonFreeze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.base = tempfile.TemporaryDirectory()
        folder = Path(cls.base.name)
        cls.history = folder / "historical_matches.sqlite3"
        cls.rosters = folder / "career_rosters.sqlite3"
        history = HistoricalMatchArchive(cls.history)
        history.sync(
            year=2026, rng_seed=SEED,
            resolver_contract="game_v1",
            plan_fingerprint="stage43g51-sealed-previous",
            completed=[],
        )
        history.seal_year(2026, expected_match_count=0)
        by_prefecture = {
            p: sorted(s for s in cls.repo.school_to_program
                      if cls.repo.schools[s]["prefecture_code"] == p)
            for p in ("23", "24")
        }
        assert all(len(ids) >= 25 for ids in by_prefecture.values())
        cls.direct = {AICHI: [by_prefecture["23"][0]],
                      MIE: [by_prefecture["24"][0]]}
        national_others = sorted(
            s for s in cls.repo.school_to_program
            if cls.repo.schools[s]["prefecture_code"] not in ("23", "24")
        )[:32]
        cls.national = [
            *national_others[:30], cls.direct[AICHI][0],
            cls.direct[MIE][0],
        ]
        assert len(set(cls.national)) == 32
        cls.groups = {}
        cls.quota_sum = {}
        all_rosters = set(cls.national)
        for cid in (AICHI, MIE):
            stage = cls.repo.stage_by_code(cid, "BRANCH_QUALIFIER")
            groups = cls.repo.groups_by_stage[stage["stage_id"]]
            mapping = {}
            slot_count = 0
            for group in groups:
                gid = group["stage_group_id"]
                quota = cls.repo.param(
                    stage["stage_id"], "output_slots", gid,
                    int(group.get("advance_slots_to_next") or 0),
                )
                possible = sorted(_reference_group_members(cls.repo, group))
                possible = [
                    sid for sid in possible if sid not in cls.direct[cid]
                ]
                assert len(possible) >= quota, (cid, gid, quota, len(possible))
                selected = possible[:min(len(possible), quota+1)]
                mapping[gid] = selected
                all_rosters.update(selected)
                slot_count += quota
            cls.groups[cid] = mapping
            cls.quota_sum[cid] = slot_count
        cls.tochigi = sorted(
            s for s in cls.repo.school_to_program
            if cls.repo.schools[s]["prefecture_code"] == "09"
        )[:8]
        cls.gunma = sorted(
            s for s in cls.repo.school_to_program
            if cls.repo.schools[s]["prefecture_code"] == "10"
        )[:8]
        all_rosters.update(cls.tochigi)
        all_rosters.update(cls.gunma)
        generator = PlayerRosterGenerator()
        rosters = CareerRosterArchive(cls.rosters)
        for sid in sorted(all_rosters):
            rosters.save_initial_roster(
                generator.generate_for_school_id(cls.repo, sid, 2026, SEED)
            )
            rosters.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=SEED
            )
        cls.specs = [
            {
                "competition_id": NATIONAL,
                "entry_mode": "national_invitational_main_v1",
                "entrant_school_ids": cls.national,
                "group_entrant_school_ids": {},
            },
            {
                "competition_id": "CMP000086",
                "entry_mode": "kanto_direct_main_v1",
                "entrant_school_ids": cls.tochigi,
                "group_entrant_school_ids": {},
            },
        ]
        assert cls.quota_sum[AICHI] == 48
        assert cls.quota_sum[MIE] == 25

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.slot = self.root / "tokai"
        self.slot.mkdir()
        shutil.copy2(self.history, self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.rosters, self.slot / "career_rosters.sqlite3")
        self.multi = CareerMultiPreviewCheckpointService(
            self.repo, DATA, save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.service = CareerTokaiConcurrentPreflight(self.multi)
        self.manifests = CareerInvitationalManifestService(self.multi)
        self.archive = HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")

    def _start(self):
        return self.multi.start(
            "tokai", year=2027, competitions=self.specs,
            base_seed=SEED, career_seed=SEED,
        )

    def _finish(self, session):
        for _ in range(25):
            if NATIONAL in session.completed_runs():
                break
            step = self.multi.play_next_date(session)
            self.assertGreater(step["played_match_count"], 0)
        self.assertIn(NATIONAL, session.completed_runs())
        return self.multi.load("tokai", year=2027)

    def test_preseason_freeze_then_31_games_confirms_immutable_exemptions(self):
        self._start()
        before = self.service.audit("tokai", year=2027)
        self.assertEqual("no_preseason_qualification_freeze", before["status"])
        original = self.slot / "manual.json"
        original.write_bytes(b"original game save")
        freeze = self.service.freeze(
            "tokai", year=2027, group_entrant_school_ids=self.groups,
        )
        self.assertEqual("2027-03-20", freeze["qualification_frozen_before_date"])
        self.assertEqual(48, freeze["destination_schedule"][AICHI][
            "qualifier_slots"])
        self.assertEqual(25, freeze["destination_schedule"][MIE][
            "qualifier_slots"])
        self.assertEqual(self.direct[AICHI], freeze["destination_schedule"][AICHI][
            "additional_main_bypass_school_ids"])
        self.assertEqual(self.direct[MIE], freeze["destination_schedule"][MIE][
            "additional_main_bypass_school_ids"])
        self.assertFalse(freeze["auto_prefectural_activation_enabled"])
        self.assertEqual(
            "frozen_waiting_for_31_saved_senbatsu_games",
            self.service.audit("tokai", year=2027)["status"],
        )
        with self.assertRaisesRegex(TokaiPreflightNotReady, "already frozen"):
            self.service.freeze(
                "tokai", year=2027,
                group_entrant_school_ids=self.groups,
            )
        session = self.multi.load("tokai", year=2027)
        first = self.multi.play_next_date(session)
        self.assertEqual("2027-03-19", first["date"])
        self.assertEqual(
            "frozen_waiting_for_31_saved_senbatsu_games",
            self.service.audit("tokai", year=2027)["status"],
        )
        self._finish(session)
        report = self.service.audit("tokai", year=2027)
        self.assertEqual(
            "source_games_confirm_frozen_preseason_selection",
            report["status"],
        )
        self.assertEqual(self.direct[AICHI],
                         report["prefectures"][AICHI]["bypass_school_ids"])
        self.assertEqual(self.direct[MIE],
                         report["prefectures"][MIE]["bypass_school_ids"])
        self.assertEqual(5, report["prefectures"][AICHI]["district_groups_frozen"])
        self.assertEqual(3, report["prefectures"][MIE]["district_groups_frozen"])
        self.assertTrue(report["schedule_conflict_requires_simultaneous_activation"])
        self.assertFalse(report["auto_prefectural_activation_enabled"])
        self.assertFalse(report["regional_runtime_ready"])
        self.assertEqual(31, len([
            r for r in self.archive.list_matches(2027, limit=200)
            if r["competition_id"] == NATIONAL
        ]))
        self.assertEqual(freeze, self.service._read(
            self.service._path("tokai", 2027)
        ))
        self.assertEqual(b"original game save", original.read_bytes())
        self.assertEqual(
            "sealed", self.archive.list_years()[0]["status"],
        )

    def test_freeze_must_precede_any_date_even_if_senbatsu_not_complete(self):
        session = self._start()
        self.multi.play_next_date(session)
        with self.assertRaisesRegex(
            TokaiPreflightNotReady, "before|precede",
        ):
            self.service.freeze(
                "tokai", year=2027, group_entrant_school_ids=self.groups,
            )
        self.assertFalse(self.service._path("tokai", 2027).exists())

    def test_duplicates_wrong_area_and_senbatsu_double_entries_rejected(self):
        self._start()
        byes = {
            cid: {gid: list(schools) for gid, schools in m.items()}
            for cid, m in self.groups.items()
        }
        gid = next(iter(byes[AICHI]))
        byes[AICHI][gid][0] = self.direct[AICHI][0]
        with self.assertRaises(TokaiPreflightNotReady):
            self.service.freeze(
                "tokai", year=2027, group_entrant_school_ids=byes,
            )
        bad = {
            cid: {gid: list(schools) for gid, schools in m.items()}
            for cid, m in self.groups.items()
        }
        gid = next(iter(bad[MIE]))
        bad[MIE][gid][0] = self.groups[AICHI][next(iter(self.groups[AICHI]))][0]
        with self.assertRaises(TokaiPreflightNotReady):
            self.service.freeze(
                "tokai", year=2027, group_entrant_school_ids=bad,
            )
        self.assertFalse(self.service._path("tokai", 2027).exists())

    def test_removed_manifest_or_modified_freeze_rejected_after_progress(self):
        self._start()
        self.service.freeze(
            "tokai", year=2027, group_entrant_school_ids=self.groups,
        )
        self._finish(self.multi.load("tokai", year=2027))
        path = self.service._path("tokai", 2027)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["destination_schedule"][AICHI]["qualifier_slots"] += 1
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(TokaiPreflightNotReady):
            self.service.audit("tokai", year=2027)
        self.assertTrue(self.manifests._path("tokai", 2027).is_file())
        self.manifests._path("tokai", 2027).unlink()
        with self.assertRaises(TokaiPreflightNotReady):
            self.service.audit("tokai", year=2027)


if __name__ == "__main__":
    unittest.main()
