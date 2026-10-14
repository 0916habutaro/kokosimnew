"""Native mapped 33-school readonly history without fixture handle cleanup."""
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from phase2_engine.live_game_service import LiveGameService, Yamanashi33FixturePersistence as Authority
from phase2_engine.yamanashi33_history_tk import Yamanashi33HistoryTkPilot
from stage43g102_fixture_support import MEASUREMENTS
from time import perf_counter
from stage43g97_acceptance_support import pin
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read
from stage43g102_fixture_support import services, raw_records, resume_process, ROOT, SLOT, SEED


@unittest.skipUnless(sys.platform == "win32" or os.environ.get("DISPLAY"),
    "native Windows Tk or auxiliary display required")
class Stage43G102RealTkTests(unittest.TestCase):
    def test_mapped_all33schools_all32matches_ranking_and_permanent_player_close_readonly(self):
        with tempfile.TemporaryDirectory(prefix="stage102-tk-") as temp:
            saves = Path(temp).resolve() / "保存 日本語"
            service, resolver, engine = services(saves)
            session = service.new_game(SLOT, rng_seed=SEED, engine=engine, start_date="2026-07-01")
            service.advance_through(session, "2026-07-06")
            service.save_game(session)
            resume_process(saves, finish=True)  # Real separate-process load and seal.
            slot = saves / SLOT
            raw = raw_records(slot)
            before = pin(slot)
            sid = "SCH000196"
            with retained_handles() as handles, patch.object(
                    LiveGameService, "load_game", side_effect=AssertionError("history cannot write")):
                root = tk.Tk()
                gui = Yamanashi33HistoryTkPilot(root, slot, data_root=ROOT / "data")
                errors = []
                root.report_callback_exception = lambda kind, value, trace: errors.append(value)
                try:
                    root.update()
                    self.assertTrue(root.winfo_ismapped())
                    def choose(predicate):
                        wid = next(w for w, row in gui.rows_by_widget_id.items() if predicate(row))
                        gui.tree.selection_set(wid)
                        gui.tree.event_generate("<<TreeviewSelect>>")
                        root.update()
                        gui.open_button.invoke()
                        root.update()
                        self.assertIsNone(gui.last_error)
                        assert_closed(self, handles)
                        rename_and_read(self, slot)
                    choose(lambda r: r["kind"] == "year" and r["year"] == 2026)
                    first = {r["school_id"] for r in gui.rows_by_widget_id.values() if r["kind"] == "school"}
                    self.assertEqual(30, len(first))
                    start = perf_counter()
                    def browse_schools(schools):
                        for school in sorted(schools):
                            choose(lambda r: r["kind"] == "school" and r["school_id"] == school)
                            self.assertEqual(school, gui.bridge.page["data"]["school_id"])
                            gui.back_button.invoke()
                            root.update()
                    browse_schools(first)
                    gui.older_button.invoke()
                    root.update()
                    last = {r["school_id"] for r in gui.rows_by_widget_id.values() if r["kind"] == "school"}
                    self.assertEqual(3, len(last))
                    self.assertEqual(set(Authority.SCHOOL_IDS), first | last)
                    browse_schools(last)
                    MEASUREMENTS["all33_native_school_browse_seconds"] = round(perf_counter()-start, 3)
                    gui.back_button.invoke()
                    root.update()
                    choose(lambda r: r["kind"] == "school" and r["school_id"] == sid)
                    gui.tournament_button.invoke()
                    root.update()
                    self.assertTrue(gui.tournament_window.winfo_ismapped())
                    self.assertEqual(33, len(gui.ranking_table.get_children()))
                    self.assertEqual(32, gui.competition["matches"]["total"])
                    self.assertEqual(raw["outcomes"][0], gui.ranking)
                    # Every simulated game can render its complete A rows.
                    gui.back_button.invoke()
                    root.update()
                    for game in raw["matches"]:
                        second_page = game["team1_id"] in last
                        if second_page:
                            gui.older_button.invoke()
                            root.update()
                        choose(lambda r: r["kind"] == "school" and r["school_id"] == game["team1_id"])
                        choose(lambda r: r.get("target", {}).get("match_id") == game["match_id"])
                        for field in ("inning_scores", "team_stats", "batter_stats", "pitcher_stats"):
                            self.assertEqual(game[field], gui.bridge.page["data"]["details"][field])
                        gui.back_button.invoke()
                        root.update()
                        gui.back_button.invoke()
                        root.update()
                        if second_page:
                            gui.back_button.invoke()
                            root.update()
                    choose(lambda r: r["kind"] == "school" and r["school_id"] == sid)
                    for cid in ("CMP000041",):
                        match = next(m for m in raw["matches"] if m["competition_id"] == cid and sid in (m["team1_id"], m["team2_id"]))
                        choose(lambda r: r.get("target", {}).get("match_id") == match["match_id"])
                        self.assertEqual("history_match", gui.view["screen"])
                        for field in ("inning_scores", "team_stats", "batter_stats", "pitcher_stats"):
                            self.assertEqual(match[field], gui.bridge.page["data"]["details"][field])
                        gui.back_button.invoke()
                        root.update()
                    player_id = next(s["player_id"] for m in raw["matches"]
                        for s in m["batter_stats"] if s["school_id"] == sid)
                    choose(lambda r: r.get("target", {}).get("player_id") == player_id)
                    self.assertEqual("history_player", gui.view["screen"])
                    self.assertIsNotNone(gui.bridge.page["data"]["selected_statistics"])
                    self.assertFalse(errors)
                    self.assertEqual(before, pin(slot))
                finally:
                    gui._close_game_windows()
                    root.destroy()
                assert_closed(self, handles)
                rename_and_read(self, slot)
            self.assertEqual(before, pin(slot))


if __name__ == "__main__":
    unittest.main()
