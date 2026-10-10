from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_access_capability_audit import audit_future_autumn_access_capabilities
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.future_prior_autumn_access_bridge import (
    prepare_future_prior_autumn_bypass_preview,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.models import CompetitionOutcome, CompetitionRun, Match, StageExecution
from phase2_engine.repository import DataRepository

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026100701
TOKYO_PRIOR = "GAME-TOKYO-AUTUMN-2026"


def simulated_autumn_run(cid, school_ids):
    """Generate a completed and internally consistent *game* ranking.

    This fixture is deliberately not a representation of real results.
    All rounds and winners are saved and checked by Stage43F-4's validator.
    """
    active = list(school_ids)
    matches = []
    knocked_out = defaultdict(list)
    round_no = 1
    while len(active) > 1:
        winners = []
        for i in range(0, len(active), 2):
            a, b = active[i:i + 2]
            winners.append(a)
            knocked_out[round_no].append(b)
            matches.append(Match(
                match_id=f"{cid}-M{len(matches) + 1:03d}",
                competition_id=cid,
                stage_id="STG-SANDBOX-AUTUMN",
                stage_code="MAIN", phase_code="MAIN_BRACKET",
                round_no=round_no, team1=a, team2=b,
                winner=a, loser=b,
            ))
        active = winners
        round_no += 1
    ranks = [active[0]]
    for number in sorted(knocked_out, reverse=True):
        ranks.extend(knocked_out[number])
    outcome = CompetitionOutcome(
        champion_school_id=ranks[0],
        runner_up_school_id=ranks[1],
        semifinalist_school_ids=ranks[2:4],
        quarterfinalist_school_ids=ranks[4:8],
        final_ranking_school_ids=ranks,
        eliminated_by_round={
            str(num): list(ids) for num, ids in knocked_out.items()
        },
        match_count=len(matches), bye_count=0, bracket_size=len(school_ids),
    )
    result = CompetitionRun(
        competition_id=cid, year=2026, rng_seed=SEED,
        entrant_school_ids=list(school_ids), seed_assignments=[],
        stage_executions=[StageExecution(
            stage_id="STG-SANDBOX-AUTUMN", stage_code="MAIN",
            format_model_id="MAIN_SINGLE_ELIMINATION",
            entrant_school_ids=list(school_ids),
            output_school_ids=[ranks[0]], matches=matches,
        )],
        main_entrant_school_ids=list(school_ids), outcome=outcome,
    )
    rows = [{
        "competition_id": cid, "match_id": m.match_id,
        "competition_name": "試験用ゲーム内2026秋季大会",
        "match_date": "2026-10-10", "completed_on": "2026-10-10",
        "date_source": "game_projection_v1",
        "status": "completed", "stage_code": "MAIN",
        "phase_code": "MAIN_BRACKET", "round_no": m.round_no,
        "team1_id": m.team1, "team2_id": m.team2,
        "winner_id": m.winner, "loser_id": m.loser,
        "team1_score": 4, "team2_score": 2,
        "score_source": "generated_v1",
    } for m in matches]
    return result, rows


class Stage43F7GifuTokyoFutureAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.temp = tempfile.TemporaryDirectory()
        cls.matches = HistoricalMatchArchive(
            Path(cls.temp.name) / "historical_matches.sqlite3"
        )
        cls.rosters = CareerRosterArchive(
            Path(cls.temp.name) / "career_rosters.sqlite3"
        )
        cls.cases = {}
        generator = PlayerRosterGenerator()
        saved_ids = set()
        runs = []
        records = []

        for cid, pcode, direct_count, source in [
            ("CMP000109", "21", 4, "CMP000110"),
            ("CMP000094", "13", 64, TOKYO_PRIOR),
        ]:
            eligible = sorted(
                sid for sid in cls.repo.school_to_program
                if cls.repo.schools[sid]["prefecture_code"] == pcode
            )
            # Synthetic annual population, never actual 2027 entrants.
            if cid == "CMP000109":
                source_schools = eligible[:4]
                qualifier = eligible[4:44]
            else:
                source_schools = eligible[:64]
                qualifier = eligible[64:112]
            run, matches = simulated_autumn_run(source, source_schools)
            runs.append(run)
            records.extend(matches)

            stages = cls.repo.stages(cid)
            pre = next(s for s in stages if s["stage_code"] != "MAIN")
            groups = cls.repo.groups_by_stage[pre["stage_id"]]
            mapping = {}
            start = 0
            if cid == "CMP000109":
                # All 4 FMT002 district blocks get nontrivial primary and
                # repechage rounds: 2 * (8,4,5,3) entrants respectively.
                for group in groups:
                    slots = int(group["advance_slots_to_next"])
                    mapping[group["stage_group_id"]] = qualifier[
                        start:start + 2 * slots
                    ]
                    start += 2 * slots
            else:
                self_group = groups[0]
                self_key = self_group["stage_group_id"]
                mapping[self_key] = list(qualifier)
                start = len(qualifier)
            assert start == len(qualifier)
            entrants = list(source_schools) + list(qualifier)
            cls.cases[cid] = {
                "direct": list(run.outcome.final_ranking_school_ids[:direct_count]),
                "entrants": entrants,
                "group_entrant_school_ids": mapping,
                "source": source,
                "qualifier_count": len(qualifier),
                "stage_code": pre["stage_code"],
                "stage_id": pre["stage_id"],
                "group_count": len(groups),
            }
            for school in entrants:
                if school in saved_ids:
                    continue
                saved_ids.add(school)
                initial = generator.generate_for_school_id(
                    cls.repo, school, 2026, SEED,
                )
                cls.rosters.save_initial_roster(initial)
                cls.rosters.advance_and_save(
                    cls.repo.team(school), next_year=2027, career_seed=SEED,
                )
        cls.matches.sync(
            year=2026, rng_seed=42, resolver_contract="game_v1",
            plan_fingerprint="stage43f7-sandbox",
            completed=records,
        )
        cls.matches.seal_year(2026, expected_match_count=len(records))
        writer = CareerCompetitionOutcomes(cls.matches)
        for run in runs:
            writer.record_completed(run)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def prepare(self, cid, **override):
        case = self.cases[cid]
        args = {
            "data_root": ROOT / "data", "year": 2027,
            "competition_id": cid,
            "entrant_school_ids": case["entrants"],
            "group_entrant_school_ids": case["group_entrant_school_ids"],
            "match_archive": self.matches,
            "roster_archive": self.rosters,
            "repo": self.repo,
            "base_seed": SEED, "career_seed": SEED,
            "ability_config_dir": ROOT / "config" / "abilities",
            "match_config_dir": ROOT / "config" / "match",
            "prior_source_competition_id": TOKYO_PRIOR if cid == "CMP000094" else None,
        }
        args.update(override)
        return prepare_future_prior_autumn_bypass_preview(**args)

    def test_gifu_fmt002_from_sealed_top_four_and_two_part_qualification(self):
        cid = "CMP000109"
        preview = self.prepare(cid)
        self.assertEqual(2027, preview.annual.year)
        self.assertEqual(self.cases[cid]["direct"],
                         preview.annual.direct_main_entry_school_ids)
        self.assertEqual(44, len(preview.annual.entrant_school_ids))
        self.assertEqual(40, len(preview.scheduled.runtime.qualifier_entrant_school_ids))
        self.assertEqual(4, len(preview.scheduled.runtime.qualifier_groups))
        self.assertTrue(all(
            group.format_model_id == "FMT002"
            for group in preview.scheduled.runtime.qualifier_groups
        ))
        self.assertEqual("2027-03-20", preview.scheduled.next_scheduled_date())
        count = 0
        stages_seen = set()
        while preview.scheduled.runtime.main_runtime is None and count < 10:
            step = preview.play_next_date()
            stages_seen.add(step["date_source"])
            count += 1
        self.assertIsNotNone(preview.scheduled.runtime.main_runtime)
        self.assertEqual({"game_projection_v1"}, stages_seen)
        main = preview.scheduled.runtime.main_entrant_school_ids
        self.assertEqual(24, len(main))
        self.assertTrue(set(self.cases[cid]["direct"]) <= set(main))
        self.assertEqual([], preview.annual.main_seed_school_ids)
        self.assertFalse(preview.snapshot()["official_competition"])

    def test_tokyo_47_preliminary_representatives_plus_64_direct(self):
        cid = "CMP000094"
        preview = self.prepare(cid)
        case = self.cases[cid]
        self.assertEqual(112, len(preview.annual.entrant_school_ids))
        self.assertEqual(64, len(preview.annual.direct_main_entry_school_ids))
        self.assertEqual(48, len(preview.scheduled.runtime.qualifier_entrant_school_ids))
        self.assertEqual("2027-03-14", preview.scheduled.next_scheduled_date())
        self.assertEqual(1, len(preview.scheduled.matches_for_date("2027-03-14")))
        step = preview.play_next_date()
        self.assertEqual(1, step["played_match_count"])
        self.assertTrue(preview.scheduled.runtime.qualifier_complete)
        main = preview.scheduled.runtime.main_entrant_school_ids
        self.assertEqual(111, len(main))
        self.assertEqual(111, len(set(main)))
        self.assertTrue(set(case["direct"]) <= set(main))
        self.assertEqual(47, len(set(main) - set(case["direct"])))
        self.assertFalse(set(case["direct"]) & set(
            preview.scheduled.runtime.qualifier_entrant_school_ids
        ))
        self.assertEqual("2027-04-01", preview.scheduled.next_scheduled_date())
        self.assertFalse(preview.snapshot()["official_competition"])
        rec = next(m for m in preview.scheduled.matches.values()
                   if m.status == "completed")
        self.assertEqual(2027, rec.ability_detail["reference_year"])
        self.assertTrue(rec.ability_detail["batter_stats"])
        self.assertIsNotNone(rec.ability_detail["inning_scores"])

    def test_tokyo_requires_explicit_prior_game_source_not_2026_master(self):
        with self.assertRaisesRegex(
            FutureCompetitionNotReady, "explicitly bound",
        ):
            self.prepare("CMP000094", prior_source_competition_id=None)
        with self.assertRaisesRegex(
            FutureCompetitionNotReady, "64 verified",
        ):
            self.prepare(
                "CMP000094", prior_source_competition_id="CMP000110",
            )
        with self.assertRaisesRegex(
            FutureCompetitionNotReady, "64 verified",
        ):
            self.prepare(
                "CMP000094",
                prior_source_competition_id="GAME-NOT-IN-ARCHIVE",
            )

    def test_gifu_cannot_override_source_and_tokyo_cannot_override_qualifier(self):
        with self.assertRaisesRegex(FutureCompetitionNotReady, "only for Tokyo"):
            self.prepare("CMP000109", prior_source_competition_id=TOKYO_PRIOR)
        group_id = next(iter(
            self.cases["CMP000094"]["group_entrant_school_ids"]
        ))
        with self.assertRaisesRegex(FutureCompetitionNotReady, "explicit non-direct"):
            self.prepare("CMP000094", group_entrant_school_ids={
                group_id: [],
            })
        original = self.cases["CMP000094"]["group_entrant_school_ids"][group_id]
        with self.assertRaisesRegex(FutureCompetitionNotReady, "partition"):
            self.prepare("CMP000094", group_entrant_school_ids={
                group_id: original[:-1],
            })

    def test_repeatable_initial_draw_from_same_seed(self):
        for cid in self.cases:
            with self.subTest(cid=cid):
                first, second = self.prepare(cid), self.prepare(cid)
                self.assertEqual(
                    first.scheduled.public_snapshot(),
                    second.scheduled.public_snapshot(),
                )

    def test_different_prefecture_prior_game_cannot_be_used_for_tokyo(self):
        case = self.cases["CMP000094"]
        changed = list(case["entrants"])
        for sid in self.cases["CMP000109"]["direct"]:
            if sid not in changed:
                changed[-1] = sid
                break
        with self.assertRaises(FutureCompetitionNotReady):
            self.prepare(
                "CMP000094",
                entrant_school_ids=changed,
                prior_source_competition_id="CMP000110",
            )

    def test_missing_2027_roster_does_not_generate_new_player_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = CareerRosterArchive(Path(tmp) / "rosters.sqlite3")
            with self.assertRaisesRegex(FutureCompetitionNotReady, "rosters"):
                self.prepare("CMP000109", roster_archive=empty)
            self.assertFalse(empty.db_path.exists())

    def test_future_rule_audit_remains_separate_from_seed_contract(self):
        report = audit_future_autumn_access_capabilities(
            self.repo, year=2027,
        )
        by_comp = {r["competition_id"]: r for r in report["access_rules"]}
        self.assertEqual("FMT002", by_comp["CMP000109"]["qualifier_model"])
        self.assertEqual("PRELIMINARY_QUALIFIER",
                         by_comp["CMP000094"]["first_stage"])
        self.assertEqual([], by_comp["CMP000094"]["main_seed_school_ids"])
        self.assertFalse(report["main_seed_order_auto_assigned"])


if __name__ == "__main__":
    unittest.main()
