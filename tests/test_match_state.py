"""DHなしの出場状態と、本番接続前の非影響を架空データで確かめる。"""
from dataclasses import FrozenInstanceError, replace
import unittest

from game_core.match_contract import MatchSimulationInput, TeamMatchInput
from game_core.match_simulator import GameRules, MatchSimulator
from game_core.match_state import TeamMatchState
from game_core.team_strength import STARTING_POSITIONS, LineupEntry, StartingLineup, TeamStrengthGenerator
from test_stage13b3_team_strength import make_roster_abilities


class TeamMatchStateTests(unittest.TestCase):
    def setUp(self):
        orders = (9, 3, 7, 1, 6, 2, 5, 4, 8)
        self.lineup = StartingLineup('FAKE-STATE', 2026, tuple(
            LineupEntry(order, pos, 'FAKE-' + pos, 50.0)
            for order, pos in zip(orders, STARTING_POSITIONS)
        ))
        self.registered = {*self.lineup.starter_ids, 'BENCH-P', 'BENCH-F1', 'BENCH-F2'}
        self.state = TeamMatchState(self.lineup, self.registered)

    @staticmethod
    def snapshot(state):
        return (state.school_id, state.registered_player_ids, state.active_player_ids,
                state.batting_order, state.defensive_alignment, state.current_pitcher_id,
                state.bench_player_ids, state.exited_player_ids, state.history)

    def check(self, state=None):
        state = state or self.state
        state.validate(actual_pitcher_id=state.player_for_position('P'))
        self.assertEqual(9, len(state.active_player_ids))
        self.assertEqual(state.active_player_ids, {a.player_id for a in state.defensive_alignment})
        self.assertEqual(state.active_player_ids, {s.player_id for s in state.batting_order})
        self.assertEqual(tuple(range(1, 10)), tuple(s.batting_order for s in state.batting_order))
        self.assertFalse(state.active_player_ids & state.bench_player_ids)
        self.assertFalse(state.exited_player_ids & (state.active_player_ids | state.bench_player_ids))
        self.assertEqual(state.registered_player_ids,
                         state.active_player_ids | state.bench_player_ids | state.exited_player_ids)

    def rejected(self, operation):
        before = self.snapshot(self.state)
        with self.assertRaises(ValueError):
            operation()
        self.assertEqual(before, self.snapshot(self.state))
        self.check()

    def test_initialize_nine_players_positions_and_batting_slots(self):
        self.check()
        self.assertEqual('FAKE-2B', self.state.player_at_order(1))
        self.assertEqual('FAKE-P', self.state.current_pitcher_id)
        self.assertEqual({'BENCH-P', 'BENCH-F1', 'BENCH-F2'}, self.state.bench_player_ids)
        self.assertEqual((), self.state.history)

    def test_input_order_and_registration_order_do_not_change_state(self):
        other = TeamMatchState(replace(self.lineup, entries=tuple(reversed(self.lineup.entries))),
                               reversed(sorted(self.registered)))
        self.assertEqual(self.snapshot(self.state), self.snapshot(other))

    def test_infield_position_swap_keeps_batting_order(self):
        order = self.state.batting_order
        change = self.state.swap_positions('SS', '2B')
        self.assertEqual('FAKE-2B', self.state.player_for_position('SS'))
        self.assertEqual('FAKE-SS', self.state.player_for_position('2B'))
        self.assertEqual(order, self.state.batting_order)
        self.assertEqual('position_change', change.kind)
        self.assertEqual(2, len(change.defensive_changes))
        self.check()

    def test_outfield_position_swap_keeps_batting_order(self):
        order = self.state.batting_order
        self.state.swap_positions('LF', 'RF')
        self.assertEqual('FAKE-RF', self.state.player_for_position('LF'))
        self.assertEqual('FAKE-LF', self.state.player_for_position('RF'))
        self.assertEqual(order, self.state.batting_order)
        self.check()

    def test_three_positions_can_move_atomically(self):
        self.state.change_positions({'SS': 'FAKE-2B', '2B': 'FAKE-3B', '3B': 'FAKE-SS'})
        self.assertEqual(1, len(self.state.history))
        self.assertEqual(3, len(self.state.history[0].defensive_changes))
        self.check()

    def test_history_contains_only_successful_changes_in_order(self):
        self.state.swap_positions('SS', '2B')
        self.rejected(lambda: self.state.change_positions({'LF': 'FAKE-RF'}))
        self.state.substitute('FAKE-RF', 'BENCH-F1')
        self.assertEqual((1, 2), tuple(c.sequence for c in self.state.history))
        first, second = self.state.history
        self.assertIsNone(first.outgoing_player_id)
        self.assertEqual(('FAKE-RF', 'BENCH-F1'),
                         (second.outgoing_player_id, second.incoming_player_id))
        self.assertEqual([('RF', 'FAKE-RF', 'BENCH-F1')],
                         [(d.defensive_position, d.before_player_id, d.after_player_id)
                          for d in second.defensive_changes])
        self.check()

    def test_bench_fielder_inherits_the_same_batting_slot(self):
        order = next(s.batting_order for s in self.state.batting_order if s.player_id == 'FAKE-RF')
        change = self.state.substitute('FAKE-RF', 'BENCH-F1')
        self.assertEqual('BENCH-F1', self.state.player_at_order(order))
        self.assertEqual('BENCH-F1', self.state.player_for_position('RF'))
        self.assertEqual({'FAKE-RF'}, self.state.exited_player_ids)
        self.assertEqual((order, 'FAKE-RF', 'BENCH-F1'),
                         (change.batting_order, change.outgoing_player_id, change.incoming_player_id))
        self.check()

    def test_bench_pitcher_replaces_current_pitcher_and_inherits_slot(self):
        order = next(s.batting_order for s in self.state.batting_order if s.player_id == 'FAKE-P')
        change = self.state.change_pitcher('BENCH-P')
        self.assertEqual('BENCH-P', self.state.current_pitcher_id)
        self.assertEqual('BENCH-P', self.state.player_at_order(order))
        self.assertEqual({'FAKE-P'}, self.state.exited_player_ids)
        self.assertEqual('pitcher_change', change.kind)
        self.check()

    def test_active_fielder_can_pitch_and_old_pitcher_remains_in_the_field(self):
        order = self.state.batting_order
        self.state.change_pitcher('FAKE-RF')
        self.assertEqual('FAKE-RF', self.state.current_pitcher_id)
        self.assertEqual('FAKE-P', self.state.player_for_position('RF'))
        self.assertEqual(order, self.state.batting_order)
        self.assertFalse(self.state.exited_player_ids)
        self.check()

    def test_pitcher_and_fielder_can_exchange_positions_directly(self):
        self.state.swap_positions('P', 'CF')
        self.assertEqual('FAKE-CF', self.state.current_pitcher_id)
        self.check()

    def test_new_pitcher_can_replace_another_fielder_while_old_pitcher_stays(self):
        order = self.state.batting_order
        self.state.change_pitcher('BENCH-P', outgoing_player_id='FAKE-LF')
        self.assertEqual('BENCH-P', self.state.current_pitcher_id)
        self.assertEqual('FAKE-P', self.state.player_for_position('LF'))
        self.assertEqual({'FAKE-LF'}, self.state.exited_player_ids)
        for slot in order:
            self.assertEqual('BENCH-P' if slot.player_id == 'FAKE-LF' else slot.player_id,
                             self.state.player_at_order(slot.batting_order))
        self.assertEqual(1, len(self.state.history))
        self.check()

    def test_replacement_and_defensive_rotation_are_one_operation(self):
        self.state.substitute('FAKE-RF', 'BENCH-F1',
                              defensive_changes={'P': 'BENCH-F1', 'RF': 'FAKE-P'})
        self.assertEqual('BENCH-F1', self.state.current_pitcher_id)
        self.assertEqual('FAKE-P', self.state.player_for_position('RF'))
        self.assertEqual(1, len(self.state.history))
        self.check()

    def test_exited_player_cannot_reenter_as_fielder_or_pitcher(self):
        self.state.substitute('FAKE-RF', 'BENCH-F1')
        self.rejected(lambda: self.state.substitute('FAKE-LF', 'FAKE-RF'))
        self.rejected(lambda: self.state.change_pitcher('FAKE-RF'))

    def test_unregistered_active_and_nonactive_replacements_are_rejected(self):
        self.rejected(lambda: self.state.substitute('FAKE-RF', 'UNKNOWN'))
        self.rejected(lambda: self.state.change_pitcher('UNKNOWN'))
        self.rejected(lambda: self.state.substitute('FAKE-RF', 'FAKE-LF'))
        self.rejected(lambda: self.state.substitute('BENCH-F1', 'BENCH-F2'))

    def test_duplicate_positions_and_unknown_position_are_rejected_without_changes(self):
        self.rejected(lambda: self.state.change_positions({'SS': 'FAKE-2B'}))
        self.rejected(lambda: self.state.change_positions({'DH': 'BENCH-F1'}))
        self.rejected(lambda: self.state.change_positions({'SS': 'BENCH-F1'}))

    def test_failed_replacement_keeps_bench_exit_history_and_batting_slot(self):
        self.rejected(lambda: self.state.substitute('FAKE-RF', 'BENCH-F1',
                                                    defensive_changes={'P': 'BENCH-F1'}))
        # Failure must not consume the bench player or retire the original.
        self.state.substitute('FAKE-RF', 'BENCH-F1')
        self.assertEqual(1, self.state.history[0].sequence)
        self.check()

    def test_pitcher_operation_cannot_claim_another_p_assignment(self):
        self.rejected(lambda: self.state.change_pitcher('BENCH-P',
                                                        defensive_changes={'P': 'FAKE-P'}))
        self.rejected(lambda: self.state.change_pitcher('FAKE-RF',
                                                        outgoing_player_id='FAKE-LF'))

    def test_invalid_starting_lineups_and_missing_registration_are_rejected(self):
        entries = self.lineup.entries
        invalid = [
            entries[:-1],
            (replace(entries[0], player_id=entries[1].player_id), *entries[1:]),
            (replace(entries[0], defensive_position=entries[1].defensive_position), *entries[1:]),
            (replace(entries[0], batting_order=entries[1].batting_order), *entries[1:]),
        ]
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                TeamMatchState(replace(self.lineup, entries=tuple(rows)), self.registered)
        with self.assertRaises(ValueError):
            TeamMatchState(self.lineup, self.registered - {'FAKE-P'})

    def test_public_collections_and_input_data_cannot_be_mutated_by_operations(self):
        self.registered.clear()
        self.assertEqual(12, len(self.state.registered_player_ids))
        with self.assertRaises(FrozenInstanceError):
            self.state.batting_order[0].player_id = 'UNKNOWN'
        before = self.lineup.to_dict()
        self.state.change_pitcher('BENCH-P')
        with self.assertRaises(FrozenInstanceError):
            self.state.history[0].sequence = 99
        self.assertEqual(before, self.lineup.to_dict())
        self.check()

    def test_noop_does_not_append_history_and_order_lookup_is_strict(self):
        before = self.snapshot(self.state)
        self.assertIsNone(self.state.change_positions({}))
        self.assertIsNone(self.state.swap_positions('SS', 'SS'))
        self.assertIsNone(self.state.change_pitcher('FAKE-P'))
        self.assertEqual(before, self.snapshot(self.state))
        for order in (0, 10, True, '1'):
            with self.subTest(order=order), self.assertRaises(ValueError):
                self.state.player_at_order(order)


class MatchStateIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        generator = TeamStrengthGenerator()
        cls.teams = []
        for sid in ('FAKE-STATE-A', 'FAKE-STATE-B'):
            players = tuple(replace(p, player_id=sid + '-' + p.player_id)
                            for p in make_roster_abilities(school_id=sid))
            cls.teams.append(TeamMatchInput(sid, generator.generate(players), players))

    def state(self, team=None, **kwargs):
        team = team or self.teams[0]
        return TeamMatchState(team.team_strength.starting_lineup,
                              (p.player_id for p in team.player_abilities), **kwargs)

    def test_actual_position_comes_from_lineup_even_when_primary_position_differs(self):
        team = self.teams[0]
        lineup = team.team_strength.starting_lineup
        swapped = replace(lineup, entries=tuple(
            replace(e, defensive_position={'P': 'RF', 'RF': 'P'}.get(e.defensive_position, e.defensive_position))
            for e in reversed(lineup.entries)
        ))
        state = TeamMatchState(swapped, (p.player_id for p in team.player_abilities))
        actual_pitcher = lineup.player_for_position('RF')
        player = next(p for p in team.player_abilities if p.player_id == actual_pitcher)
        self.assertEqual('RF', player.primary_position)
        self.assertEqual(actual_pitcher, state.current_pitcher_id)
        self.assertEqual(lineup.player_for_position('P'), state.player_for_position('RF'))
        state.validate(actual_pitcher_id=actual_pitcher)

    def test_pitch_limit_starter_mismatch_is_detected_not_silently_reconciled(self):
        team = self.teams[0]
        selected = team.team_strength.starting_lineup.player_for_position('P')
        simulator = MatchSimulator()
        for left in (0, 60):
            with self.subTest(left=left):
                state = self.state()
                order, _ = simulator._game_staff(team, {selected: left})
                actual = order[0]
                self.assertNotEqual(selected, actual)
                before = TeamMatchStateTests.snapshot(state)
                with self.assertRaisesRegex(ValueError, 'differs from actual pitcher'):
                    state.validate(actual_pitcher_id=actual)
                with self.assertRaises(ValueError):
                    self.state(actual_pitcher_id=actual)
                self.assertEqual(before, TeamMatchStateTests.snapshot(state))
                self.assertEqual(selected, state.current_pitcher_id)
                state.change_pitcher(actual)
                state.validate(actual_pitcher_id=actual)
                self.assertEqual(selected, team.team_strength.starting_lineup.player_for_position('P'))
                self.assertEqual(order, simulator._game_staff(team, {selected: left})[0])

    def test_emergency_fielder_selected_by_existing_staff_can_pitch_in_state(self):
        team = self.teams[0]
        state = self.state()
        fielder = state.player_for_position('RF')
        allowances = {p.player_id: 0 for p in team.player_abilities}
        allowances[fielder] = 100
        order, size = MatchSimulator()._game_staff(team, allowances)
        self.assertEqual((fielder,), order)
        self.assertEqual(0, size)
        before = state.batting_order
        state.change_pitcher(order[0])
        state.validate(actual_pitcher_id=fielder)
        self.assertEqual(before, state.batting_order)

    def test_state_operations_do_not_change_any_existing_match_result_or_input(self):
        simulator = MatchSimulator()
        originals = tuple(t.to_dict() for t in self.teams)
        for number in range(12):
            inp = MatchSimulationInput(f'STATE-{number}', 'FAKE-STATE-CUP', 2026, 20261029,
                                       *self.teams, team_generation_seed=2026100701)
            options = {'rules': GameRules(tiebreak_start_inning=10, mercy=((5, 10), (7, 7)))}
            if number % 2:
                options['pitch_allowances'] = {
                    t.team_strength.starting_lineup.player_for_position('P'): 0 for t in self.teams
                }
            before = simulator.simulate(inp, **options).to_dict()
            for team in self.teams:
                state = self.state(team)
                state.swap_positions('SS', '2B')
                incoming = next(e.player_id for e in team.team_strength.pitching_staff.entries
                                if e.player_id in state.bench_player_ids)
                state.change_pitcher(incoming)
                state.validate(actual_pitcher_id=incoming)
            after = simulator.simulate(inp, **options).to_dict()
            # Full equality includes runs/ER, events' pitcher order, all batting
            # stats, line score, winner and deterministic reproduction.
            self.assertEqual(before, after)
        self.assertEqual(originals, tuple(t.to_dict() for t in self.teams))


if __name__ == '__main__':
    unittest.main()
