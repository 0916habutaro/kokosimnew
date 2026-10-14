"""Native mapped saved-result navigation; separate-process restart and close."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tkinter as tk
import unittest
from phase2_engine.registered_full_a_lab_store import RegisteredFullALabStore, fixed_authorities
from phase2_engine.joint_team_registration_lab import match_input_from_registration
from phase2_engine.registered_match_driver import simulate_registered_full_a
from phase2_engine.registered_saved_full_a_tk import RegisteredSavedFullATk
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform=='win32' or os.environ.get('DISPLAY'),'native Windows Tk or auxiliary display required')
class Stage106NativeTkTests(unittest.TestCase):
    def test_saved_team_school_player_clear_restart_close_rename_reopen(self):
        owner=tempfile.TemporaryDirectory(prefix='stage106-tk-')
        self.addCleanup(owner.cleanup)
        repo,rosters,reg=fixed_authorities()
        match=match_input_from_registration(reg,repo,rosters,team1_id=reg.teams[0].team_id,
            team2_id=reg.teams[1].team_id,opt_in=True)
        result=simulate_registered_full_a(match,reg,repo,rosters)
        store=RegisteredFullALabStore(owner)
        with retained_handles() as handles:
            store.append(result,match,reg,repo,rosters)
            before=store.db_path.read_bytes()
            # Exit the generation process before two fresh native windows read it.
            saved=Path(owner.name)/'separate-process.sqlite3'
            child=subprocess.run([sys.executable,str(ROOT/'tests/stage43g106_restart_worker.py'),
                '--generate-copy',str(saved)],check=True,capture_output=True,text=True,timeout=60)
            self.assertIn('"score": [8, 1]',child.stdout)
            for path in (store.db_path,saved):
                root=tk.Tk();errors=[]
                root.report_callback_exception=lambda kind,value,trace:errors.append(value)
                try:
                    gui=RegisteredSavedFullATk(root)
                    gui.open_saved(path,result.year,result.competition_id,result.match_id)
                    root.update()
                    self.assertTrue(root.winfo_ismapped())
                    self.assertEqual(result,gui.result)
                    self.assertIn('保存済み',gui.status.cget('text'))
                    self.assertIn('8–1',gui.status.cget('text'))
                    self.assertEqual(18,len(gui.innings.get_children()))
                    self.assertEqual(20,len(gui.members.get_children()))
                    for team in reg.teams[:2]:
                        gui.team_picker.set(team.team_id)
                        gui.team_picker.event_generate('<<ComboboxSelected>>');root.update()
                        for sid in team.school_ids:
                            gui.school_picker.set(sid)
                            gui.school_picker.event_generate('<<ComboboxSelected>>');root.update()
                            expected=[p for p in team.players if p.origin_school_id==sid]
                            self.assertEqual(len(expected),len(gui.members.get_children()))
                            for p in expected:
                                gui.player_picker.set(p.player_id)
                                gui.player_picker.event_generate('<<ComboboxSelected>>');root.update()
                                member=gui.members.item(gui.members.get_children()[0],'values')
                                self.assertEqual((team.team_id,team.label,sid,p.player_id,str(p.team_slot)),member)
                                stats=[r for r in result.batter_stats+result.pitcher_stats if r.player_id==p.player_id]
                                self.assertEqual(len(stats),len(gui.players.get_children()))
                                for item,row in zip(gui.players.get_children(),stats):
                                    values=gui.players.item(item,'values')
                                    self.assertEqual((team.team_id,sid,p.player_id),values[:3])
                                    self.assertIn('hits' if hasattr(row,'at_bats') else 'outs_recorded',values[4])
                    with self.assertRaises(ValueError):
                        gui.open_saved(path,result.year,result.competition_id,'unknown')
                    self.assertIsNone(gui.result)
                    for tree in (gui.innings,gui.players,gui.members):self.assertFalse(tree.get_children())
                    self.assertFalse(gui.team_picker['values'])
                    broken=Path(owner.name)/'broken.sqlite3';broken.write_bytes(b'corrupt')
                    with self.assertRaises(Exception):
                        gui.open_saved(broken,result.year,result.competition_id,result.match_id)
                    self.assertIsNone(gui.result)
                    broken.unlink()
                    gui.open_saved(path,result.year,result.competition_id,result.match_id)
                    root.update();self.assertFalse(errors)
                    assert_closed(self,handles)
                finally:root.destroy()
                moved=path.with_suffix('.closed');path.rename(moved);moved.rename(path)
            assert_closed(self,handles);rename_and_read(self,Path(owner.name))
            self.assertEqual(before,store.db_path.read_bytes())
            self.assertEqual(before,saved.read_bytes())
