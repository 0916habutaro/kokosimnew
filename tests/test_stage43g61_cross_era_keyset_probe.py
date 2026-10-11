"""Stage43G-61: keyset year browsing and bounded read-only probe tests.

Extra years are synthetic HEADERS for paging only, not actually simulated
national tournaments, roster graduation years, or authorized v2 game plans.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import unittest

from phase2_engine.career_cross_era_year_catalog import (
    CareerCrossEraYearCatalog, LEGACY, FUTURE,
)
from phase2_engine.career_cross_era_year_probe import (
    probe_cross_era_year_catalog,
)
import test_stage43g31_cross_era_browse_model as stage31


class Stage43G61CrossEraKeysetTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage31.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setup_both()
        self.catalog = CareerCrossEraYearCatalog(self.fixture.root)

    def _hashes(self):
        return {
            f.name: sha256(f.read_bytes()).hexdigest()
            for f in Path(self.fixture.root).glob("*.sqlite3*")
            if f.is_file()
        }

    def _add_header_catalog(self):
        # Index-stress registration, never a simulated roster/game progression.
        with sqlite3.connect(self.fixture.v2) as db:
            db.executemany(
                "INSERT INTO v2_game_years("
                "year,calendar_sha256,status,match_count,ledger_sha256"
                ") VALUES (?,?,'sealed',0,?)",
                ((year, "header_only_unverified", "header_only_unverified")
                 for year in range(10001, 11251)),
            )

    def test_cursor_pages_match_existing_offset_pages_for_two_eras(self):
        before = self._hashes()
        first = self.catalog.page_after(limit=1)
        self.assertEqual([10000], [r["year"] for r in first["years"]])
        self.assertTrue(first["has_older"])
        self.assertEqual(10000, first["next_cursor_before_year"])
        self.assertEqual(FUTURE, first["years"][0]["source"])
        older = self.catalog.page_after(limit=1, before_year=10000)
        self.assertEqual([2026], [r["year"] for r in older["years"]])
        self.assertEqual(LEGACY, older["years"][0]["source"])
        self.assertFalse(older["has_older"])
        self.assertIsNone(older["next_cursor_before_year"])
        self.assertEqual([], self.catalog.page_after(
            before_year=2026,
        )["years"])
        self.assertEqual(
            self.catalog.page(limit=1)["years"], first["years"],
        )
        self.assertEqual(
            self.catalog.page(limit=1, offset=1)["years"], older["years"],
        )
        self.assertTrue(first["source_headers_only_not_record_verification"])
        self.assertEqual(before, self._hashes())

    def test_1250_header_stress_uses_seek_indexes_and_readonly_probe(self):
        self._add_header_catalog()
        before = self._hashes()
        encountered = []
        cursor = None
        pages = 0
        while True:
            page = self.catalog.page_after(
                before_year=cursor, limit=24,
            )
            encounter = [r["year"] for r in page["years"]]
            encountered.extend(encounter)
            pages += 1
            self.assertLessEqual(len(encounter), 24)
            if not page["has_older"]:
                break
            self.assertEqual(
                encounter[-1], page["next_cursor_before_year"],
            )
            cursor = page["next_cursor_before_year"]
        expected = list(range(11250, 9999, -1)) + [2026]
        self.assertEqual(expected, encountered)
        self.assertGreater(pages, 50)
        with sqlite3.connect(
            Path(self.fixture.v2).resolve().as_uri() + "?mode=ro",
            uri=True,
        ) as conn:
            query = [
                row[3] for row in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT year FROM v2_game_years "
                    "WHERE status='sealed' AND year<? "
                    "ORDER BY year DESC LIMIT ?",
                    (10500, 25),
                )
            ]
        self.assertTrue(any(
            "SEARCH v2_game_years" in row and
            "INTEGER PRIMARY KEY" in row for row in query
        ), query)
        diagnostic = probe_cross_era_year_catalog(
            self.fixture.root, max_pages=100, limit=24,
        )
        self.assertTrue(diagnostic["older_catalog_exhausted"])
        self.assertEqual(len(expected), diagnostic["sampled_unique_year_headers"])
        self.assertEqual(pages, diagnostic["sampled_pages"])
        self.assertEqual(24, diagnostic["limit"])
        self.assertLessEqual(
            max(m["year_count"] for m in diagnostic["measurements"]), 24,
        )
        self.assertTrue(diagnostic["read_only_sha256_unchanged"])
        self.assertFalse(diagnostic["verified_gameplay_years"])
        self.assertFalse(diagnostic["verified_source_payloads"])
        self.assertEqual(before, self._hashes())

    def test_cursor_rejects_invalid_identity_and_untrusted_types(self):
        for year, limit in (
            (True, 24), (False, 24), (0, 24), (-1, 24),
            ("2027", 24), (None, True), (None, 0), (None, 25),
        ):
            with self.subTest(before_year=year, limit=limit):
                with self.assertRaises(ValueError):
                    self.catalog.page_after(before_year=year, limit=limit)
        for limit, pages in ((0, 1), (25, 1), (24, 0), (24, 101),
                             (True, 10), (10, True)):
            with self.subTest(limit=limit, max_pages=pages):
                with self.assertRaises(ValueError):
                    probe_cross_era_year_catalog(
                        self.fixture.root, limit=limit, max_pages=pages,
                    )

    def test_keyset_header_does_not_bypass_sha_verification(self):
        before = self._hashes()
        page = self.catalog.page_after(limit=1)
        self.assertEqual(10000, page["years"][0]["year"])
        good = self.catalog.select_school(10000, self.fixture.a)
        self.assertTrue(good["source_payloads_rechecked"])
        self.assertEqual(before, self._hashes())
        with sqlite3.connect(self.fixture.v2) as db:
            db.execute(
                "UPDATE v2_option_a_matches SET record_sha256='BAD' "
                "WHERE year=10000",
            )
        bad_before = self._hashes()
        self.assertEqual(10000, self.catalog.page_after(
            limit=1,
        )["years"][0]["year"])
        with self.assertRaises(ValueError):
            self.catalog.select_school(10000, self.fixture.a)
        self.assertEqual(bad_before, self._hashes())

    def test_empty_slot_probe_never_creates_a_file(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            diagnostic = probe_cross_era_year_catalog(root)
            self.assertEqual(0, diagnostic["sampled_unique_year_headers"])
            self.assertEqual([], diagnostic["slot_files_checked"])
            self.assertEqual([], list(root.iterdir()))


if __name__ == "__main__":
    unittest.main()
