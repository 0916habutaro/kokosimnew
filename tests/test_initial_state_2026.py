"""2026年度開始時に使う実在の前提データ（data/initial_state/2026/）の整合性。"""
from __future__ import annotations

import csv
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIOR = ROOT / "data" / "initial_state" / "2026" / "prior_results.csv"

COLUMNS = [
    "record_id", "kind", "rule_id", "source_year", "source_competition_name",
    "prefecture_code", "school_id", "published_team_name", "achievement",
    "source_id", "verified_at", "notes",
]
KINDS = {"senbatsu_entrant", "autumn_prefectural", "autumn_regional"}


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class InitialState2026Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with PRIOR.open(encoding="utf-8-sig", newline="") as handle:
            cls.header = next(csv.reader(handle))
        cls.rows = _read(PRIOR)
        cls.schools = {r["school_id"]: r for r in _read(ROOT / "data/master/schools.csv")}
        cls.sources = {r["source_id"] for r in _read(ROOT / "data/master/sources.csv")}
        cls.rules = {
            r["access_rule_id"]: r
            for r in _read(ROOT / "data/competitions/competition_access_rules.csv")
        }

    def test_columns(self):
        self.assertEqual(COLUMNS, self.header)

    def test_rows_reference_existing_master_data(self):
        ids = [r["record_id"] for r in self.rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in self.rows:
            with self.subTest(record=row["record_id"]):
                self.assertIn(row["kind"], KINDS)
                school = self.schools.get(row["school_id"])
                self.assertIsNotNone(school, row["school_id"])
                self.assertEqual(row["prefecture_code"], school["prefecture_code"])
                self.assertIn(row["source_id"], self.sources)
                self.assertTrue(row["published_team_name"])

    def test_prior_year_rules_have_previous_season_results(self):
        # 前年の結果を使うルール（source_year_offset=-1）すべてにデータがある
        needed = {
            rule_id for rule_id, rule in self.rules.items()
            if rule["source_year_offset"] == "-1"
            and rule["effective_from_year"] <= "2026"
        }
        present = {r["rule_id"] for r in self.rows if r["rule_id"]}
        self.assertEqual(needed, present)
        for row in self.rows:
            if row["rule_id"]:
                rule = self.rules[row["rule_id"]]
                self.assertEqual(rule["destination_prefecture_code"], row["prefecture_code"])
                self.assertEqual(rule["source_competition_type"], row["kind"])
                self.assertEqual("2025", row["source_year"])

    def test_fixed_top_n_rules_have_exactly_quota_schools(self):
        counts = Counter(r["rule_id"] for r in self.rows if r["rule_id"])
        for rule_id, count in counts.items():
            rule = self.rules[rule_id]
            if rule["quota_mode"] == "fixed_top_n":
                with self.subTest(rule=rule_id):
                    self.assertEqual(int(rule["quota"]), count)
        for rule_id in counts:
            schools = [r["school_id"] for r in self.rows if r["rule_id"] == rule_id]
            self.assertEqual(len(schools), len(set(schools)), rule_id)

    def test_senbatsu_entrants_cover_rules_that_use_them(self):
        entrants = [r for r in self.rows if r["kind"] == "senbatsu_entrant"]
        self.assertEqual(len(entrants), len({r["school_id"] for r in entrants}))
        prefectures = {r["prefecture_code"] for r in entrants}
        for rule in self.rules.values():
            if (rule["source_competition_id_2026"] == "CMP000001"
                    and rule["source_year_offset"] == "0"):
                with self.subTest(rule=rule["access_rule_id"]):
                    self.assertIn(rule["destination_prefecture_code"], prefectures)


if __name__ == "__main__":
    unittest.main()
