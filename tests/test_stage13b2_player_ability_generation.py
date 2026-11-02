from __future__ import annotations

import copy
import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from game_core.abilities import (
    BATTER_ABILITIES,
    FIELD_POSITIONS,
    PlayerAbilityGenerator,
    PlayerAbilitySnapshot,
    validate_ability_snapshot,
    write_ability_snapshots_csv,
)
from game_core.ability_audit import audit_ability_snapshots
from game_core.players import Player

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config" / "abilities"


def make_player(
    player_id: str,
    *,
    grade: int,
    position: str,
    roster_no: int = 1,
) -> Player:
    return Player(
        player_id=player_id,
        school_id="SCH_GOLDEN",
        program_id="PRG_GOLDEN",
        display_name=player_id,
        name_source="test",
        hometown_prefecture_code="13",
        academic_year=grade,
        entry_year=2026 - grade + 1,
        roster_no=roster_no,
        primary_position=position,
        position_group=(
            "pitcher"
            if position == "P"
            else "catcher"
            if position == "C"
            else "infielder"
            if position in {"1B", "2B", "3B", "SS"}
            else "outfielder"
        ),
        bats="R",
        throws="R",
        roster_status="active_core",
        generation_seed=2026100701,
    )


class Stage13B2PlayerAbilityGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = PlayerAbilityGenerator(CONFIG_DIR)
        cls.seed = 2026100701
        cls.year = 2026

    def test_regular_player_has_all_batter_abilities(self):
        player = make_player("PLYTESTSS000000000001", grade=2, position="SS")
        snapshot = self.generator.generate(player, self.year, self.seed)
        for ability_id in BATTER_ABILITIES:
            value = snapshot.ability(ability_id)
            self.assertIsNotNone(value)
            self.assertGreaterEqual(value, 1)
            self.assertLessEqual(value, 100)

    def test_pitcher_has_pitcher_abilities_and_repertoire(self):
        player = make_player("PLYTESTP0000000000001", grade=2, position="P")
        snapshot = self.generator.generate(player, self.year, self.seed)
        self.assertIsNotNone(snapshot.velocity_kmh)
        self.assertGreaterEqual(snapshot.velocity_kmh, 100)
        self.assertLessEqual(snapshot.velocity_kmh, 165)
        self.assertGreaterEqual(len(snapshot.pitch_repertoire), 2)
        self.assertLessEqual(len(snapshot.pitch_repertoire), 4)
        self.assertIn(
            "four_seam",
            {pitch.pitch_type for pitch in snapshot.pitch_repertoire},
        )
        self.assertEqual(
            100,
            sum(pitch.usage for pitch in snapshot.pitch_repertoire),
        )

    def test_non_pitcher_has_no_pitcher_only_values(self):
        player = make_player("PLYTESTCF000000000001", grade=2, position="CF")
        snapshot = self.generator.generate(player, self.year, self.seed)
        self.assertIsNone(snapshot.velocity_kmh)
        self.assertIsNone(snapshot.control)
        self.assertEqual((), snapshot.pitch_repertoire)

    def test_catcher_has_catcher_only_values(self):
        catcher = self.generator.generate(
            make_player("PLYTESTC0000000000001", grade=2, position="C"),
            self.year,
            self.seed,
        )
        shortstop = self.generator.generate(
            make_player("PLYTESTSS00000000002", grade=2, position="SS"),
            self.year,
            self.seed,
        )
        self.assertIsNotNone(catcher.catching)
        self.assertIsNotNone(catcher.game_calling)
        self.assertIsNone(shortstop.catching)
        self.assertIsNone(shortstop.game_calling)

    def test_position_aptitude_has_all_positions(self):
        player = make_player("PLYTEST2B000000000001", grade=1, position="2B")
        snapshot = self.generator.generate(player, self.year, self.seed)
        self.assertEqual(
            set(FIELD_POSITIONS),
            set(dict(snapshot.position_aptitude)),
        )
        self.assertGreaterEqual(snapshot.aptitude("2B"), 60)

    def test_generation_is_deterministic(self):
        player = make_player("PLYDETERMINISTIC000001", grade=3, position="3B")
        first = self.generator.generate(player, self.year, self.seed)
        second = self.generator.generate(player, self.year, self.seed)
        self.assertEqual(first, second)

    def test_different_seed_changes_abilities(self):
        player = make_player("PLYSEEDCHANGE00000001", grade=2, position="LF")
        first = self.generator.generate(player, self.year, self.seed)
        second = self.generator.generate(player, self.year, self.seed + 1)
        self.assertNotEqual(first.contact, second.contact)
        self.assertNotEqual(first.position_aptitude, second.position_aptitude)

    def test_config_identity_is_embedded(self):
        player = make_player("PLYCONFIG000000000001", grade=2, position="RF")
        snapshot = self.generator.generate(player, self.year, self.seed)
        self.assertEqual("ability_catalog_v1", snapshot.catalog_config_id)
        self.assertEqual("ability_scale_v1", snapshot.scale_config_id)
        self.assertEqual(
            "player_generation_v1",
            snapshot.generation_config_id,
        )
        self.assertEqual(64, len(snapshot.catalog_sha256))
        self.assertEqual(64, len(snapshot.scale_sha256))
        self.assertEqual(64, len(snapshot.generation_sha256))

    def test_snapshot_validator_accepts_generated_values(self):
        player = make_player("PLYVALID0000000000001", grade=1, position="P")
        snapshot = self.generator.generate(player, self.year, self.seed)
        validate_ability_snapshot(snapshot)

    def test_structured_abilities_are_not_scalar_lookup(self):
        player = make_player("PLYSTRUCT000000000001", grade=2, position="P")
        snapshot = self.generator.generate(player, self.year, self.seed)
        with self.assertRaises(ValueError):
            snapshot.ability("position_aptitude")
        with self.assertRaises(ValueError):
            snapshot.ability("pitch_repertoire")

    def test_csv_export(self):
        players = [
            make_player("PLYCSV000000000000001", grade=1, position="P"),
            make_player("PLYCSV000000000000002", grade=2, position="C"),
            make_player("PLYCSV000000000000003", grade=3, position="SS"),
        ]
        snapshots = [
            self.generator.generate(player, self.year, self.seed)
            for player in players
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "abilities.csv"
            summary = write_ability_snapshots_csv(snapshots, path)
            with path.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(3, summary["snapshot_count"])
        self.assertEqual(3, len(rows))
        self.assertIn("position_aptitude_json", rows[0])
        self.assertIn("pitch_repertoire_json", rows[0])

    def test_namespace_isolation_when_contact_mean_changes(self):
        player = make_player("PLYISOLATION000000001", grade=2, position="SS")
        original = self.generator.generate(player, self.year, self.seed)

        with tempfile.TemporaryDirectory() as td:
            temp_config = Path(td) / "abilities"
            shutil.copytree(CONFIG_DIR, temp_config)
            generation_path = temp_config / "player_generation_v1.json"
            payload = json.loads(generation_path.read_text(encoding="utf-8"))
            payload["revision"] += 1
            payload["batter_abilities"]["contact"]["mean"] += 10
            generation_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            changed = PlayerAbilityGenerator(temp_config).generate(
                player,
                self.year,
                self.seed,
            )

        self.assertNotEqual(original.contact, changed.contact)
        for ability_id in BATTER_ABILITIES:
            if ability_id == "contact":
                continue
            self.assertEqual(
                original.ability(ability_id),
                changed.ability(ability_id),
                ability_id,
            )
        self.assertEqual(
            original.position_aptitude,
            changed.position_aptitude,
        )

    def test_audit_produces_percentile_rows(self):
        snapshots = [
            self.generator.generate(
                make_player(
                    f"PLYAUDIT{index:014d}",
                    grade=(index % 3) + 1,
                    position=("P", "C", "SS")[index % 3],
                    roster_no=index + 1,
                ),
                self.year,
                self.seed,
            )
            for index in range(30)
        ]
        rows = audit_ability_snapshots(snapshots, seed=self.seed)
        contact = next(
            row
            for row in rows
            if row.dimension == "overall"
            and row.metric == "contact"
        )
        self.assertEqual(30, contact.n)
        self.assertLessEqual(contact.p01, contact.p50)
        self.assertLessEqual(contact.p50, contact.p99)


if __name__ == "__main__":
    unittest.main()
