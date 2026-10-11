"""Stage43G-52: saved 2027 national + Aichi/Mie concurrent date replay.

Reuse Stage43G-51's authenticated fictional roster/manifests as inputs,
but run independent Stage43G-52 tests without importing its TestCase class
into unittest discovery's module namespace.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import unittest

import test_stage43g51_tokai_concurrent_preflight as stage51

from phase2_engine.career_preview_checkpoint import CareerPreviewSaveError
from phase2_engine.career_tokai_concurrent_preflight import TokaiPreflightNotReady
from phase2_engine.future_tokai_concurrent_bridge import (
    TOKAI_AICHI, TOKAI_MIE,
)

BASE = stage51.Stage43G51TokaiPreseasonFreeze
NATIONAL = stage51.NATIONAL


class Stage43G52ConcurrentTokaiSavedCareer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        BASE.setUpClass()
        for field in (
            "repo", "base", "history", "rosters", "national",
            "direct", "groups", "quota_sum", "tochigi",
            "gunma", "specs",
        ):
            setattr(cls, field, getattr(BASE, field))

    @classmethod
    def tearDownClass(cls):
        BASE.tearDownClass()

    def setUp(self):
        BASE.setUp(self)

    def _start(self):
        return BASE._start(self)

    def _activate(self):
        session = self._start()
        frozen = self.service.freeze(
            "tokai", year=2027, group_entrant_school_ids=self.groups,
        )
        attached = self.multi.add_tokai_concurrent(session)
        self.assertEqual([TOKAI_AICHI, TOKAI_MIE], attached["competition_ids"])
        self.assertEqual(2, len(frozen["qualifier_groups_by_competition"]))
        return session

    def test_concurrent_senbatsu_aichi_mie_save_then_replay(self):
        original = self.slot / "manual.json"
        original.write_bytes(b"personal save remains unchanged")
        session = self._activate()
        self.assertEqual(4, len(session.previews))
        self.assertEqual("", session.tokai_concurrent["activation_after_date"])
        self.assertEqual("2027-03-19", self.multi._next_date(session))
        with sqlite3.connect(self.archive.db_path) as db:
            ledger = db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0]
            annual = db.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0]
        first = self.multi.play_next_date(session)
        self.assertEqual("2027-03-19", first["date"])
        self.assertEqual([NATIONAL], list(first["competition_match_counts"]))
        simultaneous = None
        for _ in range(50):
            if len(session.completed_runs()) == 4:
                break
            step = self.multi.play_next_date(session)
            if (NATIONAL in step["competition_match_counts"]
                    and (TOKAI_AICHI in step["competition_match_counts"]
                         or TOKAI_MIE in step["competition_match_counts"])):
                simultaneous = step
            if step["date"] == "2027-03-20":
                self.assertIn(TOKAI_AICHI, step["competition_match_counts"])
                self.assertIn(TOKAI_MIE, step["competition_match_counts"])
                self.assertIn(NATIONAL, step["competition_match_counts"])
                reloaded = self.multi.load("tokai", year=2027)
                for cid in session.previews:
                    self.assertEqual(
                        session.previews[cid].scheduled.public_snapshot(),
                        reloaded.previews[cid].scheduled.public_snapshot(),
                    )
                self.assertEqual(session.processed_dates, reloaded.processed_dates)
        self.assertIsNotNone(simultaneous)
        self.assertEqual(4, len(session.completed_runs()))
        final = self.multi.load("tokai", year=2027)
        for cid, expected_slots in ((TOKAI_AICHI, 48), (TOKAI_MIE, 25)):
            run = final.completed_runs()[cid]
            self.assertEqual(expected_slots+1, len(run.main_entrant_school_ids))
            self.assertIn(self.direct[cid][0], run.main_entrant_school_ids)
            self.assertEqual(expected_slots, run.outcome.match_count)
            self.assertEqual(1, run.main_entrant_school_ids.count(self.direct[cid][0]))
            groups = final.previews[cid].scheduled.runtime.qualifier_entrant_school_ids
            self.assertNotIn(self.direct[cid][0], groups)
        for day in final.processed_dates:
            self.assertTrue(day.startswith("2027-"))
        self.assertEqual(
            sorted(set(final.processed_dates)), final.processed_dates,
        )
        proof = self.service.audit("tokai", year=2027)
        self.assertEqual(
            "source_games_confirm_frozen_preseason_selection",
            proof["status"],
        )
        self.assertFalse(proof["regional_runtime_ready"])
        archive = self.archive.list_matches(2027, limit=500)
        self.assertEqual(31, len([r for r in archive
                                 if r["competition_id"] == NATIONAL]))
        for cid in (TOKAI_AICHI, TOKAI_MIE):
            matches = [r for r in archive if r["competition_id"] == cid]
            self.assertTrue(matches)
            self.assertTrue(all(
                row["score_source"] == "ability_model_v1"
                and row["date_source"] == "game_projection_v1"
                and row["inning_scores"] and row["batter_stats"]
                and row["pitcher_stats"]
                for row in matches
            ))
        with sqlite3.connect(self.archive.db_path) as db:
            self.assertEqual(ledger, db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0])
            self.assertEqual(annual, db.execute(
                "SELECT metadata_json FROM career_years WHERE year=2027"
            ).fetchone()[0])
        self.assertEqual(
            b"personal save remains unchanged", original.read_bytes(),
        )

    def test_cannot_attach_after_played_date(self):
        session = self._start()
        self.service.freeze(
            "tokai", year=2027, group_entrant_school_ids=self.groups,
        )
        self.multi.play_next_date(session)
        with self.assertRaisesRegex(
            CareerPreviewSaveError, "before the first game",
        ):
            self.multi.add_tokai_concurrent(session)

    def test_frozen_manifest_modified_or_absent_fails_closed(self):
        session = self._activate()
        self.multi.play_next_date(session)
        path = self.service._path("tokai", 2027)
        frozen = json.loads(path.read_text(encoding="utf-8"))
        frozen["qualifier_groups_by_competition"][TOKAI_AICHI] = {}
        path.write_text(json.dumps(frozen), encoding="utf-8")
        with self.assertRaises((
            TokaiPreflightNotReady, CareerPreviewSaveError, ValueError,
        )):
            self.multi.load("tokai", year=2027)


if __name__ == "__main__":
    unittest.main()
