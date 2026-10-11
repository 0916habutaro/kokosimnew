"""Stage43G-54 Tokai season A-archive read-only school/game/player navigation.

Only synthetic fictional fixtures are written in setUp. All browse calls
must preserve existing historical SQLite bytes.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from phase2_engine.career_history_scale_audit import synthetic_ability_record
from phase2_engine.career_player_records import BATTER, PITCHER
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.career_tokai_season_browse_model import (
    CareerTokaiSeasonBrowseModel, TokaiSeasonBrowseConflict,
    SENBATSU, GIFU, SHIZUOKA, AICHI, MIE, TOKAI, TOKAI_SEASON_IDS,
)
import test_stage43g14_player_records as stage14

ROOT = Path(__file__).resolve().parents[1]


class Stage43G54TokaiHistoryReadOnly(unittest.TestCase):
    def setUp(self):
        self.fixture = stage14.Stage43G14PlayerRecordTests(
            "test_annual_and_career_stats_and_defined_ratios",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.slot = Path(self.work.name) / "tokai_sandbox"
        self.slot.mkdir()
        history = self.slot / "historical_matches.sqlite3"
        shutil.copy2(self.fixture.history.db_path, history)
        shutil.copy2(
            self.fixture.rosters.db_path,
            self.slot / "career_rosters.sqlite3",
        )
        self.archive = HistoricalMatchArchive(history)
        self.a, self.b = self.fixture.a, self.fixture.b
        self.hitter = self.fixture.hitter
        rosters = self.fixture.rosters
        fixtures = []
        for i, (cid, match) in enumerate([
            (SENBATSU, "SENB-01"), (GIFU, "GIFU-01"),
            (AICHI, "AICHI-01"), (TOKAI, "REGIONAL-01"),
        ], start=4):
            row = synthetic_ability_record(
                2027, cid, match, self.a, self.b, i,
            )
            for school in (self.a, self.b):
                players = rosters.roster(2027, school).players
                bats = [
                    p.player_id for p in players
                    if p.primary_position != "P"
                ][:9]
                assert len(bats) == 9
                source = [
                    item for item in row["ability_detail"]["batter_stats"]
                    if item["school_id"] == school
                ]
                for item, pid in zip(source, bats):
                    item["player_id"] = pid
                    for key in BATTER:
                        item.setdefault(key, 0)
                    item["plate_appearances"] = 4
                pitcher = next(p.player_id for p in players
                               if p.primary_position == "P")
                for item in row["ability_detail"]["pitcher_stats"]:
                    if item["school_id"] == school:
                        item["player_id"] = pitcher
                        for key in PITCHER:
                            item.setdefault(key, 0)
                        item["outs_recorded"] = 27
            fixtures.append(row)
        self.archive.sync(
            year=2027, rng_seed=stage14.SEED,
            resolver_contract="synthetic_test_v1",
            plan_fingerprint="stage43g14-year-2027",
            completed=fixtures,
        )
        self.model = CareerTokaiSeasonBrowseModel(ROOT / "data", self.slot)

    def _sha(self):
        return sha256(
            (self.slot / "historical_matches.sqlite3").read_bytes()
        ).hexdigest()

    def test_season_index_shows_only_saved_tokai_games_and_source_warning(self):
        before = self._sha()
        page = self.model.overview(2027)
        self.assertEqual("tokai_season", page["screen"])
        self.assertEqual(len(TOKAI_SEASON_IDS), len(page["events"]))
        self.assertEqual(4, page["archived_match_count"])
        self.assertFalse(page["official_future_results"])
        self.assertFalse(page["regional_qualifiers_inferred_from_scores"])
        counts = {x["competition_id"]: x["archived_match_count"]
                  for x in page["events"]}
        self.assertEqual(
            {SENBATSU: 1, GIFU: 1, SHIZUOKA: 0,
             AICHI: 1, MIE: 0, TOKAI: 1},
            counts,
        )
        self.assertTrue(all(
            x["bracket_completed_or_advancement_proven"] is False
            for x in page["events"]
        ))
        self.assertEqual(before, self._sha())
        self.assertFalse((self.slot / "derived_player_stats.sqlite3").exists())

    def test_competition_school_match_and_player_navigation_by_ids(self):
        before = self._sha()
        index = self.model.overview(2027)
        target = next(x["competition_target"] for x in index["events"]
                      if x["competition_id"] == TOKAI)
        games = self.model.open(target)
        self.assertEqual(1, games["matches"]["total"])
        row = games["matches"]["rows"][0]
        self.assertEqual("REGIONAL-01", row["match_id"])
        self.assertEqual("2027-04-07", row["match_date"])
        school = self.model.open(games["school_targets"][0])
        self.assertEqual(4, school["matches"]["total"])
        self.assertEqual(4, school["archived_wins"])
        self.assertEqual(0, school["archived_losses"])
        self.assertTrue(school["player_targets"])
        self.assertFalse(school["all_real_world_season_games_known"])
        detail = self.model.open(row["match_target"])
        self.assertEqual("tokai_match", detail["screen"])
        self.assertEqual("recorded", detail["inning_score_status"])
        self.assertEqual("recorded", detail["box_score_status"])
        self.assertTrue(detail["player_targets"])
        self.assertEqual(self.a, detail["school_targets"][0]["school_id"])
        stat = self.model.open(detail["player_targets"][0])
        self.assertEqual("tokai_player", stat["screen"])
        self.assertTrue(stat["season_stats"])
        self.assertTrue(stat["career_stats"])
        self.assertFalse(stat["official_future_results"])
        self.assertEqual(before, self._sha())

    def test_only_explicit_matching_ids_and_bounds_are_addressable(self):
        with self.assertRaises(TokaiSeasonBrowseConflict):
            self.model.overview(2028)
        with self.assertRaises(TokaiSeasonBrowseConflict):
            self.model.overview(2026)
        with self.assertRaises(TokaiSeasonBrowseConflict):
            self.model.competition(2027, "CMP000086")
        with self.assertRaises(TokaiSeasonBrowseConflict):
            self.model.match(2027, TOKAI, "GIFU-01")
        with self.assertRaises(TokaiSeasonBrowseConflict):
            self.model.school(2027, "BAD-SCHOOL-ID")
        with self.assertRaises(TokaiSeasonBrowseConflict):
            self.model.open({"screen": "school", "year": 2027,
                             "school_id": self.a, "school_name": "forged"})
        with self.assertRaises(TokaiSeasonBrowseConflict):
            self.model.open({"screen": "school", "year": True,
                             "school_id": self.a})
        with self.assertRaises(TokaiSeasonBrowseConflict):
            self.model.competition(2027, TOKAI, limit=101)
        self.assertEqual([], self.model.competition(
            2027, SHIZUOKA,
        )["matches"]["rows"])
        self.assertEqual([], self.model.competition(
            2027, TOKAI, offset=1,
        )["matches"]["rows"])

    def test_single_record_sha_tamper_blocks_overview_and_every_browse(self):
        before = self._sha()
        self.assertTrue(before)
        with sqlite3.connect(self.archive.db_path) as db:
            db.execute(
                "UPDATE historical_matches SET payload_json=? "
                "WHERE year=2027 AND competition_id=? AND match_id=?",
                ('{"fabricated":true}', GIFU, "GIFU-01"),
            )
        for callback in (
            lambda: self.model.overview(2027),
            lambda: self.model.competition(2027, TOKAI),
            lambda: self.model.school(2027, self.a),
            lambda: self.model.match(2027, TOKAI, "REGIONAL-01"),
        ):
            with self.assertRaises(TokaiSeasonBrowseConflict):
                callback()


if __name__ == "__main__":
    unittest.main()
