from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from phase2_engine.career_competition_outcomes import (
    CareerCompetitionOutcomes,
    CareerOutcomeConflictError,
    build_future_blueprint_from_archive,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.models import (
    CompetitionOutcome, CompetitionRun, Match, StageExecution,
)

ROOT = Path(__file__).resolve().parents[1]
COMPETITION = "CMP000085"  # 2026 autumn Ibaraki -> 2027 spring ACR000004
SCHOOLS = ("SCH-A", "SCH-B", "SCH-C", "SCH-D")


def match(match_id, a, b, winner, round_no):
    return Match(
        match_id=match_id, competition_id=COMPETITION, stage_id="STG-TEST",
        stage_code="MAIN", phase_code="MAIN_BRACKET", round_no=round_no,
        team1=a, team2=b, winner=winner, loser=b if winner == a else a,
    )


def complete_run(year=2026):
    main_matches = [
        match("M1", "SCH-A", "SCH-C", "SCH-A", 1),
        match("M2", "SCH-B", "SCH-D", "SCH-B", 1),
        match("M3", "SCH-A", "SCH-B", "SCH-A", 2),
    ]
    stage = StageExecution(
        stage_id="STG-TEST", stage_code="MAIN",
        format_model_id="MAIN_SINGLE_ELIMINATION",
        entrant_school_ids=list(SCHOOLS),
        output_school_ids=["SCH-A"],
        matches=main_matches,
    )
    outcome = CompetitionOutcome(
        champion_school_id="SCH-A",
        runner_up_school_id="SCH-B",
        semifinalist_school_ids=["SCH-C", "SCH-D"],
        quarterfinalist_school_ids=[],
        final_ranking_school_ids=list(SCHOOLS),
        eliminated_by_round={"1": ["SCH-C", "SCH-D"], "2": ["SCH-B"]},
        match_count=3,
        bye_count=0,
        bracket_size=4,
    )
    run = CompetitionRun(
        competition_id=COMPETITION, year=year, rng_seed=44,
        entrant_school_ids=list(SCHOOLS),
        seed_assignments=[],
        stage_executions=[stage],
        main_entrant_school_ids=list(SCHOOLS),
        outcome=outcome,
    )
    return run


def historic_row(year, m):
    return {
        "competition_id": COMPETITION, "competition_name": "ゲーム内秋季県大会",
        "match_id": m.match_id, "match_date": f"{year}-10-10",
        "completed_on": f"{year}-10-10", "date_source": "game_projection_v1",
        "status": "completed", "stage_code": "MAIN", "phase_code": "MAIN_BRACKET",
        "round_no": m.round_no, "team1_id": m.team1, "team2_id": m.team2,
        "winner_id": m.winner, "loser_id": m.loser,
        "team1_score": 4 if m.winner == m.team1 else 2,
        "team2_score": 2 if m.winner == m.team1 else 4,
        "score_source": "generated_v1",
    }


class Stage43F4VerifiedOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "slot" / "historical_matches.sqlite3"
        self.archive = HistoricalMatchArchive(self.db_path)
        self.outcomes = CareerCompetitionOutcomes(self.archive)
        self.run = complete_run()
        self.records = [historic_row(2026, m)
                        for m in self.run.stage_executions[0].matches]

    def tearDown(self):
        self.temp.cleanup()

    def save(self, rows=None, *, year=2026):
        result = self.archive.sync(
            year=year, rng_seed=42, resolver_contract="game_v1",
            plan_fingerprint=f"plan-{year}",
            completed=self.records if rows is None else rows,
        )
        return result

    def seal(self, count=3):
        return self.archive.seal_year(2026, expected_match_count=count)

    def test_previous_autumn_2026_actual_game_ranking_flows_to_2027(self):
        self.save()
        self.seal()
        self.assertTrue(self.outcomes.record_completed(self.run)["inserted"])
        future = build_future_blueprint_from_archive(
            ROOT / "data", year=2027, base_seed=1234,
            match_archive=self.archive,
        )
        rule = next(x for x in future["prior_autumn_access"]
                    if x["access_rule_id"] == "ACR000004")
        self.assertEqual(2026, rule["source_year"])
        self.assertEqual(COMPETITION, rule["source_competition_id"])
        self.assertEqual("resolved", rule["status"])
        self.assertEqual(list(SCHOOLS), rule["school_ids"])
        self.assertEqual("previous_year_saved_game_result", rule["provenance"])
        self.assertNotIn("ACR000004", future["unresolved_prior_rule_ids"])
        self.assertEqual("sealed_career_game_archive",
                         future["previous_results_source"])
        self.assertEqual(1, future["previous_results_count"])
        self.assertFalse(future["official_calendar"])
        self.assertFalse(future["live_runtime_ready"])
        committee = next(x for x in future["committee_selections"]
                         if x["competition_id"] == "CMP000001")
        self.assertEqual("committee_selection_pending", committee["status"])

    def test_outcome_is_idempotent_even_when_archive_reopened(self):
        self.save()
        self.seal()
        self.assertTrue(self.outcomes.record_completed(self.run)["inserted"])
        again = CareerCompetitionOutcomes(self.db_path)
        self.assertFalse(again.record_completed(self.run)["inserted"])
        self.assertEqual(
            list(SCHOOLS),
            again.previous_results(2026)[COMPETITION]["ranked_school_ids"],
        )
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(
                1, conn.execute(
                    "SELECT COUNT(*) FROM historical_competition_outcomes"
                ).fetchone()[0],
            )

    def test_unsealed_year_is_not_a_valid_source(self):
        self.save()
        with self.assertRaisesRegex(CareerOutcomeConflictError, "sealed"):
            self.outcomes.record_completed(self.run)
        with self.assertRaisesRegex(CareerOutcomeConflictError, "sealed"):
            build_future_blueprint_from_archive(
                ROOT / "data", year=2027, base_seed=7,
                match_archive=self.archive,
            )

    def test_missing_record_prevents_fabricated_rankings(self):
        self.save(self.records[:2])
        self.seal(2)
        with self.assertRaisesRegex(CareerOutcomeConflictError, "missing"):
            self.outcomes.record_completed(self.run)
        self.assertEqual({}, self.outcomes.previous_results(2026))

    def test_winner_mismatch_between_run_and_archived_score_is_rejected(self):
        rows = [dict(x) for x in self.records]
        rows[0]["winner_id"], rows[0]["loser_id"] = (
            rows[0]["loser_id"], rows[0]["winner_id"]
        )
        rows[0]["team1_score"], rows[0]["team2_score"] = 2, 4
        self.save(rows)
        self.seal()
        with self.assertRaisesRegex(CareerOutcomeConflictError, "disagrees"):
            self.outcomes.record_completed(self.run)

    def test_changed_school_or_stage_in_stored_record_is_rejected(self):
        rows = [dict(x) for x in self.records]
        rows[1]["stage_code"] = "BRANCH_QUALIFIER"
        self.save(rows)
        self.seal()
        with self.assertRaisesRegex(CareerOutcomeConflictError, "disagrees"):
            self.outcomes.record_completed(self.run)

    def test_changed_semifinal_ranking_does_not_overwrite(self):
        self.save()
        self.seal()
        self.outcomes.record_completed(self.run)
        different = complete_run()
        different.outcome.final_ranking_school_ids = [
            "SCH-A", "SCH-B", "SCH-D", "SCH-C",
        ]
        with self.assertRaisesRegex(CareerOutcomeConflictError, "changed"):
            self.outcomes.record_completed(different)
        self.assertEqual(
            list(SCHOOLS),
            self.outcomes.previous_results(2026)[COMPETITION]["ranked_school_ids"],
        )

    def test_unfinished_runtime_cannot_enter_qualification(self):
        self.save()
        self.seal()
        not_done = replace(self.run, outcome=None)
        with self.assertRaisesRegex(CareerOutcomeConflictError, "not completed"):
            self.outcomes.record_completed(not_done)
        self.assertEqual({}, self.outcomes.previous_results(2026))

    def test_final_ranking_must_cover_all_main_entrants(self):
        self.save()
        self.seal()
        bad = complete_run()
        bad.outcome.final_ranking_school_ids = ["SCH-A", "SCH-B"]
        with self.assertRaisesRegex(CareerOutcomeConflictError, "cover"):
            self.outcomes.record_completed(bad)
        bad = complete_run()
        bad.outcome.champion_school_id = "SCH-C"
        with self.assertRaisesRegex(CareerOutcomeConflictError, "champion"):
            self.outcomes.record_completed(bad)

    def test_final_winner_must_match_ranking(self):
        self.save()
        self.seal()
        bad = complete_run()
        bad.stage_executions[0].matches[-1].winner = "SCH-B"
        bad.stage_executions[0].matches[-1].loser = "SCH-A"
        with self.assertRaisesRegex(CareerOutcomeConflictError, "final"):
            self.outcomes.record_completed(bad)

    def test_tampered_sealed_match_ledger_fails_closed(self):
        self.save()
        self.seal()
        self.outcomes.record_completed(self.run)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE historical_matches SET record_sha256 = 'bad' "
                "WHERE match_id = 'M1'"
            )
        with self.assertRaisesRegex(CareerOutcomeConflictError, "ledger"):
            self.outcomes.previous_results(2026)

    def test_tampered_outcome_payload_is_rejected(self):
        self.save()
        self.seal()
        self.outcomes.record_completed(self.run)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE historical_competition_outcomes SET payload_json='{}'"
            )
        with self.assertRaisesRegex(CareerOutcomeConflictError, "fingerprint"):
            self.outcomes.previous_results(2026)

    def test_archived_year_without_completed_ranking_remains_unresolved(self):
        self.save()
        self.seal()
        future = build_future_blueprint_from_archive(
            ROOT / "data", year=2027, base_seed=12,
            match_archive=self.archive,
        )
        rule = next(x for x in future["prior_autumn_access"]
                    if x["access_rule_id"] == "ACR000004")
        self.assertEqual("unresolved", rule["status"])
        self.assertEqual([], rule["school_ids"])
        self.assertIn("ACR000004", future["unresolved_prior_rule_ids"])

    def test_other_six_rules_remain_independent_and_regional_rule_unresolved(self):
        self.save()
        self.seal()
        self.outcomes.record_completed(self.run)
        future = build_future_blueprint_from_archive(
            ROOT / "data", year=2027, base_seed=2,
            match_archive=self.archive,
        )
        resolved = [x for x in future["prior_autumn_access"]
                    if x["status"] == "resolved"]
        self.assertEqual(["ACR000004"],
                         [x["access_rule_id"] for x in resolved])
        region = next(x for x in future["prior_autumn_access"]
                      if x["access_rule_id"] == "ACR000015")
        self.assertEqual("unresolved", region["status"])
        self.assertEqual("unsupported_prior_year_selector", region["reason"])

    def test_only_previous_year_can_be_looked_up(self):
        self.save()
        self.seal()
        self.outcomes.record_completed(self.run)
        with self.assertRaisesRegex(CareerOutcomeConflictError, "sealed"):
            build_future_blueprint_from_archive(
                ROOT / "data", year=2028, base_seed=2,
                match_archive=self.archive,
            )

    def test_no_database_is_created_by_missing_history_check(self):
        result = self.outcomes.previous_results(2026)
        self.assertEqual({}, result)
        self.assertFalse(self.db_path.exists())


if __name__ == "__main__":
    unittest.main()
