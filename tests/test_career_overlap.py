"""年度の重なり（game_definition.md §8）。

秋の大会の後に翌年度の大会表をつくり、3月は前の年度の選抜と新しい年度の
春季県大会を同じ日付で進める。年度末（3月31日）を進めたら前の年度を閉じる。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path
import tempfile
import unittest

from phase2_engine import DataRepository, LiveGameService
from phase2_engine.career_state import CareerState, autumn_end


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


def _school_days(seasons):
    days = defaultdict(set)
    for year, state in seasons.items():
        for row in state.completed_results().values():
            for team in (row["team1_id"], row["team2_id"]):
                days[(team, row["match_date"])].add(
                    (year, row["competition_id"], row["match_id"])
                )
    return days


class CareerOverlapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        repo = DataRepository(DATA_ROOT)
        cls.service = LiveGameService(
            repo, DATA_ROOT, save_root=cls.tmp.name,
            autosave_after_action=False,
        )
        cls.session = cls.service.new_game("career", rng_seed=20261021)
        cls.state = cls.session.state
        cls.autumn_end_2026 = autumn_end(cls.state.seasons[2026])
        cls.service.advance_through(cls.session, "2027-03-25")
        cls.overlap_seasons = dict(cls.state.seasons)
        cls.service.save_game(cls.session)
        cls.loaded = cls.service.load_game("career")
        cls.service.advance_through(cls.session, "2027-04-02")
        cls.service.advance_through(cls.loaded, "2027-04-02")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_next_season_opens_after_autumn(self):
        self.assertIsInstance(self.state, CareerState)
        self.assertEqual([2026, 2027], sorted(self.overlap_seasons))
        opened = self.overlap_seasons[2027].start_date
        self.assertEqual(
            self.autumn_end_2026.toordinal() + 1, opened.toordinal()
        )
        self.assertLess(opened, date(2027, 4, 1))

    def test_march_games_of_both_seasons_share_the_calendar(self):
        march = [
            row for row in self.overlap_seasons[2027].completed_results().values()
            if row["match_date"] < "2027-04-01"
        ]
        self.assertTrue(march)
        senbatsu = [
            row for row in self.overlap_seasons[2026].completed_results().values()
            if row["competition_id"] == "CMP000001"
        ]
        self.assertTrue(senbatsu)
        self.assertTrue(all(r["match_date"].startswith("2027-03") for r in senbatsu))

    def test_no_school_plays_two_competitions_on_one_day(self):
        days = _school_days(self.overlap_seasons)
        doubles = {key: games for key, games in days.items() if len(games) > 1}
        across = [
            games for games in doubles.values()
            if len({(year, cid) for year, cid, _ in games}) > 1
        ]
        self.assertEqual([], across)
        # 日程が地区ごとの日をまとめたものしかない大会だけ、わずかに残る
        self.assertLess(len(doubles), 30)

    def test_previous_season_closes_on_april_first(self):
        self.assertEqual([2027], sorted(self.state.seasons))
        self.assertEqual(2027, self.session.plan.year)
        years = {
            row["year"]: row for row in self.service.career_history_years("career")
        }
        self.assertEqual("sealed", years[2026]["status"])
        self.assertEqual("active", years[2027]["status"])

    def test_save_during_overlap_restores_both_seasons(self):
        self.assertEqual([2027], sorted(self.loaded.state.seasons))
        self.assertEqual(
            self.state.seasons[2027].completed_results(),
            self.loaded.state.seasons[2027].completed_results(),
        )


if __name__ == "__main__":
    unittest.main()
