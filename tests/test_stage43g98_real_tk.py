"""Native mapped Windows Tk; Linux display is an auxiliary check only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from phase2_engine.live_game_demo_controller import DemoController, pin
from phase2_engine.live_game_tk_pilot import LiveGameTkPilot
import stage43g97_acceptance_support as oracle

DISPLAY = sys.platform == 'win32' or bool(os.environ.get('DISPLAY'))


@unittest.skipUnless(DISPLAY, 'native Windows Tk or auxiliary display required')
class Stage43G98RealTkTests(unittest.TestCase):
    def pump(self, root, predicate, timeout=120):
        errors = []
        deadline = time.monotonic() + timeout
        def tick():
            if predicate(): root.quit()
            elif time.monotonic() > deadline:
                errors.append(AssertionError('native Tk operation timed out'));root.quit()
            else: root.after(10, tick)
        root.after(10, tick)
        root.mainloop()
        if errors: raise errors[0]

    def invoke(self, gui, action):
        self.assertEqual('normal', str(gui.buttons[action]['state']))
        gui.buttons[action].invoke()
        self.pump(gui.root, lambda:gui.pending is None)
        self.assertIsNone(gui.last_error)

    def test_native_new_progress_save_exit_restart_load_history_and_corruption(self):
        with tempfile.TemporaryDirectory(prefix='stage98-native-') as temp:
            base = Path(temp) / '保存 日本語'
            c = DemoController(_base=base)
            root = tk.Tk()
            gui = LiveGameTkPilot(root, c, confirm=lambda _:True)
            try:
                self.pump(root, lambda:bool(root.winfo_ismapped()))
                self.assertIsNone(c.view.game)
                self.invoke(gui,'new')
                # A queued double button cannot start another game operation.
                gui.buttons['day'].invoke()
                future = gui.pending
                gui.dispatch('day')
                self.assertIs(future,gui.pending)
                self.pump(root, lambda:gui.pending is None)
                self.assertIsNone(gui.last_error)
                self.assertEqual('2026-07-02', c.view.game['summary']['current_date'])
                self.invoke(gui,'today')
                self.invoke(gui,'next_match')
                self.invoke(gui,'manual')
                self.assertIn('autosave.json', pin(c.saves))
                # Unsealed history is a rejected UI event, no save writes.
                before = pin(c.saves)
                gui.buttons['history'].invoke()
                self.assertIsNotNone(gui.last_error)
                self.assertEqual(before,pin(c.saves))
                for _ in range(2): self.invoke(gui,'next_match')
                self.invoke(gui,'seal')
                self.assertEqual('disabled',str(gui.buttons['next_match']['state']))
                game = c.view.game
                self.assertEqual(7, game['summary']['completed_match_count'])
                demo_id = c.demo_id
                gui.buttons['exit'].invoke()
                self.assertTrue(gui.closed)
            finally:
                if not gui.closed: gui.close()

            for source in ('manual','autosave'):
                c = DemoController(demo_id,_base=base)
                root = tk.Tk()
                gui = LiveGameTkPilot(root,c,confirm=lambda _:True)
                callback_errors = []
                root.report_callback_exception = lambda kind,value,trace:callback_errors.append(value)
                try:
                    self.pump(root,lambda:bool(root.winfo_ismapped()))
                    self.assertIsNone(c.view.game)
                    before = pin(c.saves)
                    with patch.object(c,'_worker',side_effect=AssertionError('writer from history')):
                        gui.buttons['history'].invoke()
                        self.assertIsNone(gui.last_error)
                        h = gui.history_gui
                        self.pump(root,lambda:bool(h.root.winfo_ismapped()))
                        def choose(predicate, open_item=True):
                            wid = next(w for w,row in h.rows_by_widget_id.items() if predicate(row))
                            h.tree.selection_set(wid)
                            h.tree.event_generate('<<TreeviewSelect>>')
                            root.update()
                            if open_item: h.open_button.invoke();root.update()
                            self.assertIsNone(h.last_error)
                        choose(lambda r:r['kind']=='year' and r['year']==2026)
                        self.assertEqual(8,len(h.view['rows']))
                        first = game['actual_games'][0]
                        choose(lambda r:r['kind']=='school' and r['school_id']==first['team1_id'])
                        choose(lambda r:r.get('target',{}).get('match_id')==first['match_id'])
                        self.assertEqual('history_match',h.view['screen'])
                        self.assertEqual({k:first['ability_detail'][k] for k in oracle.DETAILS},
                                         h.bridge.page['data']['details'])
                        for field,caption in [('inning_scores','イニング別得点'),('batter_stats','打撃成績'),('pitcher_stats','投手成績')]:
                            choose(lambda r:r['kind']=='detail' and r['title']==caption+' 1',False)
                            self.assertEqual(first['ability_detail'][field][0],json.loads(h.detail_text.get('1.0','end-1c')))
                        h.back_button.invoke();root.update()
                        choose(lambda r:bool(r.get('target',{}).get('player_id')))
                        self.assertEqual('history_player',h.view['screen'])
                        self.assertIsNotNone(h.bridge.page['data']['selected_statistics'])
                        h.back_button.invoke();h.back_button.invoke();h.back_button.invoke();root.update()
                        gui.close_history()
                    self.assertEqual(before,pin(c.saves))
                    gui.source_var.set(source)
                    self.invoke(gui,'load')
                    self.assertEqual(game['actual_games'],c.view.game['actual_games'])
                    self.assertEqual(before,pin(c.saves))
                    if source == 'autosave':
                        # Corrupt an owned save: UI rejects before writer entry.
                        (c.slot/'manual.json').write_text('破損',encoding='utf-8')
                        broken = oracle.pin(c.root)
                        gui.buttons['load'].invoke()
                        self.pump(root,lambda:gui.pending is None)
                        self.assertIsNotNone(gui.last_error)
                        self.assertEqual(broken,oracle.pin(c.root))
                    self.assertFalse(callback_errors,callback_errors)
                finally:
                    gui.close()
            base.rename(Path(temp)/'GUI終了後 rename')


if __name__ == '__main__':
    unittest.main()
