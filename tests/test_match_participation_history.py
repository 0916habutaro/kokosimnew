"""架空データで開始配置・交代時点の保存、復元、改変拒否を確認する。"""
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
            with sqlite3.connect(path) as conn:
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


if __name__ == '__main__':
    unittest.main()
