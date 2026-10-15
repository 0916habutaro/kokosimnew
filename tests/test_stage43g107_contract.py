"""Explicit two-game fixture and unchanged Stage104/105/106 contract boundary."""
from dataclasses import replace
import tempfile
import unittest
from unittest.mock import patch

from phase2_engine.registered_full_a_lab_store import fixed_authorities, RegisteredFullALabStore
from phase2_engine.joint_team_registration_lab import match_input_from_registration, validate_registered_match_input
from phase2_engine.registered_match_driver import simulate_registered_full_a
from phase2_engine.registered_full_a_oracle import event_oracle
from phase2_engine.joint_tournament_lab import (
    fixed_plan, next_match_input, simulate_tournament_match, validate_tournament_input, verify_prefix,
)
from phase2_engine.joint_tournament_oracle import progression_oracle


class Stage107ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo, cls.rosters, cls.reg = fixed_authorities()
        cls.plan = fixed_plan(cls.reg, cls.repo, cls.rosters)
        cls.m1 = next_match_input(cls.reg, cls.repo, cls.rosters, opt_in=True)
        cls.r1 = simulate_tournament_match(cls.m1, cls.reg, cls.repo, cls.rosters)
        cls.m2 = next_match_input(cls.reg, cls.repo, cls.rosters, (cls.r1,), opt_in=True)
        cls.r2 = simulate_tournament_match(cls.m2, cls.reg, cls.repo, cls.rosters, (cls.r1,))

    def test_exact_plan_two_calculated_games_separate_seeds_identity_and_oracles(self):
        self.assertEqual(430103, self.m1.ability_seed)
        self.assertEqual((430107, 430108), (self.m1.match_seed, self.m2.match_seed))
        self.assertEqual(self.plan.entries[2], self.plan.bye_team_id)
        self.assertEqual(self.r1.winner_id, self.m2.team1.team_id)
        self.assertEqual(self.plan.bye_team_id, self.m2.team2.team_id)
        self.assertEqual(self.plan.fingerprint, self.m1.plan_sha256)
        self.assertNotEqual(self.m1.match_id, self.m2.match_id)
        self.assertIsNone(self.m1.prior_result_sha256)
        self.assertIsNotNone(self.m2.prior_result_sha256)
        for match, result in ((self.m1, self.r1), (self.m2, self.r2)):
            people = {p.player_id: (t.team_id, p.origin_school_id, p.player)
                      for t in self.reg.teams for p in t.players}
            for row in result.batter_stats + result.pitcher_stats:
                tid, sid, player = people[row.player_id]
                self.assertEqual((tid, sid, row.player_id), (row.team_id, row.origin_school_id, player.player_id))
                self.assertEqual(sid, player.school_id)
                self.assertEqual(match.match_id, row.match_id)
            with patch('phase2_engine.registered_match_driver._run', side_effect=AssertionError('oracle must be independent')):
                report = event_oracle(result, match)
                ledger, ranks = progression_oracle(self.plan, self.reg, (self.r1, self.r2))
            self.assertEqual(report['runs'], report['rbi'])
            self.assertEqual(report['runs'], report['pitcher_runs'])
            self.assertEqual(len(result.events), report['plate_appearances'])
            for team in result.team_stats:
                self.assertEqual(team.runs, sum(r.runs or 0 for r in result.inning_scores if r.team_id == team.team_id))
        self.assertEqual('BYE', ledger[0].source)
        self.assertEqual((self.r2.winner_id, self.r2.loser_id, self.r1.loser_id), tuple(r.team_id for r in ranks))

    def test_opt_in_fixed_plan_and_match_input_tampering_refused(self):
        for opt in (False, 1, None):
            with self.assertRaises(ValueError):
                next_match_input(self.reg, self.repo, self.rosters, opt_in=opt)
        for m in (replace(self.m2, match_id='unknown'), replace(self.m2, match_seed=1),
                  replace(self.m2, ability_seed=1), replace(self.m2, plan_sha256='0'*64),
                  replace(self.m2, prior_result_sha256=None), replace(self.m2, day='2026-07-01'),
                  replace(self.m2, team1=self.m1.team2), replace(self.m2, team2=self.m2.team1),
                  replace(self.m2, opt_in=1), replace(self.m2, year=True),
                  replace(self.m2, team1=replace(self.m2.team1, players=self.m2.team1.players[:-1]))):
            with self.subTest(input=m.match_id), self.assertRaises(ValueError):
                validate_tournament_input(m, self.reg, self.repo, self.rosters, (self.r1,))
        for plan in (replace(self.plan, bye_team_id=self.plan.entries[0]),
                     replace(self.plan, entries=self.plan.entries[::-1]),
                     replace(self.plan, games=(replace(self.plan.games[0], seed=1), self.plan.games[1])),
                     replace(self.plan, games=(self.plan.games[0], replace(self.plan.games[1], team1_source='loser')))):
            with self.assertRaises(ValueError):
                next_match_input(self.reg, self.repo, self.rosters, opt_in=True, plan=plan)

    def test_missing_first_duplicate_reverse_loser_unknown_seed_stats_refused(self):
        invalid = ((self.r2,), (self.r1, self.r1), (self.r2, self.r1),
            (replace(self.r1, winner_id=self.r1.loser_id),),
            (replace(self.r1, run_seed=1),), (replace(self.r1, match_id='unknown'),),
            (replace(self.r1, team1_score=self.r1.team1_score+1),),
            (replace(self.r1, batter_stats=(replace(self.r1.batter_stats[0], hits=999),)+self.r1.batter_stats[1:]),),
            (replace(self.r1, events=self.r1.events[:-1]),))
        for results in invalid:
            with self.subTest(count=len(results)), self.assertRaises(ValueError):
                verify_prefix(self.reg, self.repo, self.rosters, results)
        with self.assertRaises(ValueError):
            next_match_input(self.reg, self.repo, self.rosters, (self.r1, self.r2), opt_in=True)
        with self.assertRaises(ValueError):
            validate_tournament_input(self.m2, self.reg, self.repo, self.rosters)
        with self.assertRaises(ValueError):
            progression_oracle(self.plan, self.reg, (self.r1, replace(self.r2, team1_id=self.r1.loser_id)))

    def test_stage106_fixed_match_seed_bit_equivalence_and_no_new_input_acceptance(self):
        old_match = match_input_from_registration(self.reg, self.repo, self.rosters,
            team1_id=self.reg.teams[0].team_id, team2_id=self.reg.teams[1].team_id, opt_in=True)
        original = simulate_registered_full_a(old_match, self.reg, self.repo, self.rosters)
        self.assertEqual((8, 1, 430104, 79), (original.team1_score, original.team2_score, original.run_seed, len(original.events)))
        self.assertEqual(original.to_json(), simulate_registered_full_a(old_match, self.reg, self.repo, self.rosters).to_json())
        with tempfile.TemporaryDirectory(prefix='stage107-old-') as root:
            owner = tempfile.TemporaryDirectory(dir=root)
            try:
                store = RegisteredFullALabStore(owner)
                store.append(original, old_match, self.reg, self.repo, self.rosters)
                before = store.db_path.read_bytes()
                for match in (self.m1, self.m2, replace(old_match, match_id=self.m2.match_id), replace(old_match, match_seed=430107)):
                    with self.assertRaises(ValueError):
                        validate_registered_match_input(match, self.reg, self.repo, self.rosters)
                with self.assertRaises(ValueError):
                    store.append(self.r1, self.m1, self.reg, self.repo, self.rosters)
                self.assertEqual(before, store.db_path.read_bytes())
            finally:
                owner.cleanup()
