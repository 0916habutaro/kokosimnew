"""Self-generated TemporaryDirectory only; no product save inputs."""
from contextlib import closing
import errno
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.live_game_service import LiveGameService
from stage43g93_fixture_support import OwnedLab, Refused, facts, private_anchor, canonical, sha, ro


class Stage43G93ExportTests(unittest.TestCase):
    def lab(self, phase='active'):
        return self.enterContext(OwnedLab(phase))

    def refuses(self, lab, code, **kwargs):
        before = private_anchor(lab.slot)
        with self.assertRaisesRegex(Refused, '^' + code + '$'):
            lab.export('refused', source='manual', **kwargs)
        self.assertEqual(before, private_anchor(lab.slot))
        self.assertNotIn('refused', lab.completed)

    def test_active_real_live_manual_autosave_are_explicit_and_readonly(self):
        lab = self.lab()
        before = private_anchor(lab.slot)
        with patch.object(LiveGameService, 'load_game', side_effect=AssertionError('no replay writes')):
            for source in ('manual', 'autosave'):
                with self.subTest(source=source):
                    metric = lab.export(source, source=source)
                    self.assertGreater(metric['matches'], 0)
                    self.assertGreater(metric['complete_a_matches'], 0)
                    self.assertEqual(0, metric['sealed_years'])
                    self.assertTrue(lab.verify(source)['candidate_consistent'])
                    self.assertFalse(lab.verify(source)['restoration_authorized'])
                    self.assertEqual(lab.original_facts, facts(lab.candidate_path(source) / 'labslot'))
        self.assertEqual(before, private_anchor(lab.slot))

    def test_sealed_real_live_full_a_and_all_rolling_checkpoints_retained(self):
        lab = self.lab('sealed')
        before = private_anchor(lab.slot)
        metric = lab.export('sealed', source='manual')
        self.assertEqual(1, metric['sealed_years'])
        self.assertGreater(metric['matches'], 1)
        target = lab.candidate_path('sealed') / 'labslot'
        self.assertEqual(1, len(facts(target)['historical_matches.sqlite3'][1]['historical_competition_outcomes']))
        for n in before:
            if n not in ('historical_matches.sqlite3', 'career_rosters.sqlite3'):
                self.assertEqual((lab.slot / n).read_bytes(), (target / n).read_bytes())
        self.assertGreater(len(list((target / 'backups').glob('*.json'))), 0)
        self.assertTrue(lab.verify('sealed')['candidate_consistent'])

    def test_next_year_registration_preserves_sealed_past_without_claiming_rollover(self):
        lab = self.lab('registered')
        metric = lab.export('next', source='manual')
        target = lab.candidate_path('next') / 'labslot'
        with closing(ro(target / 'historical_matches.sqlite3')) as con:
            self.assertEqual([(2026, 'sealed'), (2027, 'active')],
                             con.execute('SELECT year,status FROM career_years ORDER BY year').fetchall())
        self.assertEqual(lab.original_facts, facts(target))
        self.assertFalse(metric['whole_game_restore_proven'])

    def test_derived_missing_or_present_is_unused_and_measured(self):
        lab = self.lab()
        extra = lab.slot / 'derived_player_stats.sqlite3'
        extra.write_bytes(b'not activated or parsed' * 4096)
        lab.input_pin = private_anchor(lab.slot)
        small = lab.export('originals', source='manual')
        large = lab.export('derived', source='manual', include_derived=True)
        self.assertEqual(extra.stat().st_size, large['copy_bytes'] - small['copy_bytes'])
        self.assertFalse((lab.candidate_path('originals') / 'labslot' / extra.name).exists())
        self.assertEqual(extra.read_bytes(), (lab.candidate_path('derived') / 'labslot' / extra.name).read_bytes())
        extra.unlink()
        self.assertTrue(lab.export('missing', source='manual')['fixture_only'])

    def test_selection_latest_and_backup_never_automatically_promoted(self):
        lab = self.lab()
        for selection in ('latest', 'manual_backup_001', None):
            with self.subTest(selection=selection), self.assertRaisesRegex(Refused, 'explicit_checkpoint_required'):
                lab.export('invalid', source=selection)
        self.assertFalse(lab.candidate_path('invalid').exists())

    def test_writer_flag_refuses_before_reads(self):
        lab = self.lab()
        lab.writers_stopped = False
        with patch('stage43g93_fixture_support.private_anchor', side_effect=AssertionError('read')):
            with self.assertRaisesRegex(Refused, 'writer_not_stopped'):
                lab.export('writer', source='manual')

    def test_wal_shm_journal_and_json_rotation_tmp_refuse(self):
        lab = self.lab()
        for name in ('historical_matches.sqlite3-wal', 'career_rosters.sqlite3-shm',
                     'historical_matches.sqlite3-journal', 'manual.json.tmp'):
            with self.subTest(artifact=name):
                p = lab.slot / name
                p.write_bytes(b'fixture transient')
                self.refuses(lab, 'non_quiescent_artifact')
                p.unlink()

    def test_unknown_files_and_original_table_refuse(self):
        lab = self.lab()
        p = lab.slot / 'unknown.sqlite3'
        p.write_bytes(b'unknown is never derived')
        self.refuses(lab, 'unknown_original')
        p.unlink()
        with closing(sqlite3.connect(lab.slot / 'historical_matches.sqlite3')) as con, con:
            con.execute('CREATE TABLE unknown_original(x)')
        lab.input_pin = private_anchor(lab.slot)
        self.refuses(lab, 'unknown_original_table')

    def test_required_original_loss_refuses_and_no_history_repair(self):
        lab = self.lab()
        for name in ('manual.json', 'historical_matches.sqlite3', 'career_rosters.sqlite3'):
            with self.subTest(original=name):
                path = lab.slot / name
                data = path.read_bytes()
                path.unlink()
                self.refuses(lab, 'private_original_pin_mismatch')
                path.write_bytes(data)

    def test_missing_master_settings_and_engine_version_refuse(self):
        lab = self.lab()
        for folder in ('data', 'config', 'phase2_engine', 'game_core'):
            with self.subTest(component=folder):
                p = next(p for p in (lab.compat / folder).rglob('*') if p.is_file())
                raw = p.read_bytes()
                p.unlink()
                self.refuses(lab, 'compatibility_missing_or_changed')
                p.write_bytes(raw + b'fixture incompatible version')
                self.refuses(lab, 'compatibility_missing_or_changed')
                p.write_bytes(raw)

    def test_cross_slot_and_generation_impersonation_refuse(self):
        lab = self.lab()
        other = self.lab('sealed')
        shutil.copyfile(other.slot / 'historical_matches.sqlite3', lab.slot / 'historical_matches.sqlite3')
        self.refuses(lab, 'private_original_pin_mismatch')
        # Even if a caller forges a SHA memo, original raw oracle is independent.
        lab.input_pin = private_anchor(lab.slot)
        self.refuses(lab, 'manual_judgment_required')

    def test_stale_json_archive_ahead_needs_manual_judgment_without_rollback(self):
        lab = self.lab('sealed')
        backup = next((lab.slot / 'backups').glob('manual.*.json'))
        shutil.copyfile(backup, lab.slot / 'manual.json')
        lab.input_pin = private_anchor(lab.slot)
        self.refuses(lab, 'manual_judgment_required')
        self.assertEqual(lab.original_facts, facts(lab.slot))

    def test_json_ahead_needs_manual_judgment_without_sync(self):
        lab = self.lab()
        with closing(sqlite3.connect(lab.slot / 'historical_matches.sqlite3')) as con, con:
            con.execute('DELETE FROM historical_matches WHERE rowid=(SELECT MAX(rowid) FROM historical_matches)')
        lab.input_pin = private_anchor(lab.slot)
        self.refuses(lab, 'manual_judgment_required')

    def test_sealed_ledger_and_roster_identity_modification_refuse(self):
        lab = self.lab('sealed')
        for database, sql in (
            ('historical_matches.sqlite3', "UPDATE career_years SET ledger_sha256='forged' WHERE status='sealed'"),
            ('career_rosters.sqlite3', "UPDATE career_player_identities SET identity_sha256='forged'")):
            with self.subTest(component=database):
                path = lab.slot / database
                raw = path.read_bytes()
                with closing(sqlite3.connect(path)) as con, con:
                    con.execute(sql)
                lab.input_pin = private_anchor(lab.slot)
                self.refuses(lab, 'inventory_contract_refused')
                path.write_bytes(raw)
                lab.input_pin = private_anchor(lab.slot)

    def test_forged_candidate_sha_memo_cannot_authorize_modified_rows(self):
        lab = self.lab()
        lab.export('tamper', source='manual')
        candidate = lab.candidate_path('tamper')
        with closing(sqlite3.connect(candidate / 'labslot' / 'historical_matches.sqlite3')) as con, con:
            con.execute('DELETE FROM historical_matches')
        (candidate / 'lab_evidence.json').write_text(json.dumps({'sha256': '0' * 64, 'approved': True}))
        with self.assertRaisesRegex(Refused, 'candidate_private_pin_mismatch'):
            lab.verify('tamper')
        # Even a forged in-memory byte pin cannot replace the independent rows.
        lab.completed['tamper'] = (private_anchor(candidate), lab.original_facts)
        with self.assertRaisesRegex(Refused, 'candidate_raw_mismatch'):
            lab.verify('tamper')

    def test_existing_output_and_rerun_refuse_without_touching_either(self):
        lab = self.lab()
        lab.export('existing', source='manual')
        before = private_anchor(lab.root)
        with self.assertRaisesRegex(Refused, 'output_exists'):
            lab.export('existing', source='autosave')
        self.assertEqual(before, private_anchor(lab.root))

    def test_traversal_absolute_and_source_alias_refuse(self):
        lab = self.lab()
        for name in ('../input', '.', 'a/b', str(lab.slot), '/tmp/out', 'a\\b'):
            with self.subTest(name_type='invalid'), self.assertRaisesRegex(Refused, 'invalid_candidate_name'):
                lab.export(name, source='manual')

    def test_links_and_hardlinks_refuse(self):
        lab = self.lab()
        hard = lab.slot / 'hard'
        os.link(lab.slot / 'manual.json', hard)
        self.refuses(lab, 'hardlinked_input')
        hard.unlink()
        # Windows hosted runners may not permit symlinks; junction is tested instead.
        link = lab.outputs / 'linked'
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(lab.slot)],
                           check=True, capture_output=True)
        else:
            link.symlink_to(lab.slot, target_is_directory=True)
        with self.assertRaisesRegex(Refused, 'linked_path'):
            lab.export('anything', source='manual')
        if os.name == 'nt':
            link.rmdir()
        else:
            link.unlink()

    def test_cross_filesystem_refused_before_copy(self):
        lab = self.lab()
        original_stat = Path.stat
        def stat(path, *args, **kwargs):
            info = original_stat(path, *args, **kwargs)
            if path == lab.outputs:
                fields = list(info)
                fields[2] += 1
                return os.stat_result(fields)
            return info
        with patch.object(Path, 'stat', stat):
            with self.assertRaisesRegex(Refused, 'cross_filesystem'):
                lab.export('cross', source='manual')

    def test_enospc_copy_error_and_interrupt_leave_untrusted_no_clobber(self):
        lab = self.lab()
        for i, error in enumerate((OSError(errno.ENOSPC, 'fixture disk full'),
                                   OSError(errno.EIO, 'fixture copy failure'), KeyboardInterrupt())):
            with self.subTest(fault=type(error).__name__):
                name = 'partial' + str(i)
                before = private_anchor(lab.slot)
                def fault(event, path):
                    if event == 'copied':
                        raise error
                expected = Refused if isinstance(error, OSError) else KeyboardInterrupt
                with self.assertRaises(expected):
                    lab.export(name, source='manual', boundary=fault)
                self.assertEqual(before, private_anchor(lab.slot))
                output_before = private_anchor(lab.candidate_path(name))
                with self.assertRaisesRegex(Refused, 'incomplete_or_untrusted_candidate'):
                    lab.verify(name)
                with self.assertRaisesRegex(Refused, 'output_exists'):
                    lab.export(name, source='manual')
                self.assertEqual(output_before, private_anchor(lab.candidate_path(name)))

    def test_mid_copy_file_collision_is_not_overwritten(self):
        lab = self.lab()
        def collision(event, path):
            if event == 'created':
                (path / 'labslot' / 'autosave.json').write_bytes(b'collision sentinel')
        self.refuses(lab, 'copy_io_failure', boundary=collision)
        self.assertEqual(b'collision sentinel', (lab.candidate_path('refused') / 'labslot' / 'autosave.json').read_bytes())

    def test_source_mutation_during_copy_is_detected(self):
        lab = self.lab()
        def change(event, path):
            if event == 'copied_compatibility':
                (lab.slot / 'manual.json').write_bytes(b'fixture changed by nonparticipating writer')
        with self.assertRaisesRegex(Refused, 'input_changed_during_export'):
            lab.export('changed', source='manual', boundary=change)
        self.assertNotIn('changed', lab.completed)

    def test_unverified_career_dependencies_refuse_even_valid_checksum(self):
        lab = self.lab()
        folder = lab.slot / 'career_multi_previews'
        folder.mkdir()
        body = dict(schema_version='career_multi_preview_sandbox_v1', slot_id='labslot', year=2027)
        body['payload_checksum'] = sha(canonical(body))
        (folder / '2027.json').write_text(json.dumps(body), encoding='utf-8')
        lab.input_pin = private_anchor(lab.slot)
        self.refuses(lab, 'manual_judgment_required')

    def test_actual_career_preview_participation_plan_and_roster_dependency_is_manual(self):
        from game_core.players import PlayerRosterGenerator
        from phase2_engine.career_roster_archive import CareerRosterArchive
        from phase2_engine.career_multi_preview_checkpoint import CareerMultiPreviewCheckpointService
        from stage43g91_fixture_support import closed_archive_connection
        from stage43g93_fixture_support import ROOT, SEED, Stage43G92LegacyReplayTests
        lab = self.lab('sealed')
        repo = Stage43G92LegacyReplayTests.repo
        groups = {cid: sorted(s for s in repo.school_to_program if repo.schools[s]['prefecture_code'] == pref)[:8]
                  for cid, pref in (('CMP000086', '09'), ('CMP000088', '10'))}
        rosters = CareerRosterArchive(lab.slot / 'career_rosters.sqlite3')
        with patch.object(CareerRosterArchive, '_connect', closed_archive_connection):
            for sid in [s for group in groups.values() for s in group]:
                rosters.save_initial_roster(PlayerRosterGenerator().generate_for_school_id(repo, sid, 2026, SEED))
                rosters.advance_and_save(repo.team(sid), next_year=2027, career_seed=SEED)
        multi = CareerMultiPreviewCheckpointService(repo, ROOT / 'data', save_root=lab.slot.parent,
            ability_config_dir=ROOT / 'config' / 'abilities', match_config_dir=ROOT / 'config' / 'match')
        multi.start('labslot', year=2027, competitions=[dict(competition_id=cid,
            entry_mode='kanto_direct_main_v1', entrant_school_ids=schools, group_entrant_school_ids={})
            for cid, schools in groups.items()],
            base_seed=SEED, career_seed=SEED)
        lab.input_pin = private_anchor(lab.slot)
        lab.original_facts = facts(lab.slot)
        self.assertTrue((lab.slot / 'career_multi_previews' / '2027.json').is_file())
        self.refuses(lab, 'manual_judgment_required')

    def test_changed_seed_and_plan_even_with_new_checksum_refuse(self):
        lab = self.lab()
        path = lab.slot / 'manual.json'
        original = path.read_bytes()
        for field, value in (('rng_seed', 999), ('plan_fingerprint', 'forged-new-generation')):
            with self.subTest(field=field):
                body = json.loads(original)
                body.pop('payload_checksum')
                body[field] = value
                body['payload_checksum'] = sha(canonical(body))
                path.write_text(json.dumps(body), encoding='utf-8')
                lab.input_pin = private_anchor(lab.slot)
                self.refuses(lab, 'inventory_contract_refused')
        path.write_bytes(original)

    def test_sqlite_backup_source_readonly_and_backup_io_failure(self):
        lab = self.lab()
        with closing(ro(lab.slot / 'historical_matches.sqlite3')) as con:
            self.assertEqual(1, con.execute('PRAGMA query_only').fetchone()[0])
            with self.assertRaises(sqlite3.OperationalError):
                con.execute('DELETE FROM historical_matches')
        class BackupFault(sqlite3.Connection):
            def backup(self, *args, **kwargs):
                self.assert_readonly = self.execute('PRAGMA query_only').fetchone()[0]
                if self.assert_readonly != 1:
                    raise AssertionError('source is writable')
                raise OSError(errno.ENOSPC, 'fixture backup disk full')
        def fault_ro(path):
            con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True,
                                  factory=BackupFault)
            con.execute('PRAGMA query_only=ON')
            return con
        with patch('stage43g93_fixture_support.ro', fault_ro):
            self.refuses(lab, 'copy_io_failure')
        # Failure did not leave a source connection/lock alive.
        with closing(sqlite3.connect(lab.slot / 'historical_matches.sqlite3', timeout=0)) as con:
            con.execute('BEGIN EXCLUSIVE')
            con.rollback()

    def test_modification_at_final_boundary_never_becomes_a_trusted_pin(self):
        lab = self.lab()
        def tamper(event, path):
            if event == 'verified':
                (path / 'labslot' / 'manual.json').write_bytes(b'late fixture tampering')
        self.refuses(lab, 'candidate_json_mismatch', boundary=tamper)

    def test_handles_closed_and_output_can_move_after_verification(self):
        lab = self.lab()
        lab.export('handles', source='manual')
        self.assertTrue(lab.verify('handles')['candidate_consistent'])
        source = lab.candidate_path('handles')
        source.rename(lab.candidate_path('moved'))
        lab.candidate_path('moved').rename(source)
        self.assertTrue(lab.verify('handles')['candidate_consistent'])
        # Zero-timeout exclusive writer succeeds after all read-only operations.
        with closing(sqlite3.connect(lab.slot / 'historical_matches.sqlite3', timeout=0)) as con:
            con.execute('BEGIN EXCLUSIVE')
            con.rollback()

    def test_cli_has_no_user_save_input_option(self):
        proc = subprocess.run([sys.executable, '-m', 'phase2_engine.legacy_quiescent_export_audit',
                               '--save-root', 'unused'], capture_output=True, text=True)
        self.assertEqual(2, proc.returncode)
        self.assertIn('unrecognized arguments', proc.stderr)


if __name__ == '__main__':
    unittest.main()
