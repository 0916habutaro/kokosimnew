"""Stage43G-58: two adjacent saved fictional Tokai seasons and identities.

Uses real archive/roster storage for a synthetic 2027-2028 rollover, not an
actual 2028 national calendar or a claim of full multi-year game execution.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tkinter as tk
import os
import sys
import unittest

from phase2_engine.career_history_scale_audit import synthetic_ability_record
from phase2_engine.historical_match_archive import (
    compact_payload,
    expand_payload,
)
from phase2_engine.career_player_records import BATTER, PITCHER
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_tokai_season_browse_model import (
    GIFU, TOKAI, TokaiSeasonBrowseConflict,
)
from phase2_engine.career_tokai_season_gui_pilot import (
    CareerTokaiSeasonGuiPilot, TokaiSeasonScreenController,
)
from test_stage43g54_tokai_season_history_browse import (
    Stage43G54TokaiHistoryReadOnly,
)
import test_stage43g14_player_records as stage14


GUI_AVAILABLE = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G58TokaiMultiYearTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Stage43G54TokaiHistoryReadOnly(
            "test_competition_school_match_and_player_navigation_by_ids",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.model = self.fixture.model
        self.archive = self.fixture.archive
        self.a, self.b = self.fixture.a, self.fixture.b
        self.rosters = CareerRosterArchive(
            self.fixture.slot / "career_rosters.sqlite3"
        )
        repo = self.model.source.repo
        previous = self.rosters.roster(2027, self.a)
        self.graduated = next(
            player.player_id for player in previous.players
            if player.academic_year == 3
        )
        self.archive.seal_year(2027, expected_match_count=5)
        self.archive.register_next_year(
            year=2028, rng_seed=stage14.SEED,
            resolver_contract="synthetic_test_v1",
            plan_fingerprint="stage43g58-year-2028",
        )
        for school in (self.a, self.b):
            self.rosters.advance_and_save(
                repo.team(school), next_year=2028,
                career_seed=stage14.SEED,
            )
        self.assertFalse(any(
            p.player_id == self.graduated
            for p in self.rosters.roster(2028, self.a).players
        ))
        future = []
        for day, cid, match_id in (
            (3, GIFU, "GIFU-2028"),
            # Reuse the same composite competition/match ID across years:
            # saved-year must remain part of the immutable identity.
            (8, TOKAI, "REGIONAL-01"),
        ):
            row = synthetic_ability_record(
                2028, cid, match_id, self.a, self.b, day,
            )
            for school in (self.a, self.b):
                players = self.rosters.roster(2028, school).players
                bats = [
                    p.player_id for p in players
                    if p.primary_position != "P"
                ][:9]
                self.assertEqual(9, len(bats))
                for item, pid in zip(
                    (x for x in row["ability_detail"]["batter_stats"]
                     if x["school_id"] == school), bats,
                ):
                    item["player_id"] = pid
                    for key in BATTER:
                        item.setdefault(key, 0)
                    item["plate_appearances"] = 4
                pitcher = next(
                    p.player_id for p in players
                    if p.primary_position == "P"
                )
                for item in row["ability_detail"]["pitcher_stats"]:
                    if item["school_id"] == school:
                        item["player_id"] = pitcher
                        for key in PITCHER:
                            item.setdefault(key, 0)
                        item["outs_recorded"] = 27
            future.append(row)
        self.archive.sync(
            year=2028, rng_seed=stage14.SEED,
            resolver_contract="synthetic_test_v1",
            plan_fingerprint="stage43g58-year-2028",
            completed=future,
        )

    def _snap(self):
        return {
            f.name: hashlib.sha256(f.read_bytes()).hexdigest()
            for f in self.fixture.slot.glob("*.sqlite3*")
            if f.is_file()
        }

    def test_saved_year_picker_is_bounded_and_does_not_mix_sources(self):
        before = self._snap()
        self.assertEqual([2028, 2027], self.model.available_years())
        self.assertEqual([2028], self.model.available_years(limit=1))
        self.assertEqual([2027], self.model.available_years(limit=1, offset=1))
        self.assertEqual([], self.model.available_years(limit=1, offset=2))
        for limit, offset in ((0, 0), (101, 0), (30, -1), (True, 0)):
            with self.assertRaises(TokaiSeasonBrowseConflict):
                self.model.available_years(limit=limit, offset=offset)
        self.assertEqual(4, self.model.overview(2027)["archived_match_count"])
        self.assertEqual(2, self.model.overview(2028)["archived_match_count"])
        self.assertEqual(before, self._snap())

    def test_year_switch_clears_old_routes_and_keeps_exact_year_matches(self):
        before = self._snap()
        ctrl = TokaiSeasonScreenController(self.model, year=2027)
        old_list = ctrl.open({
            "screen": "competition", "year": 2027,
            "competition_id": TOKAI,
        })
        old_match = old_list["matches"]["rows"][0]["match_target"]
        self.assertEqual("2027-04-07", ctrl.open(old_match)["game"]["match_date"])
        self.assertTrue(ctrl.history)
        page = ctrl.switch_year(2028)
        self.assertEqual(2028, page["year"])
        self.assertEqual([], ctrl.history)
        self.assertEqual(0, ctrl.offset)
        self.assertEqual("tokai_season", ctrl.back()["screen"])
        with self.assertRaises(TokaiSeasonBrowseConflict):
            ctrl.open(old_match)
        new_list = ctrl.open({
            "screen": "competition", "year": 2028,
            "competition_id": TOKAI,
        })
        match = ctrl.open(new_list["matches"]["rows"][0]["match_target"])
        self.assertEqual("2028-04-08", match["game"]["match_date"])
        self.assertEqual("REGIONAL-01", match["match_id"])
        self.assertEqual(2028, ctrl.back()["year"])
        self.assertEqual(before, self._snap())

    def test_invalid_year_switch_keeps_page_offset_and_history_intact(self):
        ctrl = TokaiSeasonScreenController(self.model, year=2028)
        ctrl.open({"screen": "competition", "year": 2028,
                   "competition_id": GIFU})
        old = (dict(ctrl.target), ctrl.offset, list(ctrl.history), ctrl.page)
        for year in (2029, 2026, 2027.0, True):
            with self.subTest(year=year):
                with self.assertRaises((ValueError, TypeError)):
                    ctrl.switch_year(year)
                self.assertEqual(old, (
                    ctrl.target, ctrl.offset, ctrl.history, ctrl.page,
                ))

    def test_school_rosters_and_players_are_attributed_to_selected_year(self):
        before = self._snap()
        old = self.model.school(2027, self.a)
        new = self.model.school(2028, self.a)
        self.assertEqual(4, old["matches"]["total"])
        self.assertEqual(2, new["matches"]["total"])
        old_ids = {t["player_id"] for t in old["player_targets"]}
        new_ids = {t["player_id"] for t in new["player_targets"]}
        self.assertIn(self.graduated, old_ids)
        self.assertNotIn(self.graduated, new_ids)
        with self.assertRaises(TokaiSeasonBrowseConflict):
            self.model.player(2028, self.graduated)
        current = self.model.player(
            2028, next(iter(sorted(new_ids - old_ids))),
        )
        self.assertEqual(2028, current["year"])
        self.assertTrue(current["selected_year_roster_confirmed"])
        self.assertEqual(self.a, current["school_id"])
        with self.assertRaises(ValueError):
            self.model.player(2027, current["player_id"])
        self.assertEqual(before, self._snap())

    def test_cross_school_forged_stat_identity_never_creates_player_link(self):
        # This case intentionally rewrites a disposable 2028 fixture AND its
        # per-record digest: the display must still reject the cross-school
        # identity claim even when the match payload SHA matches.
        b_players = self.rosters.roster(2028, self.b).players
        path = self.archive.db_path
        with sqlite3.connect(path) as conn:
            raw, = conn.execute(
                "SELECT payload_json FROM historical_matches "
                "WHERE year=2028 AND competition_id=? AND match_id=?",
                (TOKAI, "REGIONAL-01"),
            ).fetchone()
            game = expand_payload(json.loads(raw))
            used = {
                x["player_id"] for kind in ("batter_stats", "pitcher_stats")
                for x in (game.get(kind) or [])
            }
            foreign_player = next(
                p.player_id for p in b_players if p.player_id not in used
            )
            forged = next(
                x for x in game["batter_stats"] if x["school_id"] == self.a
            )
            forged["player_id"] = foreign_player
            changed = json.dumps(
                compact_payload(game), ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
            conn.execute(
                "UPDATE historical_matches SET payload_json=?,record_sha256=? "
                "WHERE year=2028 AND competition_id=? AND match_id=?",
                (changed, hashlib.sha256(changed.encode()).hexdigest(),
                 TOKAI, "REGIONAL-01"),
            )
        before_read = self._snap()
        page = self.model.match(2028, TOKAI, "REGIONAL-01")
        self.assertNotIn(
            foreign_player,
            {target["player_id"] for target in page["player_targets"]},
        )
        self.assertEqual(before_read, self._snap())

    @unittest.skipUnless(GUI_AVAILABLE, "Tk requires Xvfb or a desktop display")
    def test_real_tk_year_combobox_switch_and_read_only(self):
        before = self._snap()
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        gui = CareerTokaiSeasonGuiPilot(root, self.model, year=2027)
        self.assertEqual(["2028", "2027"],
                         [str(y) for y in gui.available_years])
        gui.year_var.set("2028")
        gui._change_year()
        self.assertEqual(2028, gui.controller.page["year"])
        self.assertEqual("tokai_season", gui.controller.page["screen"])
        self.assertIn("2028", gui.status_var.get())
        self.assertEqual(before, self._snap())


if __name__ == "__main__":
    unittest.main()
