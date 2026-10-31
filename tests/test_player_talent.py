"""選手ごとの素質・有望な新入生・型（school_intake_v1 の talent_model・player_types）。"""
from __future__ import annotations

import statistics
import unittest
from pathlib import Path

from game_core.players import Player
from game_core.school_intake import SchoolAwarePlayerAbilityGenerator, SchoolIntakeProfile


ROOT = Path(__file__).resolve().parents[1]
SEED = 20261031


def _player(school_id: str, roster_no: int, position: str = "SS", entry_year: int = 2027) -> Player:
    return Player(
        player_id=f"{school_id}:{entry_year}:{roster_no}", school_id=school_id,
        program_id=f"{school_id}:PRG", display_name=f"選手{roster_no}", name_source="test",
        hometown_prefecture_code="13", academic_year=1, entry_year=entry_year,
        roster_no=roster_no, primary_position=position,
        position_group="pitcher" if position == "P" else "infielder",
        bats="R", throws="R", roster_status="active_core", generation_seed=SEED,
    )


class PlayerTalentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = SchoolAwarePlayerAbilityGenerator(ROOT / "config" / "abilities")
        config = cls.generator.intake_model.config
        cls.common = dict(
            generation_seed=SEED, intake_config_id=config.config_id,
            intake_config_revision=config.revision, intake_config_sha256=config.canonical_sha256,
            program_quality_z=0.0, cohort_quality_z=0.0,
        )

    def _profile(self, school_id: str, z: float, entry_year: int = 2027) -> SchoolIntakeProfile:
        return SchoolIntakeProfile(
            school_id=school_id, entry_year=entry_year, intake_quality_z=z, **self.common,
        )

    def _snapshot(self, school_id, roster_no, z, *, position="SS", cohort=(1, 2, 3, 4, 5, 6, 7)):
        player = _player(school_id, roster_no, position)
        return self.generator._adjust_snapshot(
            base=self.generator.base_generator.generate(player, 2027, SEED),
            player=player, profile=self._profile(school_id, z), cohort=cohort,
        )

    def test_prospect_count_depends_on_school_not_on_cohort_size(self):
        def mean_count(z):
            return statistics.mean(
                self.generator.prospect_count(self._profile(f"FAKE-P{i}", z), SEED)
                for i in range(600)
            )
        strong, middle, weak = mean_count(2.5), mean_count(0.0), mean_count(-1.5)
        # 強豪校は学年に数人、中位校は数年に1人、弱小校はまれ
        self.assertGreater(strong, 2.0)
        self.assertTrue(0.15 < middle < 0.6, middle)
        self.assertLess(weak, 0.1)
        # 人数は学校・年度で決まる（新入生が多くても有望な新入生は増えない）
        for i in range(50):
            profile = self._profile(f"FAKE-C{i}", 1.5)
            small = self.generator.prospects(profile, range(1, 6), SEED)
            large = self.generator.prospects(profile, range(1, 21), SEED)
            self.assertEqual(min(5, len(large)), len(small))

    def test_existing_player_does_not_change_when_cohort_grows(self):
        """選手ごとの乱数は入学年度・学校・部員番号で決まる（部員が増えても変わらない）。"""
        school = "FAKE-STABLE"
        profile = self._profile(school, 0.0)
        small, large = (1, 2, 3, 4, 5), (1, 2, 3, 4, 5, 6, 7, 8, 9)
        for roster_no in small:
            chosen_small = roster_no in self.generator.prospects(profile, small, SEED)
            chosen_large = roster_no in self.generator.prospects(profile, large, SEED)
            if chosen_small != chosen_large:
                continue
            self.assertEqual(
                self._snapshot(school, roster_no, 0.0, cohort=small),
                self._snapshot(school, roster_no, 0.0, cohort=large),
            )

    def test_strong_school_has_weak_and_one_sided_players(self):
        """強豪校でも素質に選手ごとの差があり、型で長所と短所が出る。"""
        snapshots = [
            self._snapshot(f"FAKE-S{i}", roster_no, 2.0)
            for i in range(40) for roster_no in range(1, 8)
        ]
        contact = [s.contact for s in snapshots]
        self.assertTrue(any(value < 45 for value in contact))
        self.assertLess(sum(value >= 80 for value in contact) / len(contact), 0.35)
        by_type = {}
        for snapshot in snapshots:
            by_type.setdefault(snapshot.batter_type, []).append(snapshot)
        speed = by_type["speed"]
        sluggers = by_type["slugger"]
        # 非力な俊足型・守備はうまいが打撃は弱い選手がいる
        self.assertGreater(
            statistics.mean(s.speed - s.power for s in speed),
            statistics.mean(s.speed - s.power for s in sluggers) + 15,
        )
        self.assertTrue(any(s.fielding - s.contact >= 15 for s in by_type["defense"]))
        # 弱い学校より平均は高い
        weak = [self._snapshot(f"FAKE-W{i}", roster_no, -1.5) for i in range(40) for roster_no in range(1, 8)]
        self.assertGreater(statistics.mean(contact), statistics.mean(s.contact for s in weak) + 5)

    def test_pitcher_types_split_velocity_and_control(self):
        pitchers = [
            self._snapshot(f"FAKE-PT{i}", roster_no, 0.5, position="P")
            for i in range(80) for roster_no in range(1, 8)
        ]
        by_type = {}
        for snapshot in pitchers:
            by_type.setdefault(snapshot.pitcher_type, []).append(snapshot)
        power, control = by_type["power"], by_type["control"]
        # 速球はあるが制球が悪い投手と、制球のよい投手
        self.assertGreater(
            statistics.mean(s.velocity_kmh for s in power),
            statistics.mean(s.velocity_kmh for s in control) + 4,
        )
        self.assertGreater(
            statistics.mean(s.control for s in control),
            statistics.mean(s.control for s in power) + 12,
        )
        # 入学時（1年の4月）の球速は 120km/h 前後で、145km/h 以上はほとんどいない
        velocity = [s.velocity_kmh for s in pitchers]
        self.assertTrue(112 < statistics.mean(velocity) < 125)
        self.assertLess(sum(v >= 145 for v in velocity), 2)


if __name__ == "__main__":
    unittest.main()
