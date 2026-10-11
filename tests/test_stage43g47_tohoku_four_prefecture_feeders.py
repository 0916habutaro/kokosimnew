"""Stage43G-47: four saved 2027 prefectural competitions qualify Tohoku.

Fixtures, entrant selection and dates are simulated from verified 2026
masters. All six real prefectures must complete before the regional starts.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService, CareerPreviewSaveError,
)
from phase2_engine.career_regional_main_checkpoint import (
    CareerRegionalMainCheckpointService,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.chiba_third_place_checkpoint import (
    AomoriThirdPlaceCheckpointService,
    AkitaThirdPlaceCheckpointService,
)
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.future_tohoku_composite_bridge import (
    TOHOKU_COMPOSITE_PREFECTURES, prepare_future_tohoku_composite_preview,
)
from phase2_engine.future_yamagata_direct_main_bridge import (
    prepare_future_yamagata_direct_main_preview,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository
from phase2_engine.same_year_regional_feeder_gate import (
    RegionalFeederNotReady, project_same_year_regional_feeders,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEED = 2026101147
REGIONAL = "CMP000005"
AOMORI = "CMP000072"
IWATE = "CMP000074"
MIYAGI = "CMP000076"
AKITA = "CMP000078"
YAMAGATA = "CMP000080"
FUKUSHIMA = "CMP000082"
SOURCES = (AOMORI, IWATE, MIYAGI, AKITA, YAMAGATA, FUKUSHIMA)


class Stage43G47TohokuFourPrefecturesRegionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.fixtures = tempfile.TemporaryDirectory()
        base = Path(cls.fixtures.name)
        cls.history = base / "historical_matches.sqlite3"
        cls.rosters = base / "career_rosters.sqlite3"
        hist = HistoricalMatchArchive(cls.history)
        hist.sync(
            year=2026, rng_seed=SEED, resolver_contract="game_v1",
            plan_fingerprint="stage43g47-sealed-empty-prior",
            completed=[],
        )
        hist.seal_year(2026, expected_match_count=0)
        rosters = CareerRosterArchive(cls.rosters)
        generator = PlayerRosterGenerator()
        cls.inputs = []
        cls.inputs_by_id = {}
        participants = set()
        for cid, (pcode, model, count, quota) in TOHOKU_COMPOSITE_PREFECTURES.items():
            stage = cls.repo.stage_by_code(cid, "BRANCH_QUALIFIER")
            group_memberships = {}
            for group in cls.repo.groups_by_stage[stage["stage_id"]]:
                gid = group["stage_group_id"]
                slots = cls.repo.param(
                    stage["stage_id"], "output_slots", gid,
                    int(group.get("advance_slots_to_next") or 0),
                )
                candidates = sorted(cls.repo.group_school_ids(group, 2026))
                assert len(candidates) >= slots + 1, (cid, gid, slots, len(candidates))
                # Each district has a simulated decision match, not a bye-only pass.
                group_memberships[gid] = candidates[:slots + 1]
            entrants = [school for members in group_memberships.values()
                        for school in members]
            assert len(entrants) == len(set(entrants))
            spec = {
                "competition_id": cid,
                "entry_mode": "tohoku_composite_qualifier_v1",
                "entrant_school_ids": entrants,
                "group_entrant_school_ids": group_memberships,
            }
            cls.inputs.append(spec)
            cls.inputs_by_id[cid] = spec
            participants.update(entrants)

        for cid, pcode, mode in (
            (AOMORI, "02", "aomori_seed_main_v1"),
            (AKITA, "05", "akita_direct_main_v1"),
            (YAMAGATA, "06", "yamagata_direct_main_v1"),
        ):
            groups = {}
            if cid == AOMORI:
                stage = cls.repo.stage_by_code(cid, "SEED_EVENT")
                groups = {}
                for group in cls.repo.groups_by_stage[stage["stage_id"]]:
                    gid = group["stage_group_id"]
                    candidates = sorted(cls.repo.group_school_ids(group, 2026))
                    assert len(candidates) >= 5
                    groups[gid] = candidates[:min(len(candidates), 6)]
                entrants = [s for members in groups.values() for s in members]
            else:
                entrants = sorted(
                    sid for sid in cls.repo.school_to_program
                    if cls.repo.schools[sid]["prefecture_code"] == pcode
                )[:8]
            assert len(entrants) == len(set(entrants))
            spec = {
                "competition_id": cid,
                "entry_mode": mode,
                "entrant_school_ids": entrants,
                "group_entrant_school_ids": groups,
            }
            cls.inputs.append(spec)
            cls.inputs_by_id[cid] = spec
            participants.update(entrants)
        cls.inputs.sort(key=lambda x: x["competition_id"])
        cls.participants = sorted(participants)
        for sid in cls.participants:
            rosters.save_initial_roster(
                generator.generate_for_school_id(cls.repo, sid, 2026, SEED)
            )
            rosters.advance_and_save(
                cls.repo.team(sid), next_year=2027,
                career_seed=SEED,
            )

    @classmethod
    def tearDownClass(cls):
        cls.fixtures.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.save_root = Path(self.tmp.name)
        self.slot = self.save_root / "tohoku"
        self.slot.mkdir()
        shutil.copy2(self.history,
                     self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.rosters,
                     self.slot / "career_rosters.sqlite3")
        self.multi = CareerMultiPreviewCheckpointService(
            self.repo, DATA, save_root=self.save_root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.regional = CareerRegionalMainCheckpointService(
            self.multi, target_competition_id=REGIONAL,
        )
        self.aomori = AomoriThirdPlaceCheckpointService(self.multi)
        self.akita = AkitaThirdPlaceCheckpointService(self.multi)
        self.hist = HistoricalMatchArchive(
            self.slot / "historical_matches.sqlite3"
        )

    def _start(self, specs=None):
        return self.multi.start(
            "tohoku", year=2027,
            competitions=self.inputs if specs is None else specs,
            base_seed=SEED, career_seed=SEED,
        )

    def _finish_six_sources(self):
        session = self._start()
        for _ in range(65):
            if len(session.completed_runs()) == 6:
                break
            event = self.multi.play_next_date(session)
            self.assertGreater(event["played_match_count"], 0)
        self.assertEqual(set(SOURCES), set(session.completed_runs()))
        return self.multi.load("tohoku", year=2027)

    def _complete_deciders(self):
        source = self._finish_six_sources()
        aomori = self.aomori.start("tohoku", year=2027)
        akita = self.akita.start("tohoku", year=2027)
        proof = {AOMORI: aomori["match_id"], AKITA: akita["match_id"]}
        return source, proof

    def test_six_saved_sources_and_two_third_place_games_qualify_14(self):
        manual = self.slot / "manual.json"
        manual.write_bytes(b"original save")
        session = self._start()
        with self.assertRaises(RegionalFeederNotReady):
            self.regional.start("tohoku", year=2027)
        for _ in range(65):
            if len(session.completed_runs()) == 6:
                break
            self.multi.play_next_date(session)
        self.assertEqual(set(SOURCES), set(session.completed_runs()))
        self.assertTrue(any(
            x.stage_code == "BRANCH_QUALIFIER"
            for cid in (IWATE, MIYAGI, FUKUSHIMA)
            for x in session.completed_runs()[cid].stage_executions
        ))
        self.assertEqual(
            {IWATE: 24, MIYAGI: 25, FUKUSHIMA: 28},
            {cid: len(session.completed_runs()[cid].main_entrant_school_ids)
             for cid in (IWATE, MIYAGI, FUKUSHIMA)},
        )
        self.assertEqual(
            {"CMP000074", "CMP000076", "CMP000082"},
            set(TOHOKU_COMPOSITE_PREFECTURES),
        )
        restored = self.multi.load("tohoku", year=2027)
        for cid in SOURCES:
            self.assertEqual(
                session.previews[cid].scheduled.public_snapshot(),
                restored.previews[cid].scheduled.public_snapshot(),
            )
        before = project_same_year_regional_feeders(
            self.multi, restored, REGIONAL,
        )
        self.assertFalse(before["all_feeder_results_verified"])
        self.assertIn(AOMORI, {
            rule["source_competition_id"] for rule in before["feeder_rules"]
            if rule["status"] == "ranking_cutoff_requires_tiebreak_rule"
        })
        self.assertIn(AKITA, {
            rule["source_competition_id"] for rule in before["feeder_rules"]
            if rule["status"] == "ranking_cutoff_requires_tiebreak_rule"
        })
        self.assertEqual(8, before["verified_entrant_count"])
        with self.assertRaises(RegionalFeederNotReady):
            self.regional.start("tohoku", year=2027)
        with sqlite3.connect(self.hist.db_path) as db:
            old_ledger = db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0]
            year_meta = db.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0]
        aomori = self.aomori.start("tohoku", year=2027)
        akita = self.akita.start("tohoku", year=2027)
        self.assertEqual(aomori, self.aomori.load("tohoku", year=2027))
        self.assertEqual(akita, self.akita.load("tohoku", year=2027))
        placement_ids = {
            AOMORI: aomori["match_id"], AKITA: akita["match_id"],
        }
        proof = project_same_year_regional_feeders(
            self.multi, restored, REGIONAL,
            placement_decider_match_ids=placement_ids,
        )
        self.assertEqual(6, proof["feeder_rule_count"])
        self.assertEqual(14, proof["verified_entrant_count"])
        self.assertTrue(proof["all_feeder_results_verified"])
        self.assertEqual([], proof["unresolved_feeder_rule_ids"])
        self.assertEqual(14, len(set(proof["verified_school_ids"])))
        for item in proof["feeder_rules"]:
            self.assertEqual("verified_game_qualification", item["status"])
            cid = item["source_competition_id"]
            ranked = restored.completed_runs()[cid].outcome.final_ranking_school_ids
            self.assertEqual(ranked[:2], item["school_ids"][:2])
            self.assertEqual(64, len(item["evidence_sha256"]))
        regional = self.regional.start(
            "tohoku", year=2027,
            placement_decider_match_ids=placement_ids,
        )
        self.assertEqual(14, regional.summary()["entrant_count"])
        self.assertEqual(set(proof["verified_school_ids"]),
                         set(regional.preview.annual.entrant_school_ids))
        first = self.regional.play_next_date(regional)
        self.assertGreater(first["played_match_count"], 0)
        resumed = self.regional.load("tohoku", year=2027)
        self.assertEqual(
            regional.preview.scheduled.public_snapshot(),
            resumed.preview.scheduled.public_snapshot(),
        )
        for _ in range(9):
            if resumed.preview.scheduled.is_complete:
                break
            self.regional.play_next_date(resumed)
        self.assertTrue(resumed.preview.scheduled.is_complete)
        outcome = resumed.preview.scheduled.to_competition_run()
        self.assertEqual(13, outcome.outcome.match_count)
        self.assertIn(outcome.outcome.champion_school_id,
                      proof["verified_school_ids"])
        reopened = self.regional.load("tohoku", year=2027)
        self.assertEqual(
            reopened.preview.scheduled.public_snapshot(),
            resumed.preview.scheduled.public_snapshot(),
        )
        records = self.hist.list_matches(2027, limit=500)
        region_rows = [x for x in records if x["competition_id"] == REGIONAL]
        self.assertEqual(13, len(region_rows))
        self.assertTrue(all(
            x["score_source"] == "ability_model_v1"
            and x["date_source"] == "game_projection_v1"
            and x["inning_scores"] and x["batter_stats"] and x["pitcher_stats"]
            for x in records
        ))
        with sqlite3.connect(self.hist.db_path) as db:
            self.assertEqual(old_ledger, db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0])
            self.assertEqual(year_meta, db.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0])
        self.assertEqual(b"original save", manual.read_bytes())

    def test_bad_group_membership_not_accepted(self):
        specs = [dict(x) for x in self.inputs]
        item = next(x for x in specs if x["competition_id"] == IWATE)
        item["group_entrant_school_ids"] = {
            k: list(v) for k, v in item["group_entrant_school_ids"].items()
        }
        gid = next(iter(item["group_entrant_school_ids"]))
        item["group_entrant_school_ids"][gid][0] = self.inputs_by_id[YAMAGATA][
            "entrant_school_ids"
        ][0]
        with self.assertRaises(FutureCompetitionNotReady):
            self._start(specs)
        self.assertFalse(
            (self.slot / "career_multi_previews" / "2027.json").exists()
        )

    def test_unrostered_composite_and_direct_game_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = CareerRosterArchive(
                Path(tmp) / "rosters.sqlite3"
            )
            with self.assertRaisesRegex(
                FutureCompetitionNotReady, "roster",
            ):
                spec = self.inputs_by_id[MIYAGI]
                prepare_future_tohoku_composite_preview(
                    data_root=DATA, year=2027,
                    competition_id=MIYAGI,
                    entrant_school_ids=spec["entrant_school_ids"],
                    group_entrant_school_ids=spec["group_entrant_school_ids"],
                    roster_archive=missing, repo=self.repo,
                    base_seed=SEED, career_seed=SEED,
                )
            with self.assertRaisesRegex(
                FutureCompetitionNotReady, "roster",
            ):
                spec = self.inputs_by_id[YAMAGATA]
                prepare_future_yamagata_direct_main_preview(
                    data_root=DATA, year=2027,
                    competition_id=YAMAGATA,
                    entrant_school_ids=spec["entrant_school_ids"],
                    roster_archive=missing, repo=self.repo,
                    base_seed=SEED, career_seed=SEED,
                )

    def test_wrong_placement_id_cannot_unlock_regional(self):
        completed, ids = self._complete_deciders()
        with self.assertRaises(RegionalFeederNotReady):
            project_same_year_regional_feeders(
                self.multi, completed, REGIONAL,
                placement_decider_match_ids={
                    AOMORI: "FAKE-MATCH", AKITA: ids[AKITA],
                },
            )
        with self.assertRaises(RegionalFeederNotReady):
            self.regional.start(
                "tohoku", year=2027,
                placement_decider_match_ids={AOMORI: ids[AOMORI]},
            )
        with self.assertRaises(RegionalFeederNotReady):
            self.regional.start(
                "tohoku", year=2027,
                placement_decider_match_ids={
                    **ids, "CMP000092": "CHIBA-FALSE",
                },
            )


if __name__ == "__main__":
    unittest.main()
