"""Stage43G-71: derived cache PK index cleanup, no schema/data migration.

Legacy cache has an explicit index whose columns duplicate the SQLite PK.
V2 player-first index is distinct from its PK and must remain.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from phase2_engine.career_stats_cache_btree_audit import (
    audit_saved_stats_cache_indexes, CareerStatsCacheBtreeConflict,
)
from phase2_engine.career_history_scale_benchmark import file_sha256
import test_stage43g15_sealed_player_cache as legacy_fixture
import test_stage43g29_v2_player_stat_cache as v2_fixture


class Stage43G71CacheIndexTests(unittest.TestCase):
    def setUp(self):
        self.old = legacy_fixture.Stage43G15SealedPlayerCacheTests(
            "test_immutable_two_year_cache_matches_original_A_seasons_and_leaders",
        )
        self.old.setUp()
        self.addCleanup(self.old.tearDown)
        self.old.seal_all()
        for y in (2026, 2027):
            self.old.cache.materialize(self.old.seed.a, year=y)
        self.future = v2_fixture.Stage43G29V2PlayerStatCacheTests(
            "test_cache_creation_repeat_full_verification_and_archive_sha",
        )
        self.future.setUp()
        self.addCleanup(self.future.tearDown)
        self.future.sealed()
        for school in (self.future.a, self.future.b):
            self.future.cache.materialize(10000, school)
        self.legacy_path = self.old.cache.path
        self.v2_path = self.future.cache_file

    @staticmethod
    def _index_names(path, table):
        with sqlite3.connect(path) as conn:
            return [r[1] for r in conn.execute(
                f'PRAGMA index_list("{table}")'
            )]

    @staticmethod
    def _payload_digest(path, table):
        with sqlite3.connect(path) as conn:
            return sha256("".join(row[0] for row in conn.execute(
                f"SELECT payload_json FROM {table} "
                "ORDER BY school_id,year,player_id"
            )).encode("utf-8")).hexdigest()

    def test_new_legacy_cache_avoids_duplicate_but_player_lookup_survives(self):
        initial = file_sha256(self.legacy_path)
        report = audit_saved_stats_cache_indexes(legacy_cache=self.legacy_path)
        row = report["files"]["legacy"]
        self.assertFalse(row["old_duplicate_index_present"])
        self.assertEqual([], row["exact_primary_key_duplicate_indexes"])
        self.assertNotIn(
            "idx_cached_school_year",
            self._index_names(self.legacy_path, "player_year_stat_cache"),
        )
        self.assertIn(
            "idx_cached_player_year",
            self._index_names(self.legacy_path, "player_year_stat_cache"),
        )
        self.assertTrue(row["both_query_plans_use_indexes"])
        self.assertTrue(any(
            row["primary_key_autoindex"] in query
            for query in row["school_year_seek_plan"]
        ))
        read = self.old.cache.player_seasons(
            self.old.seed.hitter, start_year=2026, end_year=2027,
            verify_source=True,
        )
        raw = self.old.seed.view.player_seasons(
            self.old.seed.hitter, start_year=2026, end_year=2027,
        )
        self.assertEqual(raw["totals"], read["totals"])
        self.assertEqual(initial, file_sha256(self.legacy_path))

    def test_old_legacy_cache_keeps_duplicate_index_unmodified_and_readable(self):
        with sqlite3.connect(self.legacy_path) as conn:
            conn.execute(
                "CREATE INDEX idx_cached_school_year ON "
                "player_year_stat_cache(school_id,year,player_id)"
            )
        before = file_sha256(self.legacy_path)
        report = audit_saved_stats_cache_indexes(legacy_cache=self.legacy_path)
        self.assertEqual(
            ["idx_cached_school_year"],
            report["files"]["legacy"]["exact_primary_key_duplicate_indexes"],
        )
        self.assertTrue(report["files"]["legacy"]["both_query_plans_use_indexes"])
        if report["files"]["legacy"]["dbstat_available"]:
            self.assertGreater(
                report["files"]["legacy"]["old_duplicate_index_allocated_bytes"],
                0,
            )
        self.assertEqual(before, file_sha256(self.legacy_path))
        self.assertFalse(
            self.old.cache.materialize(self.old.seed.a, year=2026)["inserted"]
        )
        self.assertIn(
            "idx_cached_school_year",
            self._index_names(self.legacy_path, "player_year_stat_cache"),
        )
        self.assertEqual(
            raw := self.old.seed.view.player_seasons(
                self.old.seed.hitter, start_year=2026, end_year=2027,
            )["totals"],
            self.old.cache.player_seasons(
                self.old.seed.hitter, start_year=2026, end_year=2027,
                verify_source=True,
            )["totals"],
        )

    def test_v2_player_first_index_is_not_duplicate_and_deep_read_stays_correct(self):
        before = file_sha256(self.v2_path)
        report = audit_saved_stats_cache_indexes(v2_cache=self.v2_path)
        row = report["files"]["v2"]
        self.assertFalse(row["old_duplicate_index_present"])
        self.assertEqual([], row["exact_primary_key_duplicate_indexes"])
        self.assertTrue(row["both_query_plans_use_indexes"])
        self.assertIn(
            "idx_v2_stat_player_year",
            self._index_names(self.v2_path, "v2_player_year_stat_cache"),
        )
        self.assertTrue(self.future.cache.read_year(
            10000, self.future.a, verify_source=True,
        )["source_payloads_rechecked_on_read"])
        self.assertEqual(before, file_sha256(self.v2_path))

    def test_both_files_btree_allocation_and_sqlite_hashes_unchanged(self):
        before = [file_sha256(p) for p in (self.legacy_path, self.v2_path)]
        report = audit_saved_stats_cache_indexes(
            legacy_cache=self.legacy_path, v2_cache=self.v2_path,
        )
        self.assertEqual({"legacy", "v2"}, set(report["files"]))
        self.assertEqual(
            sum(row["file_bytes"] for row in report["files"].values()),
            report["observed_cache_file_bytes"],
        )
        self.assertTrue(report["existing_cache_shas_unchanged"])
        self.assertFalse(report["existing_saved_cache_indexes_dropped"])
        self.assertFalse(report["full_cache_source_integrity_audited_here"])
        for row in report["files"].values():
            self.assertGreater(row["saved_player_year_rows"], 0)
            self.assertGreater(row["file_bytes"], 0)
            if row["dbstat_available"]:
                self.assertGreater(
                    row["index_btree_bytes"][row["primary_key_autoindex"]], 0
                )
            else:
                self.assertIsNone(row["index_btree_bytes"])
        self.assertEqual(
            before, [file_sha256(p) for p in (
                self.legacy_path, self.v2_path,
            )],
        )

    def test_cloned_old_index_has_same_stat_rows_but_extra_btree(self):
        with tempfile.TemporaryDirectory() as temp:
            clone = Path(temp) / "previous_legacy_cache.sqlite3"
            shutil.copy2(self.legacy_path, clone)
            with sqlite3.connect(clone) as conn:
                conn.execute(
                    "CREATE INDEX idx_cached_school_year ON "
                    "player_year_stat_cache(school_id,year,player_id)"
                )
            before = file_sha256(self.legacy_path)
            newer = audit_saved_stats_cache_indexes(
                legacy_cache=self.legacy_path,
            )["files"]["legacy"]
            older = audit_saved_stats_cache_indexes(
                legacy_cache=clone,
            )["files"]["legacy"]
            self.assertEqual(
                newer["saved_player_year_rows"],
                older["saved_player_year_rows"],
            )
            self.assertEqual(
                self._payload_digest(self.legacy_path, "player_year_stat_cache"),
                self._payload_digest(clone, "player_year_stat_cache"),
            )
            self.assertFalse(newer["old_duplicate_index_present"])
            self.assertTrue(older["old_duplicate_index_present"])
            if newer["dbstat_available"] and older["dbstat_available"]:
                self.assertGreater(
                    older["old_duplicate_index_allocated_bytes"], 0,
                )
            # This is an observed index page allocation, NOT predicted
            # recoverable bytes on a user's existing sealed database.
            self.assertEqual(before, file_sha256(self.legacy_path))

    def test_dropped_player_first_index_fails_without_creating_it(self):
        with sqlite3.connect(self.legacy_path) as conn:
            conn.execute("DROP INDEX idx_cached_player_year")
        before = file_sha256(self.legacy_path)
        with self.assertRaisesRegex(
            CareerStatsCacheBtreeConflict, "PK or player-first index",
        ):
            audit_saved_stats_cache_indexes(legacy_cache=self.legacy_path)
        self.assertEqual(before, file_sha256(self.legacy_path))
        self.assertNotIn(
            "idx_cached_player_year",
            self._index_names(self.legacy_path, "player_year_stat_cache"),
        )

    def test_bad_paths_alias_and_symlink_never_create_any_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "no-cache.sqlite3"
            with self.assertRaises(ValueError):
                audit_saved_stats_cache_indexes()
            with self.assertRaises(FileNotFoundError):
                audit_saved_stats_cache_indexes(legacy_cache=missing)
            self.assertFalse(missing.exists())
            with self.assertRaises(CareerStatsCacheBtreeConflict):
                audit_saved_stats_cache_indexes(
                    legacy_cache=self.legacy_path,
                    v2_cache=self.legacy_path,
                )
            link = Path(temp) / "link.sqlite3"
            link.symlink_to(self.legacy_path)
            with self.assertRaises(CareerStatsCacheBtreeConflict):
                audit_saved_stats_cache_indexes(legacy_cache=link)

    def test_cli_writes_report_only_and_refuses_overwrite_of_source_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "indexes.json"
            before = [file_sha256(x) for x in (
                self.legacy_path, self.v2_path,
            )]
            args = [
                sys.executable, "-m", "phase2_engine.career_stats_cache_btree_audit",
                "--legacy-cache", str(self.legacy_path),
                "--v2-cache", str(self.v2_path),
                "--output-json", str(output),
            ]
            done = subprocess.run(
                args, check=True, capture_output=True, text=True,
            )
            self.assertEqual(
                "43G-71", json.loads(output.read_text(encoding="utf-8"))["stage"],
            )
            self.assertIn('"read_only": true', done.stdout)
            refused = subprocess.run(
                args[:-1] + [str(self.v2_path)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(0, refused.returncode)
            self.assertEqual(
                before, [file_sha256(x) for x in (
                    self.legacy_path, self.v2_path,
                )],
            )


if __name__ == "__main__":
    unittest.main()
