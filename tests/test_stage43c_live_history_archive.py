from __future__ import annotations

import sqlite3
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
        with sqlite3.connect(self.path) as conn:
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
