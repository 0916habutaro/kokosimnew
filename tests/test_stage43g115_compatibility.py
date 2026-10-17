"""True Stage114 export adds the seventeenth old-version RO gate."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from phase2_engine import manual_save_backup as product
from phase2_engine.legacy_backup_compatibility import CATALOG, CATALOG_VERSION
from phase2_engine.live_game_service import LiveGameService
from stage43g95_isolated_harness import anchor
import stage43g99_fixture_support as support

STAGE114_MAIN = '8cf1c4324730d2ec4e24aa41728fc626b16d014d'


class Stage43G115CompatibilityTests(unittest.TestCase):
    def test_true114_export_catalog338_master106_and_candidate_bytes_readonly(self):
        with tempfile.TemporaryDirectory(prefix='stage115-true114-') as temp:
            root = Path(temp)
            with patch.object(support, 'OLD_MAIN', STAGE114_MAIN):
                candidate = support.old_candidate(root)
            before = anchor(candidate)
            evidence = json.loads((candidate/'evidence.json').read_text(encoding='utf-8'))
            self.assertEqual(338, len(evidence['compatibility_files']))
            self.assertEqual(set(CATALOG), set(evidence['compatibility_files']))
            self.assertEqual(CATALOG_VERSION, evidence['catalog_version'])
            self.assertEqual(product._compatibility(support.ROOT), evidence['compatibility_files'])
            with patch.object(LiveGameService, 'load_game', side_effect=AssertionError('no replay')):
                self.assertTrue(product.verify_candidate(candidate=candidate)['candidate_consistent'])
                result = product.diagnose_candidate_compatibility(candidate=candidate)
                self.assertFalse(result['candidate_code_executed'])
                self.assertFalse(result['evidence_authenticated'])
            old, new = root/'old-main'/'data', support.ROOT/'data'
            names = {p.relative_to(old) for p in old.rglob('*') if p.is_file()}
            self.assertEqual(names, {p.relative_to(new) for p in new.rglob('*') if p.is_file()})
            self.assertEqual(106, sum(p.suffix == '.csv' for p in names))
            self.assertTrue(all((old/p).read_bytes() == (new/p).read_bytes() for p in names))
            self.assertEqual(before, anchor(candidate))
