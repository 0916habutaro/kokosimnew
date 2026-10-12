"""Stage43G-79: separate school index for sealed synthetic v2 full-A source."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import unittest

from phase2_engine.career_calendar_v2 import explicit_sandbox_plan
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_v2_school_read_index import (
    CareerV2ReadIndexConflict, build_v2_school_read_index,
    read_indexed_v2_school_page,
)
import test_stage43g27_v2_option_a_archive as stage27

SECOND_COMP = "CMP000087"


class Stage43G79IndependentSchoolIndexTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage27.Stage43G27V2OptionASidecarTests(
            "test_10000_full_a_match_sealed_and_readonly_paged"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root
        self.v2 = self.fixture.sidecar
        self.source = self.fixture.v2_file
        self.calendar = self.fixture.calendar_file
        self.index = self.root / "fictional_v2_school_read_index.sqlite3"

    def populate(self):
        self.v2.append(10000, stage27.full_a(10000, "AA", "02-29"))
        self.v2.append(10000, stage27.full_a(10000, "AB", "04-01"))
        self.v2.seal_year(10000, expected_match_count=2)
        self.fixture.calendar.record(explicit_sandbox_plan(
            10001, {
                stage27.COMP: ["04-01", "04-02"],
                SECOND_COMP: ["04-02"],
            },
            approved_for_fictional_game=True,
        ))
        for name in ("BA", "BB"):
            self.v2.append(10001, stage27.full_a(10001, name, "04-01"))
        alternate = stage27.full_a(10001, "BC", "04-02")
        alternate["competition_id"] = SECOND_COMP
        alternate["ability_detail"]["competition_id"] = SECOND_COMP
        self.v2.append(10001, alternate)
        self.v2.seal_year(10001, expected_match_count=3)

    def build(self):
        return build_v2_school_read_index(
            self.source, self.calendar, self.index,
            start_year=10000, end_year=10001,
        )

    def page(self, **overrides):
        args = {
            "start_year": 10000, "end_year": 10001,
            "school_id": stage27.FIRST,
        }
        args.update(overrides)
        school_id = args.pop("school_id")
        return read_indexed_v2_school_page(
            self.source, self.calendar, self.index, school_id, **args,
        )

    def test_atomic_build_unchanged_source_and_exact_old_api_page_match(self):
        self.populate()
        before = (file_sha256(self.source), file_sha256(self.calendar))
        result = self.build()
        self.assertEqual([10000, 10001], result["indexed_saved_years"])
        self.assertEqual(5, result["indexed_source_matches"])
        self.assertTrue(result["derived_index_is_not_authoritative"])
        self.assertEqual(before, (
            file_sha256(self.source), file_sha256(self.calendar)
        ))
        baseline = self.v2.school_game_page(
            stage27.FIRST, start_year=10000, end_year=10001,
        )
        indexed = self.page()
        self.assertEqual(baseline["total"], indexed["total"])
        self.assertEqual(baseline["records"], indexed["records"])
        self.assertTrue(indexed["uses_separate_verified_school_index"])
        self.assertFalse(indexed["school_filter_uses_unindexed_json_scan"])
        self.assertFalse(indexed["legacy_records_combined"])
        self.assertFalse(self.fixture.legacy_file.exists())
        with sqlite3.connect(self.index) as con:
            plan = " ".join(str(r[3]) for r in con.execute(
                "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM school_game "
                "WHERE school_id=? AND year BETWEEN ? AND ?",
                (stage27.FIRST, 10000, 10001),
            ))
        self.assertIn("INDEX", plan)
        self.assertIn("school_id=?", plan)
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(before, (
            file_sha256(self.source), file_sha256(self.calendar)
        ))

    def test_competition_page_and_strict_all_sources(self):
        self.populate()
        self.build()
        strict = self.page(verify_scope="selected_years")
        self.assertEqual(5, strict["total"])
        self.assertTrue(strict["school_membership_integrity_for_years_verified"])
        self.assertTrue(strict["offpage_derived_memberships_verified"])
        filtered = self.page(competition_id=SECOND_COMP)
        self.assertEqual(1, filtered["total"])
        self.assertEqual("BC", filtered["records"][0]["match_id"])
        self.assertEqual(0, self.page(school_id="SCH999999")["total"])

    def test_source_tamper_ledger_and_calendar_are_fail_closed(self):
        self.populate()
        self.build()
        with sqlite3.connect(self.source) as con:
            con.execute(
                "UPDATE v2_option_a_matches SET record_sha256='BAD' "
                "WHERE match_id='AA'"
            )
        with self.assertRaisesRegex(ValueError, "ledger"):
            self.page()

    def test_hidden_json_payload_change_page_limited_strict_rejects(self):
        self.populate()
        self.build()
        with sqlite3.connect(self.source) as con:
            con.execute(
                "UPDATE v2_option_a_matches SET payload_json='{}' "
                "WHERE match_id='BC'"
            )
        # Baseline page has the same limitation: off-page payload changes
        # which leave stored SHA/ledger unchanged need strict verification.
        shallow = self.page(limit=1)
        self.assertEqual(5, shallow["total"])
        self.assertFalse(shallow["offpage_derived_memberships_verified"])
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.page(limit=1, verify_scope="selected_years")

    def test_stale_index_rejects_unexpected_new_sealed_year(self):
        self.populate()
        self.build()
        self.fixture.calendar.record(explicit_sandbox_plan(
            10002, {stage27.COMP: ["04-01"]},
            approved_for_fictional_game=True,
        ))
        self.v2.append(10002, stage27.full_a(10002, "CA", "04-01"))
        self.v2.seal_year(10002, expected_match_count=1)
        with self.assertRaisesRegex(ValueError, "different saved source or year"):
            self.page(end_year=10002)

    def test_cache_membership_tamper_rejected_strict_and_visible(self):
        self.populate()
        self.build()
        with sqlite3.connect(self.index) as con:
            con.execute(
                "UPDATE school_game SET school_id='SCH999999' "
                "WHERE school_id=? AND match_id='AB'",
                (stage27.FIRST,),
            )
        # A missing offpage row is not guaranteed detectable in page mode.
        shallow = self.page(limit=1)
        self.assertEqual(4, shallow["total"])
        with self.assertRaisesRegex(ValueError, "memberships differ"):
            self.page(verify_scope="selected_years")
        with self.assertRaises(ValueError):
            self.page(school_id="SCH999999")

    def test_fail_on_unsealed_source_or_overwriting_existing_index(self):
        self.v2.append(10000, stage27.full_a(10000, "AA"))
        with self.assertRaisesRegex(ValueError, "unsealed"):
            self.build()
        self.assertFalse(self.index.exists())
        with self.assertRaises(ValueError):
            build_v2_school_read_index(
                self.source, self.calendar, self.source,
                start_year=10000, end_year=10000,
            )
        self.assertFalse(self.fixture.legacy_file.exists())

    def test_bad_input_and_missing_cache_are_not_automatically_repaired(self):
        self.populate()
        with self.assertRaises(FileNotFoundError):
            self.page()
        self.assertFalse(self.index.exists())
        self.build()
        with self.assertRaises(ValueError):
            self.page(start_year=9999)
        with self.assertRaises(ValueError):
            self.page(start_year=10000, end_year=10100)
        with self.assertRaises(ValueError):
            self.page(verify_scope="filtered_window")
        with self.assertRaises(ValueError):
            self.page(limit=True)
        with self.assertRaises(ValueError):
            self.page(competition_id="")
        self.assertTrue(self.index.exists())


if __name__ == "__main__":
    unittest.main()
