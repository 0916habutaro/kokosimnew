"""Cancellation is acknowledged only after a fresh full RO verification."""
from pathlib import Path
import tempfile
import threading
import time
import unittest

from phase2_engine.yamanashi_demo_controller import DemoController
from phase2_engine.yamanashi_demo_store import MARKER


class Stage110ControllerTests(unittest.TestCase):
    def test_cancel_after_commit_reverifies_and_keeps_committed_game(self):
        with tempfile.TemporaryDirectory(prefix='stage110-cancel-') as temp:
            c=DemoController(); self.addCleanup(c.close)
            c.use_namespace(Path(temp)/'dedicated',create=True); c.execute('new')
            def fault(at):
                if at=='after_commit': c.request_cancel()
            c.begin('round',fault=fault)
            updates=self.drain(c)
            self.assertEqual([1],[len(u.snapshot.results) for u in updates if u.snapshot and not u.done])
            self.assertTrue(updates[-1].done); self.assertFalse(updates[-1].error)
            self.assertIn('中断完了',updates[-1].message)
            self.assertEqual(1,len(c.snapshot.results))
            before=c.store.db_path.read_bytes()
            self.assertEqual(1,len(c.store.snapshot().results))
            self.assertEqual(before,c.store.db_path.read_bytes())

    def test_cancel_reverification_failure_clears_untrusted_snapshot(self):
        with tempfile.TemporaryDirectory(prefix='stage110-refuse-') as temp:
            c=DemoController(); self.addCleanup(c.close)
            c.use_namespace(Path(temp)/'dedicated',create=True); c.execute('new')
            db=c.store.db_path; before=db.read_bytes()
            marker=db.parent/MARKER
            def fault(at):
                if at=='before_calculation':
                    marker.write_bytes(marker.read_bytes()+b' ')
                    c.request_cancel()
            c.begin('one',fault=fault)
            updates=self.drain(c)
            self.assertTrue(updates[-1].done and updates[-1].error)
            self.assertIsNone(c.snapshot); self.assertIsNone(c.store)
            self.assertEqual(before,db.read_bytes())

    def drain(self,c):
        deadline=time.monotonic()+120; updates=[]
        while c.busy:
            update=c.poll()
            if update: updates.append(update)
            self.assertLess(time.monotonic(),deadline)
            time.sleep(.005)
        return updates
