"""閉じた年度（前の年度）の大会・試合を見る（game_definition.md §9）。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from phase2_engine import DataRepository, LiveGameService
from phase2_engine.screen.data import GameScreenData


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class ClosedYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        repo = DataRepository(DATA_ROOT)
        cls.service = LiveGameService(
            repo, DATA_ROOT, save_root=cls.tmp.name, autosave_after_action=False,
        )
        cls.session = cls.service.new_game("closed", rng_seed=20261026, save_initial=False)
        cls.service.advance_through(cls.session, "2027-04-05")
        cls.data = GameScreenData(cls.service, cls.session)
        cls.koshien = next(
            cid for cid, row in repo.competitions.items()
            if row.get("competition_type") == "national_championship"
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_closed_year_can_be_chosen(self):
        self.assertNotIn(2026, self.session.state.seasons)
        current = self.data.competitions()
        self.assertEqual(2027, current["school_year"])
        self.assertIn(2026, current["school_years"])
        closed = self.data.competitions(2026)
        rows = closed["competitions"]
        self.assertEqual(162, len(rows))
        self.assertTrue(all(row["status"] == "completed" for row in rows))
        # 大会の表示名（第108回…）も残る
        koshien = next(row for row in rows if row["competition_id"] == self.koshien)
        self.assertIn("108", koshien["name"])

    def test_closed_bracket_entrants_and_matches(self):
        bracket = self.data.bracket(2026, self.koshien)
        self.assertTrue(bracket["main"]["champion_id"] or bracket["main"].get("champion_after_draw"))
        self.assertEqual(49, len(bracket["entrants"]))
        # 夏の代表の地区名（東東京など）も閉じた年度で出る
        self.assertEqual(4, len({
            row["area"] for row in bracket["entrants"] if row["prefecture_code"] in ("01", "13")
        }))
        entrant = self.data.entrant(2026, self.koshien, bracket["entrants"][0]["school_id"])
        self.assertIn("results", entrant)
        # 前の年度の試合（試合の履歴から）
        row = next(
            r for r in self.service.historical_match_index(self.session.slot_id, 2026)
            if r["competition_id"] == self.koshien
        )
        match = self.data.match(2026, self.koshien, row["match_id"])
        self.assertEqual(2026, match["school_year"])
        self.assertEqual((row["team1_id"], row["team2_id"]), (match["team1_id"], match["team2_id"]))
        # 校名の札（夏の代表の地区名）も閉じた年度で出る
        tags = self.data.entry_tags(self.koshien, 2026)
        self.assertEqual(49, len(tags))

if __name__ == "__main__":
    unittest.main()
