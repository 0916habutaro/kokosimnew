"""Owned fixture relocation, private-anchor distrust and deterministic faults."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import errno
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import shutil
import threading
import unittest
from unittest.mock import patch

import stage43g95_isolated_harness as lab
from phase2_engine import manual_save_backup as product


class Stage43G95IsolatedRestoreTests(unittest.TestCase):
    def experiment(self, phase='sealed', source='manual'):
        e = lab.Experiment(phase, source)
        self.addCleanup(e.close)
        return e

    def refused(self, e):
        source = lab.anchor(e.fixture.slot)
        candidate = lab.anchor(e.fixture.destination)
        with self.assertRaises(product.BackupRefused):
            e.relocate()
        self.assertEqual(source, lab.anchor(e.fixture.slot))
        self.assertEqual(candidate, lab.anchor(e.fixture.destination))
        if e.target.exists() and e.target.name == 'isolated':
            self.assertFalse((e.target/'COMPLETE').exists())

    def test_six_states_all_sql_sha_readonly_and_handle_release(self):
        for phase in ('active','sealed','registered'):
            for source in ('manual','autosave'):
                with self.subTest(phase=phase, source=source):
                    e = self.experiment(phase,source)
                    with patch('phase2_engine.live_game_service.LiveGameService.load_game',
                               side_effect=AssertionError('load forbidden')):
                        metric = e.relocate(measure=True)
                    self.assertGreater(metric['matches'],0)
                    self.assertEqual(e.pin, lab.anchor(e.target))
                    self.assertEqual(e.source_pin, lab.anchor(e.fixture.slot))
                    # Windows rename immediately after RO reads proves closure.
                    moved = e.fixture.root/'moved'
                    e.target.rename(moved)
                    e.trusted(moved)

    def test_missing_receipts_payload_and_compatibility(self):
        for name in ('COMPLETE','evidence.json','payload/owned94/manual.json',
                     'payload/owned94/career_rosters.sqlite3',
                     'compatibility/data/master/schools.csv'):
            e = self.experiment()
            (e.fixture.destination/name).unlink()
            self.refused(e)

    def test_json_rolling_and_compatibility_corruption(self):
        for name in ('payload/owned94/manual.json','payload/owned94/autosave.json',
                     'compatibility/data/master/schools.csv'):
            e = self.experiment()
            (e.fixture.destination/name).write_bytes(b'changed')
            self.refused(e)
        e = self.experiment()
        next((e.fixture.destination/'payload'/'owned94'/'backups').glob('*.json')).write_bytes(b'changed')
        self.refused(e)

    def test_raw_db_checksum_ledger_roster_identity_outcomes_schema(self):
        for db,sql in (
            ('historical_matches.sqlite3',"UPDATE historical_matches SET record_sha256='bad'"),
            ('historical_matches.sqlite3',"UPDATE career_years SET ledger_sha256='bad'"),
            ('historical_matches.sqlite3',"UPDATE historical_competition_outcomes SET record_sha256='bad'"),
            ('career_rosters.sqlite3',"UPDATE career_school_rosters SET payload_json='{}'"),
            ('career_rosters.sqlite3',"UPDATE career_player_identities SET identity_json='{}'"),
            ('historical_matches.sqlite3','CREATE TABLE unknown(id INTEGER)')):
            e = self.experiment()
            with closing(sqlite3.connect(e.fixture.destination/'payload'/'owned94'/db)) as con:
                con.execute(sql)
                con.commit()
            self.refused(e)

    def rewrite_evidence(self, e, **changes):
        root = e.fixture.destination
        evidence = json.loads((root/'evidence.json').read_text(encoding='utf-8'))
        evidence.update(changes)
        (root/'evidence.json').write_bytes(product._encoded(evidence))
        (root/'COMPLETE').write_text(product.VERSION+'\n'+product._sha((root/'evidence.json').read_bytes())+'\n',
                                   encoding='utf-8',newline='\n')

    def test_forged_consistent_evidence_cannot_replace_private_anchor(self):
        e = self.experiment()
        # Internally consistent candidate receipt accepted by product, but the
        # original private anchor still detects rewritten provenance evidence.
        self.rewrite_evidence(e, source_files={})
        self.assertTrue(product.verify_candidate(candidate=e.fixture.destination)['candidate_consistent'])
        self.refused(e)

    def test_unknown_metadata_generation_catalog_slot_and_traversal(self):
        for fields in ({'version':'unknown'},{'catalog_version':'other-code'},
                       {'slot_id':'other'},{'slot_id':'../owned94'},
                       {'source':'autosave'},{'runtime':{'unknown':True}}):
            e = self.experiment()
            self.rewrite_evidence(e,**fields)
            self.refused(e)

    def test_same_content_other_export_is_not_this_generation(self):
        e = self.experiment()
        other = e.fixture.root/'other-backup'
        product.export_backup(**e.fixture.args(destination=other,source='autosave'))
        with self.assertRaises(product.BackupRefused):
            e.trusted(other)

    def test_consistent_registered_history_truncation_private_anchor_refuses(self):
        e = lab.Experiment('registered', extended=True)
        self.addCleanup(e.close)
        e.relocate()
        self.assertEqual(3,len(e.views['years']))
        root = e.fixture.destination
        payload = root/'payload'/'owned94'
        # API-registered 2027 sealed empty year and 2028 active registration
        # are coherently removed; internally valid 2026 history remains.
        with closing(sqlite3.connect(payload/'historical_matches.sqlite3')) as con:
            con.execute('DELETE FROM career_years WHERE year>=2027')
            con.commit()
        self.rewrite_evidence(e,payload_files=lab.anchor(payload),
                              logical_digest=product._logical_digest(lab.facts(payload)))
        self.assertTrue(product.verify_candidate(candidate=root)['candidate_consistent'])
        # Content-only product verification cannot prove historical completeness.
        with self.assertRaisesRegex(product.BackupRefused,'untrusted_needs_manual_review'):
            e.trusted(root)

    def test_existing_empty_nonempty_and_second_execution(self):
        for nonempty in (False,True):
            e = self.experiment()
            e.target.mkdir()
            if nonempty:
                (e.target/'keep').write_bytes(b'keep')
            before = lab.anchor(e.target)
            self.refused(e)
            self.assertEqual(before,lab.anchor(e.target))
        e = self.experiment()
        e.relocate()
        before = lab.anchor(e.target)
        with self.assertRaisesRegex(product.BackupRefused,'destination_exists'):
            e.relocate()
        self.assertEqual(before,lab.anchor(e.target))

    def test_output_overlap_containment_traversal_external(self):
        e = self.experiment()
        for dst in (e.fixture.root, e.fixture.save_root, e.fixture.slot/'nested',
                    e.fixture.destination, e.fixture.destination/'nested',
                    e.fixture.root/'..'/'escape', Path('relative'),Path('/tmp/unowned-stage95')):
            e.target = dst
            self.refused(e)

    def test_transient_wal_shm_journal_and_early_complete(self):
        for name in ('historical_matches.sqlite3-wal','career_rosters.sqlite3-shm',
                     'historical_matches.sqlite3-journal','manual.json.tmp'):
            e = self.experiment()
            (e.fixture.destination/'payload'/'owned94'/name).write_bytes(b'writer')
            # scan rejects before a SHA can be taken; independent source pin
            # still proves that the harness did not touch the owned original.
            with self.assertRaises(product.BackupRefused):
                e.relocate()
            self.assertEqual(e.source_pin,lab.anchor(e.fixture.slot))
            self.assertFalse(e.target.exists())
        e = self.experiment()
        (e.fixture.destination/'payload'/'COMPLETE').write_bytes(b'early')
        self.refused(e)

    def test_hardlink_candidate_and_target_parent_alias(self):
        e = self.experiment()
        os.link(e.fixture.destination/'evidence.json',e.fixture.root/'hardlink')
        with self.assertRaises(product.BackupRefused):
            e.relocate()
        self.assertEqual(e.source_pin,lab.anchor(e.fixture.slot))
        self.assertFalse(e.target.exists())

    def test_symlink_or_windows_junction_never_followed(self):
        e = self.experiment()
        link = e.fixture.destination/'alias'
        if os.name == 'nt':
            proc = subprocess.run(['cmd','/c','mklink','/J',str(link),str(e.fixture.root)],capture_output=True)
            self.assertEqual(0,proc.returncode)
            self.addCleanup(lambda: os.rmdir(link) if link.exists() else None)
        else:
            link.symlink_to(e.fixture.root,target_is_directory=True)
        with self.assertRaisesRegex(product.BackupRefused,'linked_path'):
            e.relocate()
        self.assertEqual(e.source_pin,lab.anchor(e.fixture.slot))
        self.assertFalse(e.target.exists())

    def test_enospc_eio_interrupt_keep_partial_and_reject_rerun(self):
        for error in (OSError(errno.ENOSPC,'injected'),OSError(errno.EIO,'injected'),KeyboardInterrupt()):
            e = self.experiment()
            original = lab.copy_file
            calls = 0
            def faulty(src,dst):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise error
                original(src,dst)
            with patch.object(lab,'copy_file',faulty):
                self.refused(e)
            self.assertTrue(e.target.exists())
            self.refused(e)

    def test_actual_process_exit_midcopy_leaves_no_complete(self):
        script = '''
import json, os
import stage43g95_isolated_harness as lab
e = lab.Experiment('sealed')
print(json.dumps(dict(root=str(e.fixture.root),source=e.source_pin,candidate=e.pin)),flush=True)
original = lab.copy_file
count = 0
def killed(src,dst):
    global count
    count += 1
    if count == 3:
        os._exit(77)
    original(src,dst)
lab.copy_file = killed
e.relocate()
'''
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(Path(__file__).parent),str(Path(__file__).resolve().parents[1]))))
        proc = subprocess.run([sys.executable,'-c',script],env=env,capture_output=True,text=True)
        self.assertEqual(77,proc.returncode,proc.stderr)
        private = json.loads(proc.stdout)
        root = Path(private['root'])
        self.addCleanup(lambda: shutil.rmtree(root))
        self.assertFalse((root/'isolated'/'COMPLETE').exists())
        self.assertEqual(private['source'],lab.anchor(root/'saves'/'owned94'))
        self.assertEqual(private['candidate'],lab.anchor(root/'backup'))
        with self.assertRaises(product.BackupRefused):
            product.verify_candidate(candidate=root/'isolated')

    def test_injected_early_target_complete_is_never_accepted(self):
        e = self.experiment()
        original = lab.copy_file
        def early(src,dst):
            original(src,dst)
            if src.name != 'COMPLETE' and not (e.target/'COMPLETE').exists():
                (e.target/'COMPLETE').write_bytes(b'premature')
        with patch.object(lab,'copy_file',early):
            self.refused(e)

    def test_receipt_write_and_postcopy_tamper_revoke_completion(self):
        for receipt_fault in (True,False):
            e = self.experiment()
            original = lab.copy_file
            def faulty(src,dst):
                if src.name == 'COMPLETE' and receipt_fault:
                    raise OSError(errno.EIO,'receipt')
                original(src,dst)
                if src.name == 'COMPLETE':
                    (e.target/'payload'/'owned94'/'manual.json').write_bytes(b'late')
            with patch.object(lab,'copy_file',faulty):
                self.refused(e)

    def test_source_candidate_change_during_copy_detected_no_harness_writeback(self):
        e = self.experiment()
        original = lab.copy_file
        before = e.pin
        injected = False
        def writer(src,dst):
            nonlocal injected
            original(src,dst)
            if not injected:
                injected = True
                (e.fixture.destination/'evidence.json').write_bytes(b'injected writer')
        with patch.object(lab,'copy_file',writer):
            with self.assertRaises(product.BackupRefused):
                e.relocate()
        self.assertNotEqual(before,lab.anchor(e.fixture.destination)) # injector only
        self.assertEqual(e.source_pin,lab.anchor(e.fixture.slot))
        self.assertFalse((e.target/'COMPLETE').exists())

    def test_success_then_target_tamper_readonly_rejection(self):
        e = self.experiment()
        e.relocate()
        (e.target/'evidence.json').write_bytes(b'changed after completion')
        before = lab.anchor(e.target)
        with self.assertRaises(product.BackupRefused):
            e.trusted(e.target)
        self.assertEqual(before,lab.anchor(e.target))
        self.assertEqual(e.pin,lab.anchor(e.fixture.destination))

    def test_two_executions_one_exclusive_directory(self):
        e = self.experiment()
        barrier = threading.Barrier(2)
        original = e.trusted
        def trusted(root):
            result = original(root)
            if root == e.fixture.destination:
                barrier.wait(timeout=30)
            return result
        def run(_):
            try:
                e.relocate()
                return True
            except product.BackupRefused:
                return False
        with patch.object(e,'trusted',trusted),ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual([False,True],sorted(pool.map(run,range(2))))
        self.assertEqual(e.pin,lab.anchor(e.target))


if __name__ == '__main__':
    unittest.main()
