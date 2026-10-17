"""Saved31/2027/practice1 protected while evidence dry-run generates zero games."""
from dataclasses import replace
from pathlib import Path
import os
import tempfile
from time import perf_counter
import unittest
from unittest.mock import patch

from phase2_engine import competition_evidence_gates as gates
from phase2_engine import saved_practice_match as practice
from phase2_engine import yamanashi_annual_rosters as annual
from phase2_engine.manual_save_backup import _compatibility
from stage43g99_fixture_support import retained_handles, assert_closed
from stage43g115_support import scenario

MEASUREMENTS = {}
ROOT = Path(__file__).resolve().parents[1]


class EvidenceGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        began = perf_counter()
        owners = [tempfile.TemporaryDirectory(prefix='stage115-owned-') for _ in range(3)]
        for owner in owners:
            cls.addClassCleanup(owner.cleanup)
        cls.source = annual.SelfCreated2026(owners[0], opt_in=True)
        cls.addClassCleanup(cls.source.close)
        for _ in range(31):
            cls.source.store.play_next()
        cls.lab = annual.AnnualRosterLab(cls.source, owners[1], opt_in=True)
        cls.addClassCleanup(cls.lab.close)
        assert cls.lab.advance()['accepted']
        cls.store = practice.PracticeStore(cls.lab, owners[2], opt_in=True)
        cls.addClassCleanup(cls.store.close)
        cls.store.play()
        cls.request = scenario(cls.lab)
        cls.saved = practice.saved_authority(cls.lab)
        cls.pins = cls.bytes()
        cls.catalog = _compatibility(ROOT)
        cls.master = {str(p.relative_to(ROOT)): p.read_bytes() for p in (ROOT/'data').rglob('*') if p.is_file()}
        MEASUREMENTS['fixture_seconds'] = round(perf_counter()-began, 3)
        MEASUREMENTS['source'] = dict(saved2026_matches=31, saved2027_schools=33,
            active_players=660, permanent_ids=924, saved2027_practice_matches=1,
            fictional_scenario_teams=3, fictional_joint_teams=1)

    @classmethod
    def bytes(cls):
        return (cls.source._evidence(), annual._sha(cls.lab.db_path), annual._sha(cls.store.db_path))

    def tearDown(self):
        self.assertEqual(self.pins, self.bytes())

    def run_gate(self, request=None, **kwargs):
        return gates.dry_run(self.lab, request or self.request, **dict(fictional_opt_in=True, **kwargs))

    def test_positive_saved_sql_dry_run_with_explicit_joint_seed_bye_and_dates(self):
        began = perf_counter()
        with retained_handles() as handles:
            result = self.run_gate()
            assert_closed(self, handles)
        self.assertTrue(result.fictional_scenario_ready)
        self.assertTrue(result.roster_year_accepted)
        self.assertTrue(result.prior_sealed_year_checked)
        self.assertFalse(result.official_year_verified)
        self.assertFalse(result.product_season_start_authorized)
        self.assertEqual(9, len(result.evidence_digests))
        self.assertEqual(result, self.run_gate())
        self.assertEqual(31, len(self.saved[0].results))
        self.assertEqual(1, len(self.store.snapshot().results))
        self.assertEqual(self.catalog, _compatibility(ROOT))
        self.assertEqual(338, len(self.catalog))
        self.assertEqual(106, sum(p.endswith('.csv') for p in self.master))
        self.assertEqual(self.master, {str(p.relative_to(ROOT)): p.read_bytes()
                                     for p in (ROOT/'data').rglob('*') if p.is_file()})
        MEASUREMENTS['dry_run_seconds'] = round(perf_counter()-began, 3)
        MEASUREMENTS['positive'] = result.to_dict()
        MEASUREMENTS['generated2027_tournament_matches'] = 0
        MEASUREMENTS['generated2027_rankings'] = 0
        MEASUREMENTS['generated_official_calendars'] = 0

    def test_missing_official_entry_qualification_and_schedule_are_independent(self):
        request = gates.CompetitionRequest(self.request.competition_id, 2027,
                                           self.request.competition_type, 'official:2027')
        result = self.run_gate(request)
        self.assertTrue(result.roster_year_accepted)
        self.assertFalse(result.entry_set_checked)
        self.assertFalse(result.fictional_scenario_ready)
        self.assertIn('official_2027_entry_unknown', result.reasons)
        self.assertIn('schedule:missing_evidence', result.reasons)
        MEASUREMENTS['official_missing'] = result.to_dict()
        for name in ('entries', 'joints', 'qualification', 'districts', 'seeds', 'draw', 'schedule'):
            partial = self.run_gate(replace(self.request, **{name: None}))
            self.assertFalse(partial.fictional_scenario_ready)
            self.assertFalse(partial.product_season_start_authorized)
            if name != 'entries':
                self.assertTrue(partial.entry_set_checked)

    def test_fake_official_label_authority_year_and_recipe_do_not_grant_authentication(self):
        for authority in (gates.Authority.OFFICIAL_CLAIM, gates.Authority.HISTORICAL_CONTEXT,
                          'self_created_fictional_scenario'):
            bad = replace(self.request.entries, evidence=replace(self.request.entries.evidence,
                authority=authority, source='https://official.example/2027/verified'))
            self.assertFalse(self.run_gate(replace(self.request, entries=bad)).entry_set_checked)
        for changes in (dict(year=2026), dict(year=True), dict(recipe=''), dict(source='')):
            bad = replace(self.request.entries, evidence=replace(self.request.entries.evidence, **changes))
            self.assertFalse(self.run_gate(replace(self.request, entries=bad)).entry_set_checked)
        fake = replace(self.request.entries, evidence=replace(self.request.entries.evidence,
                       source='official verified source'))
        result = self.run_gate(replace(self.request, entries=fake))
        self.assertTrue(result.fictional_scenario_ready)
        self.assertFalse(result.official_year_verified)

    def test_opt_in_namespace_and_saved_authority_required(self):
        for flag in (False, 1, 'true', None):
            self.assertFalse(gates.dry_run(self.lab, self.request, fictional_opt_in=flag).fictional_scenario_ready)
        self.assertFalse(self.run_gate(replace(self.request, namespace='official:2027')).fictional_scenario_ready)
        for year in (2026, 2028, True, '2027'):
            with self.assertRaises(ValueError):
                self.run_gate(replace(self.request, year=year))
        for source in (object(), self.store):
            with self.assertRaises(ValueError):
                gates.dry_run(source, self.request, fictional_opt_in=True)
        from phase2_engine.saved_school_roster_source import SavedSchoolRosterSource
        with self.assertRaises(ValueError):
            gates.dry_run(SavedSchoolRosterSource.__new__(SavedSchoolRosterSource), self.request, fictional_opt_in=True)

    def test_school_program_team_and_joint_double_entry_rejected(self):
        a, b, joint = self.request.entries.teams
        altered = (replace(b, entry_team_id=a.entry_team_id),
                   replace(b, programs=a.programs, player_ids=a.player_ids),
                   replace(b, programs=joint.programs, player_ids=joint.player_ids),
                   replace(b, programs=((b.programs[0][0], 'unknown-program'),)),
                   replace(b, entry_team_id='CMP000041'),
                   replace(b, programs=()))
        for bad in altered:
            request = replace(self.request, entries=replace(self.request.entries, teams=(a, bad, joint)))
            self.assertFalse(self.run_gate(request).entry_set_checked)
        self.assertFalse(self.run_gate(replace(self.request,
            joints=replace(self.request.joints, teams=()))).joint_composition_checked)

    def test_graduated_other_school_duplicate_and_unrepresented_joint_players_rejected(self):
        a, b, joint = self.request.entries.teams
        graduated = next(p.player_id for r in self.saved[0].rosters for p in r.players if p.academic_year == 3)
        for players in ((graduated,)+a.player_ids[1:], (b.player_ids[0],)+a.player_ids[1:],
                        (a.player_ids[0],)*20, a.player_ids[:19]):
            bad = replace(a, player_ids=players)
            request = replace(self.request, entries=replace(self.request.entries, teams=(bad, b, joint)))
            self.assertFalse(self.run_gate(request).entry_set_checked)
        sid = joint.programs[0][0]
        roster = next(r for r in self.saved[1] if r.school_id == sid)
        bad = replace(joint, player_ids=tuple(p.player_id for p in roster.players))
        self.assertFalse(self.run_gate(replace(self.request,
            entries=replace(self.request.entries, teams=(a, b, bad)))).entry_set_checked)

    def test_qualification_prior_receipt_exemption_seed_district_and_bracket_fail_closed(self):
        q = self.request.qualification
        a = self.request.entries.teams[0].entry_team_id
        cases = (
            ('qualification', replace(q, decisions=q.decisions[:-1])),
            ('qualification', replace(q, decisions=(replace(q.decisions[0], eligible=False),)+q.decisions[1:])),
            ('qualification', replace(q, decisions=q.decisions+(q.decisions[0],))),
            ('qualification', replace(q, prior_year_receipt_sha256='practice-or-roster-only')),
            ('qualification', replace(q, decisions=(replace(q.decisions[0], basis='practice_result'),)+q.decisions[1:])),
            ('qualification', replace(q, decisions=(replace(q.decisions[0], exempt=1),)+q.decisions[1:])),
            ('districts', replace(self.request.districts, rule_version='')),
            ('districts', replace(self.request.districts, memberships=self.request.districts.memberships[:-1])),
            ('seeds', replace(self.request.seeds, seeds=((a, True),))),
            ('seeds', replace(self.request.seeds, seeds=((a, 1), (a, 1)))),
            ('draw', replace(self.request.draw, participant_slots=32)),
            ('draw', replace(self.request.draw, bye_count=0)),
            ('draw', replace(self.request.draw, bracket_size=3)),
        )
        for name, value in cases:
            with self.subTest(gate=name, value=value):
                self.assertFalse(self.run_gate(replace(self.request, **{name: value})).fictional_scenario_ready)
        # Explicit no-prior/no-seed choices are valid, never inferred from absence.
        request = replace(self.request, qualification=replace(q,
            decisions=tuple(replace(d, basis='explicit_scenario', exempt=True) for d in q.decisions),
            prior_year_receipt_sha256=None), seeds=replace(self.request.seeds, seeds=()))
        self.assertTrue(self.run_gate(request).fictional_scenario_ready)

    def test_schedule_wrong_year_dates_order_and_gate_digest_independence(self):
        for dates in ((), ('2027-07-01',), ('2026-07-01', '2026-07-03'),
                      ('2027-07-01', '2027-07-01'), ('2027-07-03', '2027-07-01'),
                      ('2027-02-30', '2027-07-03')):
            self.assertFalse(self.run_gate(replace(self.request,
                schedule=replace(self.request.schedule, round_dates=dates))).schedule_checked)
        original = self.run_gate()
        changed = self.run_gate(replace(self.request,
            schedule=replace(self.request.schedule, round_dates=('2027-07-02', '2027-07-04'))))
        self.assertTrue(changed.fictional_scenario_ready)
        old, new = dict(original.evidence_digests), dict(changed.evidence_digests)
        self.assertEqual(['schedule'], [key for key in old if old[key] != new[key]])
        self.assertNotEqual(original.request_sha256, changed.request_sha256)

    def test_no_simulation_history_writer_or_generator_invoked_by_dry_run(self):
        from game_core.players import PlayerRosterGenerator
        from phase2_engine.live_game_service import LiveGameService
        # Source audits intentionally replay saved2026 and check its generator recipe.
        # Isolate the new layer only after obtaining that actual validated receipt.
        with patch.object(gates, 'saved_authority', return_value=self.saved), \
             patch.object(practice, '_run', side_effect=AssertionError('no game')), \
             patch.object(PlayerRosterGenerator, 'generate_for_school_id', side_effect=AssertionError('no regeneration')), \
             patch.object(LiveGameService, 'load_game', side_effect=AssertionError('no replay')):
            self.assertTrue(self.run_gate().fictional_scenario_ready)

    def test_source_sidecars_and_hardlink_rejected_before_sql_and_bytes_unchanged(self):
        import sqlite3
        connect = sqlite3.connect
        guarded_path = None
        def checked_connect(database, *args, **kwargs):
            if str(guarded_path) in str(database):
                raise AssertionError('no SQL on guarded source')
            return connect(database, *args, **kwargs)
        for path in (self.lab.db_path, self.source.store.db_path):
            guarded_path = path
            for suffix in ('-journal', '-wal', '-shm'):
                side = Path(str(path)+suffix)
                side.write_bytes(b'foreign-sidecar-no-recovery')
                try:
                    before = path.read_bytes()
                    with patch.object(sqlite3, 'connect', side_effect=checked_connect):
                        with self.assertRaises(ValueError):
                            self.run_gate()
                    self.assertEqual(before, path.read_bytes())
                    self.assertEqual(b'foreign-sidecar-no-recovery', side.read_bytes())
                finally:
                    side.unlink()
        with tempfile.TemporaryDirectory(prefix='stage115-link-') as owned:
            link = Path(owned)/'linked'
            os.link(self.lab.db_path, link)
            guarded_path = self.lab.db_path
            try:
                with patch.object(sqlite3, 'connect', side_effect=checked_connect):
                    with self.assertRaises(ValueError):
                        self.run_gate()
            finally:
                link.unlink()

    def test_incomplete_saved2027_year_is_not_roster_accepted(self):
        owner = tempfile.TemporaryDirectory(prefix='stage115-incomplete-')
        self.addCleanup(owner.cleanup)
        incomplete = annual.AnnualRosterLab(self.source, owner, opt_in=True)
        try:
            with self.assertRaises(ValueError):
                gates.dry_run(incomplete, self.request, fictional_opt_in=True)
        finally:
            incomplete.close()
