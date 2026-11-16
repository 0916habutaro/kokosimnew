"""記録の画面「ランキング」の都道府県別の対戦成績（甲子園。ゲーム開始後の試合だけ）。学校・試合は架空。"""
from __future__ import annotations

import unittest

from phase2_engine.screen import rankings
from phase2_engine.screen.school_views import normalized_rows, year_results


COMPETITIONS = {
    "SUMMER": {"competition_type": "national_championship", "competition_name": "夏の架空大会"},
    "SPRING": {"competition_type": "national_invitational", "competition_name": "春の架空大会"},
    "LOCAL": {"competition_type": "summer_local_qualifier", "competition_name": "地方の架空大会"},
}
# 学校 → 地域（北海道・東京は夏の代表区分で2つに分ける）
AREAS = {"N1": "01N", "S1": "01S", "E1": "13E", "W1": "13W", "O1": "27", "O2": "27", "K1": "28"}


def game(cid, mid, day, team1, team2, s1, s2, round_no=1, winner=None, status="completed"):
    return {"competition_id": cid, "match_id": f"STG-MAIN-R{round_no:02d}-{mid}", "match_date": day,
            "stage_code": "MAIN", "round_no": round_no, "team1_id": team1, "team2_id": team2,
            "team1_score": s1, "team2_score": s2, "winner_id": winner or "", "status": status}


def season(year):
    s = f"{year}-08-"
    p = f"{year + 1}-03-"
    return [
        game("SUMMER", "M1", s + "06", "N1", "S1", 5, 3),            # 北北海道が南北海道に勝つ
        game("SUMMER", "M2", s + "07", "E1", "W1", 2, 4),            # 西東京が東東京に勝つ
        game("SUMMER", "M3", s + "08", "O1", "K1", 1, 0),            # 大阪が兵庫に勝つ
        game("SUMMER", "M4", s + "09", "O1", "N1", 3, 3),            # 引き分け（数えない）
        game("SUMMER", "M5", s + "10", "O1", "N1", 6, 2),            # 再試合（1試合に数える）
        game("SUMMER", "M6", s + "11", "S1", "K1", None, None, winner="K1"),  # 不戦勝（勝ち・負けに数える）
        game("SPRING", "M1", p + "20", "O1", "O2", 7, 1),            # 同じ地域どうし（大阪）
        game("SPRING", "M2", p + "21", "W1", "N1", 0, 2),
        game("LOCAL", "M1", s + "01", "O1", "O2", 9, 0),             # 甲子園ではない
        game("SUMMER", "M7", s + "12", "K1", "E1", None, None, status="scheduled"),  # まだ
    ]


def games_by_year(years=(2026, 2027)):
    return {y: rankings.koshien_games(normalized_rows(season(y)), COMPETITIONS) for y in years}


class MatchupTests(unittest.TestCase):
    def test_split_areas_are_counted_separately(self):
        table = rankings.matchups(games_by_year((2026,)), None, "koshien", AREAS.get)
        self.assertEqual({"01S": [1, 0], "27": [0, 1], "13W": [1, 0]}, table["01N"]["opponents"])
        self.assertEqual({"01N": [0, 1], "28": [0, 1]}, table["01S"]["opponents"])
        self.assertEqual({"13W": [0, 1], }, table["13E"]["opponents"])
        self.assertEqual({"13E": [1, 0], "01N": [0, 1]}, table["13W"]["opponents"])
        # 同じ地域どうしは、その地域に1勝1敗（相手の欄は自分の地域）
        self.assertEqual([1, 1], table["27"]["opponents"]["27"])
        self.assertEqual((3, 1), (table["27"]["wins"], table["27"]["losses"]))
        self.assertAlmostEqual(0.75, table["27"]["rate"])

    def test_kind_and_period_change_the_counts(self):
        games = games_by_year()
        summer = rankings.matchups(games, None, "summer", AREAS.get)
        spring = rankings.matchups(games, None, "spring", AREAS.get)
        both = rankings.matchups(games, None, "koshien", AREAS.get)
        self.assertEqual((2, 2), (summer["01N"]["wins"], summer["01N"]["losses"]))
        self.assertEqual((2, 0), (spring["01N"]["wins"], spring["01N"]["losses"]))
        self.assertEqual((4, 2), (both["01N"]["wins"], both["01N"]["losses"]))
        self.assertNotIn("27", spring["01N"]["opponents"])
        last_year = rankings.matchups(games, {2027}, "koshien", AREAS.get)
        self.assertEqual(both["01N"]["wins"] / 2, last_year["01N"]["wins"])

    def test_totals_match_the_prefecture_ranking(self):
        """勝・敗の合計は、ランキングの都道府県別（学校の通算の勝敗を地域ごとに足したもの）と同じ。"""
        tallies = {y: rankings.year_tally(year_results(normalized_rows(season(y)), COMPETITIONS, {},
                                                       lambda cid, name: name)) for y in (2026, 2027)}
        for kind in ("koshien", "summer", "spring"):
            for years in (None, {2027}):
                by_area = rankings.prefecture_totals(rankings.school_totals(tallies, years), AREAS.get)
                table = rankings.matchups(games_by_year(), years, kind, AREAS.get)
                for area, total in by_area.items():
                    entry = table.get(area, {"wins": 0, "losses": 0})
                    self.assertEqual((total[kind]["wins"], total[kind]["losses"]),
                                     (entry["wins"], entry["losses"]), (kind, years, area))

    def test_unfinished_competitions_are_not_counted(self):
        rows = normalized_rows(season(2026))
        games = rankings.koshien_games(rows, COMPETITIONS, finished=lambda cid: cid != "SPRING")
        self.assertEqual({"summer"}, {g["kind"] for g in games})

    def test_best_and_worst_and_area_games(self):
        games = games_by_year()
        table = rankings.matchups(games, None, "koshien", AREAS.get)
        order = {code: i for i, code in enumerate(["01N", "01S", "13E", "13W", "27", "28"])}
        best, worst = rankings.best_and_worst(table["01N"]["opponents"], order)
        self.assertEqual(("01S", 2, 0), (best["area"], best["wins"], best["losses"]))
        self.assertEqual(("27", 0, 2), (worst["area"], worst["wins"], worst["losses"]))
        self.assertEqual((None, None), rankings.best_and_worst({"28": [1, 1]}, order))
        listed = rankings.area_games(games, {2027}, "koshien", AREAS.get, "01N")
        self.assertEqual(["2028-03-21", "2027-08-10", "2027-08-06"], [g["match_date"] for g in listed])
        self.assertEqual([2, 2, 1], [g["side"] for g in listed])
        # 架空の選抜は1回戦しかないので、その回戦が決勝になる
        self.assertEqual("決勝", listed[0]["round_name"])


if __name__ == "__main__":
    unittest.main()
