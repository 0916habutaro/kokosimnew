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

    def test_national_bracket_has_prefectures_and_entrants(self):
        koshien = next(
            cid for cid, c in self.service.repo.competitions.items()
            if c.get("competition_type") == "national_championship"
        )
        bracket = self.data.bracket(2026, koshien)
        # 全国大会の校名には都道府県を添える
        self.assertTrue(all(name.endswith("）") for name in bracket["names"].values()))
        entrants = bracket["entrants"]
        self.assertEqual(49, len(entrants))
        codes = [row["prefecture_code"] for row in entrants]
        self.assertEqual(sorted(codes), codes)
        for row in entrants:
            actual = self.data.actual_koshien.get(row["school_id"], {}).get("summer", {})
            self.assertEqual(
                {"total": actual.get("appearances", 0) + 1,
                 "actual": actual.get("appearances", 0), "game": 1},
                row["appearance"],
            )
            # カードの地区名と「初出場」「〇年連続〇回目」「〇年ぶり〇回目」
            self.assertTrue(row["area"])
            self.assertTrue(row["region_id"].startswith("REG"))
            self.assertEqual("", row["basis_label"])  # 夏に21世紀枠・神宮枠はない
            label = row["appearance_label"]
            if row["appearance"]["total"] == 1:
                self.assertEqual("初出場", label)
            else:
                self.assertTrue(label.endswith(f"{row['appearance']['total']}回目"), label)
        # 北海道・東京は代表の大会の地区名（北北海道・東東京など）
        areas = {row["area"] for row in entrants if row["prefecture_code"] in ("01", "13")}
        self.assertEqual(4, len(areas))
        # トーナメント表の校名も代表の地区名（「京都」は「京」にならない）
        names = self.data.bracket(2026, koshien)["names"]
        for row in entrants:
            self.assertTrue(names[row["school_id"]].endswith(f"（{row['area']}）"))
        self.assertIn("京都", {row["area"] for row in entrants})
        # 右の詳細：夏の地方大会の勝ち上がり（優勝して出場）
        detail = self.data.entrant(2026, koshien, entrants[0]["school_id"])
        self.assertEqual("優勝", detail["results"][-1]["finish"])
        self.assertEqual(detail["results"][-1]["wins"], len(detail["results"][-1]["games"]))
        self.assertIn("batting_average", detail["stats"])
        # 都道府県大会には付けない・出場校一覧もない
        local = next(
            row["competition_id"] for row in self.data.competitions()["competitions"]
            if row["level"] == "local" and row["status"] == "completed"
        )
        bracket = self.data.bracket(2026, local)
        self.assertEqual([], bracket["entrants"])
        self.assertFalse(any(name.endswith("）") for name in bracket["names"].values()))

    def test_competition_list_order(self):
        order = {"active": 0, "upcoming": 1, "completed": 2}
        statuses = [order[row["status"]] for row in self.data.competitions()["competitions"]]
        self.assertEqual(sorted(statuses), statuses)

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


class AutumnEntrantTests(unittest.TestCase):
    """秋の地区大会の校名の順位と、選抜の出場校一覧の枠の札。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        repo = DataRepository(DATA_ROOT)
        cls.service = LiveGameService(
            repo, DATA_ROOT, save_root=cls.tmp.name, autosave_after_action=False,
        )
        cls.session = cls.service.new_game(
            "autumn", rng_seed=20261022, save_initial=False,
        )
        cls.service.advance_through(cls.session, "2026-12-01")
        cls.data = GameScreenData(cls.service, cls.session)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _by_type(self, kind):
        return next(
            cid for cid, c in self.service.repo.competitions.items()
            if c.get("competition_type") == kind
        )

    def test_regional_names_have_prefectural_rank(self):
        ranked = 0
        for cid, competition in self.service.repo.competitions.items():
            if (competition.get("competition_level") != "regional"
                    or competition.get("season_segment") != "autumn"):
                continue
            names = self.data.bracket(2026, cid)["names"]
            ranked += sum(name.endswith("位）") for name in names.values())
        self.assertGreater(ranked, 50)

    def test_invitational_entrants_have_selection_labels(self):
        senbatsu = self._by_type("national_invitational")
        entrants = self.data.bracket(2026, senbatsu)["entrants"]
        labels = [row["basis_label"] for row in entrants if row["basis_label"]]
        self.assertEqual(["21世紀枠", "21世紀枠", "神宮枠"], sorted(labels))
        # 右の詳細は秋の大会の成績
        detail = self.data.entrant(2026, senbatsu, entrants[0]["school_id"])
        self.assertTrue(detail["results"])
        self.assertTrue(all("秋" in r["competition_name"] for r in detail["results"]))


if __name__ == "__main__":
    unittest.main()
