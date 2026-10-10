from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService, CareerPreviewSaveError,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.chiba_third_place_checkpoint import (
    ChibaThirdPlaceCheckpointService, ChibaThirdPlaceNotReady,
)
from phase2_engine.same_year_regional_feeder_gate import (
    project_same_year_regional_feeders, RegionalFeederNotReady,
)
from phase2_engine.future_kanagawa_invitational_access import (
    audit_kanagawa_spring_access,
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



class Stage43G6ChibaTokyoMultiSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.fixture = tempfile.TemporaryDirectory()
        root = Path(cls.fixture.name)
        cls.history_file = root / "history.sqlite3"
        cls.roster_file = root / "rosters.sqlite3"
        history = HistoricalMatchArchive(cls.history_file)
        archive = CareerRosterArchive(cls.roster_file)
        generator = PlayerRosterGenerator()
        cls.competitions = []
        rows = []
        results = []

        for cid, pcode, source, direct_n in (
            ("CMP000092", "12", None, 8),
            ("CMP000094", "13", TOKYO_PRIOR, 64),
        ):
            schools = sorted(
                sid for sid in cls.repo.school_to_program
                if cls.repo.schools[sid]["prefecture_code"] == pcode
            )
            if source is None:
                source = next(
                    key for key, value in cls.repo.competitions.items()
                    if value.get("competition_type") == "autumn_prefectural"
                    and value.get("prefecture_code") == pcode
                )
            direct = schools[:direct_n]
            run, games = simulated_autumn_run(source, direct)
            results.append(run)
            rows.extend(games)
            stages = cls.repo.stages(cid)
            qual = next(stage for stage in stages
                        if stage["stage_code"] != "MAIN")
            groups = cls.repo.groups_by_stage[qual["stage_id"]]
            allocation = {}
            offset = direct_n
            for group in groups:
                n = cls.repo.param(
                    qual["stage_id"], "output_slots",
                    group["stage_group_id"],
                    int(group["advance_slots_to_next"]),
                ) + 1
                allocation[group["stage_group_id"]] = schools[offset:offset+n]
                offset += n
            entrants = schools[:offset]
            assert len(entrants) == (56 if cid == "CMP000092" else 112)
            assert all(allocation.values())
            for sid in entrants:
                initial = generator.generate_for_school_id(
                    cls.repo, sid, 2026, SEED,
                )
                archive.save_initial_roster(initial)
                archive.advance_and_save(
                    cls.repo.team(sid), next_year=2027, career_seed=SEED,
                )
            cls.competitions.append({
                "competition_id": cid,
                "entry_mode": "prior_autumn_bypass_v1",
                "entrant_school_ids": entrants,
                "group_entrant_school_ids": allocation,
                "prior_source_competition_id": (
                    TOKYO_PRIOR if cid == "CMP000094" else None
                ),
            })

        history.sync(
            year=2026, rng_seed=42, resolver_contract="game_v1",
            plan_fingerprint="stage43g6-two-autumn-games",
            completed=rows,
        )
        history.seal_year(2026, expected_match_count=len(rows))
        writer = CareerCompetitionOutcomes(history)
        for run in results:
            writer.record_completed(run)
        cls.original_2026_count = len(rows)

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

    def tearDown(self):
        self.temp.cleanup()

    def start(self, specs=None):
        return self.service.start(
            "career_slot", year=2027,
            competitions=self.competitions if specs is None else specs,
            base_seed=SEED, career_seed=SEED,
        )

    def test_joint_2027_save_uses_8_chiba_and_64_tokyo_exemptions(self):
        session = self.start()
        self.assertEqual(
            ["CMP000092", "CMP000094"], session.summary()["competition_ids"]
        )
        chiba = session.previews["CMP000092"]
        tokyo = session.previews["CMP000094"]
        self.assertEqual(8, len(chiba.annual.direct_main_entry_school_ids))
        self.assertEqual(40, sum(
            self.repo.param("STG000175", "output_slots", gid, 0)
            for gid in chiba.annual.group_entrant_school_ids
        ))
        self.assertEqual(64, len(tokyo.annual.direct_main_entry_school_ids))
        self.assertEqual(48, len(tokyo.scheduled.runtime.qualifier_entrant_school_ids))
        self.assertEqual(111, len(tokyo.annual.direct_main_entry_school_ids)+47)
        self.assertEqual([], tokyo.annual.main_seed_school_ids)
        self.assertEqual([], chiba.annual.main_seed_school_ids)
        self.assertFalse(session.summary()["full_year_gameplay"])
        self.assertFalse(session.summary()["official_future_calendar"])
        hist = HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")
        self.assertEqual(self.original_2026_count, len(hist.list_matches(2026)))
        self.assertEqual([], hist.list_matches(2027))
        self.assertEqual("sealed", hist.list_years()[0]["status"])

    def test_joint_game_dates_save_and_restore_real_match_stats(self):
        session = self.start()
        first = self.service.play_next_date(session)
        self.assertEqual("2027-03-14", first["date"])
        self.assertEqual({"CMP000094": 1}, first["competition_match_counts"])
        # Subsequent Tokyo MAIN rounds and Chiba qualifiers share one global
        # date queue and one append-only game archive.
        for _ in range(3):
            self.service.play_next_date(session)
        history = HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")
        rows = history.list_matches(2027)
        self.assertGreater(len(rows), 2)
        self.assertTrue(all(x["date_source"] == "game_projection_v1" for x in rows))
        self.assertTrue(any(x["batter_stats"] and x["pitcher_stats"] for x in rows))
        old = {
            cid: p.scheduled.public_snapshot() for cid,p in session.previews.items()
        }
        resumed = self.service.load("career_slot", year=2027)
        self.assertEqual(old, {
            cid: p.scheduled.public_snapshot() for cid,p in resumed.previews.items()
        })
        next_step = self.service.play_next_date(resumed)
        self.assertGreater(next_step["date"], first["date"])
        self.assertEqual(len(history.list_matches(2027)),
                         next_step["checkpoint"]["completed_match_count"])
        self.assertEqual(self.original_2026_count, len(history.list_matches(2026)))

    def test_chiba_top_eight_and_tokyo_top_sixty_four_not_in_preliminary(self):
        session = self.start()
        for cid in ("CMP000092", "CMP000094"):
            p = session.previews[cid]
            self.assertFalse(set(p.annual.direct_main_entry_school_ids) &
                             set(p.scheduled.runtime.qualifier_entrant_school_ids))
            self.assertEqual(set(p.annual.entrant_school_ids), (
                set(p.annual.direct_main_entry_school_ids) |
                set(p.scheduled.runtime.qualifier_entrant_school_ids)
            ))

    def test_tokyo_missing_or_invalid_autumn_source_rejected_before_creation(self):
        for value in (None, "", "CMP000092", "GAME-DOES-NOT-EXIST"):
            with self.subTest(source=value):
                specs = [dict(x) for x in self.competitions]
                tokyo = next(x for x in specs if x["competition_id"] == "CMP000094")
                tokyo["prior_source_competition_id"] = value
                with self.assertRaises((CareerPreviewSaveError, ValueError)):
                    self.start(specs)
                self.assertFalse(
                    (self.slot / "career_multi_previews" / "2027.json").exists()
                )
        self.assertFalse(
            (self.slot / "career_multi_previews" / "2027.json").exists()
        )

    def test_chiba_cannot_substitute_arbitrary_previous_source(self):
        specs = [dict(x) for x in self.competitions]
        specs[0]["prior_source_competition_id"] = TOKYO_PRIOR
        with self.assertRaisesRegex(CareerPreviewSaveError, "Chiba"):
            self.start(specs)

    def test_provisional_joint_save_can_be_loaded_twice_deterministically(self):
        self.start()
        a = self.service.load("career_slot", year=2027)
        b = self.service.load("career_slot", year=2027)
        self.assertEqual(
            {cid: p.scheduled.public_snapshot() for cid,p in a.previews.items()},
            {cid: p.scheduled.public_snapshot() for cid,p in b.previews.items()}
        )
        self.service.play_next_date(a)
        with self.assertRaisesRegex(CareerPreviewSaveError, "another"):
            self.service.play_next_date(b)

    def test_kanagawa_senbatsu_bypass_stays_unresolved_and_does_not_infer_zero(self):
        audit = audit_kanagawa_spring_access(self.repo, year=2027)
        self.assertEqual("ACR000008", audit["access_rule_id"])
        self.assertEqual("CMP000001", audit["source_competition_id"])
        self.assertEqual(2027, audit["source_year"])
        self.assertEqual(
            "requires_same_year_verified_invitational_participants",
            audit["status"],
        )
        self.assertFalse(audit["no_record_interpreted_as_zero_participants"])
        self.assertFalse(audit["automatic_bypass_enabled"])
        self.assertFalse(audit["runtime_ready"])
        self.assertEqual([], audit["main_seed_school_ids"])
        self.assertEqual([], audit["direct_main_school_ids"])
        with self.assertRaisesRegex(CareerPreviewSaveError, "whitelisted"):
            spec = dict(self.competitions[0])
            spec["competition_id"] = "CMP000095"
            spec["entry_mode"] = "kanto_direct_main_v1"
            self.start([self.competitions[1], spec])

    def test_unknown_future_year_and_invalid_kanagawa_contract_rejected(self):
        for year in (2026, 10000, True):
            with self.subTest(year=year), self.assertRaises(ValueError):
                audit_kanagawa_spring_access(self.repo, year=year)


    def test_stage43g7_third_place_refused_until_chiba_main_completed(self):
        self.start()
        placement = ChibaThirdPlaceCheckpointService(self.service)
        with self.assertRaisesRegex(
            ChibaThirdPlaceNotReady, "MAIN must be completed",
        ):
            placement.start("career_slot", year=2027)
        self.assertFalse(placement._path("career_slot", 2027).exists())

    def _finish_chiba_for_stage43g7(self):
        session = self.start()
        for _ in range(85):
            if session.previews["CMP000092"].scheduled.is_complete:
                break
            self.service.play_next_date(session)
        self.assertTrue(session.previews["CMP000092"].scheduled.is_complete)
        return session

    def test_stage43g7_real_third_decider_archive_and_feeder_verification(self):
        session = self._finish_chiba_for_stage43g7()
        before = project_same_year_regional_feeders(
            self.service, session, "CMP000006",
        )
        by_rule = {r["feeder_rule_id"]: r for r in before["feeder_rules"]}
        self.assertEqual(
            "ranking_cutoff_requires_tiebreak_rule",
            by_rule["RFR000011"]["status"],
        )
        placement = ChibaThirdPlaceCheckpointService(self.service)
        finished = placement.start("career_slot", year=2027)
        self.assertFalse(finished["official_future_rule_verified"])
        self.assertEqual("2027-05-03", finished["match_date"])
        self.assertEqual(2, len(finished["semifinal_loser_school_ids"]))
        self.assertIn(
            finished["third_place_school_id"],
            finished["semifinal_loser_school_ids"],
        )
        history = HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")
        saved = [x for x in history.list_matches(2027)
                 if x["match_id"] == finished["match_id"]]
        self.assertEqual(1, len(saved))
        self.assertEqual("PLACEMENT", saved[0]["stage_code"])
        self.assertEqual("THIRD_PLACE", saved[0]["phase_code"])
        self.assertEqual("ability_model_v1", saved[0]["score_source"])
        self.assertTrue(saved[0]["inning_scores"])
        self.assertTrue(saved[0]["batter_stats"])
        self.assertTrue(saved[0]["pitcher_stats"])
        self.assertEqual(
            self.original_2026_count, len(history.list_matches(2026)),
        )
        view = project_same_year_regional_feeders(
            self.service, session, "CMP000006",
            placement_decider_match_ids={"CMP000092": finished["match_id"]},
        )
        third = next(x for x in view["feeder_rules"]
                     if x["feeder_rule_id"] == "RFR000011")
        self.assertEqual("verified_game_qualification", third["status"])
        self.assertEqual(3, len(third["school_ids"]))
        self.assertEqual(finished["third_place_school_id"], third["school_ids"][2])
        self.assertFalse(view["all_feeder_results_verified"])
        self.assertEqual(finished, placement.load("career_slot", year=2027))
        with self.assertRaisesRegex(ChibaThirdPlaceNotReady, "already started"):
            placement.start("career_slot", year=2027)

    def test_stage43g7_modified_decider_is_not_accepted(self):
        self._finish_chiba_for_stage43g7()
        placement = ChibaThirdPlaceCheckpointService(self.service)
        finished = placement.start("career_slot", year=2027)
        with sqlite3.connect(self.slot / "historical_matches.sqlite3") as conn:
            conn.execute(
                "UPDATE historical_matches SET record_sha256=? "
                "WHERE year=2027 AND competition_id=? AND match_id=?",
                ("tampered", "CMP000092", finished["match_id"]),
            )
        with self.assertRaises(ValueError):
            placement.load("career_slot", year=2027)



if __name__ == "__main__":
    unittest.main()
