from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import shutil
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService,
    CareerPreviewSaveError,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.future_kanto_direct_main_bridge import (
    DIRECT_MAIN_PREFECTURES,
    prepare_future_kanto_direct_main_preview,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository


ROOT = Path(__file__).resolve().parents[1]
SEED = 2026100701


class Stage43G5DirectMainThreePrefecturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.fixture = tempfile.TemporaryDirectory()
        base = Path(cls.fixture.name)
        cls.historical_path = base / "history.sqlite3"
        cls.roster_path = base / "rosters.sqlite3"
        hist = HistoricalMatchArchive(cls.historical_path)
        hist.sync(
            year=2026, rng_seed=SEED, resolver_contract="game_v1",
            plan_fingerprint="2026-sealed-empty-test-only",
            completed=[],
        )
        hist.seal_year(2026, expected_match_count=0)
        rosters = CareerRosterArchive(cls.roster_path)
        generator = PlayerRosterGenerator()
        cls.specs = []
        for cid, pcode in DIRECT_MAIN_PREFECTURES.items():
            schools = sorted(
                sid for sid in cls.repo.school_to_program
                if cls.repo.schools[sid]["prefecture_code"] == pcode
            )[:8]
            assert len(schools) == 8
            for sid in schools:
                roster = generator.generate_for_school_id(
                    cls.repo, sid, 2026, SEED,
                )
                rosters.save_initial_roster(roster)
                rosters.advance_and_save(
                    cls.repo.team(sid), next_year=2027, career_seed=SEED,
                )
            cls.specs.append({
                "competition_id": cid,
                "entry_mode": "kanto_direct_main_v1",
                "entrant_school_ids": schools,
                "group_entrant_school_ids": {},
            })

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.slot_dir = self.root / "career_slot"
        self.slot_dir.mkdir()
        shutil.copy2(self.historical_path,
                     self.slot_dir / "historical_matches.sqlite3")
        shutil.copy2(self.roster_path,
                     self.slot_dir / "career_rosters.sqlite3")
        self.service = CareerMultiPreviewCheckpointService(
            self.repo, ROOT / "data", save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )

    def tearDown(self):
        self.temp.cleanup()

    def start(self, *, specs=None):
        return self.service.start(
            "career_slot", year=2027,
            competitions=self.specs if specs is None else specs,
            base_seed=SEED, career_seed=SEED,
        )

    def test_all_three_direct_main_competitions_create_seed_free_brackets(self):
        session = self.start()
        self.assertEqual(sorted(DIRECT_MAIN_PREFECTURES),
                         session.summary()["competition_ids"])
        self.assertEqual(3, session.summary()["competition_count"])
        for cid, preview in session.previews.items():
            with self.subTest(cid=cid):
                self.assertEqual(8, len(preview.annual.entrant_school_ids))
                self.assertEqual([], preview.annual.main_seed_school_ids)
                self.assertEqual([], preview.annual.direct_main_entry_school_ids)
                self.assertFalse(preview.snapshot()["official_competition"])
                self.assertEqual("game_projection_v1",
                                 preview.snapshot()["game_provenance"])
                self.assertEqual(2027, preview.year)
        self.assertEqual([], HistoricalMatchArchive(
            self.slot_dir / "historical_matches.sqlite3"
        ).list_matches(2027))

    def test_three_prefectures_global_dates_save_and_resume(self):
        original = self.slot_dir / "manual.json"
        original.write_bytes(b"2026 original save stays untouched")
        session = self.start()
        a = self.service.play_next_date(session)
        self.assertEqual("2027-04-11", a["date"])
        self.assertGreaterEqual(a["played_match_count"], 4)
        historic = HistoricalMatchArchive(
            self.slot_dir / "historical_matches.sqlite3"
        )
        self.assertEqual(a["played_match_count"], len(historic.list_matches(2027)))
        self.assertEqual("sealed", historic.list_years()[0]["status"])
        self.assertEqual(original.read_bytes(),
                         b"2026 original save stays untouched")
        self.assertTrue(all(
            x["date_source"] == "game_projection_v1"
            for x in historic.list_matches(2027)
        ))
        resumed = self.service.load("career_slot", year=2027)
        self.assertEqual(session.processed_dates, resumed.processed_dates)
        self.assertEqual(
            {cid: p.scheduled.public_snapshot()
             for cid, p in session.previews.items()},
            {cid: p.scheduled.public_snapshot()
             for cid, p in resumed.previews.items()},
        )
        next_day = self.service.play_next_date(resumed)
        self.assertGreater(next_day["date"], a["date"])
        self.assertEqual(next_day["checkpoint"]["completed_match_count"],
                         len(historic.list_matches(2027)))

    def test_direct_main_sandbox_season_can_finish_and_publish_outcomes(self):
        session = self.start()
        for _ in range(15):
            if all(x.scheduled.is_complete for x in session.previews.values()):
                break
            self.service.play_next_date(session)
        self.assertEqual(3, len(session.completed_runs()))
        self.assertEqual(21, session.summary()["completed_match_count"])
        for cid, run in session.completed_runs().items():
            self.assertEqual(2027, run.year)
            self.assertEqual(cid, run.competition_id)
            self.assertEqual(8, len(run.main_entrant_school_ids))
            self.assertEqual(7, run.outcome.match_count)
        replay = self.service.load("career_slot", year=2027)
        self.assertEqual(
            {k: v.outcome.champion_school_id for k, v in session.completed_runs().items()},
            {k: v.outcome.champion_school_id for k, v in replay.completed_runs().items()},
        )
        self.assertFalse(session.summary()["competition_advancement_automatic"])

    def test_no_unvalidated_direct_main_mode_for_kanagawa_or_chiba(self):
        for cid in ("CMP000095", "CMP000092", "CMP000094"):
            with self.subTest(cid=cid), self.assertRaisesRegex(
                CareerPreviewSaveError, "whitelisted competition",
            ):
                self.start(specs=[
                    self.specs[0], {
                        "competition_id": cid,
                        "entry_mode": "kanto_direct_main_v1",
                        "entrant_school_ids": self.specs[0]["entrant_school_ids"],
                        "group_entrant_school_ids": {},
                    },
                ])

    def test_unnamed_mode_not_upgraded_or_reinterpreted(self):
        s = dict(self.specs[0])
        s.pop("entry_mode")
        with self.assertRaises(Exception):
            self.start(specs=[s, self.specs[1]])
        self.assertFalse(
            (self.slot_dir / "career_multi_previews" / "2027.json").exists()
        )

    def test_duplicate_unknown_and_other_prefecture_school_rejected(self):
        cid = "CMP000086"
        schools = list(self.specs[0]["entrant_school_ids"])
        rosters = CareerRosterArchive(
            self.slot_dir / "career_rosters.sqlite3"
        )
        kwargs = {
            "data_root": ROOT / "data", "year": 2027,
            "competition_id": cid, "roster_archive": rosters,
            "repo": self.repo, "base_seed": SEED, "career_seed": SEED,
        }
        for wrong in (schools + [schools[0]], schools[:3],
                      schools[:-1] + self.specs[1]["entrant_school_ids"][:1],
                      schools[:-1] + ["SCH-NOT-A-SCHOOL"]):
            with self.subTest(wrong=wrong[-1]), self.assertRaises(FutureCompetitionNotReady):
                prepare_future_kanto_direct_main_preview(
                    **kwargs, entrant_school_ids=wrong,
                )

    def test_missing_year_roster_or_incorrect_seed_is_not_regenerated(self):
        with tempfile.TemporaryDirectory() as t:
            empty = CareerRosterArchive(Path(t) / "missing.sqlite3")
            with self.assertRaisesRegex(FutureCompetitionNotReady, "saved career roster"):
                prepare_future_kanto_direct_main_preview(
                    data_root=ROOT / "data", year=2027,
                    competition_id="CMP000088",
                    entrant_school_ids=self.specs[1]["entrant_school_ids"],
                    roster_archive=empty, repo=self.repo,
                    base_seed=SEED, career_seed=SEED,
                )
            self.assertFalse(empty.db_path.exists())
        with self.assertRaisesRegex(FutureCompetitionNotReady, "saved career roster"):
            prepare_future_kanto_direct_main_preview(
                data_root=ROOT / "data", year=2027,
                competition_id="CMP000088",
                entrant_school_ids=self.specs[1]["entrant_school_ids"],
                roster_archive=CareerRosterArchive(
                    self.slot_dir / "career_rosters.sqlite3",
                ), repo=self.repo, base_seed=SEED, career_seed=SEED + 1,
            )

    def test_malformed_modes_and_unexpected_group_inputs_fail_before_start(self):
        for entry in ("unknown", "kanto_direct_main_v2"):
            bad = dict(self.specs[0], entry_mode=entry)
            with self.assertRaisesRegex(CareerPreviewSaveError, "mode"):
                self.start(specs=[bad, self.specs[1]])
        bad = dict(self.specs[0], group_entrant_school_ids={"OTHER": ["SCH-X"]})
        with self.assertRaisesRegex(CareerPreviewSaveError, "no feeder override"):
            self.start(specs=[bad, self.specs[1]])
        bad = dict(self.specs[0], prior_source_competition_id="OTHER")
        with self.assertRaisesRegex(CareerPreviewSaveError, "no feeder override"):
            self.start(specs=[bad, self.specs[1]])

    def test_checkpoint_seed_and_games_cannot_be_rewritten_after_start(self):
        session = self.start()
        self.service.play_next_date(session)
        path = self.slot_dir / "career_multi_previews" / "2027.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["inputs"][0]["entrant_school_ids"][0] = "CHANGED"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(CareerPreviewSaveError, "checksum"):
            self.service.load("career_slot", year=2027)


if __name__ == "__main__":
    unittest.main()
