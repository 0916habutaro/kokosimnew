"""Mapped Tk six-game restart on both sources and product-persisted history/ranking."""
import json
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from phase2_engine.live_game_demo_controller import DemoController
from phase2_engine.live_game_tk_pilot import LiveGameTkPilot
import test_stage43g98_real_tk as native
from test_stage43g100_persistence import raw_records
from stage43g97_acceptance_support import pin
from stage43g99_fixture_support import retained_handles,assert_closed,rename_and_read


@unittest.skipUnless(sys.platform=='win32' or os.environ.get('DISPLAY'),'native Windows or auxiliary display required')
class Stage43G100RealTkTests(unittest.TestCase):
    pump = native.Stage43G98RealTkTests.pump
    invoke = native.Stage43G98RealTkTests.invoke

    def test_six_restart_both_sources_finish_seal_show_school_players_ranking_readonly(self):
        for source in ('manual','autosave'):
            with self.subTest(source=source),tempfile.TemporaryDirectory(prefix='stage100-tk-') as temp:
                base=Path(temp)/'保存 日本語'
                c=DemoController(_base=base)
                root=tk.Tk();gui=LiveGameTkPilot(root,c,confirm=lambda _:True)
                try:
                    self.pump(root,lambda:bool(root.winfo_ismapped()))
                    self.invoke(gui,'new');self.invoke(gui,'next_match');self.invoke(gui,'next_match')
                    self.assertEqual(6,c.view.game['summary']['completed_match_count'])
                    self.invoke(gui,'manual')
                    demo_id=c.demo_id
                    gui.buttons['exit'].invoke()
                    self.assertTrue(gui.closed)
                finally:
                    if not gui.closed: gui.close()
                # The controller dispatches another real Python process for load.
                c=DemoController(demo_id,_base=base)
                root=tk.Tk();gui=LiveGameTkPilot(root,c,confirm=lambda _:True)
                try:
                    self.pump(root,lambda:bool(root.winfo_ismapped()))
                    gui.source_var.set(source);self.invoke(gui,'load')
                    self.assertEqual(6,c.view.game['summary']['completed_match_count'])
                    self.invoke(gui,'next_match');self.invoke(gui,'seal')
                    raw=raw_records(c.slot)
                    before=pin(c.saves)
                    with patch.object(c,'_worker',side_effect=AssertionError('history cannot write')):
                        gui.buttons['history'].invoke()
                        self.assertIsNone(gui.last_error)
                        h=gui.history_gui
                        self.pump(root,lambda:bool(h.root.winfo_ismapped()))
                        for rank,sid in enumerate(raw['outcomes'][0]['ranked_school_ids'],1):
                            self.assertIn(f'{rank}位 ',h.ranking_text)
                            self.assertIn('['+sid+']',h.ranking_text)
                        def choose(predicate):
                            wid=next(w for w,r in h.rows_by_widget_id.items() if predicate(r))
                            h.tree.selection_set(wid);h.tree.event_generate('<<TreeviewSelect>>');root.update()
                            h.open_button.invoke();root.update();self.assertIsNone(h.last_error)
                        choose(lambda r:r['kind']=='year' and r['year']==2026)
                        self.assertEqual(8,len(h.view['rows']))
                        match=raw['matches'][0]
                        choose(lambda r:r['kind']=='school' and r['school_id']==match['team1_id'])
                        choose(lambda r:r.get('target',{}).get('match_id')==match['match_id'])
                        self.assertEqual('history_match',h.view['screen'])
                        for field in ('inning_scores','team_stats','batter_stats','pitcher_stats'):
                            self.assertEqual(match[field],h.bridge.page['data']['details'][field])
                        h.back_button.invoke();root.update()
                        choose(lambda r:bool(r.get('target',{}).get('player_id')))
                        self.assertEqual('history_player',h.view['screen'])
                        self.assertIsNotNone(h.bridge.page['data']['selected_statistics'])
                        gui.close_history();root.update()
                    self.assertEqual(before,pin(c.saves))
                    self.invoke(gui,'load')
                    self.assertEqual(7,c.view.game['summary']['completed_match_count'])
                    self.assertEqual(before,pin(c.saves))
                finally: gui.close()
                base.rename(Path(temp)/'子窓・ゲーム終了後 rename')


if __name__=='__main__': unittest.main()
