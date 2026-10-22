"""正式な画面のデータの層と、JavaScript から呼ぶ入口（game_definition.md §9）。

ウィンドウは開かない（ADR-044）。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import tempfile
import unittest

from phase2_engine import DataRepository, LiveGameService
from phase2_engine.screen.app import ScreenApi, WEB_DIR, open_session
from phase2_engine.screen.data import GameScreenData


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class ScreenDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = LiveGameService(
            self.repo, DATA_ROOT, save_root=self.tmp.name,
            autosave_after_action=False,
        )
        self.session = self.service.new_game(
            "screen", rng_seed=20261022, save_initial=False,
        )
        self.data = GameScreenData(self.service, self.session)

    def tearDown(self):
        self.tmp.cleanup()

    def test_shell_has_menu_and_header(self):
        shell = self.data.shell()
        self.assertEqual(
            ["today", "competitions", "matches", "schools", "records", "saves"],
            [item["id"] for item in shell["menu"]],
        )
        header = shell["header"]
        self.assertEqual("2026-04-01", header["date"])
        self.assertEqual("2026年4月1日（水）", header["date_label"])
        self.assertEqual(2026, header["school_year"])
        self.assertEqual(
            header["today_match_count"], len(self.data.today_matches())
        )
        self.assertTrue(header["active_competitions"])

    def test_advance_one_day(self):
        result = self.data.advance("day")
        self.assertEqual("2026-04-01", result["from_date"])
        self.assertEqual("2026-04-02", result["to_date"])
        self.assertEqual("2026-04-02", result["header"]["date"])

    def test_advance_to_next_match_day(self):
        result = self.data.advance("next_match_day")
        self.assertEqual("match_day", result["stopped_reason"])
        self.assertGreater(result["to_date"], "2026-04-01")
        self.assertTrue(self.data.today_matches())

    def test_stop_before_big_scene(self):
        result = self.data.advance(
            "date", target_date="2026-08-31", stop_at_big_scene=True,
        )
        self.assertEqual("big_scene", result["stopped_reason"])
        self.assertLess(result["to_date"], "2026-08-31")
        # 止まった日の試合はまだしていない
        finals = result["big_scene_matches"]
        self.assertTrue(finals)
        self.assertTrue(all(row["round_name"] == "決勝" for row in finals))
        self.assertTrue(all(row["status"] != "completed" for row in finals))

    def test_advance_until_competition_ends(self):
        competition = self.data.active_competitions()[0]
        result = self.data.advance(
            "competition_end",
            competition_id=competition["competition_id"],
            school_year=competition["school_year"],
        )
        self.assertEqual("competition_end", result["stopped_reason"])
        season = self.session.state.seasons[competition["school_year"]]
        self.assertTrue(
            season.competitions[competition["competition_id"]].is_complete
        )

    def test_progress_is_reported_each_day(self):
        days = []
        self.data.advance(
            "date", target_date="2026-04-05", on_day=days.append,
        )
        self.assertEqual(4, len(days))
        self.assertEqual("2026-04-05", self.data.header()["date"])

    def test_invalid_requests_are_errors(self):
        with self.assertRaises(ValueError):
            self.data.advance("date", target_date="2026-04-01")
        with self.assertRaises(ValueError):
            self.data.advance("sideways")


class ScreenApiTests(unittest.TestCase):
    def test_api_returns_errors_instead_of_raising(self):
        repo = DataRepository(DATA_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            service = LiveGameService(
                repo, DATA_ROOT, save_root=tmp, autosave_after_action=False,
            )
            session = open_session(service, "slot01", 20261022, "テスト")
            api = ScreenApi(GameScreenData(service, session))
            self.assertIn("menu", api.shell())
            self.assertIn("error", api.advance({"mode": "sideways"}))
            result = api.advance({"mode": "day"})
            self.assertEqual("2026-04-02", result["header"]["date"])
            self.assertEqual({"running": False}, api.progress())
            # 同じスロットは読み込む
            reopened = open_session(service, "slot01", 1, "別")
            self.assertEqual(
                date(2026, 4, 1), reopened.state.start_date
            )

    def test_screen_calls_only_existing_api_methods(self):
        script = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        called = set(re.findall(r"api\(\)\.(\w+)\(", script))
        self.assertTrue(called)
        for name in called:
            self.assertTrue(
                callable(getattr(ScreenApi, name, None)), name
            )
        for name in ("index.html", "style.css", "app.js"):
            self.assertTrue((WEB_DIR / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
