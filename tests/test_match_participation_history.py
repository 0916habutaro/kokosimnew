"""架空データで開始配置・交代時点の保存、復元、改変拒否を確認する。"""
from contextlib import closing
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from game_core.highlights import game_highlights
from game_core.match_contract import validate_match_simulation_result
from game_core.match_simulator import MatchSimulator
from game_core.match_state import (
    ChangeMoment, TeamMatchParticipation, TeamMatchState, apply_lineup_change,
    replay_team_participation,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive, compact_payload, expand_payload
from test_coach_intake import books
from test_coach_tactics import resolver
import test_live_match_state as fixtures


class MatchParticipationHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.LiveMatchStateTests.setUpClass()
        cls.fixture = fixtures.LiveMatchStateTests()

    def assert_replays(self, result, states):
        for record in result.team_participation:
            restored = replay_team_participation(record, result.reference_year)
            actual = states[record.school_id]
            self.assertEqual(actual.batting_order, restored.batting_order)
            self.assertEqual(actual.defensive_alignment, restored.defensive_alignment)
            self.assertEqual(actual.exited_player_ids, restored.exited_player_ids)
            self.assertEqual(actual.history, restored.history)
            self.assertEqual(actual.fielding_player_ids, restored.fielding_player_ids)
            self.assertEqual(record, TeamMatchParticipation.from_dict(record.to_dict()))

    def relief_game(self):
        team = self.fixture.teams[1]
        staff = self.fixture.staff(team)
        result, sim = self.fixture.play(top=['walk', 'walk', 'home_run'],
                                         changes=((staff[0], 1), (staff[1], 1)))
        return result, sim

    def test_normal_initial_lineups_and_empty_changes(self):
        result, sim = self.fixture.play()
        self.assertEqual(2, len(result.team_participation))
        for record in result.team_participation:
            self.assertEqual(9, len(record.starting_lineup))
            self.assertEqual(tuple(range(1, 10)), tuple(s.batting_order for s in record.starting_lineup))
            self.assertEqual(record.starting_pitcher_id,
                             next(s.player_id for s in record.starting_lineup if s.defensive_position == 'P'))
            self.assertEqual((), record.changes)
            self.assertEqual({s.player_id for s in record.starting_lineup}, set(record.fielding_player_ids))
        self.assert_replays(result, sim.states)

    def test_pitch_limit_starter_change_is_initial_configuration_not_substitution(self):
        team = self.fixture.teams[1]
        old, new = self.fixture.staff(team)[:2]
        result, sim = self.fixture.play(pitch_allowances={old: 60}, regulation_innings=1)
        record = result.team_participation[1]
        self.assertEqual(new, record.starting_pitcher_id)
        self.assertNotIn(old, {s.player_id for s in record.starting_lineup})
        self.assertNotIn(old, record.fielding_player_ids)
        self.assertEqual((), record.changes)
        self.assert_replays(result, sim.states)

    def test_pitch_limit_fielder_start_saves_actual_positions(self):
        team = self.fixture.teams[1]
        new, allowances = self.fixture.fielder_allowances(team)
        result, sim = self.fixture.play(pitch_allowances=allowances)
        record = result.team_participation[1]
        positions = {s.defensive_position: s.player_id for s in record.starting_lineup}
        self.assertEqual(new, positions['P'])
        self.assertEqual(self.fixture.staff(team)[0], positions['SS'])
        self.assertEqual((), record.changes)
        self.assert_replays(result, sim.states)

    def test_multiple_relief_changes_share_slot_and_precede_next_plate_appearance(self):
        result, sim = self.relief_game()
        changes = result.team_participation[1].changes
        self.assertEqual((1, 2), tuple(c.sequence for c in changes))
        self.assertEqual((2, 3), tuple(c.moment.next_plate_appearance_no for c in changes))
        self.assertEqual(1, len({c.batting_order for c in changes}))
        for change in changes:
            event = result.events[change.moment.next_plate_appearance_no - 1]
            self.assertEqual((event.inning, event.half), (change.moment.inning, change.moment.half))
            self.assertEqual(event.pitcher_id, change.incoming_player_id)
            self.assertEqual(event.defense_school_id, change.school_id)
            self.assertIsNotNone(change.outgoing_player_id)
        self.assert_replays(result, sim.states)

    def test_active_fielder_relief_keeps_original_pitcher_in_field(self):
        team = self.fixture.teams[0]
        old = self.fixture.staff(team)[0]
        new, allowances = self.fixture.fielder_allowances(team)
        allowances[old] = 100
        sim = fixtures.ObservedSimulator({self.fixture.teams[1].school_id: ['home_run']})
        sim._pitches = lambda *args: 100
        result = sim.simulate(self.fixture.match(), pitch_allowances=allowances)
        record = result.team_participation[0]
        change = record.changes[0]
        self.assertIsNone(change.outgoing_player_id)
        self.assertIsNone(change.incoming_player_id)
        self.assertIsNone(change.batting_order)
        restored = replay_team_participation(record, 2026)
        self.assertEqual(new, restored.current_pitcher_id)
        self.assertEqual(old, restored.player_for_position('SS'))
        self.assertFalse(restored.exited_player_ids)
        self.assert_replays(result, sim.states)
        with tempfile.TemporaryDirectory() as tmp:
            archive = HistoricalMatchArchive(Path(tmp) / 'history.sqlite3')
            self.sync(archive, [self.record(result)])
            archive.pack_competition(2026, result.competition_id)
            loaded = archive.get_match(2026, result.competition_id, result.match_id)
            self.assertEqual(record.to_dict(), loaded['team_participation'][0])

    def test_position_only_exchanges_and_failed_changes_round_trip_without_retirement(self):
        team = self.fixture.teams[0]
        state = TeamMatchState(team.team_strength.starting_lineup, (p.player_id for p in team.player_abilities))
        state.record_fielding_appearance()
        state.swap_positions('SS', '2B', moment=ChangeMoment(2, 'top', 10))
        state.swap_positions('P', 'RF', moment=ChangeMoment(3, 'top', 20))
        before = state.participation()
        with self.assertRaises(ValueError):
            state.change_positions({'SS': state.player_for_position('2B')}, moment=ChangeMoment(3, 'top', 20))
        state.change_pitcher(state.current_pitcher_id, moment=ChangeMoment(3, 'top', 20))
        self.assertEqual(before, state.participation())
        restored = replay_team_participation(before, 2026)
        self.assertEqual(state.defensive_alignment, restored.defensive_alignment)
        self.assertEqual(state.batting_order, restored.batting_order)
        self.assertFalse(restored.exited_player_ids)
        self.assertEqual(('position_change', 'position_change'), tuple(c.kind for c in restored.history))

    def test_reentry_and_modified_differences_are_rejected_atomically(self):
        result, _ = self.relief_game()
        record = result.team_participation[1]
        state = replay_team_participation(record, 2026)
        before = state.participation()
        with self.assertRaises(ValueError):
            state.change_pitcher(record.starting_pitcher_id, moment=ChangeMoment(9, 'top', 60))
        bad = replace(record.changes[-1], sequence=len(state.history) + 1)
        with self.assertRaises(ValueError):
            apply_lineup_change(state, bad)
        trial = replay_team_participation(record, 2026)
        proposal = trial.swap_positions('LF', 'RF', moment=ChangeMoment(9, 'top', 60))
        # 配置自体は適用可能でも、履歴の出場情報が矛盾すれば操作全体を戻す。
        with self.assertRaises(ValueError):
            apply_lineup_change(state, replace(proposal, incoming_player_id=record.starting_pitcher_id))
        self.assertEqual(before, state.participation())

    def test_corrupt_initial_state_history_and_appearance_facts_are_rejected(self):
        result, _ = self.relief_game()
        record = result.team_participation[1]
        first, second = record.changes
        variants = [
            replace(record, starting_pitcher_id=record.starting_lineup[0].player_id),
            replace(record, starting_lineup=(record.starting_lineup[0],) * 9),
            replace(record, changes=(replace(first, sequence=2), second)),
            replace(record, changes=(replace(first, school_id='UNREGISTERED'), second)),
            replace(record, changes=(replace(first, moment=ChangeMoment(2, 'top', 2)), second)),
            replace(record, changes=(first, replace(second, moment=ChangeMoment(1, 'top', 1)))),
            replace(record, changes=(first, replace(second, moment=ChangeMoment(99, 'top', 999)))),
            replace(record, changes=(replace(first, defensive_changes=tuple(
                replace(d, before_player_id='WRONG') for d in first.defensive_changes)), second)),
            replace(record, changes=(replace(first, batting_order=1), second)),
            replace(record, fielding_player_ids=record.fielding_player_ids[:-1]),
            replace(record, fielding_player_ids=(*record.fielding_player_ids, 'NEVER-APPEARED')),
        ]
        for index, bad in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate_match_simulation_result(replace(result, team_participation=(result.team_participation[0], bad)),
                                                 self.fixture.match())

    def test_runtime_final_state_must_equal_replayed_state(self):
        result, sim = self.relief_game()
        sim.states[result.team1_school_id].swap_positions('LF', 'RF')
        with self.assertRaisesRegex(ValueError, 'final lineup'):
            validate_match_simulation_result(result, self.fixture.match(), final_states=sim.states)

    def record(self, result):
        detail = result.to_dict()
        detail['highlights'] = game_highlights(result.events)
        return dict(competition_id=result.competition_id, match_id=result.match_id,
                    team1_id=result.team1_school_id, team2_id=result.team2_school_id,
                    winner_id=result.winner_id, loser_id=result.loser_id,
                    team1_score=result.team1_score, team2_score=result.team2_score,
                    score_source=result.score_source, ability_detail=detail,
                    match_date='2026-07-05', status='completed')

    def sync(self, archive, rows, year=2026):
        return archive.sync(year=year, rng_seed=20261029, resolver_contract='players_v1',
                            plan_fingerprint='fake-history', completed=rows)

    def test_archive_pack_seal_and_fifty_hundred_year_later_reads_need_only_saved_ids(self):
        result, sim = self.relief_game()
        record = self.record(result)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.sqlite3'
            archive = HistoricalMatchArchive(path)
            self.sync(archive, [record])
            initial = archive.get_match(2026, result.competition_id, result.match_id)
            self.assertEqual(result.to_dict()['team_participation'], initial['team_participation'])
            self.assertEqual(record['ability_detail']['highlights'], initial['highlights'])
            self.assertNotIn('events', initial)
            with closing(sqlite3.connect(path)) as conn:
                raw = json.loads(conn.execute('SELECT payload_json FROM historical_matches').fetchone()[0])
            self.assertTrue(any(h[0] == 'P' for h in raw['highlights']))
            self.assertTrue(all(len(h) == 3 for h in raw['highlights'] if h[0] == 'P'))
            self.assertEqual(initial, expand_payload(compact_payload(initial)))
            self.assertEqual(1, archive.pack_competition(2026, result.competition_id))
            self.assertEqual(1, archive.seal_year(2026, expected_match_count=1)['match_count'])
            for year in range(2027, 2127):
                archive.register_next_year(year=year, rng_seed=20261029,
                                           resolver_contract='players_v1', plan_fingerprint='fake-history')
                if year not in (2076, 2126):
                    continue
                loaded = HistoricalMatchArchive(path).get_match(2026, result.competition_id, result.match_id)
                self.assertEqual(initial, loaded)
                records = tuple(TeamMatchParticipation.from_dict(r) for r in loaded['team_participation'])
                self.assert_replays(replace(result, team_participation=records), sim.states)

    def test_archive_rejects_inconsistent_history_before_save_and_after_corrupt_read(self):
        result, _ = self.relief_game()
        for field in ('sequence', 'half', 'fielding', 'inning_count'):
            record = self.record(result)
            saved = record['ability_detail']['team_participation'][1]
            if field == 'sequence':
                saved['changes'][0]['sequence'] = 99
            elif field == 'half':
                saved['changes'][0]['moment']['half'] = 'bottom'
            elif field == 'fielding':
                saved['fielding_player_ids'].pop()
            else:
                innings = record['ability_detail']['inning_scores']
                innings[1]['plate_appearances'] += innings[0]['plate_appearances']
                innings[0]['plate_appearances'] = 0
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                archive = HistoricalMatchArchive(Path(tmp) / 'history.sqlite3')
                with self.assertRaises(ValueError):
                    self.sync(archive, [record])
        payload = self.record(result)['ability_detail']
        compact = compact_payload(payload)
        # expand_payload expects archive metadata in addition to the result.
        compact.update(year=2026, team1_id=result.team1_school_id, team2_id=result.team2_school_id)
        compact['highlights'][0] = ['P', 9, 1]
        with self.assertRaises(ValueError):
            expand_payload(compact)
        compact['team_participation']['rows'] = []
        with self.assertRaises(ValueError):
            expand_payload(compact)

    def test_production_resolver_passes_same_participation_through_detail_sink(self):
        bridge = resolver(books(), date(2026, 7, 5))
        bridge.detail_sink = {}
        resolution = bridge(match_id='FAKE-SINK', competition_id='FAKE-CUP', reference_year=2026,
                            generation_seed=7, team1='FAKE-A', team2='FAKE-B')
        detail = bridge.detail_sink['FAKE-CUP:FAKE-SINK']
        self.assertEqual([], detail['events'])
        self.assertEqual(2, len(detail['team_participation']))
        record = dict(competition_id='FAKE-CUP', match_id='FAKE-SINK', team1_id='FAKE-A', team2_id='FAKE-B',
                      winner_id=resolution.winner_id, loser_id=resolution.loser_id,
                      team1_score=resolution.team1_score, team2_score=resolution.team2_score,
                      score_source=resolution.score_source, ability_detail=detail, status='completed')
        with tempfile.TemporaryDirectory() as tmp:
            archive = HistoricalMatchArchive(Path(tmp) / 'history.sqlite3')
            self.sync(archive, [record])
            self.assertEqual(detail['team_participation'], archive.get_match(2026, 'FAKE-CUP', 'FAKE-SINK')['team_participation'])

    def test_guarding_only_players_are_explicitly_identifiable_and_result_repeats(self):
        sim = MatchSimulator()
        for number in range(8):
            inp = self.fixture.match(number=number)
            a, b = sim.simulate(inp), sim.simulate(inp)
            self.assertEqual(a.to_dict(), b.to_dict())
        result, _ = self.fixture.play(top=['home_run'], regulation_innings=1)
        batting = {r.player_id for r in result.batter_stats if r.plate_appearances}
        pitching = {r.player_id for r in result.pitcher_stats if r.batters_faced}
        fielding = {pid for r in result.team_participation for pid in r.fielding_player_ids}
        self.assertTrue(fielding - batting - pitching)


class DHHistoryFixtures:
    @classmethod
    def setUpClass(cls):
        fixtures.DHSimulationTests.setUpClass()
        cls.dh = fixtures.DHSimulationTests()

    def game(self, mode='normal', **kwargs):
        from game_core.match_contract import validated_match_history
        inp, result, states = self.dh.play(mode, **kwargs)
        detail = validated_match_history(result, inp)
        row = dict(competition_id=result.competition_id, competition_name='架空DH大会', match_id=result.match_id,
                   team1_id=result.team1_school_id, team2_id=result.team2_school_id,
                   winner_id=result.winner_id, loser_id=result.loser_id,
                   team1_score=result.team1_score, team2_score=result.team2_score,
                   score_source=result.score_source, ability_detail=detail,
                   match_date='2026-07-05', status='completed', round_name='決勝')
        return inp, result, states, row

    @staticmethod
    def sync(archive, rows):
        return archive.sync(year=2026, rng_seed=20261022, resolver_contract='players_v1',
                            plan_fingerprint='fake-dh-history', completed=rows)

    def saved(self, row):
        from phase2_engine.historical_match_archive import _history_payload
        return _history_payload(2026, row)

    def double_switch(self):
        from game_core.match_simulator import LineupAdjustment
        team = self.dh.by_mode['normal'][0]
        lineup = team.team_strength.starting_lineup
        cf_slot = next(e.batting_order for e in lineup.entries if e.defensive_position == 'CF')
        bench = [p.player_id for p in team.player_abilities if p.player_id not in lineup.starter_ids]
        rp = next(pid for pid in fixtures.MatchSimulator._pitcher_order(team) if pid in bench)
        batter = next(pid for pid in bench if pid != rp)
        plan = LineupAdjustment(2, team.school_id, ((1, batter), (cf_slot, rp)), (('CF', batter), ('P', rp)))
        return self.game(lineup_changes=(plan,)), cf_slot, rp, batter


class DHMatchHistoryTests(DHHistoryFixtures, unittest.TestCase):
    def test_recorded_batting_cycles_equal_actual_events_and_keep_first_dh_obligation(self):
        from copy import deepcopy
        from game_core.match_contract import dh_history_fingerprint
        from game_core.match_state import _validate_dh_event_history
        from phase2_engine.historical_match_archive import _validate_participation_payload

        for mode in ('none', 'normal', 'pitcher'):
            with self.subTest(mode=mode):
                teams = []
                for team in self.dh.by_mode[mode]:
                    lineup = team.team_strength.starting_lineup
                    if mode != 'none':
                        ordered = sorted(lineup.entries,
                            key=lambda e: (e.player_id == lineup.designated_hitter_id, e.batting_order))
                        lineup = replace(lineup, entries=tuple(replace(e, batting_order=i)
                                          for i, e in enumerate(ordered, 1)))
                    teams.append(replace(team, team_strength=replace(team.team_strength, starting_lineup=lineup)))
                inp, result, _, row = self.game(mode, teams=teams, top=('walk',)*20)
                ranges, next_pa = {}, 1
                for half in result.inning_scores:
                    ranges[half.inning, half.half] = (next_pa, next_pa+half.plate_appearances-1)
                    next_pa += half.plate_appearances
                args = (result.team_participation, (inp.team1.school_id, inp.team2.school_id),
                        2026, {t.school_id: {p.player_id for p in t.player_abilities} for t in teams})
                actual = _validate_dh_event_history(*args, result.events, None, ranges, next_pa-1)
                recorded = _validate_dh_event_history(*args, None, None, ranges, next_pa-1, recorded=True)
                self.assertEqual(actual, recorded)
                self.saved(row)
                if mode == 'none':
                    continue
                payload = self.saved(row)
                for change_kind in ('remove', 'late'):
                    bad = deepcopy(payload)
                    changes = bad['team_participation'][0]['changes']
                    index = next(i for i, c in enumerate(changes) if c['kind'] == 'dh_plate_appearance')
                    if change_kind == 'remove':
                        changes.pop(index)
                    else:
                        changes[index]['moment']['completed_plate_appearance_no'] += 1
                    bad['dh_verification']['facts_sha256'] = dh_history_fingerprint(bad)
                    with self.assertRaisesRegex(ValueError, 'completed DH plate appearance notification'):
                        _validate_participation_payload(bad)

    def test_presave_validation_uses_the_simulators_match_configuration(self):
        import shutil
        from game_core.match_contract import validated_match_history
        inp = self.dh.match()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp)/'match'
            shutil.copytree(Path(__file__).resolve().parents[1]/'config'/'match', config)
            path = config/'match_simulation_v1.json'
            document = json.loads(path.read_text())
            document['revision'] += 1
            path.write_text(json.dumps(document))
            result = fixtures.MatchSimulator(config).simulate(inp)
            with self.assertRaisesRegex(ValueError, 'config provenance'):
                validated_match_history(result, inp)
            self.assertIn('dh_verification', validated_match_history(result, inp, config_dir=config))

    def test_opponent_starter_notice_and_final_batter_completion_survive_storage(self):
        teams = list(self.dh.by_mode['normal'])
        lineup = teams[0].team_strength.starting_lineup
        entries = tuple(replace(e, batting_order=9 if e.batting_order == 1 else e.batting_order-1) for e in lineup.entries)
        teams[0] = replace(teams[0], team_strength=replace(teams[0].team_strength, starting_lineup=replace(lineup, entries=entries)))
        starter = teams[1].team_strength.starting_lineup.player_for_position('P')
        _, _, _, row = self.game(teams=teams, changes=((starter, 1),))
        payload = expand_payload(compact_payload(self.saved(row)))
        self.assertTrue(any(c['kind'] == 'dh_opponent_pitcher' for c in payload['team_participation'][0]['changes']))
        _, result, _, row = self.game(top=(), bottom=('home_run',))
        payload = expand_payload(compact_payload(self.saved(row)))
        complete = next(c for c in payload['team_participation'][1]['changes'] if c['kind'] == 'dh_plate_appearance')
        self.assertEqual(len(result.events), complete['moment']['completed_plate_appearance_no'])

    def test_cold_skipped_bottom_and_extra_inning_records_replay_without_events(self):
        cases = (dict(top=(), bottom=('home_run',), regulation_innings=9, rules=fixtures.GameRules(mercy=((2, 1),))),
                 dict(top=('field_out',)*3+('home_run',), rules=fixtures.GameRules(tiebreak_start_inning=2)))
        for case in cases:
            _, _, _, row = self.game(**case)
            payload = self.saved(row)
            self.assertEqual(payload, expand_payload(compact_payload(payload)))

    def test_pitcher_announced_during_offense_highlight_uses_next_actual_defensive_half(self):
        from game_core.match_simulator import LineupAdjustment
        team = self.dh.by_mode['normal'][0]
        lineup = team.team_strength.starting_lineup
        rp = next(pid for pid in fixtures.MatchSimulator._pitcher_order(team) if pid not in lineup.starter_ids)
        plan = LineupAdjustment(8, team.school_id, defensive_changes=(('P', rp),))
        _, _, _, row = self.game(regulation_innings=2, lineup_changes=(plan,))
        payload = self.saved(row)
        change = next(c for c in payload['team_participation'][0]['changes'] if c['defensive_changes'])
        self.assertEqual('top', change['moment']['half'])
        highlight = next(h for h in payload['highlights'] if h[0] == 'P')
        self.assertEqual((2, 'b'), tuple(highlight[1:3]))
        self.assertEqual(payload, expand_payload(compact_payload(payload)))

    def test_mixed_dh_and_no_dh_teams_share_saved_contract(self):
        teams = (self.dh.by_mode['none'][0], self.dh.by_mode['normal'][1])
        _, _, _, row = self.game(teams=teams)
        payload = self.saved(row)
        self.assertEqual(payload, expand_payload(compact_payload(payload)))

    def test_resolver_hands_verified_event_free_dh_detail_to_both_save_routes(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from game_core.coaches import CoachTactics
        from game_core.tournament_bridge import AbilityMatchResolver
        inp, result, _, row = self.game()
        for sink in ({}, None):
            live = object.__new__(AbilityMatchResolver)
            live.dh_enabled = False
            live.team_input = lambda **kw: inp.team1 if kw['school_id'] == inp.team1.school_id else inp.team2
            live._match_day = lambda: None
            live._coach_tactics = lambda *a: CoachTactics()
            live.rules_for = lambda *a: fixtures.GameRules()
            live._pitch_allowances = lambda *a: None
            live.simulator = SimpleNamespace(config_dir='config/match', simulate=lambda *a, **kw: result)
            live._record_pitches, live._record_games = Mock(), Mock()
            live.detail_sink = sink
            resolved = live(match_id=inp.match_id, competition_id=inp.competition_id, reference_year=2026,
                            generation_seed=inp.generation_seed, team1=inp.team1.school_id, team2=inp.team2.school_id)
            detail = sink[f'{inp.competition_id}:{inp.match_id}'] if sink is not None else resolved.detail
            self.assertNotIn('events', detail)
            self.assertIn('dh_verification', detail)
            live._record_pitches.assert_called_once()
            live._record_games.assert_called_once()
            loaded = self.saved({**row, 'ability_detail': detail})
            self.assertEqual(detail['team_participation'], loaded['team_participation'])

    def test_three_modes_save_reload_compact_without_events(self):
        from copy import deepcopy
        for mode in ('none', 'normal', 'pitcher'):
            with self.subTest(mode=mode):
                _, result, _, row = self.game(mode)
                original = deepcopy(row)
                with tempfile.TemporaryDirectory() as tmp:
                    archive = HistoricalMatchArchive(Path(tmp)/'history.sqlite3')
                    self.assertEqual(1, self.sync(archive, [row])['inserted'])
                    loaded = archive.get_match(2026, result.competition_id, result.match_id)
                    self.assertEqual(row, original)
                    self.assertNotIn('events', loaded)
                    self.assertEqual(result.to_dict()['team_participation'], loaded['team_participation'])
                    self.assertEqual(loaded, expand_payload(compact_payload(loaded)))
                    self.assertEqual(mode != 'none', 'dh_verification' in loaded)

    def test_typed_moments_dh_actions_defense_and_pitching_highlight_references_round_trip(self):
        team = self.dh.by_mode['pitcher'][1]
        starter = team.team_strength.starting_lineup.designated_hitter_id
        _, _, _, row = self.game('pitcher', changes=((starter, 1),))
        payload = self.saved(row)
        compact = compact_payload(payload)
        self.assertEqual(payload, expand_payload(json.loads(json.dumps(compact))))
        self.assertTrue(all(len(h) == 3 for h in compact['highlights'] if h[0] == 'P'))
        self.assertTrue(any(c['kind'] == 'dh_plate_appearance' for r in payload['team_participation'] for c in r['changes']))
        self.assertTrue(any('order' in c['moment'] for r in payload['team_participation'] for c in r['changes']))

    def test_double_switch_dh_successor_and_pitcher_batting_slot_survive(self):
        (_, result, states, row), slot, rp, batter = self.double_switch()
        loaded = expand_payload(compact_payload(self.saved(row)))
        state = replay_team_participation(TeamMatchParticipation.from_dict(loaded['team_participation'][0]), 2026)
        self.assertIsNone(state.designated_hitter_id)
        self.assertEqual(rp, state.player_at_order(slot))
        self.assertEqual(batter, state.player_for_position('CF'))
        self.assertEqual(states[result.team1_school_id].exited_player_ids, state.exited_player_ids)

    def test_pitcher_only_player_is_known_without_batter_row_and_dh_has_no_fielding(self):
        _, _, _, row = self.game()
        payload = expand_payload(compact_payload(self.saved(row)))
        for raw in payload['team_participation']:
            pitcher, dh = raw['starting_pitcher_id'], raw['starting_designated_hitter_id']
            self.assertNotIn(pitcher, {b['player_id'] for b in payload['batter_stats']})
            self.assertIn(pitcher, {p['player_id'] for p in payload['pitcher_stats']})
            self.assertNotIn(dh, raw['fielding_player_ids'])

    def test_each_two_way_role_exit_and_full_exit_replay(self):
        from game_core.match_simulator import LineupAdjustment
        team = self.dh.by_mode['pitcher'][0]
        lineup = team.team_strength.starting_lineup
        bench = [p.player_id for p in team.player_abilities if p.player_id not in lineup.starter_ids]
        rp = next(pid for pid in fixtures.MatchSimulator._pitcher_order(team) if pid in bench)
        batter = next(pid for pid in bench if pid != rp)
        for bats, defense, expected in (((), (('P', rp),), {'pitcher'}),
                                       (((1, batter),), (), {'batter'}),
                                       (((1, batter),), (('P', rp),), {'pitcher', 'batter'})):
            _, _, _, row = self.game('pitcher', lineup_changes=(LineupAdjustment(2, team.school_id, bats, defense),))
            loaded = expand_payload(compact_payload(self.saved(row)))
            state = replay_team_participation(TeamMatchParticipation.from_dict(loaded['team_participation'][0]), 2026)
            self.assertEqual(expected, state.retired_two_way_roles)
            self.assertEqual(len(expected) == 2, lineup.designated_hitter_id in state.exited_player_ids)

    def test_pack_seal_reopen_and_duplicate_save_are_idempotent(self):
        _, result, _, row = self.game('pitcher')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'history.sqlite3'
            archive = HistoricalMatchArchive(path)
            self.sync(archive, [row])
            before = archive.get_match(2026, result.competition_id, result.match_id)
            self.assertEqual(1, archive.pack_competition(2026, result.competition_id))
            archive.seal_year(2026, expected_match_count=1)
            restarted = HistoricalMatchArchive(path)
            self.assertEqual({'inserted': 0, 'already_archived': 1}, self.sync(restarted, [row]))
            for year in range(2027, 2127):
                restarted.register_next_year(year=year, rng_seed=20261022, resolver_contract='players_v1', plan_fingerprint='fake-dh-history')
            self.assertEqual(before, restarted.get_match(2026, result.competition_id, result.match_id))

    def test_missing_presave_verification_or_changed_stats_are_rejected(self):
        from copy import deepcopy
        _, _, _, row = self.game()
        for mutate in (lambda d: d.pop('dh_verification'),
                       lambda d: d['pitcher_stats'][0].update(pitches=d['pitcher_stats'][0]['pitches']+1)):
            bad = deepcopy(row)
            mutate(bad['ability_detail'])
            with self.assertRaises(ValueError):
                self.saved(bad)

    def test_presave_strict_validation_rejects_wrong_runner_liability(self):
        from game_core.match_contract import validated_match_history
        team = self.dh.by_mode['normal'][1]
        starter = team.team_strength.starting_lineup.player_for_position('P')
        inp, result, _, _ = self.game(top=('walk', 'home_run'), changes=((starter, 1),))
        rows = list(result.pitcher_stats)
        index = next(i for i, p in enumerate(rows) if p.player_id == starter)
        other = next(i for i, p in enumerate(rows) if p.school_id == team.school_id and p.player_id != starter)
        rows[index] = replace(rows[index], runs_allowed=0, earned_runs=0)
        rows[other] = replace(rows[other], runs_allowed=2, earned_runs=2)
        with self.assertRaisesRegex(ValueError, 'actual runner liability'):
            validated_match_history(replace(result, pitcher_stats=tuple(rows)), inp)

    def test_recorded_validator_rejects_corrupt_dh_rules_even_with_recomputed_transfer_hash(self):
        from copy import deepcopy
        from game_core.match_contract import dh_history_fingerprint
        from phase2_engine.historical_match_archive import _validate_participation_payload
        payload = self.saved(self.game()[3])
        mutations = (
            lambda p: p['team_participation'][0].update(starting_designated_hitter_id='UNKNOWN'),
            lambda p: p['team_participation'][0].update(changes=[]),
            lambda p: p['team_participation'][0]['starting_defense'][1].update(player_id=p['team_participation'][0]['starting_pitcher_id']),
            lambda p: p['batter_stats'][0].update(plate_appearances=2, at_bats=2),
            lambda p: p['team_participation'][0]['changes'][0]['moment'].update(completed_plate_appearance_no=999),
        )
        for mutate in mutations:
            bad = deepcopy(payload)
            mutate(bad)
            bad['dh_verification']['facts_sha256'] = dh_history_fingerprint(bad)
            with self.assertRaises(ValueError):
                _validate_participation_payload(bad)

    def test_stored_checksum_detects_payload_corruption(self):
        _, result, _, row = self.game()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'history.sqlite3'
            archive = HistoricalMatchArchive(path)
            self.sync(archive, [row])
            with closing(sqlite3.connect(path)) as conn, conn:
                raw = json.loads(conn.execute('SELECT payload_json FROM historical_matches').fetchone()[0])
                raw['dh_verification']['facts_sha256'] = '0'*64
                conn.execute('UPDATE historical_matches SET payload_json=?', (json.dumps(raw),))
            with self.assertRaises(ValueError):
                archive.get_match(2026, result.competition_id, result.match_id)


if __name__ == '__main__':
    unittest.main()
