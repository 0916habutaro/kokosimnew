"""Stage43G-10: real 8-prefecture → 17-team Kanto game E2E."""
from __future__ import annotations

from collections import defaultdict
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.career_invitational_manifest import CareerInvitationalManifestService
from phase2_engine.career_kanagawa_spring_checkpoint import CareerKanagawaSpringCheckpointService
from phase2_engine.career_multi_preview_checkpoint import CareerMultiPreviewCheckpointService
from phase2_engine.career_regional_main_checkpoint import CareerRegionalMainCheckpointService
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.chiba_third_place_checkpoint import ChibaThirdPlaceCheckpointService
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.models import CompetitionRun, CompetitionOutcome, Match, StageExecution
from phase2_engine.repository import DataRepository
from phase2_engine.same_year_regional_feeder_gate import (
    RegionalFeederNotReady, project_same_year_regional_feeders,
)

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026100701
DESTINATION = "CMP000006"
KANAGAWA = "CMP000095"
CHIBA = "CMP000092"
TOKYO_SOURCE = "GAME-TOKYO-AUTUMN-2026"
KANTO = {
    "CMP000084": ("08", 4),
    "CMP000086": ("09", 0),
    "CMP000088": ("10", 0),
    "CMP000090": ("11", 8),
    "CMP000092": ("12", 8),
    "CMP000094": ("13", 64),
    "CMP000105": ("19", 0),
}
KANAGAWA_GROUP_SIZES = (46, 46, 36, 34)


def previous_autumn_game(cid, school_ids):
    """Produce an internally validated archived *game* bracket, not real 2026."""
    active = list(school_ids)
    eliminated = defaultdict(list)
    matches = []
    round_no = 1
    while len(active) > 1:
        winners = []
        for i in range(0, len(active), 2):
            a, b = active[i:i+2]
            winners.append(a)
            eliminated[round_no].append(b)
            matches.append(Match(
                match_id=f"{cid}-M{len(matches)+1:03d}",
                competition_id=cid, stage_id="STG-G10-SANDBOX-AUTUMN",
                stage_code="MAIN", phase_code="MAIN_BRACKET",
                round_no=round_no, team1=a, team2=b, winner=a, loser=b,
            ))
        active = winners
        round_no += 1
    ranks = [active[0]]
    for n in sorted(eliminated, reverse=True):
        ranks.extend(eliminated[n])
    outcome = CompetitionOutcome(
        champion_school_id=ranks[0],
        runner_up_school_id=ranks[1],
        semifinalist_school_ids=ranks[2:4],
        quarterfinalist_school_ids=ranks[4:8],
        final_ranking_school_ids=ranks,
        eliminated_by_round={str(k): list(v) for k, v in eliminated.items()},
        match_count=len(matches), bye_count=0, bracket_size=len(school_ids),
    )
    run = CompetitionRun(
        competition_id=cid, year=2026, rng_seed=SEED,
        entrant_school_ids=list(school_ids), seed_assignments=[],
        stage_executions=[StageExecution(
            stage_id="STG-G10-SANDBOX-AUTUMN", stage_code="MAIN",
            format_model_id="MAIN_SINGLE_ELIMINATION",
            entrant_school_ids=list(school_ids),
            output_school_ids=[ranks[0]], matches=matches,
        )],
        main_entrant_school_ids=list(school_ids), outcome=outcome,
    )
    rows = [{
        "competition_id": cid, "match_id": m.match_id,
        "competition_name": "ゲーム内2026仮秋季大会",
        "match_date": "2026-10-01", "completed_on": "2026-10-01",
        "date_source": "game_projection_v1",
        "status": "completed", "stage_code": "MAIN",
        "phase_code": "MAIN_BRACKET", "round_no": m.round_no,
        "team1_id": m.team1, "team2_id": m.team2,
        "winner_id": m.winner, "loser_id": m.loser,
        "team1_score": 5, "team2_score": 1,
        "score_source": "generated_v1",
    } for m in matches]
    return run, rows


@unittest.skipIf(
    os.environ.get("KOKOSIM_SKIP_STAGE43G10_E2E") == "1",
    "Run in the dedicated Kanto 17-school E2E CI job",
)
class Stage43G10Kanto17EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.tmp = tempfile.TemporaryDirectory()
        folder = Path(cls.tmp.name)
        cls.history_file = folder / "matches.sqlite3"
        cls.roster_file = folder / "rosters.sqlite3"
        cls.specs = []
        cls.prior_runs = []
        cls.prior_rows = []
        roster_schools = set()
        cls.prefecture_schools = {
            p: sorted(sid for sid in cls.repo.school_to_program
                      if cls.repo.schools[sid]["prefecture_code"] == p)
            for p in set(code for code, _ in KANTO.values()) | {"14"}
        }

        for cid, (pref, exempt) in KANTO.items():
            all_schools = cls.prefecture_schools[pref]
            stage = cls.repo.stages(cid)
            if exempt:
                if cid == "CMP000094":
                    source = TOKYO_SOURCE
                    groups = cls.repo.groups_by_stage["STG000209"]
                else:
                    source = next(k for k, v in cls.repo.competitions.items()
                                  if v.get("prefecture_code") == pref
                                  and v.get("competition_type") == "autumn_prefectural")
                    groups = cls.repo.groups_by_stage[
                        next(s for s in stage if s["stage_code"] != "MAIN")["stage_id"]
                    ]
                run, rows = previous_autumn_game(source, all_schools[:exempt])
                cls.prior_runs.append(run)
                cls.prior_rows.extend(rows)
                membership = {}
                offset = exempt
                for group in groups:
                    quota = int(group["advance_slots_to_next"])
                    membership[group["stage_group_id"]] = all_schools[
                        offset:offset+quota+1
                    ]
                    assert len(membership[group["stage_group_id"]]) == quota+1
                    offset += quota+1
                entrants = all_schools[:offset]
                spec = {
                    "competition_id": cid, "entry_mode": "prior_autumn_bypass_v1",
                    "entrant_school_ids": entrants,
                    "group_entrant_school_ids": membership,
                    "prior_source_competition_id": (
                        TOKYO_SOURCE if cid == "CMP000094" else None
                    ),
                }
                assert len(entrants) == offset
            else:
                entrants = all_schools[:8]
                assert len(entrants) == 8
                spec = {
                    "competition_id": cid, "entry_mode": "kanto_direct_main_v1",
                    "entrant_school_ids": entrants,
                    "group_entrant_school_ids": {},
                }
            cls.specs.append(spec)
            roster_schools.update(entrants)

        kanagawa = cls.prefecture_schools["14"]
        cls.recommended = kanagawa[:2]
        cls.qualifier_schools = kanagawa[2:2+sum(KANAGAWA_GROUP_SIZES)]
        assert len(cls.qualifier_schools) == sum(KANAGAWA_GROUP_SIZES)
        cls.kanagawa_schools = cls.recommended + cls.qualifier_schools
        groups = sorted(
            cls.repo.groups_by_stage["STG000177"],
            key=lambda x: int(x["group_order"]),
        )
        cls.kanagawa_groups = {}
        index = 0
        for group, amount in zip(groups, KANAGAWA_GROUP_SIZES):
            cls.kanagawa_groups[group["stage_group_id"]] = cls.qualifier_schools[
                index:index+amount
            ]
            index += amount
        assert sum(int(g["advance_slots_to_next"]) for g in groups) == 81

        outside = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] != "14"
        )[:30]
        cls.national_schools = outside + cls.recommended
        assert len(set(cls.national_schools)) == 32
        cls.specs.append({
            "competition_id": "CMP000001",
            "entry_mode": "national_invitational_main_v1",
            "entrant_school_ids": cls.national_schools,
            "group_entrant_school_ids": {},
        })
        roster_schools.update(cls.national_schools)
        roster_schools.update(cls.kanagawa_schools)
        hist = HistoricalMatchArchive(cls.history_file)
        hist.sync(
            year=2026, rng_seed=SEED, resolver_contract="game_v1",
            plan_fingerprint="stage43g10-full-game-autumn-source",
            completed=cls.prior_rows,
        )
        hist.seal_year(2026, expected_match_count=len(cls.prior_rows))
        outcomes = CareerCompetitionOutcomes(hist)
        for run in cls.prior_runs:
            outcomes.record_completed(run)
        factory = PlayerRosterGenerator()
        rosters = CareerRosterArchive(cls.roster_file)
        for sid in sorted(roster_schools):
            rosters.save_initial_roster(
                factory.generate_for_school_id(cls.repo, sid, 2026, SEED)
            )
            rosters.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=SEED,
            )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.tmp_run = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_run.name)
        self.slot = self.root / "kanto"
        self.slot.mkdir()
        shutil.copy2(self.history_file, self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.roster_file, self.slot / "career_rosters.sqlite3")
        self.multi = CareerMultiPreviewCheckpointService(
            self.repo, ROOT / "data", save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.manifest = CareerInvitationalManifestService(self.multi)
        self.kanagawa = CareerKanagawaSpringCheckpointService(self.multi)
        self.chiba = ChibaThirdPlaceCheckpointService(self.multi)
        self.regional = CareerRegionalMainCheckpointService(self.multi)

    def tearDown(self):
        self.tmp_run.cleanup()

    def start(self):
        session = self.multi.start(
            "kanto", year=2027, competitions=self.specs,
            base_seed=SEED, career_seed=SEED,
        )
        self.manifest.record("kanto", year=2027)
        spring = self.kanagawa.start(
            "kanto", year=2027,
            entrant_school_ids=self.kanagawa_schools,
            group_entrant_school_ids=self.kanagawa_groups,
        )
        return session, spring

    def test_not_ready_with_any_incomplete_feeder_or_missing_sidecar(self):
        session, spring = self.start()
        partial = project_same_year_regional_feeders(
            self.multi, session, DESTINATION,
        )
        self.assertFalse(partial["all_feeder_results_verified"])
        self.assertIn("RFR000013", partial["unresolved_feeder_rule_ids"])
        with self.assertRaises(RegionalFeederNotReady):
            self.regional.start("kanto", year=2027,
                                kanagawa_sidecar_enabled=True)

    def test_all_eight_sources_third_place_and_region_final_are_resumable(self):
        _, spring = self.start()
        global_days = []
        for _ in range(100):
            result = self.kanagawa.play_next_global_date(spring)
            global_days.append(result["date"])
            if result["all_registered_events_complete"]:
                break
        self.assertTrue(result["all_registered_events_complete"])
        self.assertEqual(global_days, sorted(set(global_days)))
        upstream = self.multi.load("kanto", year=2027)
        self.assertEqual(8, len(upstream.previews))  # 7 prefectures plus Senbatsu
        self.assertEqual(8, len(upstream.completed_runs()))
        self.assertTrue(spring.preview.scheduled.is_complete)
        self.assertEqual(83, len(
            spring.preview.scheduled.to_competition_run().main_entrant_school_ids
        ))

        placement = self.chiba.start("kanto", year=2027)
        self.assertEqual(2027, placement["year"])
        without_sidecar = project_same_year_regional_feeders(
            self.multi, upstream, DESTINATION,
            placement_decider_match_ids={CHIBA: placement["match_id"]},
        )
        self.assertEqual(["RFR000013"],
                         without_sidecar["unresolved_feeder_rule_ids"])
        with_sidecar = project_same_year_regional_feeders(
            self.multi, upstream, DESTINATION,
            placement_decider_match_ids={CHIBA: placement["match_id"]},
            kanagawa_sidecar_enabled=True,
        )
        self.assertTrue(with_sidecar["all_feeder_results_verified"])
        self.assertEqual(8, with_sidecar["feeder_rule_count"])
        self.assertEqual(17, with_sidecar["verified_entrant_count"])
        self.assertEqual(17, len(set(with_sidecar["verified_school_ids"])))
        source = next(r for r in with_sidecar["feeder_rules"]
                      if r["source_competition_id"] == KANAGAWA)
        self.assertEqual("verified_game_qualification", source["status"])
        self.assertEqual(2, len(source["school_ids"]))
        chiba = next(r for r in with_sidecar["feeder_rules"]
                     if r["source_competition_id"] == CHIBA)
        self.assertEqual(3, len(chiba["school_ids"]))
        self.assertEqual(placement["third_place_school_id"], chiba["school_ids"][-1])
        with self.assertRaisesRegex(RegionalFeederNotReady, "unresolved"):
            self.regional.start(
                "kanto", year=2027,
                placement_decider_match_ids={CHIBA: placement["match_id"]},
            )

        region = self.regional.start(
            "kanto", year=2027,
            placement_decider_match_ids={CHIBA: placement["match_id"]},
            kanagawa_sidecar_enabled=True,
        )
        self.assertEqual(17, region.summary()["entrant_count"])
        played = []
        for _ in range(12):
            result = self.regional.play_next_date(region)
            played.append(result["date"])
            if region.preview.scheduled.is_complete:
                break
        self.assertTrue(region.preview.scheduled.is_complete)
        self.assertEqual(played, sorted(set(played)))
        self.assertEqual(16, region.summary()["completed_match_count"])
        final = region.preview.scheduled.to_competition_run()
        self.assertEqual(17, len(final.main_entrant_school_ids))
        self.assertEqual(16, final.outcome.match_count)
        restored = self.regional.load("kanto", year=2027)
        self.assertEqual(
            region.preview.scheduled.public_snapshot(),
            restored.preview.scheduled.public_snapshot(),
        )
        archive = HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")
        regional_rows = [r for r in archive.list_matches(2027, limit=1000)
                         if r["competition_id"] == DESTINATION]
        self.assertEqual(16, len(regional_rows))
        self.assertTrue(all(r["inning_scores"] is not None
                            and r["batter_stats"] and r["pitcher_stats"]
                            for r in regional_rows))
        self.assertEqual(len(self.prior_rows), len(archive.list_matches(2026)))
        self.assertEqual("sealed", archive.list_years()[0]["status"])


if __name__ == "__main__":
    unittest.main()
