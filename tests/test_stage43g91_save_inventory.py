"""Owned fixtures only: actual legacy service/replay versus synthetic v2."""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_v2_national_storage_audit import synthetic_storage_fixture
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.live_game_service import LiveGameService
from phase2_engine.live_season_planner import LiveSeasonGraphPlan, LiveSeasonGraphPlanner
from phase2_engine.live_season_save import rechecksum_live_season_save_payload
from phase2_engine.repository import DataRepository
from phase2_engine.save_inventory_audit import InventoryRefused, inventory_slot, file_digest

from stage43g91_fixture_support import closed_archive_connection

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026101201


class StaticPlanner:
    def __init__(self, plan):
        self.plan, self.year, self.rng_seed = plan, plan.year, plan.rng_seed

    def build_plan(self):
        return self.plan


def private_anchor(root):
    return {p.relative_to(root).as_posix(): file_digest(p)
            for p in root.rglob('*') if p.is_file()}


class Stage43G91InventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for archive_class in (HistoricalMatchArchive, CareerRosterArchive):
            lifetime = patch.object(archive_class, '_connect', closed_archive_connection)
            lifetime.start()
            cls.addClassCleanup(lifetime.stop)
        cls.repo = DataRepository(ROOT / 'data')
        full = LiveSeasonGraphPlanner(cls.repo, ROOT / 'data', SEED, year=2026).build_plan()
        keep = ['CMP000029', 'CMP000077']
        cls.plan = LiveSeasonGraphPlan(
            repo=full.repo, data_dir=full.data_dir, year=full.year, rng_seed=full.rng_seed,
            entries={k: full.entries[k] for k in keep},
            annual_templates={k: full.annual_templates[k] for k in keep},
            annual_build_strategies={k: full.annual_build_strategies[k] for k in keep},
            calendar_rows=[r for r in full.calendar_rows if r['competition_id'] in keep],
            stage_calendar_rows=full.stage_calendar_rows,
            dependency_edges=[tuple(keep)], topological_order=keep,
        )
        cls.base = tempfile.TemporaryDirectory(prefix='stage91-fixture-')
        cls.addClassCleanup(cls.base.cleanup)
        cls.legacy = Path(cls.base.name) / 'legacy'
        cls.service(cls.legacy.parent).new_game('legacy', rng_seed=SEED, start_date='2026-07-01')
        session = cls.service(cls.legacy.parent).load_game('legacy')
        cls.service(cls.legacy.parent).advance_through(session, '2026-07-12')
        assert sum(len(s.matches) for s in session.state.competitions.values()) > 0
        assert json.loads((cls.legacy / 'autosave.json').read_text(encoding='utf-8'))['completed_match_results']
        cls.v2 = Path(cls.base.name) / 'v2'
        cls.v2.mkdir()
        with synthetic_storage_fixture(ROOT / 'data', schools=2, years=2,
                                       rounds=1, first_year=10099, seed=SEED) as f:
            for p in (f.source, f.calendar, f.legacy):
                shutil.copy2(p, cls.v2 / p.name)

    @classmethod
    def service(cls, root):
        return LiveGameService(cls.repo, ROOT / 'data', save_root=root,
                               planner_factory=lambda *args: StaticPlanner(cls.plan))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='stage91-case-')
        self.addCleanup(self.temp.cleanup)
        self.slot = Path(self.temp.name) / 'owned_slot'
        shutil.copytree(self.legacy, self.slot)
        self.anchor = private_anchor(self.slot)

    def audit(self, **kwargs):
        args = dict(slot_id='owned_slot', contract='legacy_live', source='autosave',
                    authorized_read=True, expected_files=self.anchor)
        args.update(kwargs)
        return inventory_slot(self.slot, **args)

    def v2_slot(self):
        # Mutations below are ONLY within this test's owned TemporaryDirectory.
        shutil.rmtree(self.slot)
        shutil.copytree(self.v2, self.slot)
        self.anchor = private_anchor(self.slot)

    def test_permission_is_required_before_read(self):
        with patch('phase2_engine.save_inventory_audit.file_digest', side_effect=AssertionError('read')):
            with self.assertRaisesRegex(InventoryRefused, '^read_authorization_required$'):
                self.audit(authorized_read=False)

    def test_actual_legacy_manual_autosave_contract_and_readonly(self):
        before = private_anchor(self.slot)
        with patch.object(LiveGameService, 'load_game', side_effect=AssertionError('replay writes')):
            current = self.audit()
            older = self.audit(source='manual')
        self.assertTrue(current['contract_consistent'])
        self.assertTrue(older['contract_consistent'])
        self.assertGreater(current['counts']['live_completed_matches'], 0)
        self.assertIn('archive_ahead_preserve_history_no_rollback', older['notes'])
        self.assertEqual(before, private_anchor(self.slot))
        self.assertFalse(current['whole_game_restore_proven'])
        self.assertFalse(current['restoration_authorized'])
        self.assertNotIn('fictional_years', current['counts'])

    def test_seed_replay_preserves_source_match_facts_and_history(self):
        path = self.slot / 'historical_matches.sqlite3'
        with closing(sqlite3.connect(path)) as con:
            before = con.execute('SELECT year,competition_id,match_id,payload_json FROM historical_matches ORDER BY 1,2,3').fetchall()
        service = self.service(self.slot.parent)
        first = service.load_game('owned_slot', source='autosave')
        second = service.load_game('owned_slot', source='autosave')
        self.assertEqual(first.state.public_snapshot(), second.state.public_snapshot())
        service.load_game('owned_slot', source='manual')
        with closing(sqlite3.connect(path)) as con:
            self.assertEqual(before, con.execute('SELECT year,competition_id,match_id,payload_json FROM historical_matches ORDER BY 1,2,3').fetchall())

    def test_json_commit_before_archive_sync_is_reported_without_repair(self):
        service = self.service(self.slot.parent)
        session = service.load_game('owned_slot', source='autosave')
        with patch.object(service, '_sync_history', side_effect=RuntimeError('fixture boundary')):
            with self.assertRaisesRegex(RuntimeError, 'fixture boundary'):
                service.advance_through(session, '2026-07-18')
        self.anchor = private_anchor(self.slot)
        result = self.audit()
        self.assertTrue(result['contract_consistent'])
        self.assertIn('json_ahead_current_year_replay_sync_candidate', result['notes'])
        self.assertEqual(self.anchor, private_anchor(self.slot))
        # Demonstrate EXISTING explicit fixture load semantics, not new recovery.
        service.load_game('owned_slot', source='autosave')
        self.anchor = private_anchor(self.slot)
        self.assertNotIn('json_ahead_current_year_replay_sync_candidate', self.audit()['notes'])

    def test_missing_originals_refuse_but_missing_derived_is_disposable(self):
        for name, role in [('autosave.json', 'autosave'), ('historical_matches.sqlite3', 'legacy_history')]:
            with self.subTest(role=role):
                saved = (self.slot / name).read_bytes()
                (self.slot / name).unlink()
                self.assertIn('required_original_missing:' + role, self.audit()['blockers'])
                (self.slot / name).write_bytes(saved)
        self.assertTrue(self.audit()['contract_consistent'])
        self.assertFalse(self.audit()['roles']['legacy_stats']['present'])
        self.assertIn('derived_indexes_unused_explicit_rebuild_and_selection_only', self.audit()['notes'])

    def test_derived_index_loss_never_requires_original_repair(self):
        index = self.slot / 'fictional_v2_school_read_index_test.sqlite3'
        index.write_bytes(b'unused synthetic index')
        self.anchor = private_anchor(self.slot)
        index.unlink()
        # No index activation or schema parsing, even when the anchor names it.
        result = self.audit()
        self.assertTrue(result['contract_consistent'], result['blockers'])
        self.assertIn('derived_anchor_mismatch_unused', result['notes'])

    def test_different_seed_same_schema_is_cross_contract_refusal(self):
        path = self.slot / 'autosave.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['rng_seed'] += 1
        path.write_text(json.dumps(rechecksum_live_season_save_payload(data)), encoding='utf-8')
        result = self.audit(expected_files=None)
        self.assertIn('original_contract_invalid:live_archive_pair', result['blockers'])

    def test_slot_name_and_checksum_bound_checkpoint_mismatch(self):
        with self.assertRaisesRegex(InventoryRefused, '^slot_root_mismatch$'):
            self.audit(slot_id='different_slot')
        folder = self.slot / 'career_multi_previews'
        folder.mkdir()
        # Real checkpoint checksum and slot fields; replay is outside this API.
        value = {'schema_version': 'career_multi_preview_sandbox_v1', 'slot_id': 'foreign', 'year': 2027}
        value['payload_checksum'] = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        (folder / '2027.json').write_text(json.dumps(value), encoding='utf-8')
        self.assertIn('original_contract_invalid:checkpoint', self.audit(expected_files=None)['blockers'])

    def test_identical_content_foreign_slot_requires_private_pin(self):
        result = self.audit(expected_files=None)
        self.assertIn('slot_and_complete_history_not_proven_without_private_anchor', result['notes'])
        other = deepcopy(self.anchor)
        other['historical_matches.sqlite3'] = '0' * 64
        self.assertIn('pinned_original_missing_or_mismatched', self.audit(expected_files=other)['blockers'])

    def test_v2_year10099_10100_is_synthetic_and_keeps_old_iso_guard(self):
        self.v2_slot()
        result = self.audit(contract='fictional_v2')
        self.assertTrue(result['contract_consistent'], result['blockers'])
        self.assertEqual(2, result['counts']['fictional_years'])
        self.assertEqual(2, result['counts']['fictional_matches'])
        self.assertFalse(result['fictional_v2_is_live_progression'])
        self.assertEqual(self.anchor, private_anchor(self.slot))
        legacy = self.audit(contract='legacy_history')
        self.assertEqual(1, legacy['counts']['legacy_sealed_years'])
        with closing(sqlite3.connect(self.slot / 'historical_matches.sqlite3')) as con:
            record = json.loads(con.execute('SELECT payload_json FROM historical_matches').fetchone()[0])
        self.assertTrue(record['match_date'].startswith('2026-'))
        for key in ('inning_scores', 'batter_stats', 'pitcher_stats'):
            self.assertTrue(record[key])

    def test_calendar_missing_or_generation_different_refuses(self):
        self.v2_slot()
        calendar = self.slot / 'sandbox_calendar_v2.sqlite3'
        saved = calendar.read_bytes()
        calendar.unlink()
        self.assertIn('required_original_missing:v2_calendar', self.audit(contract='fictional_v2')['blockers'])
        calendar.write_bytes(saved)
        with closing(sqlite3.connect(self.slot / 'fictional_option_a_v2.sqlite3')) as con, con:
            con.execute("UPDATE v2_game_years SET calendar_sha256=? WHERE year=10100", ('f'*64,))
        self.assertIn('original_contract_invalid:v2_history', self.audit(contract='fictional_v2', expected_files=None)['blockers'])

    def test_full_a_ledger_corruption_refuses_no_sha_leak(self):
        self.v2_slot()
        with closing(sqlite3.connect(self.slot / 'fictional_option_a_v2.sqlite3')) as con, con:
            con.execute("UPDATE v2_option_a_matches SET payload_json='sensitive/path/SCHOOL-PRIVATE'")
        result = self.audit(contract='fictional_v2', expected_files=None)
        self.assertFalse(result['contract_consistent'])
        encoded = json.dumps(result)
        self.assertNotIn('sensitive', encoded)
        self.assertNotIn('SCHOOL-PRIVATE', encoded)
        self.assertNotIn(str(self.slot), encoded)
        self.assertTrue(all(sha not in encoded for sha in self.anchor.values()))

    def test_valid_but_truncated_history_is_rejected_by_private_pin(self):
        self.v2_slot()
        with closing(sqlite3.connect(self.slot / 'fictional_option_a_v2.sqlite3')) as con, con:
            con.execute('DELETE FROM v2_option_a_matches WHERE year=10100')
            con.execute('DELETE FROM v2_game_years WHERE year=10100')
        with closing(sqlite3.connect(self.slot / 'sandbox_calendar_v2.sqlite3')) as con, con:
            con.execute('DELETE FROM sandbox_year_plans WHERE game_year=10100')
        result = self.audit(contract='fictional_v2')
        self.assertIn('pinned_original_missing_or_mismatched', result['blockers'])
        self.assertEqual(1, result['counts']['fictional_years'])

    def test_active_v2_is_not_sealed_history(self):
        self.v2_slot()
        with closing(sqlite3.connect(self.slot / 'fictional_option_a_v2.sqlite3')) as con, con:
            con.execute("UPDATE v2_game_years SET status='active',match_count=NULL,ledger_sha256=NULL WHERE year=10100")
        self.assertIn('fictional_active_year_not_sealed_history', self.audit(contract='fictional_v2', expected_files=None)['blockers'])

    def test_roster_identity_missing_and_corrupt_refuses_player_history(self):
        self.assertIn('required_original_missing:rosters', self.audit(contract='legacy_player_history')['blockers'])
        rosters = CareerRosterArchive(self.slot / 'career_rosters.sqlite3')
        sid = sorted(self.repo.school_to_program)[0]
        roster = PlayerRosterGenerator().generate_for_school_id(self.repo, sid, 2026, SEED)
        rosters.save_initial_roster(roster)
        self.anchor = private_anchor(self.slot)
        result = self.audit(contract='legacy_player_history')
        self.assertTrue(result['contract_consistent'])
        self.assertEqual(20, result['counts']['player_identities'])
        with closing(sqlite3.connect(rosters.db_path)) as con, con:
            con.execute('DELETE FROM career_player_identities WHERE player_id=?', (roster.players[0].player_id,))
        self.assertIn('original_contract_invalid:rosters', self.audit(contract='legacy_player_history', expected_files=None)['blockers'])

    def test_wal_and_journal_are_refused_before_immutable_sqlite(self):
        for suffix in ('-wal', '-shm', '-journal'):
            path = self.slot / ('historical_matches.sqlite3' + suffix)
            path.write_bytes(b'committed data must not be ignored')
            with self.subTest(suffix=suffix), patch('phase2_engine.save_inventory_audit._ro', side_effect=AssertionError('read')):
                with self.assertRaisesRegex(InventoryRefused, '^quiescent_copy_required$'):
                    self.audit()
            path.unlink()

    def test_symlink_and_path_escape_refuse(self):
        link = self.slot / 'external.json'
        try:
            link.symlink_to(self.slot / 'manual.json')
        except OSError:
            self.skipTest('OS does not permit symlink creation')
        with self.assertRaisesRegex(InventoryRefused, '^symlink_input$'):
            self.audit()
        link.unlink()
        with self.assertRaisesRegex(InventoryRefused, '^invalid_request$'):
            self.audit(slot_id='../foreign')

    def test_input_mutation_is_detected_and_never_repaired(self):
        import phase2_engine.save_inventory_audit as audit_module
        original = audit_module._history
        def modify(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.slot / 'unexpected.txt').write_text('owned fixture mutation', encoding='utf-8')
            return result
        with patch.object(audit_module, '_history', side_effect=modify):
            result = self.audit()
        self.assertIn('input_changed_during_audit', result['blockers'])
        self.assertFalse(result['input_bytes_unchanged'])
        self.assertTrue((self.slot / 'unexpected.txt').is_file())


if __name__ == '__main__':
    unittest.main()
