"""Executed games only; independent positional/statistical and SQL identity checks."""
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from stage43g103_fixture_support import fixture
from stage43g97_acceptance_support import pin
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read
from phase2_engine import joint_team_registration_lab as registration
from phase2_engine.registered_match_driver import simulate_registered_full_a, _run
from phase2_engine.registered_full_a_oracle import validate_registered_full_a, load_result, event_oracle, legacy_writer_payload


class Stage105FullATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='stage105-owned-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.slot = Path(cls.temp.name)
        cls.repo, cls.rosters, _ = fixture(cls.slot)
        cls.registry = registration.registration_from_rosters(cls.repo, cls.rosters)
        cls.match = registration.match_input_from_registration(cls.registry, cls.repo, cls.rosters,
            team1_id=cls.registry.teams[0].team_id, team2_id=cls.registry.teams[1].team_id, opt_in=True)
        cls.result = simulate_registered_full_a(cls.match, cls.registry, cls.repo, cls.rosters)
        cls.before = pin(cls.slot)

    def tearDown(self):
        self.assertEqual(self.before, pin(self.slot))

    def validate(self, result, **kwargs):
        return validate_registered_full_a(result, self.match, self.registry, self.repo, self.rosters, **kwargs)

    def test_actual_game_twice_roundtrip_and_separate_seed(self):
        again = simulate_registered_full_a(self.match, self.registry, self.repo, self.rosters)
        self.assertEqual(self.result.to_json(), again.to_json())
        raw = self.result.to_json()
        self.assertEqual(self.result, load_result(raw, self.match, self.registry, self.repo, self.rosters))
        self.assertNotIn('"school_id"', raw)
        for seed in (0, 1, 430105):
            other = simulate_registered_full_a(self.match, self.registry, self.repo, self.rosters, run_seed=seed)
            self.assertNotEqual(self.result.events, other.events)
            with self.assertRaises(ValueError):
                self.validate(other)
            self.validate(other, expected_seed=seed)
        self.assertEqual((8, 1, 9, 79), (self.result.team1_score, self.result.team2_score,
                         self.result.last_inning, len(self.result.events)))

    def test_independent_sql_permanent_identity_and_both_joint_origins(self):
        with closing(sqlite3.connect(self.slot/'career_rosters.sqlite3')) as con:
            identities = dict(con.execute('SELECT player_id,school_id FROM career_player_identities'))
        self.assertEqual(80, len(identities))
        joint = self.match.team1.team_id
        for rows in (self.result.batter_stats, self.result.pitcher_stats):
            if rows is self.result.batter_stats:
                self.assertEqual({'SCH000202', 'SCH000220'},
                                 {r.origin_school_id for r in rows if r.team_id == joint})
            for row in rows:
                self.assertEqual(identities[row.player_id], row.origin_school_id)
                self.assertNotEqual(row.team_id, row.origin_school_id)
        for event in self.result.events:
            self.assertEqual(identities[event.batter_id], event.batter_origin_school_id)
            self.assertEqual(identities[event.pitcher_id], event.pitcher_origin_school_id)

    def test_oracle_independent_of_driver_and_all_totals(self):
        # The oracle cannot generate an expected game or use the driver's movement.
        with patch('phase2_engine.registered_match_driver._run', side_effect=AssertionError('independent')), \
             patch('phase2_engine.registered_match_driver._advance', side_effect=AssertionError('independent')):
            report = event_oracle(self.result, self.match)
        self.assertEqual((79, 54, 21, 9, 9, 9), tuple(report[k] for k in
            ('plate_appearances', 'pitching_outs', 'strikeouts', 'runs', 'rbi', 'pitcher_runs')))
        for tid, opponent in ((self.result.team1_id, self.result.team2_id), (self.result.team2_id, self.result.team1_id)):
            bat = [r for r in self.result.batter_stats if r.team_id == tid]
            pit = [r for r in self.result.pitcher_stats if r.team_id == opponent]
            self.assertEqual(sum(r.plate_appearances for r in bat), sum(r.batters_faced for r in pit))
            self.assertEqual(sum(r.hits for r in bat), sum(r.hits_allowed for r in pit))
            self.assertEqual(sum(r.runs for r in bat), sum(r.runs_allowed for r in pit))
            self.assertEqual(sum(r.strikeouts for r in bat), sum(r.strikeouts for r in pit))

    def test_every_full_a_counter_tamper_independently_refused(self):
        for group in ('batter_stats', 'pitcher_stats'):
            rows = getattr(self.result, group)
            for key, value in asdict(rows[0]).items():
                if type(value) is int and key != 'year':
                    bad = replace(self.result, **{group: (replace(rows[0], **{key: value + 1}),) + rows[1:]})
                    with self.subTest(group=group, key=key), self.assertRaises(ValueError):
                        event_oracle(bad, self.match)
        for key in ('team1_score', 'team2_score'):
            with self.assertRaises(ValueError):
                event_oracle(replace(self.result, **{key: getattr(self.result, key) + 1}), self.match)

    def test_event_sequence_identity_base_and_version_fail_closed(self):
        r = self.result
        first = r.events[0]
        mutations = dict(event_no=2, inning=2, half='bottom', offense_team_id=r.team2_id,
            defense_team_id=r.team1_id, batter_id=self.match.team1.players[0].player_id,
            pitcher_id='outside', batter_origin_school_id=r.team1_id, pitcher_origin_school_id=r.team2_id,
            event_type='unknown', bases_after=('outside', None, None), scored_player_ids=('outside',),
            outs_before=2, outs_on_play=2, rbi=1, pitcher_staff_order=5, replaced_pitcher_id='outside')
        for key, value in mutations.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(replace(r, events=(replace(first, **{key: value}),) + r.events[1:]))
        for events in (r.events[1:], r.events + (first,), (first, first) + r.events[2:]):
            with self.assertRaises(ValueError):
                self.validate(replace(r, events=events))
        for group in ('team_stats', 'inning_scores', 'batter_stats', 'pitcher_stats'):
            rows = getattr(r, group)
            for field, value in (('year', 2027), ('competition_id', 'other'), ('match_id', 'other'),
                                 ('team_id', 'SCH000202')):
                bad = replace(r, **{group: (replace(rows[0], **{field: value}),) + rows[1:]})
                with self.subTest(group=group, field=field), self.assertRaises(ValueError):
                    event_oracle(bad, self.match)
        for innings in (r.inning_scores[:-1], r.inning_scores + (r.inning_scores[-1],)):
            with self.assertRaises(ValueError):
                event_oracle(replace(r, inning_scores=innings), self.match)
        for group in ('batter_stats', 'pitcher_stats'):
            rows = getattr(r, group)
            for key, value in (('player_id', 'outside'), ('origin_school_id', r.team1_id)):
                with self.assertRaises(ValueError):
                    event_oracle(replace(r, **{group: (replace(rows[0], **{key: value}),) + rows[1:]}), self.match)
        for changes in (dict(version='legacy'), dict(run_seed=1), dict(year=2027), dict(input_sha256='0'*64),
                dict(probability_config_sha256='0'*64), dict(team1_id='SCH000202'), dict(team1_score=True),
                dict(events=list(r.events)), dict(ending_half='top'), dict(last_inning=8)):
            with self.assertRaises(ValueError):
                self.validate(replace(r, **changes))

    def test_corrupt_json_old_schema_and_writer_misrouting_refused(self):
        raw = self.result.to_json()
        bad = [raw[:-1], '{}', raw.replace('"version":', '"extra":0,"version":'),
               raw.replace('"run_seed":430104', '"run_seed":true'),
               raw.replace('"run_seed":430104', '"run_seed":430104,"run_seed":430104')]
        for value in bad:
            with self.assertRaises(ValueError):
                load_result(value, self.match, self.registry, self.repo, self.rosters)
        with self.assertRaises(ValueError):
            legacy_writer_payload(self.result)
        from phase2_engine.historical_match_archive import HistoricalMatchArchive
        with tempfile.TemporaryDirectory(prefix='stage105-writer-refusal-') as temp:
            path = Path(temp)/'forbidden.sqlite3'
            with self.assertRaises(ValueError):
                HistoricalMatchArchive(path).sync(year=2026, rng_seed=430104,
                    resolver_contract='lab105', plan_fingerprint='self-generated',
                    completed=[self.result.to_dict()])
            self.assertFalse(path.exists())
        from game_core.match_contract import validate_match_simulation_result
        with self.assertRaises((ValueError, AttributeError, TypeError)):
            validate_match_simulation_result(self.result, self.match)
        with self.assertRaises(ValueError):
            self.validate(self.match)

    def test_rejects_input_seed_and_registration_before_execution(self):
        with patch('phase2_engine.registered_match_driver._run', side_effect=AssertionError('must reject first')):
            for match in (replace(self.match, match_seed=1), replace(self.match, opt_in=False)):
                with self.assertRaises(ValueError):
                    simulate_registered_full_a(match, self.registry, self.repo, self.rosters)
            team = self.registry.teams[0]
            duplicate = replace(team, players=(self.registry.teams[1].players[0],) + team.players[1:])
            with self.assertRaises(ValueError):
                simulate_registered_full_a(self.match, replace(self.registry, teams=(duplicate,) + self.registry.teams[1:]), self.repo, self.rosters)
            for seed in (True, -1, 2**63, '1'):
                with self.assertRaises(ValueError):
                    simulate_registered_full_a(self.match, self.registry, self.repo, self.rosters, run_seed=seed)

    def test_actual_pitching_changes_batting_slots_and_inherited_runs(self):
        changes = [e for e in self.result.events if e.replaced_pitcher_id]
        self.assertGreaterEqual(len(changes), 2)
        for change in changes:
            preceding = [e for e in self.result.events[:change.event_no - 1] if e.pitcher_id == change.replaced_pitcher_id]
            self.assertGreaterEqual(len(preceding), 3)
        # Find a real inherited runner crossing after the responsible P leaves.
        result = _run(self.match, 0)
        self.assertTrue(any(e.replaced_pitcher_id and any(e.bases_before) for e in result.events))
        event_oracle(result, self.match)
        self.assertEqual(sum(r.runs for r in result.batter_stats), sum(r.runs_allowed for r in result.pitcher_stats))

    def test_real_walkoff_skipped_bottom_and_extra_innings(self):
        # Each is a complete generated game; no prewritten outcome fixture.
        seen = set()
        for seed in range(60):
            result = _run(self.match, seed)
            event_oracle(result, self.match)
            if result.last_inning > 9:
                seen.add('extra')
            if result.ending_half == 'top':
                self.assertFalse(result.inning_scores[-1].was_played)
                self.assertIsNone(result.inning_scores[-1].runs)
                seen.add('skipped')
            if result.team2_score > result.team1_score and result.ending_half == 'bottom':
                last = result.events[-1]
                self.assertLess(last.outs_before + last.outs_on_play, 3)
                seen.add('walkoff')
            if len(seen) == 3:
                break
        self.assertEqual({'extra', 'skipped', 'walkoff'}, seen)

    def test_tie_and_nonterminating_inning_refuse_no_result(self):
        with patch('game_core.match_simulator.MatchSimulator._weighted_choice', return_value='field_out'):
            with self.assertRaisesRegex(RuntimeError, 'tie'):
                _run(self.match, 0)
        with patch('game_core.match_simulator.MatchSimulator._weighted_choice', return_value='walk'):
            with self.assertRaisesRegex(RuntimeError, 'safety bound'):
                _run(self.match, 0)

    def test_native_handles_closed_and_no_existing_store_mutation(self):
        with retained_handles() as handles:
            repo, rosters, _ = fixture(self.slot)
            registry = registration.registration_from_rosters(repo, rosters)
            simulate_registered_full_a(self.match, registry, repo, rosters)
            assert_closed(self, handles)
            rename_and_read(self, self.slot)
