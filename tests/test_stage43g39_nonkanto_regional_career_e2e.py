"""Stage43G-39: Tokai + Shikoku saved-game regional E2E with real master IDs.

The entrants are deterministic SANDBOX choices, not verified qualifiers.
2027 dates are projected from 2026 and are NOT official future schedules.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_cross_era_navigation import CareerCrossEraNavigator
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService, CareerPreviewSaveError,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.future_non_kanto_regional_main_bridge import (
    NON_KANTO_REGIONAL_MAIN_IDS,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository
from phase2_engine.career_history_scale_benchmark import file_sha256


ROOT = Path(__file__).resolve().parents[1]
SEED = 2026100701
REGIONS = {
    "CMP000008": ("21", "22", "23", "24"),  # Tokai 2026 structure
    "CMP000011": ("36", "37", "38", "39"),  # Shikoku 2026 structure
}


class Stage43G39NonKantoRegionalCareerE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.base = tempfile.TemporaryDirectory()
        p = Path(cls.base.name)
        cls.initial_history = p / "historical_matches.sqlite3"
        cls.initial_rosters = p / "career_rosters.sqlite3"
        hist = HistoricalMatchArchive(cls.initial_history)
        hist.sync(
            year=2026, rng_seed=SEED, resolver_contract="game_v1",
            plan_fingerprint="stage43g39-empty-prior-year-game-sandbox",
            completed=[],
        )
        hist.seal_year(2026, expected_match_count=0)
        archive = CareerRosterArchive(cls.initial_rosters)
        generator = PlayerRosterGenerator()
        cls.specs = []
        cls.teams = {}
        used = set()
        for cid, codes in REGIONS.items():
            entrants = []
            for pcode in codes:
                candidates = sorted(
                    sid for sid in cls.repo.school_to_program
                    if cls.repo.schools[sid]["prefecture_code"] == pcode
                )
                assert len(candidates) >= 2, (pcode, len(candidates))
                entrants.extend(candidates[:2])
            assert len(entrants) == 8
            assert all(sid not in used for sid in entrants)
            used.update(entrants)
            cls.teams[cid] = entrants
            cls.specs.append({
                "competition_id": cid,
                "entry_mode": "non_kanto_regional_main_sandbox_v1",
                "entrant_school_ids": entrants,
                "group_entrant_school_ids": {},
            })
        for sid in sorted(used):
            archive.save_initial_roster(
                generator.generate_for_school_id(cls.repo, sid, 2026, SEED)
            )
            archive.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=SEED,
            )

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.save_root = Path(self.temp.name)
        self.slot = self.save_root / "regional"
        self.slot.mkdir()
        shutil.copy2(self.initial_history, self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.initial_rosters, self.slot / "career_rosters.sqlite3")
        self.service = CareerMultiPreviewCheckpointService(
            self.repo, ROOT / "data", save_root=self.save_root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )

    def _start(self, specs=None):
        return self.service.start(
            "regional", year=2027,
            competitions=self.specs if specs is None else specs,
            base_seed=SEED, career_seed=SEED,
        )

    def _history(self):
        return HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")

    def test_first_game_date_checkpoint_replay_and_A_details(self):
        original = self.slot / "manual.json"
        original.write_text("untouched original manual save", encoding="utf-8")
        prior_ledger = self._history().list_years()[0]["ledger_sha256"]
        self.assertTrue(set(REGIONS).issubset(NON_KANTO_REGIONAL_MAIN_IDS))
        session = self._start()
        self.assertEqual(2, session.summary()["competition_count"])
        self.assertFalse(session.summary()["competition_advancement_automatic"])
        first = self.service.play_next_date(session)
        self.assertEqual("2027-04-25", first["date"])
        self.assertGreater(first["played_match_count"], 0)
        self.assertTrue(
            (self.slot / "career_multi_previews" / "2027.json").is_file()
        )
        prior_counts = {
            cid: p.scheduled.public_snapshot()
            for cid, p in session.previews.items()
        }
        restored = self.service.load("regional", year=2027)
        self.assertEqual(
            prior_counts,
            {cid: p.scheduled.public_snapshot()
             for cid, p in restored.previews.items()},
        )
        history = self._history()
        rows = history.list_matches(2027, limit=500)
        self.assertEqual(first["played_match_count"], len(rows))
        self.assertTrue(all(row["inning_scores"] is not None
                            and row["batter_stats"] and row["pitcher_stats"]
                            and row["score_source"] == "ability_model_v1"
                            and row["date_source"] == "game_projection_v1"
                            for row in rows))
        self.assertEqual(prior_ledger, history.list_years()[0]["ledger_sha256"])
        self.assertEqual([], history.list_matches(2026))
        self.assertEqual("untouched original manual save",
                         original.read_text(encoding="utf-8"))

    def test_tokai_and_shikoku_complete_then_saved_match_browse(self):
        session = self._start()
        for _ in range(15):
            if len(session.completed_runs()) == 2:
                break
            self.service.play_next_date(session)
        self.assertEqual(sorted(REGIONS), sorted(session.completed_runs()))
        self.assertEqual(14, session.summary()["completed_match_count"])
        self.assertEqual(
            14, len(self._history().list_matches(2027, limit=500)),
        )
        for cid, run in session.completed_runs().items():
            with self.subTest(competition=cid):
                self.assertEqual(8, len(run.main_entrant_school_ids))
                self.assertEqual(7, run.outcome.match_count)
                self.assertIn(run.outcome.champion_school_id, self.teams[cid])
        finished = self.service.load("regional", year=2027)
        self.assertEqual(
            {cid: r.outcome.champion_school_id
             for cid, r in session.completed_runs().items()},
            {cid: r.outcome.champion_school_id
             for cid, r in finished.completed_runs().items()},
        )

        # Explicitly seal this complete two-event sandbox, *not* a full
        # 2027 season. The read-only archive browser requires a sealed year.
        history = self._history()
        history.seal_year(2027, expected_match_count=14)
        before = [
            file_sha256(self.slot / "historical_matches.sqlite3"),
            file_sha256(self.slot / "career_rosters.sqlite3"),
        ]
        nav = CareerCrossEraNavigator(self.slot)
        cid = "CMP000008"
        sid = self.teams[cid][0]
        school = nav.school_page(
            [2027], sid, selected_year=2027, verify_source=True,
        )
        self.assertEqual("cross_era_school", school["screen"])
        self.assertGreater(school["match_total"], 0)
        self.assertEqual("historical_matches_legacy_iso", school["source"])
        self.assertTrue(school["match_detail_targets"])
        target = school["match_detail_targets"][0]["target"]
        detail = nav.follow(target, verify_source=True)
        self.assertEqual("cross_era_match", detail["screen"])
        self.assertTrue(detail["details"]["batter_stats"])
        self.assertTrue(detail["details"]["pitcher_stats"])
        self.assertTrue(detail["details"]["inning_scores"])
        self.assertEqual(
            before,
            [
                file_sha256(self.slot / "historical_matches.sqlite3"),
                file_sha256(self.slot / "career_rosters.sqlite3"),
            ],
        )

    def test_region_exclusion_and_nonqualified_inputs_fail_closed(self):
        wrong = [
            dict(spec, entrant_school_ids=list(spec["entrant_school_ids"]))
            for spec in self.specs
        ]
        # An actual school from a *different* region may not sneak into Tokai.
        wrong[0]["entrant_school_ids"][-1] = self.teams["CMP000011"][0]
        with self.assertRaisesRegex(FutureCompetitionNotReady, "region"):
            self._start(wrong)
        self.assertFalse(
            (self.slot / "career_multi_previews" / "2027.json").exists()
        )

        # No same-prefecture all-entrant shortcut for a regional event.
        same = [dict(spec) for spec in self.specs]
        first = self.teams["CMP000008"]
        more = sorted(
            sid for sid in self.repo.school_to_program
            if self.repo.schools[sid]["prefecture_code"] == "21"
        )[:8]
        self.assertEqual(8, len(more))
        same[0]["entrant_school_ids"] = more
        with self.assertRaisesRegex(FutureCompetitionNotReady, "two prefectures"):
            self._start(same)

        invalid = [dict(spec) for spec in self.specs]
        invalid[0]["group_entrant_school_ids"] = {"fake": [first[0]]}
        with self.assertRaisesRegex(CareerPreviewSaveError, "regional MAIN"):
            self._start(invalid)

        missing = [dict(spec) for spec in self.specs]
        missing[0]["entry_mode"] = "kanto_direct_main_v1"
        with self.assertRaisesRegex(CareerPreviewSaveError, "direct MAIN"):
            self._start(missing)

    def test_roster_missing_or_tampered_checkpoint_rejected(self):
        missing = [dict(spec) for spec in self.specs]
        missing[0]["entrant_school_ids"] = self.teams["CMP000008"][:7] + [
            next(sid for sid in self.repo.school_to_program
                 if self.repo.schools[sid]["prefecture_code"] == "21"
                 and sid not in self.teams["CMP000008"])
        ]
        with self.assertRaisesRegex(FutureCompetitionNotReady, "roster"):
            self._start(missing)
        self.assertFalse(
            (self.slot / "career_multi_previews" / "2027.json").is_file()
        )
        self._start()
        checkpoint = self.slot / "career_multi_previews" / "2027.json"
        data = json.loads(checkpoint.read_text(encoding="utf-8"))
        data["inputs"][0]["entrant_school_ids"][0] = "INVALID-ID"
        checkpoint.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(CareerPreviewSaveError):
            self.service.load("regional", year=2027)


if __name__ == "__main__":
    unittest.main()
