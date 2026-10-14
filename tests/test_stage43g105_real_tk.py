"""Native mapped result, identity/stats inspection and atomic failure clearing."""
from dataclasses import replace
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from stage43g103_fixture_support import fixture
from stage43g97_acceptance_support import pin
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read
from phase2_engine.joint_team_registration_lab import registration_from_rosters, match_input_from_registration
from phase2_engine.registered_match_driver import simulate_registered_full_a
from phase2_engine.registered_full_a_tk import RegisteredFullATk


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'native Windows Tk or auxiliary display required')
class Stage105NativeTkTests(unittest.TestCase):
    def test_verified_result_identity_stats_failure_and_native_close(self):
        with tempfile.TemporaryDirectory(prefix='stage105-tk-') as temp, retained_handles() as handles:
            slot = Path(temp)
            repo, rosters, _ = fixture(slot)
            reg = registration_from_rosters(repo, rosters)
            match = match_input_from_registration(reg, repo, rosters,
                team1_id=reg.teams[0].team_id, team2_id=reg.teams[1].team_id, opt_in=True)
            result = simulate_registered_full_a(match, reg, repo, rosters)
            before = pin(slot)
            root = tk.Tk()
            errors = []
            root.report_callback_exception = lambda kind, value, trace: errors.append(value)
            try:
                gui = RegisteredFullATk(root)
                gui.show(result, match, reg, repo, rosters)
                root.update()
                self.assertTrue(root.winfo_ismapped())
                self.assertEqual(result, gui.result)
                self.assertIn('8–1', gui.status.cget('text'))
                self.assertEqual(len(result.inning_scores), len(gui.innings.get_children()))
                rows = [(kind, row) for kind, group in (('打撃', result.batter_stats), ('投手', result.pitcher_stats)) for row in group]
                self.assertEqual(len(rows), len(gui.players.get_children()))
                for item, (kind, row) in zip(gui.players.get_children(), rows):
                    gui.players.selection_set(item)
                    root.update()
                    values = gui.players.item(item, 'values')
                    self.assertEqual((row.team_id, row.origin_school_id, row.player_id, kind), values[:4])
                    self.assertIn('hits' if kind == '打撃' else 'outs_recorded', values[4])
                with self.assertRaises(ValueError):
                    gui.show(replace(result, team1_score=100), match, reg, repo, rosters)
                root.update()
                self.assertIsNone(gui.result)
                self.assertFalse(gui.players.get_children())
                self.assertFalse(gui.innings.get_children())
                self.assertIn('拒否', gui.status.cget('text'))
                gui.show(result, match, reg, repo, rosters)
                root.update()
                self.assertFalse(errors)
                assert_closed(self, handles)
                rename_and_read(self, slot)
            finally:
                root.destroy()
            assert_closed(self, handles)
            rename_and_read(self, slot)
            self.assertEqual(before, pin(slot))
