"""Stage43G-83: 100-year shard boundaries and cross-century Option-A paging.

All saved games are fictional, full-A, explicitly sealed. This is NOT
evidence of real nationwide progression for 3000 schools.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import unittest

from phase2_engine.career_calendar_v2 import explicit_sandbox_plan
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_v2_school_century_shards import (
    MAX_SHARDS_PER_BUILD, build_v2_school_century_shards,
    read_v2_school_century_page,
)
from phase2_engine.career_v2_school_game_page import read_v2_school_game_page
import test_stage43g27_v2_option_a_archive as stage27


class Stage43G83ShardedV2Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage27.Stage43G27V2OptionASidecarTests(
            "test_10000_full_a_match_sealed_and_readonly_paged",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.source = self.fixture.v2_file
        self.calendar = self.fixture.calendar_file
        self.index_paths = None

    def _make(self, year: int, count: int):
        if year != 10000:
            self.fixture.calendar.record(explicit_sandbox_plan(
                year, {stage27.COMP: ["04-01", "04-02"]},
                approved_for_fictional_game=True,
            ))
        for i in range(count):
            self.fixture.sidecar.append(
                year, stage27.full_a(year, f"SHARD-{year}-{i:04d}"),
            )
        self.fixture.sidecar.seal_year(year, expected_match_count=count)

    def _populate(self, third=False):
        self._make(10000, 29)
        self._make(10100, 7)
        if third:
            self._make(10200, 4)

    def _build(self, last_year=10100, version=None):
        result = build_v2_school_century_shards(
            self.source, self.calendar, start_year=10000,
            end_year=last_year, version=version,
        )
        self.index_paths = [
            Path(item["index_path"]) for item in result["shards"]
        ]
        return result

    def _page(self, **kwargs):
        args = {
            "start_year": 10000,
            "end_year": 10100,
            "limit": 30,
            "offset": 0,
        }
        args.update(kwargs)
        return read_v2_school_century_page(
            self.source, self.calendar, self.index_paths,
            stage27.FIRST, **args,
        )

    def _source_digest(self):
        return (file_sha256(self.source), file_sha256(self.calendar))

    def test_two_centuries_order_29_plus_7_and_global_30_page(self):
        self._populate()
        before = self._source_digest()
        made = self._build()
        self.assertEqual([
            (10000, 10099), (10100, 10199),
        ], [(x["start_year"], x["end_year"]) for x in made["shards"]])
        self.assertEqual([10000, 10100], made["saved_years"])
        self.assertEqual(before, self._source_digest())
        first = self._page()
        self.assertEqual(36, first["total"])
        self.assertEqual(30, len(first["records"]))
        self.assertEqual(10000, first["records"][0]["year"])
        self.assertEqual(10100, first["records"][-1]["year"])
        self.assertEqual(2, first["shard_count"])
        second = self._page(offset=30)
        self.assertEqual(36, second["total"])
        self.assertEqual(6, len(second["records"]))
        self.assertTrue(all(x["year"] == 10100 for x in second["records"]))
        self.assertEqual([], self._page(offset=36)["records"])
        a = read_v2_school_game_page(
            self.source, self.calendar, stage27.FIRST,
            start_year=10000, end_year=10000,
        )
        b = read_v2_school_game_page(
            self.source, self.calendar, stage27.FIRST,
            start_year=10100, end_year=10100,
        )
        self.assertEqual(a["records"] + b["records"][:1], first["records"])
        self.assertEqual(b["records"][1:], second["records"])
        self.assertTrue(first["original_source_data_version_unchanged"])
        self.assertFalse(first["full_nation_unlimited_years_verified"])
        self.assertFalse(self.fixture.legacy_file.exists())
        self.assertEqual(before, self._source_digest())

    def test_three_centuries_strict_and_sparse_saved_years(self):
        self._populate(third=True)
        self._build(last_year=10200)
        before = self._source_digest()
        page = self._page(
            end_year=10200, offset=28, limit=12,
            verify_scope="selected_years",
        )
        self.assertEqual(40, page["total"])
        self.assertEqual(12, len(page["records"]))
        self.assertEqual([10000] + [10100]*7 + [10200]*4,
                         [row["year"] for row in page["records"]])
        self.assertTrue(page["all_selected_year_payloads_verified"])
        self.assertTrue(page["offpage_derived_memberships_verified"])
        self.assertEqual(before, self._source_digest())

    def test_missing_or_duplicate_shard_does_not_silently_drop_games(self):
        self._populate(third=True)
        self._build(last_year=10200)
        all_paths = self.index_paths[:]
        before = self._source_digest()
        self.index_paths = all_paths[:2]
        with self.assertRaisesRegex(ValueError, "coverage"):
            self._page(end_year=10200)
        self.index_paths = [all_paths[0], all_paths[0], all_paths[1]]
        with self.assertRaisesRegex(ValueError, "overlapping"):
            self._page()
        self.index_paths = [all_paths[0], all_paths[2]]
        with self.assertRaisesRegex(ValueError, "coverage"):
            self._page(end_year=10200)
        self.index_paths = all_paths
        with self.assertRaises(ValueError):
            self._page(start_year=10000, end_year=10000)
        self.assertEqual(before, self._source_digest())

    def test_wrong_provenance_and_unsealed_source_fail_closed(self):
        self._populate()
        self._build()
        before = self._source_digest()
        with sqlite3.connect(self.index_paths[1]) as conn:
            conn.execute("UPDATE meta SET source_path='other-save'")
        with self.assertRaisesRegex(ValueError, "wrong-source"):
            self._page()
        self.assertEqual(before, self._source_digest())

    def test_strict_offpage_tamper_detected_across_third_century(self):
        self._populate(third=True)
        self._build(last_year=10200)
        with sqlite3.connect(self.source) as conn:
            conn.execute(
                "UPDATE v2_option_a_matches SET payload_json='{}' "
                "WHERE match_id='SHARD-10200-0003'",
            )
        before = self._source_digest()
        # Page mode checks only the visible payload of each shard and its
        # sealed ledger, not a hidden off-page JSON payload.
        shallow = self._page(end_year=10200, limit=1)
        self.assertEqual(40, shallow["total"])
        with self.assertRaisesRegex(ValueError, "checksum"):
            self._page(
                end_year=10200, limit=1, verify_scope="selected_years",
            )
        self.assertEqual(before, self._source_digest())

    def test_preflight_filename_collision_refuses_all_new_targets(self):
        self._populate(third=True)
        self._build(last_year=10200)
        before = self._source_digest()
        with self.assertRaises(FileExistsError):
            self._build(last_year=10200)
        # A collision in a later shard must not create an earlier new one.
        self.assertEqual(before, self._source_digest())
        new_version = build_v2_school_century_shards(
            self.source, self.calendar, start_year=10000, end_year=10200,
            version="v02",
        )
        self.assertEqual(3, len(new_version["shards"]))
        self.assertEqual(6, len(list(self.fixture.root.glob(
            "fictional_v2_school_read_index_*.sqlite3",
        ))))
        self.assertEqual(before, self._source_digest())

    def test_unsealed_years_block_build_and_reads(self):
        self._make(10000, 1)
        self.fixture.calendar.record(explicit_sandbox_plan(
            10100, {stage27.COMP: ["04-01"]},
            approved_for_fictional_game=True,
        ))
        self.fixture.sidecar.append(
            10100, stage27.full_a(10100, "UNSEALED"),
        )
        with self.assertRaisesRegex(ValueError, "unsealed"):
            self._build()
        self.assertEqual([], list(self.fixture.root.glob(
            "fictional_v2_school_read_index_*.sqlite3",
        )))

    def test_invalid_year_bounds_batch_limit_and_unknown_source(self):
        self._populate()
        for args in (
            {"start_year": 9999, "end_year": 10000},
            {"start_year": 10100, "end_year": 10000},
            {"start_year": 10000, "end_year": 10000+100*MAX_SHARDS_PER_BUILD},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                build_v2_school_century_shards(
                    self.source, self.calendar, **args,
                )
        for tag in ("", "../bad", "bad!", "x" * 17):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                build_v2_school_century_shards(
                    self.source, self.calendar,
                    start_year=10000, end_year=10100, version=tag,
                )
        self._build()
        for args in (
            {"limit": 201}, {"offset": -1},
            {"verify_scope": "unverified"},
            {"start_year": 9999},
            {"school_id": None},
        ):
            if "school_id" in args:
                with self.assertRaises(ValueError):
                    read_v2_school_century_page(
                        self.source, self.calendar,
                        self.index_paths, None,
                        start_year=10000, end_year=10100,
                    )
            else:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    self._page(**args)


if __name__ == "__main__":
    unittest.main()
