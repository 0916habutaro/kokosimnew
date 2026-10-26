"""選手で試合をするゲームの年度の切り替え：名簿はセーブに入り、閉じた年度の名簿は
履歴に書き出して手放す（game_core/roster_book.py）。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from phase2_engine import (
    PLAYER_RESOLVER_CONTRACT,
    DataRepository,
    LiveGameService,
)
from phase2_engine.screen.data import GameScreenData


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


class PlayerCareerYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.service = LiveGameService(
            DataRepository(DATA_ROOT), DATA_ROOT, save_root=cls.tmp.name,
            resolver_contract=PLAYER_RESOLVER_CONTRACT,
            autosave_after_action=False,
        )
        session = cls.service.new_game("year", rng_seed=20261021, save_initial=False)
        # 3月：選抜（2026年度）と春季県大会（2027年度、2026年度の名簿の部員）が重なる
        cls.service.advance_through(session, "2027-03-25")
        cls.service.save_game(session)
        cls.march = cls.service.load_game("year")
        cls.march_rosters = cls.march.state.rosters.years()
        # 4月：春季県大会は3月の部員のまま続く。前の年度の名簿は大会が終わるまで残す
        cls.service.advance_through(cls.march, "2027-04-05")
        cls.april_rosters = cls.march.state.rosters.years()
        cls.service.save_game(cls.march)
        cls.session = cls.service.load_game("year")
        cls.service.advance_through(cls.session, "2027-06-10")
        cls.service.save_game(cls.session)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_previous_roster_is_kept_until_its_competitions_end(self):
        self.assertEqual([2026], self.march_rosters)
        self.assertIn(2026, self.april_rosters)
        rosters = self.session.state.rosters
        self.assertEqual([2027], rosters.years())
        self.assertEqual(2026, rosters.closed_through)

    def test_closed_year_names_come_from_the_history(self):
        archived = self.service.closed_roster("year", 2026, "SCH000001")
        self.assertEqual(20, len(archived))
        screen = GameScreenData(self.service, self.session)
        matches = self.service._history_archive("year").match_index(2026)
        row = next(
            m for m in matches
            if "SCH000001" in (m["team1_id"], m["team2_id"]) and m["team1_score"] is not None
        )
        detail = screen.match(2026, row["competition_id"], row["match_id"])
        names = [b["name"] for rows in detail["batting"].values() for b in rows]
        self.assertTrue(names)
        self.assertTrue(all(" " in name for name in names))

    def test_returning_players_keep_their_name_and_hometown(self):
        archived = {
            row["player_id"]: row
            for row in self.service.closed_roster("year", 2026, "SCH000001")
        }
        now = self.session.state.rosters.roster(2027, "SCH000001").players
        returning = [p for p in now if p.player_id in archived]
        self.assertEqual(12, len(returning))
        for player in returning:
            self.assertEqual(archived[player.player_id]["display_name"], player.display_name)
            self.assertEqual(
                archived[player.player_id]["hometown_prefecture_code"],
                player.hometown_prefecture_code,
            )


if __name__ == "__main__":
    unittest.main()
