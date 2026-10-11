"""Stage43G-70: retain PK/day lookups, omit only a duplicate NEW-v2 B-tree.

The tested fixture is a synthetic Option-A sandbox, never an actual
nationwide season. Old saved files with the duplicate remain unmodified.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from phase2_engine.career_storage_btree_audit import (
    audit_save_storage_btrees, CareerStorageBtreeConflict,
)
from phase2_engine.career_history_scale_benchmark import file_sha256
import test_stage43g27_v2_option_a_archive as stage27
import test_stage43g31_cross_era_browse_model as stage31


class Stage43G70BtreeAuditTests(unittest.TestCase):
    def setUp(self):
        self.old_fixture = stage27.Stage43G27V2OptionASidecarTests(
            "test_10000_full_a_match_sealed_and_readonly_paged",
        )
        self.old_fixture.setUp()
        self.addCleanup(self.old_fixture.tearDown)
        self.old_fixture.sidecar.append(
            10000, stage27.full_a(10000, "G70-A"),
        )
        self.old_fixture.sidecar.append(
            10000, stage27.full_a(10000, "G70-B", "04-02"),
        )
        self.old_fixture.sidecar.seal_year(10000, expected_match_count=2)
        self.root = self.old_fixture.root
        self.source = self.old_fixture.v2_file

    def _index_list(self, path):
        with sqlite3.connect(path) as conn:
            return [row[1] for row in conn.execute(
                "PRAGMA index_list('v2_option_a_matches')"
            )]

    def test_new_v2_keeps_primary_key_and_calendar_day_index(self):
        before = file_sha256(self.source)
        report = audit_save_storage_btrees(self.root)
        lookup = report["v2_match_lookup"]
        self.assertTrue(lookup["v2_pk_autoindex_verified"])
        self.assertTrue(lookup["required_day_lookup_index_verified"])
        self.assertFalse(lookup["legacy_explicit_duplicate_index_present"])
        self.assertEqual([], lookup["redundant_exact_pk_index_names"])
        self.assertNotIn("idx_v2_games_school_a", self._index_list(self.source))
        self.assertIn("idx_v2_games_day", self._index_list(self.source))
        self.assertEqual(2, self.old_fixture.sidecar.year_matches(
            10000, limit=1,
        )["total"])
        self.assertEqual("G70-B", self.old_fixture.sidecar.day_matches(
            "G10000:04-02",
        )["rows"][0]["match_id"])
        self.assertEqual(before, file_sha256(self.source))
        self.assertTrue(report["all_existing_files_sha256_unchanged"])
        self.assertFalse(report["file_size_reduction_guaranteed"])
        self.assertFalse(report["existing_sealed_v2_archives_migrated_or_modified"])

    def test_old_saved_v2_duplicate_is_reported_not_dropped(self):
        with sqlite3.connect(self.source) as conn:
            conn.execute(
                "CREATE INDEX idx_v2_games_school_a "
                "ON v2_option_a_matches(year,competition_id,match_id)",
            )
        before = file_sha256(self.source)
        report = audit_save_storage_btrees(self.root)
        self.assertEqual(
            ["idx_v2_games_school_a"],
            report["v2_match_lookup"]["redundant_exact_pk_index_names"],
        )
        self.assertTrue(
            report["v2_match_lookup"]["legacy_explicit_duplicate_index_present"]
        )
        if report["files"]["v2_matches"]["dbstat_available"]:
            self.assertGreater(
                report["v2_obsolete_duplicate_exact_pk_index_bytes"], 0,
            )
        else:
            self.assertIsNone(
                report["v2_obsolete_duplicate_exact_pk_index_bytes"]
            )
        self.assertEqual(before, file_sha256(self.source))
        self.assertIn("idx_v2_games_school_a", self._index_list(self.source))
        self.assertEqual(2, self.old_fixture.sidecar.year_matches(
            10000,
        )["total"])

    def test_measured_btree_index_allocation_partition_if_dbstat_exists(self):
        report = audit_save_storage_btrees(self.root)
        row = report["files"]["v2_matches"]
        if row["dbstat_available"]:
            self.assertGreater(row["btree_index_bytes"], 0)
            self.assertGreater(row["btree_table_bytes"], 0)
            self.assertLessEqual(
                row["btree_index_bytes"] + row["btree_table_bytes"],
                row["page_count"] * row["page_size"],
            )
            self.assertTrue(row["index_btree_sizes"][
                "idx_v2_games_day"
            ] > 0)
        else:
            self.assertIsNone(row["btree_index_bytes"])
            self.assertIsNone(row["index_btree_sizes"])
        self.assertEqual(
            sum(p["file_bytes"] for p in report["files"].values()),
            report["file_bytes_total"],
        )

    def test_integrated_existing_roster_legacy_v2_cache_footprints(self):
        fixture = stage31.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year",
        )
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.setup_both()
        snapshots = {
            p.name: file_sha256(p)
            for p in fixture.root.glob("*.sqlite3")
        }
        report = audit_save_storage_btrees(fixture.root)
        self.assertEqual({
            "legacy_matches", "v2_matches", "v2_calendar",
            "shared_rosters", "v2_derived_cache",
        }, set(report["files"]))
        self.assertEqual(
            "legacy_source",
            report["files"]["legacy_matches"]["file_role"],
        )
        self.assertEqual(
            "rosters_shared",
            report["files"]["shared_rosters"]["file_role"],
        )
        self.assertEqual(
            "v2_cache",
            report["files"]["v2_derived_cache"]["file_role"],
        )
        self.assertEqual(
            sum(x["file_bytes"] for x in report["files"].values()),
            report["file_bytes_total"],
        )
        self.assertTrue(report["read_only"])
        self.assertIn(
            "source_payload_sha", report["not_verified_by_this_function"],
        )
        self.assertEqual(
            snapshots, {
                p.name: file_sha256(p)
                for p in fixture.root.glob("*.sqlite3")
            },
        )

    def test_missing_legacy_optional_but_missing_v2_never_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                audit_save_storage_btrees(path)
            self.assertEqual([], list(path.iterdir()))
            with self.assertRaises(ValueError):
                audit_save_storage_btrees(path / "missing")
        self.assertFalse(self.old_fixture.legacy_file.exists())
        self.assertEqual(
            {"v2_matches", "v2_calendar"},
            set(audit_save_storage_btrees(self.root)["files"]),
        )
        self.assertFalse(self.old_fixture.legacy_file.exists())

    def test_deleted_day_index_is_rejected_without_creating_replacement(self):
        with sqlite3.connect(self.source) as conn:
            conn.execute("DROP INDEX idx_v2_games_day")
        before = file_sha256(self.source)
        with self.assertRaisesRegex(
            CareerStorageBtreeConflict, "primary-key and calendar indexes",
        ):
            audit_save_storage_btrees(self.root)
        self.assertEqual(before, file_sha256(self.source))
        self.assertNotIn("idx_v2_games_day", self._index_list(self.source))

    def test_symlinked_or_duplicate_archive_paths_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fictional_option_a_v2.sqlite3").symlink_to(
                self.source,
            )
            with self.assertRaises(CareerStorageBtreeConflict):
                audit_save_storage_btrees(root)
        before = file_sha256(self.source)
        audit_save_storage_btrees(self.root)
        self.assertEqual(before, file_sha256(self.source))


if __name__ == "__main__":
    unittest.main()
