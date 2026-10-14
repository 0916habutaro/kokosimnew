"""Native Windows mapped team -> origin school -> permanent player inspection."""
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
from phase2_engine.joint_team_registration_lab import registration_from_rosters, CompetitionRegistration
from phase2_engine.joint_team_registration_tk import JointRegistrationTk
from stage43g103_fixture_support import fixture
from stage43g97_acceptance_support import pin
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read


@unittest.skipUnless(sys.platform=='win32' or os.environ.get('DISPLAY'),
                    'native Windows Tk or auxiliary display required')
class Stage43G104RealTkTests(unittest.TestCase):
    def test_mapped_selection_failure_closing_sqlite_rename_reopen(self):
        with tempfile.TemporaryDirectory(prefix='stage104-tk-') as temp, retained_handles() as handles:
            slot=Path(temp)
            repo,rosters,_=fixture(slot)
            model=registration_from_rosters(repo,rosters)
            before=pin(slot)
            root=tk.Tk()
            errors=[]
            root.report_callback_exception=lambda kind,value,trace:errors.append(value)
            try:
                gui=JointRegistrationTk(root,model,repo,rosters)
                root.update()
                self.assertTrue(root.winfo_ismapped())
                self.assertEqual(3,len(gui.teams.get_children()))
                for team in model.teams:
                    gui.teams.selection_set(team.team_id)
                    gui.teams.event_generate('<<TreeviewSelect>>')
                    root.update()
                    self.assertEqual(model.preview(team.team_id),gui.page)
                    self.assertEqual(20,len(gui.players.get_children()))
                    self.assertEqual(team.school_ids,gui.schools.get_children())
                    for sid in team.school_ids:
                        gui.schools.selection_set(sid)
                        gui.schools.event_generate('<<TreeviewSelect>>')
                        root.update()
                        rows=[r for r in team.players if r.origin_school_id==sid]
                        self.assertEqual(len(rows),len(gui.players.get_children()))
                        for r in rows:
                            self.assertEqual(tuple(map(str,(r.team_slot,sid,r.player_id,r.player.academic_year,
                                r.player.entry_year,r.player.primary_position))),
                                tuple(map(str,gui.players.item(r.player_id,'values'))))
                    assert_closed(self,handles)
                    rename_and_read(self,slot)
                with patch.object(CompetitionRegistration,'preview',side_effect=ValueError('refused')):
                    gui.teams.event_generate('<<TreeviewSelect>>')
                    root.update()
                    self.assertIsNone(gui.page)
                    self.assertEqual((),gui.players.get_children())
                    self.assertIn('拒否',gui.status.cget('text'))
                gui.teams.event_generate('<<TreeviewSelect>>')
                root.update()
                self.assertEqual(20,len(gui.players.get_children()))
                self.assertFalse(errors)
            finally:
                root.destroy()
            assert_closed(self,handles)
            rename_and_read(self,slot)
            self.assertEqual(before,pin(slot))
