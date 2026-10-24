"""Stage43G-43: late Hokkaido spring entry in an existing saved career year.

The prior year stays sealed; same-year source games are verified, replayed,
and persist alongside spring without rewriting the initial yearly identity.
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
from phase2_engine.career_preview_checkpoint import _checksum
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEED = 2026101143
SENBATSU = "CMP000001"
SPRING = "CMP000004"
SHIKOKU = "CMP000011"


class Stage43G43DynamicSpringCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.tmp_base = tempfile.TemporaryDirectory()
        base = Path(cls.tmp_base.name)
        cls.original_history = base / "historical_matches.sqlite3"
        cls.original_rosters = base / "career_rosters.sqlite3"
        history = HistoricalMatchArchive(cls.original_history)
        history.sync(
            year=2026, rng_seed=SEED,
            resolver_contract="game_v1",
            plan_fingerprint="stage43g43-sealed-prior-sandbox",
            completed=[],
        )
        history.seal_year(2026, expected_match_count=0)
        archive = CareerRosterArchive(cls.original_rosters)
        generator = PlayerRosterGenerator()

        qualifier = cls.repo.stage_by_code(SPRING, "BRANCH_QUALIFIER")
        cls.group_inputs = {}
        for row in cls.repo.groups_by_stage[qualifier["stage_id"]]:
            gid = row["stage_group_id"]
            slots = cls.repo.param(
                qualifier["stage_id"], "output_slots", gid,
                int(row["advance_slots_to_next"]),
            )
            candidates = sorted(cls.repo.group_school_ids(row, 2026))
            assert len(candidates) >= slots + 1
            cls.group_inputs[gid] = candidates[:slots + 1]
        assert len(cls.group_inputs) == 10
        cls.recommended = next(iter(cls.group_inputs.values()))[0]
        non_hokkaido = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] != "01"
        )[:31]
        cls.senbatsu = [cls.recommended, *non_hokkaido]
        shikoku = []
        for pcode in ("36", "37", "38", "39"):
            schools = sorted(
                sid for sid in cls.repo.school_to_program
                if cls.repo.schools[sid]["prefecture_code"] == pcode
            )
            assert len(schools) >= 2
            shikoku.extend(schools[:2])
        cls.start_specs = [
            {"competition_id": SENBATSU,
             "entry_mode": "national_invitational_main_v1",
             "entrant_school_ids": cls.senbatsu,
             "group_entrant_school_ids": {}},
            {"competition_id": SHIKOKU,
             "entry_mode": "non_kanto_regional_main_sandbox_v1",
             "entrant_school_ids": shikoku,
             "group_entrant_school_ids": {}},
        ]
        participants = set(cls.senbatsu + shikoku)
        for members in cls.group_inputs.values():
            participants.update(members)
        for sid in sorted(participants):
            archive.save_initial_roster(
                generator.generate_for_school_id(cls.repo, sid, 2026, SEED)
            )
            archive.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=SEED,
            )

    @classmethod
    def tearDownClass(cls):
        cls.tmp_base.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.save_root = Path(self.temp.name)
        self.slot = self.save_root / "spring"
        self.slot.mkdir()
        shutil.copy2(self.original_history,
                     self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.original_rosters,
                     self.slot / "career_rosters.sqlite3")
        self.service = CareerMultiPreviewCheckpointService(
            self.repo, DATA, save_root=self.save_root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )

    def _archive(self):
        return HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")

    def _checkpoint(self):
        return self.slot / "career_multi_previews" / "2027.json"

    def _start_to_senbatsu_complete(self):
        session = self.service.start(
            "spring", year=2027, competitions=self.start_specs,
            base_seed=SEED, career_seed=SEED,
        )
        for _ in range(20):
            if SENBATSU in session.completed_runs():
                break
            self.service.play_next_date(session)
        self.assertIn(SENBATSU, session.completed_runs())
        self.assertNotIn(SHIKOKU, session.completed_runs())
        self.assertLess(session.processed_dates[-1], "2027-04-25")
        return session

    def test_same_year_late_append_load_interleave_and_sealed_A_history(self):
        manual = self.slot / "manual.json"
        manual.write_bytes(b"original manual save stays unchanged")
        session = self._start_to_senbatsu_complete()
        with sqlite3.connect(self._archive().db_path) as conn:
            year_identity = conn.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0]
            previous_ledger = conn.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0]
        prior_source = len([
            x for x in self._archive().list_matches(2027, limit=500)
            if x["competition_id"] == SENBATSU
        ])
        self.assertEqual(31, prior_source)
        appended = self.service.add_hokkaido_spring(
            session, group_entrant_school_ids=self.group_inputs,
        )
        self.assertEqual(SPRING, appended["competition_id"])
        self.assertEqual([self.recommended],
                         appended["recommended_school_ids"])
        self.assertEqual(3, session.summary()["competition_count"])
        self.assertTrue(session.summary()["late_same_year_spring_checkpoint"])
        self.assertEqual(
            "hokkaido_spring_same_year_senbatsu_v1",
            json.loads(self._checkpoint().read_text())["late_spring"]["entry_mode"],
        )
        with sqlite3.connect(self._archive().db_path) as conn:
            self.assertEqual(year_identity, conn.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0])
        # Restart with both the original March outcome and late spring attached.
        restored = self.service.load("spring", year=2027)
        self.assertEqual(
            session.previews[SPRING].scheduled.public_snapshot(),
            restored.previews[SPRING].scheduled.public_snapshot(),
        )
        self.assertEqual(
            session.processed_dates, restored.processed_dates,
        )
        self.assertEqual("2027-04-25",
                         self.service.play_next_date(restored)["date"])
        restored = self.service.load("spring", year=2027)
        for _ in range(40):
            if len(restored.completed_runs()) == 3:
                break
            self.service.play_next_date(restored)
        completed = restored.completed_runs()
        self.assertEqual([SENBATSU, SPRING, SHIKOKU],
                         sorted(completed))
        self.assertIn(self.recommended,
                      completed[SPRING].main_entrant_school_ids)
        self.assertEqual(1, completed[SPRING].main_entrant_school_ids.count(
            self.recommended))
        self.assertEqual(16, len(completed[SPRING].main_entrant_school_ids))
        self.assertEqual(15, completed[SPRING].outcome.match_count)
        self.assertEqual(31, completed[SENBATSU].outcome.match_count)
        self.assertEqual(7, completed[SHIKOKU].outcome.match_count)

        again = self.service.load("spring", year=2027)
        self.assertEqual(
            {cid: r.outcome.champion_school_id for cid, r in completed.items()},
            {cid: r.outcome.champion_school_id
             for cid, r in again.completed_runs().items()},
        )
        records = self._archive().list_matches(2027, limit=500)
        spring = [r for r in records if r["competition_id"] == SPRING]
        self.assertGreater(len(spring), 15)
        self.assertEqual(15, len([r for r in spring if r["stage_code"] == "MAIN"]))
        self.assertTrue(all(
            x["score_source"] == "ability_model_v1"
            and x["date_source"] == "game_projection_v1"
            and x["inning_scores"] and x["batter_stats"] and x["pitcher_stats"]
            for x in spring
        ))
        with sqlite3.connect(self._archive().db_path) as conn:
            self.assertEqual(year_identity, conn.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0])
            self.assertEqual(previous_ledger, conn.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0])
        self.assertEqual(b"original manual save stays unchanged",
                         manual.read_bytes())

        self._archive().seal_year(2027, expected_match_count=len(records))

    def test_duplicate_and_unfinished_senbatsu_cannot_append(self):
        session = self.service.start(
            "spring", year=2027, competitions=self.start_specs,
            base_seed=SEED, career_seed=SEED,
        )
        with self.assertRaisesRegex(CareerPreviewSaveError, "Senbatsu"):
            self.service.add_hokkaido_spring(
                session, group_entrant_school_ids=self.group_inputs,
            )
        self.assertNotIn("late_spring",
                         json.loads(self._checkpoint().read_text()))
        session = self.service.load("spring", year=2027)
        for _ in range(20):
            if SENBATSU in session.completed_runs():
                break
            self.service.play_next_date(session)
        self.service.add_hokkaido_spring(
            session, group_entrant_school_ids=self.group_inputs,
        )
        with self.assertRaisesRegex(CareerPreviewSaveError, "already"):
            self.service.add_hokkaido_spring(
                session, group_entrant_school_ids=self.group_inputs,
            )

    def test_wrong_manifest_and_recomputed_tampered_checksum_rejected(self):
        session = self._start_to_senbatsu_complete()
        wrong = {k: list(v) for k, v in self.group_inputs.items()}
        k = next(iter(wrong))
        wrong[k][0] = self.start_specs[1]["entrant_school_ids"][0]
        with self.assertRaises(CareerPreviewSaveError):
            self.service.add_hokkaido_spring(
                session, group_entrant_school_ids=wrong,
            )
        self.assertNotIn("late_spring",
                         json.loads(self._checkpoint().read_text()))
        self.service.add_hokkaido_spring(
            session, group_entrant_school_ids=self.group_inputs,
        )
        path = self._checkpoint()
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["late_spring"]["recommended_school_ids"] = []
        saved["payload_checksum"] = _checksum(saved)
        path.write_text(json.dumps(saved), encoding="utf-8")
        with self.assertRaisesRegex(
            CareerPreviewSaveError, "qualification|bracket",
        ):
            self.service.load("spring", year=2027)

    def test_earlier_preview_checksum_never_rewritten_and_stale_session_fails(self):
        a = self._start_to_senbatsu_complete()
        b = self.service.load("spring", year=2027)
        self.service.add_hokkaido_spring(
            a, group_entrant_school_ids=self.group_inputs,
        )
        with self.assertRaisesRegex(
            CareerPreviewSaveError, "checkpoint",
        ):
            self.service.add_hokkaido_spring(
                b, group_entrant_school_ids=self.group_inputs,
            )
        self.assertEqual(3, len(self.service.load("spring", year=2027).previews))


if __name__ == "__main__":
    unittest.main()
