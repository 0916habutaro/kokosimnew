"""Stage43G-65: save -> sealed year -> saved school -> match / player.

Fixtures are independent fictional legacy 2026 and v2 year10000 records.
Extra school roster snapshots are not synthetic tournament entrants.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import sys
import tkinter as tk
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_history_gui_bridge import (
    CareerHistoryGuiBridgeConflict,
)
from phase2_engine.career_history_tk_pilot import CareerHistoryTkPilot
from phase2_engine.career_history_view_projection import project_history_screen
import test_stage43g64_history_slots_school_names as stage64

DISPLAY = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G65SaveSchoolNavigationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage64.Stage43G64SlotAndYearLabelsTests(
            "test_two_saves_have_different_years_and_cannot_leak_old_routes",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.session = self.fixture.session
        self.a = self.fixture.fixture.a
        self.repo = self.fixture.fixture.repo

    def _digest(self):
        return {
            str(p.relative_to(self.fixture.root)):
                sha256(p.read_bytes()).hexdigest()
            for p in self.fixture.root.rglob("*.sqlite3*") if p.is_file()
        }

    def _gui(self):
        if not DISPLAY:
            self.skipTest("real Tk/Xvfb display required")
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        gui = CareerHistoryTkPilot(
            root, self.session.bridge, school_id="",
            slot_session=self.session,
        )
        root.update_idletasks()
        return gui

    @staticmethod
    def _select(gui, check):
        wid = next(w for w, data in gui.rows_by_widget_id.items() if check(data))
        gui.tree.selection_set(wid)
        gui.open_button.invoke()

    def test_save_year_school_match_player_back_readonly(self):
        before = self._digest()
        bridge = self.session.bridge
        choices = bridge.open_year(2026)
        self.assertEqual("history_school_catalog", choices["screen"])
        self.assertTrue(choices["source_verified"])
        self.assertEqual(2, len(choices["data"]["schools"]))
        self.assertTrue(choices["data"]["only_saved_year_rosters_indexed"])
        self.assertFalse(choices["data"]["full_nation_school_coverage_proven"])
        self.assertTrue(all(x["school_name_digest_verified"]
                            for x in choices["data"]["schools"]))
        visible = project_history_screen(choices)
        self.assertEqual("history_school_catalog", visible["screen"])
        self.assertFalse(visible["show_saved_candidate_warning"])
        self.assertEqual(2, len(visible["rows"]))
        self.assertIn(self.a, [x["school_id"] for x in visible["rows"]])
        school = bridge.open_school(2026, self.a)
        self.assertEqual("history_school", school["screen"])
        self.assertEqual(1, school["data"]["match_total"])
        match = bridge.open_link(
            school["data"]["match_detail_targets"][0]["target"],
        )
        self.assertEqual("history_match", match["screen"])
        bridge.back()
        player = bridge.open_link(
            school["data"]["player_targets"][0]["target"],
        )
        self.assertEqual("history_player", player["screen"])
        self.assertEqual("history_school", bridge.back()["screen"])
        self.assertEqual("history_school_catalog", bridge.back()["screen"])
        self.assertEqual("history_year_catalog", bridge.back()["screen"])
        self.assertEqual(before, self._digest())

    def test_unknown_year_school_and_old_link_rejected_atomically(self):
        bridge = self.session.bridge
        bridge.open_year(2026)
        before = (dict(bridge.route), list(bridge.history), bridge.page)
        for year, school in (
            (10000, self.a), (2026, "SCH_UNKNOWN"), (True, self.a),
        ):
            with self.assertRaises(ValueError):
                bridge.open_school(year, school)
            self.assertEqual(before, (
                bridge.route, bridge.history, bridge.page,
            ))
        with self.assertRaises(ValueError):
            bridge.older_years()
        with self.assertRaises(ValueError):
            bridge.advance_year(2027)

    def test_roster_sha_tamper_blocks_candidate_list_without_state_change(self):
        bridge = self.session.bridge
        path = self.fixture.a_slot / "career_rosters.sqlite3"
        with sqlite3.connect(path) as conn:
            conn.execute(
                "UPDATE career_school_rosters SET content_sha256='BAD' "
                "WHERE year=2026 AND school_id=?", (self.a,),
            )
        before = self._digest()
        old = (dict(bridge.route), list(bridge.history), bridge.page)
        with self.assertRaises(ValueError):
            bridge.open_year(2026)
        self.assertEqual(old, (bridge.route, bridge.history, bridge.page))
        self.assertEqual(before, self._digest())

    def test_v2_match_sha_tamper_blocks_school_chooser(self):
        bridge = self.session.bridge
        with sqlite3.connect(self.fixture.a_slot / "fictional_option_a_v2.sqlite3") as conn:
            conn.execute(
                "UPDATE v2_option_a_matches SET record_sha256='BAD' "
                "WHERE year=10000",
            )
        before = self._digest()
        prior = (dict(bridge.route), list(bridge.history), bridge.page)
        with self.assertRaises(ValueError):
            bridge.open_year(10000)
        self.assertEqual(prior, (bridge.route, bridge.history, bridge.page))
        self.assertEqual(before, self._digest())

    def test_35_extra_schools_require_bounded_school_cursor(self):
        school_ids = [
            sid for sid in sorted(self.repo.school_to_program)
            if sid not in (self.fixture.fixture.a, self.fixture.fixture.b)
        ][:35]
        self.assertEqual(35, len(school_ids))
        generator = PlayerRosterGenerator()
        with CareerRosterArchive(
            self.fixture.a_slot / "career_rosters.sqlite3",
        )._connect() as conn:
            for school_id in school_ids:
                CareerRosterArchive._insert(
                    conn, generator.generate_for_school_id(
                        self.repo, school_id, 2026, 2026101101,
                    ),
                )
        before = self._digest()
        bridge = self.session.bridge
        first = bridge.open_year(2026)
        self.assertEqual(30, len(first["data"]["schools"]))
        self.assertTrue(first["data"]["has_older"])
        older = bridge.older_schools()
        self.assertEqual(7, len(older["data"]["schools"]))
        self.assertFalse(older["data"]["has_older"])
        all_ids = ([x["school_id"] for x in first["data"]["schools"]]
                   + [x["school_id"] for x in older["data"]["schools"]])
        self.assertEqual(37, len(set(all_ids)))
        self.assertEqual(sorted(all_ids), all_ids)
        old_id = first["data"]["schools"][0]["school_id"]
        with self.assertRaises(CareerHistoryGuiBridgeConflict):
            bridge.open_school(2026, old_id)
        self.assertEqual(older, bridge.older_schools())
        self.assertEqual(before, self._digest())

    def test_tk_choose_save_year_school_and_open_match(self):
        gui = self._gui()
        before = self._digest()
        self._select(gui, lambda x: x["kind"] == "year" and x["year"] == 2026)
        self.assertEqual("history_school_catalog", gui.view["screen"])
        self.assertIn("学校", gui.view["title"])
        self._select(gui, lambda x: x["kind"] == "school"
                     and x["school_id"] == self.a)
        self.assertEqual("history_school", gui.view["screen"])
        self._select(gui, lambda x: x["title"].startswith("試合 "))
        self.assertEqual("history_match", gui.view["screen"])
        gui.back_button.invoke()
        gui.back_button.invoke()
        self.assertEqual("history_school_catalog", gui.view["screen"])
        gui.back_button.invoke()
        gui.slot_var.set("save_B")
        gui._change_slot()
        self.assertEqual("save_B", gui.slot_var.get())
        self.assertEqual("history_year_catalog", gui.view["screen"])
        self._select(gui, lambda x: x["kind"] == "year" and x["year"] == 2026)
        self.assertEqual("history_school_catalog", gui.view["screen"])
        self.assertEqual(before, self._digest())

    def test_tk_manual_school_id_remains_compatible(self):
        gui = self._gui()
        before = self._digest()
        gui.school_var.set(self.a)
        self._select(gui, lambda x: x["kind"] == "year" and x["year"] == 2026)
        self.assertEqual("history_school", gui.view["screen"])
        gui.back_button.invoke()
        gui.school_var.set("")
        chosen = next(w for w, x in gui.rows_by_widget_id.items()
                      if x["kind"] == "year" and x["year"] == 10000)
        gui.tree.selection_set(chosen)
        gui.school_list_button.invoke()
        self.assertEqual("history_school_catalog", gui.view["screen"])
        self.assertEqual(10000, gui.bridge.page["data"]["year"])
        self.assertEqual(before, self._digest())


if __name__ == "__main__":
    unittest.main()
