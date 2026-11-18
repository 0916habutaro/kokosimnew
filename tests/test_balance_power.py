"""バランスの物差しの通しの指標（架空の学校・監督の記録で確かめる。試合は進めない）。"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest

from phase2_engine.balance_power import (
    PowerTally, UpsetCounter, dynasty_metrics, format_power, merge_seeds, spread_by_prefecture,
)
from phase2_engine.balance_report import POWER_KEY, average, format_report

KINDS = {"LOC": "summer_local_qualifier", "KOS": "national_championship", "SEN": "national_invitational"}


class FakeRepo:
    """学校IDの頭2文字を都道府県にする架空の学校。X で始まる学校は私立。"""

    def team(self, school_id):
        return SimpleNamespace(prefecture_code=school_id[:2])

    def ownership_type(self, school_id):
        return "private" if school_id.endswith("X") else "prefectural"


class FakeReputation:
    rank_labels = [["S", 0.75], ["A", 0.5], ["B", 0.25], ["C", 0.0]]

    def __init__(self, values):
        self.values = values


def match(winner, loser, pitches):
    """pitches：学校 → [(選手, 球数), …]。先頭が先発。"""
    return {
        "winner_id": winner, "loser_id": loser, "team1_school_id": winner, "team2_school_id": loser,
        "team_participation": [dict(school_id=s, starting_pitcher_id=rows[0][0]) for s, rows in pitches.items()],
        "pitcher_stats": [dict(player_id=p, school_id=s, pitches=n) for s, rows in pitches.items() for p, n in rows],
    }


class DynastyTests(unittest.TestCase):
    def test_streaks_counts_and_prefectures(self):
        by_year = {2026: {"11A", "12A"}, 2027: {"11A", "12B"}, 2028: {"11A", "12C"}, 2029: {"11B", "12A"}}
        d = dynasty_metrics(by_year, lambda school: school[:2])
        self.assertEqual(d["streaks"], {"2年": 0, "3〜4年": 1, "5〜9年": 0, "10年以上": 0})
        self.assertEqual(d["longest_streak"], 3)
        self.assertEqual(d["appearances"], {"1回": 3, "2〜3回": 2, "4〜6回": 0, "7回以上": 0})
        self.assertEqual(d["prefecture_school_counts"], {2: 1, 3: 1})
        self.assertEqual(d["dominant_prefectures"], 1)      # 11 は1校が4回のうち3回
        self.assertEqual(d["by_prefecture"]["12"], {"schools": 3, "top": 2})

    def test_two_slot_prefectures_are_left_out_of_the_distribution(self):
        d = dynasty_metrics({2026: {"01A", "01B", "11A"}}, lambda school: school[:2])
        self.assertEqual(d["prefecture_school_counts"], {1: 1})
        self.assertEqual(d["by_prefecture"]["01"]["schools"], 2)

    def test_prefecture_spread(self):
        s = spread_by_prefecture({"11": [3, 1], "12": [1, 3], "13": [0, 0]}, top=1)
        self.assertEqual((s["prefectures"], s["stdev"]), (2, 0.25))
        self.assertEqual((s["top"], s["bottom"]), ([("11", 0.75)], [("12", 0.25)]))
        merged = merge_seeds([{"prefecture_strength": s}, {"prefecture_strength": s}])
        self.assertEqual(merged["prefecture_strength"]["records"]["11"], [6, 2])


class UpsetTests(unittest.TestCase):
    def test_upper_rank_win_rate_by_gap(self):
        counter = UpsetCounter("SABC")
        counter.add("県大会", "S", "A")
        counter.add("県大会", "A", "S")
        counter.add("県大会", "S", "C")
        counter.add("県大会", "B", "B")
        counter.add("県大会", "", "B")       # ランクのない学校は数えない
        rows = counter.summary()["県大会"]
        self.assertEqual(rows["1"], {"games": 2, "upper_win_rate": 0.5})
        self.assertEqual(rows["3"], {"games": 1, "upper_win_rate": 1.0})
        self.assertEqual(rows["0"], {"games": 1})


class PowerTallyTests(unittest.TestCase):
    def tally(self):
        tally = PowerTally(FakeRepo(), KINDS.get, pitch_limit=(500, 7))
        tally.set_reputation(2026, FakeReputation({"11A": 2.0, "12A": 1.0, "13A": 0.0, "14X": -1.0}))
        return tally

    def test_koshien_records_champion_and_coach_wins(self):
        tally = self.tally()
        coach = SimpleNamespace(coach_id="C1")
        tally.add_match("KOS", match("11A", "12A", {"11A": [("a1", 150)], "12A": [("b1", 90)]}),
                        date(2026, 8, 20), 1, lambda school: coach)
        tally.add_match("KOS", match("11A", "13A", {"11A": [("a2", 30), ("a1", 100)], "13A": [("c1", 110)]}),
                        date(2026, 8, 21), 0, lambda school: coach)
        out = tally.summary()
        self.assertEqual(out["upsets"]["甲子園"]["1"], {"games": 1, "upper_win_rate": 1.0})
        self.assertEqual(out["prefecture_strength"]["records"]["11"], [2, 0])
        self.assertEqual(out["champions"]["夏"]["list"], {"2026": ["11A", "S"]})
        self.assertEqual(tally.coach_wins["C1"], 2)
        self.assertEqual(out["dynasty"]["schools"], 3)
        # 決勝：前の日に150球のエースが救援で連投（先発ではない）
        ace = out["ace"]["甲子園の準決勝・決勝"]
        self.assertEqual((ace["team_games"], ace["pitched"], ace["started"], ace["back_to_back"]), (1, 1.0, 0.0, 1))
        self.assertEqual(out["starter_pitches"]["甲子園"]["140〜"], 0.25)
        self.assertEqual(out["starter_pitches"]["甲子園"]["max"], 150)

    def test_pitch_limit_counts_seven_days(self):
        tally = self.tally()
        for day, pitches in ((10, 200), (13, 200), (16, 100), (25, 150)):
            tally.add_match("LOC", match("11A", "12A", {"11A": [("a1", pitches)], "12A": [("b1", 50)]}),
                            date(2026, 7, day), None)
        self.assertEqual(tally.summary()["pitch_limit"],
                         {"全試合": 1, "全試合（8割以上）": 1, "夏の地方大会": 1, "夏の地方大会（8割以上）": 1})

    def test_coach_tenure_retirement_and_reputation_after_a_great_coach(self):
        tally = self.tally()
        tally.coach_wins["C1"] = 5
        tally.coach_wins_by_year["C1"][2026] = 5   # 勇退（2027年4月）の前の年度までに5勝
        tally.set_reputation(2027, FakeReputation({"11A": 2.0, "12A": 1.0, "13A": 0.0, "14X": -1.0}))
        tally.set_reputation(2028, FakeReputation({"11A": 1.5, "12A": 1.0, "13A": 0.0, "14X": -1.0}))
        coaches = SimpleNamespace(
            first_year=2026, config={"public_ownership_types": ["prefectural"]},
            coaches={"C1": SimpleNamespace(birth_year=1962, appointment_year=2007, retired_on="2027-04-01"),
                     "C2": SimpleNamespace(birth_year=1990, appointment_year=2022, retired_on=None)},
            events=[SimpleNamespace(date="2007-04-01", kind="initial", coach_id="C1", from_school_id=None,
                                    completed_tenure_years=None),
                    SimpleNamespace(date="2027-04-01", kind="retirement", coach_id="C1", from_school_id="11A",
                                    completed_tenure_years=20)])
        out = tally.summary(coaches)["coaches"]
        self.assertEqual(out["ended_tenure"]["公立"]["11〜20年"], 1)
        self.assertEqual(out["retirement_age"]["全体"]["65〜69歳"], 1)
        self.assertEqual(out["active_tenure"]["7〜10年"], 1)   # 2022年就任を2028年に数えると7年目
        self.assertEqual(out["koshien_wins"], {"3勝以上": 1, "5勝以上": 1, "10勝以上": 0})
        after = out["after_great_coach"]["5勝以上・勇退"]
        self.assertEqual(after["coaches"], 1)
        self.assertEqual(after["1年後"]["change_z"], -0.5)
        self.assertEqual(out["after_great_coach"]["10勝以上・勇退"], {"coaches": 0})

    def test_reputation_where_a_great_coach_arrives_counts_only_wins_before_the_move(self):
        tally = self.tally()
        # C1 は2026年度に甲子園で5勝してから2027年に12A へ異動。C2 は異動のあとに5勝（名将の着任に数えない）
        tally.coach_wins.update({"C1": 5, "C2": 5})
        tally.coach_wins_by_year["C1"][2026] = 5
        tally.coach_wins_by_year["C2"][2027] = 5
        tally.set_reputation(2027, FakeReputation({"11A": 2.0, "12A": 0.0, "13A": 0.0, "14X": -1.0}))
        tally.set_reputation(2028, FakeReputation({"11A": 2.0, "12A": 0.4, "13A": 0.0, "14X": -1.0}))
        coaches = SimpleNamespace(
            first_year=2026, config={"public_ownership_types": ["prefectural"]},
            coaches={"C1": SimpleNamespace(birth_year=1970, appointment_year=2027, retired_on=None),
                     "C2": SimpleNamespace(birth_year=1980, appointment_year=2027, retired_on=None)},
            events=[SimpleNamespace(date="2027-04-01", kind="transfer", coach_id="C1", from_school_id="11A",
                                    to_school_id="12A", completed_tenure_years=10),
                    SimpleNamespace(date="2027-04-01", kind="transfer", coach_id="C2", from_school_id="13A",
                                    to_school_id="14X", completed_tenure_years=8)])
        after = tally.summary(coaches)["coaches"]["after_great_coach"]
        arrived = after["5勝以上・着任"]
        self.assertEqual(arrived["coaches"], 1)
        self.assertEqual(arrived["1年後"]["change_z"], 0.4)
        # 異動元も同じく異動の前の勝数で数える：C2（異動のあとに5勝）は「名将が去った」に入らない
        self.assertEqual(after["5勝以上・異動"]["coaches"], 1)

    def test_active_tenure_counts_the_appointment_year_as_the_first_year(self):
        tally = self.tally()
        tally.set_reputation(2028, FakeReputation({"11A": 0.0}))
        coaches = SimpleNamespace(
            first_year=2026, config={"public_ownership_types": ["prefectural"]},
            coaches={"C1": SimpleNamespace(birth_year=1980, appointment_year=2025, retired_on=None),
                     "C2": SimpleNamespace(birth_year=1980, appointment_year=2026, retired_on=None)},
            events=[])
        active = tally.summary(coaches)["coaches"]["active_tenure"]
        # 2028年に、2025年就任は4年目（画面と同じ）、2026年就任は3年目
        self.assertEqual((1, 1), (active["4〜6年"], active["〜3年"]))

    def test_report_prints_and_averages_the_span(self):
        tally = self.tally()
        tally.add_match("SEN", match("12A", "11A", {"12A": [("b1", 120)], "11A": [("a1", 99)]}),
                        date(2027, 3, 30), 0)
        power = tally.summary()
        merged = average([{2026: {"x": 1}, POWER_KEY: power}, {2026: {"x": 3}, POWER_KEY: power}])
        self.assertEqual(merged[2026], {"x": 2})
        self.assertEqual(merged[POWER_KEY]["upsets"]["甲子園"]["1"]["upper_win_rate"], 0.0)
        text = format_report("平均", merged)
        self.assertIn("選抜 1大会", text)
        self.assertIn("実際の値なし", format_power(power))


if __name__ == "__main__":
    unittest.main()
