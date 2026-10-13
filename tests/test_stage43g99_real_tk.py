"""Real mapped history events without Stage98's fixture handle closer."""
import os
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

from phase2_engine.career_history_slot_session import CareerHistorySlotSession
from phase2_engine.career_history_tk_pilot import CareerHistoryTkPilot
from phase2_engine.live_game_service import LiveGameService
from phase2_engine.career_roster_archive import CareerRosterArchive
from stage43g94_fixture_support import Fixture, owned_sqlite_handles
from stage43g95_isolated_harness import anchor
from stage43g97_acceptance_support import sql_games
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read

DISPLAY = sys.platform == 'win32' or bool(os.environ.get('DISPLAY'))


@unittest.skipUnless(DISPLAY, 'native Windows Tk or auxiliary display required')
class Stage43G99RealTkTests(unittest.TestCase):
    def test_product_history_open_back_exception_child_close_and_restart_release(self):
        # Only fixture generation has a legacy cleanup wrapper. Every GUI read
        # below must release its own product handles before our final cleanup.
        with owned_sqlite_handles():
            f = Fixture('sealed')
        self.addCleanup(f.close)
        first = sql_games(f.slot)[0]
        before = anchor(f.slot)
        sid = first['team1_id']
        with retained_handles() as handles, patch.object(
                LiveGameService, 'load_game', side_effect=AssertionError('history writer')):
            for cycle in range(2):
                session = CareerHistorySlotSession(f.save_root, 'owned94')
                root = tk.Tk()
                gui = CareerHistoryTkPilot(root, session.bridge, school_id='', slot_session=session)
                errors = []
                root.report_callback_exception = lambda kind,value,trace:errors.append(value)
                try:
                    root.update()
                    self.assertTrue(root.winfo_ismapped())
                    def choose(predicate):
                        wid = next(w for w,row in gui.rows_by_widget_id.items() if predicate(row))
                        gui.tree.selection_set(wid)
                        gui.tree.event_generate('<<TreeviewSelect>>')
                        root.update()
                        gui.open_button.invoke()
                        root.update()
                        self.assertIsNone(gui.last_error)
                        assert_closed(self, handles)
                        rename_and_read(self, f.slot)
                    choose(lambda r:r['kind']=='year' and r['year']==2026)
                    failure = ValueError('owned read failure')
                    wid = next(w for w,row in gui.rows_by_widget_id.items()
                               if row['kind']=='school' and row['school_id']==sid)
                    gui.tree.selection_set(wid)
                    # A real button dispatch catches a product reader exception
                    # and keeps the previously validated navigation state.
                    with patch.object(CareerRosterArchive,'_get',side_effect=failure):
                        gui.open_button.invoke();root.update()
                    self.assertIsNotNone(gui.last_error)
                    self.assertEqual('history_school_catalog',gui.view['screen'])
                    self.assertIsNotNone(failure.__traceback__)
                    assert_closed(self,handles)
                    rename_and_read(self,f.slot)
                    choose(lambda r:r['kind']=='school' and r['school_id']==sid)
                    # Open and close a real child window, then repeat close.
                    gui._open_legacy_games()
                    root.update()
                    self.assertIsNone(gui.last_error)
                    self.assertTrue(gui.legacy_window.root.winfo_ismapped())
                    gui._close_game_windows()
                    gui._close_game_windows()
                    assert_closed(self, handles)
                    choose(lambda r:r.get('target',{}).get('match_id')==first['match_id'])
                    self.assertEqual('history_match',gui.view['screen'])
                    gui.back_button.invoke();root.update()
                    choose(lambda r:bool(r.get('target',{}).get('player_id')))
                    self.assertEqual('history_player',gui.view['screen'])
                    gui.back_button.invoke();gui.back_button.invoke();gui.back_button.invoke();root.update()
                    gui.slot_var.set('../foreign')
                    gui.slot_box.event_generate('<<ComboboxSelected>>');root.update()
                    self.assertIsNotNone(gui.last_error)
                    self.assertEqual('owned94',session.slot_id)
                    assert_closed(self,handles)
                    self.assertFalse(errors,errors)
                    assert_closed(self,handles)
                    rename_and_read(self,f.slot)
                    self.assertEqual(before,anchor(f.slot),cycle)
                finally:
                    gui._close_game_windows()
                    root.destroy()
                assert_closed(self,handles)
                rename_and_read(self,f.slot)
        self.assertEqual(before,anchor(f.slot))


if __name__ == '__main__':
    unittest.main()
