"""秋季地区大会の結果から選抜の出場校を選ぶ（game_definition.md §8）。"""
from __future__ import annotations

import unittest

from phase2_engine.senbatsu_selection import (
    select_invitational,
    selection_region_ids,
)


def _rule(scope, region, base, bonus=0):
    return {
        "selection_scope": scope, "region_id": region,
        "base_quota": str(base), "bonus_quota": str(bonus),
        "total_quota": str(base + bonus),
    }


RULES = [
    _rule("A地区", "REG01", 2, 1),
    _rule("関東", "REG03", 2),
    _rule("東京", "REG04", 1),
    _rule("関東・東京", "", 1),
    _rule("21世紀枠", "", 2),
]
RANKINGS = {
    "REG01": ["a1", "a2", "a3"],
    "REG03": ["k1", "k2", "k3", "k4"],
    "REG04": ["t1", "t2", "t3"],
}


class SenbatsuSelectionTests(unittest.TestCase):
    def test_regions_used(self):
        self.assertEqual(
            ["REG01", "REG03", "REG04"], selection_region_ids(RULES)
        )

    def test_top_of_each_region_and_one_comparison_slot(self):
        selected = select_invitational(
            RULES, RANKINGS, jingu_region="REG03", rng_seed=1
        )
        # 神宮枠はデータの地区（A地区）ではなく、神宮大会の優勝校の地区（関東）
        self.assertEqual(["a1", "a2", "k1", "k2", "k3", "t1"], selected[:6])
        self.assertEqual(7, len(selected))
        self.assertIn(selected[6], {"k4", "t2"})

    def test_jingu_slot_goes_to_champion_region(self):
        selected = select_invitational(
            RULES, RANKINGS, jingu_region="REG01", rng_seed=1
        )
        self.assertEqual(["a1", "a2", "a3", "k1", "k2", "t1"], selected[:6])
        self.assertIn(selected[6], {"k3", "t2"})

    def test_century_slots_from_public_top8_recommendations(self):
        rules = RULES + [{
            "selection_scope": "21世紀枠", "region_id": "",
            "base_quota": "2", "bonus_quota": "0", "total_quota": "2",
            "selection_method": "21st_century_selection",
        }]
        prefectural = {
            # 一般の選考で選ばれた a1 と、私立の p1 は候補にならない
            "REG01": [["a1", "p1", "c1"]],
            "REG03": [["k1", "c2"], ["c3"]],
            "REG04": [["t1", "c4"]],
        }
        public = {"a1", "c1", "c2", "c3", "c4", "k1", "t1"}
        selected = select_invitational(
            rules, RANKINGS, jingu_region="REG03",
            prefectural_rankings=prefectural, public_school_ids=public,
            rng_seed=3,
        )
        century = selected[-2:]
        self.assertEqual(9, len(selected))
        self.assertTrue(set(century) <= {"c1", "c2", "c3", "c4"})
        # 推薦は1地区1校まで。関東と東京は1つの地区なので、関東・東京から
        # 2校は選ばれない（推薦校は A地区と関東・東京の2校だけ）
        self.assertIn("c1", century)
        self.assertEqual(1, len(set(century) & {"c2", "c3", "c4"}))

    def test_school_outside_top8_is_not_a_candidate(self):
        rules = RULES + [{
            "selection_scope": "21世紀枠", "region_id": "",
            "base_quota": "2", "bonus_quota": "0",
            "selection_method": "21st_century_selection",
        }]
        ranking = [f"x{i}" for i in range(9)]
        selected = select_invitational(
            rules, RANKINGS, jingu_region="REG03",
            prefectural_rankings={"REG01": [ranking]},
            public_school_ids={"x8"},
            rng_seed=3,
        )
        self.assertNotIn("x8", selected)

    def test_same_seed_gives_same_selection(self):
        self.assertEqual(
            select_invitational(
                RULES, RANKINGS, jingu_region="REG01", rng_seed=7
            ),
            select_invitational(
                RULES, RANKINGS, jingu_region="REG01", rng_seed=7
            ),
        )

    def test_short_ranking_is_an_error(self):
        with self.assertRaises(ValueError):
            select_invitational(
                RULES, {**RANKINGS, "REG01": ["a1"]},
                jingu_region="REG03", rng_seed=1,
            )


if __name__ == "__main__":
    unittest.main()
