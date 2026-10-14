"""Five real historical exports; new read-only code has no replay dependencies."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from phase2_engine import manual_save_backup as product
from phase2_engine.legacy_backup_compatibility import CATALOG, CATALOG_VERSION
from phase2_engine.live_game_service import LiveGameService
from stage43g95_isolated_harness import anchor
import stage43g99_fixture_support as support

COMMITS = (
    ('94',support.OLD_MAIN),
    ('99','4ee0f9199b0c40811e3c33c10bc0ba2de3ed97f4'),
    ('100','bd83cec686239d826d7aaab85532680aea3eb13b'),
    ('101','e3fca8af56e851fec91e8748940624024e74d0a1'),
    ('102','8480dc079967e12365ccb145860ee2f34243402f'),
)


class Stage43G103CompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='stage103-five-old-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name).resolve()
        cls.candidates = {}
        for label, commit in COMMITS:
            root = cls.root/label
            root.mkdir()
            with patch.object(support,'OLD_MAIN',commit):
                cls.candidates[label] = support.old_candidate(root)
        cls.pins = {k:anchor(p) for k,p in cls.candidates.items()}

    def test_five_true_exports_readonly_content_verify_no_joint_replay_authority(self):
        for label, path in self.candidates.items():
            with self.subTest(version=label), patch.object(LiveGameService,'load_game',side_effect=AssertionError('no replay')):
                evidence = json.loads((path/'evidence.json').read_text(encoding='utf-8'))
                self.assertEqual(338,len(evidence['compatibility_files']))
                self.assertTrue(product.verify_candidate(candidate=path)['candidate_consistent'])
                diagnostic = product.diagnose_candidate_compatibility(candidate=path)
                self.assertFalse(diagnostic['candidate_code_executed'])
                self.assertFalse(diagnostic['evidence_authenticated'])
                if label != '102':
                    self.assertFalse(diagnostic['current_code_replay_allowed'])
                    self.assertEqual('catalog_mismatch_refused',diagnostic['replay_status'])
                else:
                    # Identical Stage102 runtime bytes; no new replay permission.
                    self.assertEqual(CATALOG_VERSION,evidence['catalog_version'])
                self.assertEqual(self.pins[label],anchor(path))

    def test_all_338_catalog_inputs_and_data_master106_unchanged_from_true102(self):
        path = self.candidates['102']
        evidence = json.loads((path/'evidence.json').read_text(encoding='utf-8'))
        self.assertEqual(set(CATALOG),set(evidence['compatibility_files']))
        self.assertEqual(product._compatibility(support.ROOT),evidence['compatibility_files'])
        old = self.root/'102'/'old-main'/'data'
        new = support.ROOT/'data'
        names = {p.relative_to(old) for p in old.rglob('*') if p.is_file()}
        self.assertEqual(names,{p.relative_to(new) for p in new.rglob('*') if p.is_file()})
        self.assertEqual(106,sum(p.suffix=='.csv' for p in names))
        self.assertTrue(all((old/p).read_bytes()==(new/p).read_bytes() for p in names))
        self.assertEqual(self.pins['102'],anchor(path))
