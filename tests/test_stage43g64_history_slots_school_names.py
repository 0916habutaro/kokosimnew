"""Stage43G-64: two independently selected fictional save snapshots.

Test fixtures are disconnected 2026 legacy / 10000 v2 demonstration data.
Saving school names or corrupting identity happens only in disposable DBs.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import tkinter as tk
import unittest

from phase2_engine.career_history_slot_session import (
    CareerHistorySlotSession, CareerHistorySlotConflict,
)
from phase2_engine.career_saved_year_display_labels import (
    CareerSavedYearDisplayLabels,
)
from phase2_engine.career_history_view_projection import project_history_screen
from phase2_engine.career_history_tk_pilot import CareerHistoryTkPilot
import test_stage43g31_cross_era_browse_model as stage31

DISPLAY = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G64SlotAndYearLabelsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage31.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setup_both()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a_slot = self.root / "save_A"
        self.b_slot = self.root / "save_B"
        self.a_slot.mkdir()
        self.b_slot.mkdir()
        # Save A holds both legacy and v2. B holds *only* 2026 legacy.
        files_a = [
            "historical_matches.sqlite3", "fictional_option_a_v2.sqlite3",
            "sandbox_calendar_v2.sqlite3", "career_rosters.sqlite3",
            "fictional_v2_player_stat_cache.sqlite3",
        ]
        for file in files_a:
            shutil.copy2(self.fixture.root / file, self.a_slot / file)
        for file in ("historical_matches.sqlite3", "career_rosters.sqlite3"):
            shutil.copy2(self.fixture.root / file, self.b_slot / file)
        self.session = CareerHistorySlotSession(self.root, "save_A")

    def _hashes(self):
        return {
            str(path.relative_to(self.root)):
                sha256(path.read_bytes()).hexdigest()
            for path in self.root.rglob("*.sqlite3*") if path.is_file()
        }

    def _gui(self):
        if not DISPLAY:
            self.skipTest("requires Tk display / Xvfb")
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        gui = CareerHistoryTkPilot(
            root, self.session.bridge,
            school_id=self.fixture.a, slot_session=self.session,
        )
        root.update_idletasks()
        return gui

    def test_two_saves_have_different_years_and_cannot_leak_old_routes(self):
        before = self._hashes()
        self.assertEqual(["save_A", "save_B"], self.session.available_slots())
        first = self.session.bridge
        self.assertEqual([10000, 2026], [
            row["year"] for row in first.page["data"]["years"]
        ])
        first.open_school(10000, self.fixture.a)
        first_route = dict(first.route)
        current = self.session.select("save_B")
        self.assertIsNot(current, first)
        self.assertEqual("save_B", self.session.slot_id)
        self.assertEqual([], current.history)
        self.assertEqual("history_year_catalog", current.page["screen"])
        self.assertEqual([2026], [
            row["year"] for row in current.page["data"]["years"]
        ])
        self.assertEqual(first_route, first.route)
        with self.assertRaises(ValueError):
            current.open_school(10000, self.fixture.a)
        school = current.open_school(2026, self.fixture.a)
        self.assertEqual(1, school["data"]["match_total"])
        self.assertEqual(before, self._hashes())

    def test_bad_slot_name_does_not_change_active_session(self):
        before = self._hashes()
        active = self.session.bridge
        for name in ("", "..", "../save_B", "save_A/../save_B",
                     "/tmp/save_A", "missing", " save_B", "."):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.session.select(name)
                self.assertIs(active, self.session.bridge)
                self.assertEqual("save_A", self.session.slot_id)
        self.assertEqual(before, self._hashes())

    def test_symlinks_and_unrelated_directories_are_not_slots(self):
        (self.root / "notes").mkdir()
        (self.root / "notes" / "readme.txt").write_text(
            "unrelated", encoding="utf-8",
        )
        try:
            (self.root / "escape_link").symlink_to(
                self.a_slot, target_is_directory=True,
            )
        except (OSError, NotImplementedError):
            pass
        self.assertEqual(["save_A", "save_B"], self.session.available_slots())

    def test_saved_year_school_and_player_names_override_current_labels(self):
        before = self._hashes()
        labels = CareerSavedYearDisplayLabels(self.session.bridge)
        school = labels.school(2026, self.fixture.a)
        expected = self.fixture.rosters.roster(
            2026, self.fixture.a,
        ).school_name
        self.assertEqual(expected, school["name"])
        self.assertEqual("exact_saved_school_year_roster", school["source"])
        self.assertTrue(school["historical_name_proven"])
        player = self.fixture.rosters.roster(
            2026, self.fixture.a,
        ).players[0]
        self.assertIn(player.display_name, labels.player(
            2026, self.fixture.a, player.player_id,
        )["label"])
        self.assertFalse(labels.player(
            2026, self.fixture.a, "NON_EXISTENT_ID",
        )["exact_year_roster_membership_verified"])
        self.assertFalse(labels.school(
            2025, self.fixture.a,
        )["historical_name_proven"])
        page = project_history_screen(
            self.session.bridge.open_school(2026, self.fixture.a),
            labels=labels,
        )
        self.assertIn(expected, page["title"])
        self.assertTrue(page["saved_year_display"][
            "historical_school_name_proven"
        ])
        self.assertTrue(any(
            player.display_name in row["title"]
            for row in page["rows"]
        ))
        self.assertEqual(before, self._hashes())

    def test_archived_school_rename_is_bound_to_exact_saved_year(self):
        path = self.b_slot / "career_rosters.sqlite3"
        with sqlite3.connect(path) as db:
            raw, = db.execute(
                "SELECT payload_json FROM career_school_rosters "
                "WHERE year=? AND school_id=?",
                (2026, self.fixture.a),
            ).fetchone()
            document = json.loads(raw)
            document["school_name"] = "旧校名・架空テスト"
            encoded = json.dumps(
                document, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
            db.execute(
                "UPDATE career_school_rosters "
                "SET payload_json=?, content_sha256=? "
                "WHERE year=? AND school_id=?",
                (encoded, sha256(encoded.encode("utf-8")).hexdigest(),
                 2026, self.fixture.a),
            )
        before = self._hashes()
        other = self.session.select("save_B")
        label = CareerSavedYearDisplayLabels(other).school(2026, self.fixture.a)
        self.assertIn("旧校名・架空テスト", label["label"])
        self.assertTrue(label["historical_name_proven"])
        self.session.select("save_A")
        first = CareerSavedYearDisplayLabels(
            self.session.bridge,
        ).school(2026, self.fixture.a)
        self.assertNotIn("旧校名・架空テスト", first["label"])
        self.assertEqual(before, self._hashes())

    def test_tk_switches_save_and_rejects_stale_year_and_bad_slot(self):
        gui = self._gui()
        before = self._hashes()
        self.assertEqual(["save_A", "save_B"], list(gui.slot_box["values"]))
        gui.slot_var.set("save_B")
        gui._change_slot()
        self.assertEqual("save_B", self.session.slot_id)
        self.assertEqual("history_year_catalog", gui.view["screen"])
        self.assertEqual([2026], [r["year"] for r in gui.view["rows"]])
        self.assertEqual([], gui.bridge.history)
        prior = gui.view
        gui.slot_var.set("../save_A")
        gui._change_slot()
        self.assertIs(gui.view, prior)
        self.assertIsNotNone(gui.last_error)
        self.assertEqual("save_B", gui.slot_var.get())
        gui.slot_var.set("save_A")
        gui._change_slot()
        self.assertEqual([10000, 2026], [
            r["year"] for r in gui.view["rows"]
        ])
        self.assertEqual(before, self._hashes())


if __name__ == "__main__":
    unittest.main()
