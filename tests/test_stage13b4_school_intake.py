from __future__ import annotations

import csv
import statistics
import tempfile
import unittest
from pathlib import Path

from game_core.abilities import PlayerAbilityGenerator
from game_core.players import Player
from game_core.school_intake import (
    IntakeAdjustedPlayerAbilitySnapshot,
    SchoolAwarePlayerAbilityGenerator,
    SchoolIntakeModel,
    SchoolIntakeProfile,
)
from game_core.team_strength import (
    TeamStrengthGenerator,
    write_team_strength_csv,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config" / "abilities"

POSITIONS = (
    "P", "P", "P", "P", "P",
    "C", "C",
    "1B",
    "2B", "2B",
    "3B", "3B",
    "SS", "SS",
    "LF", "LF",
    "CF", "CF",
    "RF", "RF",
)


def _position_group(position: str) -> str:
    if position == "P":
        return "pitcher"
    if position == "C":
        return "catcher"
    if position in {"1B", "2B", "3B", "SS"}:
        return "infielder"
    return "outfielder"


def make_roster(
    *,
    school_id: str,
    year: int = 2026,
    seed: int = 2026100701,
) -> list[Player]:
    grade_slots = [1] * 5 + [2] * 7 + [3] * 8
    players: list[Player] = []
    for index, position in enumerate(POSITIONS, start=1):
        grade = grade_slots[index - 1]
        players.append(
            Player(
                player_id=f"{school_id}:PLY:{index:02d}",
                school_id=school_id,
                program_id=f"{school_id}:PRG",
                display_name=f"選手{index:02d}",
                name_source="test",
                academic_year=grade,
                entry_year=year - grade + 1,
                roster_no=index,
                primary_position=position,
                position_group=_position_group(position),
                bats="R",
                throws="R",
                roster_status="active_core",
                generation_seed=seed,
            )
        )
    return players


class Stage13B4SchoolIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = SchoolIntakeModel(CONFIG_DIR)
        cls.base_generator = PlayerAbilityGenerator(CONFIG_DIR)
        cls.aware_generator = SchoolAwarePlayerAbilityGenerator(CONFIG_DIR)
        cls.team_generator = TeamStrengthGenerator(CONFIG_DIR)

    def test_config_is_explicitly_synthetic_and_pre_team_strength(self):
        rules = self.model.params["rules"]
        self.assertTrue(rules["synthetic_not_real_school_rating"])
        self.assertTrue(rules["applied_before_team_strength"])
        self.assertFalse(rules["direct_team_strength_bonus"])
        self.assertEqual("entry_year", rules["cohort_key"])

    def test_profile_is_deterministic(self):
        first = self.model.profile(
            school_id="SCH_TEST_A",
            entry_year=2026,
            base_seed=2026100701,
        )
        second = self.model.profile(
            school_id="SCH_TEST_A",
            entry_year=2026,
            base_seed=2026100701,
        )
        self.assertEqual(first, second)

    def test_program_component_persists_across_cohorts(self):
        first = self.model.profile(
            school_id="SCH_TEST_A",
            entry_year=2024,
            base_seed=2026100701,
        )
        second = self.model.profile(
            school_id="SCH_TEST_A",
            entry_year=2025,
            base_seed=2026100701,
        )
        self.assertEqual(
            first.program_quality_z,
            second.program_quality_z,
        )
        self.assertNotEqual(
            first.cohort_quality_z,
            second.cohort_quality_z,
        )

    def test_different_school_changes_program_component(self):
        left = self.model.profile(
            school_id="SCH_TEST_A",
            entry_year=2026,
            base_seed=2026100701,
        )
        right = self.model.profile(
            school_id="SCH_TEST_B",
            entry_year=2026,
            base_seed=2026100701,
        )
        self.assertNotEqual(
            left.program_quality_z,
            right.program_quality_z,
        )

    def test_intake_quality_is_clipped_to_configured_bounds(self):
        clip = self.model.params["quality_model"]["combined_clip"]
        for index in range(200):
            profile = self.model.profile(
                school_id=f"SCH_CLIP_{index:04d}",
                entry_year=2026,
                base_seed=2026100701,
            )
            self.assertGreaterEqual(
                profile.intake_quality_z,
                float(clip["min"]),
            )
            self.assertLessEqual(
                profile.intake_quality_z,
                float(clip["max"]),
            )

    def test_school_aware_snapshot_embeds_intake_provenance(self):
        player = make_roster(school_id="SCH_PROVENANCE")[0]
        snapshot = self.aware_generator.generate(
            player,
            2026,
            2026100701,
        )
        self.assertIsInstance(
            snapshot,
            IntakeAdjustedPlayerAbilitySnapshot,
        )
        self.assertEqual("school_intake_v1", snapshot.intake_config_id)
        self.assertEqual(1, snapshot.intake_config_revision)
        self.assertEqual(64, len(snapshot.intake_config_sha256))
        self.assertEqual(player.player_id, snapshot.player_id)

    def test_positive_quality_profile_raises_core_abilities(self):
        player = make_roster(school_id="SCH_DIRECTION")[0]
        base = self.base_generator.generate(
            player,
            2026,
            2026100701,
        )
        common = dict(
            school_id=player.school_id,
            entry_year=player.entry_year,
            generation_seed=2026100701,
            intake_config_id=self.model.config.config_id,
            intake_config_revision=self.model.config.revision,
            intake_config_sha256=self.model.config.canonical_sha256,
            program_quality_z=0.0,
            cohort_quality_z=0.0,
        )
        low = SchoolIntakeProfile(
            **common,
            intake_quality_z=-2.0,
        )
        high = SchoolIntakeProfile(
            **common,
            intake_quality_z=2.0,
        )
        low_snapshot = self.aware_generator._adjust_snapshot(
            base=base,
            player=player,
            profile=low,
        )
        high_snapshot = self.aware_generator._adjust_snapshot(
            base=base,
            player=player,
            profile=high,
        )
        self.assertGreater(high_snapshot.contact, low_snapshot.contact)
        self.assertGreater(high_snapshot.power, low_snapshot.power)
        self.assertGreater(
            high_snapshot.velocity_kmh,
            low_snapshot.velocity_kmh,
        )

    def test_baseline_generator_remains_available(self):
        player = make_roster(school_id="SCH_BASELINE")[0]
        first = self.base_generator.generate(
            player,
            2026,
            2026100701,
        )
        second = self.base_generator.generate(
            player,
            2026,
            2026100701,
        )
        self.assertEqual(first, second)
        self.assertFalse(hasattr(first, "intake_quality_z"))

    def test_team_strength_embeds_intake_config_provenance(self):
        players = make_roster(school_id="SCH_TEAM_INTAKE")
        abilities = list(
            self.aware_generator.iter_roster(
                players,
                2026,
                2026100701,
            )
        )
        team = self.team_generator.generate(abilities)
        self.assertEqual(
            "school_intake_v1",
            team.school_intake_config_id,
        )
        self.assertEqual(1, team.school_intake_config_revision)
        self.assertEqual(64, len(team.school_intake_config_sha256 or ""))

    def test_mixing_baseline_and_intake_snapshots_is_rejected(self):
        players = make_roster(school_id="SCH_MIXED")
        aware = list(
            self.aware_generator.iter_roster(
                players,
                2026,
                2026100701,
            )
        )
        aware[0] = self.base_generator.generate(
            players[0],
            2026,
            2026100701,
        )
        with self.assertRaises(ValueError):
            self.team_generator.generate(aware)

    def test_school_intake_increases_between_school_strength_variance(self):
        seed = 2026100701
        baseline_batting: list[float] = []
        intake_batting: list[float] = []
        baseline_pitching: list[float] = []
        intake_pitching: list[float] = []

        for index in range(160):
            school_id = f"SCH_VARIANCE_{index:04d}"
            players = make_roster(
                school_id=school_id,
                seed=seed,
            )
            baseline = self.team_generator.generate(
                list(
                    self.base_generator.iter_roster(
                        players,
                        2026,
                        seed,
                    )
                )
            )
            aware = self.team_generator.generate(
                list(
                    self.aware_generator.iter_roster(
                        players,
                        2026,
                        seed,
                    )
                )
            )
            baseline_batting.append(baseline.batting_strength)
            intake_batting.append(aware.batting_strength)
            baseline_pitching.append(baseline.pitching_strength)
            intake_pitching.append(aware.pitching_strength)

        baseline_batting_sd = statistics.pstdev(baseline_batting)
        intake_batting_sd = statistics.pstdev(intake_batting)
        baseline_pitching_sd = statistics.pstdev(baseline_pitching)
        intake_pitching_sd = statistics.pstdev(intake_pitching)

        self.assertGreater(
            intake_batting_sd,
            baseline_batting_sd + 0.8,
        )
        self.assertGreater(
            intake_pitching_sd,
            baseline_pitching_sd + 0.8,
        )

    def test_team_strength_csv_contains_intake_provenance(self):
        players = make_roster(school_id="SCH_CSV")
        team = self.team_generator.generate(
            list(
                self.aware_generator.iter_roster(
                    players,
                    2026,
                    2026100701,
                )
            )
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "team.csv"
            write_team_strength_csv([team], path)
            with path.open(encoding="utf-8-sig", newline="") as f:
                row = next(csv.DictReader(f))
        self.assertEqual(
            "school_intake_v1",
            row["school_intake_config_id"],
        )
        self.assertEqual(
            team.school_intake_config_sha256,
            row["school_intake_config_sha256"],
        )

    def test_clis_expose_baseline_switch(self):
        ability_cli = (
            ROOT / "game_core" / "ability_cli.py"
        ).read_text(encoding="utf-8")
        team_cli = (
            ROOT / "game_core" / "team_strength_cli.py"
        ).read_text(encoding="utf-8")
        self.assertIn("--baseline-no-school-intake", ability_cli)
        self.assertIn("--baseline-no-school-intake", team_cli)


if __name__ == "__main__":
    unittest.main()
