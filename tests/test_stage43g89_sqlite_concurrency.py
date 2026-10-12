"""Deterministic multi-file snapshots and actual append/seal races."""
from contextlib import closing
import copy
import json
import os
from pathlib import Path
import random
import shutil
import sqlite3
import threading
import tempfile
import unittest
from unittest.mock import patch

from phase2_engine.career_calendar_v2 import CareerCalendarV2Archive, explicit_sandbox_plan
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_v2_national_storage_audit import (
    COMPETITIONS, _box_score, audit_fixture, synthetic_storage_fixture,
)
from phase2_engine.career_v2_school_century_shards import (
    build_v2_school_century_shards, read_v2_school_century_page,
)
from phase2_engine.career_v2_sqlite_concurrency_audit import (
    OrderedWriter, ReadProbe, TIMEOUT, commit_probe, wal_probe,
)
from phase2_engine import career_v2_option_a_archive as archive_module
from phase2_engine import career_v2_school_read_index as reader

DATA = Path(__file__).resolve().parents[1] / "data"


class Stage43G89ConcurrencyTests(unittest.TestCase):
    def fixture(self, *, years=2, rounds=3):
        f = self.enterContext(synthetic_storage_fixture(
            DATA, schools=4, years=years, rounds=rounds, first_year=10099))
        indexes = [Path(s["index_path"]) for s in build_v2_school_century_shards(
            f.source, f.calendar, start_year=f.years[0], end_year=f.years[-1])["shards"]]
        return f, indexes

    def read(self, f, indexes, scope="selected_years", **kwargs):
        return read_v2_school_century_page(f.source, f.calendar, indexes,
            f.schools[0], start_year=10099, end_year=10100,
            verify_scope=scope, **kwargs)

    def oracle(self, f, result, *, competition=None, offset=0):
        expected = [r for r in f.expected[f.schools[0]]
                    if competition is None or r["competition_id"] == competition]
        self.assertEqual(len(expected), result["total"])
        actual = [{k: row[k] for k in expected[0]} for row in result["records"]] if expected else []
        self.assertEqual(expected[offset:offset + 30], actual)
        for row in result["records"]:
            self.assertTrue(row["full_option_a_original_retained"])

    def probe_read(self, f, indexes, target, boundary, action, *, scope="selected_years"):
        original = reader._read_only
        fired = []
        def hook(probe, sql, when):
            if fired or probe.path != target:
                return
            hit = (
                boundary == "snapshot_" + when and sql.startswith("SELECT name FROM sqlite_master")
                or boundary == "watcher_" + when and sql == "PRAGMA data_version" and probe.versions == 2
                or boundary == "count_after" and sql.startswith("SELECT COUNT(*) FROM school_game") and when == "after"
            )
            if hit:
                fired.append(boundary)
                writer.run()
        with OrderedWriter(action) as writer, patch.object(reader, "_read_only",
                lambda path: ReadProbe(original(path), path, hook)):
            try:
                result = self.read(f, indexes, scope)
            except reader.CareerV2ReadIndexConflict:
                result = None
        self.assertEqual([boundary], fired)
        if result is not None:
            self.oracle(f, result)
        return result

    def test_wal_before_and_after_each_snapshot_fail_closed(self):
        # 2 verification modes x 4 files x 2 exact pin boundaries = 16 schedules.
        for scope in ("page", "selected_years"):
            for pos in range(4):
                for boundary in ("snapshot_before", "snapshot_after"):
                    with self.subTest(scope=scope, file=pos, boundary=boundary):
                        f, indexes = self.fixture()
                        target = (f.source, f.calendar, *indexes)[pos]
                        wal_probe(target)
                        self.assertIsNone(self.probe_read(f, indexes, target, boundary,
                            lambda: commit_probe(target), scope=scope))

    def test_commit_between_connection_and_prepare_fail_closed(self):
        for pos in range(4):
            with self.subTest(file=pos):
                f, indexes = self.fixture()
                target = (f.source, f.calendar, *indexes)[pos]
                wal_probe(target)
                original = reader._SchoolReadRequest.prepare
                calls = []
                def interleave(request, *args):
                    if not calls:
                        calls.append(1)
                        writer.run()
                    return original(request, *args)
                with OrderedWriter(lambda: commit_probe(target)) as writer, \
                        patch.object(reader._SchoolReadRequest, "prepare", interleave):
                    with self.assertRaises(reader.CareerV2ReadIndexConflict):
                        self.read(f, indexes)

    def test_count_to_page_commit_keeps_pinned_data_but_rejects_result(self):
        for scope in ("page", "selected_years"):
            for pos in range(2):
                with self.subTest(scope=scope, index=pos):
                    f, indexes = self.fixture(rounds=34)
                    target = indexes[pos]
                    wal_probe(target)
                    self.assertIsNone(self.probe_read(f, indexes, target, "count_after",
                        lambda: commit_probe(target), scope=scope))

    def test_watcher_before_rejects_and_after_returns_coherent_old_snapshot(self):
        # Commits after a file's LAST observation need not be detected.
        for pos in range(4):
            for boundary in ("watcher_before", "watcher_after"):
                with self.subTest(file=pos, boundary=boundary):
                    f, indexes = self.fixture()
                    target = (f.source, f.calendar, *indexes)[pos]
                    wal_probe(target)
                    result = self.probe_read(f, indexes, target, boundary,
                        lambda: commit_probe(target))
                    self.assertEqual(boundary == "watcher_after", result is not None)

    def test_rename_after_snapshot_and_before_watcher_rejects_every_file(self):
        for pos in range(4):
            for boundary in ("snapshot_after", "watcher_before"):
                with self.subTest(file=pos, boundary=boundary):
                    f, indexes = self.fixture()
                    target = (f.source, f.calendar, *indexes)[pos]
                    replacement = target.with_name("replacement89.sqlite3")
                    shutil.copyfile(target, replacement)
                    old = target.stat().st_ino
                    self.assertIsNone(self.probe_read(f, indexes, target, boundary,
                        lambda: os.replace(replacement, target)))
                    self.assertNotEqual(old, target.stat().st_ino)

    def test_wal_checkpoint_does_not_change_content_generation(self):
        for pos in range(4):
            with self.subTest(file=pos):
                f, indexes = self.fixture()
                target = (f.source, f.calendar, *indexes)[pos]
                wal_probe(target)
                commit_probe(target)
                checkpoints = []
                def checkpoint():
                    with closing(sqlite3.connect(target, timeout=TIMEOUT)) as db:
                        checkpoints.append(db.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone())
                self.assertIsNotNone(self.probe_read(f, indexes, target,
                    "snapshot_after", checkpoint))
                self.assertEqual(0, checkpoints[0][0])

    def test_real_staged_calendar_append_seal_and_new_index(self):
        f, indexes = self.fixture(years=1)
        empty = f.source.parent / "fictional_v2_school_read_index_G10100_G10199_empty.sqlite3"
        reader.build_v2_school_read_index(f.source, f.calendar, empty,
                                        start_year=10100, end_year=10199)
        indexes.append(empty)
        plan = explicit_sandbox_plan(10100, {COMPETITIONS[0]: ["04-01"]},
                                     approved_for_fictional_game=True)
        CareerCalendarV2Archive(f.calendar).record(plan)
        self.oracle(f, self.read(f, indexes))  # unused calendar year is harmless
        row = _box_score(10100, "NEW89", COMPETITIONS[0], *f.schools[:2],
                         "04-01", random.Random(89))
        f.archive.append(10100, row)
        with self.assertRaisesRegex(ValueError, "unsealed"):
            self.read(f, indexes)
        f.archive.seal_year(10100, expected_match_count=1)
        with self.assertRaisesRegex(ValueError, "exact saved"):
            self.read(f, indexes)  # stale immutable index cannot omit the new year
        fresh = empty.with_name("fictional_v2_school_read_index_G10100_G10199_new.sqlite3")
        reader.build_v2_school_read_index(f.source, f.calendar, fresh,
                                        start_year=10100, end_year=10199)
        result = self.read(f, [indexes[0], fresh])
        self.assertEqual(4, result["total"])
        self.assertEqual({"year": 10100, "competition_id": COMPETITIONS[0],
            "match_id": "NEW89", "game_day_token": "G10100:04-01",
            "school_id": f.schools[0], "opponent_school_id": f.schools[1],
            "runs_for": row["team1_score"], "runs_against": row["team2_score"],
            "result_for_school": "win" if row["team1_score"] > row["team2_score"] else "loss"},
            {k: result["records"][-1][k] for k in f.expected[f.schools[0]][0]})
        with closing(sqlite3.connect(empty)) as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM indexed_year").fetchone()[0])

    def test_actual_calendar_append_and_seal_mid_request_rejected(self):
        for stage in ("calendar", "append", "seal"):
            with self.subTest(stage=stage):
                f, indexes = self.fixture(years=1)
                plan = explicit_sandbox_plan(10100, {COMPETITIONS[0]: ["04-01"]},
                                             approved_for_fictional_game=True)
                row = _box_score(10100, "LIVE89", COMPETITIONS[0], *f.schools[:2],
                                 "04-01", random.Random(89))
                if stage != "calendar":
                    CareerCalendarV2Archive(f.calendar).record(plan)
                if stage == "seal":
                    f.archive.append(10100, row)
                target = f.calendar if stage == "calendar" else f.source
                wal_probe(target)
                action = {
                    "calendar": lambda: CareerCalendarV2Archive(f.calendar).record(plan),
                    "append": lambda: f.archive.append(10100, row),
                    "seal": lambda: f.archive.seal_year(10100, expected_match_count=1),
                }[stage]
                # Query sealed 10099 only; the writer changes a different year.
                original = reader._VerifiedSchoolSlice.page
                calls = []
                def interleave(verified, *args):
                    result = original(verified, *args)
                    if not calls:
                        calls.append(1)
                        writer.run()
                    return result
                with OrderedWriter(action) as writer, patch.object(reader._VerifiedSchoolSlice, "page", interleave):
                    with self.assertRaises(reader.CareerV2ReadIndexConflict):
                        reader.read_indexed_v2_school_page(f.source, f.calendar, indexes[0],
                            f.schools[0], start_year=10099, end_year=10099)

    def test_stable_two_century_30_zero_filters_and_sha(self):
        f, indexes = self.fixture(rounds=34)
        before = {p: file_sha256(p) for p in (f.source, f.calendar, f.legacy, *indexes)}
        self.assertEqual(36, audit_fixture(f, indexes, repeats=1)["verified_page_calls"])
        for scope in ("page", "selected_years"):
            for cid in (None, *COMPETITIONS):
                for offset in (0, 30, 60, 100):
                    self.oracle(f, self.read(f, indexes, scope, competition_id=cid, offset=offset),
                                competition=cid, offset=offset)
        self.assertEqual(before, {p: file_sha256(p) for p in before})

    def test_build_observed_wal_source_or_calendar_drift_not_published(self):
        for kind in ("source", "calendar"):
            with self.subTest(file=kind):
                f, indexes = self.fixture()
                target = f.source if kind == "source" else f.calendar
                wal_probe(target)
                destination = f.source.parent / "building89.sqlite3"
                original = reader._verify_match
                calls = []
                def interleave(*args):
                    value = original(*args)
                    if not calls:
                        calls.append(1)
                        writer.run()
                    return value
                with OrderedWriter(lambda: commit_probe(target)) as writer, \
                        patch.object(reader, "_verify_match", interleave):
                    with self.assertRaises(reader.CareerV2ReadIndexConflict):
                        reader.build_v2_school_read_index(f.source, f.calendar, destination,
                            start_year=10099, end_year=10100)
                self.assertFalse(destination.exists())
                self.assertEqual([], list(f.source.parent.glob(".v2-school-index-*")))

    def test_build_existing_target_race_never_overwrites(self):
        f, indexes = self.fixture()
        destination = f.source.parent / "target89.sqlite3"
        original = reader.os.link
        def preempt(source, target):
            destination.write_bytes(b"independent approved target89")
            return original(source, target)
        with patch.object(reader.os, "link", preempt):
            with self.assertRaises(FileExistsError):
                reader.build_v2_school_read_index(f.source, f.calendar, destination,
                    start_year=10099, end_year=10100)
        self.assertEqual(b"independent approved target89", destination.read_bytes())
        self.assertEqual([], list(f.source.parent.glob(".v2-school-index-*")))

    def test_stage_update_after_all_watchers_can_return_old_coherent_result(self):
        f, indexes = self.fixture()
        wal_probe(f.source)
        plan = explicit_sandbox_plan(10101, {COMPETITIONS[0]: ["04-01"]},
                                     approved_for_fictional_game=True)
        CareerCalendarV2Archive(f.calendar).record(plan)
        row = _box_score(10101, "AFTER89", COMPETITIONS[0], *f.schools[:2],
                         "04-01", random.Random(89))
        original = reader._SchoolReadRequest.check_unchanged
        calls = []
        def interleave(request):
            original(request)
            calls.append(1)
            writer.run()
        with OrderedWriter(lambda: f.archive.append(10101, row)) as writer, \
                patch.object(reader._SchoolReadRequest, "check_unchanged", interleave):
            self.oracle(f, self.read(f, indexes))
        self.assertEqual(1, len(calls))

    def test_staged_raw_source_calendar_index_updates_refuse_mixed_success(self):
        # Deliberately violates append-only/sealed policy; not a save API.
        for updated in (1, 2, 3):
            with self.subTest(committed_files=updated):
                f, indexes = self.fixture()
                paths = (f.calendar, f.source, indexes[-1])
                def corrupt():
                    statements = (
                        "DELETE FROM sandbox_year_plans WHERE game_year=10100",
                        "DELETE FROM v2_option_a_matches WHERE year=10100",
                        "DELETE FROM school_game WHERE year=10100",
                    )
                    for path, sql in zip(paths[:updated], statements):
                        with closing(sqlite3.connect(path, timeout=TIMEOUT)) as db:
                            db.execute(sql)
                            db.commit()
                for p in paths: wal_probe(p)
                self.assertIsNone(self.probe_read(f, indexes, indexes[0],
                    "snapshot_after", corrupt))

    def test_rollback_journal_blocks_commit_until_read_scope_closes(self):
        f, indexes = self.fixture()
        target = indexes[0]
        original = reader._SchoolReadRequest.prepare
        outcomes = []
        def locked_writer():
            with closing(sqlite3.connect(target, timeout=0)) as db:
                db.execute("UPDATE meta SET schema_version=schema_version")
                try: db.commit()
                except sqlite3.OperationalError as exc:
                    self.assertIn("locked", str(exc))
                    db.rollback()
                    outcomes.append("busy_rolled_back")
                else: raise AssertionError("rollback journal commit unexpectedly passed read lock")
        def interleave(request, *args):
            if not outcomes: writer.run()
            return original(request, *args)
        with OrderedWriter(locked_writer) as writer, patch.object(reader._SchoolReadRequest, "prepare", interleave):
            self.oracle(f, self.read(f, indexes))
        self.assertEqual(["busy_rolled_back"], outcomes)
        with closing(sqlite3.connect(target, timeout=0)) as db:
            db.execute("UPDATE meta SET schema_version=schema_version")
            db.commit()

    def active(self):
        f, _ = self.fixture(years=1)
        year = 10100
        CareerCalendarV2Archive(f.calendar).record(explicit_sandbox_plan(
            year, {COMPETITIONS[0]: ["04-01"]}, approved_for_fictional_game=True))
        rows = [_box_score(year, f"RACE89-{i}", COMPETITIONS[0], *f.schools[:2],
                           "04-01", random.Random(89 + i)) for i in range(2)]
        f.archive.append(year, rows[0])
        wal_probe(f.source)
        return f, year, rows

    def assert_seal_oracle(self, f, year):
        # Independent raw-row oracle, not the production _ledger verifier.
        import hashlib
        with closing(sqlite3.connect(f.source)) as db:
            header = db.execute("SELECT status,match_count,ledger_sha256 FROM v2_game_years WHERE year=?", (year,)).fetchone()
            rows = db.execute("SELECT competition_id,match_id,record_sha256 FROM v2_option_a_matches WHERE year=? ORDER BY competition_id,match_id", (year,)).fetchall()
        digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
        self.assertEqual(("sealed", len(rows), digest), header)
        return len(rows)

    def test_append_during_seal_cannot_invalidate_committed_ledger(self):
        f, year, rows = self.active()
        original = archive_module._ledger
        reached, attempted = threading.Event(), threading.Event()
        release = threading.Event()
        results = {}
        def ledger(db, selected):
            value = original(db, selected)
            if threading.current_thread().name == "seal89":
                reached.set()
                if not release.wait(TIMEOUT):
                    raise TimeoutError("seal release timed out")
            return value
        def seal():
            try: results["seal"] = f.archive.seal_year(year, expected_match_count=1)
            except BaseException as exc: results["seal_error"] = exc
        connect = sqlite3.connect
        def traced_connect(*args, **kwargs):
            db = connect(*args, **kwargs)
            if threading.current_thread().name == "append89":
                def trace(sql):
                    # Fixed version waits at BEGIN IMMEDIATE. Baseline commits.
                    if sql == "BEGIN IMMEDIATE": attempted.set()
                db.set_trace_callback(trace)
            return db
        def append():
            try: results["append"] = f.archive.append(year, rows[1])
            except BaseException as exc: results["append_error"] = exc
            finally: attempted.set()
        with patch.object(archive_module, "_ledger", ledger), patch.object(sqlite3, "connect", traced_connect):
            a = threading.Thread(target=seal, name="seal89", daemon=True)
            b = threading.Thread(target=append, name="append89", daemon=True)
            a.start()
            try:
                self.assertTrue(reached.wait(TIMEOUT))
                b.start()
                self.assertTrue(attempted.wait(TIMEOUT))
            finally:
                release.set()
                a.join(TIMEOUT)
                if b.ident is not None: b.join(TIMEOUT)
        self.assertFalse(a.is_alive() or b.is_alive())
        self.assertNotIn("seal_error", results)
        self.assertEqual(1, self.assert_seal_oracle(f, year))
        self.assertIsInstance(results.get("append_error"), archive_module.CareerV2MatchConflict)
        self.assertNotIn("append", results)

    def test_seal_after_append_status_check_cannot_be_overtaken(self):
        f, year, rows = self.active()
        reached, attempted, release = (threading.Event() for _ in range(3))
        results = {}
        connect = sqlite3.connect
        def traced_connect(*args, **kwargs):
            db = connect(*args, **kwargs)
            name = threading.current_thread().name
            if name in ("append89", "seal89"):
                def trace(sql):
                    if name == "append89" and sql.startswith("SELECT * FROM v2_option_a_matches WHERE year="):
                        reached.set()
                        if not release.wait(TIMEOUT):
                            results["trace_timeout"] = True
                    elif name == "seal89" and sql == "BEGIN IMMEDIATE":
                        attempted.set()
                db.set_trace_callback(trace)
            return db
        def append():
            try: results["append"] = f.archive.append(year, rows[1])
            except BaseException as exc: results["append_error"] = exc
        def seal():
            try: results["seal"] = f.archive.seal_year(year, expected_match_count=1)
            except BaseException as exc: results["seal_error"] = exc
            finally: attempted.set()
        with patch.object(sqlite3, "connect", traced_connect):
            a = threading.Thread(target=append, name="append89", daemon=True)
            b = threading.Thread(target=seal, name="seal89", daemon=True)
            a.start()
            try:
                self.assertTrue(reached.wait(TIMEOUT))
                b.start()
                self.assertTrue(attempted.wait(TIMEOUT))
            finally:
                release.set()
                a.join(TIMEOUT)
                if b.ident is not None: b.join(TIMEOUT)
        self.assertFalse(a.is_alive() or b.is_alive())
        self.assertNotIn("trace_timeout", results)
        self.assertNotIn("append_error", results)
        self.assertIsInstance(results.get("seal_error"), archive_module.CareerV2MatchConflict)
        with closing(sqlite3.connect(f.source)) as db:
            self.assertEqual("active", db.execute("SELECT status FROM v2_game_years WHERE year=?", (year,)).fetchone()[0])
        f.archive.seal_year(year, expected_match_count=2)
        self.assertEqual(2, self.assert_seal_oracle(f, year))

    def test_simultaneous_same_match_is_idempotent_and_conflicting_match_rejected(self):
        for conflicting in (False, True):
            with self.subTest(conflicting=conflicting):
                f, year, rows = self.active()
                second = copy.deepcopy(rows[1])
                if conflicting:
                    second["ability_detail"]["batter_stats"][0]["hits"] += 1
                gate = threading.Barrier(2, timeout=TIMEOUT)
                outcomes = []
                def append(row):
                    try:
                        gate.wait()
                        outcomes.append(f.archive.append(year, row))
                    except BaseException as exc:
                        outcomes.append(exc)
                a = threading.Thread(target=append, args=(rows[1],), daemon=True)
                b = threading.Thread(target=append, args=(second,), daemon=True)
                a.start(); b.start(); a.join(TIMEOUT); b.join(TIMEOUT)
                self.assertFalse(a.is_alive() or b.is_alive())
                if conflicting:
                    self.assertEqual(1, sum(isinstance(x, archive_module.CareerV2MatchConflict) for x in outcomes))
                else:
                    self.assertEqual([False, True], sorted(x["inserted"] for x in outcomes))
                f.archive.seal_year(year, expected_match_count=2)
                self.assertEqual(2, self.assert_seal_oracle(f, year))

    def test_separate_save_selection_does_not_transfer_index_proofs(self):
        from phase2_engine.career_history_slot_session import CareerHistorySlotSession
        from phase2_engine.career_v2_school_game_tk import CareerV2SchoolGamePager
        f, indexes = self.fixture()
        root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="stage89-slots-")))
        for name in ("slot-a", "slot-b"):
            slot = root / name
            slot.mkdir()
            for path in (f.source, f.calendar, f.legacy):
                shutil.copyfile(path, slot / path.name)
        session = CareerHistorySlotSession(root, "slot-a")
        first = session.bridge
        session.select("slot-b")
        self.assertIsNot(first, session.bridge)
        self.assertEqual("slot-b", session.slot_id)
        foreign = root / "slot-b" / indexes[0].name
        shutil.copyfile(indexes[0], foreign)
        pager = CareerV2SchoolGamePager(root / "slot-b" / f.source.name,
            root / "slot-b" / f.calendar.name, f.schools[0], 10099)
        old = pager.page
        with self.assertRaises(ValueError):
            pager.select_century_shards([foreign.name], start_year=10099, end_year=10099)
        self.assertIs(old, pager.page)
        self.assertEqual("original_json1", pager.lookup_mode)


@unittest.skipUnless(os.environ.get("DISPLAY"), "real Tk/Xvfb display required")
class Stage43G89TkConcurrencyTests(unittest.TestCase):
    def test_real_tk_wal_rejection_preserves_page_filters_and_manual_indexes(self):
        import tkinter as tk
        from phase2_engine.career_v2_school_game_tk import CareerV2SchoolGamePager
        from phase2_engine.career_legacy_school_game_tk import CareerLegacySchoolGamesTkPilot
        with synthetic_storage_fixture(DATA, schools=4, years=2, rounds=34,
                                       first_year=10099) as f:
            indexes = [Path(s["index_path"]) for s in build_v2_school_century_shards(
                f.source, f.calendar, start_year=10099, end_year=10100)["shards"]]
            wal_probe(indexes[-1])
            pager = CareerV2SchoolGamePager(f.source, f.calendar, f.schools[0], 10099)
            root = tk.Tk()
            root.withdraw()
            try:
                window = CareerLegacySchoolGamesTkPilot(root, pager)
                window.start_var.set("10099"); window.end_var.set("10100")
                window.scope_var.set("selected_years")
                window.century_files_var.set(" ".join(p.name for p in indexes))
                window.century_apply_button.invoke()
                self.assertIsNone(window.last_error)
                window.next_button.invoke()
                self.assertEqual(30, pager.offset)
                old_page = pager.page
                old_rows = copy.deepcopy(window.rows_by_widget_id)
                old_paths = pager.century_index_paths
                original = reader._VerifiedSchoolSlice.page
                calls = []
                def interleave(verified, *args):
                    result = original(verified, *args)
                    if not calls:
                        calls.append(1)
                        writer.run()
                    return result
                with OrderedWriter(lambda: commit_probe(indexes[-1])) as writer, \
                        patch.object(reader._VerifiedSchoolSlice, "page", interleave):
                    window.next_button.invoke()
                root.update()
                self.assertIn("changed during school read", window.last_error)
                self.assertIs(old_page, pager.page)
                self.assertEqual(old_rows, window.rows_by_widget_id)
                self.assertEqual((30, 10099, 10100, "selected_years"),
                    (pager.offset, pager.start_year, pager.end_year, pager.verify_scope))
                self.assertEqual(old_paths, pager.century_index_paths)
                self.assertEqual("century_shards", pager.lookup_mode)
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
