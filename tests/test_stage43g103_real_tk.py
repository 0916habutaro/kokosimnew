"""Native mapped preview retains original IDs and releases all SQLite handles."""
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from phase2_engine.joint_team_fixture import ENTRIES
from phase2_engine.joint_team_fixture_tk import JointTeamFixtureTk
from stage43g103_fixture_support import fixture
from stage43g97_acceptance_support import pin
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read


@unittest.skipUnless(sys.platform=='win32' or os.environ.get('DISPLAY'),'native Windows Tk or auxiliary display required')
class Stage43G103RealTkTests(unittest.TestCase):
    def test_mapped_three_teams_original_school_players_readonly_native_close(self):
        with tempfile.TemporaryDirectory(prefix='stage103-tk-') as temp:
            slot = Path(temp)
            with retained_handles() as handles:
                repo, rosters, model = fixture(slot)
                before = pin(slot)
                root = tk.Tk()
                errors = []
                root.report_callback_exception = lambda kind,value,trace: errors.append(value)
                try:
                    gui = JointTeamFixtureTk(root,model)
                    root.update()
                    self.assertTrue(root.winfo_ismapped())
                    self.assertEqual(3,len(gui.teams.get_children()))
                    for entry in ENTRIES:
                        gui.teams.selection_set(entry.team_id)
                        gui.teams.event_generate('<<TreeviewSelect>>')
                        root.update()
                        self.assertEqual(model.preview(entry.team_id),gui.page)
                        self.assertEqual(20,len(gui.players.get_children()))
                        for p in gui.page['players']:
                            self.assertEqual((p['school_id'],p['player_id'],str(p['academic_year']),str(p['entry_year'])),
                                tuple(str(v) for v in gui.players.item(p['player_id'],'values')))
                        assert_closed(self,handles)
                        rename_and_read(self,slot)
                    self.assertFalse(errors)
                finally:
                    root.destroy()
                assert_closed(self,handles)
                rename_and_read(self,slot)
                self.assertEqual(before,pin(slot))
