"""Mapped native Tk button operations; all GUI Python processes fully exit."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from phase2_engine.yamanashi_demo_store import DemoNamespace, DemoStore, MARKER
from phase2_engine.yamanashi_demo_tk import YamanashiDemoTk
from stage43g109_support import run_gui
from stage43g99_fixture_support import retained_handles, assert_closed

MEASUREMENTS = {}


@unittest.skipUnless(sys.platform=='win32' or os.environ.get('DISPLAY'), 'native Windows Tk or auxiliary display required')
class Stage109NativeTkTests(unittest.TestCase):
    def test_mapped_new_progress_exit_separate_processes_continue31_all660_navigation(self):
        with tempfile.TemporaryDirectory(prefix='stage109-tk-process-') as temp:
            namespace=Path(temp)/'dedicated'
            phases=[run_gui(namespace,0)]
            did=phases[0]['demo_id']
            phases += [run_gui(namespace,phase,did) for phase in (1,2)]
            self.assertEqual([1,16,31],[p['committed'] for p in phases])
            self.assertTrue(all(p['mapped'] for p in phases))
            self.assertEqual(660,phases[-1]['visited_players'])
            MEASUREMENTS['native_tk']=[{k:v for k,v in p.items() if k!='demo_id'} for p in phases]

    def test_mapped_cancel_uncommitted_and_corruption_selection_clear_close_reopen(self):
        with tempfile.TemporaryDirectory(prefix='stage109-tk-cancel-') as temp:
            ns=DemoNamespace.create(Path(temp)/'dedicated',opt_in=True)
            root=tk.Tk();errors=[]
            root.report_callback_exception=lambda *args:errors.append('callback')
            gui=YamanashiDemoTk(root,namespace_picker=lambda create:ns.path,confirm=lambda text:True)
            def pump_until(condition):
                end=time.monotonic()+120
                while not condition():
                    root.update()
                    self.assertFalse(errors)
                    self.assertLess(time.monotonic(),end)
                    time.sleep(.01)
            try:
                gui.buttons['namespace_open'].invoke()
                gui.buttons['new'].invoke()
                pump_until(lambda:not gui.controller.busy)
                self.assertTrue(root.winfo_ismapped())
                self.assertEqual(0,len(gui.controller.snapshot.results))
                store=gui.controller.store;did=store.demo_id;db=store.db_path
                before=db.read_bytes()
                entered=threading.Event();release=threading.Event()
                from phase2_engine import yamanashi_demo_store as module
                original=module._run
                def slow(*args):
                    entered.set()
                    if not release.wait(30):raise RuntimeError('test deadline')
                    return original(*args)
                with patch.object(module,'_run',side_effect=slow):
                    gui.buttons['one'].invoke()
                    pump_until(entered.is_set)
                    self.assertIn('処理中',gui.status_var.get())
                    self.assertFalse(gui.history.tables['scores'].get_children())
                    gui.buttons['exit'].invoke()
                    self.assertTrue(gui.closing)
                    self.assertIn('未commit',gui.status_var.get())
                    release.set()
                    pump_until(lambda:gui.closed)
                self.assertEqual(before,db.read_bytes())
                self.assertTrue(gui.controller.closed)
            finally:
                if not gui.closed:
                    gui.controller.close();root.destroy()
            with retained_handles() as handles:
                resumed=DemoStore.resume(DemoNamespace(ns.path),did)
                self.assertEqual(0,len(resumed.snapshot().results))
                resumed.close()
                assert_closed(self,handles)
            moved=db.with_suffix('.released');db.rename(moved);moved.rename(db)
            import gc
            gui=None;root=None;gc.collect()  # Tcl finalizers run on the owning thread.
            root=tk.Tk();gui=YamanashiDemoTk(root,namespace_picker=lambda create:ns.path,confirm=lambda text:True)
            root.report_callback_exception=lambda *args:errors.append('callback')
            try:
                gui.buttons['namespace_open'].invoke();gui.demo_box.set(did)
                gui.buttons['resume'].invoke();pump_until(lambda:not gui.controller.busy)
                self.assertIsNotNone(gui.history.snapshot)
                marker=db.parent/MARKER;raw=marker.read_bytes();marker.write_bytes(raw+b' ')
                before=db.read_bytes()
                gui.buttons['reload'].invoke();pump_until(lambda:not gui.controller.busy)
                self.assertIsNone(gui.history.snapshot)
                self.assertTrue(all(not tree.get_children() for tree in gui.history.tables.values()))
                self.assertTrue(all(not picker['values'] for picker in gui.history.pickers.values()))
                self.assertIsNotNone(gui.last_error)
                self.assertEqual(before,db.read_bytes())
                # Explicitly selecting a broken demo also fails with an empty screen.
                gui.demo_box.set(did);gui.buttons['resume'].invoke();pump_until(lambda:not gui.controller.busy)
                self.assertIsNone(gui.history.snapshot)
                gui.buttons['exit'].invoke();self.assertTrue(gui.closed)
                self.assertFalse(errors)
            finally:
                if not gui.closed:
                    gui.controller.close();root.destroy()
