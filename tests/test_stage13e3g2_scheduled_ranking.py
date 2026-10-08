from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from datetime import date

from phase2_engine import DataRepository
from phase2_engine.browse_repository import BrowseRepository
from phase2_engine.competition_schedule_runtime import ScheduledCompetitionRuntime
from phase2_engine.live_season_dependency import LiveSeasonDependencyRuntimeState
from phase2_engine.post_qualification_ranking import RankingOnlyEventRuntime
from phase2_engine.post_qualification_schedule import ScheduledRankingSidecar


DATA = Path(__file__).resolve().parents[1] / "data"


def sidecar(mode="semifinal_final", *, fmt="FMT022"):
    event = RankingOnlyEventRuntime.create(
        competition_id="CMP000162" if fmt == "FMT022" else "CMP000112",
        stage_id="STG000206" if fmt == "FMT022" else "STG000183",
        stage_code="SEED_EVENT" if fmt == "FMT022" else "BRANCH_QUALIFIER",
        group_id="SGR000184" if fmt == "FMT022" else "SGR000106",
        format_model_id=fmt,
        mode=mode,
        locked_school_ids=["A", "B", "C", "D"],
        pairings=(("A", "D"), ("B", "C")),
    )
    return ScheduledRankingSidecar.create(
        event,
        qualification_locked_on="2026-08-12",
        match_dates=["2026-08-13", "2026-08-14"]
        if mode == "semifinal_final" else ["2026-08-13"],
    )


class CompletedMainRuntime:
    is_complete = True


class Stage13E3G2ScheduledRankingTests(unittest.TestCase):
    def test_fmt022_rounds_are_dated_and_not_eager(self):
        event = sidecar()
        self.assertEqual(2, len(event.matches_for_date("2026-08-13")))
        self.assertEqual([], event.matches_for_date("2026-08-14"))
        first = event.matches_for_date("2026-08-13")
        winners = {first[0]["match_id"]: "A", first[1]["match_id"]: "B"}
        result = event.resolve_date(
            "2026-08-13", winners,
            scores={first[0]["match_id"]: (5, 2),
                    first[1]["match_id"]: (3, 1)},
        )
        self.assertEqual(2, len(result))
        self.assertEqual({"A", "B"}, {
            key for r in event.matches_for_date("2026-08-14")
            for key in (r["team1_id"], r["team2_id"])
        })
        self.assertFalse(event.is_complete)
        final = event.matches_for_date("2026-08-14")[0]
        event.resolve_date("2026-08-14", {final["match_id"]: "B"})
        self.assertTrue(event.is_complete)
        self.assertEqual(("A", "B", "C", "D"), event.event.locked_school_ids)

    def test_requires_verified_dates_after_qualification(self):
        event = sidecar().event
        for dates, lock in (
            ([], "2026-08-12"),
            (["2026-08-13", "2026-08-13"], "2026-08-12"),
            (["2026-08-14", "2026-08-13"], "2026-08-12"),
            (["2026-08-12", "2026-08-14"], "2026-08-12"),
            (["invalid", "2026-08-14"], "2026-08-12"),
        ):
            with self.subTest(dates=dates, lock=lock):
                with self.assertRaises(ValueError):
                    ScheduledRankingSidecar.create(
                        event, qualification_locked_on=lock, match_dates=dates,
                    )

    def test_unfinished_event_can_be_canceled_without_losing_seeds(self):
        event = sidecar()
        first = event.matches_for_date("2026-08-13")[0]
        event.cancel_remaining()
        self.assertTrue(event.is_complete)
        self.assertEqual("canceled", event.matches_for_date("2026-08-13")[0]["status"])
        with self.assertRaisesRegex(ValueError, "canceled"):
            event.resolve_date("2026-08-13", {first["match_id"]: "A"})
        self.assertEqual(["A", "B", "C", "D"],
                         event.event.ranking_metadata()["locked_qualifiers"])

    def test_snapshot_restores_partial_ranking_and_next_wave(self):
        event = sidecar()
        first = event.matches_for_date("2026-08-13")
        event.resolve_date(
            "2026-08-13",
            {first[0]["match_id"]: "A", first[1]["match_id"]: "B"},
        )
        stored = json.loads(json.dumps(event.snapshot()))
        resumed = ScheduledRankingSidecar.from_snapshot(stored)
        self.assertEqual(stored, resumed.snapshot())
        self.assertEqual(1, len(resumed.matches_for_date("2026-08-14")))
        future = resumed.matches_for_date("2026-08-14")[0]
        resumed.resolve_date("2026-08-14", {future["match_id"]: "B"})
        self.assertTrue(resumed.is_complete)

    def test_wrong_date_or_unqualified_winner_rejected_atomically(self):
        event = sidecar()
        first = event.matches_for_date("2026-08-13")
        with self.assertRaises(ValueError):
            event.resolve_date(
                "2026-08-13",
                {first[0]["match_id"]: "A", first[1]["match_id"]: "NOT_SEEDED"},
            )
        self.assertEqual({}, event.event.results)
        with self.assertRaises(ValueError):
            event.resolve_date(
                "2026-08-12", {first[0]["match_id"]: "A"},
            )
        self.assertEqual({}, event.event.results)

    def test_scores_must_match_winner_and_nonnegative(self):
        event = sidecar()
        first = event.matches_for_date("2026-08-13")
        winners = {first[0]["match_id"]: "A", first[1]["match_id"]: "B"}
        with self.assertRaises(ValueError):
            event.resolve_date(
                "2026-08-13", winners,
                scores={first[0]["match_id"]: (1, 9)},
            )
        self.assertEqual({}, event.event.results)
        with self.assertRaises(ValueError):
            event.resolve_date(
                "2026-08-13", winners,
                scores={first[0]["match_id"]: (-1, 2)},
            )

    def test_main_scheduler_exposes_sidecar_but_remains_complete(self):
        repo = DataRepository(DATA)
        scheduled = ScheduledCompetitionRuntime(
            repo=repo,
            runtime=CompletedMainRuntime(),
            competition_id="CMP000162",
            competition_name="沖縄秋",
            calendar_dates=[],
            stage_date_lists={},
            calendar_status="official_schedule",
        )
        self.assertTrue(scheduled.is_complete)
        event = sidecar()
        scheduled.attach_ranking_sidecar(event)
        self.assertEqual(2, len(scheduled.matches_for_date("2026-08-13")))
        self.assertTrue(scheduled.is_complete)
        first = scheduled.ranking_matches_for_date("2026-08-13")
        scheduled.resolve_ranking_date(
            "2026-08-13",
            winners_by_group={"SGR000184": {
                first[0]["match_id"]: "A", first[1]["match_id"]: "B",
            }},
        )
        self.assertTrue(scheduled.is_complete)
        self.assertEqual(1, len(scheduled.matches_for_date("2026-08-14")))
        restored = ScheduledCompetitionRuntime(
            repo=repo, runtime=CompletedMainRuntime(),
            competition_id="CMP000162", competition_name="沖縄秋",
            calendar_dates=[], stage_date_lists={},
            calendar_status="official_schedule",
        )
        restored.restore_ranking_snapshot(
            json.loads(json.dumps(scheduled.ranking_snapshot()))
        )
        self.assertEqual(scheduled.ranking_snapshot(),
                         restored.ranking_snapshot())
        self.assertTrue(restored.is_complete)

    def test_sqlite_sidecar_save_restore_date_and_competition_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = BrowseRepository(Path(directory) / "season.sqlite3")
            event = sidecar()
            saved = repo.save_ranking_sidecar(2026, event)
            self.assertEqual(2, saved["match_count"])
            self.assertEqual(2, len(repo.ranking_matches_on_date(
                2026, "2026-08-13", competition_id="CMP000162",
            )))
            self.assertEqual([], repo.ranking_matches_on_date(
                2026, "2026-08-13", competition_id="CMP000140",
            ))
            rows = repo.ranking_matches_on_date(2026, "2026-08-13")
            winners = {rows[0]["match_id"]: "A", rows[1]["match_id"]: "B"}
            event.resolve_date("2026-08-13", winners)
            repo.save_ranking_sidecar(2026, event)
            self.assertEqual(3, len(repo.competition_ranking_matches(
                2026, "CMP000162",
            )))
            self.assertEqual(2, len([r for r in repo.competition_ranking_matches(
                2026, "CMP000162",
            ) if r["status"] == "completed"]))
            restored = repo.load_ranking_sidecar(
                2026, "CMP000162", "SGR000184",
            )
            self.assertEqual(event.snapshot(), restored.snapshot())
            self.assertIsNone(repo.load_ranking_sidecar(
                2026, "CMP000162", "NONE",
            ))

    def test_live_season_today_shows_optional_rankings_without_blocking(self):
        repo = DataRepository(DATA)
        scheduled = ScheduledCompetitionRuntime(
            repo=repo, runtime=CompletedMainRuntime(),
            competition_id="CMP000162", competition_name="沖縄秋",
            calendar_dates=[], stage_date_lists={},
            calendar_status="official_schedule",
        )
        live = LiveSeasonDependencyRuntimeState(
            engine=None, repo=repo, current_date=date(2026, 8, 13)
        )
        live.competitions["CMP000162"] = scheduled
        live.register_ranking_sidecar("CMP000162", sidecar())
        rows = live.today_matches()
        self.assertEqual(2, len(rows))
        self.assertTrue(all(r["competition_name"] == "沖縄秋" for r in rows))
        self.assertTrue(all(r["ranking_only"] for r in rows))
        self.assertTrue(scheduled.is_complete)
        live.play_today_rankings({
            "CMP000162": {"SGR000184": {
                rows[0]["match_id"]: "A", rows[1]["match_id"]: "B",
            }},
        })
        self.assertTrue(scheduled.is_complete)
        self.assertEqual("play_today_rankings", live.history[-1]["action"])

    def test_live_season_rejects_unregistered_competition(self):
        repo = DataRepository(DATA)
        live = LiveSeasonDependencyRuntimeState(
            engine=None, repo=repo, current_date=date(2026, 8, 13)
        )
        with self.assertRaisesRegex(ValueError, "not been activated"):
            live.register_ranking_sidecar("CMP000162", sidecar())

    def test_2026_main_tables_and_queue_are_untouched(self):
        repo = DataRepository(DATA)
        scheduled = ScheduledCompetitionRuntime(
            repo=repo, runtime=CompletedMainRuntime(),
            competition_id="CMP000162", competition_name="沖縄秋",
            calendar_dates=[], stage_date_lists={},
            calendar_status="official_schedule",
        )
        scheduled.attach_ranking_sidecar(sidecar())
        self.assertEqual({}, scheduled.completed_results())
        self.assertTrue(scheduled.is_complete)
        self.assertEqual([], scheduled.calendar_gap_matches())


if __name__ == "__main__":
    unittest.main()
