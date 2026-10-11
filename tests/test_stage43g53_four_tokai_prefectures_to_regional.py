"""Stage43G-53: sealed previous autumn + Senbatsu + four Tokai prefectures.

All results are simulated for 2027 using the 2026 structural master, not
official 2027 participants, match dates, or records.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService, CareerPreviewSaveError,
)
from phase2_engine.career_regional_main_checkpoint import (
    CareerRegionalMainCheckpointService,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_tokai_concurrent_preflight import (
    CareerTokaiConcurrentPreflight,
)
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.same_year_regional_feeder_gate import (
    RegionalFeederNotReady, project_same_year_regional_feeders,
)

from test_stage43f7_gifu_tokyo_access import simulated_autumn_run
import test_stage43g51_tokai_concurrent_preflight as stage51

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BASE = stage51.Stage43G51TokaiPreseasonFreeze
SEED = stage51.SEED
NATIONAL = stage51.NATIONAL
AICHI = stage51.AICHI
MIE = stage51.MIE
GIFU = "CMP000109"
GIFU_AUTUMN = "CMP000110"
SHIZUOKA = "CMP000111"
TOKAI = "CMP000008"


class Stage43G53FourPrefecturesToTokaiRegional(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        BASE.setUpClass()
        cls.repo = BASE.repo
        cls.base = BASE.base
        cls.direct = BASE.direct
        cls.groups = BASE.groups
        cls.national = BASE.national
        cls.rosters = BASE.rosters
        cls.tochigi = BASE.tochigi

        cls.future_groups = {}
        cls.future_entrants = {}
        extra = set()
        excluded_national = set(cls.national)
        for cid, pcode in ((GIFU, "21"), (SHIZUOKA, "22")):
            qualifier = cls.repo.stage_by_code(cid, "BRANCH_QUALIFIER")
            groups = cls.repo.groups_by_stage[qualifier["stage_id"]]
            expected_groups = 4 if cid == GIFU else 3
            assert len(groups) == expected_groups
            mapping = {}
            quota_sum = 0
            for group in groups:
                gid = group["stage_group_id"]
                quota = cls.repo.param(
                    qualifier["stage_id"], "output_slots", gid,
                    int(group.get("advance_slots_to_next") or 0),
                )
                eligible = sorted(
                    cls.repo.group_school_ids(group, 2026)
                    - excluded_national
                )
                assert len(eligible) >= quota + 1, (
                    cid, gid, len(eligible), quota,
                )
                selected = eligible[:quota + 1]
                mapping[gid] = selected
                quota_sum += quota
                extra.update(selected)
            assert quota_sum == (20 if cid == GIFU else 39)
            members = [sid for ids in mapping.values() for sid in ids]
            assert len(members) == len(set(members))
            cls.future_groups[cid] = mapping
            cls.future_entrants[cid] = members

        all_gifu = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "21"
        )
        available_autumn = [
            sid for sid in all_gifu
            if sid not in set(cls.future_entrants[GIFU])
            and sid not in excluded_national
        ]
        assert len(available_autumn) >= 8
        cls.autumn_teams = available_autumn[:8]
        autumn, records = simulated_autumn_run(GIFU_AUTUMN, cls.autumn_teams)
        cls.autumn_top_four = list(autumn.outcome.final_ranking_school_ids[:4])
        cls.future_entrants[GIFU] = [
            *cls.autumn_top_four, *cls.future_entrants[GIFU],
        ]
        extra.update(cls.autumn_top_four)
        cls.history = Path(BASE.base.name) / "with_gifu_autumn.sqlite3"
        archive = HistoricalMatchArchive(cls.history)
        archive.sync(
            year=2026, rng_seed=SEED,
            resolver_contract="game_v1",
            plan_fingerprint="stage43g53-sealed-gifu-autumn-sandbox",
            completed=records,
        )
        archive.seal_year(2026, expected_match_count=len(records))
        CareerCompetitionOutcomes(archive).record_completed(autumn)
        rosters = CareerRosterArchive(cls.rosters)
        generator = PlayerRosterGenerator()
        for sid in sorted(extra):
            if rosters.roster(2026, sid) is None:
                rosters.save_initial_roster(
                    generator.generate_for_school_id(
                        cls.repo, sid, 2026, SEED,
                    )
                )
                rosters.advance_and_save(
                    cls.repo.team(sid), next_year=2027, career_seed=SEED,
                )
        cls.specs = [
            {
                "competition_id": NATIONAL,
                "entry_mode": "national_invitational_main_v1",
                "entrant_school_ids": list(cls.national),
                "group_entrant_school_ids": {},
            },
            {
                "competition_id": GIFU,
                "entry_mode": "gifu_sealed_autumn_fmt002_v1",
                "entrant_school_ids": list(cls.future_entrants[GIFU]),
                "group_entrant_school_ids": cls.future_groups[GIFU],
            },
            {
                "competition_id": SHIZUOKA,
                "entry_mode": "shizuoka_fmt025_qualifier_v1",
                "entrant_school_ids": list(cls.future_entrants[SHIZUOKA]),
                "group_entrant_school_ids": cls.future_groups[SHIZUOKA],
            },
        ]

    @classmethod
    def tearDownClass(cls):
        BASE.tearDownClass()

    def setUp(self):
        BASE.setUp(self)
        self.regional = CareerRegionalMainCheckpointService(
            self.multi, target_competition_id=TOKAI,
        )

    def _start(self, specs=None):
        session = self.multi.start(
            "tokai", year=2027,
            competitions=self.specs if specs is None else specs,
            base_seed=SEED, career_seed=SEED,
        )
        self.service.freeze(
            "tokai", year=2027,
            group_entrant_school_ids=self.groups,
        )
        self.multi.add_tokai_concurrent(session)
        return session

    def _finish_prefectures(self):
        session = self._start()
        gate = project_same_year_regional_feeders(
            self.multi, session, TOKAI,
        )
        self.assertEqual(4, gate["feeder_rule_count"])
        self.assertEqual(0, gate["verified_entrant_count"])
        with self.assertRaises(RegionalFeederNotReady):
            self.regional.start("tokai", year=2027)
        self.assertEqual(
            "frozen_waiting_for_31_saved_senbatsu_games",
            self.service.audit("tokai", year=2027)["status"],
        )
        saw_same_date = False
        for _ in range(65):
            if len(session.completed_runs()) == 5:
                break
            step = self.multi.play_next_date(session)
            self.assertGreater(step["played_match_count"], 0)
            if step["date"] == "2027-03-20":
                self.assertEqual(
                    {NATIONAL, GIFU, SHIZUOKA, AICHI, MIE},
                    set(step["competition_match_counts"]),
                )
                saw_same_date = True
                replay = self.multi.load("tokai", year=2027)
                self.assertEqual(
                    session.processed_dates, replay.processed_dates,
                )
                for cid in session.previews:
                    self.assertEqual(
                        session.previews[cid].scheduled.public_snapshot(),
                        replay.previews[cid].scheduled.public_snapshot(),
                    )
        self.assertTrue(saw_same_date)
        self.assertEqual(5, len(session.completed_runs()))
        return self.multi.load("tokai", year=2027)

    def test_all_four_prefectures_certify_eight_and_tokai_seven_saved_games(self):
        manual = self.slot / "original_user_save.json"
        manual.write_bytes(b"never modify unrelated save")
        with sqlite3.connect(self.archive.db_path) as conn:
            old_ledger = conn.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0]
        saved = self._finish_prefectures()
        counts = {GIFU: 24, SHIZUOKA: 39, AICHI: 49, MIE: 26}
        for cid, n in counts.items():
            result = saved.completed_runs()[cid]
            self.assertEqual(n, len(result.main_entrant_school_ids))
            self.assertEqual(n-1, result.outcome.match_count)
        self.assertEqual(
            self.autumn_top_four,
            saved.previews[GIFU].annual.direct_main_entry_school_ids,
        )
        certified = self.service.audit("tokai", year=2027)
        self.assertEqual(
            "source_games_confirm_frozen_preseason_selection",
            certified["status"],
        )
        gate = project_same_year_regional_feeders(
            self.multi, saved, TOKAI,
        )
        self.assertTrue(gate["all_feeder_results_verified"])
        self.assertEqual(8, gate["verified_entrant_count"])
        self.assertEqual(8, gate["expected_entrant_count"])
        self.assertEqual(4, gate["feeder_rule_count"])
        self.assertEqual([], gate["unresolved_feeder_rule_ids"])
        self.assertEqual(8, len(set(gate["verified_school_ids"])))
        for cid in counts:
            rule = next(
                x for x in gate["feeder_rules"]
                if x["source_competition_id"] == cid
            )
            self.assertEqual("verified_game_qualification", rule["status"])
            self.assertEqual(
                saved.completed_runs()[cid].outcome.final_ranking_school_ids[:2],
                rule["school_ids"],
            )
        regional = self.regional.start("tokai", year=2027)
        self.assertEqual(8, len(regional.preview.annual.entrant_school_ids))
        self.assertEqual(
            set(gate["verified_school_ids"]),
            set(regional.preview.annual.entrant_school_ids),
        )
        first = self.regional.play_next_date(regional)
        self.assertGreater(first["played_match_count"], 0)
        reopened = self.regional.load("tokai", year=2027)
        self.assertEqual(
            regional.preview.scheduled.public_snapshot(),
            reopened.preview.scheduled.public_snapshot(),
        )
        for _ in range(10):
            if regional.preview.scheduled.is_complete:
                break
            self.regional.play_next_date(regional)
        self.assertTrue(regional.preview.scheduled.is_complete)
        final = self.regional.load("tokai", year=2027)
        self.assertEqual(7, final.preview.scheduled.to_competition_run().outcome.match_count)
        self.assertEqual(
            regional.preview.scheduled.public_snapshot(),
            final.preview.scheduled.public_snapshot(),
        )
        records = self.archive.list_matches(2027, limit=500)
        tokai_games = [x for x in records if x["competition_id"] == TOKAI]
        self.assertEqual(7, len(tokai_games))
        self.assertTrue(all(
            x["score_source"] == "ability_model_v1"
            and x["date_source"] == "game_projection_v1"
            and x["inning_scores"] and x["batter_stats"] and x["pitcher_stats"]
            for x in tokai_games
        ))
        with sqlite3.connect(self.archive.db_path) as conn:
            self.assertEqual(old_ledger, conn.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0])
            self.assertEqual("sealed", conn.execute(
                "SELECT status FROM career_years WHERE year=2026"
            ).fetchone()[0])
        self.assertEqual(b"never modify unrelated save", manual.read_bytes())

    def test_saved_source_tamper_blocks_regional_seat(self):
        saved = self._finish_prefectures()
        self.assertTrue(project_same_year_regional_feeders(
            self.multi, saved, TOKAI,
        )["all_feeder_results_verified"])
        with sqlite3.connect(self.archive.db_path) as conn:
            match = conn.execute(
                "SELECT match_id FROM historical_matches WHERE year=2027 "
                "AND competition_id=? LIMIT 1",
                (AICHI,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE historical_matches SET payload_json=? WHERE "
                "year=2027 AND competition_id=? AND match_id=?",
                ('{"forged":true}', AICHI, match),
            )
        with self.assertRaises((
            RegionalFeederNotReady, CareerPreviewSaveError, ValueError,
        )):
            self.regional.start("tokai", year=2027)
        self.assertFalse(self.regional._path("tokai", 2027).exists())


if __name__ == "__main__":
    unittest.main()
