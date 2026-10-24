"""正式な画面：今日と記録（game_definition.md §9）。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from phase2_engine import DataRepository, LiveGameService
from phase2_engine.screen.data import GameScreenData


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class TodayAndRecordsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        repo = DataRepository(DATA_ROOT)
        cls.service = LiveGameService(
            repo, DATA_ROOT, save_root=cls.tmp.name, autosave_after_action=False,
        )
        cls.session = cls.service.new_game(
            "records", rng_seed=20261022, save_initial=False,
        )
        cls.service.advance_through(cls.session, "2026-08-31")
        cls.data = GameScreenData(cls.service, cls.session)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_records_of_the_summer(self):
        records = self.data.records(2026)
        self.assertEqual([2026], records["years"])
        summer = next(n for n in records["nationals"] if n["type"] == "national_championship")
        self.assertTrue(summer["finished"])
        counts = {finish: len(rows) for finish, rows in summer["groups"].items()}
        self.assertEqual({"優勝": 1, "準優勝": 1, "ベスト4": 2, "ベスト8": 4}, counts)
        # 夏の代表校は49校で、甲子園の成績がそろう
        reps = records["representatives"]
        self.assertEqual(49, len(reps))
        self.assertTrue(all(row["school_id"] and row["koshien"] for row in reps))
        champion = summer["groups"]["優勝"][0]["school_id"]
        self.assertIn(champion, {row["school_id"] for row in reps})
        # 出場は「実際の記録＋ゲーム内（今年の1回）」の何回目か
        for row in reps:
            actual = self.data.actual_koshien.get(row["school_id"], {}).get("summer", {})
            self.assertEqual(
                {"total": actual.get("appearances", 0) + 1,
                 "actual": actual.get("appearances", 0), "game": 1},
                row["appearance"],
            )
        self.assertEqual(1, summer["groups"]["優勝"][0]["championship_count"]["game"])
        senbatsu = next(n for n in records["nationals"] if n["type"] == "national_invitational")
        self.assertFalse(senbatsu["started"])
        with self.assertRaises(ValueError):
            self.data.records(2030)

    def test_today_screen(self):
        # このテストの進め方では甲子園の決勝が8月中旬なので、30日分を見る
        self.data.config = {
            **self.data.config,
            "recent_results": {**self.data.config["recent_results"], "days": 30},
        }
        today = self.data.today()
        self.assertEqual("2026-08-31", today["header"]["date"])
        finals = [r for r in today["recent_results"] if r["competition_name"] == "夏の甲子園"]
        self.assertEqual(1, len(finals))
        self.assertEqual("決勝", finals[0]["round_name"])
        dates = [r["match_date"] for r in today["recent_results"]]
        self.assertEqual(sorted(dates, reverse=True), dates)
        featured = today["featured"]
        self.assertLessEqual(len(featured), 6)
        matches = {(m["competition_id"], m["match_id"]) for m in self.data.today_matches()}
        for row in featured:
            self.assertIn((row["competition_id"], row["match_id"]), matches)
        per_competition = [row["competition_id"] for row in featured]
        self.assertTrue(all(per_competition.count(cid) <= 2 for cid in per_competition))


if __name__ == "__main__":
    unittest.main()
