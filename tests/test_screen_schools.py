"""正式な画面：学校の一覧と詳細（game_definition.md §9）。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from phase2_engine import DataRepository, LiveGameService
from phase2_engine.screen.data import GameScreenData, load_screen_config
from phase2_engine.screen.koshien_records import (
    combined as koshien_combined,
    load_actual as load_actual_koshien,
    result_rank,
)
from phase2_engine.screen.school_views import (
    SchoolAbilities,
    best_result,
    finish_label,
    koshien_summary,
    normalized_rows,
    year_results,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


def _row(cid, mid, team1, team2, score1, score2, day="2026-07-01"):
    return {
        "competition_id": cid, "match_id": mid, "match_date": day,
        "team1_id": team1, "team2_id": team2,
        "team1_score": score1, "team2_score": score2,
    }


class RecordTests(unittest.TestCase):
    def test_finish_labels(self):
        self.assertEqual("優勝", finish_label(True, 3, 3)[0])
        self.assertEqual("準優勝", finish_label(False, 3, 3)[0])
        self.assertEqual("ベスト4", finish_label(False, 4, 5)[0])
        self.assertEqual("ベスト16", finish_label(False, 3, 6)[0])
        self.assertEqual("1回戦敗退", finish_label(False, 1, 6)[0])
        self.assertEqual("決勝進出", finish_label(True, 4, 5)[0])

    def test_year_results_from_history_rows(self):
        # 履歴の試合は回戦名を持たないので、試合IDから MAIN の回戦を読む
        rows = normalized_rows([
            _row("C1", "S-MAIN-R01-M001", "A", "B", 3, 1),
            _row("C1", "S-MAIN-R01-M002", "C", "D", 0, 2),
            _row("C1", "S-MAIN-R02-M001", "A", "D", 5, 4, "2026-07-02"),
            _row("C1", "S-SGR1-POOL-M001", "A", "E", 1, 2, "2026-06-01"),
        ])
        competitions = {"C1": {
            "competition_name": "第108回全国高等学校野球選手権大会",
            "competition_type": "national_championship",
            "competition_level": "national", "season_segment": "summer",
        }}
        results = year_results(rows, competitions, {}, lambda cid, name: "夏の甲子園")
        champion = results["A"][0]
        self.assertEqual(("優勝", 2, 1), (champion["finish"], champion["wins"], champion["losses"]))
        self.assertEqual("準優勝", results["D"][0]["finish"])
        self.assertEqual("予選敗退", results["E"][0]["finish"])
        self.assertEqual("夏の甲子園 優勝", best_result(results["A"])["label"])
        koshien = koshien_summary({2026: results["A"], 2027: results["D"]})
        self.assertEqual(2, koshien["summer"]["appearances"])
        self.assertEqual([2026, 2026], koshien["summer"]["years"])
        self.assertEqual(0, koshien["spring"]["appearances"])


class ActualKoshienTests(unittest.TestCase):
    def test_load_and_combine_with_game_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "koshien_records.csv"
            path.write_text(
                "school_id,kind,as_of_edition,appearances,wins,losses,draws,"
                "championships,runner_ups,best_result,last_appearance_year,"
                "appearance_years,source_id,verified_at,notes\n"
                "SCHX1,summer,107,3,4,3,1,0,1,準優勝,2019,2001;2010;2019,S1,2026-10-23,\n"
                "SCHX1,spring,98,2,0,2,,0,,初戦敗退,,,S1,2026-10-23,\n",
                encoding="utf-8",
            )
            actual = load_actual_koshien(path)
            self.assertEqual({}, load_actual_koshien(Path(tmp) / "none.csv"))
        summer = actual["SCHX1"]["summer"]
        self.assertEqual([2001, 2010, 2019], summer["years"])
        self.assertEqual([], actual["SCHX1"]["spring"]["years"])
        game = {"appearances": 2, "wins": 6, "losses": 1, "championships": 1,
                "best": "優勝", "years": [2027, 2028]}
        both = koshien_combined(summer, game)["total"]
        self.assertEqual((5, 10, 4, 1, 1), (
            both["appearances"], both["wins"], both["losses"],
            both["draws"], both["championships"],
        ))
        self.assertEqual(("優勝", 2028), (both["best"], both["last_year"]))
        only_game = koshien_combined(None, {**game, "best": "2回戦敗退"})
        self.assertIsNone(only_game["actual"])
        self.assertEqual(2, only_game["total"]["appearances"])
        self.assertGreater(result_rank("ベスト8"), result_rank("2回戦敗退"))
        self.assertGreater(result_rank("3回戦"), result_rank("初戦敗退"))


class AbilityTests(unittest.TestCase):
    def test_overall_uses_config_weights_and_cache(self):
        from game_core.membership import RosterBook

        repo = DataRepository(DATA_ROOT)
        weights = load_screen_config(ROOT / "config")["school_overall_weights"]
        abilities = SchoolAbilities(ROOT / "config", weights)
        book = RosterBook(repo.team, first_year=2026, career_seed=7)
        schools = list(repo.schools)[:2]
        members = {sid: tuple(book.roster(2026, sid).players) for sid in schools}
        abilities.compute(members, 2026, 7)
        values, ready = abilities.get(members, 2026)
        self.assertTrue(ready)
        first = values[schools[0]]
        expected = sum(
            first[name.replace("_strength", "")] * weight
            for name, weight in weights.items()
        )
        self.assertAlmostEqual(expected, first["overall"], delta=0.2)
        # 部員が変わった学校は、計算し直すまで出さない
        changed = {schools[0]: members[schools[0]][1:]}
        self.assertEqual({}, abilities.get(changed, 2026)[0])


class SchoolScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        repo = DataRepository(DATA_ROOT)
        cls.service = LiveGameService(
            repo, DATA_ROOT, save_root=cls.tmp.name, autosave_after_action=False,
        )
        cls.session = cls.service.new_game(
            "schools", rng_seed=20261022, save_initial=False,
        )
        cls.service.advance_through(cls.session, "2026-05-10")
        cls.data = GameScreenData(cls.service, cls.session)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_school_list(self):
        listing = self.data.schools()
        self.assertEqual(3746, len(listing["schools"]))
        # 選手で試合をしないときは能力を出さない
        self.assertEqual("unavailable", listing["abilities_status"])
        played = [row for row in listing["schools"] if row["wins"] + row["losses"]]
        self.assertTrue(played)
        self.assertTrue(all(row["best"] for row in played))
        self.assertTrue({row["ownership"] for row in listing["schools"]} >= {"県立", "私立"})

    def test_school_detail_and_matches(self):
        listing = self.data.schools()["schools"]
        top = max(listing, key=lambda row: row["best_score"])
        detail = self.data.school(top["school_id"])
        self.assertEqual(top["name"], detail["name"])
        self.assertEqual([2026], detail["years"])
        self.assertEqual(top["wins"], detail["yearly"][0]["wins"])
        for kind in ("summer", "spring"):
            koshien = detail["koshien"][kind]
            actual = self.data.actual_koshien.get(top["school_id"], {}).get(kind)
            self.assertEqual(actual, koshien["actual"])
            self.assertEqual(
                (actual or {}).get("appearances", 0) + koshien["game"]["appearances"],
                koshien["total"]["appearances"],
            )
        matches = self.data.school_matches(top["school_id"], 2026)["matches"]
        self.assertEqual(top["wins"], sum(m["won"] for m in matches))
        self.assertEqual(
            sorted(m["match_date"] for m in matches),
            [m["match_date"] for m in matches],
        )
        self.assertFalse([m for m in matches if "_" in m["round_name"]])


if __name__ == "__main__":
    unittest.main()
