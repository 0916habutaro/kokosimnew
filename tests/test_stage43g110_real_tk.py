"""Mapped native Tk UX: commit ACK, responsive cancel, lazy guarded records."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from phase2_engine.yamanashi_demo_tk import YamanashiDemoTk
from phase2_engine.yamanashi_demo_store import MARKER, codec
from stage43g109_support import run_cli


@unittest.skipUnless(sys.platform=='win32' or os.environ.get('DISPLAY'), 'native Windows Tk or auxiliary display required')
class Stage110NativeTkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='stage110-ux-'); self.addCleanup(self.temp.cleanup)
        self.namespace=Path(self.temp.name)/'dedicated'
        self.root=tk.Tk(); self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append('callback')
        self.gui=YamanashiDemoTk(self.root,namespace_picker=lambda create:self.namespace,confirm=lambda text:True)
        self.addCleanup(self.close)
        self.root.update(); self.assertTrue(self.root.winfo_ismapped())
        self.gui.buttons['namespace_new'].invoke(); self.gui.buttons['new'].invoke()
        self.pump(lambda:not self.gui.controller.busy)

    def close(self):
        if not self.gui.closed:
            self.gui.controller.close(); self.gui.close()
        # Release Tk cycles on its owning thread before any next worker starts.
        import gc
        self.gui=None; self.root=None; gc.collect()

    def pump(self,condition):
        deadline=time.monotonic()+150
        while not condition():
            self.root.update(); self.assertFalse(self.errors)
            self.assertLess(time.monotonic(),deadline); time.sleep(.005)
        self.root.update(); self.assertFalse(self.errors)

    def test_each_commit_progress_busy_controls_cancel_ack_and_independent_reader(self):
        gui=self.gui; c=gui.controller
        observed=[]; owner=threading.get_ident()
        def observe(*args):
            self.assertEqual(owner,threading.get_ident())
            observed.append(gui.current_var.get())
        gui.current_var.trace_add('write',observe)
        entered=threading.Event(); release=threading.Event(); count=0
        def fault(at):
            nonlocal count
            if at=='after_commit':
                count+=1
                if count==4:
                    entered.set()
                    if not release.wait(60): raise RuntimeError('test deadline')
        original=c.begin
        with patch.object(c,'begin',side_effect=lambda action,**kwargs:original(action,fault=fault,**kwargs)):
            gui.buttons['round'].invoke()
        try:
            self.pump(entered.is_set)
            self.pump(lambda:any('3/31試合 自動保存済み' in text for text in observed))
            self.assertFalse(any('4/31試合 自動保存済み' in text for text in observed))
            self.assertIn('前試合',gui.current_var.get()); self.assertIn('ラウンド',gui.current_var.get())
            ticks=[]; self.root.after(1,lambda:ticks.append(True)); self.pump(lambda:bool(ticks))
            for key in ('new','resume','one','round','reload','namespace_new','namespace_open'):
                self.assertEqual('disabled',str(gui.buttons[key]['state']))
                gui.buttons[key].invoke()
            gui.dispatch('namespace_open'); gui.dispatch('one')
            self.assertEqual(4,count)
            gui.buttons['cancel'].invoke(); self.assertIn('中断要求中',gui.status_var.get())
        finally: release.set()
        self.pump(lambda:not c.busy)
        self.assertIn('中断完了',gui.status_var.get())
        self.assertEqual(4,len(c.snapshot.results)); self.assertEqual(4,float(gui.progress['value']))
        for n in (1,2,3,4): self.assertTrue(any(f'{n}/31試合 自動保存済み' in text for text in observed))
        db=c.store.db_path; did=c.store.demo_id; before=db.read_bytes()
        gui.buttons['exit'].invoke(); self.assertTrue(gui.closed)
        self.assertEqual(4,run_cli(self.namespace,demo_id=did)['committed'])
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as con:
            self.assertEqual(4,con.execute('SELECT count(*) FROM matches').fetchone()[0])
            for raw,sha in con.execute('SELECT result_json,result_sha256 FROM matches'):
                self.assertEqual(codec.digest(raw),sha)
                value=codec.strict_json(raw)
                self.assertTrue(value['inning_scores'] and value['batter_stats'] and value['pitcher_stats'])
        self.assertEqual(before,db.read_bytes())

    def test_deferred_stats_unregistered_names_and_corruption_clear_all_tabs(self):
        gui=self.gui; history=gui.history; snap=gui.controller.snapshot
        from phase2_engine import yamanashi_demo_tk as module
        with patch.object(module,'player_totals',wraps=module.player_totals) as totals:
            history.show(snap)
            self.assertEqual(0,totals.call_count)
            joint=next(i for i,t in enumerate(snap.registration.teams) if len(t.school_ids)==2)
            history.pickers['team'].current(joint); history.select('team')
            self.assertEqual(0,totals.call_count)
            self.assertTrue(all('[' in name for name in history.pickers['school']['values'][1:]))
            registered={p.player_id for t in snap.registration.teams for p in t.players}
            people=history.pickers['player']['values']
            index=next(i for i,pid in enumerate(people[1:],1) if pid not in registered)
            history.pickers['player'].current(index); history.select('player')
            self.assertIn('未登録1人／未出場1人',history.status['text'])
            history.book.select(history.tables['stats'].master); self.root.update()
            self.assertGreater(totals.call_count,0)
            rows=[history.tables['stats'].item(i,'values') for i in history.tables['stats'].get_children()]
            self.assertEqual(2,len(rows)); self.assertTrue(all(r[5]=='未登録・未出場' for r in rows))
            history.book.select(history.tables['ranks'].master); self.root.update()
            db=gui.controller.store.db_path; before=db.read_bytes()
            marker=db.parent/MARKER; marker.write_bytes(marker.read_bytes()+b' ')
            history.book.select(history.tables['stats'].master); self.root.update()
            self.assertIsNone(history.snapshot); self.assertIsNone(gui.controller.snapshot)
            self.assertTrue(all(not t.get_children() for t in history.tables.values()))
            self.assertTrue(all(not box['values'] for box in history.pickers.values()))
            self.assertEqual(0,float(gui.progress['value']))
            self.assertEqual(before,db.read_bytes())
