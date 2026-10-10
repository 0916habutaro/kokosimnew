from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.career_preview_checkpoint import (
    CareerPreviewCheckpointService,
    CareerPreviewSaveError,
    _checksum,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.models import (
    CompetitionOutcome, CompetitionRun, Match, StageExecution,
)
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
AUTUMN = "CMP000085"
SPRING = "CMP000084"
SEED = 2026100701


def finished_autumn(schools):
    a, b, c, d = schools
    pairs = [(a, c, a, 1), (b, d, b, 1), (a, b, a, 2)]
    matches = [
        Match(
            match_id=f"G43G1-{i}", competition_id=AUTUMN,
            stage_id="STG-SANDBOX", stage_code="MAIN",
            phase_code="MAIN_BRACKET", round_no=round_no,
            team1=x, team2=y, winner=w,
            loser=y if w == x else x,
        )
        for i, (x, y, w, round_no) in enumerate(pairs, start=1)
    ]
    run = CompetitionRun(
        competition_id=AUTUMN, year=2026, rng_seed=SEED,
        entrant_school_ids=list(schools), seed_assignments=[],
        stage_executions=[StageExecution(
            stage_id="STG-SANDBOX", stage_code="MAIN",
            format_model_id="MAIN_SINGLE_ELIMINATION",
            entrant_school_ids=list(schools),
            output_school_ids=[a], matches=matches,
        )],
        main_entrant_school_ids=list(schools),
        outcome=CompetitionOutcome(
            champion_school_id=a, runner_up_school_id=b,
            semifinalist_school_ids=[c, d], quarterfinalist_school_ids=[],
            final_ranking_school_ids=list(schools),
            eliminated_by_round={"1": [c, d], "2": [b]},
            match_count=3, bye_count=0, bracket_size=4,
        ),
    )
    records = [{
        "competition_id": AUTUMN, "match_id": m.match_id,
        "competition_name": "ゲーム内2026秋大会",
        "match_date": "2026-10-10", "completed_on": "2026-10-10",
        "date_source": "game_projection_v1", "stage_code": "MAIN",
        "phase_code": "MAIN_BRACKET", "round_no": m.round_no,
        "status": "completed",
        "team1_id": m.team1, "team2_id": m.team2,
        "winner_id": m.winner, "loser_id": m.loser,
        "team1_score": 4, "team2_score": 2,
        "score_source": "generated_v1",
    } for m in matches]
    return run, records


class Stage43G1CareerPreviewCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        schools = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "08"
        )
        cls.direct = schools[:4]
        cls.entrants = schools[:39]
        cls.non_direct = schools[4:39]
        cls.stage_groups = cls.repo.groups_by_stage["STG000171"]
        cls.mapping = {}
        pos = 0
        for group, length in zip(cls.stage_groups, (9, 9, 9, 8)):
            cls.mapping[group["stage_group_id"]] = cls.non_direct[
                pos:pos + length
            ]
            pos += length
        assert pos == 35

        cls.fixture = tempfile.TemporaryDirectory()
        src = Path(cls.fixture.name)
        cls.history_file = src / "history.sqlite3"
        cls.roster_file = src / "rosters.sqlite3"
        archive = HistoricalMatchArchive(cls.history_file)
        run, rows = finished_autumn(cls.direct)
        archive.sync(
            year=2026, rng_seed=42,
            resolver_contract="game_v1",
            plan_fingerprint="stage43g1-fixture-2026",
            completed=rows,
        )
        archive.seal_year(2026, expected_match_count=3)
        CareerCompetitionOutcomes(archive).record_completed(run)
        rosters = CareerRosterArchive(cls.roster_file)
        generator = PlayerRosterGenerator()
        for sid in cls.entrants:
            initial = generator.generate_for_school_id(
                cls.repo, sid, 2026, SEED,
            )
            rosters.save_initial_roster(initial)
            rosters.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=SEED,
            )

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.slot = self.root / "career_one"
        self.slot.mkdir()
        shutil.copy2(
            self.history_file, self.slot / "historical_matches.sqlite3",
        )
        shutil.copy2(
            self.roster_file, self.slot / "career_rosters.sqlite3",
        )
        self.service = CareerPreviewCheckpointService(
            self.repo, ROOT / "data", save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.path = self.slot / "career_previews" / "2027_CMP000084.json"

    def tearDown(self):
        self.temp.cleanup()

    def start(self):
        return self.service.start(
            "career_one", year=2027, competition_id=SPRING,
            entrant_school_ids=self.entrants,
            group_entrant_school_ids=self.mapping,
            base_seed=SEED, career_seed=SEED,
        )

    def test_start_does_not_overwrite_original_live_game_save(self):
        original = self.slot / "manual.json"
        original.write_bytes(b"an untouched legacy season save")
        session = self.start()
        self.assertTrue(self.path.is_file())
        self.assertEqual(original.read_bytes(), b"an untouched legacy season save")
        self.assertFalse(session.summary()["full_season_live"])
        self.assertFalse(session.summary()["official_2027_calendar"])
        self.assertEqual(2027, session.summary()["year"])
        years = HistoricalMatchArchive(
            self.slot / "historical_matches.sqlite3"
        ).list_years()
        self.assertEqual(
            [(2026, "sealed"), (2027, "active")],
            [(x["year"], x["status"]) for x in years],
        )
        self.assertEqual([], HistoricalMatchArchive(
            self.slot / "historical_matches.sqlite3"
        ).list_matches(2027))

    def test_play_first_day_archives_a_details_and_keeps_2026_sealed(self):
        session = self.start()
        result = self.service.play_next_date(session)
        self.assertEqual("2027-04-08", result["date"])
        self.assertEqual(4, result["played_match_count"])
        self.assertEqual(4, result["checkpoint"]["completed_match_count"])
        history = HistoricalMatchArchive(
            self.slot / "historical_matches.sqlite3"
        )
        self.assertEqual(3, len(history.list_matches(2026)))
        self.assertEqual(4, len(history.list_matches(2027)))
        row = history.list_matches(2027)[0]
        self.assertEqual("game_projection_v1", row["date_source"])
        self.assertEqual("ability_model_v1", row["score_source"])
        self.assertEqual(2027, row["year"])
        self.assertTrue(row["batter_stats"])
        self.assertTrue(row["pitcher_stats"])
        self.assertEqual(2, len(row["team_stats"]))
        self.assertTrue(row["inning_scores"])
        self.assertEqual(
            "sealed", history.list_years()[0]["status"],
        )

    def test_load_replays_checkpoint_and_continues_on_main_date(self):
        old = self.start()
        self.service.play_next_date(old)
        before = old.preview.scheduled.public_snapshot()
        resumed = self.service.load(
            "career_one", year=2027, competition_id=SPRING,
        )
        self.assertEqual(
            before, resumed.preview.scheduled.public_snapshot(),
        )
        self.assertEqual(["2027-04-08"],
                         resumed.preview.scheduled.processed_dates)
        self.assertEqual(
            "2027-04-11", resumed.preview.scheduled.next_scheduled_date(),
        )
        second = self.service.play_next_date(resumed)
        self.assertTrue(second["played_match_count"] > 0)
        self.assertEqual(
            second["checkpoint"]["completed_match_count"],
            len(HistoricalMatchArchive(
                self.slot / "historical_matches.sqlite3",
            ).list_matches(2027)),
        )
        round_trip = self.service.load(
            "career_one", year=2027, competition_id=SPRING,
        )
        self.assertEqual(
            resumed.preview.scheduled.public_snapshot(),
            round_trip.preview.scheduled.public_snapshot(),
        )

    def test_crash_between_json_checkpoint_and_archive_can_be_repaired(self):
        session = self.start()
        self.service.play_next_date(session)
        db_path = self.slot / "historical_matches.sqlite3"
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM historical_matches WHERE year = 2027")
        resumed = self.service.load(
            "career_one", year=2027, competition_id=SPRING,
        )
        self.assertEqual(4, len(resumed.preview.scheduled.completed_results()))
        self.assertEqual(4, len(
            HistoricalMatchArchive(db_path).list_matches(2027),
        ))

    def test_modified_checksum_is_rejected_before_replay(self):
        self.start()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["completed_match_count"] = 999
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(CareerPreviewSaveError, "checksum"):
            self.service.load("career_one", year=2027, competition_id=SPRING)

    def test_rechecks_results_even_when_attacker_recalculates_checksum(self):
        session = self.start()
        self.service.play_next_date(session)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["completed_match_sha256"] = "wrong"
        payload["payload_checksum"] = _checksum(payload)
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(CareerPreviewSaveError, "replay score"):
            self.service.load("career_one", year=2027, competition_id=SPRING)

    def test_previous_year_tamper_is_rejected_on_resume(self):
        self.start()
        with sqlite3.connect(
            self.slot / "historical_matches.sqlite3"
        ) as conn:
            conn.execute(
                "UPDATE career_years SET ledger_sha256='modified' "
                "WHERE year=2026"
            )
        with self.assertRaisesRegex(CareerPreviewSaveError, "ledger"):
            self.service.load("career_one", year=2027, competition_id=SPRING)

    def test_checkpoint_cannot_be_overwritten_by_stale_session(self):
        self.start()
        a = self.service.load("career_one", year=2027, competition_id=SPRING)
        b = self.service.load("career_one", year=2027, competition_id=SPRING)
        self.service.play_next_date(a)
        with self.assertRaisesRegex(CareerPreviewSaveError, "another session"):
            self.service.play_next_date(b)
        self.assertEqual(
            4, len(self.service.load(
                "career_one", year=2027, competition_id=SPRING,
            ).preview.scheduled.completed_results()),
        )

    def test_duplicate_start_and_another_competition_in_same_year_rejected(self):
        self.start()
        with self.assertRaisesRegex(CareerPreviewSaveError, "already exists"):
            self.start()
        with self.assertRaisesRegex(CareerPreviewSaveError, "only one"):
            self.service.start(
                "career_one", year=2027, competition_id="CMP000090",
                entrant_school_ids=self.entrants,
                group_entrant_school_ids=self.mapping,
                base_seed=SEED, career_seed=SEED,
            )

    def test_invalid_slot_and_unsealed_prior_year_refuse_start(self):
        with self.assertRaises(ValueError):
            self.service.start(
                "../escape", year=2027, competition_id=SPRING,
                entrant_school_ids=self.entrants,
                group_entrant_school_ids=self.mapping,
                base_seed=SEED, career_seed=SEED,
            )
        with sqlite3.connect(
            self.slot / "historical_matches.sqlite3"
        ) as conn:
            conn.execute(
                "UPDATE career_years SET status='active' WHERE year=2026"
            )
        with self.assertRaisesRegex(CareerPreviewSaveError, "not sealed"):
            self.start()
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
