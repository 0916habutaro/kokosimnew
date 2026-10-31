"""正式な試合画面が当時の配置を表示し、現在の本職から推測しないことを確認する。"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from game_core.highlights import game_highlights
from game_core.match_state import ChangeMoment, replay_team_participation
from game_core.players import Player
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.screen.app import ScreenApi
from phase2_engine.screen.competition_views import match_detail
from phase2_engine.screen.data import GameScreenData
import test_live_match_state as fixtures
import test_match_participation_history as history_fixtures


class MatchLineupScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.LiveMatchStateTests.setUpClass()
        cls.fixture = fixtures.LiveMatchStateTests()
        cls.names = {team.school_id: f'架空第{i + 1}校' for i, team in enumerate(cls.fixture.teams)}
        cls.players = {
            team.school_id: {
                p.player_id: Player(p.player_id, team.school_id, 'FAKE-PROGRAM', f'架空選手{i + 1:02d}',
                                    'test', '13', 2, 2025, i + 1, 'RF', 'outfielder', 'R', 'R',
                                    'active_core', 20261029)
                for i, p in enumerate(team.player_abilities)
            } for team in cls.fixture.teams
        }

    @classmethod
    def row(cls, result):
        return dict(competition_id=result.competition_id, competition_name='架空テスト大会',
                    match_id=result.match_id, match_date='2026-07-05', round_name='決勝',
                    team1_id=result.team1_school_id, team2_id=result.team2_school_id,
                    team1_score=result.team1_score, team2_score=result.team2_score,
                    winner_id=result.winner_id, loser_id=result.loser_id,
                    score_source=result.score_source, status='completed')

    def detail(self, result):
        return {**result.to_dict(), 'highlights': game_highlights(result.events)}

    def view(self, result, detail=None, players=None):
        return match_detail(self.row(result), detail if detail is not None else self.detail(result),
                            self.names.get, (players or self.players).get, school_year=2026)

    def relief(self):
        staff = self.fixture.staff(self.fixture.teams[1])
        return self.fixture.play(top=['walk', 'walk', 'home_run'], changes=((staff[0], 1), (staff[1], 1)))[0]

    def test_starting_order_and_nine_positions_come_from_record_not_primary_position(self):
        result, _ = self.fixture.play()
        view = self.view(result)
        for record in result.team_participation:
            rows = view['lineups'][record.school_id]['players']
            self.assertEqual(list(range(1, 10)), [row['batting_order'] for row in rows])
            self.assertEqual(9, len({row['player_id'] for row in rows}))
            self.assertEqual(9, len({row['position_code'] for row in rows}))
            actual = {row['player_id']: row['position_code'] for row in rows}
            self.assertEqual('P', actual[record.starting_pitcher_id])
            self.assertEqual('RF', self.players[record.school_id][record.starting_pitcher_id].primary_position)
            pitcher = next(row for row in view['batting'][record.school_id]
                           if row['player_id'] == record.starting_pitcher_id)
            self.assertEqual('投', pitcher['position'])
        self.assertTrue(view['has_lineup_record'])

    def test_pitch_limit_replacement_is_actual_starter_without_substitution_history(self):
        team = self.fixture.teams[1]
        old, new = self.fixture.staff(team)[:2]
        result, _ = self.fixture.play(pitch_allowances={old: 60}, regulation_innings=1)
        view = self.view(result)
        self.assertEqual(new, view['lineups'][team.school_id]['starting_pitcher_id'])
        self.assertNotIn(old, {row['player_id'] for row in view['lineups'][team.school_id]['players']})
        self.assertEqual([], view['lineup_changes'])

    def test_relief_history_and_shared_position_and_slot_keep_all_stat_rows(self):
        result = self.relief()
        view = self.view(result)
        team = self.fixture.teams[1].school_id
        staff = self.fixture.staff(self.fixture.teams[1])[:3]
        rows = {row['player_id']: row for row in view['batting'][team]}
        self.assertTrue(set(staff) <= set(rows))
        self.assertEqual(1, len({rows[pid]['batting_order'] for pid in staff}))
        self.assertEqual({'投'}, {rows[pid]['position'] for pid in staff})
        self.assertEqual([True, True, False], [rows[pid]['exited'] for pid in staff])
        # 同じ「投」の3行は時間の異なる守備履歴。各打席で同時に投げるのは1人。
        from game_core.match_state import apply_lineup_change
        record = next(r for r in result.team_participation if r.school_id == team)
        state = replay_team_participation(replace(record, changes=(), fielding_player_ids=()), 2026,
                                          registered=self.players[team])
        pending = iter(record.changes)
        change = next(pending, None)
        actual_pitchers = set()
        for event in result.events:
            while change is not None and change.moment.next_plate_appearance_no == event.plate_appearance_no:
                apply_lineup_change(state, change)
                change = next(pending, None)
            if event.defense_school_id == team:
                pitchers = [a.player_id for a in state.defensive_alignment if a.defensive_position == 'P']
                self.assertEqual([event.pitcher_id], pitchers)
                actual_pitchers.update(pitchers)
        self.assertEqual(set(staff), actual_pitchers)
        for shown in view['lineup_changes']:
            event = result.events[shown['next_plate_appearance_no'] - 1]
            self.assertEqual((event.inning, '表' if event.half == 'top' else '裏'),
                             (shown['inning'], shown['half']))
            self.assertEqual(event.pitcher_id, shown['incoming']['player_id'])
            self.assertIsNotNone(shown['outgoing'])
        self.assert_stats_unchanged(result, view)

    def assert_stats_unchanged(self, result, view):
        for team in self.fixture.teams:
            sid = team.school_id
            original = {row.player_id: row.to_dict() for row in result.batter_stats if row.school_id == sid}
            self.assertEqual(len(original), len(view['batting'][sid]))
            for row in view['batting'][sid]:
                for key in ('at_bats', 'hits', 'runs', 'rbi', 'home_runs', 'walks', 'strikeouts', 'stolen_bases'):
                    self.assertEqual(original[row['player_id']][key], row[key])
            original = {row.player_id: row.to_dict() for row in result.pitcher_stats if row.school_id == sid}
            self.assertEqual(len(original), len(view['pitching'][sid]))
            for row in view['pitching'][sid]:
                for key in ('batters_faced', 'hits_allowed', 'runs_allowed', 'earned_runs', 'walks',
                            'strikeouts', 'home_runs_allowed', 'pitches'):
                    self.assertEqual(original[row['player_id']][key], row[key])

    def test_fielder_pitching_and_original_pitcher_remaining_show_position_sequences(self):
        team = self.fixture.teams[0]
        old = self.fixture.staff(team)[0]
        new, allowances = self.fixture.fielder_allowances(team)
        allowances[old] = 100
        sim = fixtures.ObservedSimulator({self.fixture.teams[1].school_id: ['home_run']})
        sim._pitches = lambda *args: 100
        result = sim.simulate(self.fixture.match(), pitch_allowances=allowances)
        view = self.view(result)
        rows = {row['player_id']: row for row in view['batting'][team.school_id]}
        self.assertEqual('投→遊', rows[old]['position'])
        self.assertEqual('遊→投', rows[new]['position'])
        self.assertFalse(rows[old]['exited'])
        change = view['lineup_changes'][0]
        self.assertIsNone(change['outgoing'])
        self.assertIsNone(change['incoming'])
        self.assertEqual({(old, '投', '遊'), (new, '遊', '投')},
                         {(p['player_id'], p['before'], p['after']) for p in change['moves']})
        self.assert_stats_unchanged(result, view)

    def test_position_only_exchange_uses_existing_state_operations(self):
        result, _ = self.fixture.play()
        detail = self.detail(result)
        state = replay_team_participation(result.team_participation[0], 2026)
        short = state.player_for_position('SS')
        second = state.player_for_position('2B')
        pa = 1
        for half in result.inning_scores:
            if half.inning == 2 and half.half == 'bottom':
                break
            pa += half.plate_appearances
        state.swap_positions('SS', '2B', moment=ChangeMoment(2, 'bottom', pa))
        detail['team_participation'][0] = state.participation().to_dict()
        view = self.view(result, detail)
        rows = {row['player_id']: row for row in view['batting'][state.school_id]}
        self.assertEqual(('遊→二', '二→遊'), (rows[short]['position'], rows[second]['position']))
        self.assertEqual('position_change', view['lineup_changes'][0]['kind'])
        self.assertFalse(any(row['exited'] for row in rows.values()))

    def test_two_changes_before_same_plate_appearance_do_not_claim_unplayed_position(self):
        result, _ = self.fixture.play()
        detail = self.detail(result)
        state = replay_team_participation(result.team_participation[0], 2026)
        old = state.current_pitcher_id
        pa = result.inning_scores[0].plate_appearances + 1
        moment = ChangeMoment(1, 'bottom', pa)
        state.swap_positions('P', 'SS', moment=moment)
        state.swap_positions('P', 'SS', moment=moment)
        detail['team_participation'][0] = state.participation().to_dict()
        view = self.view(result, detail)
        self.assertEqual('投', next(r['position'] for r in view['batting'][state.school_id] if r['player_id'] == old))
        self.assertEqual(2, len(view['lineup_changes']))

    def test_no_changes_and_no_configuration_record_are_different(self):
        result, _ = self.fixture.play()
        detail = self.detail(result)
        recorded = self.view(result, detail)
        self.assertTrue(recorded['has_lineup_record'])
        self.assertEqual([], recorded['lineup_changes'])
        detail.pop('team_participation')
        unknown = self.view(result, detail)
        self.assertFalse(unknown['has_lineup_record'])
        self.assertTrue(all(record is None for record in unknown['lineups'].values()))
        self.assertTrue(all(r['position'] == '配置記録なし' for rows in unknown['batting'].values() for r in rows))
        self.assert_stats_unchanged(result, unknown)

    def test_view_does_not_change_saved_records_or_depend_on_current_primary_position(self):
        result = self.relief()
        detail = self.detail(result)
        before = deepcopy(detail)
        first = self.view(result, detail)
        changed = {sid: {pid: replace(p, primary_position='C') for pid, p in rows.items()}
                   for sid, rows in self.players.items()}
        self.assertEqual(first, self.view(result, detail, changed))
        self.assertEqual(before, detail)

    def data(self, result, archive=None):
        row = self.row(result)
        detail = self.detail(result)
        provider = lambda cid, sid: SimpleNamespace(players=tuple(self.players[sid].values()))
        season = SimpleNamespace(year=2026, competitions={result.competition_id: SimpleNamespace(
            matches={result.match_id: SimpleNamespace(public_dict=lambda: dict(row))})},
            pending_match_details={f'{result.competition_id}:{result.match_id}': detail},
            engine=SimpleNamespace(main_match_resolver=SimpleNamespace(member_provider=provider)))
        data = GameScreenData.__new__(GameScreenData)
        data.session = SimpleNamespace(state=season, slot_id='fake-screen')
        data.service = SimpleNamespace(historical_match=lambda slot, year, cid, mid: archive.get_match(year, cid, mid))
        data.team_name = lambda sid, *args: self.names[sid]
        data._competition_name = lambda *args: '架空テスト大会'
        data.competition_names = lambda cid, fallback: '架空テスト大会'
        data._mercy = [[5, 10], [7, 7]]
        return data

    def test_current_and_packed_sealed_previous_year_routes_show_identical_recorded_configuration(self):
        result = self.relief()
        with tempfile.TemporaryDirectory() as tmp:
            archive = HistoricalMatchArchive(Path(tmp) / 'history.sqlite3')
            archive.sync(year=2026, rng_seed=20261029, resolver_contract='players_v1', plan_fingerprint='fake',
                         completed=[{**self.row(result), 'ability_detail': self.detail(result)}])
            data = self.data(result, archive)
            current = ScreenApi(data).match(2026, result.competition_id, result.match_id)
            archive.pack_competition(2026, result.competition_id)
            archive.seal_year(2026, expected_match_count=1)
            current_players = {sid: [replace(p, display_name='現在の別名') for p in rows.values()]
                               for sid, rows in self.players.items()}
            data.session.state = SimpleNamespace(year=2027, rosters=SimpleNamespace(closed_through=2026,
                roster=lambda year, sid: SimpleNamespace(players=current_players[sid])))
            data.service.closed_roster = lambda slot, year, sid: [p.to_dict() for p in self.players[sid].values()] if year == 2026 else []
            closed = ScreenApi(data).match(2026, result.competition_id, result.match_id)
            for key in ('school_year', 'lineups', 'lineup_changes', 'batting', 'pitching', 'board', 'highlights'):
                self.assertEqual(current[key], closed[key], key)

    def test_old_match_player_link_can_resolve_by_match_year_through_existing_api(self):
        result, _ = self.fixture.play()
        data = self.data(result)
        data.config_root = Path(__file__).resolve().parents[1] / 'config'
        data.prefectures = {'13': '架空県'}
        data.names = self.names.get
        data._school_details = lambda sid, year: []
        data.session.state = SimpleNamespace(year=2126, rosters=SimpleNamespace(closed_through=2125,
            pitch_types=lambda: {}, roster=lambda year, sid: SimpleNamespace(players=())))
        data.service.closed_roster = lambda slot, year, sid: [
            {**p.to_dict(), 'abilities': None, 'growth_type': None} for p in self.players[sid].values()
        ] if year == 2026 else []
        sid = result.team1_school_id
        pid = result.team_participation[0].starting_lineup[0].player_id
        api = ScreenApi(data)
        with self.assertRaisesRegex(ValueError, 'その選手はいません'):
            data.player(sid, pid)
        player = api.player(sid, pid, 2026)
        self.assertNotIn('error', player)
        self.assertEqual(self.players[sid][pid].display_name, player['name'])
        self.assertEqual('卒業', player['status'])
        self.assertEqual(pid, player['player_id'])


class DHMatchScreenTests(history_fixtures.DHHistoryFixtures, unittest.TestCase):
    def test_no_dh_explicit_transition_also_preserves_batting_slot_and_saved_view(self):
        from game_core.match_simulator import LineupAdjustment
        team = self.dh.by_mode['none'][0]
        lineup = team.team_strength.starting_lineup
        slot = next(e.batting_order for e in lineup.entries if e.defensive_position == 'CF')
        bench = next(p.player_id for p in team.player_abilities if p.player_id not in lineup.starter_ids)
        plan = LineupAdjustment(2, team.school_id, ((slot, bench),), (('CF', bench),))
        _, result, _, row = self.game('none', lineup_changes=(plan,))
        view = self.view(row)
        self.assertEqual(view, self.view(row, self.saved(row)))
        batter = next(p for p in view['batting'][result.team1_school_id] if p['player_id'] == bench)
        self.assertEqual((slot, '中'), (batter['batting_order'], batter['position']))

    def test_mixed_modes_show_only_the_dh_team_pitcher_outside_order(self):
        teams = (self.dh.by_mode['none'][0], self.dh.by_mode['normal'][1])
        _, result, _, row = self.game(teams=teams)
        view = self.view(row)
        self.assertNotIn('pitcher', view['lineups'][result.team1_school_id])
        self.assertIn('pitcher', view['lineups'][result.team2_school_id])
        self.assertEqual(view, self.view(row, self.saved(row)))

    def view(self, row, detail=None):
        players = {team.school_id: {p.player_id: SimpleNamespace(display_name=f'架空選手{i+1:02d}', primary_position='RF')
                                   for i, p in enumerate(team.player_abilities)} for team in self.dh.by_mode['normal']}
        names = {sid: f'架空第{i+1}校' for i, sid in enumerate(players)}
        return match_detail(row, row['ability_detail'] if detail is None else detail,
                            names.get, players.get, school_year=2026)

    def test_normal_dh_has_nine_batting_slots_and_separate_pitcher_tenth_row(self):
        _, result, _, row = self.game()
        view = self.view(row)
        for record in result.team_participation:
            lineup = view['lineups'][record.school_id]
            self.assertEqual(list(range(1, 10)), [p['batting_order'] for p in lineup['players']])
            self.assertEqual(record.starting_pitcher_id, lineup['pitcher']['player_id'])
            self.assertIsNone(lineup['pitcher']['batting_order'])
            self.assertEqual(10, len({p['player_id'] for p in lineup['players']} | {lineup['pitcher']['player_id']}))
            self.assertNotIn(record.starting_pitcher_id, {p['player_id'] for p in view['batting'][record.school_id]})
            dh = next(p for p in view['batting'][record.school_id] if p['player_id'] == record.starting_designated_hitter_id)
            self.assertEqual(('DH', False, '打撃専任'), (dh['position'], dh['fielded'], dh['role_label']))

    def test_two_way_is_one_starting_person_with_batting_and_pitching_stats(self):
        _, result, _, row = self.game('pitcher')
        view = self.view(row)
        for record in result.team_participation:
            lineup = view['lineups'][record.school_id]
            self.assertNotIn('pitcher', lineup)
            dual = next(p for p in lineup['players'] if p['player_id'] == record.starting_pitcher_id)
            self.assertEqual('投・DH', dual['position'])
            self.assertEqual(9, len({p['player_id'] for p in lineup['players']}))
            for table in ('batting', 'pitching'):
                self.assertEqual(1, sum(p['player_id'] == dual['player_id'] for p in view[table][record.school_id]))

    def test_internal_rule_notifications_are_not_displayed_as_substitutions(self):
        _, result, _, row = self.game()
        self.assertTrue(any(r.changes for r in result.team_participation))
        self.assertEqual([], self.view(row)['lineup_changes'])

    def test_two_way_partial_and_full_exit_labels_are_distinct(self):
        from game_core.match_simulator import LineupAdjustment
        team = self.dh.by_mode['pitcher'][1]
        lineup = team.team_strength.starting_lineup
        bench = [p.player_id for p in team.player_abilities if p.player_id not in lineup.starter_ids]
        rp = next(pid for pid in fixtures.MatchSimulator._pitcher_order(team) if pid in bench)
        batter = next(pid for pid in bench if pid != rp)
        for bats, defense, expected in (((), (('P', rp),), {'投手'}), (((1, batter),), (), {'打撃'}),
                                        (((1, batter),), (('P', rp),), {'投手', '打撃'})):
            _, _, _, row = self.game('pitcher', regulation_innings=2,
                lineup_changes=(LineupAdjustment(6, team.school_id, bats, defense),))
            view = self.view(row)
            event = next(c for c in view['lineup_changes'] if c['school_id'] == team.school_id)
            self.assertEqual(expected, {p['role'] for p in event['roles_ended']})
            self.assertEqual(len(expected) == 2, lineup.designated_hitter_id in {p['player_id'] for p in event['fully_exited']})

    def test_successor_fielding_dh_loss_and_explicit_pitcher_batting_slot_are_visible(self):
        (_, result, _, row), slot, rp, batter = self.double_switch()
        view = self.view(row)
        event = view['lineup_changes'][0]
        self.assertTrue(event['dh_ended'])
        self.assertIn('DH解除', event['label'])
        self.assertEqual({1, slot}, {c['batting_order'] for c in event['batting_changes']})
        pitcher = next(b for b in view['batting'][result.team1_school_id] if b['player_id'] == rp)
        self.assertEqual((slot, '投'), (pitcher['batting_order'], pitcher['position']))
        fielder = next(b for b in view['batting'][result.team1_school_id] if b['player_id'] == batter)
        self.assertEqual('中', fielder['position'])

    def test_three_modes_have_identical_screen_data_before_save_and_after_packed_sealed_read(self):
        for mode in ('none', 'normal', 'pitcher'):
            with self.subTest(mode=mode):
                _, result, _, row = self.game(mode)
                before = self.view(row)
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp)/'history.sqlite3'
                    archive = HistoricalMatchArchive(path)
                    self.sync(archive, [row])
                    archive.pack_competition(2026, result.competition_id)
                    archive.seal_year(2026, expected_match_count=1)
                    loaded = HistoricalMatchArchive(path).get_match(2026, result.competition_id, result.match_id)
                    self.assertEqual(before, self.view(row, loaded))

    def test_role_exit_and_double_switch_screen_data_survive_json_and_codec(self):
        from phase2_engine.historical_match_archive import compact_payload, expand_payload
        import json
        (_, _, _, row), _, _, _ = self.double_switch()
        loaded = expand_payload(json.loads(json.dumps(compact_payload(self.saved(row)))))
        self.assertEqual(self.view(row), self.view(row, loaded))


if __name__ == '__main__':
    unittest.main()
