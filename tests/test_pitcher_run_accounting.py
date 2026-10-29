"""架空の学校・選手で責任投手、無失策再構成、保存後の成績を確かめる。"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from game_core.match_contract import MatchSimulationInput, TeamMatchInput, validate_match_simulation_result
from game_core.match_simulator import (
    GameRules, MatchSimulator, _EarnedRunTracker, _RunnerResponsibilityTracker,
)
from game_core.team_strength import TeamStrengthGenerator
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from test_stage13b3_team_strength import make_roster_abilities


class _ScriptedSimulator(MatchSimulator):
    """打席結果と交代時点だけを指定し、実際の進塁・成績・試合終了処理を通す。"""

    def __init__(self, scripts, changes=()):
        super().__init__()
        self.scripts = scripts
        self.changes = dict(changes)
        self.calls = Counter()

    def _event_weights(self, batter, pitcher, defense_strength):
        script = self.scripts.get(pitcher.school_id, ())
        index = self.calls[pitcher.school_id]
        self.calls[pitcher.school_id] += 1
        return {script[index] if index < len(script) else "field_out": 1.0}

    def _should_sacrifice_bunt(self, *args):
        return False

    def _maybe_sacrifice_fly(self, event_type, *args):
        return event_type

    def _should_change_pitcher(self, *, pitcher, stats, has_next, **kwargs):
        return has_next and stats['batters_faced'] >= self.changes.get(pitcher.player_id, float('inf'))


class PitcherRunAccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gen = TeamStrengthGenerator()
        cls.teams = []
        for sid in ('FAKE-RUN-A', 'FAKE-RUN-B'):
            abilities = tuple(replace(a, player_id=sid + '-' + a.player_id)
                              for a in make_roster_abilities(school_id=sid))
            cls.teams.append(TeamMatchInput(sid, gen.generate(abilities), abilities))
        cls.staff = tuple(e.player_id for e in cls.teams[1].team_strength.pitching_staff.entries)

    def match(self, number=0):
        return MatchSimulationInput(f'RUN-{number}', 'FAKE-RUN-CUP', 2026, 20261029,
                                    *self.teams, team_generation_seed=2026100701)

    def play(self, top, changes=(), *, bottom=(), rules=None, regulation=9):
        sim = _ScriptedSimulator({self.teams[1].school_id: top,
                                  self.teams[0].school_id: bottom},
                                 [(self.staff[i], n) for i, n in enumerate(changes)])
        result = sim.simulate(self.match(), rules=rules, regulation_innings=regulation)
        self.check_totals(result)
        rows = {p.player_id: p for p in result.pitcher_stats}
        return result, [(rows[pid].runs_allowed, rows[pid].earned_runs)
                        for pid in self.staff if pid in rows]

    def check_totals(self, result):
        validate_match_simulation_result(result, self.match())
        for sid, runs in ((self.teams[0].school_id, result.team2_score),
                          (self.teams[1].school_id, result.team1_score)):
            rows = [p for p in result.pitcher_stats if p.school_id == sid]
            self.assertEqual(runs, sum(p.runs_allowed for p in rows))
            self.assertTrue(all(0 <= p.earned_runs <= p.runs_allowed for p in rows))

    def test_inherited_walk_scores_on_relief_hit(self):
        _, rows = self.play(['walk', 'triple'], changes=(1,))
        self.assertEqual([(1, 1), (0, 0)], rows)

    def test_three_pitchers_share_grand_slam_and_loaded_walk(self):
        for finish, expected in [('home_run', [(1, 1), (1, 1), (2, 2)]),
                                 ('walk', [(1, 1), (0, 0), (0, 0)])]:
            with self.subTest(finish=finish):
                _, rows = self.play(['walk', 'walk', 'walk', finish], changes=(1, 1))
                self.assertEqual(expected, rows)

    def test_error_runner_is_unearned_but_clean_home_run_is_earned(self):
        _, rows = self.play(['reached_on_error', 'home_run'])
        self.assertEqual([(2, 1)], rows)

    def test_missed_third_out_makes_subsequent_home_runs_unearned(self):
        _, rows = self.play(['field_out', 'field_out', 'reached_on_error', 'home_run', 'home_run'])
        self.assertEqual([(3, 0)], rows)

    def test_relief_does_not_inherit_previous_missed_out_opportunity(self):
        _, rows = self.play(['field_out', 'field_out', 'walk', 'reached_on_error', 'home_run'],
                            changes=(4,))
        self.assertEqual([(2, 0), (1, 1)], rows)

    def test_later_error_benefits_retired_pitcher_too(self):
        _, rows = self.play(['field_out', 'field_out', 'walk', 'walk',
                             'reached_on_error', 'home_run'], changes=(4,))
        self.assertEqual([(2, 0), (2, 0)], rows)

    def test_separate_relief_reconstruction_with_two_errors(self):
        _, rows = self.play(['walk', 'reached_on_error', 'home_run', 'strikeout',
                             'strikeout', 'reached_on_error', 'home_run'], changes=(2,))
        self.assertEqual([(2, 1), (3, 1)], rows)

    def test_fielders_choice_preserves_inherited_responsibility(self):
        _, rows = self.play(['walk', 'fielder_choice', 'home_run'], changes=(1,))
        self.assertEqual([(1, 1), (1, 1)], rows)

    def test_error_replacement_is_also_unearned(self):
        _, rows = self.play(['reached_on_error', 'fielder_choice', 'home_run'], changes=(1,))
        self.assertEqual([(1, 0), (1, 1)], rows)

    def test_tiebreak_and_choice_replacement_are_not_earned(self):
        for top in (['home_run'], ['fielder_choice', 'home_run']):
            with self.subTest(top=top):
                _, rows = self.play(top, rules=GameRules(tiebreak_start_inning=1))
                self.assertEqual([(3, 1)], rows)

    def test_tiebreak_runners_remain_predecessors_unearned_runs_after_relief(self):
        _, rows = self.play(['field_out', 'home_run'], changes=(1,),
                            rules=GameRules(tiebreak_start_inning=1))
        self.assertEqual([(2, 0), (1, 1)], rows)

    def test_error_forced_run_can_become_earned_on_later_clean_hit(self):
        # Initially the fourth walk scores the first runner only because ROE
        # filled a base. A later triple supplies the missing clean advancement.
        top = ['walk', 'reached_on_error', 'walk', 'walk']
        _, before = self.play(top)
        _, after = self.play([*top, 'triple'])
        self.assertEqual([(1, 0)], before)
        self.assertEqual([(4, 3)], after)

    def test_walkoff_mercy_and_extra_innings_reconcile(self):
        walkoff, _ = self.play(['home_run'], bottom=['home_run', 'field_out', 'field_out',
                                                    'field_out', 'home_run'], regulation=1)
        self.assertEqual((2, 'bottom'), (walkoff.last_inning, walkoff.ending_half))
        called, _ = self.play(['home_run'] * 10, rules=GameRules(mercy=((5, 10),)))
        self.assertEqual(5, called.last_inning)
        extra, _ = self.play(['home_run'], bottom=['home_run', 'field_out', 'field_out',
                                                  'field_out', 'home_run'], regulation=1,
                             rules=GameRules(tiebreak_start_inning=2))
        self.assertEqual(2, extra.last_inning)

    def test_archive_reload_and_packing_preserve_result_and_stats(self):
        result, _ = self.play(['walk', 'fielder_choice', 'home_run'], changes=(1,))
        record = {
            'competition_id': result.competition_id, 'match_id': result.match_id,
            'team1_id': result.team1_school_id, 'team2_id': result.team2_school_id,
            'winner_id': result.winner_id, 'loser_id': result.loser_id,
            'team1_score': result.team1_score, 'team2_score': result.team2_score,
            'score_source': result.score_source, 'ability_detail': result.to_dict(),
            'match_date': '2026-07-01', 'status': 'completed',
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.sqlite3'
            archive = HistoricalMatchArchive(path)
            archive.sync(year=2026, rng_seed=20261029, resolver_contract='ability_model_v1',
                         plan_fingerprint='fake-run-plan', completed=[record])
            first = HistoricalMatchArchive(path).get_match(2026, result.competition_id, result.match_id)
            archive.pack_competition(2026, result.competition_id)
            loaded = HistoricalMatchArchive(path).get_match(2026, result.competition_id, result.match_id)
        self.assertEqual(first, loaded)
        self.assertEqual(result.to_dict()['pitcher_stats'], loaded['pitcher_stats'])
        self.assertEqual(result.to_dict()['batter_stats'], loaded['batter_stats'])
        self.assertEqual(result.team1_score, loaded['team1_score'])
        self.assertEqual(result.winner_id, loaded['winner_id'])

    def test_only_pitcher_run_columns_change_with_responsibility_accounting(self):
        class DuringOutingTracker(_RunnerResponsibilityTracker):
            def record_play(self, **kwargs):
                return tuple(replace(r, responsible_pitcher_id=kwargs['pitcher_id'])
                             for r in super().record_play(**kwargs))

        sim = MatchSimulator()
        sim.params['pitching_usage']['runs_allowed_quick_hook'] = 2
        changed = False

        def unaffected(result):
            value = result.to_dict()
            for p in value['pitcher_stats']:
                p.pop('runs_allowed')
                p.pop('earned_runs')
            return value

        for number in range(16):
            inp = self.match(number)
            actual = sim.simulate(inp, rules=GameRules(tiebreak_start_inning=10))
            with patch('game_core.match_simulator._RunnerResponsibilityTracker', DuringOutingTracker):
                old_credit = sim.simulate(inp, rules=GameRules(tiebreak_start_inning=10))
            self.assertEqual(unaffected(actual), unaffected(old_credit))
            self.assertEqual(actual.to_dict(), sim.simulate(inp, rules=GameRules(tiebreak_start_inning=10)).to_dict())
            changed |= actual.pitcher_stats != old_credit.pitcher_stats
        self.assertTrue(changed, 'must exercise inherited scoring, not just scoreless games')


class ReconstructionRulesTests(unittest.TestCase):
    """進塁の細部を指定し、9.16(g)の途中の責任移動も検証する。"""

    def setUp(self):
        self.ledger = _RunnerResponsibilityTracker()
        self.earned = _EarnedRunTracker()
        self.bases = [None] * 3
        self.outs = self.pa = 0
        self.runs = Counter()

    def play(self, batter, pitcher, event, after, scored=(), outs=0):
        self.pa += 1
        origins = self.ledger.record_play(
            bases_before=self.bases, bases_after=after, scored_runner_ids=list(scored),
            batter_id=batter, pitcher_id=pitcher, event_type=event, plate_appearance_no=self.pa)
        self.earned.record_play(
            bases_before=self.bases, bases_after=after, scored_runners=origins,
            batter_id=batter, pitcher_id=pitcher, event_type=event,
            plate_appearance_no=self.pa, outs_before=self.outs, outs_on_play=outs)
        self.runs.update(r.responsible_pitcher_id for r in origins)
        self.bases = list(after)
        self.outs += outs
        return origins

    def prepare_choice(self, error=False):
        self.play('R1', 'A', 'reached_on_error' if error else 'walk', ['R1', None, None])
        self.play('R2', 'B', 'walk', ['R2', 'R1', None])
        self.play('R3', 'B', 'fielder_choice', ['R3', 'R2', None], outs=1)

    def test_prior_pitcher_slot_moves_to_first_scorer_not_only_new_batter(self):
        self.prepare_choice()
        origins = self.play('R4', 'B', 'single', ['R4', None, 'R3'], ['R2'])
        self.assertEqual('A', origins[0].responsible_pitcher_id)
        self.assertEqual({'A': 1}, self.runs)

    def test_two_choices_preserve_three_pitchers_slots(self):
        self.play('R1', 'A', 'walk', ['R1', None, None])
        self.play('R2', 'B', 'walk', ['R2', 'R1', None])
        self.play('R3', 'C', 'fielder_choice', ['R3', 'R2', None], outs=1)
        self.play('R4', 'C', 'fielder_choice', ['R4', 'R3', None], outs=1)
        self.play('R5', 'C', 'home_run', [None] * 3, ['R4', 'R3', 'R5'])
        self.assertEqual({'A': 1, 'B': 1, 'C': 1}, self.runs)
        self.assertEqual(self.runs, self.earned.earned_runs())

    def test_simultaneous_scorers_keep_error_replacement_lineage(self):
        self.prepare_choice(error=True)
        origins = self.play('R4', 'B', 'home_run', [None] * 3, ['R2', 'R3', 'R4'])
        self.assertEqual(['B', 'A', 'B'], [r.responsible_pitcher_id for r in origins])
        self.assertEqual({'A': 1, 'B': 2}, self.runs)
        self.assertEqual({'B': 2}, self.earned.earned_runs())

    def test_partial_scoring_inherits_error_slot_and_remains_unearned(self):
        self.prepare_choice(error=True)
        self.play('R4', 'B', 'single', ['R4', None, 'R3'], ['R2'])
        self.assertEqual({'A': 1}, self.runs)
        self.assertEqual({}, self.earned.earned_runs())

    def test_team_earned_runs_may_differ_from_pitcher_sum(self):
        self.play('O1', 'A', 'field_out', [None] * 3, outs=1)
        self.play('O2', 'A', 'field_out', [None] * 3, outs=1)
        self.play('R1', 'A', 'walk', ['R1', None, None])
        self.play('R2', 'A', 'reached_on_error', ['R2', 'R1', None])
        self.play('R3', 'B', 'home_run', [None] * 3, ['R1', 'R2', 'R3'])
        self.assertEqual({'A': 2, 'B': 1}, self.runs)
        self.assertEqual({'B': 1}, self.earned.earned_runs())
        self.assertEqual(0, self.earned.team_earned_runs)

    def test_virtual_runner_from_previous_trip_is_not_the_same_appearance(self):
        self.play('R1', 'A', 'walk', ['R1', None, None])
        self.play('E', 'A', 'reached_on_error', ['E', 'R1', None])
        self.play('R2', 'A', 'walk', ['R2', 'E', 'R1'])
        self.play('R3', 'A', 'walk', ['R3', 'R2', 'E'], ['R1'])
        # R1 remains on virtual third. Its second trip must have a distinct key.
        self.play('R1', 'A', 'home_run', [None] * 3, ['R3', 'R2', 'E', 'R1'])
        self.assertEqual({'A': 5}, self.runs)
        self.assertEqual({'A': 4}, self.earned.earned_runs())


if __name__ == '__main__':
    unittest.main()
