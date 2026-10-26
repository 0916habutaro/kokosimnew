from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from game_core.player_names import PlayerIdentity
from game_core.players import (
    CORE_ROSTER_SIZE,
    GRADE_COUNTS,
    POSITION_SLOTS,
    PlayerRosterGenerator,
    validate_school_roster,
    write_players_csv,
)
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]


class Stage13APlayerRosterFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.school_ids = sorted(cls.repo.school_to_program)[:2]
        cls.generator = PlayerRosterGenerator()
        cls.seed = 2026100701

    def test_roster_has_20_players(self):
        roster = self.generator.generate_for_school_id(
            self.repo,
            self.school_ids[0],
            2026,
            self.seed,
        )
        self.assertEqual(CORE_ROSTER_SIZE, len(roster.players))

    def test_roster_is_deterministic_for_same_seed(self):
        first = self.generator.generate_for_school_id(
            self.repo,
            self.school_ids[0],
            2026,
            self.seed,
        )
        second = self.generator.generate_for_school_id(
            self.repo,
            self.school_ids[0],
            2026,
            self.seed,
        )
        self.assertEqual(
            [player.to_dict() for player in first.players],
            [player.to_dict() for player in second.players],
        )

    def test_different_seed_changes_player_identity(self):
        first = self.generator.generate_for_school_id(
            self.repo,
            self.school_ids[0],
            2026,
            self.seed,
        )
        second = self.generator.generate_for_school_id(
            self.repo,
            self.school_ids[0],
            2026,
            self.seed + 1,
        )
        self.assertNotEqual(
            [player.player_id for player in first.players],
            [player.player_id for player in second.players],
        )

    def test_grade_distribution_contract(self):
        roster = self.generator.generate_for_school_id(
            self.repo,
            self.school_ids[0],
            2026,
            self.seed,
        )
        actual = {
            grade: sum(
                player.academic_year == grade
                for player in roster.players
            )
            for grade in (1, 2, 3)
        }
        self.assertEqual(GRADE_COUNTS, actual)

    def test_position_slot_contract(self):
        roster = self.generator.generate_for_school_id(
            self.repo,
            self.school_ids[0],
            2026,
            self.seed,
        )
        self.assertEqual(
            sorted(POSITION_SLOTS),
            sorted(player.primary_position for player in roster.players),
        )
        self.assertEqual(
            5,
            sum(player.position_group == "pitcher" for player in roster.players),
        )
        self.assertEqual(
            2,
            sum(player.position_group == "catcher" for player in roster.players),
        )

    def test_roster_numbers_are_1_to_20(self):
        roster = self.generator.generate_for_school_id(
            self.repo,
            self.school_ids[0],
            2026,
            self.seed,
        )
        self.assertEqual(
            list(range(1, 21)),
            [player.roster_no for player in roster.players],
        )

    def test_player_ids_are_unique_across_two_schools(self):
        rosters = [
            self.generator.generate_for_school_id(
                self.repo,
                school_id,
                2026,
                self.seed,
            )
            for school_id in self.school_ids
        ]
        ids = [
            player.player_id
            for roster in rosters
            for player in roster.players
        ]
        self.assertEqual(40, len(ids))
        self.assertEqual(40, len(set(ids)))

    def test_entry_year_matches_academic_year(self):
        roster = self.generator.generate_for_school_id(
            self.repo,
            self.school_ids[0],
            2026,
            self.seed,
        )
        for player in roster.players:
            self.assertEqual(
                2026 - player.academic_year + 1,
                player.entry_year,
            )

    def test_generated_names_have_hometown_and_are_unique_in_school(self):
        roster = self.generator.generate_for_school_id(
            self.repo,
            self.school_ids[0],
            2026,
            self.seed,
        )
        self.assertTrue(
            all(player.name_source == "player_names_v1" for player in roster.players)
        )
        names = [player.display_name for player in roster.players]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(" " in name for name in names))
        self.assertTrue(all(player.hometown_prefecture_code for player in roster.players))
        again = self.generator.generate_for_school_id(
            self.repo, self.school_ids[0], 2026, self.seed,
        )
        self.assertEqual(roster, again)

    def test_custom_name_provider_can_replace_default(self):
        def provider(team, base_seed, rng, taken):
            del base_seed, rng
            return PlayerIdentity(
                f"テスト選手{len(taken) + 1:02d}", "test_provider", team.prefecture_code,
            )

        generator = PlayerRosterGenerator(name_provider=provider)
        roster = generator.generate_for_school_id(
            self.repo,
            self.school_ids[0],
            2026,
            self.seed,
        )
        self.assertEqual("テスト選手01", roster.players[0].display_name)
        self.assertEqual("test_provider", roster.players[0].name_source)

    def test_provider_returning_a_taken_name_is_rejected(self):
        def provider(team, base_seed, rng, taken):
            return PlayerIdentity("同じ 名前", "test_provider", team.prefecture_code)

        with self.assertRaisesRegex(ValueError, "duplicate player name"):
            PlayerRosterGenerator(name_provider=provider).generate_for_school_id(
                self.repo, self.school_ids[0], 2026, self.seed,
            )

    def test_validate_school_roster_accepts_generated_roster(self):
        roster = self.generator.generate_for_school_id(
            self.repo,
            self.school_ids[0],
            2026,
            self.seed,
        )
        validate_school_roster(roster)

    def test_iter_all_rosters_begins_in_school_id_order(self):
        iterator = self.generator.iter_all_rosters(
            self.repo,
            2026,
            self.seed,
        )
        first = next(iterator)
        second = next(iterator)
        self.assertEqual(self.school_ids, [first.school_id, second.school_id])

    def test_csv_writer_contract(self):
        rosters = [
            self.generator.generate_for_school_id(
                self.repo,
                school_id,
                2026,
                self.seed,
            )
            for school_id in self.school_ids
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "players.csv"
            summary = write_players_csv(rosters, path)
            with path.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))

        self.assertEqual(2, summary["roster_count"])
        self.assertEqual(40, summary["player_count"])
        self.assertEqual(40, len(rows))
        self.assertIn("player_id", rows[0])
        self.assertIn("academic_year", rows[0])
        self.assertIn("primary_position", rows[0])
        self.assertIn("name_source", rows[0])

    def test_cli_source_supports_one_school_or_all(self):
        source = (
            ROOT / "game_core" / "player_cli.py"
        ).read_text(encoding="utf-8")
        self.assertIn("--school-id", source)
        self.assertIn("iter_all_rosters", source)
        self.assertIn("write_players_csv", source)


if __name__ == "__main__":
    unittest.main()
