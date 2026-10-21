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
