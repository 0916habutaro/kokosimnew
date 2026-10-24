"""甲子園の実際の記録（historical_data/koshien_*.csv）の検証。"""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from historical_results.koshien import (
    APPEARANCE_COLUMNS, RECORD_COLUMNS, SPECIAL_RESULT_COLUMNS,
    HISTORICAL_SCHOOL_COLUMNS, HISTORICAL_TEAM_COLUMNS, HISTORICAL_ATTRIBUTION_COLUMNS,
    aggregate, summarize_adjudications, summarize_historical_attributions, validate,
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
        self.special_results = []
        self.historical_schools = [
            dict(historical_school_id="HSC1", historical_name="架空第一部",
                 source_id="HS9001", notes=""),
            dict(historical_school_id="HSC2", historical_name="架空商工部",
                 source_id="HS9001", notes=""),
        ]
        self.historical_teams = []
        self.attributions = []
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
            ("koshien_special_results.csv", SPECIAL_RESULT_COLUMNS, self.special_results),
            ("koshien_historical_schools.csv", HISTORICAL_SCHOOL_COLUMNS, self.historical_schools),
            ("koshien_historical_teams.csv", HISTORICAL_TEAM_COLUMNS, self.historical_teams),
            ("koshien_team_attributions.csv", HISTORICAL_ATTRIBUTION_COLUMNS, self.attributions),
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


    @staticmethod
    def walkover(**changes):
        row = dict(
            event_id="EV1", kind="summer", year="2001", edition="83",
            round_label="2回戦",
            winner_school_id="SCH000001", winner_team_name="架空高校",
            loser_school_id="", loser_team_name="架空相手校",
            result_type="walkover", played="false",
            win_counted="1", loss_counted="unknown", source_id="HS9001",
        )
        row.update(changes)
        return row

    def test_forfeit_row_keeps_original_results_unchanged(self):
        self.special_results = [self.walkover()]
        self.assertEqual(set(), self.codes())
        played = aggregate(self.appearances)[("SCH000001", "summer")]
        awarded = summarize_adjudications(self.special_results)[("SCH000001", "summer")]
        self.assertEqual((1, 2), (played["wins"], played["losses"]))
        self.assertEqual(1, awarded["awarded_wins"])
        self.assertEqual(0, awarded["pending_wins"])

    def test_unknown_is_pending_not_zero_and_unknown_schools_are_not_guessed(self):
        self.special_results = [self.walkover(win_counted="unknown", loss_counted="1")]
        counts = summarize_adjudications(self.special_results)
        self.assertEqual(0, counts[("SCH000001", "summer")]["awarded_wins"])
        self.assertEqual(1, counts[("SCH000001", "summer")]["pending_wins"])
        self.assertEqual(1, len(counts))  # 対戦校のIDは不明

    def test_special_data_rejects_bad_fields_and_duplicate_events(self):
        self.special_results = [
            self.walkover(played="true", win_counted="maybe", source_id="HS_UNKNOWN"),
            self.walkover(loser_school_id="SCH_UNKNOWN", loser_team_name=""),
        ]
        codes = self.codes()
        self.assertTrue({
            "PLAYED", "COUNTED", "UNKNOWN_SOURCE", "UNKNOWN_SCHOOL",
            "EMPTY_TEAM_NAME", "DUPLICATE_OR_EMPTY_ID",
        } <= codes)

    def test_special_schema_and_required_file(self):
        self.assertEqual(set(), self.codes())
        (self.root / "koshien_special_results.csv").unlink()
        self.assertIn("READ_ERROR", {i.code for i in validate(self.root, self.schools)})
        (self.root / "koshien_special_results.csv").write_text("wrong,header\n", encoding="utf-8")
        self.assertIn("SCHEMA", {i.code for i in validate(self.root, self.schools)})


    @staticmethod
    def historical_team(appearance_id, name, **changes):
        row = dict(
            appearance_id=appearance_id, historical_school_id="HSC1",
            kind="spring", year="1947",
            edition="19", team_name=name, representative_region="架空地区",
            source_id="HS9001",
        )
        row.update(changes)
        return row

    @staticmethod
    def historical_attribution(appearance_id, decision, **changes):
        row = dict(appearance_id=appearance_id, school_id="SCH000001",
                   counts_in_school_total=decision, source_id="HS9001")
        row.update(changes)
        return row

    def test_two_historical_teams_one_year_one_current_school(self):
        self.historical_teams = [
            self.historical_team("HA1", "架空第一部"),
            self.historical_team("HA2", "架空商工部", historical_school_id="HSC2"),
        ]
        self.attributions = [
            self.historical_attribution("HA1", "1"),
            self.historical_attribution("HA2", "0"),
        ]
        self.assertEqual(set(), self.codes())
        actual, school = summarize_historical_attributions(
            self.historical_teams, self.attributions)
        self.assertEqual(2, actual[("spring", "1947")])
        self.assertEqual({"counted": 1, "excluded": 1, "pending": 0},
                         school[("SCH000001", "spring")])
        # 古い年度別W/L/Dと学校別通算はこの段階で変えない
        self.assertEqual(1, aggregate(self.appearances)[("SCH000001", "summer")]["wins"])

    def test_historical_school_id_survives_rename_across_years(self):
        self.historical_teams = [
            self.historical_team("HA1", "架空旧校名"),
            self.historical_team("HA2", "架空新校名", year="1948", edition="20"),
        ]
        self.attributions = [
            self.historical_attribution("HA1", "1"),
            self.historical_attribution("HA2", "1"),
        ]
        self.assertEqual(set(), self.codes())
        self.assertEqual("HSC1", self.historical_teams[0]["historical_school_id"])
        self.assertEqual("HSC1", self.historical_teams[1]["historical_school_id"])
        actual, school = summarize_historical_attributions(
            self.historical_teams, self.attributions)
        self.assertEqual(1, actual[("spring", "1947")])
        self.assertEqual(1, actual[("spring", "1948")])
        self.assertEqual(2, school[("SCH000001", "spring")]["counted"])

    def test_historical_school_registry_rejects_missing_or_invalid_reference(self):
        self.historical_teams = [
            self.historical_team("HA1", "架空未確認校", historical_school_id="HSC_UNKNOWN"),
        ]
        self.assertIn("UNKNOWN_HISTORICAL_SCHOOL", self.codes())
        self.historical_schools.append(dict(self.historical_schools[0]))
        self.assertIn("DUPLICATE_OR_EMPTY_ID", self.codes())
        self.historical_schools[0]["historical_name"] = ""
        self.assertIn("EMPTY_NAME", self.codes())

    def test_historical_school_registry_required_and_schema(self):
        self.assertEqual(set(), self.codes())
        (self.root / "koshien_historical_schools.csv").unlink()
        self.assertIn("READ_ERROR", {i.code for i in validate(self.root, self.schools)})
        (self.root / "koshien_historical_schools.csv").write_text(
            "wrong,header\n", encoding="utf-8")
        self.assertIn("SCHEMA", {i.code for i in validate(self.root, self.schools)})

    def test_same_appearance_multiple_school_histories_is_one_actual(self):
        self.schools.write_text(
            "school_id,official_name\n"
            "SCH000001,架空高校\nSCH000002,架空二高校\n", encoding="utf-8")
        self.historical_teams = [self.historical_team("HA3", "架空共通前身")]
        self.attributions = [
            self.historical_attribution("HA3", "1"),
            self.historical_attribution("HA3", "1", school_id="SCH000002"),
        ]
        self.assertEqual(set(), self.codes())
        actual, school = summarize_historical_attributions(
            self.historical_teams, self.attributions)
        self.assertEqual(1, actual[("spring", "1947")])
        self.assertEqual(1, school[("SCH000001", "spring")]["counted"])
        self.assertEqual(1, school[("SCH000002", "spring")]["counted"])

    def test_undetermined_count_is_not_zero(self):
        self.historical_teams = [self.historical_team("HA4", "架空前身部")]
        self.attributions = [self.historical_attribution("HA4", "unknown")]
        self.assertEqual(set(), self.codes())
        _, school = summarize_historical_attributions(
            self.historical_teams, self.attributions)
        self.assertEqual(1, school[("SCH000001", "spring")]["pending"])
        self.assertEqual(0, school[("SCH000001", "spring")]["counted"])

    def test_historical_missing_reference_duplicates_and_bad_values(self):
        self.historical_teams = [
            self.historical_team("HA1", "架空第一部", source_id="HS_NO"),
            self.historical_team("HA1", "架空第二部", edition="abc"),
        ]
        self.attributions = [
            self.historical_attribution("HA_MISSING", "yes"),
            self.historical_attribution("HA_MISSING", "yes"),
        ]
        codes = self.codes()
        self.assertTrue({
            "DUPLICATE_OR_EMPTY_ID", "UNKNOWN_SOURCE", "EDITION",
            "UNKNOWN_APPEARANCE", "COUNTED", "DUPLICATE_LINK",
        } <= codes)

    def test_historical_required_csvs_and_schema(self):
        self.assertEqual(set(), self.codes())
        (self.root / "koshien_historical_teams.csv").unlink()
        self.assertIn("READ_ERROR", {i.code for i in validate(self.root, self.schools)})
        (self.root / "koshien_historical_teams.csv").write_text(
            "wrong,header\n", encoding="utf-8")
        self.assertIn("SCHEMA", {i.code for i in validate(self.root, self.schools)})


if __name__ == "__main__":
    unittest.main()
