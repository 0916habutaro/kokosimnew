"""Stage43G-34: exact-source Japanese names, no roster-name guesses, Tk UX."""
from __future__ import annotations

import csv
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

import test_stage43g31_cross_era_browse_model as fixtures
from phase2_engine.career_cross_era_display_labels import (
    CareerCrossEraDisplayLabels, CareerDisplayLabelConflict,
)
from phase2_engine.career_cross_era_navigation import CareerCrossEraNavigator
from phase2_engine.career_cross_era_gui_pilot import CareerCrossEraGuiPilot
from phase2_engine.career_history_scale_benchmark import file_sha256

ROOT = fixtures.ROOT
TK_AVAILABLE = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G34CrossEraLabelTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setup_both()
        self.nav = CareerCrossEraNavigator(self.fixture.root)
        self.school = self.fixture.a
        self.labels = CareerCrossEraDisplayLabels(
            ROOT / "data", self.fixture.rosters,
            self.nav.browse.attribution,
        )

    def test_known_school_name_comes_from_master_and_keeps_saved_id(self):
        saved = self.fixture.repo.schools[self.school]
        name = saved.get("display_name") or saved.get("federation_name")
        self.assertTrue(name)
        value = self.labels.school(self.school)
        self.assertIn(name, value)
        self.assertIn(self.school, value)
        self.assertNotEqual(self.school, value)

    def test_roster_year_display_name_is_exact_same_year_verified_id(self):
        saved = self.fixture.rosters.roster(2026, self.school)
        first = saved.players[0]
        mapping = self.labels.player_labels(2026, self.school)
        self.assertEqual(first.display_name, mapping[first.player_id])
        label = self.labels.player(first.player_id, mapping)
        self.assertIn(first.display_name, label)
        self.assertIn(first.player_id, label)
        future = self.labels.player_labels(10000, self.school)
        self.assertNotIn(first.player_id, future)
        self.assertIn("この年度に氏名の確認なし",
                      self.labels.player(first.player_id, future))

    def test_unknown_school_or_missing_year_shows_explicit_fallback(self):
        self.assertEqual("SCH-NOT-REGISTERED（学校名未登録）",
                         self.labels.school("SCH-NOT-REGISTERED"))
        self.assertEqual({}, self.labels.player_labels(2030, self.school))
        self.assertIn("確認なし", self.labels.player("PLY-UNKNOWN", {}))
        no_master = CareerCrossEraDisplayLabels(
            None, self.fixture.rosters, self.nav.browse.attribution,
        )
        self.assertIn("学校名未登録", no_master.school(self.school))

    def test_corrupt_permanent_identity_blocks_name_lookup(self):
        pid = self.fixture.rosters.roster(2026, self.school).players[0].player_id
        with sqlite3.connect(self.fixture.rosters.db_path) as con:
            con.execute(
                "UPDATE career_player_identities SET identity_sha256='BAD' "
                "WHERE player_id=?", (pid,),
            )
        with self.assertRaises(ValueError):
            self.labels.player_labels(2026, self.school)

    def test_name_lookup_does_not_modify_archives_or_create_cache(self):
        paths = [
            self.fixture.old, self.fixture.v2,
            self.fixture.calendar, self.fixture.rosters.db_path,
            self.fixture.cache.path,
        ]
        before = [file_sha256(p) for p in paths]
        self.labels.school(self.school)
        self.labels.player_labels(2026, self.school)
        self.labels.player_labels(10000, self.school)
        self.assertEqual(before, [file_sha256(p) for p in paths])
        self.assertFalse(
            (self.fixture.root / "derived_player_stats.sqlite3").exists()
        )

    def test_duplicate_school_master_id_rejected_not_silent_override(self):
        with tempfile.TemporaryDirectory() as temp:
            master = Path(temp) / "master"
            master.mkdir()
            with (master / "schools.csv").open(
                "w", encoding="utf-8", newline="",
            ) as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=[
                        "school_id", "display_name", "federation_name",
                    ],
                )
                writer.writeheader()
                writer.writerow({"school_id": self.school,
                                 "display_name": "第1表記"})
                writer.writerow({"school_id": self.school,
                                 "display_name": "第2表記"})
            with self.assertRaises(CareerDisplayLabelConflict):
                CareerCrossEraDisplayLabels(
                    temp, self.fixture.rosters,
                    self.nav.browse.attribution,
                )

    def test_invalid_id_and_missing_master_rejected(self):
        with self.assertRaises(ValueError):
            self.labels.school("")
        with self.assertRaises(ValueError):
            self.labels.player("", {})
        with self.assertRaises(ValueError):
            self.labels.player_labels(True, self.school)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                CareerCrossEraDisplayLabels(
                    temp, self.fixture.rosters,
                    self.nav.browse.attribution,
                )

    @unittest.skipUnless(TK_AVAILABLE, "actual Tk test needs DISPLAY or Windows")
    def test_real_tk_treeview_shows_school_and_player_names_and_ids(self):
        import tkinter as tk
        root = tk.Tk()
        self.addCleanup(root.destroy)
        gui = CareerCrossEraGuiPilot(
            root, self.nav, school_id=self.school,
            years=[2026, 10000], selected_year=2026,
            data_root=ROOT / "data",
        )
        root.update_idletasks()
        heading = gui.status_var.get()
        self.assertIn(self.labels.school(self.school), heading)
        self.assertIn("1～1 / 1件", heading)
        values = [
            gui.table.item(iid, "values")
            for iid in gui.table.get_children()
        ]
        all_text = " ".join(str(x) for row in values for x in row)
        first = self.fixture.rosters.roster(2026, self.school).players[0]
        self.assertIn(first.display_name, all_text)
        self.assertIn(first.player_id, all_text)
        self.assertIn(self.labels.school(self.fixture.b), all_text)
        player_iid = next(
            iid for iid, link in gui.links.items()
            if link.get("view") == "player"
            and link.get("player_id") == first.player_id
        )
        gui.table.selection_set(player_iid)
        gui.table.focus(player_iid)
        # Synthetic Tk key events require focus on the widget, not merely
        # Treeview's active row. This mirrors keyboard navigation by a user.
        root.update()
        gui.table.focus_set()
        root.update()
        gui.table.event_generate("<Return>")
        root.update()
        self.assertEqual("cross_era_player", gui.controller.page["screen"])
        self.assertIn(first.display_name, gui.details.get("1.0", "end"))
        gui.year_var.set("10000")
        gui._change_year()
        self.assertIn("この年度に氏名の確認なし",
                      gui.details.get("1.0", "end"))
        gui._back()
        self.assertEqual(2026, gui.controller.page["selected_year"])

    @unittest.skipUnless(TK_AVAILABLE, "actual Tk test needs DISPLAY or Windows")
    def test_legacy_gui_handoff_supplies_master_for_new_window(self):
        import tkinter as tk
        from phase2_engine.career_history_browse_model import (
            CareerHistoryBrowseModel, HistoryRoute,
        )
        from phase2_engine.career_history_gui_pilot import CareerHistoryGuiPilot
        root = tk.Tk()
        self.addCleanup(root.destroy)
        old = CareerHistoryGuiPilot(
            root, CareerHistoryBrowseModel(
                ROOT / "data", self.fixture.root,
            ),
        )
        old.navigator.open(HistoryRoute(
            "school", 2026, school_id=self.school,
        ))
        old.year_var.set("2026")
        old._open_cross_era()
        root.update_idletasks()
        children = [
            w for w in root.winfo_children()
            if isinstance(w, tk.Toplevel)
        ]
        self.assertEqual(1, len(children))
        child = children[0]._career_cross_era_gui
        self.assertIn(
            self.labels.school(self.school), child.status_var.get(),
        )
        self.assertEqual(self.school, child.controller.target["school_id"])
        self.assertEqual("school", old.navigator.current.screen)


if __name__ == "__main__":
    unittest.main()
