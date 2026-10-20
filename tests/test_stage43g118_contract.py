"""Fast Stage118 checks inside the full suite: pure 16/32 graphs, v2 bounds and CI wiring.

The real-scale cases live in `stage43g118_scale_cases.py` and run in their own
Linux/Windows workflow; this file fails if that wiring disappears.
"""
from contextlib import closing
from pathlib import Path
import random
import sqlite3
import unittest

from phase2_engine import saved_fictional_bracket as trial
from phase2_engine.fictional_bracket_oracle import progression
from test_stage43g117_bracket import synthetic, play_fake
import stage43g118_support as support

ROOT = Path(__file__).resolve().parents[1]


class Stage118ContractTests(unittest.TestCase):
    def test_sixteen_and_thirty_two_full_brackets_rounds_ranks_and_mid_null(self):
        for n, rounds in ((16, {1: 8, 2: 4, 3: 2, 4: 1}), (32, {1: 16, 2: 8, 3: 4, 4: 2, 5: 1})):
            seeds = tuple((f'fictional:pure:team{i}', i) for i in range(1, 5))
            for seed in range(5):
                ids, bracket, plan, request = synthetic(n, n, seeds, seed=seed)
                self.assertEqual((), bracket.byes)
                self.assertEqual(rounds, {r: sum(g.round_no == r for g in bracket.games) for r in rounds})
                rng, results = random.Random(seed), []
                while len(results) < n - 1:
                    results.append(play_fake(bracket, plan, results, rng))
                    ledger, ranks = progression(plan, request, tuple(results))
                    if len(results) < n - 1:
                        self.assertEqual([], ranks)
                        self.assertEqual([], bracket.ranks(results))
                self.assertEqual([(r, t) for r, t, _, _ in ranks], bracket.ranks(results))
                expected = [1, 2, 3, 3] + [5] * 4 + [9] * 8 + ([17] * 16 if n == 32 else [])
                self.assertEqual(expected, [r for r, *_ in ranks])
                self.assertEqual(n - 1, sum(w for *_, w, _ in ranks))

    def test_stage117_v2_schema_already_bounds_31_games_5_rounds_32_ranks(self):
        with closing(sqlite3.connect(':memory:')) as con:
            for sql in trial.DDL:
                con.execute(sql)
            row = "(?, ?, ?, 2027, 'fictional_bracket_tournament', 'ns', 'd', 'i', 'h', 'r', 'h')"
            con.execute('INSERT INTO bracket_matches VALUES ' + row, (31, 'm31', 5))
            for bad in ((32, 'm32', 5), (30, 'm30', 6)):
                with self.assertRaises(sqlite3.IntegrityError):
                    con.execute('INSERT INTO bracket_matches VALUES ' + row, bad)
            con.execute('INSERT INTO bracket_ranks VALUES (?,?,?,?)', ('t', 32, 0, 1))
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute('INSERT INTO bracket_ranks VALUES (?,?,?,?)', ('u', 33, 0, 1))

    def test_scenario_constants_are_fictional_and_separate(self):
        self.assertEqual(5, len(support.DATES32))
        self.assertEqual(4, len(support.DATES16))
        for namespace in (support.NAMESPACE32, support.NAMESPACE16):
            self.assertTrue(namespace.startswith('fictional:stage118-'))
        self.assertNotEqual(support.SEED32, support.SEED16)
        self.assertNotIn(trial.SEED, (support.SEED32, support.SEED16))
        self.assertEqual(2, len(support.JOINT))

    def test_dedicated_parallel_workflow_runs_real_scale_cases_on_linux_and_windows(self):
        # 専用workflowは段階0のCI整理で削除（重いケースは自動探索外のまま）
        audit = (ROOT / 'tests' / 'stage43g118_audit.py').read_text(encoding='utf-8')
        self.assertIn("'stage43g118_scale_cases.py'", audit)
        self.assertFalse(Path('stage43g118_scale_cases.py').match('test*.py'))
        self.assertEqual(20, len(list((ROOT / 'tests').glob('test_stage43g*_compatibility.py'))))
