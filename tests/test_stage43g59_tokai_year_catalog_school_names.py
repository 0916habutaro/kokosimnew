"""Stage43G-59: bounded old-year navigation and saved school display names.

The 100+ year catalog is synthetic registration metadata, NOT consecutive
tournament simulations. All recorded games remain original fictional fixtures.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import tkinter as tk
import unittest

from phase2_engine.career_tokai_season_browse_model import (
    CareerTokaiSeasonBrowseModel, TOKAI,
)
from phase2_engine.career_tokai_season_gui_pilot import (
    YEAR_PAGE_SIZE, CareerTokaiSeasonGuiPilot, TokaiSavedYearPager,
    TokaiSeasonScreenController,
)
from test_stage43g54_tokai_season_history_browse import (
    Stage43G54TokaiHistoryReadOnly,
)

GUI_AVAILABLE = bool(os.environ.get("DISPLAY") or sys.platform.startswith("win"))


class Stage43G59YearCatalogAndHistoricNames(unittest.TestCase):
    def setUp(self):
        self.fixture = Stage43G54TokaiHistoryReadOnly(
            "test_season_index_shows_only_saved_tokai_games_and_source_warning",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.model = self.fixture.model

    def _snapshot(self, slot=None):
        path = self.fixture.slot if slot is None else Path(slot)
        return {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.glob("*.sqlite3*") if p.is_file()
        }

    def _synthetic_year_catalog(self):
        # Only career_years metadata: NO fabricated games or roster seasons.
        with sqlite3.connect(self.fixture.archive.db_path) as conn:
            conn.executemany(
                "INSERT INTO career_years(year, metadata_json, status) "
                "VALUES (?,?, 'active')",
                ((year, json.dumps({
                    "synthetic_catalog_fixture_only": True, "year": year
                })) for year in range(2028, 2141)),
            )

    def test_more_than_100_year_entries_are_lazy_and_all_pages_reachable(self):
        self._synthetic_year_catalog()
        before = self._snapshot()
        pager = TokaiSavedYearPager(self.model)
        self.assertEqual(YEAR_PAGE_SIZE, len(pager.years))
        self.assertEqual(2140, pager.years[0])
        self.assertTrue(pager.has_older)
        count = 0
        while pager.has_older:
            previous = pager.offset
            pager.move(1)
            self.assertEqual(previous + YEAR_PAGE_SIZE, pager.offset)
            count += 1
        self.assertEqual(3, count)
        self.assertEqual(90, pager.offset)
        self.assertEqual(2027, pager.years[-1])
        self.assertFalse(pager.has_older)
        last = (pager.offset, list(pager.years))
        self.assertEqual(last[1], pager.move(1))
        self.assertEqual(last, (pager.offset, pager.years))
        self.assertEqual(2027, TokaiSeasonScreenController(
            self.model, year=2027,
        ).page["year"])
        while pager.offset:
            pager.move(-1)
        self.assertEqual(0, pager.offset)
        self.assertEqual(before, self._snapshot())

    def test_invalid_year_catalog_paging_preserves_state(self):
        pager = TokaiSavedYearPager(self.model)
        before = (pager.offset, list(pager.years), pager.has_older)
        for delta in (0, 2, True, 1.0):
            with self.subTest(delta=delta):
                with self.assertRaises(ValueError):
                    pager.move(delta)
        self.assertEqual(before, (
            pager.offset, pager.years, pager.has_older
        ))
        self.assertEqual([2027], pager.move(-1))
        self.assertEqual([2027], pager.move(1))

    def test_saved_school_name_uses_exact_year_snapshot_not_current_master(self):
        # Write an internally consistent renamed school snapshot only to
        # this disposable fixture, never to a real player save.
        school = self.fixture.a
        path = self.fixture.slot / "career_rosters.sqlite3"
        master_name = self.model.source.repo.schools[school]["school_name"]
        before_name = self.model.school(2027, school)["school_name"]
        self.assertEqual(master_name, before_name)
        with sqlite3.connect(path) as conn:
            raw, = conn.execute(
                "SELECT payload_json FROM career_school_rosters "
                "WHERE year=? AND school_id=?", (2027, school),
            ).fetchone()
            document = json.loads(raw)
            document["school_name"] = "旧校名（架空fixture）"
            encoded = json.dumps(
                document, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
            conn.execute(
                "UPDATE career_school_rosters "
                "SET payload_json=?,content_sha256=? "
                "WHERE year=? AND school_id=?",
                (encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                 2027, school),
            )
        before = self._snapshot()
        page = self.model.school(2027, school)
        self.assertEqual("旧校名（架空fixture）", page["school_name"])
        self.assertEqual("saved_year_roster", page["school_name_source"])
        self.assertEqual(school, page["school_id"])
        self.assertEqual(4, page["matches"]["total"])
        self.assertEqual(before, self._snapshot())

    def test_two_separate_slots_cannot_leak_matches_to_each_other(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        slot_b = Path(other.name) / "slot_B"
        slot_b.mkdir()
        for name in ("historical_matches.sqlite3", "career_rosters.sqlite3"):
            shutil.copy2(self.fixture.slot / name, slot_b / name)
        with sqlite3.connect(slot_b / "historical_matches.sqlite3") as conn:
            conn.execute(
                "DELETE FROM historical_matches "
                "WHERE year=? AND competition_id=? AND match_id=?",
                (2027, TOKAI, "REGIONAL-01"),
            )
        second = CareerTokaiSeasonBrowseModel(
            self.model.source.repo.data_dir, slot_b,
        )
        first_before = self._snapshot()
        second_before = self._snapshot(slot_b)
        self.assertEqual(4, self.model.overview(2027)["archived_match_count"])
        self.assertEqual(3, second.overview(2027)["archived_match_count"])
        self.assertEqual(1, self.model.competition(
            2027, TOKAI,
        )["matches"]["total"])
        self.assertEqual(0, second.competition(
            2027, TOKAI,
        )["matches"]["total"])
        self.assertEqual(first_before, self._snapshot())
        self.assertEqual(second_before, self._snapshot(slot_b))

    @unittest.skipUnless(GUI_AVAILABLE, "Tk requires Xvfb or desktop display")
    def test_tk_older_year_candidates_can_reach_beyond_first_100(self):
        self._synthetic_year_catalog()
        before = self._snapshot()
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        gui = CareerTokaiSeasonGuiPilot(root, self.model, year=2027)
        self.assertEqual(YEAR_PAGE_SIZE, len(gui.available_years))
        self.assertIn("2027", gui.year_picker["values"])
        gui._year_candidates(1)
        gui._year_candidates(1)
        gui._year_candidates(1)
        self.assertEqual(90, gui.year_pager.offset)
        self.assertIn("2027", gui.year_picker["values"])
        self.assertEqual(2027, gui.controller.target["year"])
        self.assertEqual("tokai_season", gui.controller.page["screen"])
        self.assertEqual(before, self._snapshot())


if __name__ == "__main__":
    unittest.main()
