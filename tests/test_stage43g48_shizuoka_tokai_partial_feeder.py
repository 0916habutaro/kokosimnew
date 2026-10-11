"""Stage43G-48: Shizuoka FMT025 qualifiers qualify two of Tokai's 8.

2027 participants, dates and results are sandbox projections only. A Gifu
prior-autumn exemption and Aichi/Mie Senbatsu exemptions are NOT fabricated.
"""
from __future__ import annotations

from pathlib import Path
import json
import shutil
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService,
)
from phase2_engine.career_regional_main_checkpoint import (
    CareerRegionalMainCheckpointService,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.future_shizuoka_fmt025_bridge import (
    prepare_future_shizuoka_fmt025_preview,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository
from phase2_engine.same_year_regional_feeder_gate import (
    RegionalFeederNotReady, project_same_year_regional_feeders,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEED = 2026101148
SHIZUOKA = "CMP000111"
TOKUSHIMA = "CMP000139"
TOKAI = "CMP000008"


class Stage43G48ShizuokaToTokaiPartialFeeder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.tmp_base = tempfile.TemporaryDirectory()
        base = Path(cls.tmp_base.name)
        cls.original_history = base / "historical_matches.sqlite3"
        cls.original_rosters = base / "career_rosters.sqlite3"
        history = HistoricalMatchArchive(cls.original_history)
        history.sync(
            year=2026, rng_seed=SEED, resolver_contract="game_v1",
            plan_fingerprint="stage43g48-sealed-prior-sandbox",
            completed=[],
        )
        history.seal_year(2026, expected_match_count=0)
        roster = CareerRosterArchive(cls.original_rosters)
        generator = PlayerRosterGenerator()
        stage = cls.repo.stage_by_code(SHIZUOKA, "BRANCH_QUALIFIER")
        groups = cls.repo.groups_by_stage[stage["stage_id"]]
        assert len(groups) == 3
        cls.group_memberships = {}
        cls.group_quota = {}
        entrants = []
        for group in groups:
            gid = group["stage_group_id"]
            slots = cls.repo.param(
                stage["stage_id"], "output_slots", gid,
                int(group.get("advance_slots_to_next") or 0),
            )
            schools = sorted(cls.repo.group_school_ids(group, 2026))
            assert len(schools) >= slots + 1, (
                gid, slots, len(schools),
            )
            members = schools[:slots + 1]
            cls.group_memberships[gid] = members
            cls.group_quota[gid] = slots
            entrants.extend(members)
        assert sum(cls.group_quota.values()) == 39
        assert len(entrants) == len(set(entrants))
        cls.shizuoka_ids = entrants
        cls.tokushima_ids = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "36"
        )[:8]
        assert len(cls.tokushima_ids) == 8
        cls.specs = [
            {
                "competition_id": SHIZUOKA,
                "entry_mode": "shizuoka_fmt025_qualifier_v1",
                "entrant_school_ids": entrants,
                "group_entrant_school_ids": cls.group_memberships,
            },
            {
                "competition_id": TOKUSHIMA,
                "entry_mode": "shikoku_direct_main_v1",
                "entrant_school_ids": cls.tokushima_ids,
                "group_entrant_school_ids": {},
            },
        ]
        for sid in sorted(set(entrants + cls.tokushima_ids)):
            roster.save_initial_roster(
                generator.generate_for_school_id(cls.repo, sid, 2026, SEED),
            )
            roster.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=SEED,
            )

    @classmethod
    def tearDownClass(cls):
        cls.tmp_base.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.save_root = Path(self.temp.name)
        self.slot = self.save_root / "shizuoka"
        self.slot.mkdir()
        shutil.copy2(
            self.original_history,
            self.slot / "historical_matches.sqlite3",
        )
        shutil.copy2(
            self.original_rosters,
            self.slot / "career_rosters.sqlite3",
        )
        self.multi = CareerMultiPreviewCheckpointService(
            self.repo, DATA, save_root=self.save_root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.regional = CareerRegionalMainCheckpointService(
            self.multi, target_competition_id=TOKAI,
        )
        self.archive = HistoricalMatchArchive(
            self.slot / "historical_matches.sqlite3",
        )

    def _start(self, specs=None):
        return self.multi.start(
            "shizuoka", year=2027,
            competitions=self.specs if specs is None else specs,
            base_seed=SEED, career_seed=SEED,
        )

    def _finish(self):
        session = self._start()
        for _ in range(35):
            if SHIZUOKA in session.completed_runs():
                break
            event = self.multi.play_next_date(session)
            self.assertGreater(event["played_match_count"], 0)
        self.assertIn(SHIZUOKA, session.completed_runs())
        return self.multi.load("shizuoka", year=2027)

    def test_three_fmt025_groups_real_results_verify_two_tokai_seats(self):
        manual = self.slot / "manual.json"
        manual.write_bytes(b"original")
        session = self._start()
        pending = project_same_year_regional_feeders(
            self.multi, session, TOKAI,
        )
        self.assertFalse(pending["all_feeder_results_verified"])
        self.assertEqual(0, pending["verified_entrant_count"])
        with self.assertRaises(RegionalFeederNotReady):
            self.regional.start("shizuoka", year=2027)

        for _ in range(35):
            if SHIZUOKA in session.completed_runs():
                break
            self.multi.play_next_date(session)
        self.assertIn(SHIZUOKA, session.completed_runs())
        saved = self.multi.load("shizuoka", year=2027)
        self.assertEqual(
            session.previews[SHIZUOKA].scheduled.public_snapshot(),
            saved.previews[SHIZUOKA].scheduled.public_snapshot(),
        )
        result = saved.completed_runs()[SHIZUOKA]
        self.assertEqual(39, len(result.main_entrant_school_ids))
        self.assertEqual(38, result.outcome.match_count)
        qualifier = next(
            row for row in result.stage_executions
            if row.stage_code == "BRANCH_QUALIFIER"
        )
        self.assertEqual(3, qualifier.metadata["group_count"])
        self.assertEqual(
            {"FMT025"},
            set(qualifier.metadata["group_models"].values()),
        )
        self.assertEqual(
            self.group_quota,
            {gid: len(ids) for gid, ids
             in qualifier.metadata["group_outputs"].items()},
        )
        archive_rows = self.archive.list_matches(2027, limit=500)
        source_rows = [
            row for row in archive_rows
            if row["competition_id"] == SHIZUOKA
        ]
        self.assertEqual(38, sum(
            row["stage_code"] == "MAIN" for row in source_rows
        ))
        qualifiers = [
            row for row in source_rows
            if row["stage_code"] == "BRANCH_QUALIFIER"
        ]
        self.assertGreater(len(qualifiers), 0)
        self.assertTrue(all(
            row["match_date"] < "2027-04-18" for row in qualifiers
        ))
        self.assertTrue(all(
            row["date_source"] == "game_projection_v1"
            and row["score_source"] == "ability_model_v1"
            and row["inning_scores"] and row["batter_stats"]
            and row["pitcher_stats"]
            for row in source_rows
        ))

        gate = project_same_year_regional_feeders(
            self.multi, saved, TOKAI,
        )
        self.assertFalse(gate["all_feeder_results_verified"])
        self.assertEqual(4, gate["feeder_rule_count"])
        self.assertEqual(2, gate["verified_entrant_count"])
        self.assertEqual(3, len(gate["unresolved_feeder_rule_ids"]))
        actual = next(
            r for r in gate["feeder_rules"]
            if r["source_competition_id"] == SHIZUOKA
        )
        self.assertEqual("verified_game_qualification", actual["status"])
        self.assertEqual(
            result.outcome.final_ranking_school_ids[:2],
            actual["school_ids"],
        )
        self.assertEqual(64, len(actual["evidence_sha256"]))
        self.assertFalse(gate["regional_runtime_ready"])
        with self.assertRaises(RegionalFeederNotReady):
            self.regional.start("shizuoka", year=2027)
        self.assertFalse(
            (self.slot / "career_regional_previews" /
             f"2027_{TOKAI}.json").exists()
        )
        with sqlite3.connect(self.archive.db_path) as conn:
            self.assertEqual(
                "sealed",
                conn.execute("SELECT status FROM career_years WHERE year=2026")
                .fetchone()[0],
            )
            self.assertEqual(
                "active",
                conn.execute("SELECT status FROM career_years WHERE year=2027")
                .fetchone()[0],
            )
        self.assertEqual(b"original", manual.read_bytes())

    def test_wrong_prefecture_group_and_missing_roster_rejected(self):
        invalid = [{
            **spec,
            "group_entrant_school_ids": {
                gid: list(group) for gid, group
                in spec["group_entrant_school_ids"].items()
            },
        } for spec in self.specs]
        gid = next(iter(invalid[0]["group_entrant_school_ids"]))
        invalid[0]["group_entrant_school_ids"][gid][0] = self.tokushima_ids[0]
        with self.assertRaises(FutureCompetitionNotReady):
            self._start(invalid)
        self.assertFalse(
            (self.slot / "career_multi_previews" / "2027.json").exists()
        )
        with tempfile.TemporaryDirectory() as tmp:
            missing = CareerRosterArchive(
                Path(tmp) / "roster.sqlite3",
            )
            with self.assertRaisesRegex(FutureCompetitionNotReady, "roster"):
                prepare_future_shizuoka_fmt025_preview(
                    data_root=DATA, year=2027,
                    competition_id=SHIZUOKA,
                    entrant_school_ids=self.shizuoka_ids,
                    group_entrant_school_ids=self.group_memberships,
                    roster_archive=missing, repo=self.repo,
                    base_seed=SEED, career_seed=SEED,
                )

    def test_tampered_saved_main_result_cannot_qualify(self):
        saved = self._finish()
        with sqlite3.connect(self.archive.db_path) as conn:
            row = conn.execute(
                "SELECT match_id FROM historical_matches "
                "WHERE year=2027 AND competition_id=? "
                "AND json_extract(payload_json, '$.stage_code')='MAIN' LIMIT 1",
                (SHIZUOKA,),
            ).fetchone()
            assert row
            conn.execute(
                "UPDATE historical_matches SET payload_json=? "
                "WHERE year=2027 AND competition_id=? AND match_id=?",
                ('{"modified":true}', SHIZUOKA, row[0]),
            )
        with self.assertRaises(RegionalFeederNotReady):
            project_same_year_regional_feeders(
                self.multi, saved, TOKAI,
            )


if __name__ == "__main__":
    unittest.main()
