"""Native mapped 32-team/31-game school/player totals and failure clearing."""
import ast
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import tkinter as tk
import unittest

from phase2_engine.yamanashi_tournament_store import OwnedTournamentStore, TournamentLabReader
from phase2_engine.yamanashi_tournament_tk import YamanashiTournamentTk
from stage43g108_process_support import run_phase
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'native Windows Tk or auxiliary display required')
class Stage108NativeTkTests(unittest.TestCase):
    def test_native_two_processes_two_windows_all_teams_schools_players_totals_and_refusal(self):
        owner=tempfile.TemporaryDirectory(prefix='stage108-tk-')
        self.addCleanup(owner.cleanup)
        store=OwnedTournamentStore(owner,opt_in=True)
        run_phase(store.resume_capability(),0,16)
        # Incomplete saved tournament must never retain an earlier screen.
        incomplete=Path(owner.name)/'incomplete.sqlite3'
        incomplete.write_bytes(store.db_path.read_bytes())
        run_phase(store.resume_capability(),16,31)
        snapshot=TournamentLabReader(store.db_path).tournament()
        before=store.db_path.read_bytes()
        _,history=TournamentLabReader(store.db_path).history()
        with retained_handles() as handles:
            for repeat in range(1):
                root=tk.Tk(); errors=[]
                root.geometry('1280x900')
                root.report_callback_exception=lambda kind,value,trace:errors.append(value)
                try:
                    gui=YamanashiTournamentTk(root)
                    gui.open_saved(store.db_path)
                    root.update()
                    self.assertTrue(root.winfo_ismapped())
                    self.assertEqual(32,len(gui.tables['ranks'].get_children()))
                    gui.tables['ranks'].yview_moveto(1);root.update()
                    self.assertGreater(gui.tables['ranks'].yview()[0],0)
                    self.assertEqual(31,len(gui.tables['ledger'].get_children()))
                    self.assertIn('学校単独順位ではありません',gui.status.cget('text'))
                    for team in snapshot.registration.teams:
                        gui.pickers['team'].set(team.team_id)
                        gui.pickers['team'].event_generate('<<ComboboxSelected>>');root.update()
                        matches=[r for r in snapshot.results if team.team_id in (r.team1_id,r.team2_id)]
                        self.assertEqual(tuple(r.match_id for r in matches),gui.pickers['match']['values'])
                        for game in matches:
                            gui.pickers['match'].set(game.match_id)
                            gui.pickers['match'].event_generate('<<ComboboxSelected>>');root.update()
                            self.assertEqual(game,gui.result)
                            self.assertEqual(len(game.inning_scores),len(gui.tables['innings'].get_children()))
                            score=gui.tables['scores'].item(gui.tables['scores'].get_children()[0],'values')
                            self.assertEqual((game.match_id,game.team1_id,str(game.team1_score),game.team2_id,str(game.team2_score)),score)
                        for sid in team.school_ids:
                            gui.pickers['school'].set(sid)
                            gui.pickers['school'].event_generate('<<ComboboxSelected>>');root.update()
                            people=[p for p in team.players if p.origin_school_id==sid]
                            self.assertEqual(len(people),len(gui.tables['members'].get_children()))
                            # Select an actual batter; bench behavior is covered in the reader gate.
                            p=next(p for p in people if any(r.player_id==p.player_id for g in matches for r in g.batter_stats))
                            gui.pickers['player'].set(p.player_id)
                            gui.pickers['player'].event_generate('<<ComboboxSelected>>');root.update()
                            member=gui.tables['members'].item(gui.tables['members'].get_children()[0],'values')
                            self.assertEqual((team.team_id,sid,p.player_id,str(p.team_slot)),member)
                            values=[gui.tables['stats'].item(i,'values') for i in gui.tables['stats'].get_children()]
                            actual=[v for v in values if v[0]!='累計']
                            expected=[r for g in snapshot.results for r in g.batter_stats+g.pitcher_stats if r.player_id==p.player_id]
                            self.assertEqual(len(expected),len(actual))
                            totals=history[p.player_id]['totals']
                            for row in (v for v in values if v[0]=='累計'):
                                self.assertEqual(totals[row[4]],ast.literal_eval(row[5]))
                    # Joint unregistered players remain selectable with no invented appearances.
                    joint=next(t for t in snapshot.registration.teams if len(t.school_ids)==2)
                    gui.pickers['team'].set(joint.team_id);gui._team()
                    registered={p.player_id for p in joint.players}
                    bench=next(p for ros in snapshot.rosters if ros.school_id in joint.school_ids
                               for p in ros.players if p.player_id not in registered)
                    gui.pickers['player'].set(bench.player_id);gui._player();root.update()
                    self.assertFalse(gui.tables['stats'].get_children())
                    row=gui.tables['members'].item(gui.tables['members'].get_children()[0],'values')
                    self.assertEqual('未登録',row[3])
                    assert_closed(self,handles)
                    with self.assertRaises(ValueError):gui.open_saved(incomplete)
                    self.assertIsNone(gui.snapshot)
                    self.assertTrue(all(not t.get_children() for t in gui.tables.values()))
                    self.assertTrue(all(not p['values'] for p in gui.pickers.values()))
                    gui.open_saved(store.db_path)
                    broken=Path(owner.name)/'broken.sqlite3';broken.write_bytes(b'corrupt')
                    with self.assertRaises(sqlite3.DatabaseError):gui.open_saved(broken)
                    self.assertIsNone(gui.result)
                    self.assertTrue(all(not t.get_children() for t in gui.tables.values()))
                    broken.unlink()  # The subsequent SQLite integrity sweep covers valid fixtures.
                    gui.open_saved(store.db_path)
                    # Failure during navigation clears a previously complete screen.
                    hidden=store.db_path.with_suffix('.hidden')
                    store.db_path.rename(hidden)
                    try:
                        with self.assertRaises(sqlite3.OperationalError):gui._checked()
                        self.assertTrue(all(not t.get_children() for t in gui.tables.values()))
                    finally:hidden.rename(store.db_path)
                    self.assertFalse(errors)
                    assert_closed(self,handles)
                finally:root.destroy()
                rename_and_read(self,Path(owner.name))
        self.assertEqual(before,store.db_path.read_bytes())
