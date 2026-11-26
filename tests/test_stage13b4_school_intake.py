from __future__ import annotations

import csv
import json
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

INTAKE_REVISION = json.loads(
    (Path(__file__).resolve().parents[1] / "config" / "abilities" / "school_intake_v1.json")
    .read_text(encoding="utf-8")
)["revision"]


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
                hometown_prefecture_code="13",
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

    def test_config_uses_reputation_and_pre_team_strength(self):
        rules = self.model.params["rules"]
        self.assertEqual(
            "reputation",
            self.model.params["quality_model"]["program_component"]["source"],
        )
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
        self.assertEqual(INTAKE_REVISION, snapshot.intake_config_revision)
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

    def test_entry_cap_holds_back_only_the_top_and_keeps_the_amount(self):
        # 入学時の頭打ちで抑えた点（intake_deferred）を足すと、頭打ちがないときの値に戻る
        without = SchoolAwarePlayerAbilityGenerator(CONFIG_DIR)
        without.params = {k: v for k, v in without.params.items() if k != "entry_soft_cap"}
        knee = self.aware_generator.params["entry_soft_cap"]["scalar"]["knee"]
        held_any = False
        for player in make_roster(school_id="SCH_ENTRY_CAP"):
            base = self.base_generator.generate(player, 2026, 2026100701)
            profile = SchoolIntakeProfile(
                school_id=player.school_id, entry_year=player.entry_year,
                generation_seed=2026100701,
                intake_config_id=self.model.config.config_id,
                intake_config_revision=self.model.config.revision,
                intake_config_sha256=self.model.config.canonical_sha256,
                program_quality_z=3.0, cohort_quality_z=0.0, intake_quality_z=3.0,
            )
            capped = self.aware_generator._adjust_snapshot(base=base, player=player, profile=profile)
            full = without._adjust_snapshot(base=base, player=player, profile=profile)
            held = dict(capped.intake_deferred)
            self.assertNotIn("velocity_kmh", held)
            self.assertEqual(full.velocity_kmh, capped.velocity_kmh)
            self.assertEqual(full.pitch_repertoire, capped.pitch_repertoire)
            for name in ("contact", "power", "fielding", "control", "stuff", "catching"):
                if getattr(full, name) is None:
                    continue
                self.assertEqual(getattr(full, name), getattr(capped, name) + held.get(name, 0))
                if getattr(full, name) <= knee:
                    self.assertNotIn(name, held)
            held_any = held_any or bool(held)
        self.assertTrue(held_any)

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
        self.assertEqual(INTAKE_REVISION, team.school_intake_config_revision)
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


class PrivateComponentTests(unittest.TestCase):
    """私立の上乗せ（quality_model.private_component）が評判の順位どおりになだらかに入り、公立には入らない。"""

    def setUp(self):
        from statistics import NormalDist

        self.normal = NormalDist()
        self.model = SchoolIntakeModel(CONFIG_DIR)
        self.real_points = self.model.params["quality_model"]["private_component"]["z_by_share"]
        self.model.params = json.loads(json.dumps(self.model.params))
        self.model.params["quality_model"]["private_component"] = {
            "z_by_share": [[0.0, 0.1], [0.5, 0.3], [0.9, 0.3], [0.98, 0.0], [1.0, 0.0]]}
        owners = {"PRIV": "private", "PREF": "prefectural", "CITY": "municipal", "NATL": "national"}
        self.model.ownership = lambda school_id: owners[school_id[:4]]

    def z(self, share):
        """全校の中の順位（下からの割合）→ 学校成分 z。"""
        return self.normal.inv_cdf(share)

    def test_private_bonus_follows_the_reputation_order(self):
        expected = {0.25: 0.2, 0.7: 0.3, 0.94: 0.15, 0.99: 0.0, 0.999: 0.0}
        for share, bonus in expected.items():
            self.assertAlmostEqual(bonus, self.model.private_z("PRIV-X1", self.z(share)), places=6, msg=share)

    def test_public_and_national_schools_get_nothing(self):
        for school in ("PREF-X1", "CITY-X1", "NATL-X1"):
            for share in (0.25, 0.7, 0.94, 0.99):
                self.assertEqual(0.0, self.model.private_z(school, self.z(share)), school)

    def test_configured_bonus_has_no_steps_and_keeps_the_order(self):
        # 設定の値：ランクの境目（A・Bの境目 0.98 など）で急に変わらず、学校成分と足した入部品質 z は
        # 順位が上がるほど下がらない
        self.model.params["quality_model"]["private_component"]["z_by_share"] = self.real_points
        weight = float(self.model.params["quality_model"]["program_component"]["weight"])
        previous_bonus = previous_total = None
        for step in range(1, 1000):
            z = self.z(step / 1000)
            bonus = self.model.private_z("PRIV-X1", z)
            total = z * weight + bonus
            if previous_bonus is not None:
                self.assertLess(abs(bonus - previous_bonus), 0.02, step)
                self.assertGreaterEqual(total, previous_total, step)
            previous_bonus, previous_total = bonus, total
        self.assertLess(self.model.private_z("PRIV-X1", self.z(0.98)), 0.1)      # A はごく小さく
        self.assertEqual(0.0, self.model.private_z("PRIV-X1", self.z(0.996)))   # S は 0

    def test_bonus_is_added_to_the_intake_quality(self):
        class Fixed:
            def program_z(self, school_id, entry_year):
                return 0.0      # 全校の真ん中（0.5）

        self.model.reputation = Fixed()
        private = self.model.profile(school_id="PRIV-X2", entry_year=2027, base_seed=7)
        public = self.model.profile(school_id="PREF-X2", entry_year=2027, base_seed=7)
        self.assertAlmostEqual(0.3, private.private_quality_z)
        self.assertEqual(0.0, public.private_quality_z)
        # 同じ学校成分・年度の当たり外れなら、差は上乗せの分だけ
        weight = float(self.model.params["quality_model"]["cohort_component"]["weight"])
        self.assertAlmostEqual(
            private.intake_quality_z - private.cohort_quality_z * weight,
            public.intake_quality_z - public.cohort_quality_z * weight + 0.3, places=5)

class PrefectureComponentTests(unittest.TestCase):
    """県の強さの入部品質の項（quality_model.prefecture_component）。ゲームの中の県の強さの入学年度の値を使う。"""

    def setUp(self):
        self.model = SchoolIntakeModel(CONFIG_DIR)
        self.model.params = json.loads(json.dumps(self.model.params))
        self.model.params["quality_model"]["prefecture_component"] = {"z_per_win_rate": 4.0}
        self.model._master_prefecture = {"SCH-A": "98", "SCH-B": "99"}

        class Reputation:
            by_year = {2026: {"98": 0.6, "99": 0.45}, 2027: {"98": 0.55, "99": 0.5}}

            def prefecture_intake_rate(self, code, entry_year):
                return self.by_year[max(2026, entry_year)].get(code, 0.5)

            def program_z(self, school_id, entry_year):
                return 0.0

        self.model.reputation = Reputation()

    def test_term_follows_the_prefecture_strength_of_the_entry_year(self):
        self.assertAlmostEqual(0.4, self.model.prefecture_z("SCH-A", 2025))     # 開始時の在籍は開始時の値
        self.assertAlmostEqual(-0.2, self.model.prefecture_z("SCH-B", 2026))
        self.assertAlmostEqual(0.2, self.model.prefecture_z("SCH-A", 2027))     # ゲームの中で更新された値
        self.assertAlmostEqual(0.0, self.model.prefecture_z("SCH-B", 2027))
        self.assertEqual(0.0, self.model.prefecture_z("SCH-NONE", 2027))       # 県の分からない学校

    def test_term_is_added_to_the_intake_quality(self):
        profile = self.model.profile(school_id="SCH-A", entry_year=2026, base_seed=7)
        self.assertAlmostEqual(0.4, profile.prefecture_quality_z)
        self.model.params["quality_model"].pop("prefecture_component")
        plain = self.model.profile(school_id="SCH-A", entry_year=2026, base_seed=7)
        self.assertAlmostEqual(plain.intake_quality_z + 0.4, profile.intake_quality_z, places=5)


class PublicComponentTests(unittest.TestCase):
    """甲子園の実績のある公立の上乗せ（quality_model.public_component）の対象と、21世紀枠を数えないこと。"""

    def setUp(self):
        self.model = SchoolIntakeModel(CONFIG_DIR)
        self.model.params = json.loads(json.dumps(self.model.params))
        self.model.params["quality_model"]["public_component"] = {
            "recent_years": 15, "z_by_appearances": [[1, 0.2], [3, 0.4], [6, 0.5]]}
        owners = {"PRIV": "private", "PREF": "prefectural", "CITY": "municipal"}
        self.model.ownership = lambda school_id: owners[school_id[:4]]

        class Reputation:
            first_year = 1900       # 実際の記録（historical_data）を使わない
            koshien = {"PREF-X1": [2020, 2021, 2030], "CITY-X1": [2010, 2025, 2031],
                       "PRIV-X1": [2028, 2029, 2030], "PREF-X2": [2014]}

        self.model.reputation = Reputation()

    def test_only_public_schools_with_recent_koshien_get_the_bonus(self):
        self.assertAlmostEqual(0.4, self.model.public_z("PREF-X1", 2031))      # 3回
        self.assertAlmostEqual(0.2, self.model.public_z("CITY-X1", 2031))      # 2010年度は15年より前、2031年度は入学より後
        self.assertEqual(0.0, self.model.public_z("PREF-X2", 2031))            # 16年前だけ
        self.assertEqual(0.0, self.model.public_z("PREF-X3", 2031))            # 出場なし
        self.assertEqual(0.0, self.model.public_z("PRIV-X1", 2031))            # 私立
        self.assertAlmostEqual(0.2, self.model.public_z("PREF-X2", 2029))      # 2014年度が15年の中

    def test_game_entrants_only_skips_players_enrolled_before_the_game(self):
        rule = self.model.params["quality_model"]["public_component"]
        rule["game_entrants_only"] = True
        self.model.reputation.first_year = 2021
        self.assertEqual(0.0, self.model.public_z("PREF-X1", 2020))           # 開始時の在籍
        self.assertAlmostEqual(0.4, self.model.public_z("PREF-X1", 2031))

    def test_century_selection_is_not_counted(self):
        from game_core.annual_reputation import _century_schools
        from game_core.school_intake import historical_koshien

        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "historical_data"
            history.mkdir()
            (history / "koshien_entrants.csv").write_text(
                "kind,year,edition,prefecture_code,team_name,school_id,status,source_id\n"
                "spring,2020,1,99,架空西,PREF-X5,played,X\nspring,2021,2,99,架空西,PREF-X5,played,X\n"
                "summer,2021,3,99,架空西,PREF-X5,played,X\nsummer,2022,4,99,架空西,PREF-X5,withdrawn,X\n",
                encoding="utf-8")
            (history / "senbatsu_century_entrants.csv").write_text(
                "year,prefecture_code,team_name,school_id,source_id\n2021,99,架空西,PREF-X5,X\n", encoding="utf-8")
            # 選抜は前の年度。2021年の選抜は21世紀枠、2022年の夏は辞退で数えない
            self.assertEqual((2019, 2021), historical_koshien(tmp)["PREF-X5"])

        class Season:
            history = [{"action": "select_invitational", "competition_id": "SEN",
                        "selection_basis": {"PREF-X6": "century", "PRIV-X6": "jingu"}}]

        self.assertEqual({"PREF-X6"}, _century_schools(Season(), "SEN"))
        self.assertEqual(set(), _century_schools(Season(), "OTHER"))


if __name__ == "__main__":
    unittest.main()
