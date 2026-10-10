"""Stage43G-30: no-write cross-era route preflight and conflict tests."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from phase2_engine.career_calendar_v2 import (
    CareerCalendarV2Archive, explicit_sandbox_plan,
)
from phase2_engine.career_cross_era_read_gate import (
    CareerCrossEraConflict, CareerCrossEraReadGate,
)
from phase2_engine.career_history_scale_audit import synthetic_ability_record
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_v2_option_a_archive import CareerV2OptionAArchive
from phase2_engine.historical_match_archive import HistoricalMatchArchive

COMP = "CMP000086"
FIRST = "SCH000001"
SECOND = "SCH000002"
YEAR = 10000


class Stage43G30CrossEraReadGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old = self.root / "historical_matches.sqlite3"
        self.v2 = self.root / "fictional_option_a_v2.sqlite3"
        self.calendar = self.root / "sandbox_calendar_v2.sqlite3"
        self.legacy = HistoricalMatchArchive(self.old)
        self.future = CareerV2OptionAArchive(
            self.v2, self.calendar, legacy_archive_path=self.old,
        )
        self.gate = CareerCrossEraReadGate(
            self.old, self.v2, self.calendar,
        )

    def tearDown(self):
        self.temp.cleanup()

    def legacy_record(self):
        return synthetic_ability_record(
            2026, COMP, "OLD-2026", FIRST, SECOND, 1,
        )

    def future_record(self, year=YEAR, mid="FUTURE", day="04-01"):
        row = synthetic_ability_record(
            year, COMP, mid, FIRST, SECOND, int(day[-2:]),
        )
        row.pop("match_date")
        row["completed_on"] = ""
        row["game_day_token"] = f"G{year}:{day}"
        row["date_source"] = "fictional_v2_day_slot"
        return row

    def save_old(self, *, seal=True):
        self.legacy.sync(
            year=2026, rng_seed=17, resolver_contract="stage43g30_test",
            plan_fingerprint="stage43g30-source",
            completed=[self.legacy_record()],
        )
        if seal:
            self.legacy.seal_year(2026, expected_match_count=1)

    def save_future(self, year=YEAR, *, seal=True, mid="FUTURE"):
        CareerCalendarV2Archive(self.calendar).record(
            explicit_sandbox_plan(
                year, {COMP: ["04-01", "04-02"]},
                approved_for_fictional_game=True,
            )
        )
        self.future.append(year, self.future_record(year, mid))
        if seal:
            self.future.seal_year(year, expected_match_count=1)

    def test_separate_source_routes_and_deep_audit_do_not_modify_sources(self):
        self.save_old()
        self.save_future()
        paths = (self.old, self.v2, self.calendar)
        before = [file_sha256(p) for p in paths]
        manifest = self.gate.inspect([2026, YEAR])
        self.assertEqual(["YYYY-MM-DD", "G{year}:MM-DD"], [
            r["date_kind"] for r in manifest["routes"]
        ])
        self.assertEqual([2026, YEAR], manifest["requested_years"])
        self.assertEqual(
            [{"from_year": 2027, "through_year": 9999}],
            manifest["unverified_intervening_year_intervals"],
        )
        self.assertFalse(manifest["selected_years_are_contiguous"])
        self.assertFalse(manifest["combined_career_stats_authorized"])
        self.assertFalse(manifest["future_tournament_runtime_authorized"])
        self.assertTrue(self.gate.inspect(
            [2026, YEAR], verify_source=True,
        )["source_payloads_rechecked"])
        self.assertEqual(before, [file_sha256(p) for p in paths])

    def test_one_source_only_with_missing_other_does_not_create_db(self):
        self.save_future()
        result = self.gate.inspect([YEAR])
        self.assertEqual("fictional_option_a_v2", result["routes"][0]["source"])
        self.assertTrue(result["selected_years_are_contiguous"])
        self.assertFalse(self.old.exists())

    def test_legacy_only_and_unsaved_requested_year_rejected(self):
        self.save_old()
        self.assertEqual(
            "historical_matches_legacy_iso",
            self.gate.inspect([2026])["routes"][0]["source"],
        )
        with self.assertRaisesRegex(CareerCrossEraConflict, "not saved"):
            self.gate.inspect([2026, YEAR])
        self.assertFalse(self.v2.exists())
        self.assertFalse(self.calendar.exists())

    def test_unsealed_old_and_unsealed_v2_rejected(self):
        self.save_old(seal=False)
        with self.assertRaisesRegex(CareerCrossEraConflict, "not sealed"):
            self.gate.inspect([2026])
        self.legacy.seal_year(2026, expected_match_count=1)
        self.save_future(seal=False)
        with self.assertRaisesRegex(CareerCrossEraConflict, "not sealed"):
            self.gate.inspect([2026, YEAR])

    def test_overlap_even_outside_selection_rejected(self):
        self.save_old()
        self.save_future()
        self.save_future(year=2026, mid="DUPLICATE-ERA")
        with self.assertRaisesRegex(CareerCrossEraConflict, "overlapping years"):
            self.gate.inspect([YEAR])

    def test_v2_year_in_legacy_era_rejected_alone(self):
        self.save_future(year=2027)
        with self.assertRaisesRegex(
            CareerCrossEraConflict, "Gregorian legacy calendar era"
        ):
            self.gate.inspect([2027])

    def test_legacy_year_beyond_9999_rejected(self):
        self.save_old()
        with sqlite3.connect(self.old) as conn:
            conn.execute("UPDATE career_years SET year=10000 WHERE year=2026")
        with self.assertRaisesRegex(CareerCrossEraConflict, "beyond 9999"):
            self.gate.inspect([YEAR])

    def test_tampered_sealed_legacy_ledger_detected(self):
        self.save_old()
        with sqlite3.connect(self.old) as conn:
            conn.execute(
                "UPDATE historical_matches SET record_sha256='BAD' "
                "WHERE match_id='OLD-2026'"
            )
        with self.assertRaisesRegex(CareerCrossEraConflict, "ledger differs"):
            self.gate.inspect([2026])

    def test_deep_legacy_detects_payload_tamper_not_fast_claim(self):
        self.save_old()
        with sqlite3.connect(self.old) as conn:
            conn.execute(
                "UPDATE historical_matches SET payload_json=payload_json || ' ' "
                "WHERE match_id='OLD-2026'"
            )
        self.assertFalse(self.gate.inspect([2026])[
            "source_payloads_rechecked"
        ])
        with self.assertRaisesRegex(CareerCrossEraConflict, "SHA differs"):
            self.gate.inspect([2026], verify_source=True)

    def test_v2_sealed_ledger_and_payload_tamper_detected(self):
        self.save_future()
        with sqlite3.connect(self.v2) as conn:
            conn.execute(
                "UPDATE v2_option_a_matches SET record_sha256='BAD' "
                "WHERE match_id='FUTURE'"
            )
        with self.assertRaisesRegex(CareerCrossEraConflict, "ledger differs"):
            self.gate.inspect([YEAR])

    def test_deep_v2_detects_payload_tamper(self):
        self.save_future()
        with sqlite3.connect(self.v2) as conn:
            conn.execute(
                "UPDATE v2_option_a_matches SET payload_json=payload_json || ' ' "
                "WHERE match_id='FUTURE'"
            )
        self.assertFalse(self.gate.inspect([YEAR])["source_payloads_rechecked"])
        with self.assertRaisesRegex(CareerCrossEraConflict, "validation failed"):
            self.gate.inspect([YEAR], verify_source=True)

    def test_calendar_provenance_conflict(self):
        self.save_future()
        with sqlite3.connect(self.calendar) as conn:
            conn.execute(
                "UPDATE sandbox_year_plans SET content_sha256='BAD' "
                "WHERE game_year=?", (YEAR,),
            )
        with self.assertRaisesRegex(CareerCrossEraConflict, "validation failed"):
            self.gate.inspect([YEAR])

    def test_invalid_year_list_no_write(self):
        for years in ([], [True], [0], [YEAR, 2026], [2026, 2026], "2026"):
            with self.subTest(years=years):
                with self.assertRaises(ValueError):
                    self.gate.inspect(years)
        with self.assertRaises(ValueError):
            self.gate.inspect([2026], verify_source=1)
        self.assertFalse(self.old.exists())
        self.assertFalse(self.v2.exists())

    def test_reject_duplicate_source_file_paths(self):
        with self.assertRaisesRegex(ValueError, "separate"):
            CareerCrossEraReadGate(self.old, self.old, self.calendar)


if __name__ == "__main__":
    unittest.main()
