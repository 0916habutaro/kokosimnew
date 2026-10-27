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
from phase2_engine.screen.data import GameScreenData


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
            # 開始前の試合の球数も数える（球数制限。試合の日 → 球数）
            log = session.state.primary.pitch_log
            self.assertTrue(log)
            self.assertTrue(all(day < "2026-04-01" for days in log.values() for day in days))
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

            # セーブには名簿（選手の名前・出身・能力）が入る。試合の決め方は入れない
            save = Path(tmp) / "players" / "manual.json"
            self.assertLess(save.stat().st_size, 8_000_000)
            self.assertTrue(session.state.rosters.schools(2026))

            loaded = service.load_game("players")
            self.assertEqual(session.state.primary.pitch_log, loaded.state.primary.pitch_log)
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

            # 読み込んでも名簿（選手名・出身・能力）は同じ。画面の部員一覧・試合の個人成績に出る
            screen = GameScreenData(service, session)
            again = GameScreenData(service, loaded)
            school_id = archived["batter_stats"][0]["school_id"]
            members = screen.school(school_id)["members"]
            self.assertEqual(members, again.school(school_id)["members"])
            self.assertEqual(20, len({m["name"] for m in members}))
            self.assertTrue(all(" " in m["name"] and m["hometown"] for m in members))
            self.assertTrue(all("injury" in m for m in members))

            # 怪我の頻度はセーブごとの設定。途中で変えるとセーブに残る
            self.assertEqual("normal", screen.saves()["injury"]["current"])
            screen.set_injury_level("low")
            self.assertEqual("low", service.load_game("players").state.rosters.injury_level)
            with self.assertRaises(ValueError):
                screen.set_injury_level("extreme")
            detail = screen.match(2026, competition_id, match_id)
            batting = [b for rows in detail["batting"].values() for b in rows]
            self.assertTrue(batting)
            self.assertTrue(all(" " in b["name"] for b in batting))


if __name__ == "__main__":
    unittest.main()
