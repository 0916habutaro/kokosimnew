from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from game_core.abilities import PlayerAbilityGenerator
from game_core.players import Player
from game_core.team_strength import (
    STARTING_POSITIONS,
    TEAM_STRENGTH_METRICS,
    TeamStrengthGenerator,
    validate_team_strength_snapshot,
    write_team_strength_csv,
)
from game_core.team_strength_audit import audit_team_strength_snapshots

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config" / "abilities"
DIST_PATH = (
    ROOT
    / "audits"
    / "phase3"
    / "stage13b3"
    / "stage13b3_strength_distribution_20261007.csv"
)

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


def make_roster_abilities(
    *,
    school_id: str = "SCH_TEAM_TEST",
    year: int = 2026,
    seed: int = 2026100701,
):
    generator = PlayerAbilityGenerator(CONFIG_DIR)
    players = []
    grade_slots = [1] * 5 + [2] * 7 + [3] * 8
    for index, position in enumerate(POSITIONS, start=1):
        grade = grade_slots[index - 1]
        player = Player(
            player_id=f"PLYTEAM{index:014d}",
            school_id=school_id,
            program_id="PRG_TEAM_TEST",
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
        players.append(generator.generate(player, year, seed))
    return players


class Stage13B3TeamStrengthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = TeamStrengthGenerator(CONFIG_DIR)
        cls.abilities = make_roster_abilities()
        cls.snapshot = cls.generator.generate(cls.abilities)

    def test_starting_lineup_has_nine_unique_positions(self):
        lineup = self.snapshot.starting_lineup
        self.assertEqual(9, len(lineup.entries))
        self.assertEqual(
            set(STARTING_POSITIONS),
            {entry.defensive_position for entry in lineup.entries},
        )
        self.assertEqual(
            list(range(1, 10)),
            sorted(entry.batting_order for entry in lineup.entries),
        )
        self.assertEqual(9, len(set(lineup.starter_ids)))

    def test_pitching_staff_contains_all_five_pitchers(self):
        staff = self.snapshot.pitching_staff
        self.assertEqual(5, len(staff.entries))
        self.assertEqual("ace", staff.entries[0].role)
        self.assertEqual(
            sorted(
                [entry.quality for entry in staff.entries],
                reverse=True,
            ),
            [entry.quality for entry in staff.entries],
        )

    def test_lineup_pitcher_is_ace(self):
        self.assertEqual(
            self.snapshot.starting_lineup.player_for_position("P"),
            self.snapshot.pitching_staff.ace_player_id,
        )

    def test_team_strength_metrics_are_in_1_to_100(self):
        for metric in TEAM_STRENGTH_METRICS:
            value = getattr(self.snapshot, metric)
            self.assertGreaterEqual(value, 1.0, metric)
            self.assertLessEqual(value, 100.0, metric)

    def test_generation_is_deterministic(self):
        second = self.generator.generate(make_roster_abilities())
        self.assertEqual(self.snapshot, second)

    def test_config_provenance_is_embedded(self):
        self.assertEqual("team_strength_v1", self.snapshot.team_config_id)
        self.assertEqual(2, self.snapshot.team_config_revision)
        self.assertEqual(64, len(self.snapshot.team_config_sha256))
        self.assertEqual(64, len(self.snapshot.player_generation_sha256))

    def test_snapshot_validator_accepts_generated_snapshot(self):
        validate_team_strength_snapshot(self.snapshot)

    def test_school_id_mixing_is_rejected(self):
        mixed = list(self.abilities)
        other = make_roster_abilities(school_id="SCH_OTHER")[0]
        mixed[0] = other
        with self.assertRaises(ValueError):
            self.generator.generate(mixed)

    def test_csv_export_contains_lineup_and_staff_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "team_strength.csv"
            summary = write_team_strength_csv([self.snapshot], path)
            with path.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(1, summary["team_count"])
        self.assertEqual(1, len(rows))
        lineup = json.loads(rows[0]["starting_lineup_json"])
        staff = json.loads(rows[0]["pitching_staff_json"])
        self.assertEqual(9, len(lineup["entries"]))
        self.assertEqual(5, len(staff["entries"]))

    def test_audit_produces_all_ten_metrics(self):
        snapshots = [
            self.generator.generate(
                make_roster_abilities(
                    school_id=f"SCH_AUDIT_{index:03d}",
                    seed=2026100701 + index,
                )
            )
            for index in range(10)
        ]
        rows = audit_team_strength_snapshots(
            snapshots,
            seed=2026100701,
        )
        self.assertEqual(
            set(TEAM_STRENGTH_METRICS),
            {row.metric for row in rows},
        )
        self.assertTrue(all(row.n == 10 for row in rows))

    def test_saved_distribution_has_three_seeds_and_thirty_rows(self):
        with DIST_PATH.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(30, len(rows))
        self.assertEqual(
            {"2026100701", "2026100702", "2026100703"},
            {row["seed"] for row in rows},
        )
        self.assertEqual(
            set(TEAM_STRENGTH_METRICS),
            {row["metric"] for row in rows},
        )

    def test_saved_distribution_seed_means_are_stable(self):
        with DIST_PATH.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        by_metric: dict[str, list[float]] = {}
        for row in rows:
            by_metric.setdefault(
                row["metric"], []
            ).append(float(row["mean"]))
        for metric, means in by_metric.items():
            self.assertEqual(3, len(means))
            self.assertLess(max(means) - min(means), 0.5, metric)

    def test_cli_exposes_team_strength_outputs(self):
        source = (
            ROOT / "game_core" / "team_strength_cli.py"
        ).read_text(encoding="utf-8")
        self.assertIn("--output", source)
        self.assertIn("--audit-output", source)
        self.assertIn("--school-limit", source)


if __name__ == "__main__":
    unittest.main()
