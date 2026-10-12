"""Stage43G-81: strict status of separate fictional v2 school indexes.

Every fixture is sealed synthetic full Option-A data. No live game years,
official tournament facts or legacy school results are synthesized.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import unittest

from phase2_engine.career_calendar_v2 import explicit_sandbox_plan
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_v2_school_index_health import (
    audit_v2_school_index_health, prepare_versioned_v2_school_index,
)
from phase2_engine.career_v2_school_read_index import (
    read_indexed_v2_school_page,
)
import test_stage43g79_v2_school_read_index as stage79


class Stage43G81SchoolIndexLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage79.Stage43G79IndependentSchoolIndexTests(
            "test_atomic_build_unchanged_source_and_exact_old_api_page_match",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.populate()
        self.source = self.fixture.source
        self.calendar = self.fixture.calendar
        self.old = self.fixture.index
        self.new = self.fixture.root / "fictional_v2_school_read_index_20261012.sqlite3"

    def _audit(self, path=None):
        return audit_v2_school_index_health(
            self.source, self.calendar, path or self.old,
        )

    def _refresh(self):
        return prepare_versioned_v2_school_index(
            self.source, self.calendar, self.old, self.new,
        )

    def _source_hashes(self):
        return (file_sha256(self.source), file_sha256(self.calendar))

    def _append_next_year(self, *, seal: bool = True):
        self.fixture.fixture.calendar.record(explicit_sandbox_plan(
            10002, {stage79.stage27.COMP: ["04-01"]},
            approved_for_fictional_game=True,
        ))
        self.fixture.v2.append(
            10002, stage79.stage27.full_a(10002, "NEXT-A", "04-01"),
        )
        if seal:
            self.fixture.v2.seal_year(10002, expected_match_count=1)

    def test_missing_index_reports_without_writing_or_auto_building(self):
        before = self._source_hashes()
        report = self._audit()
        self.assertEqual("missing_index", report["status"])
        self.assertEqual([10000, 10001], report["saved_years"])
        self.assertFalse(report["strict_derived_memberships_verified"])
        self.assertTrue(report["original_saved_files_unmodified"])
        self.assertFalse(report["automatic_rebuild_or_switch"])
        self.assertFalse(self.old.exists())
        self.assertEqual(before, self._source_hashes())
        self.assertFalse(self.fixture.fixture.legacy_file.exists())

    def test_current_index_full_strict_source_and_memberships_verified(self):
        self.fixture.build()
        before = self._source_hashes()
        index_sha = file_sha256(self.old)
        status = self._audit()
        self.assertEqual("ready", status["status"])
        self.assertEqual([10000, 10001], status["indexed_range"])
        self.assertEqual([10000, 10001], status["indexed_years"])
        self.assertEqual([], status["outside_index_years"])
        self.assertTrue(status["strict_original_payloads_verified"])
        self.assertTrue(status["strict_derived_memberships_verified"])
        self.assertEqual(before, self._source_hashes())
        self.assertEqual(index_sha, file_sha256(self.old))
        self.assertTrue(json.loads(json.dumps(status))["original_saved_files_unmodified"])

    def test_new_year_is_detected_and_versioned_refresh_keeps_old(self):
        self.fixture.build()
        old_sha = file_sha256(self.old)
        self._append_next_year()
        before = self._source_hashes()
        status = self._audit()
        self.assertEqual("extension_required", status["status"])
        self.assertEqual([10002], status["outside_index_years"])
        self.assertTrue(status["strict_derived_memberships_verified"])
        refreshed = self._refresh()
        self.assertEqual("extension_required", refreshed["previous_status"])
        self.assertTrue(refreshed["previous_index_retained"])
        self.assertTrue(refreshed["new_index_strict_membership_verified"])
        self.assertEqual("ready", refreshed["new_index_status"])
        self.assertEqual([10000, 10001, 10002],
                         refreshed["new_indexed_years"])
        self.assertEqual(6, refreshed["new_index_matches"])
        self.assertFalse(refreshed["automatic_gui_selection"])
        self.assertEqual(old_sha, file_sha256(self.old))
        self.assertEqual(before, self._source_hashes())
        self.assertEqual("ready", self._audit(self.new)["status"])
        new_page = read_indexed_v2_school_page(
            self.source, self.calendar, self.new,
            stage79.stage27.FIRST, start_year=10000, end_year=10002,
            verify_scope="selected_years",
        )
        self.assertEqual(6, new_page["total"])
        self.assertTrue(new_page["offpage_derived_memberships_verified"])
        with self.assertRaises(ValueError):
            read_indexed_v2_school_page(
                self.source, self.calendar, self.old,
                stage79.stage27.FIRST, start_year=10000, end_year=10002,
            )
        with self.assertRaises(FileExistsError):
            self._refresh()

    def test_corrupt_old_memberships_refuse_browsing_but_new_index_can_be_built(self):
        self.fixture.build()
        with sqlite3.connect(self.old) as con:
            con.execute(
                "UPDATE school_game SET school_id='SCH999999' "
                "WHERE school_id=? AND match_id='AB'",
                (stage79.stage27.FIRST,),
            )
        old_sha = file_sha256(self.old)
        before = self._source_hashes()
        status = self._audit()
        self.assertEqual("integrity_conflict", status["status"])
        self.assertFalse(status["strict_derived_memberships_verified"])
        rebuild = self._refresh()
        self.assertEqual("integrity_conflict", rebuild["previous_status"])
        self.assertTrue(rebuild["new_index_strict_membership_verified"])
        self.assertEqual("ready", self._audit(self.new)["status"])
        self.assertEqual(old_sha, file_sha256(self.old))
        self.assertEqual(before, self._source_hashes())

    def test_unsealed_new_year_never_enters_refreshed_index(self):
        self.fixture.build()
        self._append_next_year(seal=False)
        old_sha = file_sha256(self.old)
        status = self._audit()
        self.assertEqual("unsealed_source_years", status["status"])
        self.assertEqual([10002], status["unsealed_years"])
        with self.assertRaisesRegex(ValueError, "unsealed"):
            self._refresh()
        self.assertFalse(self.new.exists())
        self.assertEqual(old_sha, file_sha256(self.old))

    def test_source_tamper_disables_audit_and_refresh(self):
        self.fixture.build()
        with sqlite3.connect(self.source) as conn:
            conn.execute(
                "UPDATE v2_option_a_matches SET payload_json='{}' "
                "WHERE match_id='AB'"
            )
        report = self._audit()
        self.assertEqual("integrity_conflict", report["status"])
        self.assertFalse(report["strict_original_payloads_verified"])
        old_sha = file_sha256(self.old)
        before = self._source_hashes()
        with self.assertRaises(ValueError):
            self._refresh()
        self.assertFalse(self.new.exists())
        self.assertEqual(old_sha, file_sha256(self.old))
        self.assertEqual(before, self._source_hashes())

    def test_new_target_cannot_alias_old_or_source_and_never_overwrites(self):
        self.fixture.build()
        before = self._source_hashes()
        old_sha = file_sha256(self.old)
        for target in (self.source, self.calendar, self.old):
            with self.subTest(target=target), self.assertRaises(ValueError):
                prepare_versioned_v2_school_index(
                    self.source, self.calendar, self.old, target,
                )
        self.new.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            self._refresh()
        self.assertEqual(b"existing", self.new.read_bytes())
        self.assertEqual(old_sha, file_sha256(self.old))
        self.assertEqual(before, self._source_hashes())


if __name__ == "__main__":
    unittest.main()
