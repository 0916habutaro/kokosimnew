"""連合チームの画面・記録：名前「A・B」、構成校それぞれの成績、構成校の試合一覧。架空の学校で確かめる。"""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from game_core.joint_teams import JointTeam, UnionPlan
from phase2_engine.screen.data import GameScreenData

NAMES = {"SCH-A": "甲", "SCH-B": "乙", "SCH-C": "丙"}


def _season():
    competitions = {
        "PREF": {"competition_type": "autumn_prefectural", "competition_level": "prefectural"},
        "REGION": {"competition_type": "autumn_regional", "competition_level": "regional"},
        "SUMMER": {"competition_type": "summer_local_qualifier", "competition_level": "local"},
    }
    return SimpleNamespace(
        repo=SimpleNamespace(competitions=competitions),
        union_plans={"PREF": UnionPlan((JointTeam("SCH-A", ("SCH-A", "SCH-B")),), ("SCH-C",))},
        competitions={"PREF": None, "REGION": None, "SUMMER": None},
    )


def _screen(season):
    screen = SimpleNamespace(
        names=lambda sid, day="": NAMES.get(sid, sid),
        _season_of=lambda year: season,
        _current_year=lambda: 2026,
        _years=lambda: [2026],
        state=SimpleNamespace(seasons={2026: season}),
    )
    for name in ("union", "union_name", "_add_union_results", "_union_leads"):
        setattr(screen, name, getattr(GameScreenData, name).__get__(screen))
    return screen


class UnionScreenTests(unittest.TestCase):
    def test_union_name_in_its_competition_and_the_next_ones(self):
        screen = _screen(_season())
        self.assertEqual("甲・乙", screen.union_name("SCH-A", "PREF", 2026))
        # 勝ち進んだ地区大会も同じ連合の名前
        self.assertEqual("甲・乙", screen.union_name("SCH-A", "REGION", 2026))
        self.assertEqual("", screen.union_name("SCH-A", "SUMMER", 2026))
        self.assertEqual("", screen.union_name("SCH-B", "PREF", 2026))

    def test_union_result_is_given_to_each_member_school(self):
        screen = _screen(_season())
        row = {"competition_id": "PREF", "wins": 2, "losses": 1, "finish": "ベスト8",
               "score": 1012, "first_date": "2026-09-01"}
        results = {"SCH-A": [dict(row)], "SCH-C": []}
        screen._add_union_results(2026, results)
        lead, partner = results["SCH-A"][0], results["SCH-B"][0]
        self.assertEqual(["乙"], [u["name"] for u in lead["union"]])
        self.assertEqual(["甲"], [u["name"] for u in partner["union"]])
        self.assertEqual((2, 1, "ベスト8"), (partner["wins"], partner["losses"], partner["finish"]))
        # 記録の一覧で重ねて数えないように、代表校がわかる
        self.assertEqual("SCH-A", partner["union_lead"])
        self.assertEqual([], results["SCH-C"])

    def test_partner_school_sees_the_union_games(self):
        screen = _screen(_season())
        self.assertEqual({"PREF": "SCH-A", "REGION": "SCH-A"}, screen._union_leads("SCH-B", 2026))
        self.assertEqual({}, screen._union_leads("SCH-A", 2026))
        self.assertEqual({}, screen._union_leads("SCH-C", 2026))


if __name__ == "__main__":
    unittest.main()
