from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from historical_results.validate import COLUMNS, validate


class HistoricalResultsContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "historical"
        self.data.mkdir()
        self.schools = self.root / "schools.csv"
        self.competitions = self.root / "competitions.csv"
        self.schools.write_text("school_id,official_name\nSCH000001,架空一\nSCH000002,架空二\n", encoding="utf-8")
        self.competitions.write_text("competition_id,competition_name\nCMP000001,試験大会\n", encoding="utf-8")
        self.rows = {
            "sources": [dict(source_id="HS001", publisher="検証用発行者", document_title="検証用資料",
                             url="https://example.invalid/test", retrieved_at="2026-10-20",
                             verification_status="unverified")],
            "tournaments": [dict(tournament_id="HT001", season_year="2026", season="summer",
                                 competition_name="架空大会", level="prefectural", prefecture_code="19",
                                 competition_id="CMP000001", completion_status="completed", source_id="HS001")],
            "teams": [dict(team_id="H1", tournament_id="HT001", display_name="架空一", team_type="single"),
                      dict(team_id="H2", tournament_id="HT001", display_name="架空二", team_type="single")],
            "team_members": [dict(team_id="H1", school_id="SCH000001", observed_name="架空一",
                                  mapping_status="verified", source_id="HS001"),
                             dict(team_id="H2", school_id="SCH000002", observed_name="架空二",
                                  mapping_status="verified", source_id="HS001")],
            "matches": [dict(match_id="HM001", tournament_id="HT001", game_date="2026-07-10",
                             round_label="1回戦", home_team_id="H1", away_team_id="H2",
                             home_score="3", away_score="2", result_status="final", source_id="HS001")],
        }

    def write(self):
        for table, columns in COLUMNS.items():
            with (self.data / f"{table}.csv").open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                writer.writerows(self.rows[table])

    def check(self):
        self.write()
        return validate(self.data, self.schools, self.competitions)

    def codes(self):
        return {issue.code for issue in self.check().issues}

    def test_valid_and_read_only(self):
        self.write()
        before = {p.name: p.read_bytes() for p in self.data.iterdir()}
        report = validate(self.data, self.schools, self.competitions)
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.counts["matches"], 1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.data.iterdir()})

    def test_header_only_is_valid_without_claiming_real_results(self):
        self.rows = {name: [] for name in COLUMNS}
        self.assertTrue(self.check().ok)

    def test_bad_scores_and_duplicate_match_id(self):
        self.rows["matches"][0]["home_score"] = "-1"
        self.rows["matches"].append(dict(self.rows["matches"][0]))
        self.assertTrue({"FINAL_SCORE", "DUPLICATE_ID"} <= self.codes())

    def test_cross_tournament_and_unknown_school_fail_closed(self):
        self.rows["teams"][0]["tournament_id"] = "HT_OTHER"
        self.rows["team_members"][1]["school_id"] = "SCH_UNKNOWN"
        self.assertTrue({"UNKNOWN_TOURNAMENT", "CROSS_TOURNAMENT_TEAM", "UNKNOWN_SCHOOL"} <= self.codes())

    def test_joint_team_and_unresolved_member(self):
        self.rows["teams"][0]["team_type"] = "joint"
        self.rows["team_members"].append(dict(team_id="H1", school_id="", observed_name="未照合校",
                                               mapping_status="unresolved", source_id="HS001"))
        self.assertTrue(self.check().ok)
        self.rows["team_members"][-1]["school_id"] = "SCH000002"
        self.assertIn("UNRESOLVED_WITH_ID", self.codes())

    def test_nonfinal_score_and_broken_source(self):
        self.rows["matches"][0]["result_status"] = "unplayed"
        self.rows["sources"][0]["url"] = "http://example.invalid"
        self.assertTrue({"NONFINAL_SCORE", "SOURCE_URL"} <= self.codes())

    def test_malformed_url_is_reported_not_crash(self):
        self.rows["sources"][0]["url"] = "https://[invalid"
        self.assertIn("SOURCE_URL", self.codes())

    def test_missing_file_fails_closed(self):
        self.write()
        (self.data / "matches.csv").unlink()
        report = validate(self.data, self.schools, self.competitions)
        self.assertFalse(report.ok)
        self.assertIn("READ_ERROR", {issue.code for issue in report.issues})

    def test_prefecture_code_is_two_digit_zero_padded(self):
        for code in ("02", "19", "47"):
            self.rows["tournaments"][0]["prefecture_code"] = code
            self.assertNotIn("PREFECTURE", self.codes(), code)
        for code in ("2", "0", "00", "48", "019", ""):
            self.rows["tournaments"][0]["prefecture_code"] = code
            self.assertIn("PREFECTURE", self.codes(), code)

    def test_repository_csvs_live_outside_data_directory(self):
        # data/ 以下はstage43g99〜の互換性テストでファイル一覧が固定されている
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "data" / "historical_results").exists())
        report = validate(root / "historical_data")
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(set(report.counts), set(COLUMNS))

    def test_wrong_header_fails_closed(self):
        self.write()
        (self.data / "matches.csv").write_text("wrong,header\n", encoding="utf-8")
        self.assertIn("SCHEMA", {issue.code for issue in
                                validate(self.data, self.schools, self.competitions).issues})


if __name__ == "__main__":
    unittest.main()
