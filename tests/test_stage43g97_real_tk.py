"""Real mapped Tk widgets; Windows native desktop is the primary CI gate."""
import json
import os
import sys
import tkinter as tk
import unittest

import stage43g97_acceptance_support as lab
from phase2_engine.career_history_slot_session import CareerHistorySlotSession
from phase2_engine.career_history_tk_pilot import CareerHistoryTkPilot

DISPLAY = sys.platform == 'win32' or bool(os.environ.get('DISPLAY'))


@unittest.skipUnless(DISPLAY, 'native Windows Tk or auxiliary Xvfb required')
class Stage43G97RealTkTests(unittest.TestCase):
    def test_generated_game_year_school_score_boxscore_player_close_restart(self):
        game = lab.OwnedGame(); self.addCleanup(game.close)
        expected = game.ready('autosave')
        game.run('register', 'autosave')
        before = lab.pin(game.slot)
        first = expected[0]
        sid = first['team1_id']
        pid = next(r['player_id'] for r in first['batter_stats'] if r['school_id'] == sid)
        with lab.owned_sqlite_handles():
            for cycle in range(2):
                session = CareerHistorySlotSession(game.saves, lab.SLOT)
                root = tk.Tk()
                errors = []
                try:
                    gui = CareerHistoryTkPilot(root, session.bridge, school_id='', slot_session=session)
                    def callback_error(kind, value, traceback):
                        errors.append(value);root.quit()
                    root.report_callback_exception = callback_error
                    def choose(predicate, open_item=True):
                        key = next(w for w, row in gui.rows_by_widget_id.items() if predicate(row))
                        gui.tree.selection_set(key)
                        gui.tree.event_generate('<<TreeviewSelect>>')
                        root.update()
                        if open_item:
                            gui.open_button.invoke();root.update()
                        self.assertIsNone(gui.last_error)
                    def flow():
                        try:
                            self.assertTrue(root.winfo_ismapped())
                            self.assertEqual([2026], [r['year'] for r in gui.view['rows']])
                            choose(lambda r:r['kind'] == 'year' and r['year'] == 2026)
                            self.assertEqual(8, len(gui.view['rows']))
                            self.assertTrue(any(any(ord(c)>127 for c in r['title']) for r in gui.view['rows']))
                            choose(lambda r:r['kind'] == 'school' and r['school_id'] == sid)
                            self.assertEqual('history_school', gui.view['screen'])
                            choose(lambda r:r.get('target',{}).get('match_id') == first['match_id'] if r.get('target') else False)
                            self.assertEqual('history_match', gui.view['screen'])
                            self.assertEqual({k:first[k] for k in lab.DETAILS}, gui.bridge.page['data']['details'])
                            self.assertIn(str(first['team1_score']), gui.view['summary'])
                            for field, caption in (('inning_scores','イニング別得点'),('batter_stats','打撃成績'),('pitcher_stats','投手成績')):
                                choose(lambda r:r['kind'] == 'detail' and r['title'] == caption+' 1', False)
                                self.assertEqual(first[field][0], json.loads(gui.detail_text.get('1.0','end-1c')))
                            gui.back_button.invoke();root.update()
                            choose(lambda r:r.get('target',{}).get('player_id') == pid if r.get('target') else False)
                            self.assertEqual('history_player', gui.view['screen'])
                            choose(lambda r:r['kind'] == 'detail', False)
                            self.assertEqual(gui.bridge.page['data']['selected_statistics'],
                                             json.loads(gui.detail_text.get('1.0','end-1c')))
                            gui.back_button.invoke();gui.back_button.invoke();gui.back_button.invoke()
                            gui.slot_var.set('../foreign')
                            gui.slot_box.event_generate('<<ComboboxSelected>>');root.update()
                            self.assertIsNotNone(gui.last_error)
                            self.assertEqual(lab.SLOT, gui.slot_var.get())
                            gui.refresh_button.invoke();root.update()
                            self.assertIsNone(gui.last_error)
                            self.assertEqual('history_year_catalog', gui.view['screen'])
                            self.assertEqual(before, lab.pin(game.slot))
                        except BaseException as exc:
                            errors.append(exc)
                        finally:
                            root.quit()
                    root.update()
                    root.after(0, flow)
                    root.after(30000, lambda:(errors.append(AssertionError('Tk event loop timed out')),root.quit()))
                    root.mainloop()
                    if errors:
                        raise errors[0]
                finally:
                    root.destroy()
                self.assertEqual(before, lab.pin(game.slot), cycle)
        moved = game.saves.with_name('GUI終了後 移動');game.saves.rename(moved)
        self.assertEqual(7, len(lab.sql_games(moved/lab.SLOT)))


if __name__ == '__main__':
    unittest.main()
