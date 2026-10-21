"""秋季地区大会の結果から選抜の出場校を選ぶ（game_definition.md §8）。"""
from __future__ import annotations

import unittest

from phase2_engine.senbatsu_selection import (
    select_invitational,
    selection_region_ids,
)


RULES = [
    {"selection_scope": "A地区", "region_id": "REG01", "total_quota": "2"},
    {"selection_scope": "関東", "region_id": "REG03", "total_quota": "2"},
    {"selection_scope": "東京", "region_id": "REG04", "total_quota": "1"},
    {"selection_scope": "関東・東京", "region_id": "", "total_quota": "1"},
    {"selection_scope": "21世紀枠", "region_id": "", "total_quota": "2"},
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
        selected = select_invitational(RULES, RANKINGS, rng_seed=1)
        self.assertEqual(["a1", "a2", "k1", "k2", "t1"], selected[:5])
        # 関東の次（k3）と東京の次（t2）から1校。21世紀枠はまだ選ばない
        self.assertEqual(6, len(selected))
        self.assertIn(selected[5], {"k3", "t2"})

    def test_same_seed_gives_same_selection(self):
        self.assertEqual(
            select_invitational(RULES, RANKINGS, rng_seed=7),
            select_invitational(RULES, RANKINGS, rng_seed=7),
        )

    def test_short_ranking_is_an_error(self):
        with self.assertRaises(ValueError):
            select_invitational(
                RULES, {**RANKINGS, "REG01": ["a1"]}, rng_seed=1
            )


if __name__ == "__main__":
    unittest.main()
