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
        # 甲子園に出たことがなく、地方大会でも県の平均より弱い学校
        initial = self.reputation.config["summer_local"]["elo"]["initial"]
        never = [
            sid for sid in self.reputation.school_ids
            if sid not in ever and self.reputation.local_ratings.get(sid, initial) < initial
            and not any(n <= 16 for n in self.reputation.local_finishes.get(sid, {}).values())
        ]
        self.assertGreater(len(never), 500)
        z = lambda sid: self.reputation.program_z(sid, 7)  # noqa: E731
        self.assertGreater(min(z(sid) for sid in recent), max(z(sid) for sid in never))
        # 弱い学校は、昔に1回だけ出た学校と並ぶことはあっても B より上にならない
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
        # 点の少ない学校（地方大会の試合がない学校など）は乱数で順位が入れ替わる
        never = sorted(self.reputation.school_ids, key=lambda sid: self.reputation.base[sid])[:300]
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


class SummerLocalTests(unittest.TestCase):
    """夏の地方大会の結果（県の中の強さと勝ち上がり）。"""

    @classmethod
    def setUpClass(cls):
        cls.reputation = reputation_for(str(ROOT))
        with (ROOT / "data" / "master" / "schools.csv").open(encoding="utf-8-sig") as handle:
            cls.prefecture = {
                row["school_id"]: row["prefecture_code"] for row in csv.DictReader(handle)
            }

    def test_best8_regulars_rank_near_the_top_of_their_prefecture(self):
        finishes = self.reputation.local_finishes
        by_prefecture: dict[str, list[str]] = {}
        for school_id in self.reputation.school_ids:
            by_prefecture.setdefault(self.prefecture[school_id], []).append(school_id)
        regulars = inside = 0
        for schools in by_prefecture.values():
            top = sorted(schools, key=lambda sid: -self.reputation.score(sid, 7))[:10]
            for school_id in schools:
                if sum(1 for n in finishes.get(school_id, {}).values() if n <= 8) >= 3:
                    regulars += 1
                    inside += school_id in top
        self.assertGreater(regulars, 200)
        self.assertGreater(inside / regulars, 0.85)

    def test_champions_are_rated_above_the_start(self):
        initial = self.reputation.config["summer_local"]["elo"]["initial"]
        champions = [
            sid for sid, years in self.reputation.local_finishes.items() if years.get(2025) == 1
        ]
        self.assertGreater(len(champions), 40)
        self.assertTrue(all(self.reputation.local_ratings[sid] > initial for sid in champions))

    def test_union_members_and_schools_without_games(self):
        ratings = self.reputation.local_ratings
        config = self.reputation.config["summer_local"]
        self.assertGreater(len(self.reputation.union_rated), 100)
        # 試合のない学校は県の中の下位の値で、県の平均より下
        for school_id in self.reputation.no_data:
            code = self.prefecture[school_id]
            values = sorted(
                v for sid, v in ratings.items()
                if self.prefecture[sid] == code and sid not in self.reputation.no_data
            )
            self.assertLess(ratings[school_id], values[len(values) // 2])
        self.assertLess(config["no_data_rating_quantile"], 0.5)
        # 連合チームで出た学校は、県の中のレーティングで下半分が多い
        below = [
            sid for sid in self.reputation.union_rated
            if ratings[sid] < config["elo"]["initial"]
        ]
        self.assertGreater(len(below) / len(self.reputation.union_rated), 0.8)

    def test_prefecture_offset_follows_koshien_win_rate(self):
        offsets = self.reputation.prefecture_offsets
        self.assertEqual(47, len(offsets))
        self.assertGreater(max(offsets.values()), 0)
        self.assertLess(min(offsets.values()), 0)


if __name__ == "__main__":
    unittest.main()
