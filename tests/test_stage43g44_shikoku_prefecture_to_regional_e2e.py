"""Stage43G-44: four 2027 sandbox prefectural games actually feed Shikoku MAIN.

All school names/IDs are from the real 2026 master. Selected entrants,
projected 2027 dates, fictional players and match results are NOT official.
"""
from __future__ import annotations

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
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.future_shikoku_direct_main_bridge import (
    SHIKOKU_DIRECT_MAIN_PREFECTURES,
    prepare_future_shikoku_direct_main_preview,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository
from phase2_engine.same_year_regional_feeder_gate import (
    RegionalFeederNotReady, project_same_year_regional_feeders,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEED = 2026101144
REGIONAL = "CMP000011"


class Stage43G44ShikokuPrefectureRegionalCareerE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.initial = tempfile.TemporaryDirectory()
        base = Path(cls.initial.name)
        cls.initial_history = base / "historical_matches.sqlite3"
        cls.initial_rosters = base / "career_rosters.sqlite3"
        hist = HistoricalMatchArchive(cls.initial_history)
        hist.sync(
            year=2026, rng_seed=SEED,
            resolver_contract="game_v1",
            plan_fingerprint="stage43g44-2026-game-sandbox",
            completed=[],
        )
        hist.seal_year(2026, expected_match_count=0)
        rosters = CareerRosterArchive(cls.initial_rosters)
        generator = PlayerRosterGenerator()
        cls.inputs = []
        cls.entries = {}
        for cid, pcode in SHIKOKU_DIRECT_MAIN_PREFECTURES.items():
            ids = sorted(
                sid for sid in cls.repo.school_to_program
                if cls.repo.schools[sid]["prefecture_code"] == pcode
            )[:8]
            assert len(ids) == 8
            cls.entries[cid] = ids
            cls.inputs.append({
                "competition_id": cid,
                "entry_mode": "shikoku_direct_main_v1",
                "entrant_school_ids": ids,
                "group_entrant_school_ids": {},
            })
            for sid in ids:
                rosters.save_initial_roster(
                    generator.generate_for_school_id(
                        cls.repo, sid, 2026, SEED,
                    )
                )
                rosters.advance_and_save(
                    cls.repo.team(sid), next_year=2027,
                    career_seed=SEED,
                )

    @classmethod
    def tearDownClass(cls):
        cls.initial.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.slot = self.root / "shikoku"
        self.slot.mkdir()
        shutil.copy2(self.initial_history,
                     self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.initial_rosters,
                     self.slot / "career_rosters.sqlite3")
        self.multi = CareerMultiPreviewCheckpointService(
            self.repo, DATA, save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.regional = CareerRegionalMainCheckpointService(
            self.multi, target_competition_id=REGIONAL,
        )

    def _archive(self):
        return HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")

    def _start(self, specs=None):
        return self.multi.start(
            "shikoku", year=2027,
            competitions=self.inputs if specs is None else specs,
            base_seed=SEED, career_seed=SEED,
        )

    def _completed_source_year(self):
        session = self._start()
        for _ in range(15):
            if len(session.completed_runs()) == 4:
                break
            self.multi.play_next_date(session)
        self.assertEqual(4, len(session.completed_runs()))
        self.assertEqual(28, session.summary()["completed_match_count"])
        return session

    def test_saved_four_prefectures_qualify_eight_and_resume_shikoku_main(self):
        original = self.slot / "manual.json"
        original.write_bytes(b"prior-year manual save stays immutable")
        upstream = self._start()
        with self.assertRaises(RegionalFeederNotReady):
            self.regional.start("shikoku", year=2027)
        initial_gate = project_same_year_regional_feeders(
            self.multi, upstream, REGIONAL,
        )
        self.assertFalse(initial_gate["all_feeder_results_verified"])
        self.assertEqual(0, initial_gate["verified_entrant_count"])

        for _ in range(15):
            if len(upstream.completed_runs()) == 4:
                break
            self.multi.play_next_date(upstream)
        self.assertEqual(4, len(upstream.completed_runs()))
        self.assertEqual(28, upstream.summary()["completed_match_count"])
        replay = self.multi.load("shikoku", year=2027)
        self.assertEqual(
            {cid: r.outcome.champion_school_id
             for cid, r in upstream.completed_runs().items()},
            {cid: r.outcome.champion_school_id
             for cid, r in replay.completed_runs().items()},
        )
        proof = project_same_year_regional_feeders(
            self.multi, replay, REGIONAL,
        )
        self.assertTrue(proof["all_feeder_results_verified"])
        self.assertEqual(4, proof["feeder_rule_count"])
        self.assertEqual(8, proof["verified_entrant_count"])
        self.assertFalse(proof["regional_runtime_ready"])
        self.assertEqual([], proof["unresolved_feeder_rule_ids"])
        verified = []
        for feed in proof["feeder_rules"]:
            cid = feed["source_competition_id"]
            self.assertEqual(2, feed["quota"])
            self.assertEqual(
                replay.completed_runs()[cid].outcome.final_ranking_school_ids[:2],
                feed["school_ids"],
            )
            self.assertEqual("verified_game_qualification", feed["status"])
            self.assertEqual(64, len(feed["evidence_sha256"]))
            verified.extend(feed["school_ids"])
        self.assertEqual(8, len(set(verified)))
        self.assertEqual(set(verified), set(proof["verified_school_ids"]))

        with sqlite3.connect(self._archive().db_path) as db:
            prior_ledger = db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0]
            year_metadata = db.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0]
        regional = self.regional.start("shikoku", year=2027)
        self.assertEqual(REGIONAL, regional.competition_id)
        self.assertEqual(set(verified),
                         set(regional.preview.annual.entrant_school_ids))
        self.assertEqual(8, regional.summary()["entrant_count"])
        first = self.regional.play_next_date(regional)
        self.assertGreater(first["played_match_count"], 0)
        self.assertGreaterEqual(first["date"], "2027-04-25")
        restored = self.regional.load("shikoku", year=2027)
        self.assertEqual(
            regional.preview.scheduled.public_snapshot(),
            restored.preview.scheduled.public_snapshot(),
        )
        for _ in range(10):
            if restored.preview.scheduled.is_complete:
                break
            self.regional.play_next_date(restored)
        self.assertTrue(restored.preview.scheduled.is_complete)
        outcome = restored.preview.scheduled.to_competition_run()
        self.assertEqual(8, len(outcome.main_entrant_school_ids))
        self.assertEqual(7, outcome.outcome.match_count)
        self.assertIn(outcome.outcome.champion_school_id, verified)
        reloaded = self.regional.load("shikoku", year=2027)
        self.assertEqual(
            outcome.outcome.champion_school_id,
            reloaded.preview.scheduled.to_competition_run().outcome.champion_school_id,
        )

        records = self._archive().list_matches(2027, limit=500)
        self.assertEqual(35, len(records))
        self.assertEqual(7, len([
            x for x in records if x["competition_id"] == REGIONAL
        ]))
        for row in records:
            self.assertEqual("ability_model_v1", row["score_source"])
            self.assertEqual("game_projection_v1", row["date_source"])
            self.assertTrue(row["inning_scores"])
            self.assertTrue(row["batter_stats"])
            self.assertTrue(row["pitcher_stats"])
        with sqlite3.connect(self._archive().db_path) as db:
            self.assertEqual(prior_ledger, db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0])
            self.assertEqual(year_metadata, db.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0])
        self.assertEqual(
            b"prior-year manual save stays immutable", original.read_bytes(),
        )

        self._archive().seal_year(2027, expected_match_count=len(records))

    def test_invalid_prefecture_and_unrostered_source_fail_closed(self):
        specs = [{**spec, "entrant_school_ids": list(spec["entrant_school_ids"])}
                 for spec in self.inputs]
        specs[0]["entrant_school_ids"][-1] = self.entries["CMP000141"][0]
        with self.assertRaisesRegex(FutureCompetitionNotReady, "outside"):
            self._start(specs)
        self.assertFalse(
            (self.slot / "career_multi_previews" / "2027.json").exists()
        )
        with tempfile.TemporaryDirectory() as folder:
            rosters = CareerRosterArchive(
                Path(folder) / "no_rosters.sqlite3"
            )
            with self.assertRaisesRegex(FutureCompetitionNotReady, "roster"):
                prepare_future_shikoku_direct_main_preview(
                    data_root=DATA, year=2027,
                    competition_id="CMP000139",
                    entrant_school_ids=self.entries["CMP000139"],
                    roster_archive=rosters, repo=self.repo,
                    base_seed=SEED, career_seed=SEED,
                )

    def test_unauthorized_feeder_school_cannot_rewrite_dated_source(self):
        upstream = self._completed_source_year()
        regional = self.regional.start("shikoku", year=2027)
        self.regional.play_next_date(regional)
        with sqlite3.connect(self._archive().db_path) as db:
            row = db.execute(
                "SELECT match_id, payload_json FROM historical_matches "
                "WHERE year=2027 AND competition_id='CMP000139' LIMIT 1"
            ).fetchone()
            db.execute(
                "UPDATE historical_matches SET payload_json=? "
                "WHERE year=2027 AND competition_id='CMP000139' "
                "AND match_id=?", ('{"changed":true}', row[0]),
            )
        with self.assertRaises((RegionalFeederNotReady, CareerPreviewSaveError)):
            self.regional.load("shikoku", year=2027)

    def test_shikoku_rejects_kanto_only_placement_and_sidecar(self):
        self._completed_source_year()
        with self.assertRaisesRegex(RegionalFeederNotReady, "Shikoku"):
            self.regional.start(
                "shikoku", year=2027,
                placement_decider_match_ids={"CMP000092": "X"},
            )
        with self.assertRaisesRegex(RegionalFeederNotReady, "Shikoku"):
            self.regional.start(
                "shikoku", year=2027, kanagawa_sidecar_enabled=True,
            )


if __name__ == "__main__":
    unittest.main()
