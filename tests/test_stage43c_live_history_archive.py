from __future__ import annotations

import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from phase2_engine.historical_match_archive import (
    HistoricalMatchArchive,
    HistoricalMatchConflictError,
)
from phase2_engine.live_game_service import LiveGameService
from phase2_engine.save_slots import SaveSlotManager


def make_record(match_id="M1", *, score=4, ability=True) -> dict:
    row = {
        "competition_id": "CMP-1", "competition_name": "夏季大会",
        "match_id": match_id,
        "match_date": "2026-07-12", "date_source": "official_schedule",
        "completed_on": "2026-07-12", "status": "completed",
        "stage_code": "MAIN", "phase_code": "FINAL",
        "round_no": 1, "round_name": "決勝",
        "group_id": "", "group_name": "",
        "team1_id": "SCH-1", "team1_name": "第一",
        "team2_id": "SCH-2", "team2_name": "第二",
        "team1_score": score, "team2_score": 3,
        "winner_id": "SCH-1" if score > 3 else "SCH-2",
        "loser_id": "SCH-2" if score > 3 else "SCH-1",
        "score_source": "ability_model_v1" if ability else "generated_v1",
    }
    if ability:
        row["ability_detail"] = {
            "reference_year": 2026, "competition_id": "CMP-1",
            "match_id": match_id, "score_source": "ability_model_v1",
            "team1_school_id": "SCH-1", "team2_school_id": "SCH-2",
            "team1_score": score, "team2_score": 3,
            "last_inning": 1, "ending_half": "bottom",
            "inning_scores": [
                {"inning": 1, "half": "top", "batting_team_id": "SCH-1",
                 "was_played": True, "runs": score},
                {"inning": 1, "half": "bottom", "batting_team_id": "SCH-2",
                 "was_played": True, "runs": 3},
            ],
            "team_stats": [
                {"school_id": "SCH-1", "runs": score, "hits": 5, "errors": 0},
                {"school_id": "SCH-2", "runs": 3, "hits": 4, "errors": 1},
            ],
            "batter_stats": [
                {"player_id": "P1", "school_id": "SCH-1", "hits": 2,
                 "runs": 1, "at_bats": 4, "rbi": 1},
            ],
            "pitcher_stats": [
                {"player_id": "P2", "school_id": "SCH-2", "outs_recorded": 3,
                 "hits_allowed": 5},
            ],
            "events": [{"event_no": 1, "event_type": "single"}],
        }
    return row


class Stage43CHistoricalArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "slot" / "historical_matches.sqlite3"
        self.archive = HistoricalMatchArchive(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def sync(self, rows, **overrides):
        args = {
            "year": 2026, "rng_seed": 42,
            "resolver_contract": "deterministic_test",
            "plan_fingerprint": "plan123", "completed": rows,
        }
        args.update(overrides)
        return self.archive.sync(**args)

    def test_ability_game_roundtrip_omits_all_plate_appearances(self):
        first = self.sync([make_record()])
        self.assertEqual({"inserted": 1, "already_archived": 0}, first)
        payload = self.archive.get_match(2026, "CMP-1", "M1")
        self.assertEqual(4, payload["team1_score"])
        self.assertEqual(4, payload["inning_scores"][0]["runs"])
        self.assertEqual(5, payload["team_stats"][0]["hits"])
        self.assertEqual(2, payload["batter_stats"][0]["hits"])
        self.assertEqual(3, payload["pitcher_stats"][0]["outs_recorded"])
        self.assertNotIn("events", payload)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            raw = conn.execute(
                "SELECT payload_json FROM historical_matches"
            ).fetchone()[0]
            self.assertNotIn('"events"', raw)

    def test_repeat_is_idempotent_even_after_reopen(self):
        self.sync([make_record()])
        self.assertEqual(
            {"inserted": 0, "already_archived": 1},
            HistoricalMatchArchive(self.path).sync(
                year=2026, rng_seed=42, resolver_contract="deterministic_test",
                plan_fingerprint="plan123", completed=[make_record()],
            ),
        )
        self.assertEqual(1, len(self.archive.list_matches(2026)))

    def test_finished_competition_is_packed_and_reads_the_same(self):
        rows = [make_record(f"M{i}") for i in range(1, 4)]
        self.sync(rows)
        before = [self.archive.get_match(2026, "CMP-1", f"M{i}") for i in range(1, 4)]
        listed = self.archive.list_matches(2026)
        self.assertEqual(3, self.archive.pack_competition(2026, "CMP-1"))
        self.assertEqual({"CMP-1"}, self.archive.packed_competitions(2026))
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(
                [("",)] * 3,
                conn.execute("SELECT payload_json FROM historical_matches").fetchall(),
            )
        reopened = HistoricalMatchArchive(self.path)
        self.assertEqual(
            before, [reopened.get_match(2026, "CMP-1", f"M{i}") for i in range(1, 4)],
        )
        self.assertEqual(listed, reopened.list_matches(2026))
        # まとめたあとも同じ試合の再保存はそのまま通り、年度の封印も同じ
        self.assertEqual({"inserted": 0, "already_archived": 3}, self.sync(rows))
        self.assertEqual(0, self.archive.pack_competition(2026, "CMP-1"))
        self.assertEqual(3, self.archive.seal_year(2026, expected_match_count=3)["match_count"])

    def test_reads_wait_while_the_file_is_locked_for_vacuum(self):
        """年度を閉じるときの VACUUM の間に画面（別のスレッド）が読みに来ても、
        エラーにせず待って読む。"""
        import threading
        import time

        self.sync([make_record(f"M{i}") for i in range(1, 4)])
        self.archive.pack_competition(2026, "CMP-1")
        expected = self.archive.get_match(2026, "CMP-1", "M2")
        locked = threading.Event()

        def hold():
            with closing(sqlite3.connect(self.path)) as conn:
                conn.execute("BEGIN EXCLUSIVE")  # VACUUM と同じ排他ロック
                locked.set()
                time.sleep(1.0)
                conn.rollback()

        holder = threading.Thread(target=hold)
        holder.start()
        locked.wait()
        started = time.monotonic()
        from phase2_engine import historical_match_archive as archive_module

        archive_module._PACKED_CACHE.clear()
        self.assertEqual(expected, HistoricalMatchArchive(self.path).get_match(2026, "CMP-1", "M2"))
        self.assertGreater(time.monotonic() - started, 0.5)
        holder.join()
        # 本物の VACUUM と読み込みを同時に何度も
        errors = []

        def read_many():
            for _ in range(30):
                try:
                    archive_module._PACKED_CACHE.clear()
                    if HistoricalMatchArchive(self.path).get_match(2026, "CMP-1", "M2") != expected:
                        errors.append("different")
                except Exception as exc:  # noqa: BLE001
                    errors.append(repr(exc))

        reader = threading.Thread(target=read_many)
        reader.start()
        for _ in range(5):
            self.assertTrue(self.archive.vacuum())
        reader.join()
        self.assertEqual([], errors)

    def test_batch_packing_keeps_exact_existing_compression_and_reopened_records(self):
        import zlib
        from phase2_engine.historical_match_archive import _canonical

        rows = []
        for cid in ('CMP-1', 'CMP-2', 'CMP-3'):
            for number in range(2):
                row = make_record(f'M{number}')
                row['competition_id'] = row['ability_detail']['competition_id'] = cid
                rows.append(row)
        self.sync(rows)
        expected = {}
        with closing(sqlite3.connect(self.path)) as con:
            for cid in ('CMP-1', 'CMP-2', 'CMP-3'):
                payloads = dict(con.execute('SELECT match_id,payload_json FROM historical_matches WHERE competition_id=?', (cid,)))
                expected[cid] = zlib.compress(_canonical(payloads).encode('utf-8'), 9)
        before = [self.archive.get_match(2026, r['competition_id'], r['match_id']) for r in rows]
        self.assertEqual(6, self.archive.pack_competitions(2026, ('CMP-1', 'CMP-2', 'CMP-3', 'CMP-1')))
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(expected, dict(con.execute('SELECT competition_id,payloads FROM packed_competitions')))
        reopened = HistoricalMatchArchive(self.path)
        self.assertEqual(before, [reopened.get_match(2026, r['competition_id'], r['match_id']) for r in rows])
        self.assertEqual(0, self.archive.pack_competitions(2026, expected))
        self.assertEqual(6, self.archive.seal_year(2026, expected_match_count=6)['match_count'])

    def test_batch_worker_failure_rolls_back_all_packing(self):
        rows = [make_record('M1'), make_record('M2')]
        rows[1]['competition_id'] = rows[1]['ability_detail']['competition_id'] = 'CMP-2'
        self.sync(rows)
        with patch('phase2_engine.historical_match_archive.zlib.compress', side_effect=ValueError('compression failed')):
            with self.assertRaisesRegex(ValueError, 'compression failed'):
                self.archive.pack_competitions(2026, ('CMP-1', 'CMP-2'))
        self.assertEqual(set(), self.archive.packed_competitions(2026))
        self.assertEqual(4, self.archive.get_match(2026, 'CMP-1', 'M1')['team1_score'])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(2, con.execute("SELECT count(*) FROM historical_matches WHERE payload_json != ''").fetchone()[0])

    def test_corrupt_later_competition_rolls_back_prior_batch_writes(self):
        rows = []
        for cid in ('CMP-1', 'CMP-2', 'CMP-3'):
            row = make_record()
            row['competition_id'] = row['ability_detail']['competition_id'] = cid
            rows.append(row)
        self.sync(rows)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE historical_matches SET record_sha256='CORRUPT' WHERE competition_id='CMP-3'")
        with self.assertRaises(HistoricalMatchConflictError):
            self.archive.pack_competitions(2026, ('CMP-1', 'CMP-2', 'CMP-3'))
        self.assertEqual(set(), self.archive.packed_competitions(2026))
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(3, con.execute("SELECT count(*) FROM historical_matches WHERE payload_json != ''").fetchone()[0])

    def test_failed_vacuum_is_logged_and_does_not_stop_the_game(self):
        """空き容量が足りないなどで VACUUM が失敗しても、ログに残して続ける
        （次の年度を閉じるときにまた詰める）。"""
        from phase2_engine import historical_match_archive as archive_module

        self.sync([make_record()])
        real_connect = sqlite3.connect

        class _Full:
            def __init__(self, *args, **kwargs):
                self._conn = real_connect(*args, **kwargs)

            def execute(self, sql, *args):
                if sql == "VACUUM":
                    raise sqlite3.OperationalError("database or disk is full")
                return self._conn.execute(sql, *args)

            def close(self):
                self._conn.close()

        with patch.object(archive_module.sqlite3, "connect", _Full):
            with self.assertLogs(archive_module.LOGGER, "WARNING") as logs:
                self.assertFalse(self.archive.vacuum())
        self.assertIn("disk is full", logs.output[0])
        # 記録はそのまま読め、次の VACUUM は通る
        self.assertEqual(4, self.archive.get_match(2026, "CMP-1", "M1")["team1_score"])
        self.assertTrue(self.archive.vacuum())

    def test_changed_result_never_overwrites_old_record(self):
        old = make_record()
        self.sync([old])
        edited = make_record(score=5)
        with self.assertRaisesRegex(HistoricalMatchConflictError, "changed"):
            self.sync([edited])
        self.assertEqual(4, self.archive.get_match(2026, "CMP-1", "M1")["team1_score"])

    def test_batch_conflict_rolls_back_all_new_matches(self):
        self.sync([make_record()])
        different = make_record("M2")
        with self.assertRaises(HistoricalMatchConflictError):
            self.sync([different, make_record(score=5)])
        self.assertIsNone(self.archive.get_match(2026, "CMP-1", "M2"))

    def test_archive_identity_cannot_change_silently(self):
        self.sync([make_record()])
        with self.assertRaisesRegex(HistoricalMatchConflictError, "identity"):
            self.sync([make_record()], rng_seed=999)
        self.assertEqual(1, len(self.archive.list_matches(2026)))

    def test_loading_older_snapshot_does_not_erase_newer_games(self):
        self.sync([make_record(), make_record("M2")])
        self.sync([make_record()])
        self.assertEqual(2, len(self.archive.list_matches(2026)))

    def test_generated_score_only_is_preserved_without_invented_stats(self):
        record = make_record(ability=False)
        self.sync([record])
        payload = self.archive.get_match(2026, "CMP-1", "M1")
        self.assertEqual("generated_v1", payload["score_source"])
        self.assertIsNone(payload["inning_scores"])
        self.assertIsNone(payload["team_stats"])
        self.assertIsNone(payload["batter_stats"])
        self.assertIsNone(payload["pitcher_stats"])

    def test_missing_file_queries_do_not_create_any_database(self):
        self.assertIsNone(self.archive.get_match(2026, "CMP-1", "M1"))
        self.assertEqual([], self.archive.list_matches(2026))
        self.assertFalse(self.path.exists())

    def test_school_filter_and_pagination(self):
        self.sync([make_record("M3"), make_record("M1"), make_record("M2")])
        self.assertEqual(
            ["M1", "M2"], [
                x["match_id"] for x in self.archive.list_matches(
                    2026, school_id="SCH-2", limit=2
                )
            ]
        )
        self.assertEqual(
            ["M3"], [
                x["match_id"] for x in self.archive.list_matches(
                    2026, school_id="SCH-1", limit=2, offset=2
                )
            ]
        )
        self.assertEqual([], self.archive.list_matches(2027))
        with self.assertRaises(ValueError):
            self.archive.list_matches(2026, limit=5000)

    def test_invalid_line_score_is_rejected_before_creating_db(self):
        record = make_record()
        record["ability_detail"]["inning_scores"][0]["runs"] = 5
        with self.assertRaisesRegex(ValueError, "totals"):
            self.sync([record])
        self.assertFalse(self.path.exists())

    def test_duplicated_keys_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate completed"):
            self.sync([make_record(), make_record()])
        self.assertFalse(self.path.exists())

    def test_service_save_calls_history_sync_after_json_save(self):
        service = LiveGameService.__new__(LiveGameService)
        service.slots = SaveSlotManager(Path(self.temp.name) / "saves")
        match = SimpleNamespace(**make_record())
        state = SimpleNamespace(
            year=2026, rng_seed=42,
            competitions={"CMP-1": SimpleNamespace(matches={"M1": match})},
        )
        session = SimpleNamespace(
            slot_id="career", state=state, plan=object(),
            resolver_contract="deterministic_test",
        )
        with patch.object(service.slots, "save", return_value={"kind": "manual"}) as saved:
            with patch("phase2_engine.live_game_service.plan_fingerprint", return_value="plan123"):
                first = service.save_game(session)
                second = service.save_game(session)
        self.assertEqual(2, saved.call_count)
        self.assertEqual(1, first["historical_archive"]["inserted"])
        self.assertEqual(0, second["historical_archive"]["inserted"])
        self.assertEqual(1, len(service.historical_matches("career", 2026)))
        self.assertIsNotNone(service.historical_match("career", 2026, "CMP-1", "M1"))

    def test_service_does_not_archive_unsaved_action(self):
        service = LiveGameService.__new__(LiveGameService)
        service.slots = SaveSlotManager(Path(self.temp.name) / "saves")
        session = SimpleNamespace(
            slot_id="career",
            state=SimpleNamespace(year=2026, rng_seed=42, competitions={}),
            resolver_contract="test", plan=object(),
        )
        self.assertFalse(service._history_archive("career").db_path.exists())
        with patch("phase2_engine.live_game_service.plan_fingerprint", return_value="plan"):
            with patch.object(service.slots, "save", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    service.save_game(session)
        self.assertFalse(service._history_archive("career").db_path.exists())


if __name__ == "__main__":
    unittest.main()
