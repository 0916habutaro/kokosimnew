from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.future_prior_autumn_access_bridge import (
    prepare_future_prior_autumn_bypass_preview,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.models import (
    CompetitionOutcome, CompetitionRun, Match, StageExecution,
)
from phase2_engine.repository import DataRepository


ROOT = Path(__file__).resolve().parents[1]
SPRING = "CMP000084"
AUTUMN = "CMP000085"
SEED = 2026100701


def autumn_run(schools):
    a, b, c, d = schools
    pairs = [(a, c, a), (b, d, b), (a, b, a)]
    matches = [
        Match(
            match_id=f"AUTUMN-{i}", competition_id=AUTUMN,
            stage_id="STG-AUTUMN-TEST", stage_code="MAIN",
            phase_code="MAIN_BRACKET",
            round_no=1 if i < 3 else 2,
            team1=x, team2=y, winner=winner,
            loser=y if winner == x else x,
        )
        for i, (x, y, winner) in enumerate(pairs, 1)
    ]
    run = CompetitionRun(
        competition_id=AUTUMN, year=2026, rng_seed=SEED,
        entrant_school_ids=list(schools), seed_assignments=[],
        stage_executions=[StageExecution(
            stage_id="STG-AUTUMN-TEST", stage_code="MAIN",
            format_model_id="MAIN_SINGLE_ELIMINATION",
            entrant_school_ids=list(schools), output_school_ids=[a],
            matches=matches,
        )],
        main_entrant_school_ids=list(schools),
        outcome=CompetitionOutcome(
            champion_school_id=a, runner_up_school_id=b,
            semifinalist_school_ids=[c, d],
            quarterfinalist_school_ids=[],
            final_ranking_school_ids=list(schools),
            eliminated_by_round={"1": [c, d], "2": [b]},
            match_count=3, bye_count=0, bracket_size=4,
        ),
    )
    records = []
    for m in matches:
        records.append({
            "competition_id": AUTUMN, "match_id": m.match_id,
            "competition_name": "ゲーム内2026秋大会",
            "match_date": "2026-10-15", "completed_on": "2026-10-15",
            "date_source": "game_projection_v1", "stage_code": "MAIN",
            "phase_code": "MAIN_BRACKET", "round_no": m.round_no,
            "status": "completed", "team1_id": m.team1, "team2_id": m.team2,
            "winner_id": m.winner, "loser_id": m.loser,
            "team1_score": 4, "team2_score": 2,
            "score_source": "generated_v1",
        })
    return run, records


class Stage43F5PriorAutumnAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        schools = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "08"
        )
        cls.direct = schools[:4]
        cls.entrants = schools[:39]
        cls.qualifiers = schools[4:39]
        cls.groups = cls.repo.groups_by_stage["STG000171"]
        assert len(cls.groups) == 4
        cls.group_members = {}
        start = 0
        for group, number in zip(cls.groups, [9, 9, 9, 8]):
            cls.group_members[group["stage_group_id"]] = cls.qualifiers[
                start:start + number
            ]
            start += number
        assert start == len(cls.qualifiers)
        cls.temp = tempfile.TemporaryDirectory()
        cls.match_archive = HistoricalMatchArchive(
            Path(cls.temp.name) / "historical_matches.sqlite3"
        )
        cls.rosters = CareerRosterArchive(
            Path(cls.temp.name) / "career_rosters.sqlite3"
        )
        run, records = autumn_run(cls.direct)
        cls.match_archive.sync(
            year=2026, rng_seed=42,
            resolver_contract="game_v1", plan_fingerprint="test-2026",
            completed=records,
        )
        cls.match_archive.seal_year(2026, expected_match_count=3)
        CareerCompetitionOutcomes(cls.match_archive).record_completed(run)
        generator = PlayerRosterGenerator()
        for sid in cls.entrants:
            initial = generator.generate_for_school_id(
                cls.repo, sid, 2026, SEED,
            )
            cls.rosters.save_initial_roster(initial)
            cls.rosters.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=SEED,
            )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def prepare(self, *, entrants=None, groups=None, match_archive=None,
                rosters=None, competition_id=SPRING, seed=SEED):
        return prepare_future_prior_autumn_bypass_preview(
            data_root=ROOT / "data", year=2027,
            competition_id=competition_id,
            entrant_school_ids=self.entrants if entrants is None else entrants,
            group_entrant_school_ids=(
                self.group_members if groups is None else groups
            ),
            match_archive=self.match_archive if match_archive is None else match_archive,
            roster_archive=self.rosters if rosters is None else rosters,
            repo=self.repo, base_seed=SEED, career_seed=seed,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )

    def test_2026_autumn_four_schools_bypass_2027_spring_qualifiers(self):
        preview = self.prepare()
        self.assertEqual(2027, preview.annual.year)
        self.assertEqual(self.direct, preview.annual.direct_main_entry_school_ids)
        self.assertEqual(39, len(preview.annual.entrant_school_ids))
        self.assertEqual([], preview.annual.main_seed_school_ids)
        self.assertEqual(self.group_members, preview.annual.group_entrant_school_ids)
        self.assertEqual(
            set(self.qualifiers), set(
                preview.scheduled.runtime.qualifier_entrant_school_ids
            ),
        )
        self.assertEqual(
            4, len(preview.scheduled.matches_for_date("2027-04-08"))
        )
        self.assertTrue(all(
            row["date_source"] == "game_projection_v1"
            for row in preview.scheduled.matches_for_date("2027-04-08")
        ))
        self.assertFalse(preview.snapshot()["official_competition"])

    def test_real_qualifier_results_plus_direct_entries_fill_main(self):
        preview = self.prepare()
        first = preview.play_next_date()
        self.assertEqual(4, first["played_match_count"])
        self.assertEqual("2027-04-08", first["date"])
        self.assertTrue(preview.scheduled.runtime.qualifier_complete)
        actual = preview.scheduled.runtime.main_entrant_school_ids
        self.assertEqual(35, len(actual))
        self.assertEqual(35, len(set(actual)))
        self.assertTrue(set(self.direct) <= set(actual))
        self.assertEqual(
            31, len(set(actual) - set(self.direct)),
        )
        self.assertTrue(
            set(actual) - set(self.direct) <= set(self.qualifiers)
        )
        self.assertFalse(set(self.direct) & set(
            preview.scheduled.runtime.qualifier_entrant_school_ids
        ))
        one = next(m for m in preview.scheduled.matches.values()
                   if m.status == "completed")
        self.assertEqual(2027, one.ability_detail["reference_year"])
        self.assertTrue(one.ability_detail["batter_stats"])
        self.assertIsNotNone(one.ability_detail["inning_scores"])
        roster_ids = {
            p.player_id
            for sid in (one.team1_id, one.team2_id)
            for p in self.rosters.roster(2027, sid).players
        }
        self.assertTrue({
            r["player_id"] for r in one.ability_detail["batter_stats"]
        } <= roster_ids)

    def test_same_seed_draw_is_deterministic(self):
        x, y = self.prepare(), self.prepare()
        self.assertEqual(x.scheduled.public_snapshot(),
                         y.scheduled.public_snapshot())

    def test_missing_autumn_saved_result_is_not_replaced_by_2026_standings(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = HistoricalMatchArchive(Path(tmp) / "history.sqlite3")
            db.sync(
                year=2026, rng_seed=1,
                resolver_contract="test", plan_fingerprint="test",
                completed=[],
            )
            db.seal_year(2026, expected_match_count=0)
            with self.assertRaisesRegex(FutureCompetitionNotReady, "not resolved"):
                self.prepare(match_archive=db)

    def test_unsealed_source_year_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = HistoricalMatchArchive(Path(tmp) / "history.sqlite3")
            db.sync(
                year=2026, rng_seed=1,
                resolver_contract="test", plan_fingerprint="test",
                completed=[],
            )
            with self.assertRaisesRegex(FutureCompetitionNotReady, "sealed"):
                self.prepare(match_archive=db)

    def test_direct_school_must_be_in_current_year_entrants(self):
        with self.assertRaisesRegex(FutureCompetitionNotReady, "direct school"):
            self.prepare(entrants=self.entrants[1:])

    def test_future_school_groups_must_exclude_direct_entry(self):
        wrong = deepcopy(self.group_members)
        gid = self.groups[0]["stage_group_id"]
        wrong[gid].append(self.direct[0])
        with self.assertRaisesRegex(FutureCompetitionNotReady, "partition"):
            self.prepare(groups=wrong)

    def test_missing_group_and_duplicate_or_unmapped_school_rejected(self):
        wrong = deepcopy(self.group_members)
        wrong.pop(self.groups[0]["stage_group_id"])
        with self.assertRaisesRegex(FutureCompetitionNotReady, "all future"):
            self.prepare(groups=wrong)
        wrong = deepcopy(self.group_members)
        a, b = self.groups[0]["stage_group_id"], self.groups[1]["stage_group_id"]
        wrong[b][0] = wrong[a][0]
        with self.assertRaisesRegex(FutureCompetitionNotReady, "partition"):
            self.prepare(groups=wrong)

    def test_changed_entrants_cannot_bypass_district_verification(self):
        with self.assertRaisesRegex(FutureCompetitionNotReady, "partition"):
            self.prepare(entrants=self.entrants[:-1])
        new_school = next(
            sid for sid in self.repo.school_to_program
            if self.repo.schools[sid]["prefecture_code"] == "09"
        )
        with self.assertRaisesRegex(FutureCompetitionNotReady, "prefecture"):
            self.prepare(entrants=self.entrants[:-1] + [new_school])

    def test_mismatched_roster_seed_prevents_bypass(self):
        with self.assertRaisesRegex(FutureCompetitionNotReady, "rosters"):
            self.prepare(seed=SEED + 1)

    def test_autumn_rule_does_not_automatically_create_seed_rank(self):
        preview = self.prepare()
        self.assertEqual(self.direct, preview.annual.direct_main_entry_school_ids)
        self.assertEqual([], preview.annual.main_seed_school_ids)
        self.assertEqual([], preview.annual.seed_event_bypass_school_ids)

    def test_another_2027_competition_cannot_use_autumn_ibaraki_result(self):
        with self.assertRaisesRegex(FutureCompetitionNotReady, "not resolved"):
            self.prepare(competition_id="CMP000090")

    def test_missing_roster_archive_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = CareerRosterArchive(Path(tmp) / "rosters.sqlite3")
            with self.assertRaisesRegex(FutureCompetitionNotReady, "rosters"):
                self.prepare(rosters=empty)
            self.assertFalse(empty.db_path.exists())


if __name__ == "__main__":
    unittest.main()
