"""新規開始前の経験だけを区切り、通常の成長・年度更新へ混入させない。"""
from datetime import date, timedelta
from pathlib import Path
import pickle
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from game_core.injuries import Injury
from game_core.roster_book import RosterBook
from phase2_engine.career_state import CareerState
from phase2_engine.live_game_service import LiveGameService
from test_fielding_experience import make_bridge, short_game, role_ids, state_snapshot
from test_roster_book import TEAMS

ROOT = Path(__file__).resolve().parents[1]


def idle_season(year, day):
    return SimpleNamespace(
        year=year, current_date=day, start_date=date(year, 4, 1),
        calendar_rows={}, annual_templates={}, repo=SimpleNamespace(competitions={}),
        play_today=lambda: [], next_day=lambda: {'played_match_count': 0},
    )


class NewGameExperienceTests(unittest.TestCase):
    def test_boundary_clears_all_existing_states_without_creating_rosters_or_changing_other_data(self):
        book, _ = make_bridge(level='normal')
        for sid in TEAMS:
            book.record_games(sid, book.roster(2026, sid).players)
        player = book.roster(2026, 'SCH-A').players[0]
        injury = Injury(date(2026, 3, 30), 20, 2)
        book.state(player).injuries.append(injury)
        book.grown_through = date(2026, 2, 1)
        book.set_today(date(2026, 4, 1))
        before = state_snapshot(book)
        saved = book.__getstate__()
        # school_idsに載らない、既に作られた選手状態も対象。未生成校は作らない。
        book.school_ids = ('UNGENERATED',)
        with patch.object(book, 'roster', side_effect=AssertionError('roster generation')):
            book.reset_appearance_counters()
        for sid, rows in before.items():
            for key, values in rows.items():
                self.assertEqual((*values[:3], 0, 0, values[5]), state_snapshot(book)[sid][key])
        for field in ('_packed', '_year_end', 'version', 'grown_through', 'today', 'injury_level'):
            self.assertEqual(saved[field], book.__getstate__()[field])
        self.assertEqual(injury, book.injury(player))

    def test_new_game_only_applies_boundary_at_the_initial_april_first(self):
        for day in (date(2026, 4, 1), date(2026, 4, 2), date(2026, 7, 1),
                    date(2027, 4, 1), date(2028, 4, 1)):
            with self.subTest(day=day), tempfile.TemporaryDirectory() as tmp:
                book, _ = make_bridge()
                player = book.roster(2026, 'SCH-A').players[0]
                repo = SimpleNamespace(schools=TEAMS, team=TEAMS.__getitem__, ownership_overrides={})
                service = LiveGameService(repo, ROOT / 'data', save_root=tmp)
                runtime = idle_season(day.year, day)
                def build_runtime(**kwargs):
                    # build_runtime内部の開始前処理を終える前にリセットしてはならない。
                    book.record_games('SCH-A', [player])
                    return runtime
                plan = SimpleNamespace(year=day.year, build_runtime=build_runtime)
                planner = SimpleNamespace(build_plan=lambda: plan)
                with patch.object(service, '_planner', return_value=planner), \
                        patch.object(service, '_engine', return_value=(None, object())), \
                        patch.object(service, '_new_rosters', return_value=book), \
                        patch.object(RosterBook, 'reset_appearance_counters', autospec=True,
                                     side_effect=RosterBook.reset_appearance_counters) as reset:
                    session = service.new_game('start', rng_seed=7, start_date=day.isoformat(), save_initial=False)
                expected = int(day != date(2026, 4, 1))
                self.assertEqual((expected, expected), (book.state(player).games, book.state(player).season_games))
                self.assertEqual(1 - expected, reset.call_count)
                self.assertEqual(day, session.state.current_date)

    def test_april_appearances_and_may_growth_use_only_april_experience_after_save_resume(self):
        book, bridge = make_bridge()
        bridge.season_state.current_date = date(2026, 3, 31)
        result = short_game(bridge)
        bridge._record_pitches(result, bridge.season_state.current_date)
        bridge._record_games(result.competition_id, result)
        self.assertGreater(sum(s[3] for rows in state_snapshot(book).values() for s in rows.values()), 0)
        log = pickle.loads(pickle.dumps(bridge.season_state.pitch_log))
        control, _ = make_bridge()
        book.reset_appearance_counters()
        # 3月の球数ログが4月1日の残り球数へ実際に使われる。
        teams = [bridge.team_input(school_id=sid, reference_year=2026, generation_seed=7,
                                   competition_id=result.competition_id) for sid in TEAMS]
        allowances = bridge._pitch_allowances(teams, date(2026, 4, 1))
        self.assertTrue(log)
        for pid, days in log.items():
            self.assertEqual(max(0, 500 - sum(days.values())), allowances[pid])
        self.assertEqual(state_snapshot(control), state_snapshot(book))
        bridge.season_state.current_date = date(2026, 4, 5)
        result = short_game(bridge, number=1)
        bridge._record_pitches(result, bridge.season_state.current_date)
        bridge._record_games(result.competition_id, result)
        appeared = set.union(*role_ids(result))
        for sid in TEAMS:
            players = book.roster(2026, sid).players
            control.record_games(sid, [p for p in players if p.player_id in appeared])
            for player in players:
                count = int(player.player_id in appeared)
                self.assertEqual((count, count), (book.state(player).games, book.state(player).season_games))
        loaded = pickle.loads(pickle.dumps(book))
        loaded.bind(TEAMS.__getitem__)
        for candidate in (book, loaded, control):
            career = CareerState({2026: idle_season(2026, date(2026, 4, 30))},
                                 current_date=date(2026, 4, 30), rosters=candidate)
            career.next_day()
            self.assertEqual(date(2026, 5, 1), career.current_date)
            self.assertEqual(date(2026, 4, 1), candidate.grown_through)
        self.assertEqual(state_snapshot(control), state_snapshot(book))
        self.assertEqual(state_snapshot(control), state_snapshot(loaded))
        self.assertTrue(all(s[3] == 0 for rows in state_snapshot(book).values() for s in rows.values()))
        self.assertEqual(len(appeared), sum(s[4] for rows in state_snapshot(book).values() for s in rows.values()))

    def test_normal_year_boundaries_still_grow_march_before_resetting_annual_count(self):
        for year in (2027, 2028):
            with self.subTest(year=year):
                book, _ = make_bridge(year=year - 1)
                for sid in TEAMS:
                    book.record_games(sid, book.roster(year - 1, sid).players)
                expected = pickle.loads(pickle.dumps(book))
                expected.bind(TEAMS.__getitem__)
                day = date(year, 3, 31)
                expected.grow(day)
                career = CareerState({year - 1: idle_season(year - 1, day),
                                      year: idle_season(year, day + timedelta(days=1))},
                                     current_date=day, rosters=book)
                with patch.object(book, 'reset_appearance_counters', side_effect=AssertionError('initial reset')), \
                        patch.object(book.growth, 'grow', wraps=book.growth.grow) as grow:
                    career.next_day()
                self.assertTrue(grow.call_args_list)
                self.assertTrue(all(call.kwargs['games'] == 1 for call in grow.call_args_list))
                self.assertEqual(state_snapshot(expected), state_snapshot(book))
                self.assertTrue(all(s[3:5] == (0, 0) for rows in state_snapshot(book).values() for s in rows.values()))


if __name__ == '__main__':
    unittest.main()
