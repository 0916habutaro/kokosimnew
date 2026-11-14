"""投手の配置転換：降りた投手を守備に残し、あとで投手に戻す（段階F5。架空の学校・選手）。"""
from collections import Counter
from dataclasses import replace
import unittest

from game_core.coaches import CoachTactics
from game_core.highlights import game_highlights
from game_core.match_contract import MatchSimulationInput, TeamMatchInput, validate_match_simulation_result
from game_core.match_simulator import LineupAdjustment, MatchSimulator
from game_core.team_strength import TeamStrengthGenerator
from phase2_engine.screen.match_summary import pitchers_of_record
from test_stage13b3_team_strength import make_roster_abilities

SEED = 2026100701
SHUFFLER = CoachTactics(shuffle_rate=0.8)


class PitcherShuffleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = MatchSimulator()
        generator = TeamStrengthGenerator()
        cls.teams = []
        for sid in ('FAKE-A', 'FAKE-B'):
            players = tuple(replace(p, player_id=f'{sid}-{p.player_id}')
                            for p in make_roster_abilities(school_id=sid, seed=SEED))
            cls.teams.append(TeamMatchInput(sid, generator.generate(players), players))
        cls.games = [cls.play(i) for i in range(160)]

    @classmethod
    def play(cls, i, tactics=SHUFFLER, **kwargs):
        match = MatchSimulationInput(f'MATCH-{i}', 'FAKE-CUP', 2026, SEED, *cls.teams)
        result = cls.sim.simulate(match, tactics={'FAKE-A': tactics, 'FAKE-B': tactics}, **kwargs)
        validate_match_simulation_result(result, match)
        return match, result

    @staticmethod
    def shuffles(result):
        return [(part.school_id, change) for part in result.team_participation for change in part.changes
                if change.reason in ('pitcher_to_field', 'pitcher_return')]

    def test_a_pitcher_moved_to_the_field_returns_and_his_stats_add_up(self):
        returned = 0
        for match, result in self.games:
            for school, change in self.shuffles(result):
                if change.reason != 'pitcher_return':
                    continue
                returned += 1
                back = next(c for c in change.defensive_changes if c.defensive_position == 'P').after_player_id
                # 先に同じ投手を守備に残した記録がある（投手 → 守備位置、退く野手の打順に救援）
                to_field = [c for s, c in self.shuffles(result) if s == school and c.reason == 'pitcher_to_field'
                            and c.sequence < change.sequence]
                self.assertEqual(1, len(to_field))
                moved = {c.defensive_position: c.after_player_id for c in to_field[0].defensive_changes}
                self.assertIn(back, moved.values())
                self.assertNotEqual('P', next(p for p, pid in moved.items() if pid == back))
                # 投げた打席は2回に分かれ、成績は1行にまとまる
                pitched = [e.pitcher_id == back for e in result.events if e.defense_school_id == school]
                runs = sum(1 for i, x in enumerate(pitched) if x and (i == 0 or not pitched[i - 1]))
                self.assertGreaterEqual(runs, 2)
                rows = [r for r in result.pitcher_stats if r.player_id == back]
                self.assertEqual(1, len(rows))
                self.assertEqual(sum(pitched), rows[0].batters_faced)
                # 勝利・敗戦投手を決める失点の数え直しが合う
                detail = result.to_dict()
                detail['highlights'] = game_highlights(result.events)
                self.assertIsNotNone(pitchers_of_record(detail))
        self.assertGreater(returned, 5)

    def test_pitch_allowance_counts_both_outings(self):
        staff = {t.school_id: t.team_strength.pitching_staff.entries[0].player_id for t in self.teams}
        allowances = {pid: 95 for pid in staff.values()}
        returned = 0
        for i in range(120):
            _, result = self.play(i, pitch_allowances=allowances)
            for row in result.pitcher_stats:
                if row.player_id in allowances:
                    self.assertLessEqual(row.pitches, 95)
            returned += sum(c.reason == 'pitcher_return' for _, c in self.shuffles(result))
        self.assertGreater(returned, 0)

    def test_neutral_or_low_coaches_never_shuffle(self):
        for tactics in (CoachTactics(), CoachTactics(shuffle_rate=0.0, return_misread=0.4)):
            for i in range(60):
                _, result = self.play(i, tactics)
                self.assertEqual([], self.shuffles(result))

    def test_poor_judges_bring_the_pitcher_back_at_worse_times(self):
        def early_share(tactics):
            early = total = 0
            for i in range(200):
                _, result = self.play(i, tactics)
                for _, change in self.shuffles(result):
                    if change.reason == 'pitcher_return':
                        total += 1
                        early += change.moment.inning < 7
            return early / total
        self.assertLess(early_share(SHUFFLER), early_share(replace(SHUFFLER, return_misread=0.4)))

    def test_rules_once_per_inning_and_no_return_after_leaving(self):
        team = self.teams[1]
        lineup = team.team_strength.starting_lineup
        ace, right = lineup.player_for_position('P'), lineup.player_for_position('RF')
        swap = (('P', right), ('RF', ace))
        back = (('P', ace), ('RF', right))
        # 1回表（相手が攻める）の間に、投手と右翼を入れ替えて戻す・もう一度入れ替える
        changes = tuple(LineupAdjustment(n, team.school_id, defensive_changes=d)
                        for n, d in ((2, swap), (3, back), (4, swap)))
        self.play(0, CoachTactics(), lineup_changes=changes)
        # 同じイニングに同じ投手が2度は戻れない
        with self.assertRaisesRegex(ValueError, 'once per inning'):
            self.play(0, CoachTactics(), lineup_changes=changes + (
                LineupAdjustment(5, team.school_id, defensive_changes=back),))
        # 退いた投手は戻れない（控えと代わったあと）
        bench = next(p.player_id for p in team.player_abilities
                     if p.player_id not in set(lineup.starter_ids) and p.primary_position != 'P')
        changes = (LineupAdjustment(2, team.school_id, defensive_changes=swap),
                   LineupAdjustment(3, team.school_id, batting_changes=(
                       (next(e.batting_order for e in lineup.entries if e.player_id == ace), bench),),
                       defensive_changes=(('RF', bench),)),
                   LineupAdjustment(4, team.school_id, defensive_changes=(('P', ace),)))
        with self.assertRaises(ValueError):
            self.play(0, CoachTactics(), lineup_changes=changes)


class DHGameShuffleTests(unittest.TestCase):
    """DHを宣言した試合：投手が守備に就くとDHは消え、救援はDHの打順に入る。"""

    @classmethod
    def setUpClass(cls):
        cls.sim = MatchSimulator()
        generator = TeamStrengthGenerator()
        cls.teams = []
        for sid in ('FAKE-A', 'FAKE-B'):
            players = tuple(replace(p, player_id=f'{sid}-{p.player_id}')
                            for p in make_roster_abilities(school_id=sid, seed=SEED))
            cls.teams.append(TeamMatchInput(sid, generator.generate(players, dh_mode='normal'), players))

    def test_shuffle_ends_the_dh_and_the_reliever_bats_in_the_dh_slot(self):
        from game_core.match_state import replay_team_participation

        checked = returned = 0
        for i in range(80):
            match = MatchSimulationInput(f'MATCH-{i}', 'FAKE-CUP', 2026, SEED, *self.teams)
            result = self.sim.simulate(match, tactics={'FAKE-A': SHUFFLER, 'FAKE-B': SHUFFLER})
            validate_match_simulation_result(result, match)
            for part in result.team_participation:
                dh = part.starting_designated_hitter_id
                for change in part.changes:
                    returned += change.reason == 'pitcher_return'
                    if change.reason != 'pitcher_to_field' or dh is None:
                        continue
                    record = replace(part, changes=part.changes[:change.sequence], fielding_player_ids=())
                    state = replay_team_participation(record, 2026)
                    reliever = state.current_pitcher_id
                    batters = [s.player_id for s in state.batting_order]
                    moved = next(c.after_player_id for c in change.defensive_changes if c.defensive_position != 'P')
                    self.assertIsNone(state.designated_hitter_id)
                    self.assertIn(moved, batters)
                    self.assertIn(reliever, batters)
                    self.assertIn(dh, state.exited_player_ids)
                    checked += 1
        self.assertGreater(checked, 5)
        self.assertGreater(returned, 0)


class CoachShufflePolicyTests(unittest.TestCase):
    def test_rate_from_pitcher_shuffle_and_misread_from_pitching_change(self):
        from test_coach_intake import books

        book = books(50)[1]
        coach = book.coaches['C-FAKE-A']
        self.assertEqual((0.17, round(0.4 * 50 / 99, 6)), book.shuffle_policy(coach))
        for low in (1, 30, 40):
            self.assertEqual(0.0, book.shuffle_policy(replace(coach, pitcher_shuffle=low))[0])
        self.assertEqual(0.9, book.shuffle_policy(replace(coach, pitcher_shuffle=100))[0])
        self.assertEqual(0.0, book.shuffle_policy(replace(coach, pitching_change=100))[1])
        self.assertEqual(0.4, book.shuffle_policy(replace(coach, pitching_change=1))[1])


if __name__ == '__main__':
    unittest.main()
