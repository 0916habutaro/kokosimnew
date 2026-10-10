"""Stage43G-27: 10000-year complete Option-A sidecar and legacy isolation."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from phase2_engine.career_calendar_v2 import (
    CareerCalendarV2Archive, explicit_sandbox_plan,
)
from phase2_engine.career_history_scale_audit import synthetic_ability_record
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_v2_option_a_archive import (
    CareerV2OptionAArchive, CareerV2MatchConflict,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive

COMP = "CMP000086"
FIRST = "SCH000001"
SECOND = "SCH000002"


def full_a(year: int, mid: str, day: str = "04-01") -> dict:
    row = synthetic_ability_record(
        year, COMP, mid, FIRST, SECOND, int(day.split("-")[1]),
    )
    row.pop("match_date")
    row["game_day_token"] = f"G{year}:{day}"
    row["date_source"] = "fictional_v2_day_slot"
    row["completed_on"] = ""
    return row


class Stage43G27V2OptionASidecarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.legacy_file = self.root / "historical_matches.sqlite3"
        self.calendar_file = self.root / "sandbox_calendar_v2.sqlite3"
        self.v2_file = self.root / "fictional_option_a_v2.sqlite3"
        self.calendar = CareerCalendarV2Archive(self.calendar_file)
        self.calendar.record(explicit_sandbox_plan(
            10000, {COMP: ["02-29", "04-01", "04-02"]},
            approved_for_fictional_game=True,
        ))
        self.sidecar = CareerV2OptionAArchive(
            self.v2_file, self.calendar_file,
            legacy_archive_path=self.legacy_file,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_10000_full_a_match_sealed_and_readonly_paged(self):
        self.assertTrue(self.sidecar.append(
            10000, full_a(10000, "FUTURE-A")
        )["inserted"])
        self.assertTrue(self.sidecar.append(
            10000, full_a(10000, "FUTURE-B", "04-02")
        )["inserted"])
        self.assertFalse(self.legacy_file.exists())
        record = self.sidecar.append(10000, full_a(10000, "FUTURE-A"))
        self.assertFalse(record["inserted"])
        self.assertFalse(self.sidecar.seal_year(
            10000, expected_match_count=2
        )["already_sealed"])
        self.assertTrue(self.sidecar.seal_year(
            10000, expected_match_count=2
        )["already_sealed"])
        before = (file_sha256(self.calendar_file), file_sha256(self.v2_file))
        one = self.sidecar.year_matches(10000, limit=1)
        self.assertEqual("sealed", one["year_status"])
        self.assertEqual(2, one["total"])
        self.assertEqual(1, len(one["rows"]))
        self.assertEqual("G10000:04-01",
                         one["rows"][0]["game_day_token"])
        self.assertEqual(18, len(one["rows"][0]["batter_stats"]))
        self.assertEqual(2, len(one["rows"][0]["pitcher_stats"]))
        self.assertEqual(18, len(one["rows"][0]["inning_scores"]))
        self.assertEqual(2, len(one["rows"][0]["team_stats"]))
        self.assertEqual(
            "FUTURE-B",
            self.sidecar.year_matches(10000, limit=1, offset=1)
            ["rows"][0]["match_id"],
        )
        daily = self.sidecar.day_matches("G10000:04-02")
        self.assertEqual(1, daily["total"])
        self.assertEqual("FUTURE-B", daily["rows"][0]["match_id"])
        self.assertEqual(0,
                         self.sidecar.day_matches("G10000:02-29")["total"])
        self.assertEqual(
            before, (file_sha256(self.calendar_file), file_sha256(self.v2_file))
        )
        self.assertFalse(self.legacy_file.exists())
        self.assertFalse(one["real_tournament_runtime_connected"])
        self.assertFalse(one["legacy_stats_cache_supports_v2"])

    def test_sealed_year_does_not_accept_new_game_or_changed_replay(self):
        self.sidecar.append(10000, full_a(10000, "ONE"))
        self.sidecar.seal_year(10000, expected_match_count=1)
        self.assertFalse(self.sidecar.append(
            10000, full_a(10000, "ONE")
        )["inserted"])
        with self.assertRaisesRegex(CareerV2MatchConflict, "sealed"):
            self.sidecar.append(10000, full_a(10000, "TWO"))
        replay = full_a(10000, "ONE")
        replay["ability_detail"]["batter_stats"][0]["hits"] += 1
        with self.assertRaisesRegex(CareerV2MatchConflict, "immutable"):
            self.sidecar.append(10000, replay)
        self.assertEqual(1, self.sidecar.year_matches(10000)["total"])

    def test_wrong_calendar_missing_plan_or_legacy_iso_rejected(self):
        with self.assertRaisesRegex(CareerV2MatchConflict, "calendar"):
            self.sidecar.append(10001, full_a(10001, "NO-PLAN"))
        with self.assertRaisesRegex(CareerV2MatchConflict, "not in approved"):
            self.sidecar.append(10000, full_a(10000, "WRONG-DATE", "04-03"))
        bad = full_a(10000, "LEGACY-ISO")
        bad["match_date"] = "10000-04-01"
        with self.assertRaises(ValueError):
            self.sidecar.append(10000, bad)
        bad_source = full_a(10000, "WRONG-SOURCE")
        bad_source["date_source"] = "official_10000"
        with self.assertRaises(ValueError):
            self.sidecar.append(10000, bad_source)
        no_a = full_a(10000, "NOT-FULL-A")
        no_a["ability_detail"]["batter_stats"] = []
        with self.assertRaisesRegex(ValueError, "full inning"):
            self.sidecar.append(10000, no_a)
        self.assertFalse(self.v2_file.exists())

    def test_source_payload_and_calendar_digest_corruption_fail_closed(self):
        self.sidecar.append(10000, full_a(10000, "ONE"))
        self.sidecar.seal_year(10000, expected_match_count=1)
        with sqlite3.connect(self.v2_file) as con:
            con.execute(
                "UPDATE v2_option_a_matches SET record_sha256='TAMPER'"
                " WHERE match_id='ONE'"
            )
        before = file_sha256(self.v2_file)
        with self.assertRaisesRegex(CareerV2MatchConflict, "checksum differs"):
            self.sidecar.day_matches("G10000:04-01")
        self.assertEqual(before, file_sha256(self.v2_file))
        with sqlite3.connect(self.v2_file) as con:
            con.execute(
                "UPDATE v2_option_a_matches SET record_sha256="
                " (SELECT record_sha256 FROM v2_option_a_matches LIMIT 1)"
                " WHERE 0"
            )
            con.execute(
                "UPDATE v2_option_a_matches SET record_sha256='TAMPER2'"
                " WHERE match_id='ONE'"
            )
        with self.assertRaisesRegex(CareerV2MatchConflict, "checksum differs"):
            self.sidecar.seal_year(10000, expected_match_count=1)

    def test_sealed_count_mismatch_ledger_and_calendar_tamper_rejected(self):
        self.sidecar.append(10000, full_a(10000, "ONE"))
        with self.assertRaisesRegex(CareerV2MatchConflict, "count differs"):
            self.sidecar.seal_year(10000, expected_match_count=2)
        self.sidecar.seal_year(10000, expected_match_count=1)
        with sqlite3.connect(self.v2_file) as con:
            con.execute(
                "UPDATE v2_game_years SET ledger_sha256='BAD'"
                " WHERE year=10000"
            )
        with self.assertRaisesRegex(CareerV2MatchConflict, "ledger changed"):
            self.sidecar.year_matches(10000)

    def test_existing_legacy_archive_unchanged_and_duplicate_id_refused(self):
        self.calendar.record(explicit_sandbox_plan(
            2026, {COMP: ["04-01"]},
            approved_for_fictional_game=True,
        ))
        original = full_a(2026, "LEGACY-ONE")
        original["match_date"] = "2026-04-01"
        original["date_source"] = "synthetic"
        original.pop("game_day_token")
        old = HistoricalMatchArchive(self.legacy_file)
        old.sync(
            year=2026, rng_seed=17,
            resolver_contract="legacy_v1",
            plan_fingerprint="test-original",
            completed=[original],
        )
        old.seal_year(2026, expected_match_count=1)
        legacy_sha = file_sha256(self.legacy_file)
        with self.assertRaisesRegex(CareerV2MatchConflict, "duplicated"):
            self.sidecar.append(2026, full_a(2026, "LEGACY-ONE"))
        self.assertEqual(legacy_sha, file_sha256(self.legacy_file))
        self.sidecar.append(10000, full_a(10000, "FUTURE-A"))
        self.sidecar.seal_year(10000, expected_match_count=1)
        self.assertEqual(legacy_sha, file_sha256(self.legacy_file))
        self.assertIsNotNone(old.get_match(2026, COMP, "LEGACY-ONE"))

    def test_calendar_sha_tamper_rejected_without_writing_source(self):
        self.sidecar.append(10000, full_a(10000, "ONE"))
        with sqlite3.connect(self.calendar_file) as con:
            con.execute(
                "UPDATE sandbox_year_plans SET content_sha256='BAD' "
                "WHERE game_year=10000"
            )
        before = file_sha256(self.v2_file)
        with self.assertRaisesRegex(ValueError, "digest differs"):
            self.sidecar.year_matches(10000)
        self.assertEqual(before, file_sha256(self.v2_file))

    def test_bad_pages_and_missing_sidecar_no_auto_creation_on_read(self):
        with self.assertRaises(FileNotFoundError):
            self.sidecar.year_matches(10000)
        self.assertFalse(self.v2_file.exists())
        self.sidecar.append(10000, full_a(10000, "ONE"))
        for args in (
            {"limit": 0}, {"limit": 101}, {"limit": True},
            {"offset": -1}, {"offset": False},
        ):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    self.sidecar.year_matches(10000, **args)
        with self.assertRaises(CareerV2MatchConflict):
            self.sidecar.day_matches("G10000:04-03")


if __name__ == "__main__":
    unittest.main()
