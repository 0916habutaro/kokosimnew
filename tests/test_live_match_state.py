"""架空の選手で、開始配置・継投・打順・記録の本番接続を確かめる。"""
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from game_core.match_contract import MatchSimulationInput, TeamMatchInput, validate_match_simulation_result
from game_core.match_simulator import GameRules, MatchSimulator
from game_core.match_state import TeamMatchState
from game_core.team_strength import STARTING_POSITIONS, TeamStrengthGenerator
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from test_coach_intake import books
from test_coach_tactics import resolver
from test_pitcher_run_accounting import _ScriptedSimulator
from test_stage13b3_team_strength import make_roster_abilities


class ObservedSimulator(_ScriptedSimulator):
    def __init__(self, scripts, changes=()):
        super().__init__(scripts, changes)
        self.states = {}
        self.observations = []

    def _initial_state(self, team, actual_pitcher_id):
        state = super()._initial_state(team, actual_pitcher_id)
        self.states[team.school_id] = state
        return state

    def _event_weights(self, batter, pitcher, defense_strength):
        state = self.states[pitcher.school_id]
        state.validate(actual_pitcher_id=pitcher.player_id)
        self.observations.append((batter.player_id, pitcher.player_id, defense_strength,
                                  state.batting_order, state.defensive_alignment))
        return super()._event_weights(batter, pitcher, defense_strength)


class LiveMatchStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = TeamStrengthGenerator()
        cls.teams = tuple(cls.make_team(sid) for sid in ('FAKE-LIVE-A', 'FAKE-LIVE-B'))

    @classmethod
    def make_team(cls, sid):
        players = tuple(replace(p, player_id=sid + '-' + p.player_id)
                        for p in make_roster_abilities(school_id=sid))
        return TeamMatchInput(sid, cls.generator.generate(players), players)

    def match(self, teams=None, number=0):
        return MatchSimulationInput(f'LIVE-{number}', 'FAKE-LIVE-CUP', 2026, 20261029,
                                    *(teams or self.teams), team_generation_seed=2026100701)

    @staticmethod
    def staff(team):
        return tuple(e.player_id for e in team.team_strength.pitching_staff.entries)

    @staticmethod
    def order(team):
        return tuple(e.player_id for e in sorted(team.team_strength.starting_lineup.entries,
                                                key=lambda e: e.batting_order))

    def play(self, *, top=('home_run',), bottom=(), changes=(), teams=None, **kwargs):
        inp = self.match(teams)
        sim = ObservedSimulator({inp.team2.school_id: top, inp.team1.school_id: bottom}, changes)
        states = {}
        result = sim.simulate(inp, state_sink=states, **kwargs)
        self.assertEqual(sim.states, states)
        validate_match_simulation_result(result, inp)
        for state in states.values():
            self.check_state(state)
        for sid, score in ((inp.team1.school_id, result.team2_score),
                           (inp.team2.school_id, result.team1_score)):
            rows = [p for p in result.pitcher_stats if p.school_id == sid]
            self.assertEqual(score, sum(p.runs_allowed for p in rows))
            self.assertTrue(all(0 <= p.earned_runs <= p.runs_allowed for p in rows))
        return result, sim

    def check_state(self, state):
        state.validate(actual_pitcher_id=state.current_pitcher_id)
        self.assertEqual(9, len(state.active_player_ids))
        self.assertEqual(set(STARTING_POSITIONS), {a.defensive_position for a in state.defensive_alignment})
        self.assertEqual(state.active_player_ids, {a.player_id for a in state.defensive_alignment})
        self.assertFalse(state.active_player_ids & state.exited_player_ids)

    def test_normal_start_has_nine_consistent_players_and_keeps_initial_lineup(self):
        _, sim = self.play()
        for team in self.teams:
            state = sim.states[team.school_id]
            self.assertEqual(team.team_strength.starting_lineup, state.initial_lineup)
            self.assertEqual(self.order(team), tuple(s.player_id for s in state.batting_order))
            self.assertEqual((), state.history)

    def test_pitch_limit_changes_starter_to_bench_without_retiring_planned_pitcher(self):
        team = self.teams[1]
        old, new = self.staff(team)[:2]
        result, sim = self.play(pitch_allowances={old: 60})
        state = sim.states[team.school_id]
        self.assertEqual(new, state.current_pitcher_id)
        self.assertEqual(new, state.player_at_order(self.order(team).index(old) + 1))
        self.assertIn(old, state.bench_player_ids)
        self.assertNotIn(old, state.exited_player_ids)
        self.assertEqual((), state.history)
        self.assertNotIn(old, {s.player_id for s in result.batter_stats})
        self.assertEqual(new, result.events[0].pitcher_id)

    def test_planned_pitcher_can_later_enter_after_pregame_removal(self):
        team = self.teams[1]
        old, new = self.staff(team)[:2]
        _, sim = self.play(pitch_allowances={old: 60}, changes=((new, 1),), regulation_innings=1)
        state = sim.states[team.school_id]
        self.assertEqual(old, state.current_pitcher_id)
        self.assertIn(new, state.exited_player_ids)
        self.assertEqual(1, len(state.history))

    def fielder_allowances(self, team):
        fielder = team.team_strength.starting_lineup.player_for_position('SS')
        return fielder, {p.player_id: (10000 if p.player_id == fielder else 0)
                         for p in team.player_abilities}

    def test_pitch_limit_fielder_start_swaps_positions_before_initialization(self):
        team = self.teams[1]
        new, allowances = self.fielder_allowances(team)
        old = self.staff(team)[0]
        result, sim = self.play(pitch_allowances=allowances)
        state = sim.states[team.school_id]
        self.assertEqual(new, state.current_pitcher_id)
        self.assertEqual(old, state.player_for_position('SS'))
        self.assertEqual(self.order(team), tuple(s.player_id for s in state.batting_order))
        self.assertFalse(state.exited_player_ids)
        self.assertEqual((), state.history)
        self.assertEqual(new, result.events[0].pitcher_id)
        player = next(p for p in team.player_abilities if p.player_id == new)
        self.assertIsNone(player.stuff)
        self.assertEqual(sim.params['pitching_usage']['emergency_pitcher_ability'], sim._as_pitcher(player).stuff)

    def test_bench_relief_inherits_slot_and_retired_pitcher_never_bats_again(self):
        team = self.teams[0]
        old, new = self.staff(team)[:2]
        # 先発投手が一度打ち、守備で交代した後も打順を二巡させる。
        top = ['home_run'] * 8 + ['field_out'] * 12
        result, sim = self.play(top=top, changes=((old, 1),), regulation_innings=4)
        state = sim.states[team.school_id]
        self.assertEqual(new, state.current_pitcher_id)
        self.assertEqual({old}, state.exited_player_ids)
        slot = self.order(team).index(old)
        batters = [e.batter_id for e in result.events if e.offense_school_id == team.school_id]
        self.assertEqual(old, batters[slot])
        self.assertEqual(new, batters[slot + 9])
        self.assertNotIn(old, batters[11:])
        rows = {s.player_id: s for s in result.batter_stats}
        self.assertEqual(1, rows[old].plate_appearances)
        self.assertGreater(rows[new].plate_appearances, 0)
        self.assertEqual((old, new), tuple(p.player_id for p in result.pitcher_stats if p.school_id == team.school_id))
        with self.assertRaises(ValueError):
            state.change_pitcher(old)

    def test_active_fielder_relief_keeps_old_pitcher_in_field_and_batting_order(self):
        team = self.teams[0]
        old = self.staff(team)[0]
        new, allowances = self.fielder_allowances(team)
        allowances[old] = 100  # 先発後、球数到達時のみ緊急の野手へ進む。
        sim = ObservedSimulator({self.teams[1].school_id: ['home_run']}, ())
        sim._pitches = lambda *args: 100
        result = sim.simulate(self.match(), pitch_allowances=allowances)
        state = sim.states[team.school_id]
        self.check_state(state)
        self.assertEqual(new, state.current_pitcher_id)
        self.assertEqual(old, state.player_for_position('SS'))
        self.assertFalse(state.exited_player_ids)
        self.assertEqual(self.order(team), tuple(s.player_id for s in state.batting_order))
        self.assertEqual({old, new}, {p.player_id for p in result.pitcher_stats if p.school_id == team.school_id})
        by_id = {p.player_id: p for p in team.player_abilities}
        expected = self.generator.defense_for_alignment(
            by_id, ((a.defensive_position, a.player_id) for a in state.defensive_alignment))
        later = [o for o in sim.observations if o[1] == new]
        self.assertTrue(later)
        self.assertTrue(all(o[2] == expected for o in later))
        self.assertNotEqual(team.team_strength.defense_strength, expected)

    def test_defense_is_recomputed_once_per_change_and_not_per_plate_appearance(self):
        old = self.staff(self.teams[1])[0]
        sim = ObservedSimulator({self.teams[1].school_id: ['home_run']}, ((old, 1),))
        with patch.object(sim, '_current_defense', wraps=sim._current_defense) as calc:
            result = sim.simulate(self.match())
        self.assertGreater(len(result.events), 30)
        self.assertEqual(1, calc.call_count)

    def test_inherited_runner_keeps_id_and_responsible_pitcher_after_substitution(self):
        old = self.staff(self.teams[1])[0]
        result, _ = self.play(top=['walk', 'triple'], changes=((old, 1),))
        rows = {p.player_id: p for p in result.pitcher_stats}
        self.assertEqual((1, 1), (rows[old].runs_allowed, rows[old].earned_runs))
        first = result.events[0].batter_id
        self.assertIn(first, dict(result.events[1].metadata)['bases_before'])
        self.assertEqual(1, next(s.runs for s in result.batter_stats if s.player_id == first))

    def test_tiebreak_uses_replacement_in_current_batting_slot_and_is_unearned(self):
        team = self.teams[0]
        old, new = self.staff(team)[:2]
        result, _ = self.play(top=['walk'] * 6 + ['field_out'] * 3 + ['home_run'],
                             bottom=['home_run'] * 3 + ['field_out'] * 3,
                             changes=((old, 1),), regulation_innings=1,
                             rules=GameRules(tiebreak_start_inning=2))
        first = next(e for e in result.events if e.inning == 2 and e.half == 'top')
        bases = dict(first.metadata)['bases_before']
        self.assertIn(new, bases)
        self.assertNotIn(old, bases)
        opposition = [p for p in result.pitcher_stats if p.school_id == self.teams[1].school_id]
        self.assertEqual(2, sum(p.runs_allowed - p.earned_runs for p in opposition))

    def test_batting_only_pitching_only_and_both_are_distinguishable(self):
        team = self.teams[1]
        old, new = self.staff(team)[:2]
        result, _ = self.play(changes=((old, 1),))
        batting = {s.player_id for s in result.batter_stats if s.plate_appearances}
        pitching = {s.player_id for s in result.pitcher_stats if s.batters_faced}
        self.assertIn(old, pitching - batting)
        self.assertIn(new, pitching & batting)
        self.assertTrue(batting - pitching)
        self.assertEqual(len(result.batter_stats), len({s.player_id for s in result.batter_stats}))

    def test_no_pitcher_and_exhausted_last_pitcher_are_explicitly_rejected(self):
        unavailable = {p.player_id: 0 for p in self.teams[1].player_abilities}
        sink = {}
        with self.assertRaisesRegex(ValueError, 'no available pitcher'):
            MatchSimulator().simulate(self.match(), pitch_allowances=unavailable, state_sink=sink)
        self.assertFalse(sink)
        last = self.staff(self.teams[1])[0]
        unavailable[last] = 100
        sim = ObservedSimulator({self.teams[1].school_id: ['home_run']}, ())
        sim._pitches = lambda *args: 100
        with self.assertRaisesRegex(ValueError, 'no available relief pitcher'):
            sim.simulate(self.match(), pitch_allowances=unavailable, state_sink=sink)
        self.assertFalse(sink)

    def test_registered_but_unavailable_player_cannot_be_used_by_state_or_emergency(self):
        team = self.teams[1]
        injured = self.staff(team)[1]
        abilities = tuple(p for p in team.player_abilities if p.player_id != injured)
        limited = TeamMatchInput(team.school_id, self.generator.generate(abilities), abilities,
                                 frozenset(p.player_id for p in team.player_abilities))
        result, sim = self.play(teams=(self.teams[0], limited))
        state = sim.states[team.school_id]
        self.assertIn(injured, state.registered_player_ids)
        self.assertNotIn(injured, state.bench_player_ids | state.available_player_ids)
        with self.assertRaises(ValueError):
            state.change_pitcher(injured)
        self.assertNotIn(injured, {e.pitcher_id for e in result.events})

    def test_tournament_registration_survives_injury_filter_and_actual_usage_is_recorded(self):
        f = books()
        bridge = resolver(f, date(2026, 7, 5))
        args = dict(school_id='FAKE-A', reference_year=2026, generation_seed=7, competition_id='FAKE-CUP')
        before = bridge.team_input(**args)
        injured = before.team_strength.starting_lineup.player_for_position('P')
        source = bridge.ability_generator.source
        condition = source.condition
        with patch.object(source, 'condition', side_effect=lambda p, day: (True, 0) if p.player_id == injured else condition(p, day)):
            bridge.clear_cache()
            after = bridge.team_input(**args)
        self.assertIn(injured, after.registered_player_ids)
        self.assertNotIn(injured, {p.player_id for p in after.player_abilities})
        self.assertIs(bridge.team_generator, bridge.simulator._strength_generator())
        # 打撃だけ・登板だけ・両方の出場を重複なく既存の成長・怪我処理へ渡す。
        old = self.staff(self.teams[1])[0]
        result, _ = self.play(changes=((old, 1),))
        members = {t.school_id: SimpleNamespace(players=t.player_abilities) for t in self.teams}
        bridge.member_provider = lambda cid, sid: members[sid]
        with patch.object(source, 'record_games') as record, patch.object(source, 'after_game') as injury:
            bridge._record_pitches(result, date(2026, 7, 5))
            bridge._record_games(result.competition_id, result)
        expected = {s.player_id for s in result.batter_stats if s.plate_appearances} | {s.player_id for s in result.pitcher_stats if s.batters_faced}
        experienced = expected | {pid for team in result.team_participation for pid in team.fielding_player_ids}
        self.assertEqual(experienced, {p.player_id for call in record.call_args_list for p in call.args[1]})
        entries = injury.call_args.args[0]
        self.assertEqual(Counter({pid: 1 for pid in experienced}), Counter(p.player_id for p, *_ in entries))
        for p in result.pitcher_stats:
            self.assertEqual(p.pitches, bridge.season_state.pitch_log[p.player_id]['2026-07-05'])

    def test_walkoff_mercy_and_extra_innings_work_with_live_substitutions(self):
        changes = tuple((self.staff(t)[0], 1) for t in self.teams)
        walkoff, _ = self.play(top=['home_run'], bottom=['home_run', 'field_out', 'field_out', 'field_out', 'home_run'],
                              changes=changes, regulation_innings=1)
        self.assertEqual((2, 'bottom'), (walkoff.last_inning, walkoff.ending_half))
        called, _ = self.play(top=['home_run'] * 10, changes=changes, rules=GameRules(mercy=((5, 10),)))
        self.assertEqual(5, called.last_inning)
        extra, _ = self.play(top=['home_run'], bottom=['home_run', 'field_out', 'field_out', 'field_out', 'home_run'],
                            changes=changes, regulation_innings=1, rules=GameRules(tiebreak_start_inning=2))
        self.assertEqual(2, extra.last_inning)

    def test_archive_reload_and_year_packing_preserve_substitute_stats(self):
        old = self.staff(self.teams[1])[0]
        result, _ = self.play(changes=((old, 1),))
        record = dict(competition_id=result.competition_id, match_id=result.match_id,
                      team1_id=result.team1_school_id, team2_id=result.team2_school_id,
                      winner_id=result.winner_id, loser_id=result.loser_id,
                      team1_score=result.team1_score, team2_score=result.team2_score,
                      score_source=result.score_source, ability_detail=result.to_dict(),
                      match_date='2026-07-05', status='completed')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.sqlite3'
            archive = HistoricalMatchArchive(path)
            archive.sync(year=2026, rng_seed=20261029, resolver_contract='ability_model_v1',
                         plan_fingerprint='fake-live', completed=[record])
            loaded = HistoricalMatchArchive(path).get_match(2026, result.competition_id, result.match_id)
            archive.pack_competition(2026, result.competition_id)
            self.assertEqual(loaded, HistoricalMatchArchive(path).get_match(2026, result.competition_id, result.match_id))
        for key in ('batter_stats', 'pitcher_stats', 'team1_score', 'team2_score', 'inning_scores'):
            self.assertEqual(result.to_dict()[key], loaded[key])
        self.assertNotIn('initial_lineup', result.to_dict())

    def test_real_event_draws_and_all_stats_are_reproducible_with_substitutions(self):
        sim = MatchSimulator()
        sim.params['pitching_usage']['runs_allowed_quick_hook'] = 2
        changed = False
        for number in range(12):
            inp = self.match(number=number)
            first, second = {}, {}
            a = sim.simulate(inp, state_sink=first, rules=GameRules(tiebreak_start_inning=10))
            b = sim.simulate(inp, state_sink=second, rules=GameRules(tiebreak_start_inning=10))
            self.assertEqual(a.to_dict(), b.to_dict())
            self.assertEqual({sid: (s.initial_lineup, s.batting_order, s.history) for sid, s in first.items()},
                             {sid: (s.initial_lineup, s.batting_order, s.history) for sid, s in second.items()})
            changed |= any(s.history for s in first.values())
        self.assertTrue(changed)


if __name__ == '__main__':
    unittest.main()
