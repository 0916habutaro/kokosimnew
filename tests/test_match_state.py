"""DHなしの出場状態と、独立した状態操作の非影響を架空データで確かめる。"""
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

    def test_dh_state_connects_to_direct_simulation(self):
        from game_core.team_strength import DefensiveAssignment
        original = self.teams[0]
        old = original.team_strength.starting_lineup
        pitcher = old.player_for_position('P')
        dh = replace(old, entries=tuple(replace(e, defensive_position='DH')
                                       if e.defensive_position == 'P' else e for e in old.entries),
                     defense=tuple(DefensiveAssignment(e.defensive_position,e.player_id)
                                   for e in old.entries), designated_hitter_id=pitcher)
        TeamMatchState(dh,(p.player_id for p in original.player_abilities)).validate()
        team = replace(original,team_strength=replace(original.team_strength,starting_lineup=dh))
        inp = MatchSimulationInput('FAKE-DH-GATE','FAKE-CUP',2026,
                                  team.team_strength.generation_seed,team,self.teams[1])
        result = MatchSimulator().simulate(inp)
        self.assertEqual(pitcher, result.team_participation[0].starting_designated_hitter_id)

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



class DHMatchStateTests(unittest.TestCase):
    def make(self, dual=False):
        from game_core.team_strength import DefensiveAssignment
        dh = 'P' if dual else 'DH'
        lineup = StartingLineup('FAKE-DH', 2026, tuple(
            LineupEntry(i+1, 'DH' if i == 0 else pos, dh if i == 0 else pos, 50.0)
            for i, pos in enumerate(STARTING_POSITIONS)
        ), tuple(DefensiveAssignment(pos, pos) for pos in STARTING_POSITIONS), dh)
        return TeamMatchState(lineup, {*STARTING_POSITIONS, 'DH', 'RP', 'B', 'X'})

    def ready(self, dual=False):
        state = self.make(dual)
        state.record_completed_plate_appearance(state.designated_hitter_id)
        return state

    def rejected(self, state, operation):
        import json
        before = json.dumps(state.to_dict(), sort_keys=True)
        with self.assertRaises(ValueError):
            operation()
        self.assertEqual(before, json.dumps(state.to_dict(), sort_keys=True))
        state.validate()

    def round_trip(self, state):
        import json
        from game_core.match_state import TeamMatchParticipation
        restored = TeamMatchState.from_dict(json.loads(json.dumps(state.to_dict())))
        self.assertEqual(state.to_dict(), restored.to_dict())
        self.assertEqual(state.retired_two_way_roles, restored.retired_two_way_roles)
        self.assertEqual(state.exited_player_ids, restored.exited_player_ids)
        self.assertEqual(state.dh_batting_required, restored.dh_batting_required)
        self.assertEqual(state.participation(), TeamMatchParticipation.from_dict(state.participation().to_dict()))
        return restored

    def test_normal_dh_has_ten_active_and_nine_defenders(self):
        s = self.make()
        self.assertEqual(10, len(s.active_player_ids))
        self.assertEqual(9, len(s.batting_order))
        self.assertNotIn('P', {b.player_id for b in s.batting_order})
        s.record_fielding_appearance()
        self.assertEqual(set(STARTING_POSITIONS), s.fielding_player_ids)
        self.assertNotIn('DH', s.fielding_player_ids)
        self.round_trip(s)

    def test_two_way_is_nine_people_not_two_players(self):
        s = self.make(True)
        self.assertEqual(9, len(s.active_player_ids))
        self.assertEqual('P', s.player_at_order(1))
        self.assertEqual('P', s.current_pitcher_id)
        self.round_trip(s)

    def test_declared_dh_is_required_at_start(self):
        s = self.make()
        with self.assertRaises(ValueError):
            TeamMatchState(replace(s.initial_lineup, designated_hitter_id=None), s.registered_player_ids)
        with self.assertRaises(ValueError):
            TeamMatchState(replace(s.initial_lineup, defense=()), s.registered_player_ids)

    def test_normal_pitcher_substitution_preserves_dh(self):
        s = self.make()
        s.change_pitcher('RP')
        self.assertEqual('DH', s.designated_hitter_id)
        self.assertEqual({'P'}, s.exited_player_ids)
        self.assertTrue(s.dh_batting_required)
        self.round_trip(s)

    def test_two_way_can_leave_pitching_and_remain_dh(self):
        s = self.make(True)
        s.change_pitcher('RP')
        self.assertEqual('P', s.designated_hitter_id)
        self.assertNotIn('P', s.exited_player_ids)
        self.assertNotIn('P', s.bench_player_ids)
        self.assertEqual({'pitcher'}, s.retired_two_way_roles)
        self.rejected(s, lambda: s.change_pitcher('P'))
        self.round_trip(s)

    def test_two_way_can_leave_dh_and_remain_pitcher(self):
        s = self.ready(True)
        s.substitute('P', 'B')
        self.assertEqual('P', s.current_pitcher_id)
        self.assertEqual('B', s.designated_hitter_id)
        self.assertNotIn('P', s.exited_player_ids)
        self.assertEqual({'batter'}, s.retired_two_way_roles)
        self.rejected(s, lambda: s.substitute('B', 'P'))
        self.round_trip(s)

    def test_two_way_exits_only_after_both_roles_end(self):
        s = self.ready(True)
        s.change_pitcher('RP')
        s.substitute('P', 'B')
        self.assertIn('P', s.exited_player_ids)
        self.rejected(s, lambda: s.change_pitcher('P'))
        self.rejected(s, lambda: s.substitute('B', 'P'))
        self.round_trip(s)

    def test_new_pitcher_batting_ends_dh_instead_of_creating_second_two_way(self):
        s = self.ready(True)
        s.transition(batting_changes={1: 'RP'}, defensive_changes={'P': 'RP'})
        self.assertIsNone(s.designated_hitter_id)
        self.assertEqual(9, len(s.active_player_ids))
        self.assertIn('P', s.exited_player_ids)
        self.round_trip(s)

    def test_dh_pinch_hitter_or_runner_inherits_slot(self):
        for incoming in ('B', 'X'):
            s = self.ready()
            s.substitute('DH', incoming)
            self.assertEqual(incoming, s.designated_hitter_id)
            self.assertEqual(incoming, s.player_at_order(1))
            self.assertIn('DH', s.exited_player_ids)
            self.round_trip(s)

    def test_dh_taking_field_ends_dh_and_assigns_pitcher_slot(self):
        s = self.make()
        self.rejected(s, lambda: s.change_positions({'CF': 'DH'}))
        s.change_positions({'CF': 'DH'}, batting_changes={8: 'P'})
        self.assertIsNone(s.designated_hitter_id)
        self.assertEqual('P', s.player_at_order(8))
        self.assertEqual('DH', s.player_for_position('CF'))
        self.assertIn('CF', s.exited_player_ids)
        self.assertFalse(s.dh_batting_required)
        self.round_trip(s)

    def test_successor_dh_fielding_and_new_pitcher_double_switch(self):
        for dual in (False, True):
            with self.subTest(dual=dual):
                s = self.ready(dual)
                old_dh = s.designated_hitter_id
                s.transition(batting_changes={1: 'B', 8: 'RP'},
                             defensive_changes={'CF': 'B', 'P': 'RP'})
                self.assertIsNone(s.designated_hitter_id)
                self.assertEqual('B', s.player_at_order(1))
                self.assertEqual('RP', s.player_at_order(8))
                self.assertEqual('B', s.player_for_position('CF'))
                self.assertEqual('RP', s.current_pitcher_id)
                self.assertEqual({old_dh, 'CF', 'P'}, s.exited_player_ids)
                self.assertEqual({b.player_id for b in s.batting_order}, s.active_player_ids)
                self.assertEqual(9, len(s.active_player_ids))
                self.assertFalse(s.dh_batting_required)
                self.round_trip(s)

    def test_successor_dh_fielding_requires_pitcher_batting_slot(self):
        s = self.ready()
        self.rejected(s, lambda: s.transition(
            batting_changes={1: 'B'}, defensive_changes={'CF': 'B', 'P': 'RP'}))

    def test_successor_dh_fielding_can_assign_retained_pitcher_to_fielder_slot(self):
        s = self.ready()
        s.transition(batting_changes={1: 'B', 8: 'P'}, defensive_changes={'CF': 'B'})
        self.assertIsNone(s.designated_hitter_id)
        self.assertEqual('P', s.current_pitcher_id)
        self.assertEqual('P', s.player_at_order(8))
        self.assertEqual('B', s.player_for_position('CF'))
        self.assertEqual({'DH', 'CF'}, s.exited_player_ids)
        self.round_trip(s)

    def test_successor_dh_fielding_does_not_waive_first_plate_appearance(self):
        for dual in (False, True):
            s = self.make(dual)
            self.rejected(s, lambda: s.transition(
                batting_changes={1: 'B', 8: 'RP'},
                defensive_changes={'CF': 'B', 'P': 'RP'}))
        s = self.make()
        self.rejected(s, lambda: s.transition(
            batting_changes={1: 'B', 8: 'P'}, defensive_changes={'CF': 'B'}))

    def test_successor_fielding_cannot_restore_retired_batting_role(self):
        s = self.ready(True)
        s.substitute('P', 'X')
        self.rejected(s, lambda: s.transition(
            batting_changes={1: 'B', 8: 'P'}, defensive_changes={'CF': 'B'}))
        restored = self.round_trip(s)
        self.rejected(restored, lambda: restored.transition(
            batting_changes={1: 'B', 8: 'P'}, defensive_changes={'CF': 'B'}))

    def test_successor_dh_without_fielding_survives_simultaneous_pitcher_change(self):
        s = self.ready()
        s.transition(batting_changes={1: 'B'}, defensive_changes={'P': 'RP'})
        self.assertEqual('B', s.designated_hitter_id)
        self.assertEqual(10, len(s.active_player_ids))
        self.assertEqual({'DH', 'P'}, s.exited_player_ids)
        self.round_trip(s)

    def test_timed_successor_dh_fielding_double_switch_replays(self):
        from game_core.match_state import ChangeMoment, CompletedPlateAppearanceMoment, replay_team_participation
        s = self.make()
        s.record_completed_plate_appearance('DH', moment=CompletedPlateAppearanceMoment(1, 'top', 2))
        s.transition(batting_changes={1: 'B', 8: 'RP'},
                     defensive_changes={'CF': 'B', 'P': 'RP'},
                     moment=ChangeMoment(2, 'bottom', 12))
        s.record_fielding_appearance()
        restored = replay_team_participation(s.participation(), 2026, s.registered_player_ids)
        self.assertEqual(s.to_dict(), restored.to_dict())
        self.round_trip(restored)

    def test_pitcher_moving_to_field_ends_dh(self):
        s = self.make()
        s.change_pitcher('RF', batting_changes={1: 'P'})
        self.assertIsNone(s.designated_hitter_id)
        self.assertEqual('RF', s.current_pitcher_id)
        self.assertEqual('P', s.player_for_position('RF'))
        self.assertIn('DH', s.exited_player_ids)
        self.round_trip(s)

    def test_fielder_pitching_without_old_pitcher_remaining_ends_dh(self):
        s = self.make()
        s.transition(batting_changes={1: 'B'}, defensive_changes={'P': 'RF', 'RF': 'B'})
        self.assertIsNone(s.designated_hitter_id)
        self.assertEqual('RF', s.current_pitcher_id)
        self.assertEqual({'P', 'DH'}, s.exited_player_ids)
        self.round_trip(s)

    def test_pitcher_pinch_hitting_or_running_only_for_dh(self):
        s = self.ready()
        s.substitute('DH', 'P')
        self.assertIsNone(s.designated_hitter_id)
        self.assertEqual(9, len(s.active_player_ids))
        self.round_trip(s)
        s = self.ready()
        self.rejected(s, lambda: s.transition(batting_changes={8: 'P'}))

    def test_dh_can_pitch_and_end_dh(self):
        s = self.make()
        s.change_pitcher('DH')
        self.assertIsNone(s.designated_hitter_id)
        self.assertEqual('DH', s.current_pitcher_id)
        self.assertIn('P', s.exited_player_ids)
        self.round_trip(s)

    def test_multiple_changes_have_explicit_batting_order(self):
        for pitcher_slot, bench_slot in ((8, 9), (9, 8)):
            s = self.make()
            s.transition(defensive_changes={'CF':'DH', 'RF':'LF', 'LF':'B'},
                         batting_changes={pitcher_slot:'P', bench_slot:'B'})
            self.assertIsNone(s.designated_hitter_id)
            self.assertEqual('P', s.player_at_order(pitcher_slot))
            self.assertEqual({'CF','RF'}, s.exited_player_ids)
            self.round_trip(s)

    def test_active_batter_cannot_be_reordered_by_double_switch(self):
        s = self.ready()
        self.rejected(s, lambda: s.transition(batting_changes={2:'1B',3:'C'}))

    def test_first_at_bat_required_for_normal_and_two_way_dh(self):
        for dual in (False, True):
            s = self.make(dual)
            self.rejected(s, lambda: s.substitute(s.designated_hitter_id, 'B'))
            s.record_completed_plate_appearance(s.designated_hitter_id)
            s.substitute(s.designated_hitter_id, 'B')
            self.assertFalse(s.dh_batting_required)
            self.round_trip(s)

    def test_own_starter_leaving_does_not_waive_two_way_batting_obligation(self):
        s = self.make(True)
        s.change_pitcher('RP')
        self.rejected(s, lambda: s.substitute('P', 'B'))
        restored = self.round_trip(s)
        self.rejected(restored, lambda: restored.substitute('P', 'B'))

    def test_opposing_starter_change_waives_obligation(self):
        for dual in (False, True):
            s = self.make(dual)
            s.record_opposing_starter_replaced()
            s.substitute(s.designated_hitter_id, 'B')
            self.round_trip(s)

    def test_umpire_approved_injury_or_illness_exception(self):
        for reason in ('injury', 'illness'):
            s = self.make(True)
            s.change_pitcher('RP')
            self.rejected(s, lambda: s.substitute('P','B', medical_exception=reason))
            s.substitute('P','B', medical_exception=reason, umpire_approved=True)
            self.round_trip(s)
        s = self.make()
        self.rejected(s, lambda: s.substitute('DH','B', medical_exception='fatigue', umpire_approved=True))
        self.rejected(s, lambda: s.substitute('DH','B', umpire_approved=True))

    def test_two_way_moving_to_other_defense_ends_obligation(self):
        s = self.make(True)
        s.transition(defensive_changes={'P':'RP', 'CF':'P'}, batting_changes={8:'RP'})
        self.assertIsNone(s.designated_hitter_id)
        self.assertFalse(s.dh_batting_required)
        s.substitute('P', 'B')
        self.round_trip(s)

    def test_official_case_four_requires_pitcher_replacement_after_dh_role_retired(self):
        s = self.ready(True)
        s.substitute('P', 'B')
        self.rejected(s, lambda: s.transition(defensive_changes={'LF':'B'}, batting_changes={7:'P'}))
        s.transition(defensive_changes={'LF':'B','P':'RP'}, batting_changes={7:'RP'})
        self.assertEqual({'P','LF'}, s.exited_player_ids)
        self.round_trip(s)

    def test_retired_pitcher_can_field_elsewhere_but_cannot_pitch_again(self):
        s = self.make(True)
        s.change_pitcher('RP')
        s.change_positions({'CF':'P'}, batting_changes={8:'RP'})
        self.assertEqual('P', s.player_for_position('CF'))
        self.rejected(s, lambda: s.change_pitcher('P'))
        restored = self.round_trip(s)
        self.rejected(restored, lambda: restored.change_pitcher('P'))

    def test_duplicate_fielding_batting_and_exited_reentry_are_atomic(self):
        s = self.ready()
        for fn in (lambda:s.transition(batting_changes={2:'DH'}),
                   lambda:s.transition(defensive_changes={'CF':'RF'}),
                   lambda:s.transition(defensive_changes={'CF':'UNKNOWN'}),
                   lambda:s.transition(batting_changes={True:'B'})):
            self.rejected(s, fn)
        s.substitute('DH', 'B')
        self.rejected(s, lambda:s.substitute('B','DH'))
        self.rejected(s, lambda:s.transition(batting_changes={1:'DH'},defensive_changes={'CF':'DH'}))

    def test_dh_cannot_be_reintroduced_after_loss(self):
        s = self.ready()
        s.substitute('DH','P')
        self.rejected(s, lambda:s.transition(batting_changes={1:'B'}))
        self.assertIsNone(s.designated_hitter_id)
        self.round_trip(s)

    def test_initial_duplicate_defense_and_wrong_pitcher_are_rejected(self):
        s = self.make()
        defense = s.initial_lineup.defense
        for changed in (defense[:-1], (replace(defense[0],player_id='C'),*defense[1:])):
            with self.assertRaises(ValueError):
                TeamMatchState(replace(s.initial_lineup,defense=tuple(changed)),s.registered_player_ids)
        with self.assertRaises(ValueError):
            TeamMatchState(s.initial_lineup,s.registered_player_ids,actual_pitcher_id='RP')

    def test_dh_pitcher_operation_cannot_claim_another_p_assignment(self):
        s = self.make()
        self.rejected(s, lambda:s.change_pitcher('RP', defensive_changes={'P':'P'}))
        self.rejected(s, lambda:s.substitute('DH','DH'))
        self.rejected(s, lambda:s.substitute('CF','P'))

    def test_snapshot_cannot_claim_fielding_by_a_pure_dh(self):
        s = self.make()
        snapshot = s.to_dict()
        snapshot['participation']['fielding_player_ids'] = ['DH']
        with self.assertRaises(ValueError):
            TeamMatchState.from_dict(snapshot)

    def test_defense_and_batting_inputs_are_immutable_copies(self):
        s = self.make()
        entries = list(s.initial_lineup.entries)
        defense = list(s.initial_lineup.defense)
        lineup = replace(s.initial_lineup, entries=entries, defense=defense)
        state = TeamMatchState(lineup, s.registered_player_ids)
        entries.clear()
        defense.clear()
        state.validate()
        self.assertEqual(9, len(state.initial_lineup.entries))
        self.assertEqual(9, len(state.initial_lineup.defense))

    def test_defense_only_pitcher_must_be_registered_and_available(self):
        s = self.make()
        with self.assertRaises(ValueError):
            TeamMatchState(s.initial_lineup, s.registered_player_ids - {'P'})
        with self.assertRaises(ValueError):
            TeamMatchState(s.initial_lineup, s.registered_player_ids,
                           available_player_ids=s.registered_player_ids - {'P'})

    def test_non_dh_game_cannot_add_a_batting_only_player(self):
        s = self.make()
        plain = StartingLineup('FAKE-DH',2026,tuple(
            LineupEntry(i+1,pos,pos,50.0) for i,pos in enumerate(STARTING_POSITIONS)))
        state = TeamMatchState(plain,s.registered_player_ids)
        self.rejected(state,lambda:state.transition(batting_changes={1:'DH'}))
        self.assertIsNone(state.designated_hitter_id)

    def test_timed_dh_participation_replays(self):
        from game_core.match_state import ChangeMoment, CompletedPlateAppearanceMoment, replay_team_participation
        s = self.make(True)
        s.change_pitcher('RP',moment=ChangeMoment(1,'top',1))
        s.record_completed_plate_appearance('P',moment=CompletedPlateAppearanceMoment(1,'bottom',4))
        s.substitute('P','B',moment=ChangeMoment(3,'bottom',20))
        s.record_fielding_appearance()
        restored = replay_team_participation(s.participation(),2026,s.registered_player_ids)
        self.assertEqual(s.to_dict(),restored.to_dict())


if __name__ == '__main__':
    unittest.main()
