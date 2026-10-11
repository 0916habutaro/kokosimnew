"""Stage43G-49: actual sealed 2026 *game* standings bypass 2027 Gifu FMT002.

2026 sources are fabricated completed game results, NOT official results.
2027 uses real school IDs but simulated rosters, dates and matches.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService,
    CareerPreviewSaveError,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.future_gifu_sealed_autumn_bridge import (
    GIFU_SPRING, GIFU_AUTUMN,
    prepare_future_gifu_sealed_autumn_preview,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository
from phase2_engine.same_year_regional_feeder_gate import (
    project_same_year_regional_feeders,
)
from test_stage43f7_gifu_tokyo_access import simulated_autumn_run

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEED = 2026101149
TOKUSHIMA = "CMP000139"
TOKAI = "CMP000008"


class Stage43G49GifuPriorAutumnCareerE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.fixtures = tempfile.TemporaryDirectory()
        folder = Path(cls.fixtures.name)
        cls.original_history = folder / "historical_matches.sqlite3"
        cls.original_rosters = folder / "career_rosters.sqlite3"
        history = HistoricalMatchArchive(cls.original_history)
        rosters = CareerRosterArchive(cls.original_rosters)
        generator = PlayerRosterGenerator()
        stage = cls.repo.stage_by_code(GIFU_SPRING, "BRANCH_QUALIFIER")
        groups = cls.repo.groups_by_stage[stage["stage_id"]]
        assert len(groups) == 4
        cls.qualifier_group_manifest = {}
        cls.group_slots = {}
        qualifiers = []
        for group in groups:
            gid = group["stage_group_id"]
            quota = cls.repo.param(
                stage["stage_id"], "output_slots", gid,
                int(group.get("advance_slots_to_next") or 0),
            )
            candidates = sorted(cls.repo.group_school_ids(group, 2026))
            assert len(candidates) >= quota + 1, (gid, quota, len(candidates))
            members = candidates[:min(2 * quota, len(candidates))]
            cls.qualifier_group_manifest[gid] = members
            cls.group_slots[gid] = quota
            qualifiers.extend(members)
        assert sum(cls.group_slots.values()) == 20
        assert len(qualifiers) == len(set(qualifiers))
        population = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "21"
        )
        excluded = [sid for sid in population if sid not in set(qualifiers)]
        assert len(excluded) >= 8
        cls.prior_schools = excluded[:8]
        autumn, prior_game_rows = simulated_autumn_run(
            GIFU_AUTUMN, cls.prior_schools,
        )
        cls.direct = list(autumn.outcome.final_ranking_school_ids[:4])
        cls.spring_school_ids = cls.direct + qualifiers
        cls.other_schools = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "36"
        )[:8]
        assert len(cls.other_schools) == 8
        cls.specs = [
            {
                "competition_id": GIFU_SPRING,
                "entry_mode": "gifu_sealed_autumn_fmt002_v1",
                "entrant_school_ids": cls.spring_school_ids,
                "group_entrant_school_ids": cls.qualifier_group_manifest,
            },
            {
                "competition_id": TOKUSHIMA,
                "entry_mode": "shikoku_direct_main_v1",
                "entrant_school_ids": cls.other_schools,
                "group_entrant_school_ids": {},
            },
        ]
        for sid in sorted(set(cls.spring_school_ids + cls.other_schools)):
            rosters.save_initial_roster(
                generator.generate_for_school_id(
                    cls.repo, sid, 2026, SEED,
                )
            )
            rosters.advance_and_save(
                cls.repo.team(sid), next_year=2027,
                career_seed=SEED,
            )
        history.sync(
            year=2026, rng_seed=SEED,
            resolver_contract="game_v1",
            plan_fingerprint="stage43g49-prior-autumn-game",
            completed=prior_game_rows,
        )
        history.seal_year(
            2026, expected_match_count=len(prior_game_rows),
        )
        CareerCompetitionOutcomes(history).record_completed(autumn)

    @classmethod
    def tearDownClass(cls):
        cls.fixtures.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.slot = self.root / "gifu"
        self.slot.mkdir()
        shutil.copy2(
            self.original_history, self.slot / "historical_matches.sqlite3",
        )
        shutil.copy2(
            self.original_rosters, self.slot / "career_rosters.sqlite3",
        )
        self.history = HistoricalMatchArchive(
            self.slot / "historical_matches.sqlite3",
        )
        self.rosters = CareerRosterArchive(
            self.slot / "career_rosters.sqlite3",
        )
        self.multi = CareerMultiPreviewCheckpointService(
            self.repo, DATA, save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )

    def _start(self, specs=None):
        return self.multi.start(
            "gifu", year=2027,
            competitions=self.specs if specs is None else specs,
            base_seed=SEED, career_seed=SEED,
        )

    def test_sealed_autumn_top_four_skip_qualifiers_then_resume_gifu_main(self):
        manual = self.slot / "manual.json"
        manual.write_bytes(b"existing user save")
        session = self._start()
        gifu = session.previews[GIFU_SPRING]
        self.assertEqual(self.direct, gifu.annual.direct_main_entry_school_ids)
        self.assertEqual([], gifu.annual.main_seed_school_ids)
        self.assertEqual(4, len(gifu.scheduled.runtime.qualifier_groups))
        self.assertEqual(
            {id: len(schools) for id, schools in self.qualifier_group_manifest.items()},
            {group.stage_group_id: len(group.entrant_school_ids)
             for group in gifu.scheduled.runtime.qualifier_groups},
        )
        self.assertEqual(
            set(self.qualifier_group_manifest).issubset(
                {group.stage_group_id for group
                 in gifu.scheduled.runtime.qualifier_groups}
            ), True,
        )
        self.assertTrue(set(self.direct).isdisjoint(
            gifu.scheduled.runtime.qualifier_entrant_school_ids
        ))
        self.assertEqual("2027-03-20", gifu.scheduled.next_scheduled_date())
        self.assertFalse(gifu.snapshot()["official_competition"])
        with sqlite3.connect(self.history.db_path) as conn:
            prior_ledger = conn.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0]
            saved_identity = conn.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0]
        first = self.multi.play_next_date(session)
        self.assertGreater(first["played_match_count"], 0)
        reopened = self.multi.load("gifu", year=2027)
        self.assertEqual(
            session.previews[GIFU_SPRING].scheduled.public_snapshot(),
            reopened.previews[GIFU_SPRING].scheduled.public_snapshot(),
        )
        for _ in range(30):
            if GIFU_SPRING in reopened.completed_runs():
                break
            self.multi.play_next_date(reopened)
        self.assertIn(GIFU_SPRING, reopened.completed_runs())
        final = self.multi.load("gifu", year=2027)
        run = final.completed_runs()[GIFU_SPRING]
        self.assertEqual(24, len(run.main_entrant_school_ids))
        self.assertEqual(23, run.outcome.match_count)
        self.assertEqual(24, len(set(run.main_entrant_school_ids)))
        self.assertTrue(set(self.direct) <= set(run.main_entrant_school_ids))
        group_qualifiers = set(run.main_entrant_school_ids) - set(self.direct)
        self.assertEqual(20, len(group_qualifiers))
        self.assertTrue(group_qualifiers <= {
            sid for members in self.qualifier_group_manifest.values()
            for sid in members
        })
        rows = self.history.list_matches(2027, limit=500)
        games = [x for x in rows if x["competition_id"] == GIFU_SPRING]
        self.assertGreater(
            len([x for x in games if x["stage_code"] == "BRANCH_QUALIFIER"]), 0
        )
        self.assertEqual(
            23, len([x for x in games if x["stage_code"] == "MAIN"]),
        )
        self.assertTrue(all(
            x["date_source"] == "game_projection_v1"
            and x["score_source"] == "ability_model_v1"
            and x["inning_scores"] and x["batter_stats"] and x["pitcher_stats"]
            for x in games
        ))
        self.assertTrue(all(
            x["team1_id"] not in self.direct
            and x["team2_id"] not in self.direct
            for x in games if x["stage_code"] == "BRANCH_QUALIFIER"
        ))
        gate = project_same_year_regional_feeders(
            self.multi, final, TOKAI,
        )
        proof = next(r for r in gate["feeder_rules"]
                     if r["source_competition_id"] == GIFU_SPRING)
        self.assertEqual("verified_game_qualification", proof["status"])
        self.assertEqual(run.outcome.final_ranking_school_ids[:2],
                         proof["school_ids"])
        self.assertEqual(2, gate["verified_entrant_count"])
        self.assertFalse(gate["all_feeder_results_verified"])
        self.assertEqual(3, len(gate["unresolved_feeder_rule_ids"]))
        with sqlite3.connect(self.history.db_path) as conn:
            self.assertEqual(prior_ledger, conn.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0])
            self.assertEqual(saved_identity, conn.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0])
        self.assertEqual(b"existing user save", manual.read_bytes())

    def test_prior_year_and_group_integrity_fail_closed(self):
        self.assertEqual(
            self.direct,
            list(CareerCompetitionOutcomes(self.history).previous_results(2026)[
                GIFU_AUTUMN
            ]["ranked_school_ids"][:4]),
        )
        wrong = [{
            **spec,
            "group_entrant_school_ids": {
                gid: list(group) for gid, group
                in spec["group_entrant_school_ids"].items()
            },
        } for spec in self.specs]
        gid = next(iter(wrong[0]["group_entrant_school_ids"]))
        wrong[0]["group_entrant_school_ids"][gid][0] = self.other_schools[0]
        with self.assertRaises(FutureCompetitionNotReady):
            self._start(wrong)
        self.assertFalse(
            (self.slot / "career_multi_previews" / "2027.json").exists(),
        )
        forged = [{
            **spec,
            "entrant_school_ids": list(spec["entrant_school_ids"]),
        } for spec in self.specs]
        forged[0]["entrant_school_ids"][0] = self.prior_schools[7]
        with self.assertRaises(FutureCompetitionNotReady):
            self._start(forged)
        with sqlite3.connect(self.history.db_path) as conn:
            conn.execute(
                "DELETE FROM historical_matches WHERE year=2026 "
                "AND competition_id=? LIMIT 1",
                (GIFU_AUTUMN,),
            )
        with self.assertRaises(CareerPreviewSaveError):
            self._start()

    def test_unsealed_or_unrostered_autumn_cannot_grant_bypass(self):
        with sqlite3.connect(self.history.db_path) as conn:
            conn.execute(
                "UPDATE career_years SET status='active' WHERE year=2026",
            )
        with self.assertRaises(CareerPreviewSaveError):
            self._start()
        with sqlite3.connect(self.history.db_path) as conn:
            conn.execute(
                "UPDATE career_years SET status='sealed' WHERE year=2026",
            )
        with tempfile.TemporaryDirectory() as tmp:
            missing_rosters = CareerRosterArchive(
                Path(tmp) / "rosters.sqlite3",
            )
            with self.assertRaisesRegex(FutureCompetitionNotReady, "roster"):
                prepare_future_gifu_sealed_autumn_preview(
                    data_root=DATA, year=2027,
                    entrant_school_ids=self.spring_school_ids,
                    group_entrant_school_ids=self.qualifier_group_manifest,
                    match_archive=self.history,
                    roster_archive=missing_rosters,
                    repo=self.repo,
                    base_seed=SEED, career_seed=SEED,
                )


if __name__ == "__main__":
    unittest.main()
