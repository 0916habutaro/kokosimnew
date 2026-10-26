"""選手の成長（game_core/player_growth.py）。"""
from __future__ import annotations

from collections import Counter
import random
import unittest

from game_core.player_growth import POTENTIAL_SCALE, SCALARS, TYPES, PlayerGrowth


CONTACT = SCALARS.index("contact")
VELOCITY = SCALARS.index("velocity_kmh")
MONTHS = (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3)


def _values(level: int, *, pitcher: bool = False) -> bytearray:
    values = [level] * 11 + [0, 0]
    values += [140, level, level, level, level, level, level] if pitcher else [0] * 7
    values += [80] * 9
    if pitcher:
        values += [0, level, level, 100]
    return bytearray(values)


class PlayerGrowthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.growth = PlayerGrowth()

    def _year(self, values, *, grade, type_index=1, potential=POTENTIAL_SCALE,
              games=0, position="SS", seed=1):
        rng = random.Random(seed)
        for month in MONTHS:
            self.growth.grow(
                values, position=position, grade=grade, type_index=type_index,
                potential=potential, games=games, month=month, rng=rng,
            )
        return values

    def _mean_gain(self, level=50, runs=300, **kwargs):
        total = 0
        for seed in range(runs):
            values = self._year(_values(level), seed=seed, **kwargs)
            total += values[CONTACT] - level
        return total / runs

    def test_three_years_of_a_normal_player_add_about_the_configured_total(self):
        total = 0.0
        runs = 200
        for seed in range(runs):
            values = _values(50)
            for grade in (1, 2, 3):
                self._year(values, grade=grade, seed=seed * 3 + grade)
            total += values[CONTACT] - 50
        # 3年間で15（上限に近づくほど小さくなるので少し下回る）
        self.assertTrue(11.0 < total / runs < 15.5, total / runs)

    def test_types_differ_by_grade(self):
        index = {name: i for i, name in enumerate(TYPES)}
        early1 = self._mean_gain(grade=1, type_index=index["early"])
        late1 = self._mean_gain(grade=1, type_index=index["late"])
        early3 = self._mean_gain(grade=3, type_index=index["early"])
        late3 = self._mean_gain(grade=3, type_index=index["late"])
        self.assertGreater(early1, late1 * 2)
        self.assertGreater(late3, early3 * 2)

    def test_potential_and_headroom(self):
        normal = self._mean_gain(grade=2)
        high = self._mean_gain(grade=2, potential=2 * POTENTIAL_SCALE)
        self.assertGreater(high, normal * 1.7)
        # 上限に近いほど伸びにくい
        self.assertLess(self._mean_gain(level=90, grade=2), normal * 0.4)
        self.assertGreater(self._mean_gain(level=30, grade=2), normal)

    def test_games_add_a_little(self):
        bench = self._mean_gain(grade=2)
        regular = self._mean_gain(grade=2, games=2)
        self.assertGreater(regular, bench + 1.5)

    def test_pitchers_grow_velocity_and_pitches_within_limits(self):
        values = _values(60, pitcher=True)
        for grade in (1, 2, 3):
            self._year(values, grade=grade, position="P", potential=2 * POTENTIAL_SCALE, games=5)
        self.assertGreater(values[VELOCITY], 140)
        self.assertLessEqual(values[VELOCITY], 165)
        self.assertGreater(values[-3], 60)  # 変化球の質
        self.assertEqual(100, values[-1])  # 投げる割合は変わらない
        self.assertTrue(all(v <= 165 for v in values))

    def test_draw_types_and_potential(self):
        rng = random.Random(3)
        draws = [self.growth.draw(rng, 0.0) for _ in range(4000)]
        types = Counter(t for t, _ in draws)
        self.assertTrue(800 < types[0] < 1200)
        self.assertTrue(1800 < types[1] < 2200)
        mean = sum(p for _, p in draws) / len(draws) / POTENTIAL_SCALE
        self.assertTrue(0.98 < mean < 1.1, mean)
        # まれに大化け（潜在能力が大きい）
        self.assertTrue(any(p > 1.7 * POTENTIAL_SCALE for _, p in draws))
        strong = [self.growth.draw(rng, 2.5)[1] for _ in range(4000)]
        gap = (sum(strong) / len(strong) - sum(p for _, p in draws) / len(draws)) / POTENTIAL_SCALE
        # 評判の高い学校は少しだけ大きい
        self.assertTrue(0.05 < gap < 0.2, gap)


if __name__ == "__main__":
    unittest.main()
