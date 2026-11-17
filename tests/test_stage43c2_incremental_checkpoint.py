"""まとめて進めるときの自動セーブは、止まったときと月が替わったとき（履歴を先に書く）。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.live_game_service import LiveGameService
from phase2_engine.save_slots import SaveSlotManager


def completed_game(match_id: str, played_on: date) -> SimpleNamespace:
    return SimpleNamespace(
        competition_id="CMP-1", competition_name="夏季大会",
        match_id=match_id, match_date=played_on.isoformat(),
        date_source="official_schedule", completed_on=played_on.isoformat(),
        status="completed", stage_code="MAIN", phase_code="MAIN",
        round_no=1, round_name="1回戦", group_id="", group_name="",
        team1_id="SCH-1", team1_name="第一",
        team2_id="SCH-2", team2_name="第二",
        team1_score=4, team2_score=3,
        winner_id="SCH-1", loser_id="SCH-2",
        score_source="generated_v1", ability_detail=None,
    )


class DeterministicCalendarState:
    """Small replayable calendar used only to verify service save boundaries."""

    def __init__(self):
        self.year = 2026
        self.rng_seed = 42
        self.current_date = date(2026, 7, 10)
        self.competitions = {"CMP-1": SimpleNamespace(matches={})}
        self.game_days = {
            date(2026, 7, 10): "M1",
            date(2026, 7, 12): "M2",
            date(2026, 7, 20): "M3",
        }

    def play_today(self) -> list[dict]:
        match_id = self.game_days.get(self.current_date)
        if match_id is None:
            return []
        records = self.competitions["CMP-1"].matches
        if match_id in records:
            return []
        records[match_id] = completed_game(match_id, self.current_date)
        return [{"match_id": match_id}]

    def next_day(self) -> dict:
        current = self.current_date
        newly_played = self.play_today()
        self.current_date += timedelta(days=1)
        return {
            "from_date": current.isoformat(),
            "to_date": self.current_date.isoformat(),
            "played_match_count": len(newly_played),
        }

    def advance_to(self, target: str) -> dict:
        end = date.fromisoformat(target)
        if end.year != self.year or end < self.current_date:
            raise ValueError("invalid target")
        days = 0
        played = 0
        while self.current_date < end:
            row = self.next_day()
            days += 1
            played += row["played_match_count"]
        return {"current_date": self.current_date.isoformat(),
                "advanced_days": days, "played_match_count": played}

    def advance_through(self, target: str) -> dict:
        result = self.advance_to(target)
        result["played_match_count"] += len(self.play_today())
        result["processed_through"] = self.current_date.isoformat()
        return result


class Stage43C2IncrementalCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = LiveGameService.__new__(LiveGameService)
        self.service.slots = SaveSlotManager(Path(self.tmp.name) / "saves")
        self.service.autosave_after_action = True
        self.state = DeterministicCalendarState()
        self.session = SimpleNamespace(
            slot_id="career", state=self.state,
            resolver_contract="deterministic_test", plan=object(),
        )
        self.archive = HistoricalMatchArchive(
            self.service.slots.slot_dir("career") / "historical_matches.sqlite3"
        )
        self.save_points = []

    def tearDown(self):
        self.tmp.cleanup()

    def _save_checkpoint(self, *args, **kwargs):
        count = len(self.state.competitions["CMP-1"].matches)
        self.save_points.append((self.state.current_date.isoformat(), count))
        return {"kind": kwargs.get("kind"), "payload_checksum": "fake-json-checksum"}

    def test_long_jump_saves_once_when_it_stops(self):
        with patch("phase2_engine.live_game_service.plan_fingerprint",
                   return_value="plan123"):
            with patch.object(self.service.slots, "save",
                              side_effect=self._save_checkpoint):
                result = self.service.advance_to(self.session, "2026-07-24")
                again = self.service.advance_to(self.session, "2026-07-24")
        self.assertEqual(14, result["advanced_days"])
        self.assertEqual(3, result["played_match_count"])
        # 月が替わらなければ、止まったときに1回
        self.assertEqual(
            [("2026-07-24", 3), ("2026-07-24", 3)],
            self.save_points,
        )
        self.assertEqual(3, result["autosave"]["historical_archive"]["inserted"])
        # 保存済みの試合は送り直さない（増分だけ履歴へ）
        self.assertEqual(0, again["autosave"]["historical_archive"]["inserted"])
        self.assertEqual(0, again["autosave"]["historical_archive"]["already_archived"])
        self.assertEqual(3, len(self.archive.list_matches(2026)))

    def test_long_jump_also_saves_when_the_month_changes(self):
        with patch("phase2_engine.live_game_service.plan_fingerprint",
                   return_value="plan123"):
            with patch.object(self.service.slots, "save",
                              side_effect=self._save_checkpoint):
                result = self.service.advance_to(self.session, "2026-09-03")
        self.assertEqual(3, result["played_match_count"])
        # 8月1日・9月1日になったときと、止まったとき
        self.assertEqual(
            [("2026-08-01", 3), ("2026-09-01", 3), ("2026-09-03", 3)],
            self.save_points,
        )
        # 月の保存で履歴に書いた試合は、あとの保存で送り直さない
        self.assertEqual({"inserted": 0, "already_archived": 0},
                         result["autosave"]["historical_archive"])
        self.assertEqual(3, len(self.archive.list_matches(2026)))

    def test_stopping_on_the_first_of_the_month_saves_once(self):
        with patch("phase2_engine.live_game_service.plan_fingerprint",
                   return_value="plan123"):
            with patch.object(self.service.slots, "save",
                              side_effect=self._save_checkpoint):
                result = self.service.advance_to(self.session, "2026-08-01")
        self.assertEqual([("2026-08-01", 3)], self.save_points)
        self.assertEqual(3, result["autosave"]["historical_archive"]["inserted"])

    def test_month_change_does_not_save_when_autosave_is_off(self):
        with patch.object(self.service, "autosave_game",
                          side_effect=AssertionError("must not save")):
            result = self.service.advance_to(
                self.session, "2026-08-05", autosave=False, on_day=lambda step: None,
            )
        self.assertIsNone(result["autosave"])
        self.assertTrue(self.session.unsaved_progress)

    def test_history_is_written_before_the_json_save(self):
        seen = []

        def json_save(*args, **kwargs):
            seen.append([r["match_id"] for r in self.archive.list_matches(2026)])
            return self._save_checkpoint(*args, **kwargs)

        with patch("phase2_engine.live_game_service.plan_fingerprint",
                   return_value="plan123"):
            with patch.object(self.service.slots, "save", side_effect=json_save):
                self.service.advance_to(self.session, "2026-07-24")
        self.assertEqual([["M1", "M2", "M3"]], seen)

    def test_crash_on_json_save_keeps_history_and_next_save_adds_nothing(self):
        with patch("phase2_engine.live_game_service.plan_fingerprint",
                   return_value="plan123"):
            with patch.object(self.service.slots, "save",
                              side_effect=OSError("simulated disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    self.service.advance_to(self.session, "2026-07-24")
            # 履歴は先に書いてある。JSONの保存をやり直しても試合は増えない
            self.assertEqual(["M1", "M2", "M3"], [r["match_id"] for r in
                                                 self.archive.list_matches(2026)])
            with patch.object(self.service.slots, "save",
                              side_effect=self._save_checkpoint):
                retried = self.service.save_game(self.session)
        self.assertEqual({"inserted": 0, "already_archived": 0},
                         retried["historical_archive"])
        self.assertEqual([("2026-07-24", 3)], self.save_points)
        self.assertEqual(3, len(self.archive.list_matches(2026)))

    def test_replay_after_crash_resends_the_same_matches_without_conflict(self):
        """JSONより履歴が先に進んだまま落ちた場合：前の状態から進め直すと同じ試合になり、
        履歴は同じ内容として受け入れる（増やさない・書き換えない）。"""
        with patch("phase2_engine.live_game_service.plan_fingerprint",
                   return_value="plan123"):
            with patch.object(self.service.slots, "save",
                              side_effect=OSError("simulated power loss")):
                with self.assertRaises(OSError):
                    self.service.advance_to(self.session, "2026-07-24")
            # 落ちる前のセーブ（7月10日）を読み込んだのと同じ状態から進め直す
            self.state = DeterministicCalendarState()
            self.session.state = self.state
            with patch.object(self.service.slots, "save",
                              side_effect=self._save_checkpoint):
                replayed = self.service.advance_to(self.session, "2026-07-24")
        self.assertEqual({"inserted": 0, "already_archived": 3},
                         replayed["autosave"]["historical_archive"])
        self.assertEqual(["M1", "M2", "M3"], [r["match_id"] for r in
                                             self.archive.list_matches(2026)])

    def test_through_target_checkpoints_target_game_in_final_save(self):
        with patch("phase2_engine.live_game_service.plan_fingerprint",
                   return_value="plan123"):
            with patch.object(self.service.slots, "save",
                              side_effect=self._save_checkpoint):
                result = self.service.advance_through(
                    self.session, "2026-07-12",
                )
        self.assertEqual(2, result["advanced_days"])
        self.assertEqual(2, result["played_match_count"])
        self.assertEqual("2026-07-12", result["processed_through"])
        # 止まったときの1回だけ
        self.assertEqual(
            [("2026-07-12", 2)],
            self.save_points,
        )
        self.assertIsNotNone(
            self.archive.get_match(2026, "CMP-1", "M2")
        )

    def test_autosave_disabled_is_single_unsaved_runtime_jump(self):
        with patch.object(self.service, "autosave_game",
                          side_effect=AssertionError("must not save")):
            result = self.service.advance_through(
                self.session, "2026-07-12", autosave=False,
            )
        self.assertEqual(2, result["played_match_count"])
        self.assertIsNone(result["autosave"])
        self.assertFalse(self.archive.db_path.exists())

    def test_invalid_target_must_not_create_archive(self):
        with patch.object(self.service, "autosave_game") as save:
            with self.assertRaisesRegex(ValueError, "inside school year"):
                self.service.advance_to(self.session, "2027-04-01")
            with self.assertRaisesRegex(ValueError, "backward"):
                self.service.advance_to(self.session, "2026-07-09")
            save.assert_not_called()
        self.assertFalse(self.archive.db_path.exists())


if __name__ == "__main__":
    unittest.main()
