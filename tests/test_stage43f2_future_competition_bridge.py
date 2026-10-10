from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_competition_bridge import (
    FutureCompetitionNotReady,
    SANDBOX_ENTRANTS,
    prepare_future_direct_main_preview,
)
from phase2_engine.future_season_blueprint import (
    build_future_season_blueprint,
)
from phase2_engine.repository import DataRepository


ROOT = Path(__file__).resolve().parents[1]


class Stage43F2FutureCompetitionBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.year = 2027
        cls.seed = 2026100701
        cls.competition_id = "CMP000001"
        cls.entrants = sorted(cls.repo.school_to_program)[:32]
        cls.blueprint = build_future_season_blueprint(
            ROOT / "data", year=cls.year, base_seed=cls.seed,
        )
        cls.temp = tempfile.TemporaryDirectory()
        cls.archive = CareerRosterArchive(
            Path(cls.temp.name) / "career_rosters.sqlite3"
        )
        generator = PlayerRosterGenerator()
        for sid in cls.entrants:
            old = generator.generate_for_school_id(
                cls.repo, sid, 2026, cls.seed,
            )
            cls.archive.save_initial_roster(old)
            cls.archive.advance_and_save(
                cls.repo.team(sid),
                next_year=2027, career_seed=cls.seed,
            )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def prepare(self, *, blueprint=None, entrants=None, archive=None,
                entry_source=SANDBOX_ENTRANTS, career_seed=None,
                competition_id=None):
        return prepare_future_direct_main_preview(
            blueprint=self.blueprint if blueprint is None else blueprint,
            competition_id=self.competition_id if competition_id is None
                           else competition_id,
            entrant_school_ids=self.entrants if entrants is None else entrants,
            roster_archive=self.archive if archive is None else archive,
            repo=self.repo,
            career_seed=self.seed if career_seed is None else career_seed,
            ability_config_dir=str(ROOT / "config" / "abilities"),
            match_config_dir=str(ROOT / "config" / "match"),
            entry_source=entry_source,
        )

    def test_engine_generates_2027_ready_main_bracket_with_real_runtime(self):
        preview = self.prepare()
        snap = preview.snapshot()
        self.assertEqual(2027, snap["year"])
        self.assertEqual("CMP000001", snap["competition_id"])
        self.assertEqual(32, snap["entrant_count"])
        self.assertFalse(snap["official_competition"])
        self.assertFalse(snap["persistent_game_session"])
        self.assertFalse(snap["year_rollover_implemented"])
        self.assertEqual("game_projection_v1", snap["game_provenance"])
        self.assertIn("2027年度", snap["competition_display_name"])
        self.assertNotIn("第98回", snap["competition_display_name"])
        self.assertEqual(2027, preview.annual.year)
        self.assertEqual(32, len(preview.scheduled.runtime.entrant_school_ids))
        self.assertEqual("provisional_game_schedule",
                         preview.scheduled.calendar_status)
        self.assertFalse(preview.scheduled.is_complete)
        rows = preview.scheduled.matches_for_date("2027-03-19")
        self.assertEqual(16, len(rows))
        self.assertTrue(all(r["date_source"] == "game_projection_v1"
                            for r in rows))
        self.assertEqual("2027-03-19", preview.scheduled.next_scheduled_date())

    def test_game_runs_next_wave_with_continuing_player_ids_and_a_stats(self):
        preview = self.prepare()
        out = preview.play_next_date()
        self.assertEqual(2027, out["year"])
        self.assertEqual(16, out["played_match_count"])
        self.assertEqual("2027-03-19", out["date"])
        self.assertEqual("game_projection_v1", out["date_source"])
        self.assertFalse(out["is_complete"])
        completed = preview.scheduled.completed_results()
        self.assertEqual(16, len(completed))
        self.assertTrue(all(row["status"] == "completed"
                            and row["date_source"] == "game_projection_v1"
                            and row["score_source"] == "ability_model_v1"
                            for row in completed.values()))
        one = next(iter(preview.scheduled.matches.values()))
        detail = one.ability_detail
        self.assertIsNotNone(detail)
        self.assertEqual(2027, detail["reference_year"])
        self.assertIsNotNone(detail["inning_scores"])
        self.assertEqual(2, len(detail["team_stats"]))
        self.assertTrue(detail["batter_stats"])
        self.assertTrue(detail["pitcher_stats"])
        participating_ids = set()
        for sid in (one.team1_id, one.team2_id):
            roster = self.archive.roster(2027, sid)
            participating_ids.update(p.player_id for p in roster.players)
        actual = {
            row["player_id"] for row in detail["batter_stats"]
        } | {
            row["player_id"] for row in detail["pitcher_stats"]
        }
        self.assertTrue(actual.issubset(participating_ids))
        self.assertEqual(32, len(self.archive.school_years(self.entrants[0])) * 16)

    def test_same_seed_bracket_and_dates_reproduce(self):
        first = self.prepare()
        second = self.prepare()
        self.assertEqual(first.scheduled.runtime.initial_slots,
                         second.scheduled.runtime.initial_slots)
        self.assertEqual(first.scheduled.summary(),
                         second.scheduled.summary())

    def test_future_projection_remains_sandbox_and_no_official_committee_claim(self):
        preview = self.prepare()
        self.assertEqual(SANDBOX_ENTRANTS, preview.entry_source)
        committee = next(c for c in self.blueprint["committee_selections"]
                         if c["competition_id"] == "CMP000001")
        self.assertEqual("committee_selection_pending", committee["status"])
        self.assertFalse(preview.snapshot()["official_competition"])

    def test_missing_or_duplicate_entrant_is_rejected(self):
        for entrants in (self.entrants[:-1], self.entrants[:-1] + self.entrants[:1]):
            with self.subTest(entrants=entrants), self.assertRaises(FutureCompetitionNotReady):
                self.prepare(entrants=entrants)

    def test_unknown_school_and_unregistered_roster_rejected(self):
        with self.assertRaisesRegex(FutureCompetitionNotReady, "known hardball"):
            self.prepare(entrants=self.entrants[:-1] + ["UNKNOWN-SCHOOL"])
        separate = CareerRosterArchive(
            Path(self.temp.name) / "missing_rosters.sqlite3"
        )
        with self.assertRaisesRegex(FutureCompetitionNotReady, "rosters missing"):
            self.prepare(archive=separate)
        self.assertFalse(separate.db_path.exists())

    def test_wrong_seed_does_not_recreate_schools(self):
        with self.assertRaisesRegex(FutureCompetitionNotReady, "rosters missing"):
            self.prepare(career_seed=self.seed + 1)

    def test_2026_as_2027_official_calendar_is_rejected(self):
        modified = deepcopy(self.blueprint)
        modified["official_calendar"] = True
        with self.assertRaisesRegex(FutureCompetitionNotReady, "provenance"):
            self.prepare(blueprint=modified)
        modified = deepcopy(self.blueprint)
        modified["calendars"][0]["real_world_verified"] = True
        with self.assertRaisesRegex(FutureCompetitionNotReady, "provisional"):
            self.prepare(blueprint=modified)
        modified = deepcopy(self.blueprint)
        modified["calendars"][0]["date_source"] = "official_schedule"
        with self.assertRaisesRegex(FutureCompetitionNotReady, "provisional"):
            self.prepare(blueprint=modified)

    def test_missing_calendar_dates_fails_without_guessing(self):
        modified = deepcopy(self.blueprint)
        modified["calendars"][0]["game_date_list"] = ""
        with self.assertRaisesRegex(FutureCompetitionNotReady, "game days"):
            self.prepare(blueprint=modified)

    def test_unqualified_premain_cannot_use_direct_main_bridge(self):
        # CMP000004 has BRANCH_QUALIFIER and MAIN; this explicit preview
        # cannot bypass its qualifying rules by presenting a list of schools.
        with self.assertRaisesRegex(FutureCompetitionNotReady, "MAIN"):
            self.prepare(competition_id="CMP000004")

    def test_non_sandbox_entry_source_is_rejected(self):
        with self.assertRaisesRegex(FutureCompetitionNotReady, "sandbox"):
            self.prepare(entry_source="official_2027")

    def test_future_dates_outside_year_rejected(self):
        modified = deepcopy(self.blueprint)
        modified["calendars"][0]["game_date_list"] = "2026-03-19"
        with self.assertRaisesRegex(FutureCompetitionNotReady, "wrong year"):
            self.prepare(blueprint=modified)


if __name__ == "__main__":
    unittest.main()
