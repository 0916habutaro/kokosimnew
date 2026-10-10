"""Stage43G-13: small CI and a real 100-year / four-school synthetic audit.

Only synthetic records are used. Never claim national 3,000-school results
from this test: the full 3,000x50/100 profile must be opted into separately.
"""
from __future__ import annotations

import sqlite3
import json
import tempfile
from pathlib import Path
import unittest

from phase2_engine.career_history_scale_audit import run_scale_audit
from phase2_engine.career_longitudinal_read import (
    CareerHistoryViewConflict, CareerLongitudinalReadModel,
)
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]


class Stage43G13CenturyHistoryScaleTests(unittest.TestCase):
    def test_three_year_a_history_rosters_and_measured_index_read(self):
        report = run_scale_audit(
            ROOT / "data", school_count=16, years=3,
            games_per_school_year=4,
        )
        self.assertTrue(report["measured_not_extrapolated"])
        self.assertEqual(
            "synthetic_performance_only_not_real_game_results",
            report["profile"],
        )
        self.assertEqual(96, report["synthetic_match_count"])
        self.assertEqual(48, report["synthetic_school_year_roster_count"])
        self.assertGreater(report["history_sqlite"]["file_bytes"], 0)
        self.assertGreater(report["roster_sqlite"]["file_bytes"], 0)
        self.assertGreater(report["bytes_per_synthetic_match_including_indexes"], 0)
        self.assertTrue(any(
            "idx_history_school1_year" in x
            for x in report["query_plans"]["home_game"]
        ))
        self.assertTrue(any(
            "idx_history_school2_year" in x
            for x in report["query_plans"]["away_game"]
        ))
        self.assertTrue(any(
            "idx_career_players_school_entry" in x
            for x in report["query_plans"]["school_player_index"]
        ))
        self.assertEqual(
            3,
            report["read_latency"]["school_results"]["sample_count"] // 3,
        )
        self.assertFalse(report["full_year_tournament_runtime_tested"])

    def test_real_hundred_year_sqlite_horizon_for_four_schools(self):
        # This ACTUALLY writes, seals and reads 100 adjacent synthetic years.
        # Scaling to 3,000 schools requires the explicit large CLI profile.
        with tempfile.TemporaryDirectory() as temp:
            result = run_scale_audit(
                ROOT / "data", school_count=4, years=100,
                games_per_school_year=4, output_root=temp,
            )
            self.assertEqual(800, result["synthetic_match_count"])
            self.assertEqual(400, result["synthetic_school_year_roster_count"])
            print("STAGE43G13_100Y_MEASURED " + json.dumps({
                "schools": result["schools"],
                "years": result["years"],
                "games": result["synthetic_match_count"],
                "roster_years": result["synthetic_school_year_roster_count"],
                "history_bytes": result["history_sqlite"]["file_bytes"],
                "roster_bytes": result["roster_sqlite"]["file_bytes"],
                "bytes_per_synthetic_match": result[
                    "bytes_per_synthetic_match_including_indexes"
                ],
                "bytes_per_roster_year": result[
                    "bytes_per_synthetic_school_year_roster_including_identity_index"
                ],
                "school_results": result["read_latency"]["school_results"],
                "school_player_index": result["read_latency"]["school_player_index"],
                "player_years": result["read_latency"]["player_years"],
            }, ensure_ascii=False), flush=True)
            self.assertEqual([2026, 2125], result["year_range"])
            self.assertFalse(result["100_year_unbounded_simulation_verified"])
            repo = DataRepository(ROOT / "data")
            sid = sorted(repo.school_to_program)[0]
            read = CareerLongitudinalReadModel(
                Path(temp) / "historical_matches.sqlite3",
                Path(temp) / "career_rosters.sqlite3",
            )
            first = read.school_results(
                sid, start_year=2026, end_year=2125, limit=20,
            )
            tail = read.school_results(
                sid, start_year=2026, end_year=2125, limit=20, offset=180,
            )
            self.assertEqual(200, first["total_groups"])
            self.assertEqual(20, len(first["records"]))
            self.assertEqual(20, len(tail["records"]))
            self.assertEqual(2026, first["records"][0]["year"])
            self.assertEqual(2125, tail["records"][-1]["year"])
            members = read.school_player_index(
                sid, limit=100, offset=800,
            )
            self.assertEqual(812, members["total"])
            self.assertEqual(12, len(members["players"]))
            with sqlite3.connect(Path(temp) / "historical_matches.sqlite3") as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM career_years WHERE status='sealed'"
                ).fetchone()[0]
                self.assertEqual(100, count)

    def test_page_query_keeps_strict_integrity_even_outside_requested_page(self):
        repo = DataRepository(ROOT / "data")
        sid = sorted(repo.school_to_program)[0]
        with tempfile.TemporaryDirectory() as temp:
            run_scale_audit(
                ROOT / "data", school_count=8, years=4,
                games_per_school_year=4, output_root=temp,
            )
            archive = Path(temp) / "historical_matches.sqlite3"
            read = CareerLongitudinalReadModel(
                archive, Path(temp) / "career_rosters.sqlite3",
            )
            page = read.school_results(
                sid, start_year=2026, end_year=2029, limit=1,
            )
            self.assertEqual(8, page["total_groups"])
            self.assertEqual(1, len(page["records"]))
            self.assertEqual([], read.school_results(
                sid, start_year=2026, end_year=2029,
                limit=1, offset=8,
            )["records"])
            with sqlite3.connect(archive) as conn:
                row = conn.execute(
                    "SELECT match_id, competition_id FROM historical_matches "
                    "WHERE year=2029 AND team1_id=? LIMIT 1", (sid,),
                ).fetchone()
                self.assertIsNotNone(row)
                conn.execute(
                    "UPDATE historical_matches SET record_sha256='TAMPER' "
                    "WHERE year=2029 AND match_id=? AND competition_id=?",
                    (row[0], row[1]),
                )
            with self.assertRaises(CareerHistoryViewConflict):
                read.school_results(
                    sid, start_year=2026, end_year=2029, limit=1,
                )

    def test_large_profile_is_explicit_and_non_destructive(self):
        with self.assertRaisesRegex(ValueError, "allow_large"):
            run_scale_audit(
                ROOT / "data", school_count=3000, years=100,
            )
        with self.assertRaises(ValueError):
            run_scale_audit(
                ROOT / "data", school_count=3, years=100,
            )
        with self.assertRaises(ValueError):
            run_scale_audit(
                ROOT / "data", school_count=4, years=10000,
            )
        with tempfile.TemporaryDirectory() as temp:
            result = run_scale_audit(
                ROOT / "data", school_count=4, years=1,
                output_root=temp,
            )
            self.assertEqual(8, result["synthetic_match_count"])
            with self.assertRaisesRegex(ValueError, "overwrite"):
                run_scale_audit(
                    ROOT / "data", school_count=4, years=1,
                    output_root=temp,
                )


if __name__ == "__main__":
    unittest.main()
