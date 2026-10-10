from __future__ import annotations

from datetime import date
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from phase2_engine.historical_match_archive import (
    HistoricalMatchArchive, HistoricalMatchConflictError,
)
from phase2_engine.live_game_service import LiveGameService
from phase2_engine.save_slots import SaveSlotManager
from phase2_engine.year_transition import (
    require_year_end, year_end_readiness, YearTransitionBlockedError,
)


def completed_record(*, match_id="M1", score=2):
    return {
        "competition_id": "CMP-A", "match_id": match_id,
        "competition_name": "夏大会", "match_date": "2026-07-10",
        "date_source": "official_schedule",
        "completed_on": "2026-07-10",
        "status": "completed", "stage_code": "MAIN", "phase_code": "F",
        "round_no": 1, "round_name": "決勝",
        "team1_id": "S1", "team1_name": "第一",
        "team2_id": "S2", "team2_name": "第二",
        "team1_score": score, "team2_score": 1,
        "winner_id": "S1", "loser_id": "S2",
        "score_source": "generated_v1",
    }


class YearEndState:
    def __init__(self, year=2026, at_end=True, statuses=None, pending=0, gaps=0, matches=1):
        self.year = year
        self.rng_seed = 1405
        self.current_date = date(year, 12, 31) if at_end else date(year, 12, 30)
        self.status_by_competition = (
            {"CMP-A": "completed"} if statuses is None else statuses
        )
        self.competitions = {
            "CMP-A": SimpleNamespace(
                summary=lambda: {
                    "calendar_gap_count": gaps,
                    "pending_match_count": pending,
                },
                matches={},
            )
        }
        self._match_count = matches

    def completed_results(self):
        return {str(i): {"id": i} for i in range(self._match_count)}

    def summary(self):
        return {"year": self.year}


class Stage43DCareerYearBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "slot" / "historical_matches.sqlite3"
        self.archive = HistoricalMatchArchive(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def _sync(self, year=2026, rows=(), *, seed=21, fp=None):
        return self.archive.sync(
            year=year, rng_seed=seed,
            resolver_contract="match_v1",
            plan_fingerprint=fp or f"plan{year}",
            completed=rows,
        )

    def _register(self, year=2027, *, seed=22, fp=None):
        return self.archive.register_next_year(
            year=year, rng_seed=seed, resolver_contract="match_v1",
            plan_fingerprint=fp or f"plan{year}",
        )

    def test_adjacent_year_reuses_match_keys_without_erasing_history(self):
        self._sync(rows=[completed_record()])
        result = self.archive.seal_year(2026, expected_match_count=1)
        self.assertFalse(result["already_sealed"])
        self.assertTrue(self.archive.seal_year(2026, expected_match_count=1)["already_sealed"])
        self.assertTrue(self._register()["registered"])
        self.assertFalse(self._register()["registered"])
        self.assertEqual(
            {"inserted": 1, "already_archived": 0},
            self._sync(2027, [completed_record(score=3)], seed=22),
        )
        self.assertEqual(2, self.archive.get_match(2026, "CMP-A", "M1")["team1_score"])
        self.assertEqual(3, self.archive.get_match(2027, "CMP-A", "M1")["team1_score"])
        self.assertEqual(
            [(2026, "sealed"), (2027, "active")],
            [(y["year"], y["status"]) for y in self.archive.list_years()],
        )
        self.assertEqual(
            {"inserted": 0, "already_archived": 1},
            self._sync(2026, [completed_record()]),
        )

    def test_sealed_year_cannot_gain_new_matches_or_be_rewritten(self):
        self._sync(rows=[completed_record()])
        self.archive.seal_year(2026, expected_match_count=1)
        with self.assertRaisesRegex(HistoricalMatchConflictError, "sealed"):
            self._sync(rows=[completed_record(), completed_record(match_id="M2")])
        with self.assertRaisesRegex(HistoricalMatchConflictError, "changed"):
            self._sync(rows=[completed_record(score=5)])
        self.assertEqual(1, len(self.archive.list_matches(2026)))

    def test_skip_unsealed_and_unregistered_years_are_blocked(self):
        self._sync(rows=[completed_record()])
        with self.assertRaisesRegex(HistoricalMatchConflictError, "previous year"):
            self._register()
        with self.assertRaisesRegex(HistoricalMatchConflictError, "previous year"):
            self._register(2028)
        with self.assertRaisesRegex(HistoricalMatchConflictError, "identity"):
            self._sync(2027, [completed_record()], seed=22)
        self.archive.seal_year(2026, expected_match_count=1)
        with self.assertRaisesRegex(HistoricalMatchConflictError, "previous year"):
            self._register(2028)
        self._register()
        with self.assertRaisesRegex(HistoricalMatchConflictError, "identity"):
            self._sync(2027, [completed_record()], seed=999)
        with self.assertRaisesRegex(HistoricalMatchConflictError, "identity"):
            self._register(seed=23)

    def test_seal_requires_exact_archived_count(self):
        self._sync(rows=[completed_record()])
        with self.assertRaisesRegex(HistoricalMatchConflictError, "expected"):
            self.archive.seal_year(2026, expected_match_count=2)
        self.assertEqual("active", self.archive.list_years()[0]["status"])
        self.assertEqual(1, len(self.archive.list_matches(2026)))

    def test_empty_complete_season_can_seal_and_start_next_year(self):
        self._sync()
        self.assertEqual(0, self.archive.seal_year(2026, expected_match_count=0)["match_count"])
        self._register()
        self.assertEqual(0, len(self.archive.list_matches(2027)))

    def test_unfinished_calendar_and_date_block_seal(self):
        state = YearEndState(at_end=False, pending=3, gaps=2,
                             statuses={"CMP-A": "active"})
        result = year_end_readiness(state)
        self.assertFalse(result["eligible_to_seal"])
        self.assertEqual(
            {
                "current_date_not_year_end",
                "unfinished_or_blocked_competitions",
                "calendar_gaps_present",
                "scheduled_matches_pending",
            },
            set(result["blockers"]),
        )
        with self.assertRaises(YearTransitionBlockedError):
            require_year_end(state)

    def test_all_competitions_complete_on_dec31_passes_seal_gate(self):
        state = YearEndState()
        status = require_year_end(state)
        self.assertTrue(status["eligible_to_seal"])
        self.assertEqual(2027, status["next_year"])
        self.assertFalse(status["next_year_runtime_available"])
        self.assertEqual(1, status["completed_match_count"])

    def test_non_activated_competitions_block_seal(self):
        state = YearEndState(statuses={
            "CMP-A": "completed",
            "CMP-B": "waiting_dependencies",
        })
        readiness = year_end_readiness(state)
        self.assertIn("not_all_competitions_activated", readiness["blockers"])
        self.assertIn("unfinished_or_blocked_competitions", readiness["blockers"])

    def test_service_finalization_saves_then_seals_and_is_repeatable(self):
        self._sync(rows=[completed_record()])
        svc = LiveGameService.__new__(LiveGameService)
        svc.slots = SaveSlotManager(Path(self.temp.name) / "saves")
        # Use the matching archive path for the service facade.
        svc._history_archive = lambda slot_id: self.archive
        session = SimpleNamespace(slot_id="slot", state=YearEndState(),
                                  plan=object(), resolver_contract="match_v1")
        with patch.object(svc, "save_game", return_value={"kind": "manual"}) as save:
            first = svc.finalize_season(session)
            repeat = svc.finalize_season(session)
        self.assertEqual(2, save.call_count)
        self.assertFalse(first["archive"]["already_sealed"])
        self.assertTrue(repeat["archive"]["already_sealed"])
        self.assertFalse(first["next_year_gameplay_started"])
        self.assertEqual(2026, svc.career_history_years("slot")[0]["year"])

    def test_service_never_saves_when_incomplete(self):
        self._sync(rows=[completed_record()])
        svc = LiveGameService.__new__(LiveGameService)
        svc.slots = SaveSlotManager(Path(self.temp.name) / "saves")
        session = SimpleNamespace(slot_id="slot",
                                  state=YearEndState(at_end=False), plan=object())
        with patch.object(svc, "save_game") as save:
            with self.assertRaises(YearTransitionBlockedError):
                svc.finalize_season(session)
            save.assert_not_called()

    def test_old_stage43c_archive_without_year_table_migrates_non_destructively(self):
        self._sync(rows=[completed_record()])
        with sqlite3.connect(self.db) as conn:
            conn.execute("DROP TABLE career_years")
            original = conn.execute(
                "SELECT record_sha256 FROM historical_matches"
            ).fetchone()[0]
        self._sync(rows=[completed_record()])
        self.assertEqual("active", self.archive.list_years()[0]["status"])
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(
                original,
                conn.execute(
                    "SELECT record_sha256 FROM historical_matches"
                ).fetchone()[0],
            )


if __name__ == "__main__":
    unittest.main()
