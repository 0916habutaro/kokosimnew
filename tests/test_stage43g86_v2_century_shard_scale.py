"""Stage43G-86: 4/16/32 century-shard source/scale audit.

Fixture has 32 saved fictional seasons, one at each century's boundary;
it does NOT simulate every intervening season or 3000 schools.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import unittest

from phase2_engine.career_calendar_v2 import explicit_sandbox_plan
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_v2_century_scale_benchmark import (
    measure_v2_century_shard_scale,
)
from phase2_engine.career_v2_school_century_shards import (
    build_v2_school_century_shards, read_v2_school_century_page,
)
import test_stage43g27_v2_option_a_archive as stage27


class Stage43G86CenturyShardScaleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage27.Stage43G27V2OptionASidecarTests(
            "test_10000_full_a_match_sealed_and_readonly_paged",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.source = self.fixture.v2_file
        self.calendar = self.fixture.calendar_file

    def populate(self):
        for n in range(32):
            year = 10000 + n * 100
            if n:
                self.fixture.calendar.record(explicit_sandbox_plan(
                    year, {stage27.COMP: ["04-01"]},
                    approved_for_fictional_game=True,
                ))
            self.fixture.sidecar.append(
                year, stage27.full_a(year, f"SCALE-{year}", "04-01"),
            )
            self.fixture.sidecar.seal_year(year, expected_match_count=1)

    def test_4_16_32_shards_timed_and_32_plus_second_page(self):
        self.populate()
        original = (file_sha256(self.source), file_sha256(self.calendar))
        made = build_v2_school_century_shards(
            self.source, self.calendar,
            start_year=10000, end_year=13100, version="scale",
        )
        self.assertEqual(32, len(made["shards"]))
        self.assertEqual(32, len(made["saved_years"]))
        paths = tuple(Path(s["index_path"]) for s in made["shards"])
        all_before = {
            p.name: file_sha256(p)
            for p in (self.source, self.calendar, *paths)
        }
        result = measure_v2_century_shard_scale(
            self.source, self.calendar, paths, stage27.FIRST,
        )
        self.assertEqual([4, 16, 32], [
            c["shards"] for c in result["cases"]
        ])
        self.assertEqual([4, 16, 32], [
            c["saved_school_matches"] for c in result["cases"]
        ])
        self.assertEqual([4, 16, 30], [
            c["visible_school_matches"] for c in result["cases"]
        ])
        self.assertTrue(all(
            0 <= c["page_ms"] and 0 <= c["strict_selected_years_ms"]
            for c in result["cases"]
        ))
        self.assertTrue(result["source_sqlite_and_indexes_unchanged"])
        self.assertTrue(result["sparse_years_not_continuous_3200_year_simulation"])
        self.assertFalse(result["automatic_index_activation"])
        last = read_v2_school_century_page(
            self.source, self.calendar, paths, stage27.FIRST,
            start_year=10000, end_year=13100, limit=30, offset=30,
            verify_scope="selected_years",
        )
        self.assertEqual(32, last["total"])
        self.assertEqual([13000, 13100], [
            x["year"] for x in last["records"]
        ])
        self.assertTrue(last["all_selected_year_payloads_verified"])
        self.assertEqual(original, (
            file_sha256(self.source), file_sha256(self.calendar),
        ))
        self.assertEqual(all_before, {
            p.name: file_sha256(p)
            for p in (self.source, self.calendar, *paths)
        })
        self.assertFalse(self.fixture.legacy_file.exists())
        # Even with 32 shards, a hidden offpage source JSON mutation is
        # detected by an explicit strict audit.
        with sqlite3.connect(self.source) as con:
            con.execute(
                "UPDATE v2_option_a_matches SET payload_json='{}' "
                "WHERE match_id='SCALE-13100'",
            )
        altered = file_sha256(self.source)
        with self.assertRaisesRegex(ValueError, "checksum"):
            read_v2_school_century_page(
                self.source, self.calendar, paths, stage27.FIRST,
                start_year=10000, end_year=13100,
                limit=1, verify_scope="selected_years",
            )
        self.assertEqual(altered, file_sha256(self.source))

    def test_bounded_inputs_do_not_create_indexes_or_modify_source(self):
        before = file_sha256(self.calendar)
        for kwargs in (
            {"scenarios": ()}, {"scenarios": (16, 4)},
            {"scenarios": (33,)}, {"first_year": 9999},
            {"scenarios": (True,)},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                measure_v2_century_shard_scale(
                    self.source, self.calendar,
                    ["missing.sqlite3"] * 32, stage27.FIRST, **kwargs,
                )
        with self.assertRaises(ValueError):
            measure_v2_century_shard_scale(
                self.source, self.calendar,
                ["missing.sqlite3"] * 33, stage27.FIRST,
            )
        self.assertEqual(before, file_sha256(self.calendar))
        self.assertFalse(self.source.exists())
        self.assertFalse(self.fixture.legacy_file.exists())


if __name__ == "__main__":
    unittest.main()
