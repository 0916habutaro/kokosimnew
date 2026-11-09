"""出場・優勝の回数の文言（新聞の出場校紹介の書き方）。架空の学校だけを使う。"""
from types import SimpleNamespace
import unittest

from phase2_engine.screen.data import GameScreenData
from phase2_engine.screen.koshien_records import actual_history, nth_label


class NthLabelTests(unittest.TestCase):
    def test_first_consecutive_and_gap(self):
        self.assertEqual("初出場", nth_label(0, set(), 2027))
        self.assertEqual("2年連続15回目", nth_label(14, {2026, 2020}, 2027))
        self.assertEqual("4年連続4回目", nth_label(3, {2024, 2025, 2026}, 2027))
        self.assertEqual("11年ぶり3回目", nth_label(2, {2016, 2001}, 2027))
        # この年より後の年（過去の年度の行を出すとき）は数えない
        self.assertEqual("初出場", nth_label(0, {2030}, 2027))

    def test_champion(self):
        self.assertEqual("初優勝", nth_label(0, set(), 2027, champion=True))
        self.assertEqual("2年ぶり5回目の優勝", nth_label(4, {2025, 2010}, 2027, champion=True))
        self.assertEqual("2年連続3回目の優勝", nth_label(2, {2026, 2000}, 2027, champion=True))

    def test_game_only(self):
        self.assertEqual("ゲームで初出場", nth_label(0, set(), 2029, game_only=True))
        self.assertEqual("ゲームで2年ぶり3回目", nth_label(2, {2026, 2027}, 2029, game_only=True))
        self.assertEqual("ゲームで初優勝", nth_label(0, set(), 2029, game_only=True, champion=True))

    def test_missing_years_are_not_guessed(self):
        # 実際の記録の年が欠けている（〜2025年）：そこにかかる連続・ぶりは言わない
        self.assertEqual("15回目", nth_label(14, {2025}, 2026, uncertain_until=2025))
        self.assertEqual("15回目", nth_label(14, {1990}, 2026, uncertain_until=2025))
        self.assertEqual("15回目", nth_label(14, set(), 2026, uncertain_until=2025))
        # ゲームの中の年（欠けていない）だけで決まるときは言う
        self.assertEqual("2年ぶり16回目", nth_label(15, {2026, 1990}, 2028, uncertain_until=2025))
        self.assertEqual("2年連続16回目", nth_label(15, {2027, 1990}, 2028, uncertain_until=2025))
        # 連続が欠けているかもしれない年まで続くと、もっと長いかもしれない
        self.assertEqual("16回目", nth_label(15, {2026, 2027}, 2028, uncertain_until=2025))


class ActualHistoryTests(unittest.TestCase):
    def test_years_complete_or_not(self):
        listed = {"appearances": 3, "entrant_years": [2001, 2024], "years": [], "last_year": 2025,
                  "championships": 1, "champion_years": [2001]}
        self.assertEqual((3, {2001, 2024, 2025}, None), actual_history(listed, "summer"))
        self.assertEqual((1, {2001}, None), actual_history(listed, "summer", champion=True))
        partial = {"appearances": 5, "entrant_years": [2024], "last_year": 2025, "championships": 2}
        self.assertEqual((5, {2024, 2025}, 2025), actual_history(partial, "summer"))
        self.assertEqual((2, set(), 2026), actual_history(partial, "spring", champion=True))
        self.assertEqual((0, set(), None), actual_history(None, "summer"))


class EntryLabelTests(unittest.TestCase):
    """実際の記録とゲームの中の出場を、表示のときに足す（甲子園）。ほかの大会はゲームの中だけ。"""

    def setUp(self):
        competitions = {
            "FAKE-SUMMER": {"competition_type": "national_championship"},
            "FAKE-SPRING": {"competition_type": "national_invitational"},
            "FAKE-JINGU": {"competition_type": "national_autumn_championship"},
        }
        self.data = GameScreenData.__new__(GameScreenData)
        self.data.service = SimpleNamespace(repo=SimpleNamespace(competitions=competitions))
        self.data.actual_koshien = {"FAKE-A": {
            "summer": {"appearances": 14, "entrant_years": list(range(2012, 2026)), "last_year": 2025,
                       "championships": 4, "champion_years": [2001, 2005, 2010, 2025]},
            "spring": {"appearances": 2, "entrant_years": [2015, 2026], "last_year": 2026,
                       "championships": 0},
        }}
        # ゲームの中（大会ごと）：2026年夏に出場・優勝、2027年夏に出場、神宮は2026・2027年度
        self.history = {
            "FAKE-SUMMER": {"FAKE-A": {"appear": {2026, 2027}, "champion": {2026}}},
            "FAKE-JINGU": {"FAKE-A": {"appear": {2026, 2027}, "champion": set()}},
        }

    def label(self, cid, year, school="FAKE-A", champion=False):
        return self.data.entry_label(cid, year, school, self.history.get(cid, {}), champion=champion)

    def test_koshien_adds_actual_and_game(self):
        self.assertEqual("15年連続15回目", self.label("FAKE-SUMMER", 2026))
        self.assertEqual("16年連続16回目", self.label("FAKE-SUMMER", 2027))
        self.assertEqual("2年連続5回目の優勝", self.label("FAKE-SUMMER", 2026, champion=True))
        self.assertEqual("3年連続6回目の優勝", self.label("FAKE-SUMMER", 2027, champion=True))
        # 選抜は年度の翌年3月（2026年度 → 2027年）。実際の記録は2026年の選抜まで
        self.assertEqual("2年連続3回目", self.label("FAKE-SPRING", 2026))
        self.assertEqual("初出場", self.label("FAKE-SUMMER", 2027, school="FAKE-B"))

    def test_other_competitions_count_only_in_game(self):
        self.assertEqual("ゲームで初出場", self.label("FAKE-JINGU", 2026))
        self.assertEqual("ゲームで2年連続2回目", self.label("FAKE-JINGU", 2027))
        self.assertEqual("ゲームで2年ぶり3回目", self.label("FAKE-JINGU", 2029))
        self.assertEqual("ゲームで初優勝", self.label("FAKE-JINGU", 2028, champion=True))


class BundleTests(unittest.TestCase):
    def test_exe_bundles_files_read_for_counts(self):
        """EXE（kokosimnew.spec）に、回数を数えるために読む historical_data のファイルが入っている。"""
        from pathlib import Path
        from phase2_engine.screen import koshien_records as kr
        spec = (Path(__file__).resolve().parents[1] / "kokosimnew.spec").read_text(encoding="utf-8")
        for name in (kr.RECORDS_PATH.name, kr.ENTRANTS_NAME, kr.APPEARANCES_NAME):
            self.assertIn(f'"historical_data" / "{name}"', spec, name)


if __name__ == "__main__":
    unittest.main()
