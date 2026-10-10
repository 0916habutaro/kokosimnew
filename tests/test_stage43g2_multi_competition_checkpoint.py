from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService,
    CareerPreviewSaveError,
    _checksum,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_regional_main_checkpoint import (
    CareerRegionalMainCheckpointService,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.models import (
    CompetitionOutcome, CompetitionRun, Match, StageExecution,
)
from phase2_engine.repository import DataRepository
from phase2_engine.same_year_regional_feeder_gate import (
    RegionalFeederNotReady,
    project_same_year_regional_feeders,
)

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026100701
SPECS = (
    ("CMP000084", "CMP000085", "08", 4),
    ("CMP000090", "CMP000091", "11", 8),
)


def finished_autumn(competition_id, school_ids):
    live = list(school_ids)
    matches = []
    eliminated = defaultdict(list)
    round_no = 1
    while len(live) > 1:
        winners = []
        for i in range(0, len(live), 2):
            a, b = live[i], live[i + 1]
            winners.append(a)
            eliminated[round_no].append(b)
            matches.append(Match(
                match_id=f"{competition_id}-ST43G2-{len(matches) + 1}",
                competition_id=competition_id,
                stage_id="STG-ST43G2", stage_code="MAIN",
                phase_code="MAIN_BRACKET", round_no=round_no,
                team1=a, team2=b, winner=a, loser=b,
            ))
        live = winners
        round_no += 1
    ranked = live[:]
    for number in sorted(eliminated, reverse=True):
        ranked.extend(eliminated[number])
    run = CompetitionRun(
        competition_id=competition_id, year=2026, rng_seed=SEED,
        entrant_school_ids=list(school_ids), seed_assignments=[],
        stage_executions=[StageExecution(
            stage_id="STG-ST43G2", stage_code="MAIN",
            format_model_id="MAIN_SINGLE_ELIMINATION",
            entrant_school_ids=list(school_ids),
            output_school_ids=[ranked[0]], matches=matches,
        )],
        main_entrant_school_ids=list(school_ids),
        outcome=CompetitionOutcome(
            champion_school_id=ranked[0],
            runner_up_school_id=ranked[1],
            semifinalist_school_ids=ranked[2:4],
            quarterfinalist_school_ids=ranked[4:8],
            final_ranking_school_ids=ranked,
            eliminated_by_round={
                str(k): list(v) for k, v in eliminated.items()
            },
            match_count=len(matches),
            bye_count=0,
            bracket_size=len(school_ids),
        ),
    )
    rows = [{
        "competition_id": competition_id,
        "competition_name": "2026ゲーム内秋県大会（試験用）",
        "match_id": m.match_id,
        "match_date": "2026-10-10", "completed_on": "2026-10-10",
        "date_source": "game_projection_v1", "status": "completed",
        "stage_code": "MAIN", "phase_code": "MAIN_BRACKET",
        "round_no": m.round_no,
        "team1_id": m.team1, "team2_id": m.team2,
        "winner_id": m.winner, "loser_id": m.loser,
        "team1_score": 4, "team2_score": 2,
        "score_source": "generated_v1",
    } for m in matches]
    return run, rows


class Stage43G2MultiCompetitionCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.fixture = tempfile.TemporaryDirectory()
        base = Path(cls.fixture.name)
        cls.history_file = base / "history.sqlite3"
        cls.roster_file = base / "rosters.sqlite3"
        hist = HistoricalMatchArchive(cls.history_file)
        archive = CareerRosterArchive(cls.roster_file)
        generator = PlayerRosterGenerator()
        all_rows = []
        outcome_runs = []
        cls.competitions = []

        for spring, autumn, pcode, count in SPECS:
            schools = sorted(
                sid for sid in cls.repo.school_to_program
                if cls.repo.schools[sid]["prefecture_code"] == pcode
            )
            direct = schools[:count]
            qualifier = next(s for s in cls.repo.stages(spring)
                             if s["stage_code"] == "BRANCH_QUALIFIER")
            groups = cls.repo.groups_by_stage[qualifier["stage_id"]]
            group_input = {}
            pos = count
            for group in groups:
                slots = cls.repo.param(
                    qualifier["stage_id"], "output_slots",
                    group["stage_group_id"],
                    int(group["advance_slots_to_next"]),
                )
                group_input[group["stage_group_id"]] = schools[pos:pos + slots + 1]
                pos += slots + 1
            assert pos == (39 if spring == "CMP000084" else 52)
            entrants = schools[:pos]
            cls.competitions.append({
                "competition_id": spring,
                "entrant_school_ids": entrants,
                "group_entrant_school_ids": group_input,
            })
            run, rows = finished_autumn(autumn, direct)
            outcome_runs.append(run)
            all_rows.extend(rows)
            for sid in entrants:
                initial = generator.generate_for_school_id(
                    cls.repo, sid, 2026, SEED,
                )
                archive.save_initial_roster(initial)
                archive.advance_and_save(
                    cls.repo.team(sid), next_year=2027,
                    career_seed=SEED,
                )

        hist.sync(
            year=2026, rng_seed=42, resolver_contract="game_v1",
            plan_fingerprint="stage43g2-two-autumn-sandbox",
            completed=all_rows,
        )
        hist.seal_year(2026, expected_match_count=len(all_rows))
        writer = CareerCompetitionOutcomes(hist)
        for run in outcome_runs:
            writer.record_completed(run)
        cls.original_2026_count = len(all_rows)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.slot = self.root / "career_slot"
        self.slot.mkdir()
        shutil.copy2(self.history_file, self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.roster_file, self.slot / "career_rosters.sqlite3")
        self.service = CareerMultiPreviewCheckpointService(
            self.repo, ROOT / "data", save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.checkpoint = self.slot / "career_multi_previews" / "2027.json"

    def tearDown(self):
        self.temp.cleanup()

    def start(self, **kwargs):
        params = {
            "year": 2027,
            "competitions": self.competitions,
            "base_seed": SEED, "career_seed": SEED,
        }
        params.update(kwargs)
        return self.service.start("career_slot", **params)

    def test_two_competitions_share_year_archive_and_2026_save_untouched(self):
        original = self.slot / "manual.json"
        original.write_bytes(b"immutable 2026 live save")
        session = self.start()
        self.assertEqual(2, session.summary()["competition_count"])
        self.assertEqual(
            ["CMP000084", "CMP000090"],
            session.summary()["competition_ids"],
        )
        self.assertFalse(session.summary()["full_year_gameplay"])
        self.assertFalse(session.summary()["competition_advancement_automatic"])
        self.assertEqual(original.read_bytes(), b"immutable 2026 live save")
        self.assertTrue(self.checkpoint.is_file())
        history = HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")
        self.assertEqual(
            [(2026, "sealed"), (2027, "active")],
            [(r["year"], r["status"]) for r in history.list_years()],
        )
        self.assertEqual(self.original_2026_count,
                         len(history.list_matches(2026)))
        self.assertEqual([], history.list_matches(2027))

    def test_dates_advance_across_competitions_in_global_order(self):
        session = self.start()
        first = self.service.play_next_date(session)
        self.assertEqual("2027-04-08", first["date"])
        self.assertEqual({"CMP000084": 4}, first["competition_match_counts"])
        second = self.service.play_next_date(session)
        # Saitama's first qualifier date is Apr 10; Ibaraki may also be
        # scheduled on subsequent dates, so compare against its real queue.
        self.assertGreater(second["date"], first["date"])
        self.assertEqual(sorted(session.processed_dates),
                         session.processed_dates)
        self.assertEqual(len(set(session.processed_dates)),
                         len(session.processed_dates))
        total = len([
            r for r in HistoricalMatchArchive(
                self.slot / "historical_matches.sqlite3"
            ).list_matches(2027)
        ])
        self.assertEqual(first["played_match_count"] +
                         second["played_match_count"], total)
        self.assertTrue(all(
            x["date_source"] == "game_projection_v1"
            for x in HistoricalMatchArchive(
                self.slot / "historical_matches.sqlite3"
            ).list_matches(2027)
        ))

    def test_restarting_replays_both_competitions_and_continues(self):
        session = self.start()
        self.service.play_next_date(session)
        self.service.play_next_date(session)
        before = {
            cid: preview.scheduled.public_snapshot()
            for cid, preview in session.previews.items()
        }
        restored = self.service.load("career_slot", year=2027)
        self.assertEqual(
            before,
            {cid: preview.scheduled.public_snapshot()
             for cid, preview in restored.previews.items()},
        )
        self.assertEqual(session.processed_dates, restored.processed_dates)
        third = self.service.play_next_date(restored)
        self.assertGreater(third["played_match_count"], 0)
        total = len(HistoricalMatchArchive(
            self.slot / "historical_matches.sqlite3"
        ).list_matches(2027))
        self.assertEqual(total, third["checkpoint"]["completed_match_count"])
        again = self.service.load("career_slot", year=2027)
        self.assertEqual(restored.processed_dates, again.processed_dates)

    def test_checkpoint_replay_repairs_missing_2027_archive_only(self):
        session = self.start()
        first = self.service.play_next_date(session)
        self.assertEqual(4, first["played_match_count"])
        db = self.slot / "historical_matches.sqlite3"
        with sqlite3.connect(db) as conn:
            conn.execute("DELETE FROM historical_matches WHERE year=2027")
        recovered = self.service.load("career_slot", year=2027)
        self.assertEqual(4, recovered.summary()["completed_match_count"])
        history = HistoricalMatchArchive(db)
        self.assertEqual(4, len(history.list_matches(2027)))
        self.assertEqual(self.original_2026_count,
                         len(history.list_matches(2026)))
        self.assertEqual("sealed", history.list_years()[0]["status"])

    def test_stale_session_cannot_overwrite_shared_year_checkpoint(self):
        self.start()
        one = self.service.load("career_slot", year=2027)
        stale = self.service.load("career_slot", year=2027)
        self.service.play_next_date(one)
        with self.assertRaisesRegex(CareerPreviewSaveError, "another"):
            self.service.play_next_date(stale)
        restored = self.service.load("career_slot", year=2027)
        self.assertEqual(4, restored.summary()["completed_match_count"])

    def test_deleted_or_forged_match_digest_rejected(self):
        session = self.start()
        self.service.play_next_date(session)
        data = json.loads(self.checkpoint.read_text(encoding="utf-8"))
        data["completed_match_sha256"] = "tampered"
        data["payload_checksum"] = _checksum(data)
        self.checkpoint.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(CareerPreviewSaveError, "replay results"):
            self.service.load("career_slot", year=2027)

    def test_seed_change_and_pristine_plan_replay_protection(self):
        self.start()
        data = json.loads(self.checkpoint.read_text(encoding="utf-8"))
        data["inputs"][0]["base_seed"] += 1
        data["payload_checksum"] = _checksum(data)
        self.checkpoint.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(CareerPreviewSaveError):
            self.service.load("career_slot", year=2027)

    def test_no_duplicate_competition_or_single_event_collision(self):
        with self.assertRaisesRegex(CareerPreviewSaveError, "duplicate"):
            self.start(competitions=[
                self.competitions[0], self.competitions[0],
            ])
        single = self.slot / "career_previews" / "2027_CMP000084.json"
        single.parent.mkdir()
        single.write_text("do not overwrite", encoding="utf-8")
        with self.assertRaisesRegex(CareerPreviewSaveError, "single-event"):
            self.start()
        self.assertFalse(self.checkpoint.exists())

    def test_previously_unsealed_year_must_not_start(self):
        with sqlite3.connect(
            self.slot / "historical_matches.sqlite3"
        ) as conn:
            conn.execute(
                "UPDATE career_years SET status='active' WHERE year=2026"
            )
        with self.assertRaisesRegex(CareerPreviewSaveError, "not sealed"):
            self.start()
        self.assertFalse(self.checkpoint.exists())

    def test_completed_event_outcomes_are_exposed_but_not_auto_qualified(self):
        session = self.start()
        self.assertEqual({}, session.completed_runs())
        self.assertEqual([], session.summary()["completed_competition_ids"])
        self.assertFalse(session.summary()["competition_advancement_automatic"])
        self.assertFalse(json.loads(self.checkpoint.read_text(
            encoding="utf-8"
        ))["automatic_feeder_advancement"])

    def test_stage43g3_regional_feeder_pending_before_source_finals(self):
        session = self.start()
        view = project_same_year_regional_feeders(
            self.service, session, "CMP000006",
        )
        self.assertEqual(2027, view["year"])
        self.assertEqual(8, view["feeder_rule_count"])
        self.assertEqual(17, view["expected_entrant_count"])
        self.assertEqual(0, view["verified_entrant_count"])
        self.assertEqual(8, len(view["unresolved_feeder_rule_ids"]))
        self.assertFalse(view["regional_runtime_ready"])
        self.assertFalse(view["official_future_rule_verified"])
        self.assertFalse(view["automatic_qualification_committed"])
        by_rule = {r["feeder_rule_id"]: r for r in view["feeder_rules"]}
        self.assertEqual("source_not_completed", by_rule["RFR000007"]["status"])
        self.assertEqual("source_not_completed", by_rule["RFR000010"]["status"])
        self.assertEqual(
            "source_not_in_preview", by_rule["RFR000011"]["status"],
        )

    def test_stage43g3_regional_feeder_only_completed_saved_sources(self):
        session = self.start()
        for _ in range(40):
            if session.previews["CMP000084"].scheduled.is_complete:
                break
            self.service.play_next_date(session)
        self.assertTrue(session.previews["CMP000084"].scheduled.is_complete)
        view = project_same_year_regional_feeders(
            self.service, session, "CMP000006",
        )
        by_id = {x["feeder_rule_id"]: x for x in view["feeder_rules"]}
        self.assertEqual("verified_game_qualification",
                         by_id["RFR000007"]["status"])
        self.assertEqual(2, len(by_id["RFR000007"]["school_ids"]))
        self.assertTrue(by_id["RFR000007"]["evidence_sha256"])
        self.assertEqual(2, view["verified_entrant_count"])
        self.assertEqual("source_not_completed",
                         by_id["RFR000010"]["status"])
        self.assertFalse(view["all_feeder_results_verified"])
        self.assertFalse(view["regional_runtime_ready"])

    def test_stage43g3_both_sources_from_archived_games_not_unplayed_schools(self):
        session = self.start()
        for _ in range(45):
            if all(p.scheduled.is_complete for p in session.previews.values()):
                break
            self.service.play_next_date(session)
        self.assertTrue(all(p.scheduled.is_complete
                            for p in session.previews.values()))
        view = project_same_year_regional_feeders(
            self.service, session, "CMP000006",
        )
        by_id = {x["feeder_rule_id"]: x for x in view["feeder_rules"]}
        self.assertEqual(4, view["verified_entrant_count"])
        self.assertEqual(6, len(view["unresolved_feeder_rule_ids"]))
        self.assertEqual(
            ["RFR000007", "RFR000010"],
            [r["feeder_rule_id"] for r in view["feeder_rules"]
             if r["status"] == "verified_game_qualification"],
        )
        for rule_id, comp_id in (
            ("RFR000007", "CMP000084"), ("RFR000010", "CMP000090"),
        ):
            expected = session.completed_runs()[comp_id].outcome.final_ranking_school_ids[:2]
            self.assertEqual(expected, by_id[rule_id]["school_ids"])
            self.assertTrue(by_id[rule_id]["evidence_sha256"])
        self.assertEqual(4, len(set(view["verified_school_ids"])))
        self.assertFalse(view["all_feeder_results_verified"])
        self.assertFalse(view["regional_runtime_ready"])
        self.assertFalse(view["automatic_qualification_committed"])
        db = self.slot / "historical_matches.sqlite3"
        # An already-archived game's tampering must invalidate source proof.
        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE historical_matches SET record_sha256='tampered' "
                "WHERE year=2027 AND competition_id='CMP000084' "
                "AND match_id = "
                "(SELECT match_id FROM historical_matches "
                "WHERE year=2027 AND competition_id='CMP000084' "
                "AND match_date >= '2027-04-18' "
                "ORDER BY match_date, match_id LIMIT 1)"
            )
        with self.assertRaisesRegex(
            RegionalFeederNotReady, "archived games",
        ):
            project_same_year_regional_feeders(
                self.service, session, "CMP000006",
            )

    def test_stage43g3_invalid_destination_does_not_generate_qualifiers(self):
        session = self.start()
        with self.assertRaises(RegionalFeederNotReady):
            project_same_year_regional_feeders(
                self.service, session, "CMP000084",
            )
        # Another valid regional competition returns unresolved sources,
        # never schools borrowed from the Kanto prefectural games.
        other = project_same_year_regional_feeders(
            self.service, session, "CMP000007",
        )
        self.assertEqual(0, other["verified_entrant_count"])
        self.assertFalse(other["regional_runtime_ready"])
        self.assertFalse(other["all_feeder_results_verified"])

    def test_stage43g3_stale_session_cannot_claim_same_year_qualifications(self):
        self.start()
        a = self.service.load("career_slot", year=2027)
        stale = self.service.load("career_slot", year=2027)
        self.service.play_next_date(a)
        with self.assertRaisesRegex(
            RegionalFeederNotReady, "stale",
        ):
            project_same_year_regional_feeders(
                self.service, stale, "CMP000006",
            )
        valid = project_same_year_regional_feeders(
            self.service, a, "CMP000006",
        )
        self.assertEqual(0, valid["verified_entrant_count"])

    def _stage43g4_finished_sources(self):
        session = self.start()
        for _ in range(45):
            if all(p.scheduled.is_complete for p in session.previews.values()):
                break
            self.service.play_next_date(session)
        self.assertTrue(all(p.scheduled.is_complete
                            for p in session.previews.values()))
        return session

    def _stage43g4_mock_complete_region(self):
        # Unit-only fixture: the real Stage43G-3 gate is never bypassed in
        # production. The actual two-prefecture fixture contains only 4/17.
        a = self.competitions[0]["entrant_school_ids"][:9]
        b = self.competitions[1]["entrant_school_ids"][:8]
        schools = a + b
        assert len(schools) == len(set(schools)) == 17
        return {
            "year": 2027, "destination_competition_id": "CMP000006",
            "all_feeder_results_verified": True,
            "unresolved_feeder_rule_ids": [],
            "verified_entrant_count": 17,
            "verified_school_ids": schools,
            "test_only_mock_feeder": True,
        }

    def test_stage43g4_regional_main_never_starts_with_partial_sources(self):
        region = CareerRegionalMainCheckpointService(self.service)
        self.start()
        with self.assertRaisesRegex(
            RegionalFeederNotReady, "all registered prefectural events",
        ):
            region.start("career_slot", year=2027)
        self.assertFalse(region._path("career_slot", 2027).exists())
        # Even completed Ibaraki/Saitama have only 4 of 17 verified schools.

    def test_stage43g4_completed_sources_still_block_unresolved_13(self):
        self._stage43g4_finished_sources()
        region = CareerRegionalMainCheckpointService(self.service)
        with self.assertRaisesRegex(
            RegionalFeederNotReady, "unresolved prefectural feeders",
        ):
            region.start("career_slot", year=2027)
        self.assertFalse(region._path("career_slot", 2027).exists())

    def test_stage43g4_unit_region_draw_and_save_resume_share_same_archive(self):
        self._stage43g4_finished_sources()
        region = CareerRegionalMainCheckpointService(self.service)
        fake = self._stage43g4_mock_complete_region()
        history = HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")
        before = len(history.list_matches(2027))
        # Only isolate the downstream, real regional match engine/loader.
        # Fully verified 8-prefecture source integration is a later test.
        with patch(
            "phase2_engine.career_regional_main_checkpoint."
            "project_same_year_regional_feeders", return_value=fake,
        ):
            session = region.start("career_slot", year=2027)
            self.assertEqual(17, session.summary()["entrant_count"])
            self.assertFalse(session.summary()["official_calendar"])
            self.assertEqual([], session.preview.annual.main_seed_school_ids)
            self.assertEqual("2027-05-16",
                             session.preview.scheduled.next_scheduled_date())
            self.assertEqual(before, len(history.list_matches(2027)))
            day = region.play_next_date(session)
            self.assertEqual("2027-05-16", day["date"])
            self.assertGreater(day["played_match_count"], 0)
            self.assertEqual(before + day["played_match_count"],
                             len(history.list_matches(2027)))
            self.assertTrue(all(
                x["date_source"] == "game_projection_v1"
                for x in history.list_matches(2027)
            ))
            resumed = region.load("career_slot", year=2027)
            self.assertEqual(
                session.preview.scheduled.public_snapshot(),
                resumed.preview.scheduled.public_snapshot(),
            )
            self.assertEqual("sealed", history.list_years()[0]["status"])
            with self.assertRaisesRegex(CareerPreviewSaveError, "already exists"):
                region.start("career_slot", year=2027)

    def test_stage43g4_unit_region_checkpoint_tamper_fails_closed(self):
        self._stage43g4_finished_sources()
        region = CareerRegionalMainCheckpointService(self.service)
        fake = self._stage43g4_mock_complete_region()
        with patch(
            "phase2_engine.career_regional_main_checkpoint."
            "project_same_year_regional_feeders", return_value=fake,
        ):
            session = region.start("career_slot", year=2027)
            region.play_next_date(session)
            checkpoint = region._path("career_slot", 2027)
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            data["completed_match_sha256"] = "tampered"
            data["payload_checksum"] = _checksum(data)
            checkpoint.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(
                CareerPreviewSaveError, "replay match results",
            ):
                region.load("career_slot", year=2027)

    def test_stage43g4_unrecognized_placement_proof_is_rejected(self):
        session = self.start()
        with self.assertRaisesRegex(
            RegionalFeederNotReady, "unrecognized third-place",
        ):
            project_same_year_regional_feeders(
                self.service, session, "CMP000006",
                placement_decider_match_ids={"CMP000084": "FAKE-3RD"},
            )


if __name__ == "__main__":
    unittest.main()
