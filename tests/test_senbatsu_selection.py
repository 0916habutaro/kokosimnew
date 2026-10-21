"""秋季地区大会の結果から選抜の出場校を選ぶ（game_definition.md §8）。"""
from __future__ import annotations

import unittest

from pathlib import Path

from phase2_engine.senbatsu_selection import (
    load_selection_config,
    select_invitational,
    selection_region_ids,
)

ROOT = Path(__file__).resolve().parents[1]


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
CENTURY = load_selection_config(ROOT / "config")["century"]
CENTURY_RULES = RULES[:-1] + [{
    "selection_scope": "21世紀枠", "region_id": "",
    "base_quota": "2", "bonus_quota": "0",
    "selection_method": "21st_century_selection",
}]
PREFECTURAL = {
    "REG01": [["a1", "p1", "c1"]],
    "REG03": [["k1", "c2"], ["c3"]],
    "REG04": [["t1", "c4"]],
}
PUBLIC = {"a1", "c1", "c2", "c3", "c4", "k1", "t1"}
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

    def test_century_flow_prefecture_area_then_two(self):
        selected = select_invitational(
            CENTURY_RULES, RANKINGS, jingu_region="REG03",
            prefectural_rankings=PREFECTURAL, public_school_ids=PUBLIC,
            century_config=CENTURY, rng_seed=3,
        )
        century = selected[-2:]
        self.assertEqual(9, len(selected))
        # 一般の選考で選ばれた a1・k1・t1 は候補にならない。私立（p1）も候補。
        # 推薦は地区ごとに1校（関東と東京は1つの地区）なので、A地区から1校、
        # 関東・東京から1校
        self.assertEqual(1, len(set(century) & {"c1", "p1"}))
        self.assertEqual(1, len(set(century) & {"c2", "c3", "c4"}))

    def test_school_outside_best16_is_not_a_candidate(self):
        ranking = [f"x{i}" for i in range(17)]
        selected = select_invitational(
            CENTURY_RULES, RANKINGS, jingu_region="REG03",
            prefectural_rankings={"REG01": [ranking]},
            public_school_ids={"x16"}, century_config=CENTURY, rng_seed=3,
        )
        self.assertNotIn("x16", selected)
        self.assertEqual(8, len(selected))

    def test_public_and_weak_schools_are_drawn_more_often(self):
        # 都道府県推薦のくじ：公立は私立の3倍、強さが低いほど重い
        counts = {"public": 0, "weak": 0}
        for seed in range(400):
            picked = select_invitational(
                CENTURY_RULES, RANKINGS, jingu_region="REG03",
                prefectural_rankings={"REG01": [["pub", "pri"]]},
                public_school_ids={"pub"}, century_config=CENTURY,
                rng_seed=seed,
            )[-1]
            counts["public"] += picked == "pub"
            picked = select_invitational(
                CENTURY_RULES, RANKINGS, jingu_region="REG03",
                prefectural_rankings={"REG01": [["strong", "weak"]]},
                strength_of={"strong": 60.0, "weak": 40.0}.get,
                century_config=CENTURY, rng_seed=seed,
            )[-1]
            counts["weak"] += picked == "weak"
        self.assertAlmostEqual(0.75, counts["public"] / 400, delta=0.07)
        # (60/40)^4 ≒ 5.1倍
        self.assertAlmostEqual(5.06 / 6.06, counts["weak"] / 400, delta=0.07)

    def test_better_autumn_result_is_drawn_more_often_in_area(self):
        # 地区推薦のくじ：秋の成績が良いほど重い（優勝5：ベスト16 1）
        wins = 0
        for seed in range(400):
            picked = select_invitational(
                CENTURY_RULES, RANKINGS, jingu_region="REG03",
                prefectural_rankings={"REG01": [
                    ["champ"], [f"y{i}" for i in range(9)],
                ]},
                public_school_ids={"champ", "y8"},
                century_config={**CENTURY, "public_weight_multiplier": 1e9},
                rng_seed=seed,
            )[-1]
            wins += picked == "champ"
        self.assertAlmostEqual(5 / 6, wins / 400, delta=0.07)

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
