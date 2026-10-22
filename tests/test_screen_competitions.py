"""正式な画面：大会の一覧・トーナメント表・試合・校名（game_definition.md §9）。"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from phase2_engine import DataRepository, LiveGameService
from phase2_engine.screen.app import ScreenApi
from phase2_engine.screen.competition_names import (
    CompetitionNames,
    short_competition_name,
)
from phase2_engine.screen.competition_views import match_detail
from phase2_engine.screen.data import GameScreenData
from phase2_engine.screen.school_names import (
    SchoolNames,
    prefecture_names,
    short_name,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class CompetitionScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = DataRepository(DATA_ROOT)
        cls.service = LiveGameService(
            cls.repo, DATA_ROOT, save_root=cls.tmp.name,
            autosave_after_action=False,
        )
        cls.session = cls.service.new_game(
            "screen", rng_seed=20261022, save_initial=False,
        )
        cls.service.advance_through(cls.session, "2026-05-10")
        cls.data = GameScreenData(cls.service, cls.session)
        cls.listing = cls.data.competitions()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_competition_list_covers_the_season(self):
        rows = self.listing["competitions"]
        self.assertEqual(162, len(rows))
        self.assertEqual([2026], self.listing["school_years"])
        statuses = {row["status"] for row in rows}
        self.assertEqual({"upcoming", "active", "completed"}, statuses)
        for row in rows:
            self.assertTrue(row["short_name"])
            if row["status"] == "completed" and row["champion_id"]:
                self.assertTrue(row["champion_name"])

    def _completed_with_main(self):
        for row in self.listing["competitions"]:
            if row["status"] != "completed":
                continue
            bracket = self.data.bracket(2026, row["competition_id"])
            if bracket["main"] and len(bracket["main"]["rows"]) > 8:
                return bracket
        self.fail("no completed competition with a MAIN bracket")

    def test_bracket_layout_is_a_full_tree(self):
        bracket = self._completed_with_main()
        main = bracket["main"]
        rows, matches = main["rows"], main["matches"]
        # 1試合で1校が敗退するので、試合数は出場校数より1少ない
        self.assertEqual(len(rows) - 1, len(matches))
        self.assertEqual(
            sorted(row["y"] for row in rows),
            [float(i) for i in range(len(rows))],
        )
        for match in matches:
            self.assertEqual(2, len(match["children"]))
            ys = [child["y"] for child in match["children"]]
            self.assertAlmostEqual(sum(ys) / 2, match["y"])
            for child in match["children"]:
                self.assertLess(child["round"], match["round"])
            self.assertIn(
                match["winner_id"],
                [child["school_id"] for child in match["children"]],
            )
        final = [m for m in matches if m["round"] == main["total_rounds"]]
        self.assertEqual(1, len(final))
        self.assertEqual(final[0]["winner_id"], main["champion_id"])
        self.assertEqual(final[0]["y"], main["final_y"])
        self.assertEqual("決勝", main["round_names"][-1])
        for row in rows:
            self.assertTrue(bracket["names"][row["school_id"]])

    def test_match_without_player_details(self):
        bracket = self._completed_with_main()
        match = bracket["main"]["matches"][-1]
        detail = self.data.match(
            2026, bracket["competition"]["competition_id"], match["match_id"],
        )
        self.assertEqual("決勝", detail["round_name"])
        self.assertFalse(detail["has_detail"])
        self.assertTrue(detail["team1_name"])

    def test_matches_on_a_day(self):
        latest = self.data.matches_on()
        self.assertEqual("2026-05-10", latest["date"])
        self.assertTrue(latest["matches"])
        self.assertIn("2026-04-01", latest["match_dates"])
        earlier = self.data.matches_on("2026-04-01")
        self.assertTrue(all(
            row["match_date"] == "2026-04-01" for row in earlier["matches"]
        ))

    def test_api_refuses_reads_while_advancing(self):
        api = ScreenApi(self.data)
        api._advancing = True
        try:
            self.assertTrue(api.competitions()["busy"])
            self.assertTrue(api.header()["busy"])
            self.assertEqual({"running": False}, api.progress())
        finally:
            api._advancing = False
        self.assertIn("competitions", api.competitions())


class MatchDetailTests(unittest.TestCase):
    def test_board_highlights_and_stats(self):
        players = {
            "A": {"PA": SimpleNamespace(display_name="選手A", primary_position="SS")},
            "B": {"PB": SimpleNamespace(display_name="選手B", primary_position="P")},
        }
        row = {
            "competition_id": "C", "match_id": "M", "match_date": "2026-07-01",
            "round_name": "決勝", "team1_id": "A", "team2_id": "B",
            "team1_score": 3, "team2_score": 1, "winner_id": "A",
            "status": "completed",
        }
        detail = {
            "inning_scores": [
                {"inning": 1, "half": "top", "batting_team_id": "A", "runs": 3},
                {"inning": 1, "half": "bottom", "batting_team_id": "B", "runs": 1},
            ],
            "team_stats": [
                {"school_id": "A", "hits": 5, "errors": 0},
                {"school_id": "B", "hits": 2, "errors": 1},
            ],
            "highlights": [
                ["S", 1, "t", "PA", "home_run", 3],
                ["P", 2, "t", "B", "PB"],
            ],
            "batter_stats": [{"school_id": "A", "player_id": "PA", "at_bats": 4, "hits": 2}],
            "pitcher_stats": [{"school_id": "B", "player_id": "PB", "outs_recorded": 25}],
        }
        out = match_detail(row, detail, lambda sid: sid + "校", players.get)
        self.assertEqual([3] + [None] * 8, out["board"][0]["innings"])
        self.assertEqual(5, out["board"][0]["hits"])
        score, change = out["highlights"]
        self.assertEqual(("選手A", "本塁打", "表", True),
                         (score["player_name"], score["event"], score["half"], score["is_home_run"]))
        self.assertEqual(("pitching_change", "B校", "選手B"),
                         (change["kind"], change["school_name"], change["player_name"]))
        self.assertEqual("遊", out["batting"]["A"][0]["position"])
        self.assertEqual("8 1/3", out["pitching"]["B"][0]["innings"])


class CompetitionNameTests(unittest.TestCase):
    def test_rule(self):
        cases = {
            "令和8年度春季埼玉県高等学校野球大会": "春季埼玉県大会",
            "令和9年度秋季近畿地区高等学校野球大会": "秋季近畿大会",
            "東京都秋季高等学校野球大会": "秋季東京都大会",
            "第108回全国高等学校野球選手権静岡大会": "夏・静岡大会",
            "第109回全国高等学校野球選手権大会": "夏の甲子園",
            "第99回選抜高等学校野球大会": "選抜大会",
            "第58回明治神宮野球大会 高校の部": "明治神宮大会",
        }
        for name, expected in cases.items():
            self.assertEqual(expected, short_competition_name(name))

    def test_short_names_are_unique(self):
        repo = DataRepository(DATA_ROOT)
        names = CompetitionNames(ROOT / "config")
        shorts = [
            names(cid, row["competition_name"])
            for cid, row in repo.competitions.items()
        ]
        self.assertEqual(len(shorts), len(set(shorts)))
        self.assertFalse([n for n in shorts if "高等学校" in n])


class SchoolNameTests(unittest.TestCase):
    def test_rule(self):
        cases = [
            ({"display_name": "滋賀県立大津高等学校", "ownership_type": "prefectural"}, "滋賀県", "大津"),
            ({"display_name": "北海道えりも高", "ownership_type": "prefectural"}, "北海道", "えりも"),
            ({"display_name": "日高", "ownership_type": "prefectural"}, "和歌山県", "日高"),
            ({"display_name": "沼津市立沼津高等学校", "ownership_type": "municipal"}, "静岡県", "市立沼津"),
            ({"display_name": "釧路工業高等専門学校", "ownership_type": "national"}, "北海道", "釧路工業高専"),
            ({"display_name": "都立青鳥特別支援学校", "ownership_type": "prefectural"}, "東京都", "青鳥特別支援学校"),
        ]
        for school, prefecture, expected in cases:
            self.assertEqual(expected, short_name(school, prefecture))

    def test_names_are_unique_in_each_prefecture(self):
        repo = DataRepository(DATA_ROOT)
        names = SchoolNames(repo, ROOT / "config")
        by_pref = defaultdict(list)
        for school_id, name in names.all().items():
            self.assertTrue(name, school_id)
            self.assertNotIn("高等学校", name, school_id)
            by_pref[(repo.schools[school_id]["prefecture_code"], name)].append(school_id)
        duplicates = {key: ids for key, ids in by_pref.items() if len(ids) > 1}
        self.assertEqual({}, duplicates)
        self.assertEqual(47, len(prefecture_names(repo.data_dir)))


if __name__ == "__main__":
    unittest.main()
