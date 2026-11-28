"""選抜の記念大会（回数の下一桁が0か5の年は36校。ADR-046）。学校はすべて架空。"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import unittest

from phase2_engine import commemorative
from phase2_engine.national_day_plan import match_dates, plan_for
from phase2_engine.season_catalog import season_competitions
from phase2_engine.senbatsu_selection import commemorative_picks, select_invitational
from phase2_engine.tournament_runtime import MainTournamentRuntimeState

ROOT = Path(__file__).resolve().parents[1]
CONFIG = commemorative.load_config(ROOT / "config")
RULE = CONFIG["invitational"]
# ひな形は第98回（2026年3月）。ゲームの2025年度の大会なので、年度 Y の選抜は Y-2025 年ずらす
TEMPLATE = {"competition_id": "C1", "reference_year": "2026", "season_segment": "spring",
            "competition_type": "national_invitational", "competition_name": "第98回選抜高等学校野球大会"}


def _rule(scope, region, base, bonus=0, method="committee_selection"):
    return {"selection_scope": scope, "region_id": region, "base_quota": str(base),
            "bonus_quota": str(bonus), "selection_method": method}


# 実際の地区の枠（selection_rules.csv と同じ数。21世紀枠は2）
RULES = [
    _rule("北海道", "REG01", 1), _rule("東北", "REG02", 3), _rule("関東", "REG03", 4),
    _rule("東京", "REG04", 1), _rule("関東・東京", "", 1), _rule("北信越", "REG05", 2),
    _rule("東海", "REG06", 3), _rule("近畿", "REG07", 6), _rule("中国", "REG08", 2),
    _rule("四国", "REG09", 2), _rule("九州", "REG10", 4, 1),
    _rule("21世紀枠", "", 2, method="21st_century_selection"),
]
REGIONS = [f"REG{i:02d}" for i in range(1, 11)]
RANKINGS = {region: [f"{region}-{n}" for n in range(1, 11)] for region in REGIONS}
CENTURY = {
    "prefecture_candidate_ranks": [3, 8], "public_weight_multiplier": 1.0, "strength_exponent": 0.0,
    "region_performance_weights": {"champion": 1, "runner_up": 1, "best4": 1, "best8": 1, "best16": 1},
    "appearance_gap_weights": [[0, 1.0]], "never_appeared_weight": 1.0,
}
PREFECTURAL = {region: [[f"{region}-P{n}" for n in range(1, 9)]] for region in REGIONS}


class EditionTests(unittest.TestCase):
    def test_editions_100_and_105_are_commemorative(self):
        found = {98 + offset: bool(commemorative.invitational_extra(CONFIG, TEMPLATE, offset))
                 for offset in range(2, 8)}
        self.assertEqual({100: True, 101: False, 102: False, 103: False, 104: False, 105: True}, found)

    def test_name_has_commemoration_only_in_that_year(self):
        calendars = {"C1": {"start_date": "2026-03-19", "end_date": "2026-03-31"}}
        names = {year: season_competitions([TEMPLATE], calendars, year, CONFIG)["C1"].display_name
                 for year in (2027, 2028)}
        self.assertEqual({2027: "第100回記念選抜高等学校野球大会", 2028: "第101回選抜高等学校野球大会"}, names)


class ExtraPickTests(unittest.TestCase):
    def test_next_schools_by_finish_then_strength_one_per_unit(self):
        rule = {"extra_general_quota": 2, "max_extra_per_unit": 1,
                "units": [["R1"], ["R2", "R3"], ["R4"]]}
        rankings = {"R1": ["a1", "a2", "a3"], "R2": ["b1", "b2", "b3"], "R3": ["c1", "c2"],
                    "R4": ["d1", "d2", "d3", "d4", "d5"]}
        # 通常の枠：R1 は1校（次点 a2 は準優勝）、R2・R3 は2校ずつ（次点 b3・c... は優勝〜ベスト4）、R4 は4校
        chosen = {"a1", "b1", "b2", "c1", "d1", "d2", "d3", "d4"}
        strength = {"a2": 50.0, "b3": 70.0, "c2": 60.0, "d5": 90.0}.get
        picks = commemorative_picks(rule, rankings, chosen, strength, rng_seed=1)
        # a2 と c2 はどちらも準優勝（R2・R3 は良い方の c2。b3 はベスト4）なので強い c2 が先。R4 の d5 はベスト8で入らない
        self.assertEqual(["c2", "a2"], picks)

    def test_four_extra_schools_go_to_four_different_units(self):
        basis: dict[str, str] = {}
        selected = select_invitational(
            RULES, RANKINGS, jingu_region="REG07", prefectural_rankings=PREFECTURAL,
            century_config=CENTURY, rng_seed=3, basis=basis, commemorative=RULE)
        self.assertEqual(36, len(selected))
        self.assertEqual(36, len(set(selected)))
        counts = Counter(basis.values())
        self.assertEqual((4, 2, 1), (counts["commemorative"], counts["century"], counts["jingu"]))
        unit_of = {region: i for i, unit in enumerate(RULE["units"]) for region in unit}
        units = [unit_of[sid.split("-")[0]] for sid, why in basis.items() if why == "commemorative"]
        self.assertEqual(4, len(set(units)))

    def test_normal_year_is_32(self):
        selected = select_invitational(
            RULES, RANKINGS, jingu_region="REG07", prefectural_rankings=PREFECTURAL,
            century_config=CENTURY, rng_seed=3)
        self.assertEqual(32, len(selected))


class BracketTests(unittest.TestCase):
    def test_36_schools_play_four_first_round_games(self):
        entrants = [f"S{i:02d}" for i in range(36)]
        main = MainTournamentRuntimeState.create(
            competition_id="C1", reference_year=2028, generation_seed=1, stage_id="MAIN",
            entrants=entrants)
        games = [sum(not main.matches[m].is_bye for m in main.match_ids_by_round[r])
                 for r in range(1, main.total_rounds + 1)]
        self.assertEqual([4, 16, 8, 4, 2, 1], games)
        # 記念大会の日程（11日）に35試合がすべて入る
        plan = plan_for(ROOT / "data", "national_invitational", 36)
        days = [f"2028-03-{day:02d}" for day in (18, 19, 20, 21, 22, 23, 24, 25, 26, 28, 30)]
        self.assertEqual(35, len(match_dates(plan, main, days)))
        self.assertIsNotNone(plan.get("separate"))


if __name__ == "__main__":
    unittest.main()
