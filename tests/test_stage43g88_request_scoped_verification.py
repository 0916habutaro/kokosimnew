"""Single-call proofs, exact result contract and deterministic WAL drift."""
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_v2_national_storage_audit import (
    audit_fixture, synthetic_storage_fixture,
)
from phase2_engine.career_v2_school_century_shards import (
    build_v2_school_century_shards, read_v2_school_century_page,
)
from phase2_engine import career_v2_school_read_index as reader

DATA = Path(__file__).resolve().parents[1] / "data"


class Stage43G88RequestTests(unittest.TestCase):
    def fixture(self, **kwargs):
        f = self.enterContext(synthetic_storage_fixture(DATA, schools=4, **kwargs))
        made = build_v2_school_century_shards(f.source, f.calendar,
            start_year=f.years[0], end_year=f.years[-1])
        return f, [Path(s["index_path"]) for s in made["shards"]]

    def read(self, f, indexes, **kwargs):
        return read_v2_school_century_page(f.source, f.calendar, indexes,
            f.schools[0], start_year=f.years[0], end_year=f.years[-1], **kwargs)

    def test_one_scan_per_year_and_index_even_when_page_crosses_century(self):
        f, indexes = self.fixture(years=2, rounds=34, first_year=10099)
        with patch.object(reader, "_verify_index_years", wraps=reader._verify_index_years) as years, \
             patch.object(reader, "_source_checked_header", wraps=reader._source_checked_header) as headers, \
             patch.object(reader, "_verify_match", wraps=reader._verify_match) as matches:
            result = self.read(f, indexes, verify_scope="selected_years", offset=30)
            self.assertEqual(68, result["total"])
            self.assertEqual([10099] * 4 + [10100] * 26,
                             [r["year"] for r in result["records"]])
            self.assertEqual(2, years.call_count)
            self.assertEqual(2, headers.call_count)
            self.assertEqual(136, matches.call_count)  # all schools, once

    def test_independent_oracle_filters_zero_school_last_and_past_end(self):
        f, indexes = self.fixture(years=2, rounds=34, first_year=10099)
        before = {p: file_sha256(p) for p in (f.source, f.calendar, f.legacy, *indexes)}
        self.assertEqual(36, audit_fixture(f, indexes, repeats=1)["verified_page_calls"])
        for scope in ("page", "selected_years"):
            self.assertEqual(8, len(self.read(f, indexes, offset=60, verify_scope=scope)["records"]))
            self.assertEqual([], self.read(f, indexes, offset=100, verify_scope=scope)["records"])
        self.assertEqual(before, {p: file_sha256(p) for p in before})

    def test_zero_school_still_verifies_all_source_and_membership_rows(self):
        f, indexes = self.fixture(years=2, rounds=3)
        with patch.object(reader, "_verify_match", wraps=reader._verify_match) as matches:
            result = read_v2_school_century_page(f.source, f.calendar, indexes, "ZERO88",
                start_year=f.years[0], end_year=f.years[-1], verify_scope="selected_years")
            self.assertEqual((0, []), (result["total"], result["records"]))
            self.assertEqual(12, matches.call_count)

    def test_no_proof_survives_next_request(self):
        f, indexes = self.fixture(years=1, rounds=3)
        self.read(f, indexes, verify_scope="selected_years")
        with sqlite3.connect(f.source) as db:
            db.execute("UPDATE v2_option_a_matches SET payload_json='{}' WHERE match_id=("
                       "SELECT match_id FROM v2_option_a_matches WHERE "
                       "json_extract(payload_json,'$.team1_id')!=? AND "
                       "json_extract(payload_json,'$.team2_id')!=? LIMIT 1)",
                       (f.schools[0], f.schools[0]))
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.read(f, indexes, verify_scope="selected_years")

    def test_forged_hidden_index_sha_and_membership_digest_fail_closed(self):
        for sql in ("UPDATE school_game SET record_sha256='FALSE88' WHERE rowid=(SELECT MAX(rowid) FROM school_game)",
                    "UPDATE indexed_year SET memberships_sha256='FALSE88'"):
            with self.subTest(sql=sql):
                f, indexes = self.fixture(years=1, rounds=3)
                with sqlite3.connect(indexes[0]) as db:
                    db.execute(sql)
                before = {p: file_sha256(p) for p in (f.source, f.calendar, f.legacy, *indexes)}
                with self.assertRaises(ValueError):
                    self.read(f, indexes, verify_scope="selected_years", offset=100)
                self.assertEqual(before, {p: file_sha256(p) for p in before})

    def test_page_keeps_limited_offpage_meaning(self):
        f, indexes = self.fixture(years=1, rounds=3)
        with sqlite3.connect(f.source) as db:
            db.execute("UPDATE v2_option_a_matches SET payload_json='{}' WHERE match_id=("
                       "SELECT match_id FROM v2_option_a_matches WHERE "
                       "json_extract(payload_json,'$.team1_id')!=? AND "
                       "json_extract(payload_json,'$.team2_id')!=? LIMIT 1)",
                       (f.schools[0], f.schools[0]))
        self.assertFalse(self.read(f, indexes)["all_selected_year_payloads_verified"])
        with self.assertRaises(ValueError):
            self.read(f, indexes, verify_scope="selected_years")

    def test_wal_commit_between_count_and_display_rejected_for_each_file(self):
        for scope in ("page", "selected_years"):
            for kind in ("source", "calendar", "index"):
                with self.subTest(scope=scope, kind=kind):
                    f, indexes = self.fixture(years=1, rounds=3)
                    target = {
                        "source": f.source,
                        "calendar": f.calendar,
                        "index": indexes[0],
                    }[kind]
                    with closing(sqlite3.connect(target)) as db:
                        self.assertEqual("wal", db.execute("PRAGMA journal_mode=WAL").fetchone()[0])
                        db.execute("CREATE TABLE drift_probe (n INTEGER)")
                        db.commit()
                    original = reader._VerifiedSchoolSlice.page
                    calls = []
                    def interleave(verified, *args):
                        result = original(verified, *args)
                        if not calls:
                            with closing(sqlite3.connect(target)) as db:
                                db.execute("INSERT INTO drift_probe VALUES (1)")
                                db.commit()
                        calls.append(1)
                        return result
                    with patch.object(reader._VerifiedSchoolSlice, "page", interleave):
                        with self.assertRaisesRegex(ValueError, "changed during school read"):
                            self.read(f, indexes, verify_scope=scope)
                    self.assertEqual(2, len(calls))
                    # A later, independent request has no stale watcher/proof.
                    self.assertEqual(3, self.read(f, indexes, verify_scope=scope)["total"])

    def test_wal_snapshot_keeps_count_and_display_on_verified_source_and_index(self):
        for kind in ("source", "index"):
            with self.subTest(kind=kind):
                f, indexes = self.fixture(years=1, rounds=3)
                target = f.source if kind == "source" else indexes[0]
                with closing(sqlite3.connect(target)) as db:
                    db.execute("PRAGMA journal_mode=WAL")
                original = reader._VerifiedSchoolSlice.page
                results = []
                def corrupt(verified, *args):
                    result = original(verified, *args)
                    if not results:
                        with closing(sqlite3.connect(target)) as db:
                            if kind == "source":
                                db.execute("UPDATE v2_option_a_matches SET payload_json='{}'")
                            else:
                                db.execute("DELETE FROM school_game")
                            db.commit()
                    results.append(result)
                    return result
                with patch.object(reader._VerifiedSchoolSlice, "page", corrupt):
                    with self.assertRaisesRegex(ValueError, "changed during school read"):
                        self.read(f, indexes, verify_scope="selected_years")
                self.assertEqual([3, 3], [r["total"] for r in results])
                self.assertEqual(3, len(results[1]["records"]))

    def test_calendar_snapshot_pins_later_year_during_verification(self):
        f, indexes = self.fixture(years=2, rounds=3)
        with closing(sqlite3.connect(f.calendar)) as db:
            db.execute("PRAGMA journal_mode=WAL")
        original = reader._SnapshotCalendar.read
        years = []
        def corrupt(calendar, year):
            plan = original(calendar, year)
            if not years:
                with closing(sqlite3.connect(f.calendar)) as db:
                    db.execute("UPDATE sandbox_year_plans SET content_sha256='BAD88' WHERE game_year=?",
                               (f.years[-1],))
                    db.commit()
            years.append(year)
            return plan
        with patch.object(reader._SnapshotCalendar, "read", corrupt):
            with self.assertRaisesRegex(ValueError, "changed during school read"):
                self.read(f, indexes, verify_scope="selected_years")
        self.assertEqual(list(f.years), years)

    def test_index_file_replacement_between_count_and_display_rejected(self):
        f, indexes = self.fixture(years=1, rounds=3)
        copy = indexes[0].with_name("replacement.sqlite3")
        shutil.copyfile(indexes[0], copy)
        original = reader._VerifiedSchoolSlice.page
        calls = []
        def replace(verified, *args):
            result = original(verified, *args)
            if not calls:
                copy.replace(indexes[0])
            calls.append(1)
            return result
        with patch.object(reader._VerifiedSchoolSlice, "page", replace):
            with self.assertRaisesRegex(ValueError, "changed during school read"):
                self.read(f, indexes, verify_scope="selected_years")

    def test_standalone_reader_also_checks_wal_index_drift(self):
        f, indexes = self.fixture(years=1, rounds=3)
        with closing(sqlite3.connect(indexes[0])) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE drift_probe (n INTEGER)")
            db.commit()
        original = reader._VerifiedSchoolSlice.page
        def commit(verified, *args):
            result = original(verified, *args)
            with closing(sqlite3.connect(indexes[0])) as db:
                db.execute("INSERT INTO drift_probe VALUES (1)")
                db.commit()
            return result
        with patch.object(reader._VerifiedSchoolSlice, "page", commit):
            with self.assertRaisesRegex(ValueError, "changed during school read"):
                reader.read_indexed_v2_school_page(f.source, f.calendar, indexes[0],
                    f.schools[0], start_year=f.years[0], end_year=f.years[-1])


if __name__ == "__main__":
    unittest.main()
