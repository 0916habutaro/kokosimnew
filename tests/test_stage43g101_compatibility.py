"""True Stage94/99/100 content verification without current replay authority."""
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

STAGE100_MAIN = "bd83cec686239d826d7aaab85532680aea3eb13b"
STAGE99_MAIN = "4ee0f9199b0c40811e3c33c10bc0ba2de3ed97f4"


class Stage43G101CompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="stage101-three-old-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name).resolve()
        cls.candidates = {}
        for label, commit in (("94", support.OLD_MAIN), ("99", STAGE99_MAIN), ("100", STAGE100_MAIN)):
            root = cls.root / label
            root.mkdir()
            with patch.object(support, "OLD_MAIN", commit):
                cls.candidates[label] = support.old_candidate(root)
        cls.pins = {label: anchor(path) for label, path in cls.candidates.items()}

    def test_three_true_old_candidates_verify_readonly_and_replay_remains_refused(self):
        for label, path in self.candidates.items():
            with self.subTest(version=label):
                evidence = json.loads((path / "evidence.json").read_text(encoding="utf-8"))
                self.assertNotEqual(CATALOG_VERSION, evidence["catalog_version"])
                self.assertEqual(338, len(evidence["compatibility_files"]))
                with patch.object(LiveGameService, "load_game", side_effect=AssertionError("no writer/replay")):
                    self.assertTrue(product.verify_candidate(candidate=path)["candidate_consistent"])
                    diagnostic = product.diagnose_candidate_compatibility(candidate=path)
                self.assertEqual("catalog_mismatch_refused", diagnostic["replay_status"])
                self.assertFalse(diagnostic["current_code_replay_allowed"])
                self.assertFalse(diagnostic["candidate_code_executed"])
                self.assertFalse(diagnostic["evidence_authenticated"])
                self.assertEqual(self.pins[label], anchor(path))

    def test_fixed_338_inputs_only_one_source_changes_and_master106_bytes_unchanged(self):
        path = self.candidates["100"]
        evidence = json.loads((path / "evidence.json").read_text(encoding="utf-8"))
        current = product._compatibility(support.ROOT)
        self.assertEqual(set(evidence["compatibility_files"]), set(CATALOG))
        self.assertEqual({"phase2_engine/live_game_service.py"},
            {name for name in CATALOG if current[name] != evidence["compatibility_files"][name]})
        old = self.root / "100" / "old-main" / "data"
        names = {p.relative_to(old) for p in old.rglob("*") if p.is_file()}
        new = support.ROOT / "data"
        self.assertEqual(names, {p.relative_to(new) for p in new.rglob("*") if p.is_file()})
        self.assertEqual(106, sum(p.suffix == ".csv" for p in names))
        self.assertTrue(all((old / p).read_bytes() == (new / p).read_bytes() for p in names))
        self.assertEqual(self.pins["100"], anchor(path))


if __name__ == "__main__":
    unittest.main()
