"""甲子園の実際の記録（historical_data/koshien_*.csv）の検証。"""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from historical_results.koshien import (
    APPEARANCE_COLUMNS, RECORD_COLUMNS, aggregate, validate,
)


class KoshienRecordsTests(unittest.TestCase):
    def test_repository_data_is_consistent(self):
        issues = validate()
        self.assertEqual([], [str(i) for i in issues])

    def test_aggregate_counts_wins_draws_and_best_result(self):
        rows = [
            dict(kind="summer", year="1950", school_id="S1", results="WWDWL", result="ベスト4"),
            dict(kind="summer", year="1960", school_id="S1", results="WWWWW", result="優勝"),
            dict(kind="summer", year="2020", school_id="S1", results="", result=""),
        ]
        total = aggregate(rows)[("S1", "summer")]
        self.assertEqual([1950, 1960, 2020], total["years"])
        self.assertEqual((8, 1, 1), (total["wins"], total["losses"], total["draws"]))
        self.assertEqual(("優勝", 1, 0), (total["best_result"], total["championships"], total["runner_ups"]))


class KoshienValidationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.schools = self.root / "schools.csv"
        self.schools.write_text("school_id,official_name\nSCH000001,架空高校\n", encoding="utf-8")
        (self.root / "sources.csv").write_text(
            "source_id,publisher,document_title,url,retrieved_at,verification_status\n"
            "HS9001,検証用,検証用資料,https://example.invalid/,2026-10-23,unverified\n",
            encoding="utf-8",
        )
        self.appearances = [
            dict(kind="summer", year="2001", school_id="SCH000001", team_name="架空高校",
                 results="WL", result="2回戦", source_id="HS9001"),
            dict(kind="summer", year="2005", school_id="SCH000001", team_name="架空高校",
                 results="L", result="1回戦", source_id="HS9001"),
        ]
        self.record = dict(
            school_id="SCH000001", kind="summer", as_of_edition="107", appearances="2",
            wins="1", losses="2", draws="0", championships="0", runner_ups="0",
            best_result="2回戦", last_appearance_year="2005", appearance_years="2001;2005",
            source_id="HS9001", verified_at="2026-10-23", notes="",
        )

    def codes(self):
        for name, columns, rows in (
            ("koshien_appearances.csv", APPEARANCE_COLUMNS, self.appearances),
            ("koshien_records.csv", RECORD_COLUMNS, [self.record]),
        ):
            with (self.root / name).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
        return {issue.code for issue in validate(self.root, self.schools)}

    def test_valid(self):
        self.assertEqual(set(), self.codes())

    def test_record_must_match_appearances(self):
        self.record["wins"] = "3"
        self.assertIn("MISMATCH", self.codes())

    def test_years_must_match_count(self):
        self.record["appearance_years"] = "2001"
        self.assertIn("YEARS_COUNT", self.codes())

    def test_empty_years_allowed(self):
        self.record["appearance_years"] = ""
        self.assertEqual(set(), self.codes())

    def test_unknown_school_and_source(self):
        self.appearances[0]["school_id"] = "SCH999999"
        self.appearances[1]["source_id"] = "HS0000"
        codes = self.codes()
        self.assertIn("UNKNOWN_SCHOOL", codes)
        self.assertIn("UNKNOWN_SOURCE", codes)

    def test_school_with_appearances_needs_record(self):
        self.appearances.append(dict(
            kind="spring", year="2003", school_id="SCH000001", team_name="架空高校",
            results="L", result="1回戦", source_id="HS9001"))
        self.assertIn("MISSING_RECORD", self.codes())

    def test_record_without_appearances_allowed(self):
        self.appearances = []
        self.record.update(best_result="初戦敗退", runner_ups="", appearance_years="")
        self.assertEqual(set(), self.codes())

    def test_first_game_loss_label_needs_record_only(self):
        self.record["best_result"] = "初戦敗退"
        self.assertIn("MISMATCH", self.codes())

    def test_as_of_edition(self):
        self.record["as_of_edition"] = "108"
        self.assertIn("AS_OF", self.codes())


if __name__ == "__main__":
    unittest.main()
