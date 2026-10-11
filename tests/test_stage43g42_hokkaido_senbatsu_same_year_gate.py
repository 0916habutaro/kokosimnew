"""Stage43G-42: complete saved same-year Senbatsu is the only spring proof."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_hokkaido_senbatsu_gate import (
    HokkaidoRecommendationNotReady,
    SENBATSU_ID, SPRING_HOKKAIDO_ID,
    certify_saved_senbatsu_hokkaido,
    prepare_hokkaido_spring_after_senbatsu,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_competition_bridge import (
    prepare_future_direct_main_preview,
)
from phase2_engine.future_season_blueprint import build_future_season_blueprint
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEED = 2026101142


class Stage43G42HokkaidoSenbatsuSameYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.fixture = tempfile.TemporaryDirectory()
        cls.archive = HistoricalMatchArchive(
            Path(cls.fixture.name) / "historical_matches.sqlite3"
        )
        cls.rosters = CareerRosterArchive(
            Path(cls.fixture.name) / "career_rosters.sqlite3"
        )
        cls.archive.sync(
            year=2026, rng_seed=SEED,
            resolver_contract="game_v1",
            plan_fingerprint="stage43g42-sealed-prior-year",
            completed=[],
        )
        cls.archive.seal_year(2026, expected_match_count=0)
        cls.archive.register_next_year(
            year=2027, rng_seed=SEED,
            resolver_contract="stage43g42-test-v1",
            plan_fingerprint="same-year-senbatsu-then-spring",
        )
        cls.senbatsu_seed = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] != "01"
        )[:31]
        qualifier = cls.repo.stage_by_code(
            SPRING_HOKKAIDO_ID, "BRANCH_QUALIFIER",
        )
        cls.groups = cls.repo.groups_by_stage[qualifier["stage_id"]]
        assert len(cls.groups) == 10
        cls.group_input = {}
        for group in cls.groups:
            gid = group["stage_group_id"]
            quota = cls.repo.param(
                qualifier["stage_id"], "output_slots", gid,
                int(group["advance_slots_to_next"]),
            )
            members = sorted(cls.repo.group_school_ids(group, 2026))
            assert len(members) >= quota + 1
            cls.group_input[gid] = members[:quota + 1]
        cls.recommended = cls.group_input[cls.groups[0]["stage_group_id"]][0]
        cls.senbatsu_schools = [cls.recommended, *cls.senbatsu_seed]
        cls.generator = PlayerRosterGenerator()
        roster_ids = sorted(set(
            sid for members in cls.group_input.values() for sid in members
        ) | set(cls.senbatsu_schools))
        for sid in roster_ids:
            cls.rosters.save_initial_roster(
                cls.generator.generate_for_school_id(
                    cls.repo, sid, 2026, SEED,
                )
            )
            cls.rosters.advance_and_save(
                cls.repo.team(sid), next_year=2027,
                career_seed=SEED,
            )
        blueprint = build_future_season_blueprint(
            DATA, year=2027, base_seed=SEED,
        )
        cls.senbatsu_preview = prepare_future_direct_main_preview(
            blueprint=blueprint,
            competition_id=SENBATSU_ID,
            entrant_school_ids=cls.senbatsu_schools,
            roster_archive=cls.rosters,
            repo=cls.repo,
            career_seed=SEED,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        for _ in range(20):
            if cls.senbatsu_preview.scheduled.is_complete:
                break
            cls.senbatsu_preview.play_next_date()
        assert cls.senbatsu_preview.scheduled.is_complete
        cls.run = cls.senbatsu_preview.scheduled.to_competition_run()
        cls.records = [
            dict(match.__dict__)
            for match in cls.senbatsu_preview.scheduled.matches.values()
            if match.status == "completed"
        ]
        assert len(cls.records) == 31
        cls.archive.sync(
            year=2027, rng_seed=SEED,
            resolver_contract="stage43g42-test-v1",
            plan_fingerprint="same-year-senbatsu-then-spring",
            completed=cls.records,
        )

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def test_same_year_A_archive_certifies_only_hokkaido_participants(self):
        proof = certify_saved_senbatsu_hokkaido(
            self.repo, self.archive, self.run, year=2027,
        )
        self.assertEqual([self.recommended],
                         proof["recommended_hokkaido_school_ids"])
        self.assertEqual(31, proof["source_match_count"])
        self.assertTrue(proof["verified_same_year_saved_A_games"])
        self.assertFalse(proof["source_year_sealing_required"])
        self.assertFalse(proof["official_entrant_list"])
        self.assertEqual(64, len(proof["source_matches_sha256"]))
        self.assertEqual("active", self.archive.list_years()[-1]["status"])
        self.assertEqual(
            proof["source_matches_sha256"],
            certify_saved_senbatsu_hokkaido(
                self.repo, self.archive, self.run, year=2027,
            )["source_matches_sha256"],
        )

    def test_future_hokkaido_spring_Fmt001_recommendation_not_double_counted(self):
        preview, proof = prepare_hokkaido_spring_after_senbatsu(
            data_root=DATA, year=2027, repo=self.repo,
            source_archive=self.archive,
            completed_senbatsu=self.run,
            group_entrant_school_ids=self.group_input,
            roster_archive=self.rosters,
            base_seed=SEED, career_seed=SEED,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )
        self.assertEqual(SPRING_HOKKAIDO_ID, preview.competition_id)
        self.assertEqual([self.recommended],
                         preview.annual.direct_main_entry_school_ids)
        self.assertEqual(15, proof["qualifier_slots"])
        self.assertEqual(16, proof["total_main_school_count_projected"])
        self.assertFalse(proof["direct_recommendations_have_qualifier_quota_effect"])
        self.assertFalse(proof["save_checkpoint_connected"])
        self.assertTrue(all(
            self.recommended not in members
            for members in preview.annual.group_entrant_school_ids.values()
        ))
        self.assertIn(self.recommended, preview.annual.entrant_school_ids)
        self.assertEqual(0, len([
            m for m in preview.scheduled.matches.values()
            if m.stage_code == "MAIN"
        ]))
        processed_pre = False
        for _ in range(20):
            if preview.scheduled.is_complete:
                break
            result = preview.play_next_date()
            if result["date"] < "2027-05-25":
                processed_pre = True
                self.assertFalse(any(
                    m.status == "completed" and m.stage_code == "MAIN"
                    for m in preview.scheduled.matches.values()
                ))
        self.assertTrue(processed_pre)
        self.assertTrue(preview.scheduled.is_complete)
        run = preview.scheduled.to_competition_run()
        self.assertEqual(16, len(run.main_entrant_school_ids))
        self.assertEqual(1, run.main_entrant_school_ids.count(self.recommended))
        self.assertEqual(15, run.outcome.match_count)
        self.assertIn(run.outcome.champion_school_id,
                      run.main_entrant_school_ids)
        # Option-A records remain compatible with same-year active SQLite.
        future_records = [
            dict(match.__dict__) for match in preview.scheduled.matches.values()
            if match.status == "completed"
        ]
        self.archive.sync(
            year=2027, rng_seed=SEED,
            resolver_contract="stage43g42-test-v1",
            plan_fingerprint="same-year-senbatsu-then-spring",
            completed=[*self.records, *future_records],
        )
        self.assertEqual(31 + len(future_records),
                         len(self.archive.list_matches(2027, limit=200)))
        self.assertEqual(
            proof["source_matches_sha256"],
            certify_saved_senbatsu_hokkaido(
                self.repo, self.archive, self.run, year=2027,
            )["source_matches_sha256"],
        )

    def test_wrong_year_or_incomplete_senbatsu_cannot_award_access(self):
        with self.assertRaisesRegex(HokkaidoRecommendationNotReady,
                                    "same-year"):
            certify_saved_senbatsu_hokkaido(
                self.repo, self.archive, self.run, year=2028,
            )
        partial = deepcopy(self.run)
        main = next(x for x in partial.stage_executions
                    if x.stage_code == "MAIN")
        main.matches.pop()
        with self.assertRaises(HokkaidoRecommendationNotReady):
            certify_saved_senbatsu_hokkaido(
                self.repo, self.archive, partial, year=2027,
            )
        copy = deepcopy(self.run)
        copy.main_entrant_school_ids[0] = "NOT_A_REAL_TEAM"
        with self.assertRaises(HokkaidoRecommendationNotReady):
            certify_saved_senbatsu_hokkaido(
                self.repo, self.archive, copy, year=2027,
            )

    def test_bad_hokkaido_group_or_qualifier_quota_rejected(self):
        wrong = {k: list(v) for k, v in self.group_input.items()}
        gid = self.groups[0]["stage_group_id"]
        wrong[gid][1] = self.senbatsu_seed[0]
        with self.assertRaisesRegex(
            HokkaidoRecommendationNotReady, "Hokkaido school",
        ):
            prepare_hokkaido_spring_after_senbatsu(
                data_root=DATA, year=2027, repo=self.repo,
                source_archive=self.archive, completed_senbatsu=self.run,
                group_entrant_school_ids=wrong, roster_archive=self.rosters,
                base_seed=SEED, career_seed=SEED,
            )
        wrong = {k: list(v) for k, v in self.group_input.items()}
        wrong[gid] = [self.recommended]
        with self.assertRaisesRegex(
            HokkaidoRecommendationNotReady, "quota",
        ):
            prepare_hokkaido_spring_after_senbatsu(
                data_root=DATA, year=2027, repo=self.repo,
                source_archive=self.archive, completed_senbatsu=self.run,
                group_entrant_school_ids=wrong, roster_archive=self.rosters,
                base_seed=SEED, career_seed=SEED,
            )

    def test_tampered_saved_senbatsu_checksum_fails_closed(self):
        # Only this test changes the ephemeral fixture, then restores the
        # exact original game so all other tests remain order-independent.
        with sqlite3.connect(self.archive.db_path) as conn:
            row = conn.execute(
                "SELECT match_id,payload_json FROM historical_matches "
                "WHERE year=2027 AND competition_id=? LIMIT 1",
                (SENBATSU_ID,),
            ).fetchone()
            conn.execute(
                "UPDATE historical_matches SET payload_json=? "
                "WHERE year=2027 AND competition_id=? AND match_id=?",
                ('{"tampered":true}', SENBATSU_ID, row[0]),
            )
        try:
            with self.assertRaisesRegex(
                HokkaidoRecommendationNotReady, "checksum",
            ):
                certify_saved_senbatsu_hokkaido(
                    self.repo, self.archive, self.run, year=2027,
                )
        finally:
            with sqlite3.connect(self.archive.db_path) as conn:
                conn.execute(
                    "UPDATE historical_matches SET payload_json=? "
                    "WHERE year=2027 AND competition_id=? AND match_id=?",
                    (row[1], SENBATSU_ID, row[0]),
                )


if __name__ == "__main__":
    unittest.main()
