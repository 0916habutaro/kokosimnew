"""架空の選手で、開始配置・継投・打順・記録の本番接続を確かめる。"""
from collections import Counter
from dataclasses import fields, replace
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


class DHSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = TeamStrengthGenerator()
        cls.by_mode = {}
        for mode in ('none', 'normal', 'pitcher'):
            teams = []
            for sid in ('FAKE-DH-SIM-A', 'FAKE-DH-SIM-B'):
                players = tuple(replace(p, player_id=sid+'-'+p.player_id)
                                for p in make_roster_abilities(school_id=sid))
                strength = cls.generator.generate(players, dh_mode=mode)
                if mode != 'none':
                    # 第1打席と通知時点を固定する。能力・守備は生成結果のまま。
                    lineup = strength.starting_lineup
                    ordered = sorted(lineup.entries, key=lambda e: (e.player_id != lineup.designated_hitter_id, e.batting_order))
                    slots = {e.player_id: i for i, e in enumerate(ordered, 1)}
                    lineup = replace(lineup, entries=tuple(replace(e, batting_order=slots[e.player_id]) for e in lineup.entries))
                    strength = replace(strength, starting_lineup=lineup)
                teams.append(TeamMatchInput(sid, strength, players))
            cls.by_mode[mode] = tuple(teams)

    def match(self, mode='normal', teams=None):
        return MatchSimulationInput('FAKE-DH-FIXED', 'FAKE-DH-CUP', 2026, 20261022,
                                    *(teams or self.by_mode[mode]), team_generation_seed=2026100701)

    def play(self, mode='normal', *, teams=None, top=('home_run',), bottom=(), changes=(), **kwargs):
        inp = self.match(mode, teams)
        sim = _ScriptedSimulator({inp.team2.school_id: top, inp.team1.school_id: bottom}, changes)
        states = {}
        result = sim.simulate(inp, regulation_innings=kwargs.pop('regulation_innings', 1), state_sink=states, **kwargs)
        self.check_result(inp, result, states)
        return inp, result, states

    def check_result(self, inp, result, states):
        import json
        from game_core.match_state import replay_team_participation, TeamMatchParticipation
        validate_match_simulation_result(result, inp, final_states=states)
        for record in result.team_participation:
            restored = replay_team_participation(TeamMatchParticipation.from_dict(json.loads(json.dumps(record.to_dict()))), 2026)
            actual = states[record.school_id]
            self.assertEqual(actual.participation(), restored.participation())
            self.assertEqual(actual.retired_two_way_roles, restored.retired_two_way_roles)
            self.assertEqual(actual.exited_player_ids, restored.exited_player_ids)
            self.assertEqual(actual.dh_batting_required, restored.dh_batting_required)
            self.assertEqual(actual.to_dict(), TeamMatchState.from_dict(json.loads(json.dumps(actual.to_dict()))).to_dict())
        for sid in states:
            participants = ({r.player_id for r in result.batter_stats if r.school_id == sid and r.plate_appearances}
                            | {r.player_id for r in result.pitcher_stats if r.school_id == sid and r.batters_faced}
                            | set(states[sid].fielding_player_ids))
            self.assertTrue(participants <= states[sid].registered_player_ids)
            self.assertEqual(len({r.player_id for r in result.batter_stats if r.school_id == sid}),
                             len([r for r in result.batter_stats if r.school_id == sid]))

    def test_three_modes_reject_batter_stats_inconsistent_with_actual_events(self):
        for mode in ('none', 'normal', 'pitcher'):
            inp, result, _ = self.play(mode)
            hitter = next(row for row in result.batter_stats if row.home_runs)
            out = next(row for row in result.batter_stats if row.at_bats and not row.hits)
            cases = (
                (hitter, dict(home_runs=0, doubles=1)),
                (hitter, dict(rbi=0)),
                (hitter, dict(strikeouts=1)),
                (out, dict(at_bats=out.at_bats-1, walks=out.walks+1)),
                (hitter, dict(stolen_bases=1)),
                (hitter, dict(caught_stealing=1)),
            )
            for target, values in cases:
                with self.subTest(mode=mode, fields=values):
                    corrupted = replace(result, batter_stats=tuple(
                        replace(row, **values) if row == target else row for row in result.batter_stats))
                    with self.assertRaises(ValueError):
                        validate_match_simulation_result(corrupted, inp)

    def test_three_modes_reject_pitcher_stats_inconsistent_with_actual_events(self):
        for mode in ('none', 'normal', 'pitcher'):
            inp, result, _ = self.play(mode)
            target = next(row for row in result.pitcher_stats if row.hits_allowed)
            for values in (dict(outs_recorded=target.outs_recorded+1), dict(home_runs_allowed=0),
                           dict(strikeouts=1), dict(walks=1)):
                with self.subTest(mode=mode, fields=values):
                    corrupted = replace(result, pitcher_stats=tuple(
                        replace(row, **values) if row == target else row for row in result.pitcher_stats))
                    with self.assertRaises(ValueError):
                        validate_match_simulation_result(corrupted, inp)

    def test_unchanged_team_totals_do_not_hide_swapped_individual_batting_stats(self):
        for mode in ('none', 'normal', 'pitcher'):
            with self.subTest(mode=mode):
                inp, result, _ = self.play(mode)
                hitter = next(row for row in result.batter_stats if row.home_runs)
                out = next(row for row in result.batter_stats
                           if row.school_id == hitter.school_id and row.at_bats and not row.hits)
                sources = {hitter.player_id: out, out.player_id: hitter}
                swapped = tuple(replace(row, **{
                    f.name: getattr(sources[row.player_id], f.name) for f in fields(row)
                    if f.name not in ('player_id', 'school_id')}) if row.player_id in sources else row
                    for row in result.batter_stats)
                for f in fields(hitter):
                    if f.name not in ('player_id', 'school_id'):
                        self.assertEqual(sum(getattr(row, f.name) for row in result.batter_stats),
                                         sum(getattr(row, f.name) for row in swapped))
                with self.assertRaises(ValueError):
                    validate_match_simulation_result(replace(result, batter_stats=swapped), inp)

    def test_every_plate_appearance_has_one_available_defender_per_position_including_bunts(self):
        owner = self

        class EveryPlay(ObservedSimulator):
            def __init__(self, scripts, changes):
                super().__init__(scripts, changes)
                self.frames = []
                self.bunted = False

            def _should_sacrifice_bunt(self, batter, bases, outs, margin, rng):
                if not self.bunted and bases[0] and not bases[2] and outs < 2:
                    self.bunted = True
                    return True
                return False

            def _apply_event(self, **kwargs):
                offense = kwargs['offense_players'][kwargs['batter_id']].school_id
                defense = next(sid for sid in self.states if sid != offense)
                for state in self.states.values():
                    alignment = state.defensive_alignment
                    owner.assertEqual(STARTING_POSITIONS, tuple(a.defensive_position for a in alignment))
                    ids = {a.player_id for a in alignment}
                    owner.assertEqual(9, len(ids))
                    owner.assertTrue(ids <= state.registered_player_ids & state.available_player_ids)
                    owner.assertFalse(state.active_player_ids & state.exited_player_ids)
                self.frames.append((kwargs['batter_id'], self.states[defense].current_pitcher_id))
                return super()._apply_event(**kwargs)

        for mode in ('none', 'normal', 'pitcher'):
            with self.subTest(mode=mode):
                inp = self.match(mode)
                changes = tuple((t.team_strength.starting_lineup.player_for_position('P'), 1)
                                for t in (inp.team1, inp.team2))
                sim = EveryPlay({inp.team2.school_id: ('walk', 'home_run')}, changes)
                result = sim.simulate(inp, regulation_innings=1)
                self.assertTrue(sim.bunted)
                self.assertTrue(any(e.event_type == 'sacrifice_bunt' for e in result.events))
                self.assertEqual([(e.batter_id, e.pitcher_id) for e in result.events], sim.frames)
                validate_match_simulation_result(result, inp)

    def test_non_home_run_walkoff_records_only_winning_run_and_credited_hit(self):
        for mode in ('none', 'normal', 'pitcher'):
            for hit in ('double', 'triple'):
                with self.subTest(mode=mode, hit=hit):
                    _, result, _ = self.play(mode, top=(), bottom=('walk', 'walk', 'walk', hit))
                    event = result.events[-1]
                    self.assertEqual((0, 1), (result.team1_score, result.team2_score))
                    self.assertEqual(('single', 1, 1), (event.event_type, event.runs_scored, event.rbi))
                    batter = next(b for b in result.batter_stats if b.player_id == event.batter_id)
                    self.assertEqual((1, 0, 0), (batter.hits, batter.doubles, batter.triples))
                    self.assertEqual(1, sum(p.runs_allowed for p in result.pitcher_stats))

    def test_walkoff_hit_credit_depends_on_winning_runners_original_base(self):
        for mode in ('none', 'normal', 'pitcher'):
            for script, score, credit in (
                (('double', 'triple'), 1, 'double'),
                (('walk', 'triple'), 1, 'triple'),
                (('walk', 'walk', 'walk', 'triple'), 2, 'double'),
            ):
                top = ('home_run',) if score == 2 else ()
                with self.subTest(mode=mode, script=script, top=top):
                    _, result, _ = self.play(mode, top=top, bottom=script)
                    event = result.events[-1]
                    self.assertEqual(score, result.team2_score)
                    self.assertEqual(credit, event.event_type)
                    self.assertEqual(score, event.runs_scored)

    def test_walkoff_home_run_keeps_all_runs_and_bases(self):
        for mode in ('none', 'normal', 'pitcher'):
            with self.subTest(mode=mode):
                _, result, _ = self.play(mode, top=(), bottom=('walk', 'walk', 'walk', 'home_run'))
                event = result.events[-1]
                self.assertEqual((0, 4), (result.team1_score, result.team2_score))
                self.assertEqual(('home_run', 4, 4), (event.event_type, event.runs_scored, event.rbi))

    def test_walkoff_hit_credit_does_not_shorten_error_free_hit_for_earned_runs(self):
        for mode in ('none', 'normal', 'pitcher'):
            with self.subTest(mode=mode):
                _, result, _ = self.play(mode, top=(),
                    bottom=('single','reached_on_error','sacrifice_bunt','triple'))
                event = result.events[-1]
                self.assertEqual((0, 1), (result.team1_score, result.team2_score))
                self.assertEqual('single', event.event_type)
                self.assertEqual('triple', dict(event.metadata)['walkoff_hit'])
                # 失策がなくても、二塁にいるはずの先頭打者は元の三塁打で生還する。
                self.assertEqual(1, sum(p.earned_runs for p in result.pitcher_stats))

    def test_tiebreak_walkoff_records_only_automatic_winning_runner_as_unearned(self):
        for mode in ('none', 'normal', 'pitcher'):
            with self.subTest(mode=mode):
                _, result, _ = self.play(mode, top=(), bottom=('field_out',)*3+('triple',),
                                         rules=GameRules(tiebreak_start_inning=2))
                self.assertEqual((0, 1), (result.team1_score, result.team2_score))
                event = result.events[-1]
                self.assertEqual((2, 'double', 1), (event.inning, event.event_type, event.runs_scored))
                self.assertEqual(0, sum(p.earned_runs for p in result.pitcher_stats))

    def test_walkoff_hit_credit_keeps_pitch_count_from_drawn_event(self):
        for mode in ('none', 'normal', 'pitcher'):
            with self.subTest(mode=mode):
                inp = self.match(mode)
                sim = _ScriptedSimulator({inp.team1.school_id: ('walk','walk','walk','triple')})
                for key in sim.params['pitch_count']['by_event']:
                    sim.params['pitch_count']['by_event'][key] = [1, 0]
                sim.params['pitch_count']['by_event']['triple'] = [7, 0]
                result = sim.simulate(inp, regulation_innings=1)
                self.assertEqual('single', result.events[-1].event_type)
                self.assertEqual(10, sum(p.pitches for p in result.pitcher_stats
                                         if p.school_id == inp.team1.school_id))

    def test_strict_validation_rejects_scoring_after_the_winning_non_home_run(self):
        class UnfinishedWalkoff(_ScriptedSimulator):
            @staticmethod
            def _finish_walkoff(event_type, batter_id, before, bases, scored, rbi, needed):
                return event_type, scored, rbi

        for mode in ('none', 'normal', 'pitcher'):
            with self.subTest(mode=mode):
                inp = self.match(mode)
                sim = UnfinishedWalkoff({inp.team1.school_id: ('walk','walk','walk','triple')})
                with self.assertRaisesRegex(ValueError, 'non-home-run walkoff score'):
                    sim.simulate(inp, regulation_innings=1)

    def test_walkoff_terminal_bases_conserve_runners_and_their_order(self):
        team = self.by_mode['none'][0]
        players = {p.player_id: p for p in team.player_abilities}
        ids = [e.player_id for e in team.team_strength.starting_lineup.entries]
        sim = MatchSimulator()
        for mask in range(1, 8):
            before = [ids[i] if mask & (1 << i) else None for i in range(3)]
            for event in ('single', 'double', 'triple', 'reached_on_error'):
                for draw in (0.0, 0.999):
                    bases = list(before)
                    scored, _, rbi = sim._apply_event(event_type=event, batter_id=ids[3], bases=bases,
                        offense_players=players, defense_strength=50,
                        rng=SimpleNamespace(random=lambda: draw))
                    for needed in range(1, len(scored)+1):
                        with self.subTest(mask=mask, event=event, draw=draw, needed=needed):
                            terminal = list(bases)
                            kind, runs, credit = sim._finish_walkoff(
                                event, ids[3], before, terminal, scored, rbi, needed)
                            self.assertEqual(needed, len(runs))
                            self.assertEqual(Counter([p for p in before if p]+[ids[3]]),
                                             Counter([p for p in terminal if p]+runs))
                            self.assertEqual(3-len(set(terminal)-{None}), terminal.count(None))
                            retained = [p for p in before if p and p not in runs]
                            self.assertEqual(retained, [p for p in terminal if p in retained])
                            self.assertTrue(all(terminal.index(p) >= before.index(p) for p in retained))
                            self.assertLessEqual(credit, needed)

    def test_ordinary_hits_before_final_inning_keep_all_runs_and_hit_credit(self):
        for mode in ('none', 'normal', 'pitcher'):
            with self.subTest(mode=mode):
                _, result, _ = self.play(mode, top=(), bottom=('walk','walk','walk','triple'),
                                         regulation_innings=2)
                hit = next(e for e in result.events if e.event_type == 'triple')
                self.assertEqual((1, 3, 3), (hit.inning, hit.runs_scored, hit.rbi))
                self.assertEqual((0, 3), (result.team1_score, result.team2_score))

    def test_three_modes_use_nine_batters_and_independent_defense(self):
        for mode, count in (('none', 9), ('normal', 10), ('pitcher', 9)):
            with self.subTest(mode=mode):
                _, result, states = self.play(mode)
                for record in result.team_participation:
                    state = states[record.school_id]
                    self.assertEqual(count, len(state.active_player_ids))
                    self.assertEqual(9, len(state.batting_order))
                    self.assertEqual(9, len(state.defensive_alignment))
                    participants = ({b.player_id for b in result.batter_stats
                                     if b.school_id == record.school_id and b.plate_appearances}
                                    | {p.player_id for p in result.pitcher_stats
                                       if p.school_id == record.school_id and p.batters_faced}
                                    | set(state.fielding_player_ids))
                    self.assertEqual(count, len(participants))
                    if mode == 'normal':
                        self.assertNotIn(record.starting_pitcher_id, {b.player_id for b in state.batting_order})
                        self.assertNotIn(record.starting_designated_hitter_id, state.fielding_player_ids)
                        self.assertNotIn(record.starting_pitcher_id, {b.player_id for b in result.batter_stats})
                    elif mode == 'pitcher':
                        self.assertEqual(record.starting_pitcher_id, record.starting_designated_hitter_id)
                        self.assertTrue(any(b.player_id == record.starting_pitcher_id and b.plate_appearances for b in result.batter_stats))

    def test_normal_dh_multiple_relief_changes_do_not_change_batting_order(self):
        team = self.by_mode['normal'][1]
        staff = MatchSimulator._pitcher_order(team)
        _, result, states = self.play(changes=((staff[0], 1), (staff[1], 1)))
        state = states[team.school_id]
        self.assertEqual(3, len([p for p in result.pitcher_stats if p.school_id == team.school_id]))
        self.assertEqual(tuple(e.player_id for e in sorted(state.initial_lineup.entries, key=lambda e:e.batting_order)),
                         tuple(b.player_id for b in state.batting_order))
        self.assertEqual(state.initial_lineup.designated_hitter_id, state.designated_hitter_id)

    def test_two_way_pitcher_role_ends_before_own_first_batting_obligation(self):
        team = self.by_mode['pitcher'][1]
        starter = team.team_strength.starting_lineup.designated_hitter_id
        _, result, states = self.play('pitcher', changes=((starter, 1),))
        state = states[team.school_id]
        self.assertEqual(starter, state.designated_hitter_id)
        self.assertNotIn(starter, state.exited_player_ids)
        self.assertEqual({'pitcher'}, state.retired_two_way_roles)
        self.assertTrue(any(b.player_id == starter and b.plate_appearances for b in result.batter_stats))
        self.assertTrue(any(c.kind == 'dh_plate_appearance' for c in state.history))
        self.assertFalse(any(c.kind == 'dh_opponent_pitcher' for c in state.history))

    def test_opponent_starter_notification_only_waives_opponents_duty(self):
        teams = list(self.by_mode['normal'])
        lineup = teams[0].team_strength.starting_lineup
        # 先攻DHを9番にして、相手先発交代時点では未打席にする。
        entries = tuple(replace(e, batting_order=9 if e.batting_order == 1 else e.batting_order-1) for e in lineup.entries)
        teams[0] = replace(teams[0], team_strength=replace(teams[0].team_strength, starting_lineup=replace(lineup, entries=entries)))
        starter = teams[1].team_strength.starting_lineup.player_for_position('P')
        _, _, states = self.play(teams=teams, changes=((starter, 1),))
        self.assertEqual(['dh_opponent_pitcher'], [c.kind for c in states[teams[0].school_id].history])
        own = states[teams[1].school_id]
        self.assertTrue(any(c.kind == 'dh_plate_appearance' for c in own.history))
        self.assertFalse(any(c.kind == 'dh_opponent_pitcher' for c in own.history))

    def test_two_way_dh_role_can_end_while_pitcher_continues(self):
        from game_core.match_simulator import LineupAdjustment
        team = self.by_mode['pitcher'][0]
        lineup = team.team_strength.starting_lineup
        bench = next(p.player_id for p in team.player_abilities if p.player_id not in lineup.starter_ids)
        _, result, states = self.play('pitcher', lineup_changes=(LineupAdjustment(2, team.school_id, ((1, bench),)),))
        state = states[team.school_id]
        self.assertEqual(lineup.designated_hitter_id, state.current_pitcher_id)
        self.assertEqual(bench, state.designated_hitter_id)
        self.assertEqual({'batter'}, state.retired_two_way_roles)
        self.assertTrue(any(p.player_id == state.current_pitcher_id and p.batters_faced for p in result.pitcher_stats))

    def test_dh_pinch_runner_inherits_base_and_scores_without_changing_pitcher_liability(self):
        from game_core.match_simulator import LineupAdjustment
        for mode in ('normal', 'pitcher'):
            for event_type, earned in (('walk', 2), ('reached_on_error', 1)):
                with self.subTest(mode=mode, event_type=event_type):
                    team = self.by_mode[mode][0]
                    lineup = team.team_strength.starting_lineup
                    dh = lineup.designated_hitter_id
                    bench = next(p.player_id for p in team.player_abilities if p.player_id not in lineup.starter_ids)
                    opposing_starter = self.by_mode[mode][1].team_strength.starting_lineup.player_for_position('P')
                    plan = LineupAdjustment(2, team.school_id, ((1, bench),))
                    inp, result, states = self.play(mode, top=(event_type, 'home_run'),
                                                  changes=((opposing_starter, 1),), lineup_changes=(plan,))
                    rows = {b.player_id: b for b in result.batter_stats}
                    self.assertEqual(0, rows[dh].runs)
                    self.assertEqual((0, 1), (rows[bench].plate_appearances, rows[bench].runs))
                    self.assertEqual(bench, dict(result.events[1].metadata)['bases_before'].split('|')[0])
                    old = next(p for p in result.pitcher_stats if p.player_id == opposing_starter)
                    self.assertEqual(1, old.runs_allowed)
                    self.assertEqual(earned, sum(p.earned_runs for p in result.pitcher_stats))
                    event = result.events[1]
                    metadata = dict(event.metadata)
                    metadata['bases_before'] = metadata['bases_before'].replace(bench, dh)
                    events = (result.events[0], replace(event, metadata=tuple(metadata.items())), *result.events[2:])
                    with self.assertRaisesRegex(ValueError, 'base runners'):
                        validate_match_simulation_result(replace(result, events=events), inp)
                    if mode == 'pitcher':
                        self.assertEqual(dh, states[team.school_id].current_pitcher_id)

    def test_first_batting_obligation_rejects_early_dh_substitute(self):
        from game_core.match_simulator import LineupAdjustment
        team = self.by_mode['pitcher'][1]
        bench = next(p.player_id for p in team.player_abilities if p.player_id not in team.team_strength.starting_lineup.starter_ids)
        with self.assertRaisesRegex(ValueError, 'complete the first plate appearance'):
            self.play('pitcher', lineup_changes=(LineupAdjustment(2, team.school_id, ((1, bench),)),))

    def test_retired_two_way_roles_and_full_exit_cannot_reenter_in_simulation(self):
        from game_core.match_simulator import LineupAdjustment
        team = self.by_mode['pitcher'][0]
        lineup = team.team_strength.starting_lineup
        starter = lineup.designated_hitter_id
        bench = [p.player_id for p in team.player_abilities if p.player_id not in lineup.starter_ids]
        rp = next(pid for pid in MatchSimulator._pitcher_order(team) if pid in bench)
        batter = next(pid for pid in bench if pid != rp)
        cases = (
            (LineupAdjustment(2, team.school_id, defensive_changes=(('P', rp),)),
             LineupAdjustment(3, team.school_id, defensive_changes=(('P', starter),))),
            (LineupAdjustment(2, team.school_id, ((1, batter),)),
             LineupAdjustment(3, team.school_id, ((1, starter),))),
            (LineupAdjustment(2, team.school_id, ((1, batter),), (('P', rp),)),
             LineupAdjustment(3, team.school_id, ((1, starter),))),
        )
        for plan in cases:
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                self.play('pitcher', lineup_changes=plan)

    def test_umpire_approved_medical_exception_allows_unfinished_dh_substitution(self):
        from game_core.match_simulator import LineupAdjustment
        team = self.by_mode['pitcher'][1]
        lineup = team.team_strength.starting_lineup
        bench = next(p.player_id for p in team.player_abilities if p.player_id not in lineup.starter_ids)
        plan = LineupAdjustment(2, team.school_id, ((1, bench),), medical_exception='injury', umpire_approved=True)
        _, _, states = self.play('pitcher', lineup_changes=(plan,))
        self.assertEqual(bench, states[team.school_id].designated_hitter_id)

    def test_dh_loss_double_switch_and_later_relief_inherit_pitcher_batting_slot(self):
        from game_core.match_simulator import LineupAdjustment
        team = self.by_mode['normal'][0]
        lineup = team.team_strength.starting_lineup
        bench = [p.player_id for p in team.player_abilities if p.player_id not in lineup.starter_ids]
        cf_slot = next(e.batting_order for e in lineup.entries if e.defensive_position == 'CF')
        rp = next(pid for pid in MatchSimulator._pitcher_order(team) if pid in bench)
        batter = next(pid for pid in bench if pid != rp)
        plan = LineupAdjustment(2, team.school_id, ((1, batter), (cf_slot, rp)), (('CF', batter), ('P', rp)))
        _, _, states = self.play(lineup_changes=(plan,), changes=((rp, 1),))
        state = states[team.school_id]
        self.assertIsNone(state.designated_hitter_id)
        self.assertEqual(state.current_pitcher_id, state.player_at_order(cf_slot))
        self.assertEqual({b.player_id for b in state.batting_order}, {a.player_id for a in state.defensive_alignment})

    def test_pitch_limit_resolves_actual_starter_before_dh_declaration(self):
        for mode in ('normal', 'pitcher'):
            team = self.by_mode[mode][1]
            old = team.team_strength.starting_lineup.player_for_position('P')
            _, result, states = self.play(mode, pitch_allowances={old: 0})
            record = result.team_participation[1]
            self.assertNotEqual(old, record.starting_pitcher_id)
            self.assertEqual(record.starting_pitcher_id, result.events[0].pitcher_id)
            self.assertEqual(mode == 'pitcher', record.starting_pitcher_id == record.starting_designated_hitter_id)
            self.assertFalse(states[team.school_id].exited_player_ids)

    def test_emergency_fielder_can_start_in_both_dh_modes(self):
        for mode in ('normal', 'pitcher'):
            team = self.by_mode[mode][1]
            fielder = team.team_strength.starting_lineup.player_for_position('SS')
            allowances = {p.player_id: 500 if p.player_id == fielder else 0 for p in team.player_abilities}
            _, result, _ = self.play(mode, pitch_allowances=allowances)
            record = result.team_participation[1]
            self.assertEqual(fielder, record.starting_pitcher_id)
            self.assertEqual(mode == 'pitcher', fielder == record.starting_designated_hitter_id)

    def test_pitch_limit_forces_fielder_relief_and_dh_loss(self):
        team = self.by_mode['normal'][1]
        lineup = team.team_strength.starting_lineup
        starter = lineup.player_for_position('P')
        fielder = lineup.player_for_position('SS')
        allowances = {p.player_id: 0 for p in team.player_abilities}
        allowances.update({starter: 100, fielder: 500})
        with patch.object(_ScriptedSimulator, '_pitches', return_value=50):
            _, result, states = self.play(pitch_allowances=allowances)
        state = states[team.school_id]
        self.assertIsNone(state.designated_hitter_id)
        self.assertEqual(fielder, state.current_pitcher_id)
        self.assertEqual(lineup.designated_hitter_id, state.player_for_position('SS'))
        self.assertTrue(all(p.pitches <= allowances.get(p.player_id, 500) for p in result.pitcher_stats))

    def test_pitch_limit_with_no_remaining_pitcher_fails_clearly(self):
        team = self.by_mode['normal'][1]
        allowances = {p.player_id: 0 for p in team.player_abilities}
        allowances[team.team_strength.starting_lineup.player_for_position('P')] = 100
        with patch.object(_ScriptedSimulator, '_pitches', return_value=100):
            with self.assertRaisesRegex(ValueError, 'no available relief pitcher'):
                self.play(pitch_allowances=allowances)

    def test_explicit_fielder_pitching_does_not_discard_unused_relief_pitchers(self):
        from game_core.match_simulator import LineupAdjustment
        team = self.by_mode['normal'][1]
        lineup = team.team_strength.starting_lineup
        fielder = lineup.player_for_position('SS')
        # 先発DHを空いたSSへ回す。野手Pは既定の投手陣順には入っていない。
        plan = LineupAdjustment(2, team.school_id, defensive_changes=(('P', fielder), ('SS', lineup.designated_hitter_id)))
        _, result, states = self.play(lineup_changes=(plan,), changes=((fielder, 1),))
        state = states[team.school_id]
        self.assertNotEqual(fielder, state.current_pitcher_id)
        self.assertEqual(3, len([p for p in result.pitcher_stats if p.school_id == team.school_id and p.batters_faced]))

    def test_last_walkoff_plate_appearance_has_completion_without_fictional_next_pa(self):
        from game_core.match_state import CompletedPlateAppearanceMoment
        _, result, states = self.play(top=(), bottom=('home_run',))
        state = states[result.team2_school_id]
        completion = next(c for c in state.history if c.kind == 'dh_plate_appearance')
        self.assertIsInstance(completion.moment, CompletedPlateAppearanceMoment)
        self.assertEqual(len(result.events), completion.moment.completed_plate_appearance_no)
        self.assertEqual('bottom', completion.moment.half)

    def test_tiebreak_uses_actual_dh_batting_order(self):
        _, result, states = self.play(top=('field_out',)*3+('home_run',),
                                      regulation_innings=1, rules=GameRules(tiebreak_start_inning=2))
        event = next(e for e in result.events if e.inning == 2)
        state = states[event.offense_school_id]
        self.assertEqual('|'.join((state.player_at_order(3), state.player_at_order(2), '')), dict(event.metadata)['bases_before'])
        self.assertEqual(3, event.runs_scored)
        self.assertEqual(1, sum(p.earned_runs for p in result.pitcher_stats))

    def test_tiebreak_runners_reflect_substitution_before_first_extra_inning_batter(self):
        from game_core.match_simulator import LineupAdjustment
        team = self.by_mode['normal'][0]
        lineup = team.team_strength.starting_lineup
        second = next(e for e in lineup.entries if e.batting_order == 2)
        bench = next(p.player_id for p in team.player_abilities if p.player_id not in lineup.starter_ids)
        plan = LineupAdjustment(7, team.school_id, ((2, bench),), ((second.defensive_position, bench),))
        _, result, _ = self.play(top=('field_out',)*3+('home_run',), lineup_changes=(plan,),
                                  rules=GameRules(tiebreak_start_inning=2))
        event = next(e for e in result.events if e.inning == 2)
        self.assertEqual(bench, dict(event.metadata)['bases_before'].split('|')[1])

    def test_dh_relief_preserves_inherited_runs_and_earned_runs(self):
        for mode in ('normal', 'pitcher'):
            starter = self.by_mode[mode][1].team_strength.starting_lineup.player_for_position('P')
            _, result, _ = self.play(mode, top=('walk', 'walk', 'home_run'), changes=((starter, 1),))
            row = next(p for p in result.pitcher_stats if p.player_id == starter)
            self.assertEqual((1, 1), (row.runs_allowed, row.earned_runs))
            self.assertEqual(3, sum(p.runs_allowed for p in result.pitcher_stats))

    def test_cold_game_and_skipped_bottom_have_valid_notifications(self):
        _, result, _ = self.play(top=(), bottom=('home_run',), regulation_innings=9, rules=GameRules(mercy=((2, 1),)))
        self.assertEqual('top', result.ending_half)
        self.assertFalse(result.inning_scores[-1].was_played)

    def test_all_three_modes_are_deterministic_with_real_probability_model(self):
        for mode in self.by_mode:
            inp = self.match(mode)
            sim = MatchSimulator()
            self.assertEqual(sim.simulate(inp).to_dict(), sim.simulate(inp).to_dict())

    def test_selection_uses_best_available_dh_batting_and_two_way_pitcher(self):
        players = self.by_mode['normal'][0].player_abilities
        target = next(p for p in players if p.primary_position == 'P')
        target = replace(target, contact=100, power=100, plate_discipline=100, strikeout_resistance=100,
                         stuff=1, control=1, stamina=1, strikeout=1)
        players = tuple(target if p.player_id == target.player_id else p for p in players)
        normal = self.generator.select_starting_lineup(players, dh_mode='normal')
        defense = {a.player_id for a in normal.defense}
        self.assertNotIn(target.player_id, defense)
        self.assertEqual(target.player_id, normal.designated_hitter_id)
        dual = self.generator.select_starting_lineup(players, dh_mode='pitcher')
        self.assertNotEqual(target.player_id, dual.designated_hitter_id)
        target = replace(target, velocity_kmh=165, stuff=100, control=100, stamina=100, strikeout=100,
                         groundball=100, composure=100)
        players = tuple(target if p.player_id == target.player_id else p for p in players)
        dual = self.generator.select_starting_lineup(players, dh_mode='pitcher')
        self.assertEqual(target.player_id, dual.designated_hitter_id)

    def test_unavailable_or_unregistered_starter_and_too_small_dh_roster_are_rejected(self):
        from game_core.match_contract import validate_match_simulation_input
        inp = self.match()
        team = inp.team1
        pid = team.team_strength.starting_lineup.player_for_position('P')
        for bad in (replace(team, player_abilities=tuple(p for p in team.player_abilities if p.player_id != pid)),
                    replace(team, registered_player_ids=frozenset(p.player_id for p in team.player_abilities if p.player_id != pid))):
            with self.assertRaises(ValueError):
                validate_match_simulation_input(replace(inp, team1=bad))
        with self.assertRaises(ValueError):
            self.generator.generate(team.player_abilities[:9], dh_mode='normal')

    def test_forged_completed_notification_phase_or_missing_notification_is_rejected(self):
        from game_core.match_state import ChangeMoment
        inp, result, _ = self.play()
        record = result.team_participation[0]
        completion = record.changes[0]
        bad = replace(completion, moment=ChangeMoment(1, 'top', 1, 1))
        for changes in ((), (bad,)):
            with self.assertRaises(ValueError):
                validate_match_simulation_result(replace(result, team_participation=(replace(record, changes=changes), result.team_participation[1])), inp)

    def test_opponent_starter_notice_cannot_precede_actual_replacement(self):
        teams = list(self.by_mode['normal'])
        lineup = teams[0].team_strength.starting_lineup
        entries = tuple(replace(e, batting_order=9 if e.batting_order == 1 else e.batting_order-1) for e in lineup.entries)
        teams[0] = replace(teams[0], team_strength=replace(teams[0].team_strength, starting_lineup=replace(lineup, entries=entries)))
        starter = teams[1].team_strength.starting_lineup.player_for_position('P')
        inp, result, _ = self.play(teams=teams, changes=((starter, 1),))
        records = []
        for record in result.team_participation:
            changes = tuple(replace(c, moment=replace(c.moment, order=3-c.moment.order))
                            if getattr(c.moment, 'next_plate_appearance_no', None) == 2 else c for c in record.changes)
            records.append(replace(record, changes=changes))
        with self.assertRaisesRegex(ValueError, 'lacks an actual replacement'):
            validate_match_simulation_result(replace(result, team_participation=tuple(records)), inp)

    def test_forged_pitcher_pitch_counts_are_rejected(self):
        inp, result, _ = self.play()
        rows = (replace(result.pitcher_stats[0], pitches=result.pitcher_stats[0].pitches+1), *result.pitcher_stats[1:])
        with self.assertRaisesRegex(ValueError, 'individual stats differ'):
            validate_match_simulation_result(replace(result, pitcher_stats=rows), inp)

    def test_forged_individual_batting_stats_are_rejected_with_unchanged_team_totals(self):
        inp, result, _ = self.play()
        rows = list(result.batter_stats)
        first, second = rows[:2]
        rows[0] = replace(first, player_id=second.player_id)
        rows[1] = replace(second, player_id=first.player_id)
        with self.assertRaisesRegex(ValueError, 'individual stats differ'):
            validate_match_simulation_result(replace(result, batter_stats=tuple(rows)), inp)

    def test_unverified_dh_records_cannot_enter_option_a(self):
        from phase2_engine.historical_match_archive import _validate_participation_payload
        _, result, _ = self.play()
        with self.assertRaises(ValueError):
            _validate_participation_payload({'team_participation': [r.to_dict() for r in result.team_participation]})

    def test_dh_result_from_injected_simulator_is_rejected_before_live_side_effects(self):
        from unittest.mock import Mock
        from game_core.coaches import CoachTactics
        from game_core.tournament_bridge import AbilityMatchResolver
        _, result, _ = self.play()
        inp = self.match('none')
        live = object.__new__(AbilityMatchResolver)
        live.dh_enabled = False
        live.team_input = lambda **kw: inp.team1 if kw['school_id'] == inp.team1.school_id else inp.team2
        live._match_day = lambda: None
        live._coach_tactics = lambda *a: CoachTactics()
        live.rules_for = lambda *a: GameRules()
        live._pitch_allowances = lambda *a: None
        live.simulator = SimpleNamespace(config_dir='config/match', simulate=lambda *a, **kw: result)
        live._record_pitches = Mock()
        live._record_games = Mock()
        live.detail_sink = {}
        with self.assertRaisesRegex(ValueError, 'starting DH declaration'):
            live(match_id=inp.match_id, competition_id=inp.competition_id, reference_year=2026,
                 generation_seed=20261022, team1=inp.team1.school_id, team2=inp.team2.school_id)
        live._record_pitches.assert_not_called()
        live._record_games.assert_not_called()
        self.assertEqual({}, live.detail_sink)


if __name__ == '__main__':
    unittest.main()
