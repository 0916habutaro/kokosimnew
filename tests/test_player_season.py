"""全国の試合を選手で行うゲーム（resolver contract players_v1）の保存と読込。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from phase2_engine import (
    PLAYER_RESOLVER_CONTRACT,
    DataRepository,
    LiveGameService,
)


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


class PlayerSeasonServiceTests(unittest.TestCase):
    def test_box_scores_go_to_history_and_save_stays_small(self):
        repo = DataRepository(DATA_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            service = LiveGameService(
                repo, DATA_ROOT, save_root=tmp,
                resolver_contract=PLAYER_RESOLVER_CONTRACT,
                autosave_after_action=False,
            )
            session = service.new_game(
                "players", rng_seed=20261021, save_initial=False,
            )
            # 開始前（3月）の試合の記録は、まだ履歴に保存していない
            self.assertTrue(session.state.pending_match_details)
            session.state.advance_through("2026-04-04")
            service.save_game(session)
            self.assertEqual({}, session.state.pending_match_details)

            key, row = next(iter(session.state.completed_results().items()))
            competition_id, match_id = key.split(":", 1)
            archived = service.historical_match(
                "players", 2026, competition_id, match_id
            )
            self.assertTrue(archived["batter_stats"])
            self.assertTrue(archived["pitcher_stats"])
            # 試合経過の要点は履歴に残り、セーブには残らない
            self.assertIsInstance(archived["highlights"], list)
            self.assertTrue(any(
                service.historical_match(
                    "players", 2026, *key.split(":", 1)
                )["highlights"]
                for key in session.state.completed_results()
            ))

            # セーブには試合の決め方や名簿を入れない
            save = Path(tmp) / "players" / "manual.json"
            self.assertLess(save.stat().st_size, 5_000_000)

            loaded = service.load_game("players")
            self.assertEqual(
                session.state.completed_results(),
                loaded.state.completed_results(),
            )
            session.state.advance_through("2026-04-06")
            loaded.state.advance_through("2026-04-06")
            self.assertEqual(
                session.state.completed_results(),
                loaded.state.completed_results(),
            )
            service.save_game(loaded)


if __name__ == "__main__":
    unittest.main()
