"""学校の評判の初期値（初期の勢力図。game_definition.md §8）。"""
from __future__ import annotations

import csv
from pathlib import Path
from statistics import mean, pstdev
import unittest

from game_core.school_intake import SchoolIntakeModel
from game_core.school_reputation import reputation_for


ROOT = Path(__file__).resolve().parents[1]


def _entrants():
    with (ROOT / "historical_data" / "koshien_entrants.csv").open(encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row["school_id"]]


class ReputationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reputation = reputation_for(str(ROOT))

    def test_program_z_has_the_intake_distribution(self):
        values = [
            self.reputation.program_z(school_id, 7) for school_id in self.reputation.school_ids
        ]
        self.assertAlmostEqual(0.0, mean(values), delta=0.01)
        self.assertAlmostEqual(1.0, pstdev(values), delta=0.05)
        # 学校マスターにない学校は評判がない（入部品質は乱数）
        self.assertIsNone(self.reputation.program_z("SCHX0001", 7))

    def test_recent_koshien_schools_rank_above_schools_without_koshien(self):
        recent = {row["school_id"] for row in _entrants() if int(row["year"]) >= 2023}
        with (ROOT / "historical_data" / "koshien_records.csv").open(encoding="utf-8-sig") as handle:
            ever = {row["school_id"] for row in csv.DictReader(handle)}
        ever |= {row["school_id"] for row in _entrants()}
        # 甲子園に出たことがなく、直前の結果（2025年秋など）もない学校
        never = [
            sid for sid in self.reputation.school_ids
            if sid not in ever and sid not in self.reputation.base
        ]
        z = lambda sid: self.reputation.program_z(sid, 7)  # noqa: E731
        self.assertGreater(min(z(sid) for sid in recent), max(z(sid) for sid in never))
        # 乱数だけの学校は、昔に1回だけ出た学校と並ぶことはあっても B より上にならない
        self.assertTrue(all(self.reputation.rank(sid, 7) in ("C", "D", "E") for sid in never))
        top = max(self.reputation.school_ids, key=z)
        self.assertEqual("S", self.reputation.rank(top, 7))

    def test_recent_appearances_weigh_more(self):
        # 同じ点の出場でも、最近の出場ほど点が大きい
        self.assertGreater(self.reputation._decay(2025), self.reputation._decay(2000))
        self.assertAlmostEqual(
            0.5,
            self.reputation._decay(2026 - self.reputation.config["recency_half_life_years"]),
        )

    def test_noise_depends_on_the_seed(self):
        never = [sid for sid in self.reputation.school_ids if sid not in self.reputation.base]
        order = lambda seed: sorted(never, key=lambda sid: self.reputation.score(sid, seed))  # noqa: E731
        self.assertNotEqual(order(1)[:20], order(2)[:20])

    def test_intake_uses_the_reputation(self):
        model = SchoolIntakeModel(ROOT / "config" / "abilities")
        school_id = self.reputation.school_ids[0]
        profile = model.profile(school_id=school_id, entry_year=2026, base_seed=7)
        self.assertAlmostEqual(
            self.reputation.program_z(school_id, 7), profile.program_quality_z, places=5,
        )
        # 入学年が違っても学校成分は同じ（年度ごとの当たり外れは cohort）
        other = model.profile(school_id=school_id, entry_year=2024, base_seed=7)
        self.assertEqual(profile.program_quality_z, other.program_quality_z)
        self.assertNotEqual(profile.cohort_quality_z, other.cohort_quality_z)


if __name__ == "__main__":
    unittest.main()
