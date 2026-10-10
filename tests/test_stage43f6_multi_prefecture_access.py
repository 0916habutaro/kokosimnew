from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_access_capability_audit import (
    audit_future_autumn_access_capabilities,
)
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
SEED = 2026100701
# The six top-N rules have four FMT001 branch competitions, FMT002 Gifu,
# and a PRELIMINARY Tokyo graph. Ibaraki was exercised in Stage43F-5.
TARGETS = OrderedDict([
    ("CMP000090", ("11", 8, 4, 48, "2027-04-10")),
    ("CMP000092", ("12", 8, 8, 48, "2027-04-02")),
    ("CMP000133", ("33", 8, 3, 24, "2027-04-11")),
])


def prior_autumn_run(competition_id, schools):
    a, b, c, d, e, f, g, h = schools
    games = [
        (a, e, a, 1), (b, f, b, 1),
        (c, g, c, 1), (d, h, d, 1),
        (a, c, a, 2), (b, d, b, 2),
        (a, b, a, 3),
    ]
    matches = [
        Match(
            match_id=f"{competition_id}-GAME-{i}",
            competition_id=competition_id, stage_id="STG-AUTUMN-SANDBOX",
            stage_code="MAIN", phase_code="MAIN_BRACKET", round_no=round_no,
            team1=x, team2=y, winner=winner,
            loser=y if winner == x else x,
        )
        for i, (x, y, winner, round_no) in enumerate(games, 1)
    ]
    run = CompetitionRun(
        competition_id=competition_id, year=2026, rng_seed=SEED,
        entrant_school_ids=list(schools), seed_assignments=[],
        stage_executions=[
            StageExecution(
                stage_id="STG-AUTUMN-SANDBOX", stage_code="MAIN",
                format_model_id="MAIN_SINGLE_ELIMINATION",
                entrant_school_ids=list(schools),
                output_school_ids=[a], matches=matches,
            ),
        ],
        main_entrant_school_ids=list(schools),
        outcome=CompetitionOutcome(
            champion_school_id=a, runner_up_school_id=b,
            semifinalist_school_ids=[c, d],
            quarterfinalist_school_ids=[e, f, g, h],
            final_ranking_school_ids=list(schools),
            eliminated_by_round={"1": [e, f, g, h], "2": [c, d], "3": [b]},
            match_count=7, bye_count=0, bracket_size=8,
        ),
    )
    rows = [
        {
            "competition_id": competition_id, "match_id": m.match_id,
            "competition_name": "2026ゲーム内秋県大会（試験用）",
            "match_date": "2026-10-15", "completed_on": "2026-10-15",
            "date_source": "game_projection_v1", "stage_code": "MAIN",
            "phase_code": "MAIN_BRACKET", "round_no": m.round_no,
            "status": "completed", "team1_id": m.team1, "team2_id": m.team2,
            "winner_id": m.winner, "loser_id": m.loser,
            "team1_score": 4, "team2_score": 2,
            "score_source": "generated_v1",
        }
        for m in matches
    ]
    return run, rows


class Stage43F6MultiPrefectureAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.temp = tempfile.TemporaryDirectory()
        cls.match_archive = HistoricalMatchArchive(
            Path(cls.temp.name) / "history.sqlite3"
        )
        cls.rosters = CareerRosterArchive(
            Path(cls.temp.name) / "career_rosters.sqlite3"
        )
        cls.cases = {}
        history_rows = []
        runs = []
        generator = PlayerRosterGenerator()

        for cid, (pcode, rank_count, group_count, expected_main, start) in TARGETS.items():
            rules = cls.repo.access_rules(cid)
            assert len(rules) == 1 and rules[0]["source_year_offset"] == "-1"
            autumn_comp = next(
                k for k, row in cls.repo.competitions.items()
                if row["reference_year"] == "2026"
                and row["competition_type"] == "autumn_prefectural"
                and row["prefecture_code"] == pcode
            )
            candidates = sorted(
                school for school in cls.repo.school_to_program
                if cls.repo.schools[school]["prefecture_code"] == pcode
            )
            direct = candidates[:rank_count]
            stages = cls.repo.stages(cid)
            qualifier = next(s for s in stages if s["stage_code"] == "BRANCH_QUALIFIER")
            groups = cls.repo.groups_by_stage[qualifier["stage_id"]]
            assert len(groups) == group_count
            members = {}
            pos = rank_count
            quota = 0
            for group in groups:
                gid = group["stage_group_id"]
                slots = cls.repo.param(
                    qualifier["stage_id"], "output_slots", gid,
                    int(group["advance_slots_to_next"]),
                )
                quota += slots
                # One extra competitor per group forces one real match
                # while keeping the sandbox cohort reasonably small.
                members[gid] = candidates[pos:pos + slots + 1]
                pos += slots + 1
            entrants = candidates[:pos]
            assert len(entrants) == pos and quota + rank_count == expected_main
            assert all(members.values())
            cls.cases[cid] = {
                "direct": direct, "groups": members, "entrants": entrants,
                "first_date": start, "expected_main": expected_main,
                "group_count": group_count, "autumn": autumn_comp,
            }
            run, rows = prior_autumn_run(autumn_comp, direct)
            runs.append(run)
            history_rows.extend(rows)
            for sid in entrants:
                roster = generator.generate_for_school_id(
                    cls.repo, sid, 2026, SEED,
                )
                cls.rosters.save_initial_roster(roster)
                cls.rosters.advance_and_save(
                    cls.repo.team(sid), next_year=2027, career_seed=SEED,
                )

        cls.match_archive.sync(
            year=2026, rng_seed=42, resolver_contract="game_v1",
            plan_fingerprint="stage43f6-three-prefectures",
            completed=history_rows,
        )
        cls.match_archive.seal_year(
            2026, expected_match_count=len(history_rows),
        )
        writer = CareerCompetitionOutcomes(cls.match_archive)
        for run in runs:
            assert writer.record_completed(run)["inserted"]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def prepare(self, cid, **overrides):
        case = self.cases[cid]
        args = {
            "data_root": ROOT / "data",
            "year": 2027, "competition_id": cid,
            "entrant_school_ids": case["entrants"],
            "group_entrant_school_ids": case["groups"],
            "match_archive": self.match_archive,
            "roster_archive": self.rosters,
            "repo": self.repo,
            "base_seed": SEED, "career_seed": SEED,
            "ability_config_dir": ROOT / "config" / "abilities",
            "match_config_dir": ROOT / "config" / "match",
        }
        args.update(overrides)
        return prepare_future_prior_autumn_bypass_preview(**args)

    def test_all_three_prefectures_have_eight_direct_entries_but_no_auto_seeds(self):
        for cid, case in self.cases.items():
            with self.subTest(cid=cid):
                preview = self.prepare(cid)
                self.assertEqual(case["direct"],
                                 preview.annual.direct_main_entry_school_ids)
                self.assertEqual([], preview.annual.main_seed_school_ids)
                self.assertEqual([], preview.annual.seed_event_bypass_school_ids)
                self.assertEqual(case["groups"],
                                 preview.annual.group_entrant_school_ids)
                self.assertEqual(2027, preview.annual.year)
                self.assertFalse(preview.snapshot()["official_competition"])
                self.assertFalse(preview.snapshot()["persistent_game_session"])
                self.assertEqual(
                    set(case["entrants"]) - set(case["direct"]),
                    set(preview.scheduled.runtime.qualifier_entrant_school_ids),
                )

    def test_all_three_prefectures_advance_group_winners_into_main(self):
        for cid, case in self.cases.items():
            with self.subTest(cid=cid):
                preview = self.prepare(cid)
                first = preview.play_next_date()
                self.assertEqual(case["first_date"], first["date"])
                self.assertEqual("game_projection_v1", first["date_source"])
                self.assertEqual(case["group_count"], first["played_match_count"])
                self.assertTrue(preview.scheduled.runtime.qualifier_complete)
                actual = preview.scheduled.runtime.main_entrant_school_ids
                self.assertEqual(case["expected_main"], len(actual))
                self.assertEqual(len(actual), len(set(actual)))
                self.assertTrue(set(case["direct"]) <= set(actual))
                self.assertTrue(set(actual) - set(case["direct"])
                                <= set(case["entrants"]) - set(case["direct"]))
                played = [
                    m for m in preview.scheduled.matches.values()
                    if m.status == "completed"
                ]
                self.assertEqual(case["group_count"], len(played))
                self.assertTrue(all(
                    m.date_source == "game_projection_v1"
                    and m.ability_detail["reference_year"] == 2027
                    and m.ability_detail["batter_stats"]
                    and m.ability_detail["inning_scores"]
                    for m in played
                ))

    def test_repeatable_brackets_for_all_destinations(self):
        for cid in TARGETS:
            with self.subTest(cid=cid):
                self.assertEqual(
                    self.prepare(cid).scheduled.public_snapshot(),
                    self.prepare(cid).scheduled.public_snapshot(),
                )

    def test_audit_marks_four_fmt001_and_does_not_claim_real_2027_rules(self):
        result = audit_future_autumn_access_capabilities(
            self.repo, year=2027,
        )
        self.assertEqual(6, result["access_rule_count"])
        self.assertEqual(4, result["sandbox_fmt001_supported_count"])
        self.assertFalse(result["official_future_year_rules_verified"])
        self.assertFalse(result["live_runtime_ready"])
        self.assertFalse(result["main_seed_order_auto_assigned"])
        by_id = {r["competition_id"]: r for r in result["access_rules"]}
        for cid in ("CMP000084", *TARGETS):
            self.assertEqual(
                "sandbox_fmt001_supported", by_id[cid]["access_status"]
            )
            self.assertEqual([], by_id[cid]["main_seed_school_ids"])
            self.assertEqual(
                "separate_destination_seed_contract_required",
                by_id[cid]["main_seed_assignment_status"],
            )
        self.assertEqual("FMT002", by_id["CMP000109"]["qualifier_model"])
        self.assertEqual(
            "sandbox_fmt002_supported",
            by_id["CMP000109"]["access_status"],
        )
        self.assertEqual(
            "sandbox_preliminary_explicit_source_supported",
            by_id["CMP000094"]["access_status"],
        )
        self.assertEqual(1, result["sandbox_fmt002_supported_count"])
        self.assertEqual(1, result["sandbox_preliminary_explicit_source_count"])
        self.assertEqual(64, by_id["CMP000094"]["direct_main_entry_count"])

    def test_audit_does_not_repeat_2026_or_allow_invalid_year(self):
        for year in (2026, 10000, True):
            with self.subTest(year=year), self.assertRaises(ValueError):
                audit_future_autumn_access_capabilities(self.repo, year=year)

    def test_linked_seed_rules_block_unverified_seed_policy(self):
        cid = "CMP000090"
        base = self.repo.seed_rules
        rule = {
            "seed_rule_id": "SEED-FUTURE-UNVERIFIED",
            "linked_access_rule_id": "ACR000005",
            "effective_from_year": "2026",
            "effective_to_year": "",
        }
        with patch.object(
            self.repo, "seed_rules",
            side_effect=lambda comp: ([rule] if comp == cid else base(comp)),
        ):
            report = audit_future_autumn_access_capabilities(
                self.repo, year=2027,
            )
            entry = next(x for x in report["access_rules"]
                         if x["competition_id"] == cid)
            self.assertEqual(
                "linked_seed_rule_requires_separate_validation",
                entry["access_status"],
            )
            with self.assertRaisesRegex(
                FutureCompetitionNotReady, "linked MAIN seed",
            ):
                self.prepare(cid)

    def test_disjoint_prefectures_do_not_use_each_others_previous_results(self):
        case = self.cases["CMP000090"]
        with self.assertRaisesRegex(FutureCompetitionNotReady, "direct school"):
            self.prepare(
                "CMP000092",
                entrant_school_ids=case["entrants"],
                group_entrant_school_ids=case["groups"],
            )

    def test_never_uses_unregistered_2027_rosters(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = CareerRosterArchive(Path(tmp) / "none.sqlite3")
            with self.assertRaisesRegex(FutureCompetitionNotReady, "rosters"):
                self.prepare("CMP000133", roster_archive=empty)
            self.assertFalse(empty.db_path.exists())

    def test_missing_current_year_group_cannot_fall_back_to_2026(self):
        case = self.cases["CMP000092"]
        bad = dict(case["groups"])
        bad.pop(next(iter(bad)))
        with self.assertRaisesRegex(FutureCompetitionNotReady, "all future"):
            self.prepare("CMP000092", group_entrant_school_ids=bad)


if __name__ == "__main__":
    unittest.main()
