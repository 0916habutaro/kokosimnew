"""調査CSVの軽量検証（UTF-8・列数・行数・重複・削除）。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ci_research_csv as csvcheck

BASE = "1" * 40
HEAD = "2" * 40


class ResearchCSVTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def csv_file(self, content: bytes | str, name: str = "other.csv") -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return path

    def test_valid_utf8_bom_and_quoted_newline(self):
        file = self.csv_file("\ufeffkey,note\n1,\"日本語\n2行\"\n2,正常\n")
        self.assertEqual(2, csvcheck.validate_csv(file))

    def test_invalid_structure_and_encoding(self):
        examples = (
            b"key,note\n\xff,hello\n",        # not UTF-8
            "key,note\n1\n",                # short row
            "key,note\n1,ok,extra\n",       # long row
            'key,note\n1,"broken\n',       # invalid quoting
            "key,key\n1,ok\n",             # duplicate header
            "key,\n1,ok\n",                # empty header column
            "key,note\n",                 # no data rows
            "key,note\n1,ok\n1,ok\n",     # duplicate row
            "key,note\n,\n",              # empty data row
            b"key,note\n1,\x00bad\n",    # binary data
        )
        for value in examples:
            with self.subTest(value=value):
                with self.assertRaises(csvcheck.CSVValidationError):
                    csvcheck.validate_csv(self.csv_file(value))

    def test_specific_document_keys_are_unique(self):
        path = self.csv_file(
            "年度,季節,都道府県,確認結果\n2026,秋季,千葉,確認済\n2026,秋季,千葉,未確認\n",
            "prefectural_seed_rules_2026.csv",
        )
        with self.assertRaisesRegex(csvcheck.CSVValidationError, "duplicate document key"):
            csvcheck.validate_csv(path)

    def test_known_2026_coverage_counts(self):
        target = "docs/research/2026_autumn_spring_seeding/prefectural_seed_rules_2026.csv"
        records = "年度,季節,都道府県\n" + "".join(
            f"2026,秋季,県{i}\n" for i in range(94))
        path = self.csv_file(records, "prefectural_seed_rules_2026.csv")
        self.assertEqual(94, csvcheck.validate_csv(path, target))
        with self.assertRaisesRegex(csvcheck.CSVValidationError, "expected 94"):
            csvcheck.validate_csv(self.csv_file(records.rsplit("\n", 2)[0] + "\n", path.name), target)

    def test_main_only_checks_changed_existing_csv(self):
        changed = "docs/research/example.csv"
        deleted = "docs/research/old.csv"
        file = self.csv_file("id,value\n1,ok\n", changed)
        self.assertTrue(file.exists())
        with (patch.object(csvcheck, "ROOT", self.root),
              patch.object(csvcheck, "changed_paths", return_value=[changed, deleted, "docs/README.md"]),
              patch.object(csvcheck, "head_research_paths", return_value={changed}),
              patch.dict("os.environ", {"CI_BASE_SHA": BASE, "CI_HEAD_SHA": HEAD})):
            self.assertEqual(0, csvcheck.main())
            file.write_text("id,value\n1,ok\n1,ok\n", encoding="utf-8")
            self.assertEqual(1, csvcheck.main())

    def test_unknown_git_diff_fails_closed(self):
        with (patch.object(csvcheck, "changed_paths", return_value=None),
              patch.dict("os.environ", {"CI_BASE_SHA": BASE, "CI_HEAD_SHA": HEAD})):
            self.assertEqual(1, csvcheck.main())


if __name__ == "__main__":
    unittest.main()
