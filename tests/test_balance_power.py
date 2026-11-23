"""バランスの物差しの通しの指標（架空の学校・監督の記録で確かめる。試合は進めない）。"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest

from unittest import mock

from historical_results.summer_local import finishes as local_finishes
from phase2_engine import balance_power
from phase2_engine.balance_power import (
    PowerTally, UpsetCounter, dynasty_metrics, entry_rates, format_power, merge_seeds, newcomer_metrics,
    origin_metrics,
    prior_ranks, spread_by_prefecture,
)
from phase2_engine.balance_report import POWER_KEY, average, format_report

KINDS = {"LOC": "summer_local_qualifier", "KOS": "national_championship", "SEN": "national_invitational"}


class FakeRepo:
    """学校IDの頭2文字を都道府県にする架空の学校。X で始まる学校は私立。"""

    def team(self, school_id):
        return SimpleNamespace(prefecture_code=school_id[:2])

    def ownership_type(self, school_id):
        return "private" if school_id.endswith("X") else "prefectural"

    def group(self, school_id):
        return "私立" if school_id.endswith("X") else "公立"


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


def local_game(top, bottom, winner, day):
    """夏の地方大会の実際の試合の行（``summer_local_games.csv`` の列のうち使うもの）。"""
    return {"tournament": "2026年架空大会", "game_date": day, "top_team": top, "bottom_team": bottom,
            "top_school_id": top, "bottom_school_id": bottom, "winner": "top" if winner == top else "bottom",
            "result_type": "decided", "year": "2026"}


class TurnoverTests(unittest.TestCase):
    def test_prior_ranks_ties_no_record_and_divisions(self):
        finishes = {
            2023: {"北": {"11A": 1, "11B": 2}, "南": {"11C": 4}},
            2024: {"北": {"11B": 1}, "南": {"11A": 4}},
            2025: {"北": {"11D": 8}, "南": {"11C": 1}},
            2026: {"北": {"11A": 0, "11B": 0, "11E": 0}, "南": {"11C": 0, "11D": 0, "11F": 0}},
        }
        ranks = prior_ranks(finishes, 2026)
        # 11A：0.3×5＋0.6×3＝3.3、11B：0.3×4＋0.6×5＝4.2、11C：0.3×3＋1.0×5＝5.9、11D：1.0×2＝2.0
        self.assertEqual(ranks["北"], {"11B": 1, "11A": 2, "11E": None})
        self.assertEqual(ranks["南"], {"11C": 1, "11D": 2, "11F": None})
        # 同点は同じ順位で、次は飛ばす
        tied = {**finishes, 2025: {"北": {"11E": 8, "11A": 8}, "南": {}}}
        tied[2024] = {"北": {}, "南": {}}
        tied[2023] = {"北": {}, "南": {}}
        self.assertEqual(prior_ranks(tied, 2026)["北"], {"11A": 1, "11E": 1, "11B": None})
        # 前の3年がそろわない年は出さない
        self.assertIsNone(prior_ranks(finishes, 2025))

    def test_origin_bands_by_public_and_private(self):
        finishes = {2023: {"北": {"11X": 1}}, 2024: {"北": {"11X": 1}}, 2025: {"北": {"11X": 1, "11A": 2}},
                    2026: {"北": {"11A": 1, "11X": 2, "11B": 4, "11C": 4, "11D": 0}}}
        out = origin_metrics(finishes, [2025, 2026], FakeRepo().group)
        self.assertEqual(out["years"], [2026])
        self.assertEqual(out["champion"]["全体"]["slots"], 1)
        self.assertEqual(out["champion"]["公立"]["2〜3位"], 1.0)
        self.assertEqual(out["best4"]["全体"]["slots"], 4)
        self.assertEqual(out["best4"]["私立"]["1位"], 1.0)
        self.assertEqual(out["best4"]["公立"]["実績なし"], round(2 / 3, 4))

    def test_entry_rates_are_per_school_by_band_and_ownership(self):
        finishes = {2023: {"北": {"11A": 1}}, 2024: {"北": {}}, 2025: {"北": {}},
                    2026: {"北": {"11A": 4, "11B": 1, "11C": 0, "11X": 2, "11ZX": 0}}}
        out = entry_rates(finishes, [2026], FakeRepo().group)
        self.assertEqual(out["1位"]["公立"], {"schools": 1, "best4_rate": 1.0, "champion_rate": 0.0})
        self.assertEqual(out["実績なし"]["公立"], {"schools": 2, "best4_rate": 0.5, "champion_rate": 0.5})
        self.assertEqual(out["実績なし"]["私立"], {"schools": 2, "best4_rate": 0.5, "champion_rate": 0.0})

    def test_newcomer_fifteen_year_window_and_century(self):
        appearances = {"夏": {2010: {"11A"}, 2011: {"11B"}, 2026: {"11A", "11B", "11X"}},
                       "春": {2020: {"11C"}, 2026: {"11C", "11D"}}}
        century = {("11C", 2020), ("11D", 2026)}
        out = newcomer_metrics(appearances, century, {"夏": [2026], "春": [2026]}, lambda s: not s.endswith("X"))
        # 11A は16年前（新顔）、11B は15年前（新顔でない）。11X は私立
        self.assertEqual((out["夏"]["all_entrants"], out["夏"]["public"], out["夏"]["newcomers"]), (3, 2, 1))
        # 春：11D は21世紀枠なので数えない。11C は前の出場が21世紀枠だけなので新顔
        self.assertEqual((out["春"]["all_entrants"], out["春"]["newcomers"]), (1, 1))
        # 21世紀枠で出た学校の夏の出場は数える（翌年の夏は新顔でない）
        appearances["夏"][2027] = {"11D"}
        self.assertEqual(newcomer_metrics(appearances, century, {"夏": [2027]}, lambda s: True)["夏"]["newcomers"], 1)

    def test_game_and_actual_go_through_the_same_functions(self):
        # 同じ勝ち上がりを、実際の試合の行と、ゲームの試合（決勝まであと何回戦か）で与える
        games = [local_game("11A", "11B", "11A", "2026-07-20"), local_game("11C", "11D", "11C", "2026-07-21"),
                 local_game("11A", "11C", "11A", "2026-07-25")]
        actual = {("11A",): 1, ("11C",): 2, ("11B",): 4, ("11D",): 4}
        self.assertEqual({(team,): v for (_, team), v in local_finishes(games).items()}, actual)
        tally = PowerTally(FakeRepo(), KINDS.get)
        for game, left in zip(games, (1, 1, 0)):
            winner = game["top_team"] if game["winner"] == "top" else game["bottom_team"]
            loser = game["bottom_team"] if winner == game["top_team"] else game["top_team"]
            tally.add_match("LOC", match(winner, loser, {winner: [("p1", 90)], loser: [("p2", 90)]}),
                            date(2026, 7, 20), left)
        self.assertEqual(dict(tally.local_finishes[2026]["LOC"]), {k[0]: v for k, v in actual.items()})
        before = {2023: {"x": {"11B": 1}}, 2024: {"x": {}}, 2025: {"x": {}}}
        with mock.patch.object(balance_power, "actual_finishes", return_value=before), \
                mock.patch.object(balance_power, "actual_appearances", return_value=({"夏": {}, "春": {}}, set())):
            out = tally.summary()["turnover"]
        expected = origin_metrics({**before, 2026: {"LOC": dict(tally.local_finishes[2026]["LOC"])}}, [2026],
                                  FakeRepo().group)
        self.assertEqual(out["origin"], expected)
        self.assertEqual(out["origin"]["champion"]["公立"]["実績なし"], 1.0)


if __name__ == "__main__":
    unittest.main()
