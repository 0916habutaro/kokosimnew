"""Product API/CLI fault boundaries, all inputs self-owned temporary saves."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import errno
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from phase2_engine import manual_save_backup as product
from phase2_engine.legacy_backup_oracle import facts
from phase2_engine.live_game_service import LiveGameService
from phase2_engine.live_season_save import rechecksum_live_season_save_payload
from stage43g94_fixture_support import Fixture, METRICS, owned_sqlite_handles
from test_stage43g91_save_inventory import private_anchor, ROOT


class Stage43G94ManualBackupTests(unittest.TestCase):
    def fixture(self, phase='active'):
        f = Fixture(phase)
        self.addCleanup(f.close)
        return f

    def refused(self, f, code=None, **args):
        before = private_anchor(f.slot)
        with self.assertRaises(product.BackupRefused) as error:
            product.export_backup(**f.args(**args))
        if code:
            self.assertEqual(code, str(error.exception))
        self.assertEqual(before, private_anchor(f.slot))
        if f.destination.exists():
            self.assertFalse((f.destination/'COMPLETE').exists())
        return str(error.exception)

    def tamper_json(self, path, **fields):
        body = json.loads(path.read_text(encoding='utf-8'))
        body.update(fields)
        path.write_text(json.dumps(rechecksum_live_season_save_payload(body)), encoding='utf-8')

    def test_service_manual_autosave_sealed_registration_zero_write_full_history(self):
        for phase in ('active', 'sealed', 'registered'):
            for source in ('manual', 'autosave'):
                with self.subTest(phase=phase, source=source):
                    f = self.fixture(phase)
                    before = private_anchor(f.slot)
                    raw = facts(f.slot)
                    with patch.object(LiveGameService, 'load_game', side_effect=AssertionError('writes')):
                        result = product.export_backup(**f.args(source=source))
                        verified = product.verify_candidate(candidate=f.destination)
                    self.assertEqual(before, private_anchor(f.slot))
                    self.assertEqual(raw, facts(f.destination/'payload'/'owned94'))
                    self.assertTrue(verified['candidate_consistent'])
                    self.assertFalse(verified['restoration_authorized'])
                    self.assertFalse(verified['evidence_authenticated'])
                    self.assertEqual(before.keys(), private_anchor(f.destination/'payload'/'owned94').keys())
                    self.assertGreater(result['counts']['legacy_complete_a_matches'], 0)
                    METRICS.append(dict(phase=phase, **result))

    def test_declaration_required_before_any_read_or_write(self):
        f = self.fixture()
        with patch.object(product, '_path', side_effect=AssertionError('read')):
            self.refused(f, 'game_stopped_declaration_required', confirm_game_stopped=False)
        self.assertFalse(f.destination.exists())

    def test_all_selectors_are_explicit(self):
        f = self.fixture()
        for source in ('latest', '', 'manual_backup_001', 'unknown'):
            self.refused(f, 'explicit_checkpoint_required', source=source)
        for sid in ('../owned94', '', 'foreign'):
            self.refused(f, slot_id=sid)

    def test_existing_empty_and_nonempty_destination_preserved(self):
        for populated in (False, True):
            f = self.fixture()
            f.destination.mkdir()
            if populated:
                (f.destination/'retained').write_bytes(b'previous-output')
            pin = private_anchor(f.destination)
            self.refused(f, 'destination_exists')
            self.assertEqual(pin, private_anchor(f.destination))

    def test_save_area_containment_and_ancestor_refused(self):
        f = self.fixture()
        for destination in (f.slot, f.slot/'child', f.save_root/'other', f.root):
            self.refused(f, 'destination_overlaps_save_area', destination=destination)

    def test_absolute_no_parent_traversal_and_missing_parent(self):
        f = self.fixture()
        for dest in ('relative', f.root/'..'/'escape'):
            self.refused(f, 'explicit_absolute_path_required', destination=dest)
        self.refused(f, 'destination_parent_missing', destination=f.root/'absent'/'new')

    def test_unknown_file_and_unknown_table(self):
        f = self.fixture()
        (f.slot/'secret.env').write_bytes(b'fixture-only')
        self.refused(f, 'unknown_or_unsupported_original')
        (f.slot/'secret.env').unlink()
        with closing(sqlite3.connect(f.slot/'historical_matches.sqlite3')) as con:
            con.execute('CREATE TABLE unknown_authority(id INTEGER)')
        self.refused(f, 'original_or_candidate_contract_refused')

    def test_transient_json_and_sqlite_artifacts(self):
        f = self.fixture()
        for name in ('manual.json.tmp', 'historical_matches.sqlite3-wal',
                     'career_rosters.sqlite3-shm', 'historical_matches.sqlite3-journal'):
            p = f.slot/name
            p.write_bytes(b'fixture-artifact')
            self.refused(f, 'non_quiescent_artifact')
            p.unlink()

    def test_true_uncheckpointed_wal_writer_is_refused(self):
        f = self.fixture()
        with closing(sqlite3.connect(f.slot/'historical_matches.sqlite3')) as con:
            con.execute('PRAGMA journal_mode=WAL')
            con.execute('BEGIN IMMEDIATE')
            con.execute('UPDATE career_years SET match_count=match_count')
            con.commit()
            self.refused(f, 'non_quiescent_artifact')

    def test_old_current_chain_refuses_but_rolling_backups_are_kept(self):
        f = self.fixture('sealed')
        backups = sorted((f.slot/'backups').glob('*.json'))
        self.assertTrue(backups)
        old = next(p for p in backups if len(json.loads(p.read_text())['completed_match_results']) < 7)
        shutil.copyfile(old, f.slot/'manual.json')
        self.refused(f, 'unsupported_needs_manual_review')

    def test_json_checksum_seed_plan_resolver_versions_refused(self):
        for field, value in (('rng_seed', 999), ('plan_fingerprint', 'changed'),
                             ('resolver_contract', 'unknown-v99'), ('schema_version', 'unknown-v99')):
            f = self.fixture()
            self.tamper_json(f.slot/'manual.json', **{field:value})
            self.refused(f)
        f = self.fixture()
        (f.slot/'manual.json').write_bytes(b'{"payload_checksum":"invalid"}')
        self.refused(f)

    def test_slot_metadata_from_different_slot_refuses(self):
        f = self.fixture()
        (f.slot/'slot_metadata.json').write_text('{"slot_id":"different"}', encoding='utf-8')
        self.refused(f, 'slot_identity_mismatch')

    def test_required_history_roster_or_checkpoint_missing(self):
        for name in ('historical_matches.sqlite3', 'career_rosters.sqlite3', 'manual.json'):
            f = self.fixture()
            (f.slot/name).unlink()
            self.refused(f, 'inventory_contract_refused')

    def test_sealed_ledger_roster_identity_and_outcomes_mutations(self):
        mutations = [('historical_matches.sqlite3', "UPDATE career_years SET ledger_sha256='changed' WHERE status='sealed'"),
                     ('career_rosters.sqlite3', "UPDATE career_player_identities SET identity_sha256='changed'"),
                     ('historical_matches.sqlite3', "UPDATE historical_competition_outcomes SET record_sha256='changed'")]
        for name, sql in mutations:
            f = self.fixture('sealed')
            with closing(sqlite3.connect(f.slot/name)) as con:
                con.execute(sql)
                con.commit()
            self.refused(f)

    def test_all_complex_checkpoint_families_fail_closed(self):
        from phase2_engine.save_inventory_audit import CHECKPOINT_DIRS
        for directory in CHECKPOINT_DIRS:
            f = self.fixture()
            (f.slot/directory).mkdir()
            (f.slot/directory/'2026.json').write_bytes(b'{}')
            self.refused(f, 'unsupported_needs_manual_review')

    def test_actual_multi_preview_career_refuses(self):
        from game_core.players import PlayerRosterGenerator
        from phase2_engine.career_roster_archive import CareerRosterArchive
        from phase2_engine.historical_match_archive import HistoricalMatchArchive
        from phase2_engine.career_multi_preview_checkpoint import CareerMultiPreviewCheckpointService
        from stage43g91_fixture_support import closed_archive_connection
        from test_stage43g92_legacy_replay import Stage43G92LegacyReplayTests, SEED
        f = self.fixture('sealed')
        repo = Stage43G92LegacyReplayTests.repo
        groups = {cid: sorted(s for s in repo.school_to_program if repo.schools[s]['prefecture_code'] == pref)[:8]
                  for cid, pref in (('CMP000086', '09'), ('CMP000088', '10'))}
        with owned_sqlite_handles(), \
             patch.object(CareerRosterArchive, '_connect', closed_archive_connection), \
             patch.object(HistoricalMatchArchive, '_connect', closed_archive_connection):
            rosters = CareerRosterArchive(f.slot/'career_rosters.sqlite3')
            for sid in [s for group in groups.values() for s in group]:
                rosters.save_initial_roster(PlayerRosterGenerator().generate_for_school_id(repo,sid,2026,SEED))
                rosters.advance_and_save(repo.team(sid), next_year=2027, career_seed=SEED)
            multi = CareerMultiPreviewCheckpointService(repo, ROOT/'data',save_root=f.save_root,
                ability_config_dir=ROOT/'config'/'abilities',match_config_dir=ROOT/'config'/'match')
            multi.start('owned94',year=2027,competitions=[dict(competition_id=cid,
                entry_mode='kanto_direct_main_v1',entrant_school_ids=schools,group_entrant_school_ids={})
                for cid,schools in groups.items()],base_seed=SEED,career_seed=SEED)
        self.assertTrue((f.slot/'career_multi_previews'/'2027.json').is_file())
        self.refused(f,'unsupported_needs_manual_review')

    def test_dependency_runtime_even_without_sidecar_refuses(self):
        f = self.fixture()
        body = json.loads((f.slot/'manual.json').read_text())
        body['runtime_summary']['regional_feeder_resolution_count'] = 1
        self.tamper_json(f.slot/'manual.json', runtime_summary=body['runtime_summary'])
        self.refused(f, 'unsupported_needs_manual_review')

    def test_foreign_backup_seed_and_missing_roster_membership_refuse(self):
        f = self.fixture()
        self.tamper_json(next((f.slot/'backups').glob('*.json')), rng_seed=999)
        self.refused(f, 'checkpoint_collection_identity_mismatch')
        f = self.fixture()
        with closing(sqlite3.connect(f.slot/'career_rosters.sqlite3')) as con:
            con.execute('DELETE FROM career_school_rosters')
            con.commit()
        self.refused(f, 'original_or_candidate_contract_refused')

    def test_final_source_change_refuses_and_output_tamper_after_success_refuses(self):
        f = self.fixture()
        original = product._compatibility
        calls = 0
        def compatibility(root):
            nonlocal calls
            result = original(root)
            calls += 1
            if calls == 2:
                (f.slot/'manual.json').write_bytes(b'injected-late-writer')
            return result
        with patch.object(product, '_compatibility', compatibility):
            with self.assertRaises(product.BackupRefused):
                product.export_backup(**f.args())
        self.assertFalse((f.destination/'COMPLETE').exists())
        f = self.fixture()
        product.export_backup(**f.args())
        (f.destination/'payload'/'owned94'/'manual.json').write_bytes(b'after-success')
        with self.assertRaises(product.BackupRefused):
            product.verify_candidate(candidate=f.destination)

    def test_incomplete_receipt_io_failure_is_not_completion(self):
        f = self.fixture()
        original = Path.open
        def opened(path, *args, **kwargs):
            if path == f.destination/'COMPLETE':
                raise OSError(errno.EIO, 'injected receipt write fault')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',opened):
            self.refused(f,'io_failure')
        with self.assertRaisesRegex(product.BackupRefused,'incomplete_candidate'):
            product.verify_candidate(candidate=f.destination)

    def test_cross_filesystem_entry_refused(self):
        f = self.fixture()
        original = Path.stat
        def changed(path,*args,**kwargs):
            result = original(path,*args,**kwargs)
            if path == f.slot/'manual.json':
                fields = list(result)
                fields[2] += 1
                return os.stat_result(fields)
            return result
        with patch.object(Path,'stat',changed):
            with self.assertRaisesRegex(product.BackupRefused,'cross_filesystem'):
                product.export_backup(**f.args())
        self.assertFalse(f.destination.exists())

    def test_fictional_v2_cannot_mix_with_legacy(self):
        f = self.fixture()
        (f.slot/'sandbox_calendar_v2.sqlite3').write_bytes(b'fixture')
        self.refused(f, 'unknown_or_unsupported_original')

    def test_derived_files_are_unused_not_copied_or_deleted(self):
        f = self.fixture()
        for name in ('derived_player_stats.sqlite3', 'fictional_v2_school_read_index_local.sqlite3'):
            (f.slot/name).write_bytes(b'unused cache no SQL access')
        result = product.export_backup(**f.args())
        self.assertTrue(result['source_zero_write'])
        target = f.destination/'payload'/'owned94'
        self.assertFalse((target/'derived_player_stats.sqlite3').exists())
        self.assertTrue((f.slot/'derived_player_stats.sqlite3').exists())
        self.assertTrue(product.verify_candidate(candidate=f.destination)['candidate_consistent'])

    def test_fixed_compatibility_missing_and_changed_no_arbitrary_copy(self):
        f = self.fixture()
        # Bind a required allowlisted name to a synthetic missing/hash mismatch;
        # never change the real repository dependency or user's master CSV.
        for catalog in ({'data/absent-fixture.csv':'0'*64}, {'data/master/schools.csv':'0'*64}):
            with patch.object(product, 'CATALOG', catalog):
                self.refused(f)
        (f.root/'.env').write_bytes(b'fixture-private-do-not-copy')
        product.export_backup(**f.args())
        self.assertFalse(any(p.name == '.env' for p in f.destination.rglob('*')))

    def test_hardlinked_source_and_destination_parent_link(self):
        f = self.fixture()
        os.link(f.slot/'manual.json', f.root/'hardlink')
        self.refused(f, 'hardlinked_file')

    def test_symlink_aliases_and_junctions_refused(self):
        f = self.fixture()
        alias = f.root/'alias'
        if os.name == 'nt':
            proc = subprocess.run(['cmd','/c','mklink','/J',str(alias),str(f.save_root)], capture_output=True)
            self.assertEqual(0, proc.returncode)
            self.addCleanup(lambda: os.rmdir(alias) if alias.exists() else None)
        else:
            alias.symlink_to(f.save_root, target_is_directory=True)
        self.refused(f, 'linked_path', destination=alias/'backup')
        self.refused(f, 'linked_path', save_root=alias)

    def test_source_symlink_or_junction_never_followed(self):
        f = self.fixture()
        alias = f.slot/'linked'
        if os.name == 'nt':
            proc = subprocess.run(['cmd','/c','mklink','/J',str(alias),str(f.root)], capture_output=True)
            self.assertEqual(0, proc.returncode)
            self.addCleanup(lambda: os.rmdir(alias) if alias.exists() else None)
        else:
            alias.symlink_to(f.root, target_is_directory=True)
        with self.assertRaisesRegex(product.BackupRefused, '^linked_path$'):
            product.export_backup(**f.args())
        self.assertFalse(f.destination.exists())

    def test_copy_database_uses_readonly_backup_and_releases_handles(self):
        f = self.fixture()
        original = product.ro
        def checked(path):
            con = original(path)
            self.assertEqual(1, con.execute('PRAGMA query_only').fetchone()[0])
            with self.assertRaises(sqlite3.OperationalError):
                con.execute('DELETE FROM career_years')
            return con
        with patch.object(product, 'ro', checked):
            product.export_backup(**f.args())
        product.verify_candidate(candidate=f.destination)
        f.destination.rename(f.root/'moved')
        with closing(sqlite3.connect(f.slot/'historical_matches.sqlite3', timeout=0)) as con:
            con.execute('BEGIN EXCLUSIVE')
            con.rollback()

    def test_copy_faults_leave_incomplete_no_clobber_candidates(self):
        for error in (OSError(errno.ENOSPC,'private path disk full'), OSError(errno.EIO,'private path IO'), KeyboardInterrupt()):
            f = self.fixture()
            with patch.object(product, '_copy_file', side_effect=error):
                self.refused(f)
            self.assertTrue(f.destination.exists())
            with self.assertRaisesRegex(product.BackupRefused, 'incomplete_candidate'):
                product.verify_candidate(candidate=f.destination)
            self.refused(f, 'destination_exists')

    def test_sqlite_backup_io_fault_releases_readonly_source(self):
        f = self.fixture()
        class Fault(sqlite3.Connection):
            def backup(self, *args, **kwargs):
                if self.execute('PRAGMA query_only').fetchone()[0] != 1:
                    raise AssertionError('not read-only')
                raise OSError(errno.ENOSPC, 'fixture')
        def faulty_ro(path):
            con = sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1', uri=True, factory=Fault)
            con.execute('PRAGMA query_only=ON')
            return con
        with patch.object(product, 'ro', faulty_ro):
            self.refused(f, 'io_failure')
        with closing(sqlite3.connect(f.slot/'historical_matches.sqlite3', timeout=0)) as con:
            con.execute('BEGIN EXCLUSIVE')
            con.rollback()

    def test_source_writer_commit_between_database_copies_refuses(self):
        f = self.fixture()
        original = product._copy_database
        before = private_anchor(f.slot)
        def copy(src, dst):
            original(src,dst)
            if src.name == 'career_rosters.sqlite3':
                with closing(sqlite3.connect(f.slot/'historical_matches.sqlite3')) as con:
                    con.execute('UPDATE career_years SET match_count=COALESCE(match_count,0)+1')
                    con.commit()
        with patch.object(product, '_copy_database', copy):
            with self.assertRaisesRegex(product.BackupRefused,'input_changed_during_export'):
                product.export_backup(**f.args())
        self.assertNotEqual(before, private_anchor(f.slot))  # injected writer only
        self.assertFalse((f.destination/'COMPLETE').exists())

    def test_candidate_tamper_immediately_before_completion_refuses(self):
        f = self.fixture()
        original = product._anchor
        calls = 0
        def anchor(root):
            nonlocal calls
            pin = original(root)
            if root == f.destination/'compatibility':
                calls += 1
                if calls == 1:
                    (f.destination/'payload'/'owned94'/'manual.json').write_bytes(b'late-tamper')
            return pin
        with patch.object(product, '_anchor', anchor):
            self.refused(f)

    def test_two_manual_exports_same_destination_only_one_succeeds(self):
        f = self.fixture()
        barrier = threading.Barrier(2)
        original = product._inspect
        def inspect(slot, *args):
            result = original(slot,*args)
            if slot == f.slot:
                barrier.wait(timeout=30)
            return result
        def export():
            try:
                return product.export_backup(**f.args())['candidate_consistent']
            except product.BackupRefused:
                return False
        with patch.object(product, '_inspect', inspect), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _:export(),range(2)))
        self.assertEqual([False,True], sorted(results))
        self.assertTrue(product.verify_candidate(candidate=f.destination)['candidate_consistent'])

    def test_verify_candidate_is_readonly_and_does_not_reference_originals(self):
        f = self.fixture()
        product.export_backup(**f.args())
        before = private_anchor(f.destination)
        shutil.rmtree(f.save_root)
        with patch.object(product, '_compatibility', side_effect=AssertionError('external read')):
            self.assertTrue(product.verify_candidate(candidate=f.destination)['read_only'])
        self.assertEqual(before, private_anchor(f.destination))

    def test_verify_refuses_missing_tampered_and_unknown_files(self):
        for name in ('COMPLETE', 'payload/owned94/manual.json', 'compatibility/data/master/schools.csv'):
            f = self.fixture()
            product.export_backup(**f.args())
            (f.destination/name).unlink()
            with self.assertRaises(product.BackupRefused):
                product.verify_candidate(candidate=f.destination)
        f = self.fixture()
        product.export_backup(**f.args())
        (f.destination/'unrecognized').write_bytes(b'fixture')
        with self.assertRaises(product.BackupRefused):
            product.verify_candidate(candidate=f.destination)

    def test_rolling_backup_checksum_refuses(self):
        f = self.fixture()
        p = next((f.slot/'backups').glob('*.json'))
        p.write_bytes(b'{"payload_checksum":"wrong"}')
        self.refused(f)

    def test_cli_diagnose_export_verify_and_sanitized_failure(self):
        f = self.fixture()
        args = ['--save-root',str(f.save_root),'--slot-id','owned94','--source','manual']
        prefix = [sys.executable,'-m','phase2_engine.manual_save_backup']
        proc = subprocess.run(prefix+['export']+args+['--destination',str(f.destination)],capture_output=True,text=True)
        self.assertEqual(2,proc.returncode)
        self.assertEqual('',proc.stderr)
        self.assertNotIn(str(f.root),proc.stdout)
        self.assertFalse(f.destination.exists())
        for command, options in [('diagnose',args+['--confirm-game-stopped']),
                                 ('export',args+['--confirm-game-stopped','--destination',str(f.destination)]),
                                 ('verify',['--candidate',str(f.destination)])]:
            proc = subprocess.run(prefix+[command]+options,capture_output=True,text=True)
            self.assertEqual(0,proc.returncode,proc.stdout+proc.stderr)
            self.assertNotIn(str(f.root),proc.stdout)
            self.assertFalse(json.loads(proc.stdout)['restoration_authorized'])

    def test_cli_has_no_restore_auto_or_latest_entrypoint(self):
        for command in ('restore','activate','auto'):
            proc = subprocess.run([sys.executable,'-m','phase2_engine.manual_save_backup',command],capture_output=True,text=True)
            self.assertEqual(2,proc.returncode)


if __name__ == '__main__':
    unittest.main()
