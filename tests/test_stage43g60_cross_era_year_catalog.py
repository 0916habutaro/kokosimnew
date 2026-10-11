"""Stage43G-60: real legacy/v2 Option-A archives remain source separated.

Year10000 is an opt-in synthetic sandbox calendar: NO gameplay rollover
from the 2026 roster is implied. Uses existing Stage43G-31 sealed fixtures.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import unittest

from phase2_engine.career_cross_era_year_catalog import (
    CareerCrossEraYearCatalog, CareerCrossEraYearCatalogConflict,
    FUTURE, LEGACY,
)
from phase2_engine.career_cross_era_gui_pilot import (
    CareerCrossEraScreenController,
)
from phase2_engine.career_cross_era_navigation import (
    CareerCrossEraNavigator,
)
import test_stage43g31_cross_era_browse_model as stage31


class Stage43G60CrossEraYearCatalogTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage31.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setup_both()
        self.catalog = CareerCrossEraYearCatalog(self.fixture.root)

    def _snap(self):
        return {
            p.name: sha256(p.read_bytes()).hexdigest()
            for p in Path(self.fixture.root).glob("*.sqlite3*")
            if p.is_file()
        }

    def test_legacy_and_v2_headers_are_distinct_and_paged_without_writes(self):
        before = self._snap()
        index = self.catalog.page()
        self.assertEqual("cross_era_year_catalog", index["screen"])
        self.assertEqual([10000, 2026], [
            row["year"] for row in index["years"]
        ])
        self.assertEqual([FUTURE, LEGACY], [
            row["source"] for row in index["years"]
        ])
        self.assertEqual(["G{year}:MM-DD", "YYYY-MM-DD"], [
            row["date_kind"] for row in index["years"]
        ])
        self.assertFalse(index["has_older"])
        self.assertTrue(index["source_headers_only_not_record_verification"])
        self.assertTrue(all(
            not row["source_verified"] for row in index["years"]
        ))
        self.assertEqual([10000], [
            row["year"] for row in self.catalog.page(limit=1)["years"]
        ])
        self.assertEqual([2026], [
            row["year"] for row in
            self.catalog.page(limit=1, offset=1)["years"]
        ])
        self.assertEqual([], self.catalog.page(
            limit=1, offset=2,
        )["years"])
        self.assertTrue(self.catalog.page(limit=1)["has_older"])
        self.assertEqual(before, self._snap())

    def test_explicit_year_routes_separate_dates_and_reverifies_each_source(self):
        before = self._snap()
        a = self.fixture.a
        for year, expected_source, expected_date in (
            (2026, LEGACY, "YYYY-MM-DD"),
            (10000, FUTURE, "G{year}:MM-DD"),
        ):
            with self.subTest(year=year):
                page = self.catalog.select_school(year, a)
                self.assertEqual(year, page["selected_year"])
                self.assertEqual(expected_source, page["source"])
                self.assertEqual(expected_date, page["date_kind"])
                self.assertEqual(1, page["match_total"])
                self.assertTrue(page["source_payloads_rechecked"])
                self.assertTrue(page["selected_from_bounded_year_catalog"])
                self.assertFalse(page["combined_career_stats_authorized"])
                self.assertFalse(page["combined_date_index_authorized"])
                self.assertFalse(page["official_future_results"])
                detail = self.catalog.navigator.follow(
                    page["match_detail_targets"][0]["target"],
                )
                self.assertEqual(year, detail["selected_year"])
                self.assertEqual(expected_source, detail["source"])
                self.assertFalse(detail["combined_career_stats_authorized"])
        self.assertEqual(before, self._snap())

    def test_existing_gui_controller_accepts_selected_catalog_years(self):
        index = self.catalog.page()
        selection = sorted(row["year"] for row in index["years"])
        before = self._snap()
        ctl = CareerCrossEraScreenController(
            CareerCrossEraNavigator(self.fixture.root),
            selection, self.fixture.a, selected_year=2026,
        )
        self.assertEqual(LEGACY, ctl.page["source"])
        future = ctl.change_year(10000)
        self.assertEqual(FUTURE, future["source"])
        self.assertEqual("G{year}:MM-DD", future["date_kind"])
        self.assertEqual(2026, ctl.back()["selected_year"])
        self.assertEqual(before, self._snap())

    def test_corrupt_v2_payload_is_listed_not_presented_as_verified_result(self):
        with sqlite3.connect(self.fixture.v2) as conn:
            conn.execute(
                "UPDATE v2_option_a_matches SET record_sha256='BAD' "
                "WHERE year=10000"
            )
        after_corruption = self._snap()
        # The header catalog explicitly does NOT promise payload validation.
        self.assertEqual(
            [10000, 2026],
            [x["year"] for x in self.catalog.page()["years"]],
        )
        with self.assertRaises(ValueError):
            self.catalog.select_school(10000, self.fixture.a)
        self.assertEqual(after_corruption, self._snap())

    def test_invalid_page_and_unsaved_or_active_year_rejected(self):
        before = self._snap()
        for limit, offset in ((0, 0), (25, 0), (True, 0),
                              (1, -1), (1, True)):
            with self.subTest(limit=limit, offset=offset):
                with self.assertRaises(ValueError):
                    self.catalog.page(limit=limit, offset=offset)
        for year in (2027, 9999, 10001, True):
            with self.subTest(year=year):
                with self.assertRaises(ValueError):
                    self.catalog.select_school(year, self.fixture.a)
        self.assertEqual(before, self._snap())

    def test_missing_sources_catalog_must_not_create_sqlite(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            unused = Path(folder)
            blank = CareerCrossEraYearCatalog(unused)
            self.assertEqual([], blank.page()["years"])
            self.assertEqual([], list(unused.iterdir()))


if __name__ == "__main__":
    unittest.main()
