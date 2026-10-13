"""Pre-change candidate bytes and post-change environment are separate facts."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from phase2_engine import manual_save_backup as product
from phase2_engine.legacy_backup_compatibility import (
    CATALOG, CATALOG_VERSION, LEGACY_CATALOG_VERSION, LEGACY_CATALOG_DIGEST,
)
from phase2_engine.live_game_service import LiveGameService
from stage43g94_fixture_support import Fixture, owned_sqlite_handles
from stage43g95_isolated_harness import anchor
from stage43g99_fixture_support import ROOT, old_candidate


class Stage43G99CompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='stage99-private-old-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name).resolve()
        cls.old = old_candidate(cls.root)
        cls.old_pin = anchor(cls.old)

    def test_true_old_export_survives_product_change_but_replay_refused(self):
        evidence = json.loads((self.old/'evidence.json').read_text(encoding='utf-8'))
        self.assertEqual(LEGACY_CATALOG_VERSION, evidence['catalog_version'])
        self.assertEqual(338, len(evidence['compatibility_files']))
        self.assertEqual(LEGACY_CATALOG_DIGEST, product._sha(product._encoded(evidence['compatibility_files'])))
        current = product._compatibility(ROOT)
        old_data = self.root/'old-main'/'data'
        current_data = ROOT/'data'
        old_names = {p.relative_to(old_data) for p in old_data.rglob('*') if p.is_file()}
        current_names = {p.relative_to(current_data) for p in current_data.rglob('*') if p.is_file()}
        self.assertTrue(old_names == current_names, 'data file set changed')
        self.assertEqual(106,sum(p.suffix=='.csv' for p in old_names))
        self.assertTrue(all((old_data/p).read_bytes()==(current_data/p).read_bytes() for p in old_names),
                        'master/data bytes changed')
        changed = {n for n in CATALOG if current[n] != evidence['compatibility_files'][n]}
        self.assertEqual({
            'phase2_engine/career_roster_archive.py',
            'phase2_engine/career_competition_outcomes.py',
            'phase2_engine/career_history_browse_model.py',
            'phase2_engine/career_longitudinal_read.py',
            'phase2_engine/career_player_records.py',
            # Stage100 preserves the original five lifetime changes and binds
            # its two replay dependencies under a separate reviewed version.
            'phase2_engine/live_game_service.py',
            'game_core/tournament_bridge.py',
        }, changed)
        with patch.object(LiveGameService, 'load_game', side_effect=AssertionError('writer')):
            verified = product.verify_candidate(candidate=self.old)
            result = product.diagnose_candidate_compatibility(candidate=self.old)
        self.assertTrue(verified['candidate_consistent'])
        self.assertTrue(result['candidate_content_verified'])
        self.assertFalse(result['installed_catalog_match'])
        self.assertEqual('catalog_mismatch_refused', result['replay_status'])
        self.assertFalse(result['current_code_replay_allowed'])
        self.assertFalse(result['candidate_code_executed'])
        self.assertFalse(result['evidence_authenticated'])
        self.assertEqual(self.old_pin, anchor(self.old))

    def test_current_export_match_still_does_not_authorize_replay(self):
        with owned_sqlite_handles():
            f = Fixture('sealed')
        self.addCleanup(f.close)
        before = anchor(f.slot)
        product.export_backup(**f.args())
        self.assertEqual(CATALOG_VERSION, json.loads((f.destination/'evidence.json').read_text())['catalog_version'])
        candidate_before = anchor(f.destination)
        result = product.diagnose_candidate_compatibility(candidate=f.destination)
        self.assertTrue(result['installed_catalog_match'])
        self.assertEqual('separate_replay_review_required', result['replay_status'])
        self.assertFalse(result['current_code_replay_allowed'])
        self.assertFalse(result['generation_provenance_verified'])
        self.assertFalse(result['restoration_authorized'])
        self.assertEqual(before, anchor(f.slot))
        self.assertEqual(candidate_before, anchor(f.destination))
        # Existing destination is retained even if a real native DB is open.
        with product.closing(product.ro(f.slot/'historical_matches.sqlite3')):
            with self.assertRaisesRegex(product.BackupRefused, '^destination_exists$'):
                product.export_backup(**f.args())
        self.assertEqual(candidate_before, anchor(f.destination))

    def test_installed_unknown_does_not_discard_valid_old_content(self):
        with patch.object(product, '_compatibility', side_effect=product.BackupRefused(
                'compatibility_missing_or_unknown_version')):
            self.assertTrue(product.verify_candidate(candidate=self.old)['candidate_consistent'])
            r = product.diagnose_candidate_compatibility(candidate=self.old)
        self.assertTrue(r['candidate_content_verified'])
        self.assertEqual('installed_catalog_unrecognized', r['replay_status'])
        self.assertFalse(r['current_code_replay_allowed'])
        self.assertEqual(self.old_pin, anchor(self.old))

    def test_unknown_version_relabel_receipt_and_tampering_refused(self):
        for case in ('unknown', 'relabel', 'compatibility', 'payload', 'receipt', 'missing'):
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix='stage99-tamper-') as temp:
                target = Path(temp)/'candidate'
                shutil.copytree(self.old, target)
                if case in ('unknown', 'relabel'):
                    path = target/'evidence.json'
                    evidence = json.loads(path.read_text())
                    evidence['catalog_version'] = 'unknown' if case == 'unknown' else CATALOG_VERSION
                    path.write_bytes(product._encoded(evidence))
                    (target/'COMPLETE').write_text(product.VERSION+'\n'+product._sha(path.read_bytes())+'\n', newline='\n')
                elif case == 'missing':
                    (target/'compatibility'/CATALOG[0]).unlink()
                else:
                    path = {'compatibility':target/'compatibility'/CATALOG[0],
                            'payload':target/'payload'/'owned94'/'manual.json',
                            'receipt':target/'COMPLETE'}[case]
                    path.write_bytes(path.read_bytes()+b'changed')
                before = anchor(target)
                with self.assertRaises(product.BackupRefused):
                    product.diagnose_candidate_compatibility(candidate=target)
                self.assertEqual(before, anchor(target))

    def test_candidate_race_during_diagnostic_refused(self):
        with tempfile.TemporaryDirectory(prefix='stage99-race-') as temp:
            target = Path(temp)/'candidate'
            shutil.copytree(self.old, target)
            original = product._compatibility
            def changed(root):
                result = original(root)
                (target/'COMPLETE').write_bytes(b'late-change')
                return result
            with patch.object(product, '_compatibility', changed):
                with self.assertRaisesRegex(product.BackupRefused, '^candidate_changed_during_verification$'):
                    product.diagnose_candidate_compatibility(candidate=target)


if __name__ == '__main__':
    unittest.main()
