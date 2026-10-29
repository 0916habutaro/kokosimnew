"""守備だけの出場を公式戦経験へ含め、試合直後の怪我の抽選順を維持する。"""
from collections import Counter
from datetime import date
import pickle
import random
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from game_core.injuries import Injury, injury_model
from game_core.match_contract import BatterGameStats, MatchSimulationInput, PitcherGameStats
from game_core.roster_book import RosterBook
from game_core.tournament_bridge import AbilityMatchResolver
from test_pitcher_run_accounting import _ScriptedSimulator
from test_roster_book import TEAMS


def make_bridge(*, seed=7, year=2026, level='none', book=None):
    repo = SimpleNamespace(team=TEAMS.__getitem__, schools=dict.fromkeys(TEAMS), competitions={})
    if book is None:
        book = RosterBook(repo.team, first_year=2026, career_seed=seed)
        book.injury_level = level
    book.bind(repo.team)
    book.school_ids = tuple(TEAMS)
    members = lambda cid, sid: SimpleNamespace(players=book.roster(year, sid).players)
    bridge = AbilityMatchResolver(repo, member_provider=members, team_generation_seed=seed)
    bridge.ability_generator.source = book
    bridge.season_state = SimpleNamespace(current_date=date(year, 7, 5), pitch_log={})
    for sid in TEAMS:
        book.roster(year, sid)
    return book, bridge


def short_game(bridge, *, year=2026, number=0, allowances=None, relief=False):
    seed = bridge.ability_generator.source.career_seed
    cid = f'FAKE-EXPERIENCE-{year}'
    teams = [bridge.team_input(school_id=sid, reference_year=year, generation_seed=seed,
                               competition_id=cid) for sid in TEAMS]
    first = teams[1].team_strength.pitching_staff.ace_player_id
    sim = _ScriptedSimulator({teams[1].school_id: ['home_run']}, [(first, 1)] if relief else [])
    inp = MatchSimulationInput(f'EXP-{year}-{number}', cid, year, seed, *teams)
    return sim.simulate(inp, regulation_innings=1, pitch_allowances=allowances)


def role_ids(result):
    batting = {s.player_id for s in result.batter_stats if s.plate_appearances > 0}
    pitching = {s.player_id for s in result.pitcher_stats if s.batters_faced > 0}
    fielding = {pid for team in result.team_participation for pid in team.fielding_player_ids}
    return batting, pitching, fielding


def state_snapshot(book):
    return {
        sid: {key: (bytes(s.values), s.growth_type, s.potential, s.games, s.season_games, tuple(s.injuries))
              for key, s in rows.items()}
        for sid, rows in book._states.items()
    }


def role_fixture(book, *, number=0):
    a, b = TEAMS
    players = book.roster(2026, a).players
    # 打撃のみ／登板のみ／守備のみ／打撃＋守備／打撃＋投球／交代済み。
    batting = [players[i] for i in (0, 3, 4, 5)]
    pitching = [players[i] for i in (1, 4)]
    fielding = [players[i] for i in (1, 2, 3, 4, 5)]
    result = SimpleNamespace(
        match_id=f'ROLES-{number}', team1_school_id=a, team2_school_id=b,
        batter_stats=tuple(BatterGameStats(p.player_id, a, plate_appearances=int(p in batting))
                           for p in players[:8]),
        pitcher_stats=tuple(PitcherGameStats(p.player_id, a, batters_faced=1, pitches=50) for p in pitching),
        team_participation=(SimpleNamespace(school_id=a, fielding_player_ids=tuple(p.player_id for p in fielding)),
                            SimpleNamespace(school_id=b, fielding_player_ids=())),
    )
    return result, players


class CountingRandom(random.Random):
    def __init__(self, seed):
        super().__init__(seed)
        self.calls = 0

    def random(self):
        self.calls += 1
        return super().random()


class FieldingExperienceTests(unittest.TestCase):
    def test_role_union_counts_each_appeared_player_once_and_ignores_zero_stat_bench(self):
        book, bridge = make_bridge()
        result, players = role_fixture(book)
        bridge._record_games('FAKE-CUP', result)
        for i, player in enumerate(players):
            expected = int(i < 6)
            self.assertEqual((expected, expected), (book.state(player).games, book.state(player).season_games), i)

    def test_duplicate_roles_and_members_do_not_add_experience_or_injury_entries_twice(self):
        book, bridge = make_bridge()
        result, players = role_fixture(book)
        provider = bridge.member_provider
        bridge.member_provider = lambda cid, sid: SimpleNamespace(players=(
            *provider(cid, sid).players, *provider(cid, sid).players,
        ))
        with patch.object(book, 'after_game', wraps=book.after_game) as injury:
            bridge._record_games('FAKE-CUP', result)
        self.assertTrue(all(book.state(p).games == 1 for p in players[:6]))
        entries = injury.call_args.args[0]
        self.assertTrue(all(n == 1 for n in Counter(p.player_id for p, *_ in entries).values()))
        self.assertEqual(6, len(entries))

    def test_actual_short_game_records_fielding_only_players_without_counting_the_bench(self):
        book, bridge = make_bridge()
        result = short_game(bridge)
        before = result.to_dict()
        batting, pitching, fielding = role_ids(result)
        self.assertTrue(fielding - batting - pitching)
        bridge._record_games(result.competition_id, result)
        for sid in TEAMS:
            for player in book.roster(2026, sid).players:
                self.assertEqual(int(player.player_id in batting | pitching | fielding), book.state(player).games)
        self.assertEqual(before, result.to_dict())

    def test_fielding_only_injury_targets_follow_both_schools_previous_targets(self):
        book, bridge = make_bridge()
        result = short_game(bridge)
        batting, pitching, fielding = role_ids(result)
        previous = batting | pitching
        members = [p for sid in TEAMS for p in book.roster(2026, sid).players]
        expected = [p.player_id for p in members if p.player_id in previous]
        extra = [p.player_id for p in members if p.player_id in fielding - previous]
        self.assertTrue(extra)
        with patch.object(book, 'after_game') as after:
            bridge._record_games(result.competition_id, result)
        self.assertEqual(expected + extra, [p.player_id for p, *_ in after.call_args.args[0]])

    def test_retired_pitcher_and_replacement_both_keep_one_appearance(self):
        book, bridge = make_bridge()
        result = short_game(bridge, relief=True)
        change = result.team_participation[1].changes[0]
        bridge._record_games(result.competition_id, result)
        members = {p.player_id: p for sid in TEAMS for p in book.roster(2026, sid).players}
        for pid in (change.outgoing_player_id, change.incoming_player_id):
            self.assertEqual((1, 1), (book.state(members[pid]).games, book.state(members[pid]).season_games))

    def test_pregame_bench_replacement_does_not_credit_unused_planned_starter(self):
        book, bridge = make_bridge()
        sid = list(TEAMS)[1]
        team = bridge.team_input(school_id=sid, reference_year=2026, generation_seed=7,
                                 competition_id='FAKE-EXPERIENCE-2026')
        planned = team.team_strength.starting_lineup.player_for_position('P')
        result = short_game(bridge, allowances={planned: 0})
        self.assertNotEqual(planned, result.team_participation[1].starting_pitcher_id)
        self.assertNotIn(planned, set.union(*role_ids(result)))
        bridge._record_games(result.competition_id, result)
        player = next(p for p in book.roster(2026, sid).players if p.player_id == planned)
        self.assertEqual((0, 0), (book.state(player).games, book.state(player).season_games))

    def test_planned_pitcher_who_stays_in_field_is_credited_despite_no_pa_or_bf(self):
        book, bridge = make_bridge()
        sid = list(TEAMS)[1]
        team = bridge.team_input(school_id=sid, reference_year=2026, generation_seed=7,
                                 competition_id='FAKE-EXPERIENCE-2026')
        planned = team.team_strength.starting_lineup.player_for_position('P')
        fielder = team.team_strength.starting_lineup.player_for_position('SS')
        limits = {p.player_id: (10000 if p.player_id == fielder else 0) for p in team.player_abilities}
        result = short_game(bridge, allowances=limits)
        batting, pitching, fielding = role_ids(result)
        self.assertIn(planned, fielding - batting - pitching)
        bridge._record_games(result.competition_id, result)
        player = next(p for p in book.roster(2026, sid).players if p.player_id == planned)
        self.assertEqual(1, book.state(player).games)

    def test_fielding_only_injury_draws_follow_all_previous_targets_without_changing_their_results(self):
        book, bridge = make_bridge(level='normal')
        result, players = role_fixture(book)
        book.state(players[0]).injuries.append(Injury(bridge.season_state.current_date, 4, 1))
        baseline = pickle.loads(pickle.dumps(book))
        baseline.bind(TEAMS.__getitem__)
        old_ids = {p.player_id for i, p in enumerate(players) if i in (0, 1, 3, 4, 5)}
        pitches = {p.player_id: p.pitches for p in result.pitcher_stats}
        expected_entries = [(p, pitches.get(p.player_id, 0), 0, 0) for p in players if p.player_id in old_ids]
        expected_rng, actual_rng = CountingRandom(123), CountingRandom(123)
        # 必ず重さ・日数まで抽選させ、抽選対象外の既往の怪我も含めて消費を比較する。
        with patch.object(injury_model(), 'match_chance', return_value=(1.0, False)):
            baseline.after_game(expected_entries, day=bridge.season_state.current_date, rng=expected_rng)
            previous_calls = expected_rng.calls
            previous_injuries = {p.player_id: tuple(baseline.state(p).injuries) for p in players}
            fielding_entry = (players[2], 0, 0, 0)
            baseline.after_game([fielding_entry], day=bridge.season_state.current_date, rng=expected_rng)
            with patch('game_core.tournament_bridge.rng_for', return_value=actual_rng), \
                    patch.object(book, 'after_game', wraps=book.after_game) as after:
                bridge._record_games('FAKE-CUP', result)
        self.assertEqual(expected_entries + [fielding_entry], after.call_args.args[0])
        self.assertGreater(actual_rng.calls, previous_calls)
        self.assertEqual(expected_rng.calls, actual_rng.calls)
        self.assertEqual(expected_rng.getstate(), actual_rng.getstate())
        for p in players:
            self.assertEqual(baseline.state(p).injuries, book.state(p).injuries)
            if p.player_id in old_ids:
                self.assertEqual(previous_injuries[p.player_id], tuple(book.state(p).injuries))
        self.assertTrue(book.state(players[2]).injuries)
        self.assertEqual(1, book.state(players[2]).season_games)

    def test_saved_fielding_experience_drives_same_monthly_growth_after_load(self):
        book, bridge = make_bridge()
        result, players = role_fixture(book)
        control = pickle.loads(pickle.dumps(book))
        control.bind(TEAMS.__getitem__)
        characteristics = (book.state(players[2]).growth_type, book.state(players[2]).potential)
        for number in range(12):
            result.match_id = f'ROLES-{number}'
            bridge._record_games('FAKE-CUP', result)
        self.assertEqual((12, 12), (book.state(players[2]).games, book.state(players[2]).season_games))
        saved = pickle.loads(pickle.dumps(book))
        saved.bind(TEAMS.__getitem__)
        for candidate in (book, saved, control):
            candidate.grow(date(2026, 7, 31))
        self.assertEqual(state_snapshot(book), state_snapshot(saved))
        state = book.state(players[2])
        self.assertEqual((0, 12), (state.games, state.season_games))
        self.assertEqual(characteristics, (state.growth_type, state.potential))
        self.assertGreater(sum(state.values), sum(control.state(players[2]).values))
        self.assertEqual(book.growth.config, control.growth.config)

    def test_corrected_annual_count_changes_practice_chance_without_changing_coefficients(self):
        book, bridge = make_bridge()
        result, players = role_fixture(book)
        model = injury_model()
        pitcher = players[2].primary_position == 'P'
        before = model.practice_chance(pitcher=pitcher, season_games=0, level='normal')
        bridge._record_games('FAKE-CUP', result)
        after = model.practice_chance(pitcher=pitcher, season_games=book.state(players[2]).season_games,
                                      level='normal')
        self.assertAlmostEqual(before * (1 + model.config['practice']['per_season_game']), after)
        self.assertEqual(0, book.state(players[6]).season_games)

    def test_three_years_are_reproducible_including_monthly_growth_and_save_resume(self):
        def run(seed, resume):
            book, _ = make_bridge(seed=seed, level='normal')
            outputs = []
            for year in (2026, 2027, 2028):
                book, bridge = make_bridge(seed=seed, year=year, book=book)
                for month in (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3):
                    day = date(year + int(month < 4), month, 5)
                    book.set_today(day)
                    bridge.season_state.current_date = day
                    result = short_game(bridge, year=year, number=month)
                    bridge._record_pitches(result, day)
                    bridge._record_games(result.competition_id, result)
                    outputs.append(result.to_dict())
                    book.grow(day)
                    if month == 3:
                        self.assertTrue(all(book.state(p).season_games == 0 for sid in TEAMS
                                            for p in book.roster(year, sid).players))
                    if resume and year == 2027 and month == 9:
                        season = pickle.loads(pickle.dumps(bridge.season_state))
                        book = pickle.loads(pickle.dumps(book))
                        book, bridge = make_bridge(seed=seed, year=year, book=book)
                        bridge.season_state = season
            return outputs, state_snapshot(book)
        for seed in (7, 31):
            with self.subTest(seed=seed):
                self.assertEqual(run(seed, False), run(seed, True))


if __name__ == '__main__':
    unittest.main()
