"""記録の画面の「ランキング」：数え方（実際＋ゲーム・ゲームだけ・期間）と色の段階分け（架空のデータで）。"""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.screen import rankings as rk
from phase2_engine.screen.data import GameScreenData


def result(cid, ctype, wins=0, losses=0, finish="1回戦敗退"):
    return {"competition_id": cid, "type": ctype, "wins": wins, "losses": losses, "finish": finish}


def year_results():
    return {
        "S-A": [result("SUMMER", "national_championship", 5, 0, "優勝"),
                result("JINGU", "national_autumn_championship", 4, 0, "優勝"),
                result("LOCAL", "summer_local_qualifier", 6, 0, "優勝")],
        "S-B": [result("SPRING", "national_invitational", 1, 1, "2回戦敗退"),
                result("REGION", "autumn_regional", 3, 0, "優勝"),
                result("PREF", "spring_prefectural", 5, 0, "優勝")],
        # 甲子園にも出ず優勝もない学校は数えない
        "S-C": [result("PREF", "spring_prefectural", 2, 1, "ベスト8")],
    }


class YearTallyTests(unittest.TestCase):
    def test_counts_koshien_and_titles(self):
        tally = rk.year_tally(year_results())
        self.assertEqual([1, 5, 0, 1], tally["S-A"]["summer"])
        self.assertEqual((1, 1, 1), (tally["S-A"]["jingu"], tally["S-A"]["prefectural"], "regional" not in tally["S-A"]))
        self.assertEqual([1, 1, 1, 0], tally["S-B"]["spring"])
        self.assertEqual((1, 1), (tally["S-B"]["regional"], tally["S-B"]["prefectural"]))
        self.assertNotIn("S-C", tally)

    def test_unfinished_competitions_are_not_counted(self):
        tally = rk.year_tally(year_results(), finished=lambda cid: cid != "SUMMER")
        self.assertNotIn("summer", tally["S-A"])
        self.assertEqual(1, tally["S-A"]["jingu"])

    def test_blob_round_trip(self):
        tally = rk.year_tally(year_results())
        self.assertEqual(tally, rk.from_blob(rk.to_blob(tally)))


class TotalTests(unittest.TestCase):
    def setUp(self):
        self.tallies = {2030: rk.year_tally(year_results()), 2031: rk.year_tally(year_results())}
        # 実際の記録（ゲーム開始前）：S-A は夏10回出場・12勝9敗・優勝1、S-D は春だけ
        self.actual = {"S-A": {"summer": {"appearances": 10, "wins": 12, "losses": 9, "championships": 1}},
                       "S-D": {"spring": {"appearances": 2, "wins": 0, "losses": 2, "championships": 0}}}

    def test_game_only_and_actual_plus_game(self):
        game = rk.school_totals(self.tallies)
        self.assertEqual({"appearances": 2, "wins": 10, "losses": 0, "championships": 2, "rate": 1.0},
                         game["S-A"]["summer"])
        self.assertNotIn("S-D", game)
        both = rk.school_totals(self.tallies, actual=self.actual)
        self.assertEqual((12, 22, 9, 3), tuple(both["S-A"]["summer"][k] for k in rk.COUNT_KEYS))
        self.assertAlmostEqual(22 / 31, both["S-A"]["summer"]["rate"])
        # 神宮・地区・県大会はゲームだけ（実際の記録を足しても変わらない）
        self.assertEqual(2, both["S-A"]["jingu"])
        self.assertEqual(2, both["S-D"]["koshien"]["appearances"])
        self.assertEqual(0.0, both["S-D"]["spring"]["rate"])
        # 実際の記録の元のデータは変えない（保存では混ぜない）
        self.assertEqual(10, self.actual["S-A"]["summer"]["appearances"])

    def test_period_counts_only_its_years(self):
        recent = rk.school_totals(self.tallies, years={2031})
        self.assertEqual(1, recent["S-A"]["summer"]["appearances"])
        self.assertEqual(1, recent["S-B"]["regional"])
        self.assertEqual({}, rk.school_totals(self.tallies, years={2040}))

    def test_koshien_total_and_rate_without_games(self):
        total = rk.school_totals(self.tallies)["S-A"]
        self.assertEqual(2, total["koshien"]["appearances"])
        self.assertIsNone(total["spring"]["rate"])

    def test_prefecture_totals(self):
        prefs = rk.prefecture_totals(rk.school_totals(self.tallies), {"S-A": "90", "S-B": "90"}.get)
        self.assertEqual(4, prefs["90"]["koshien"]["appearances"])
        self.assertEqual((10 + 2) / (10 + 2 + 2), prefs["90"]["koshien"]["rate"])


class ColorStepTests(unittest.TestCase):
    def test_integer_steps_between_min_and_max(self):
        steps = rk.color_steps({"a": 74, "b": 275, "c": 115, "d": 0, "e": None})
        self.assertEqual([[74, 114], [115, 155], [156, 196], [197, 237], [238, 275]], steps["bounds"])
        self.assertEqual({"a": 0, "b": 4, "c": 1, "d": None, "e": None}, steps["classes"])

    def test_small_integers_do_not_make_empty_steps(self):
        steps = rk.color_steps({"a": 1, "b": 2, "c": 3})
        self.assertEqual([[1, 1], [2, 2], [3, 3]], steps["bounds"])
        self.assertEqual({"a": 0, "b": 1, "c": 2}, steps["classes"])

    def test_rates_are_split_evenly(self):
        steps = rk.color_steps({"a": 0.2, "b": 0.7, "c": 0.45, "d": 0.0})
        self.assertFalse(steps["integer"])
        self.assertEqual(5, len(steps["bounds"]))
        self.assertEqual({"a": 0, "b": 4, "c": 2, "d": None}, steps["classes"])

    def test_no_values_and_single_value(self):
        self.assertEqual([], rk.color_steps({"a": 0})["bounds"])
        self.assertEqual({"a": 0, "b": 0}, rk.color_steps({"a": 0.5, "b": 0.5})["classes"])


class ClosedYearTests(unittest.TestCase):
    def test_closed_year_is_counted_once_and_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = HistoricalMatchArchive(Path(tmp) / "history.sqlite3")
            calls = []
            data = GameScreenData.__new__(GameScreenData)
            data._ranking_years = {}
            data.session = SimpleNamespace(slot_id="s", state=SimpleNamespace(year=2031, competitions={}))
            data.service = SimpleNamespace(_history_archive=lambda slot: archive)
            data._years = lambda: [2030, 2031]
            data._results = lambda year: calls.append(year) or (year_results() if year == 2030 else {})
            self.assertEqual(1, data.ranking_tallies()[2030]["S-A"]["jingu"])
            self.assertEqual([2030, 2031], calls)
            # 次のセーブの読み込み（新しい画面のデータ）では、閉じた年度は履歴の集計を読む
            data._ranking_years = {}
            calls.clear()
            self.assertEqual(1, data.ranking_tallies()[2030]["S-A"]["jingu"])
            self.assertEqual([2031], calls)


class BasisTests(unittest.TestCase):
    def setUp(self):
        self.totals = rk.school_totals({2030: rk.year_tally({
            # 夏の甲子園で0勝1敗
            "S-L": [result("SUMMER", "national_championship", 0, 1, "1回戦敗退")],
            # 甲子園に出ず、県大会だけ優勝
            "S-P": [result("PREF", "spring_prefectural", 5, 0, "優勝")],
        })})

    def test_koshien_basis_keeps_schools_that_appeared(self):
        for key in ("K.appearances", "K.wins", "K.rate", "name", "prefecture", None):
            self.assertEqual("koshien", rk.basis(key))
        self.assertTrue(rk.has_record(self.totals["S-L"], "summer", "koshien"))
        self.assertFalse(rk.has_record(self.totals["S-L"], "spring", "koshien"))
        self.assertFalse(rk.has_record(self.totals["S-P"], "koshien", "koshien"))

    def test_title_basis_needs_a_title(self):
        self.assertEqual("jingu", rk.basis("jingu"))
        self.assertFalse(rk.has_record(self.totals["S-L"], "summer", "jingu"))
        self.assertTrue(rk.has_record(self.totals["S-P"], "summer", "prefectural"))
        self.assertEqual("神宮大会で優勝した学校だけを出しています。", rk.basis_note("summer", "jingu"))
        self.assertEqual("夏の甲子園に出場した学校だけを出しています。", rk.basis_note("summer", "koshien"))

    def test_periods(self):
        self.assertEqual((None, True), rk.period_years("all", 2031))
        self.assertEqual((None, False), rk.period_years("game", 2031))
        self.assertEqual(({2027, 2028, 2029, 2030, 2031}, False), rk.period_years("5", 2031))


class RecordsRankingsTests(unittest.TestCase):
    """画面のデータ（records_rankings）：期間と、学校別に出す学校の絞り込み。"""

    def screen(self):
        data = GameScreenData.__new__(GameScreenData)
        tally = rk.year_tally({
            "S-L": [result("SUMMER", "national_championship", 0, 1, "1回戦敗退")],
            "S-J": [result("JINGU", "national_autumn_championship", 4, 0, "優勝"),
                    result("SPRING", "national_invitational", 2, 1, "ベスト8")],
            "S-N": [result("SPRING", "national_invitational", 0, 1, "1回戦敗退")],
        })
        data.ranking_tallies = lambda: {2030: tally}
        data._current_year = lambda: 2030
        data._regions = {"90": "R1"}
        data.prefectures = {"90": "架空県"}
        data.names = lambda sid: sid
        data._ownership = lambda sid: "私立"
        data.actual_koshien = {"S-A": {"summer": {"appearances": 3, "wins": 2, "losses": 3, "championships": 0}}}
        repo = SimpleNamespace(schools={sid: {"prefecture_code": "90"} for sid in ("S-L", "S-J", "S-N", "S-A")},
                               data_dir=Path(__file__).resolve().parents[1] / "data")
        data.service = SimpleNamespace(repo=repo)
        # 地図のマス：架空県90を夏の代表区分で2つに分ける（S-L は北、ほかは南）
        tiles = [["90N", "架空北"], ["90S", "架空南"]]
        data._school_tiles = lambda: ((lambda sid: "90N" if sid == "S-L" else "90S"), tiles)
        data.tile_map = lambda: {"tiles": [{"code": "90N", "prefecture": "90"}, {"code": "90S", "prefecture": "90"}]}
        return data

    def ids(self, **filters):
        return sorted(r["school_id"] for r in self.screen().records_rankings(filters)["schools"])

    def test_game_period_does_not_add_actual_records(self):
        self.assertIn("S-A", self.ids(period="all", kind="summer"))
        out = self.screen().records_rankings({"period": "game", "kind": "summer"})
        self.assertFalse(out["use_actual"])
        self.assertNotIn("S-A", [r["school_id"] for r in out["schools"]])

    def test_summer_shows_schools_that_appeared_even_without_wins(self):
        self.assertEqual(["S-L"], self.ids(period="game", kind="summer", sort_key="K.wins"))
        self.assertEqual(["S-J", "S-N"], self.ids(period="game", kind="spring", sort_key="name"))

    def test_jingu_sort_hides_schools_without_a_title(self):
        out = self.screen().records_rankings({"period": "game", "kind": "summer", "sort_key": "jingu"})
        self.assertEqual(["S-J"], [r["school_id"] for r in out["schools"]])
        self.assertEqual("神宮大会で優勝した学校だけを出しています。", out["basis_note"])
        # 都道府県別は絞らない
        self.assertEqual(["90N", "90S"], [r["prefecture_code"] for r in out["prefecture_rows"]])

    def test_split_tiles_count_schools_by_summer_representation(self):
        out = self.screen().records_rankings({"period": "game", "kind": "koshien"})
        rows = {r["prefecture_code"]: r for r in out["prefecture_rows"]}
        self.assertEqual(1, rows["90N"]["koshien"]["appearances"])  # S-L
        self.assertEqual(2, rows["90S"]["koshien"]["appearances"])  # S-J・S-N の選抜
        self.assertEqual({"90N", "90S"}, set(out["map"]["values"]))
        # 学校別で北のマスを選ぶと、その区分の学校だけ
        self.assertEqual(["S-L"], self.ids(period="game", kind="koshien", prefecture="90N"))
        self.assertEqual([["90N", "架空北"], ["90S", "架空南"]], out["prefectures"])


if __name__ == "__main__":
    unittest.main()
