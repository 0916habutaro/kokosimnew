"""全国の試合を選手で行うゲーム（resolver contract players_v1）の保存と読込。"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phase2_engine import (
    PLAYER_RESOLVER_CONTRACT,
    DataRepository,
    LiveGameService,
    LiveSeasonGraphPlan,
)
from game_core.roster_book import RosterBook
from phase2_engine.screen.data import GameScreenData
from test_fielding_experience import state_snapshot


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
            before = {}
            build_runtime = LiveSeasonGraphPlan.build_runtime

            def capture(plan, **kwargs):
                state = build_runtime(plan, **kwargs)
                before.update(
                    players=state_snapshot(state.engine.main_match_resolver.ability_generator.source),
                    results=deepcopy(state.completed_results()),
                    details=deepcopy(state.pending_match_details),
                    pitch_log=deepcopy(state.pitch_log),
                    public=deepcopy(state.public_snapshot()),
                )
                return state

            with patch.object(LiveSeasonGraphPlan, 'build_runtime', capture):
                session = service.new_game(
                    "players", rng_seed=20261021, save_initial=False,
                )
            self.assertEqual(date(2026, 4, 1), session.state.current_date)
            book = session.state.rosters
            self.assertGreater(sum(s[3] for rows in before['players'].values() for s in rows.values()), 0)
            self.assertGreater(sum(len(s[5]) for rows in before['players'].values() for s in rows.values()), 0)
            after = state_snapshot(book)
            for sid, rows in before['players'].items():
                for key, values in rows.items():
                    self.assertEqual((*values[:3], 0, 0, values[5]), after[sid][key])
            self.assertEqual(before['results'], session.state.completed_results())
            self.assertEqual(before['details'], session.state.pending_match_details)
            self.assertEqual(before['pitch_log'], session.state.primary.pitch_log)
            self.assertEqual(before['public'], session.state.primary.public_snapshot())
            # 4/1当日にもロードで出場経験を消さない。以後の実出場も同様。
            service.save_game(session)
            with patch.object(RosterBook, 'reset_appearance_counters', side_effect=AssertionError('load reset')):
                same_day = service.load_game('players')
            self.assertEqual(after, state_snapshot(same_day.state.rosters))
            self.assertEqual(len(before['results']), len(service.historical_match_index('players', 2026)))
            for key, detail in before['details'].items():
                saved = service.historical_match('players', 2026, *key.split(':', 1))
                for field in ('batter_stats', 'pitcher_stats', 'team_participation', 'highlights'):
                    self.assertEqual(detail[field], saved[field])
            # 保存後は開始前の試合もA方式履歴に残る。
            self.assertFalse(session.state.pending_match_details)
            # 開始前の試合の球数も数える（球数制限。試合の日 → 球数）
            log = session.state.primary.pitch_log
            self.assertTrue(log)
            self.assertTrue(all(day < "2026-04-01" for days in log.values() for day in days))
            session.state.advance_through("2026-04-04")
            april_players = state_snapshot(book)
            self.assertGreater(sum(s[3] for rows in april_players.values() for s in rows.values()), 0)
            participation_before = {
                key: detail["team_participation"]
                for key, detail in {**before['details'], **session.state.pending_match_details}.items()
            }
            service.save_game(session)
            self.assertEqual({}, session.state.pending_match_details)

            key, row = next(iter(session.state.completed_results().items()))
            competition_id, match_id = key.split(":", 1)
            archived = service.historical_match(
                "players", 2026, competition_id, match_id
            )
            self.assertTrue(archived["batter_stats"])
            self.assertTrue(archived["pitcher_stats"])
            self.assertEqual(participation_before[key], archived["team_participation"])
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

            with patch.object(RosterBook, 'reset_appearance_counters', side_effect=AssertionError('load reset')):
                loaded = service.load_game("players")
            self.assertEqual(april_players, state_snapshot(loaded.state.rosters))
            self.assertEqual(
                archived["team_participation"],
                service.historical_match("players", 2026, competition_id, match_id)["team_participation"],
            )
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


class DHPlayerSaveTests(unittest.TestCase):
    def test_explicit_dh_games_survive_real_service_save_resume_without_duplicate_archive_rows(self):
        from dataclasses import replace
        from game_core.tournament_bridge import AbilityMatchResolver
        import test_stage13e3e2_save_slots_game_service as small
        small.Stage13E3E2SaveSlotsGameServiceTests.setUpClass()
        fixture = small.Stage13E3E2SaveSlotsGameServiceTests()
        original = AbilityMatchResolver.team_input

        def explicit_dh(resolver, **kwargs):
            team = original(resolver, **kwargs)
            if kwargs.get('competition_id') == 'CMP000029':
                team = replace(team, team_strength=resolver.team_generator.generate(team.player_abilities, dh_mode='normal'))
            return team

        with tempfile.TemporaryDirectory() as tmp:
            service = LiveGameService(fixture.repo, DATA_ROOT, save_root=tmp,
                resolver_contract=PLAYER_RESOLVER_CONTRACT, autosave_after_action=False,
                planner_factory=fixture._planner_factory)
            with patch.object(AbilityMatchResolver, 'team_input', explicit_dh):
                session = service.new_game('dh', rng_seed=fixture.seed, start_date='2026-07-01',
                                           injury_level='none', save_initial=False)
                session.state.advance_through('2026-07-12')
                service.save_game(session)
                index = service.historical_match_index('dh', 2026)
                dh_rows = []
                for row in index:
                    saved = service.historical_match('dh', 2026, row['competition_id'], row['match_id'])
                    if any(r.get('starting_designated_hitter_id') for r in saved.get('team_participation', ())):
                        dh_rows.append((row, saved))
                self.assertTrue(dh_rows)
                loaded = service.load_game('dh')
                self.assertEqual(session.state.completed_results(), loaded.state.completed_results())
                service.save_game(loaded)
                self.assertEqual(len(index), len(service.historical_match_index('dh', 2026)))
                row, before = dh_rows[0]
                self.assertEqual(before, service.historical_match('dh', 2026, row['competition_id'], row['match_id']))
                view = GameScreenData(service, loaded).match(2026, row['competition_id'], row['match_id'])
                self.assertTrue(all(lineup.get('pitcher') for lineup in view['lineups'].values()))
                self.assertFalse(loaded.state.pending_match_details)


if __name__ == "__main__":
    unittest.main()
