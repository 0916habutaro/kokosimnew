from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from game_core.ability_config import (
    canonical_config_sha256,
    load_and_validate_ability_configs,
    load_config,
    validate_ability_catalog,
    validate_ability_scale,
    validate_player_generation,
    validate_school_intake,
    validate_team_strength,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config" / "abilities"


class Stage13B1AbilityDesignGovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.configs = load_and_validate_ability_configs(CONFIG_DIR)
        cls.catalog = cls.configs["ability_catalog_v1"]
        cls.scale = cls.configs["ability_scale_v1"]
        cls.generation = cls.configs["player_generation_v1"]
        cls.intake = cls.configs["school_intake_v1"]
        cls.team = cls.configs["team_strength_v1"]

    def test_all_ability_configs_load(self):
        self.assertEqual(
            {
                "ability_catalog_v1",
                "ability_scale_v1",
                "player_generation_v1",
                "school_intake_v1",
                "team_strength_v1",
            },
            set(self.configs),
        )

    def test_catalog_contains_expected_core_abilities(self):
        ids = {
            item["ability_id"]
            for item in self.catalog.payload["abilities"]
        }
        expected = {
            "contact",
            "power",
            "plate_discipline",
            "strikeout_resistance",
            "bunt",
            "speed",
            "baserunning",
            "stealing",
            "arm_strength",
            "fielding",
            "throwing",
            "catching",
            "game_calling",
            "velocity_kmh",
            "control",
            "stamina",
            "stuff",
            "strikeout",
            "groundball",
            "composure",
            "position_aptitude",
            "pitch_repertoire",
        }
        self.assertTrue(expected.issubset(ids))

    def test_scale_is_1_to_100_and_bands_cover_all_values(self):
        self.assertEqual(
            {"min": 1, "max": 100, "neutral": 50},
            self.scale.payload["scalar_scale"],
        )
        validate_ability_scale(self.scale)

    def test_generation_references_catalog(self):
        validate_player_generation(
            self.generation,
            catalog=self.catalog,
        )

    def test_school_intake_references_catalog(self):
        validate_school_intake(
            self.intake,
            catalog=self.catalog,
        )

    def test_team_strength_references_catalog(self):
        validate_team_strength(
            self.team,
            catalog=self.catalog,
        )

    def test_team_strength_is_derived_not_fixed_school_rating(self):
        source = self.team.payload["source_contract"]
        self.assertFalse(source["direct_school_rating_bonus"])
        self.assertTrue(
            self.team.payload["rules"][
                "team_strength_is_snapshot_not_school_master"
            ]
        )

    def test_match_model_uses_components_not_single_overall(self):
        self.assertTrue(
            self.team.payload["rules"][
                "match_simulation_should_use_components_not_single_overall"
            ]
        )

    def test_rng_namespaces_are_versioned_and_ability_specific(self):
        policy = self.generation.payload["rng_namespace_policy"]
        self.assertIn("{ability_id}", policy["scalar_ability"])
        self.assertIn("{position}", policy["position_aptitude"])
        self.assertIn("{pitch_type}", policy["pitch_repertoire"])
        self.assertTrue(
            all("_v1:" in template for template in policy.values())
        )

    def test_config_hash_is_stable_across_key_order(self):
        left = {"b": 2, "a": 1}
        right = {"a": 1, "b": 2}
        self.assertEqual(
            canonical_config_sha256(left),
            canonical_config_sha256(right),
        )

    def test_config_hash_changes_when_parameter_changes(self):
        first = {"mean": 50, "stddev": 12}
        second = {"mean": 51, "stddev": 12}
        self.assertNotEqual(
            canonical_config_sha256(first),
            canonical_config_sha256(second),
        )

    def test_wrong_config_id_is_rejected(self):
        path = CONFIG_DIR / "ability_scale_v1.json"
        with self.assertRaises(ValueError):
            load_config(path, expected_config_id="wrong_id")

    def test_duplicate_ability_id_is_rejected(self):
        payload = copy.deepcopy(self.catalog.payload)
        payload["abilities"].append(copy.deepcopy(payload["abilities"][0]))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "catalog.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            document = load_config(path)
            with self.assertRaises(ValueError):
                validate_ability_catalog(document)

    def test_broken_display_band_is_rejected(self):
        payload = copy.deepcopy(self.scale.payload)
        payload["display_bands"][0]["min"] = 91
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "scale.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            document = load_config(path)
            with self.assertRaises(ValueError):
                validate_ability_scale(document)

    def test_non_normalized_team_weight_is_rejected(self):
        payload = copy.deepcopy(self.team.payload)
        payload["batting"]["lineup_weights"]["contact"] = 0.40
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "team.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            document = load_config(path)
            with self.assertRaises(ValueError):
                validate_team_strength(
                    document,
                    catalog=self.catalog,
                )

    def test_direct_school_bonus_is_rejected(self):
        payload = copy.deepcopy(self.team.payload)
        payload["source_contract"]["direct_school_rating_bonus"] = True
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "team.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            document = load_config(path)
            with self.assertRaises(ValueError):
                validate_team_strength(
                    document,
                    catalog=self.catalog,
                )

    def test_intake_direct_team_bonus_is_rejected(self):
        payload = copy.deepcopy(self.intake.payload)
        payload["rules"]["direct_team_strength_bonus"] = True
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "intake.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            document = load_config(path)
            with self.assertRaises(ValueError):
                validate_school_intake(
                    document,
                    catalog=self.catalog,
                )

    def test_intake_must_be_marked_synthetic(self):
        payload = copy.deepcopy(self.intake.payload)
        payload["rules"]["synthetic_not_real_school_rating"] = False
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "intake.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            document = load_config(path)
            with self.assertRaises(ValueError):
                validate_school_intake(
                    document,
                    catalog=self.catalog,
                )

    def test_generation_school_match_bonus_is_rejected(self):
        payload = copy.deepcopy(self.generation.payload)
        payload["school_context"]["direct_match_strength_bonus"] = True
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "generation.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            document = load_config(path)
            with self.assertRaises(ValueError):
                validate_player_generation(
                    document,
                    catalog=self.catalog,
                )

    def test_design_documents_exist(self):
        required = [
            ROOT / "docs" / "design" / "player_ability_design.md",
            ROOT / "docs" / "design" / "player_ability_catalog.md",
            ROOT / "docs" / "design" / "team_strength_design.md",
            ROOT / "docs" / "design" / "ability_tuning_workflow.md",
            ROOT / "docs" / "adr" / "ADR-001-team-strength-derived-from-players.md",
            ROOT / "docs" / "adr" / "ADR-002-ability-scale-and-display.md",
            ROOT / "docs" / "adr" / "ADR-003-ability-snapshot-separation.md",
            ROOT / "docs" / "adr" / "ADR-004-versioned-rng-namespaces.md",
            ROOT / "docs" / "adr" / "ADR-005-config-not-code-for-tuning.md",
        ]
        self.assertTrue(all(path.exists() for path in required))


if __name__ == "__main__":
    unittest.main()
