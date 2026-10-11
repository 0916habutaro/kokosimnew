"""Stage43G-76: sealed fictional-v2 school match search, source separation."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import unittest

from phase2_engine.career_calendar_v2 import explicit_sandbox_plan
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_v2_school_game_page import (
    CareerV2SchoolPageConflict, read_v2_school_game_page,
)
import test_stage43g27_v2_option_a_archive as stage27

ALT = "CMP000087"


class Stage43G76V2SchoolPageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage27.Stage43G27V2OptionASidecarTests(
            "test_10000_full_a_match_sealed_and_readonly_paged"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.v2 = self.fixture.sidecar
        self.root = self.fixture.root
        self.v2_path = self.fixture.v2_file
        self.calendar_path = self.fixture.calendar_file
        self.legacy_path = self.fixture.legacy_file

    def populate(self, *, seal_second=True):
        # First year is 10000 (logical leap year), with three complete A games.
        for mid, day in (
            ("A-ONE", "02-29"), ("A-TWO", "04-01"), ("A-THREE", "04-02")
        ):
            self.v2.append(10000, stage27.full_a(10000, mid, day))
        self.v2.seal_year(10000, expected_match_count=3)
        self.fixture.calendar.record(explicit_sandbox_plan(
            10001, {stage27.COMP: ["04-01"], ALT: ["04-02"]},
            approved_for_fictional_game=True,
        ))
        self.v2.append(10001, stage27.full_a(10001, "B-ONE", "04-01"))
        other = stage27.full_a(10001, "B-ALT", "04-02")
        other["competition_id"] = ALT
        self.v2.append(10001, other)
        if seal_second:
            self.v2.seal_year(10001, expected_match_count=2)

    def _get(self, **kwargs):
        defaults = dict(
            start_year=10000, end_year=10001,
            school_id=stage27.FIRST,
        )
        defaults.update(kwargs)
        school_id = defaults.pop("school_id")
        return self.v2.school_game_page(school_id, **defaults)

    def test_v2_multi_year_competition_page_and_logical_date(self):
        self.populate()
        before = (file_sha256(self.v2_path), file_sha256(self.calendar_path))
        first = self._get(limit=2)
        self.assertEqual(5, first["total"])
        self.assertEqual(["G10000:02-29", "G10000:04-01"], [
            row["game_day_token"] for row in first["records"]
        ])
        self.assertEqual(
            stage27.SECOND,
            first["records"][0]["opponent_school_id"],
        )
        self.assertTrue(all(r["logical_game_date_not_iso"]
                            and r["stored_source"] == stage27.SOURCE
                            for r in first["records"]))
        self.assertEqual([10000, 10001], first["verified_saved_years"])
        self.assertFalse(first["all_selected_year_payloads_verified"])
        self.assertTrue(first["school_filter_uses_unindexed_json_scan"])
        page2 = self._get(limit=2, offset=2)
        page3 = self._get(limit=2, offset=4)
        self.assertEqual(2, len(page2["records"]))
        self.assertEqual(1, len(page3["records"]))
        self.assertEqual(5, len(
            first["records"] + page2["records"] + page3["records"]
        ))
        filtered = self._get(competition_id=ALT)
        self.assertEqual(1, filtered["total"])
        self.assertEqual("B-ALT", filtered["records"][0]["match_id"])
        self.assertEqual(5, self._get(school_id=stage27.SECOND)["total"])
        self.assertEqual(
            "loss", self._get(school_id=stage27.SECOND)
            ["records"][0]["result_for_school"],
        )
        self.assertEqual(
            before, (file_sha256(self.v2_path), file_sha256(self.calendar_path))
        )
        self.assertFalse(self.legacy_path.exists())

    def test_page_scope_does_not_verify_offpage_payload_strict_does(self):
        self.populate()
        with sqlite3.connect(self.v2_path) as con:
            con.execute(
                "UPDATE v2_option_a_matches SET payload_json='{}' "
                "WHERE year=10001 AND match_id='B-ONE'"
            )
        hashes = (file_sha256(self.v2_path), file_sha256(self.calendar_path))
        shallow = self._get(limit=2)
        self.assertEqual(5, shallow["total"])
        self.assertFalse(shallow["all_selected_year_payloads_verified"])
        with self.assertRaisesRegex(ValueError, "checksum"):
            self._get(limit=2, verify_scope="selected_years")
        self.assertEqual(
            hashes, (file_sha256(self.v2_path), file_sha256(self.calendar_path))
        )

    def test_year_scope_proves_membership_and_rejects_other_competition_tamper(self):
        self.populate()
        page = self._get(
            competition_id=ALT, verify_scope="selected_years",
        )
        self.assertEqual(1, page["total"])
        self.assertTrue(page["school_membership_integrity_for_years_verified"])
        with sqlite3.connect(self.v2_path) as con:
            con.execute(
                "UPDATE v2_option_a_matches SET payload_json='{}' "
                "WHERE year=10000 AND match_id='A-ONE'"
            )
        # Even a different competition/other-school record is verified in
        # strict mode since JSON school membership has no independent column.
        with self.assertRaises(ValueError):
            self._get(
                competition_id=ALT, verify_scope="selected_years",
            )
        # But a page-scoped filter is not claimed to prove unrelated records.
        self.assertEqual(1, self._get(competition_id=ALT)["total"])

    def test_seal_ledger_and_calendar_tamper_fail_closed(self):
        self.populate()
        with sqlite3.connect(self.v2_path) as con:
            con.execute(
                "DELETE FROM v2_option_a_matches WHERE match_id='A-ONE'"
            )
        with self.assertRaisesRegex(ValueError, "ledger"):
            self._get(limit=1)

    def test_calendar_sha_and_unsealed_year_rejected(self):
        self.populate()
        with sqlite3.connect(self.calendar_path) as con:
            con.execute(
                "UPDATE sandbox_year_plans SET content_sha256='WRONG' "
                "WHERE game_year=10000"
            )
        with self.assertRaises(ValueError):
            self._get()
        self.assertFalse(self.legacy_path.exists())

    def test_unsealed_year_rejected_even_when_other_year_has_matches(self):
        self.populate(seal_second=False)
        with self.assertRaisesRegex(ValueError, "not sealed"):
            self._get()

    def test_missing_archive_and_sparse_years_do_not_create_records(self):
        missing = self.root / "missing.sqlite3"
        empty = read_v2_school_game_page(
            missing, self.calendar_path, stage27.FIRST,
            start_year=10000, end_year=10001,
        )
        self.assertEqual(0, empty["total"])
        self.assertFalse(missing.exists())
        self.populate()
        one = self._get(start_year=10002, end_year=10003)
        self.assertEqual([], one["verified_saved_years"])
        self.assertEqual(0, one["total"])
        self.assertTrue(one["unsaved_years_not_inferred"])

    def test_invalid_years_and_bounds(self):
        for args in (
            {"start_year": 9999}, {"end_year": 9999},
            {"start_year": 10000, "end_year": 10100},
            {"start_year": True}, {"end_year": True},
            {"competition_id": ""}, {"competition_id": 1},
            {"limit": 0}, {"limit": True}, {"limit": 201},
            {"offset": -1}, {"offset": False},
            {"verify_scope": "filtered_window"},
        ):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    self._get(**args)


if __name__ == "__main__":
    unittest.main()
