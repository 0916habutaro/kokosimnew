"""学校マスターの設置者区分（ownership_type）。"""
from __future__ import annotations

import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    "prefectural", "municipal", "public_university_corporation",
    "private", "national", "unknown",
}


class SchoolOwnershipTests(unittest.TestCase):
    def test_ownership_types_are_known_values(self):
        with (ROOT / "data/master/schools.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            with self.subTest(school=row["school_id"]):
                self.assertIn(row["ownership_type"], ALLOWED)

    def test_public_university_corporation_counts_as_public(self):
        from phase2_engine.senbatsu_selection import load_selection_config

        PUBLIC_OWNERSHIP_TYPES = set(
            load_selection_config(ROOT / "config")["century"][
                "public_ownership_types"
            ]
        )
        self.assertIn("public_university_corporation", PUBLIC_OWNERSHIP_TYPES)
        self.assertNotIn("private", PUBLIC_OWNERSHIP_TYPES)
        self.assertNotIn("national", PUBLIC_OWNERSHIP_TYPES)


if __name__ == "__main__":
    unittest.main()
