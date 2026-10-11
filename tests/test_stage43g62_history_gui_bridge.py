"""Stage43G-62: headless official-GUI handoff contract remains read-only.

Tests use isolated synthetic year2026 legacy and year10000 v2 snapshots,
NOT a continuous 7,974-year gameplay save or official game UI.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import unittest

from phase2_engine.career_history_gui_bridge import (
    CareerHistoryGuiBridge, CareerHistoryGuiBridgeConflict,
)
from phase2_engine.career_cross_era_year_catalog import LEGACY, FUTURE
import test_stage43g31_cross_era_browse_model as stage31


class Stage43G62HistoryGuiBridgeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage31.Stage43G31CrossEraBrowseTests(
            "test_school_years_provenance_and_score_only_per_year"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setup_both()
        self.bridge = CareerHistoryGuiBridge(self.fixture.root)

    def _sha(self):
        return {
            p.name: sha256(p.read_bytes()).hexdigest()
            for p in Path(self.fixture.root).glob("*.sqlite3*")
            if p.is_file()
        }

    def test_catalog_school_match_player_back_routes_and_no_writes(self):
        before = self._sha()
        home = self.bridge.page
        self.assertEqual("history_year_catalog", home["screen"])
        self.assertFalse(home["source_verified"])
        self.assertEqual([10000, 2026], [
            x["year"] for x in home["data"]["years"]
        ])
        self.assertFalse(home["allow_advance_year"])
        self.assertTrue(home["history_read_only"])
        school = self.bridge.open_school(2026, self.fixture.a)
        self.assertEqual("history_school", school["screen"])
        self.assertEqual(LEGACY, school["data"]["source"])
        self.assertEqual("YYYY-MM-DD", school["data"]["date_kind"])
        self.assertTrue(school["source_verified"])
        self.assertEqual(1, school["data"]["match_total"])
        match_target = school["data"]["match_detail_targets"][0]["target"]
        match = self.bridge.open_link(match_target)
        self.assertEqual("history_match", match["screen"])
        self.assertEqual("recorded", (
            "recorded" if match["data"]["detail_status"] ==
            "full_option_a_saved" else "partial"
        ))
        self.assertEqual(2026, match["data"]["selected_year"])
        self.assertEqual("history_school", self.bridge.back()["screen"])
        athlete = school["data"]["player_targets"][0]["target"]
        player = self.bridge.open_link(athlete)
        self.assertEqual("history_player", player["screen"])
        self.assertEqual(
            athlete["player_id"], player["data"]["player_id"],
        )
        self.assertFalse(player["data"]["identity_continuity_proven"])
        self.assertIsNone(player["data"]["combined_career_totals"])
        self.assertEqual("history_school", self.bridge.back()["screen"])
        self.assertEqual("history_year_catalog", self.bridge.back()["screen"])
        self.assertEqual(before, self._sha())

    def test_old_year_page_and_exact_saved_year_boundary(self):
        before = self._sha()
        small = CareerHistoryGuiBridge(
            self.fixture.root, year_page_size=1,
        )
        self.assertEqual(
            [10000], [r["year"] for r in small.page["data"]["years"]],
        )
        with self.assertRaises(CareerHistoryGuiBridgeConflict):
            small.open_school(2026, self.fixture.a)
        self.assertEqual("history_year_catalog", small.page["screen"])
        older = small.older_years()
        self.assertEqual(
            [2026], [r["year"] for r in older["data"]["years"]],
        )
        self.assertFalse(older["data"]["has_older"])
        self.assertEqual(older, small.older_years())
        legacy = small.open_school(2026, self.fixture.a)
        self.assertEqual("history_school", legacy["screen"])
        self.assertEqual("history_year_catalog", small.back()["screen"])
        self.assertEqual(2026, small.page["data"]["years"][0]["year"])
        self.assertEqual(10000, small.back()["data"]["years"][0]["year"])
        latest = small.open_school(10000, self.fixture.a)
        self.assertEqual(FUTURE, latest["data"]["source"])
        self.assertEqual("G{year}:MM-DD", latest["data"]["date_kind"])
        match = small.open_link(
            latest["data"]["match_detail_targets"][0]["target"],
        )
        self.assertEqual("G10000:04-01", match["data"]["match"]["date"])
        self.assertEqual(before, self._sha())

    def test_reject_forged_links_cross_year_and_write_actions(self):
        before = self._sha()
        school = self.bridge.open_school(10000, self.fixture.a)
        state = (dict(self.bridge.route), list(self.bridge.history),
                 self.bridge.page)
        match = school["data"]["match_detail_targets"][0]["target"]
        forged = {**match, "match_id": "NOT_SAVED"}
        other_year = {**match, "selected_year": 2026, "years": [2026]}
        for value in (
            forged, other_year, {"view": "advance_year"},
            {}, {"view": "school", "school_id": self.fixture.a},
        ):
            with self.subTest(target=value):
                with self.assertRaises(ValueError):
                    self.bridge.open_link(value)
                self.assertEqual(state, (
                    self.bridge.route, self.bridge.history, self.bridge.page,
                ))
        with self.assertRaises(CareerHistoryGuiBridgeConflict):
            self.bridge.older_years()
        with self.assertRaises(CareerHistoryGuiBridgeConflict):
            self.bridge.advance_year(10001)
        self.assertEqual(before, self._sha())

    def test_checksum_corruption_rejects_navigation_without_state_change(self):
        school = self.bridge.open_school(10000, self.fixture.a)
        target = school["data"]["match_detail_targets"][0]["target"]
        with sqlite3.connect(self.fixture.v2) as conn:
            conn.execute(
                "UPDATE v2_option_a_matches SET record_sha256='WRONG' "
                "WHERE year=10000",
            )
        tampered_before = self._sha()
        state = (dict(self.bridge.route), list(self.bridge.history),
                 self.bridge.page)
        with self.assertRaises(ValueError):
            self.bridge.open_link(target)
        self.assertEqual(state, (
            self.bridge.route, self.bridge.history, self.bridge.page,
        ))
        with self.assertRaises(ValueError):
            self.bridge.refresh()
        self.assertEqual(state, (
            self.bridge.route, self.bridge.history, self.bridge.page,
        ))
        self.assertEqual(tampered_before, self._sha())

    def test_empty_slot_never_creates_new_database_or_progresses(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            slot = Path(tmp)
            bridge = CareerHistoryGuiBridge(slot)
            self.assertEqual([], bridge.page["data"]["years"])
            self.assertEqual(bridge.page, bridge.older_years())
            with self.assertRaises(ValueError):
                bridge.open_school(2026, "SCH000001")
            with self.assertRaises(ValueError):
                bridge.advance_year()
            self.assertEqual([], list(slot.iterdir()))

    def test_invalid_page_size_and_type_or_unknown_school_no_state_mutation(self):
        for limit in (0, 25, True, 1.0, "24"):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    CareerHistoryGuiBridge(
                        self.fixture.root, year_page_size=limit,
                    )
        before = (dict(self.bridge.route), list(self.bridge.history),
                  self.bridge.page)
        for year, school in ((2027, self.fixture.a), (True, self.fixture.a),
                             (2026, ""), (2026, 123)):
            with self.assertRaises(ValueError):
                self.bridge.open_school(year, school)
        with self.assertRaises(ValueError):
            self.bridge.open_school(2026, "SCH_NOT_SAVED")
        self.assertEqual(before, (
            self.bridge.route, self.bridge.history, self.bridge.page,
        ))


if __name__ == "__main__":
    unittest.main()
