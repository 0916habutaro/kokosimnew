"""Generated TemporaryDirectory inputs only; failure bytes independently pinned."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from phase2_engine.live_game_demo_controller import DemoController, pin, demo_read_handles
from phase2_engine.live_game_demo_worker import ROOT, SLOT
from phase2_engine.manual_save_backup import _compatibility
import stage43g97_acceptance_support as oracle


class Stage43G98ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory(prefix='stage98-tests-'))
        self.base = Path(self.temp) / '隔離 demo'
        self.c = DemoController(_base=self.base)
        self.addCleanup(self.c.close)

    def finish(self):
        self.c.execute('new')
        for _ in range(3):
            self.c.execute('next_match')
        return self.c.execute('seal')

    def test_real_service_cycle_restart_manual_autosave_and_read_only(self):
        masters = oracle.pin(ROOT / 'data')
        self.c.execute('new')
        self.c.execute('day')
        self.c.execute('today')
        for _ in range(3):
            game = self.c.execute('next_match')
        self.assertEqual(7, game['summary']['completed_match_count'])
        self.c.execute('manual')
        game = self.c.execute('seal')
        expected = [{**{k:m[k] for k in oracle.KEYS}, **m['ability_detail']}
                    for m in game['actual_games']]
        expected.sort(key=lambda m:m['match_id'])
        stored = oracle.sql_games(self.c.slot)
        self.assertEqual([{k:g[k] for k in oracle.KEYS + oracle.DETAILS} for g in stored],
                         [{k:g[k] for k in oracle.KEYS + oracle.DETAILS} for g in expected])
        demo_id = self.c.demo_id
        self.c.close()
        for source in ('manual','autosave'):
            c = DemoController(demo_id, _base=self.base)
            try:
                self.assertIsNone(c.view.game)
                before = pin(c.saves)
                # History entry cannot invoke a game writer, even before load.
                with patch.object(c, '_worker', side_effect=AssertionError('writer from history')):
                    session = c.open_history()
                    with demo_read_handles():
                        bridge = session.bridge
                        self.assertEqual([2026], [r['year'] for r in bridge.page['data']['years']])
                        self.assertEqual(8, len(bridge.open_year(2026)['data']['schools']))
                c.close_history()
                self.assertEqual(before, pin(c.saves))
                reloaded = c.execute('load', source=source)
                self.assertEqual(game['actual_games'], reloaded['actual_games'])
                self.assertEqual(before, pin(c.saves))
                self.assertTrue(reloaded['sealed'])
            finally:
                c.close()
        self.assertEqual(masters, oracle.pin(ROOT / 'data'))
        self.assertEqual(338, len(_compatibility(ROOT)))
        moved = self.base.with_name('終了後 rename')
        self.base.rename(moved)
        self.assertTrue(moved.is_dir())

    def test_unknown_slot_sources_overwrite_unsealed_and_double_operation_refused(self):
        for slot in ('foreign','../save',''):
            with self.assertRaises(ValueError): self.c.execute('new', slot_id=slot)
        self.c.execute('new')
        before = oracle.pin(self.c.root)
        for action, args in [('new',{}),('load',{}),('load',{'source':'latest'}),
                             ('load',{'source':'autosave'}),('seal',{})]:
            with self.assertRaises(ValueError): self.c.execute(action, **args)
            self.assertEqual(before, oracle.pin(self.c.root))
        with self.assertRaises(ValueError): self.c.open_history()
        self.assertEqual(before, oracle.pin(self.c.root))
        self.c.busy = True
        with self.assertRaises(ValueError): self.c.execute('day')
        self.c.busy = False
        with self.assertRaises(FileExistsError): DemoController(self.c.demo_id, _base=self.base)
        self.assertEqual(before, oracle.pin(self.c.root))
        self.c.execute('next_match')
        before = oracle.pin(self.c.root)
        with self.assertRaises(ValueError): self.c.execute('load', source='manual')
        self.assertEqual(before, oracle.pin(self.c.root))

    def test_child_failure_and_publication_failure_preserve_selected_save(self):
        self.c.execute('new')
        before = oracle.pin(self.c.root)
        def failed_child(saves, action, source):
            (saves / SLOT / 'manual.json').write_text('broken', encoding='utf-8')
            raise ValueError('simulated failure after staged write')
        with patch.object(self.c, '_worker', side_effect=failed_child):
            with self.assertRaises(ValueError): self.c.execute('day')
        self.assertEqual(before, oracle.pin(self.c.root))
        old_saves = self.c.saves
        selected = pin(old_saves)
        with patch.object(self.c, '_manifest_write', side_effect=OSError('publication failed')):
            with self.assertRaises(OSError): self.c.execute('day')
        self.assertEqual(old_saves, self.c.saves)
        self.assertEqual(selected, pin(old_saves))
        self.assertFalse(self.c.busy)

    def test_corrupt_checkpoint_manifest_history_and_cleanup_refused(self):
        self.finish()
        selected = self.c.slot
        (selected / 'manual.json').write_text('broken', encoding='utf-8')
        before = oracle.pin(self.c.root)
        for operation in (lambda:self.c.execute('load',source='manual'), self.c.open_history):
            with self.assertRaises(ValueError): operation()
            self.assertEqual(before, oracle.pin(self.c.root))
        # Deliberately repin an owned corrupt fixture to reach semantic checks.
        manifest = json.loads((self.c.root / 'demo.json').read_text(encoding='utf-8'))
        self.c._manifest_write({**manifest, 'files':pin(self.c.root / manifest['generation'])})
        before = oracle.pin(self.c.root)
        with self.assertRaises(ValueError): self.c.execute('load',source='manual')
        self.assertEqual(before, oracle.pin(self.c.root))
        with closing(sqlite3.connect(selected / 'historical_matches.sqlite3')) as con:
            con.execute("UPDATE historical_matches SET payload_json='{}'")
            con.commit()
        self.c._manifest_write({**manifest, 'files':pin(self.c.root / manifest['generation'])})
        before = oracle.pin(self.c.root)
        with self.assertRaises(ValueError):
            session = self.c.open_history()
            with demo_read_handles(): session.bridge.open_year(2026)
        self.c.close_history()
        self.assertEqual(before, oracle.pin(self.c.root))
        self.c.close()
        self.c.root.rename(self.c.root.with_name('閉じた破損demo'))

    def test_closed_controller_unknown_demo_and_links_refused(self):
        self.c.close()
        with self.assertRaises(ValueError): self.c.execute('new')
        for demo_id in ('../save','unknown','f'*32):
            with self.assertRaises(ValueError): DemoController(demo_id, _base=self.base)
        if hasattr(Path, 'symlink_to'):
            try:
                linked = self.base / ('a'*32)
                linked.symlink_to(self.c.root, target_is_directory=True)
            except OSError:
                return  # Windows CI may not grant symlink creation privilege.
            with self.assertRaises(ValueError): DemoController('a'*32, _base=self.base)

    def test_nonblocking_child_timeout_exit_and_failure_preserve_selected_save(self):
        self.c.execute('new')
        old = self.c.saves
        before = pin(old)
        operation = self.c.begin('day')
        with self.assertRaises(ValueError): self.c.begin('day')
        operation['deadline'] = 0
        if operation['child'].poll() is None:
            with self.assertRaises(ValueError): self.c.poll()
        else:
            self.c.poll()
        self.assertEqual(before, pin(old))
        self.assertFalse(self.c.busy)
        # Incomplete sealing is rejected by the actual async worker API.
        self.c.begin('seal')
        deadline = time.monotonic()+30
        with self.assertRaises(ValueError):
            while time.monotonic() < deadline:
                result = self.c.poll()
                if result is not None: self.fail('incomplete season accepted')
                time.sleep(0.01)
            self.fail('child did not finish')
        self.assertEqual(before, pin(old))
        self.c.begin('day')
        self.c.close()
        self.assertFalse(self.c.busy)
        self.assertIsNone(self.c._pending)
        self.assertEqual(before, pin(old))
        self.base.rename(self.base.with_name('子処理終了後 rename'))


if __name__ == '__main__':
    unittest.main()
