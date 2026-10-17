"""Saved SQL source, actual2027 game, independent event/identity/history oracles."""
from contextlib import closing
from dataclasses import replace, asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter
import unittest
from unittest.mock import patch

from phase2_engine import saved_practice_match as practice
from phase2_engine import yamanashi_annual_rosters as annual
from phase2_engine.registered_match_driver import _run
from phase2_engine.registered_full_a_oracle import event_oracle
from stage43g99_fixture_support import retained_handles, assert_closed
from stage43g114_support import worker

MEASUREMENTS = {}


def pin(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PracticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owners = [tempfile.TemporaryDirectory(prefix='stage114-source-'),
                      tempfile.TemporaryDirectory(prefix='stage114-annual-')]
        for owner in cls.owners:
            cls.addClassCleanup(owner.cleanup)
        began = perf_counter()
        cls.source = annual.SelfCreated2026(cls.owners[0], opt_in=True)
        cls.addClassCleanup(lambda: cls.source.close())
        for _ in range(31):
            cls.source.store.play_next()
        cls.snap, cls.contract = cls.source.verified()
        MEASUREMENTS['saved31'] = dict(seconds=perf_counter()-began, matches=31, schools=33,
            registered_players=640, permanent_players=660, bytes=cls.source.store.db_path.stat().st_size)
        began = perf_counter()
        cls.lab = annual.AnnualRosterLab(cls.source, cls.owners[1], opt_in=True)
        cls.addClassCleanup(lambda: cls.lab.close())
        state = cls.lab.advance()
        assert state['accepted']
        MEASUREMENTS['saved2027'] = dict(seconds=perf_counter()-began, accepted=True, schools=33,
            active=660, returning=396, graduated=264, newcomers=264, permanent_identities=924,
            bytes=cls.lab.db_path.stat().st_size)
        cls.source_pin = cls.source._evidence()
        cls.annual_pin = pin(cls.lab.db_path)
        began = perf_counter()
        cls.match = practice.practice_input(cls.lab)
        cls.game = practice.simulate_practice(cls.match, cls.lab)
        MEASUREMENTS['input_and_simulation_seconds'] = perf_counter()-began

    def setUp(self):
        self.owner = tempfile.TemporaryDirectory(prefix='stage114-practice-')
        self.addCleanup(self.owner.cleanup)
        self.store = practice.PracticeStore(self.lab, self.owner, opt_in=True)
        self.addCleanup(lambda: self.store.close())

    def tearDown(self):
        self.assertEqual(self.source_pin, self.source._evidence())
        self.assertEqual(self.annual_pin, pin(self.lab.db_path))

    def test_real_game_sql_identity_event_score_individual_history_and_restart(self):
        began = perf_counter()
        authority = practice.saved_authority(self.lab)
        # The direct SQL decode must remain necessary even when browse is unavailable.
        with patch.object(self.lab, 'browse', side_effect=AssertionError('not saved JSON authority')):
            self.assertEqual(self.match, practice.practice_input(self.lab))
        with closing(sqlite3.connect(self.lab.db_path.as_uri()+'?mode=ro',uri=True)) as con:
            saved = {sid:json.loads(raw) for sid,raw in con.execute(
                'SELECT school_id,payload_json FROM career_school_rosters WHERE year=2027')}
        self.assertEqual(saved, {r.school_id:r.to_dict() for r in authority[1]})
        old = {p.player_id:p for r in self.snap.rosters for p in r.players}
        current = {p.player_id:p for r in authority[1] for p in r.players}
        graduated = {pid for pid,p in old.items() if p.academic_year==3}
        self.assertEqual(264,len(graduated));self.assertFalse(graduated & current.keys())
        for pid,p in current.items():
            if pid in old:
                self.assertEqual({**old[pid].to_dict(),'academic_year':old[pid].academic_year+1},p.to_dict())
            else:
                self.assertEqual((2027,1),(p.entry_year,p.academic_year))
        for team in (self.match.team1,self.match.team2):
            self.assertEqual(20,len(team.players))
            self.assertEqual(1,len({p.origin_school_id for p in team.players}))
            self.assertEqual({p.player_id for p in team.players},
                             {p['player_id'] for p in saved[team.players[0].origin_school_id]['players']})
            self.assertTrue(all(p.snapshot.reference_year==2027 for p in team.players))
        with retained_handles() as handles:
            self.assertTrue(self.store.append(self.match,self.game))
            assert_closed(self,handles)
        oracle = event_oracle(self.game,self.match)
        self.assertEqual(sum(r.plate_appearances for r in self.game.batter_stats),len(self.game.events))
        self.assertEqual(sum(r.runs for r in self.game.batter_stats),sum((self.game.team1_score,self.game.team2_score)))
        self.assertEqual(sum(r.runs_allowed for r in self.game.pitcher_stats),oracle['runs'])
        self.assertEqual(self.game,_run(self.match,practice.SEED))
        before = pin(self.store.db_path)
        view = self.store.snapshot()
        ids = {r.player_id for r in self.game.batter_stats if r.plate_appearances>0}
        self.assertFalse(graduated & ids)
        returning = {pid for pid in ids & old.keys() if view.player(pid)['history'][0]['appearances']}
        fresh = ids-old.keys()
        self.assertTrue(returning);self.assertTrue(fresh)
        for pid in ids:
            person=view.player(pid)
            self.assertEqual(current[pid].school_id,person['origin_school_id'])
            self.assertEqual('returning' if pid in old else 'newcomer',person['transition'])
            self.assertTrue(person['history'][1]['appearances'])
            if pid in fresh:
                self.assertEqual('not_yet_enrolled',person['history'][0]['state'])
                self.assertFalse(person['history'][0]['appearances'])
        for pid in graduated:
            self.assertFalse(view.player(pid)['history'][1]['appearances'])
        for school in saved:
            history=view.school(school)
            self.assertIsNone(history['official_2027_outcomes'])
            self.assertFalse(history['season_start_authorized'])
            self.assertEqual(['fictional_tournament','fictional_practice'],[r['record_kind'] for r in history['history']])
        self.assertEqual(before,pin(self.store.db_path))
        caps=self.lab.capability,self.source.capability,self.store.capability
        self.store.close();self.lab.close();self.source.close()
        try:
            with tempfile.TemporaryDirectory(prefix='stage114-private-') as private:
                report=worker(self.lab,self.store,Path(private))
            self.assertEqual(practice._sha(self.game.to_dict()),report['result_sha256'])
            self.assertEqual(oracle['events'],report['oracle']['events'])
            MEASUREMENTS['restart']=dict(seconds=report['seconds'],different_process=True,seed_replay=True,
                                         oracle=True,readonly_bytes_unchanged=before==pin(self.store.db_path))
        finally:
            type(self).source=annual.SelfCreated2026.resume(caps[1])
            type(self).lab=annual.AnnualRosterLab.resume(caps[0],self.source)
        self.store=practice.PracticeStore.resume(caps[2],self.lab)
        MEASUREMENTS['practice']=dict(seconds=perf_counter()-began,match_id=self.game.match_id,seed=practice.SEED,
            score=[self.game.team1_score,self.game.team2_score],innings=self.game.last_inning,events=len(self.game.events),
            batter_rows=len(self.game.batter_stats),pitcher_rows=len(self.game.pitcher_stats),
            returning_appeared=len(ids & old.keys()),newcomers_appeared=len(fresh),
            two_year_actual_appearances=len(returning),school_ids=[t.players[0].origin_school_id for t in (self.match.team1,self.match.team2)],
            bytes=self.store.db_path.stat().st_size,result_sha256=practice._sha(self.game.to_dict()),
            input_sha256=practice._sha(self.match.to_dict()),oracle=oracle)

    def test_input_seed_scope_id_origin_and_result_tampering_fail_closed(self):
        for changes in (dict(year=2026),dict(year=True),dict(match_seed=practice.SEED+1),dict(record_kind='official'),
                        dict(competition_id='CMP000041'),dict(source_receipt_sha256='bad'),dict(version='unknown')):
            with self.assertRaises(ValueError):practice.simulate_practice(replace(self.match,**changes),self.lab)
        team=self.match.team1
        for changes in (dict(player_id='unknown'),dict(origin_school_id='SCH000001')):
            altered=replace(team.players[0],**changes)
            bad=replace(self.match,team1=replace(team,players=(altered,)+team.players[1:]))
            with self.assertRaises(ValueError):practice.simulate_practice(bad,self.lab)
        for result in (replace(self.game,run_seed=practice.SEED+1),_run(self.match,practice.SEED+1),
                       replace(self.game,team1_score=self.game.team1_score+1),
                       replace(self.game,batter_stats=(replace(self.game.batter_stats[0],hits=99),)+self.game.batter_stats[1:]),
                       replace(self.game,events=(replace(self.game.events[0],batter_origin_school_id='unknown'),)+self.game.events[1:])):
            with self.assertRaises(ValueError):self.store.append(self.match,result)
        self.assertNotEqual(self.game.to_json(),_run(self.match,practice.SEED+1).to_json())
        self.assertFalse(self.store.snapshot().results)

    def test_rollback_lost_ack_idempotence_conflict_and_append_only(self):
        before=pin(self.store.db_path)
        def fail(at):
            if at=='before_commit':raise RuntimeError('injected')
        with self.assertRaises(RuntimeError):self.store.append(self.match,self.game,fault=fail)
        self.assertEqual(before,pin(self.store.db_path))
        def lost(at):
            if at=='after_commit':raise RuntimeError('lost ack')
        with self.assertRaises(RuntimeError):self.store.append(self.match,self.game,fault=lost)
        before=pin(self.store.db_path)
        self.assertFalse(self.store.append(self.match,self.game));self.assertEqual(before,pin(self.store.db_path))
        with closing(sqlite3.connect(self.store.db_path)) as con:
            for table in practice.TABLES:
                for action in ('UPDATE','DELETE'):
                    statement=f'{action} {table}' if action=='DELETE' else f'UPDATE {table} SET '+(
                        'singleton=singleton' if table=='practice_contract' else 'match_id=match_id')
                    if action=='DELETE':statement=f'DELETE FROM {table}'
                    with self.assertRaises(sqlite3.IntegrityError):con.execute(statement)
            con.rollback()
        self.assertEqual(before,pin(self.store.db_path))

    def test_crash_after_commit_restart_and_hot_journal_no_recovery(self):
        caps=self.lab.capability,self.source.capability,self.store.capability
        self.store.close();self.lab.close();self.source.close()
        try:
            with tempfile.TemporaryDirectory(prefix='stage114-private-') as private:
                worker(self.lab,self.store,Path(private),action='crash_after_commit')
                report=worker(self.lab,self.store,Path(private))
                self.assertEqual(1,report['matches'])
        finally:
            type(self).source=annual.SelfCreated2026.resume(caps[1])
            type(self).lab=annual.AnnualRosterLab.resume(caps[0],self.source)
        self.store=practice.PracticeStore.resume(caps[2],self.lab)
        self.store.close()
        owner=tempfile.TemporaryDirectory(prefix='stage114-hot-');self.addCleanup(owner.cleanup)
        self.store=practice.PracticeStore(self.lab,owner,opt_in=True)
        cap=self.store.capability
        self.store.close();self.lab.close();self.source.close()
        try:
            with tempfile.TemporaryDirectory(prefix='stage114-private-') as private:
                worker(self.lab,self.store,Path(private),action='crash_before_commit')
        finally:
            type(self).source=annual.SelfCreated2026.resume(caps[1])
            type(self).lab=annual.AnnualRosterLab.resume(caps[0],self.source)
        journal=Path(str(self.store.db_path)+'-journal')
        self.assertGreater(journal.stat().st_size,512)
        before={p.name:pin(p) for p in self.store.db_path.parent.iterdir()}
        with patch.object(sqlite3,'connect',side_effect=AssertionError('no automatic recovery')):
            with self.assertRaises(ValueError):practice.PracticeStore.resume(cap,self.lab)
        self.assertEqual(before,{p.name:pin(p) for p in self.store.db_path.parent.iterdir()})

    def test_links_sidecars_replacement_lock_and_native_handle_close(self):
        for suffix in ('-journal','-wal','-shm'):
            side=Path(str(self.store.db_path)+suffix);side.write_bytes(b'foreign')
            try:
                with patch.object(sqlite3,'connect',side_effect=AssertionError('no SQL before guard')):
                    with self.assertRaises(ValueError):self.store._guard()
            finally:side.unlink()
        cap=self.store.capability;self.store.close()
        with tempfile.TemporaryDirectory(prefix='stage114-alias-') as outside:
            alias=Path(outside)/'junction'
            if os.name=='nt':
                import subprocess
                subprocess.run(['cmd','/c','mklink','/J',str(alias),str(self.store.db_path.parent)],
                               check=True,capture_output=True)
            else:
                alias.symlink_to(self.store.db_path.parent,target_is_directory=True)
            try:
                with patch.object(sqlite3,'connect',side_effect=AssertionError('no reparse SQL')):
                    with self.assertRaises(ValueError):
                        practice.PracticeStore.resume(replace(cap,root=str(alias)),self.lab)
            finally:
                if os.name=='nt':alias.rmdir()
                else:alias.unlink()
        with tempfile.TemporaryDirectory(prefix='stage114-link-') as outside:
            link=Path(outside)/'linked';os.link(self.store.db_path,link)
            try:
                with patch.object(sqlite3,'connect',side_effect=AssertionError('no linked SQL')):
                    with self.assertRaises(ValueError):practice.PracticeStore.resume(cap,self.lab)
            finally:link.unlink()
        self.store=practice.PracticeStore.resume(cap,self.lab)
        with self.assertRaises(ValueError):practice.PracticeStore.resume(cap,self.lab)
        with closing(sqlite3.connect(self.store.db_path)) as con:
            con.execute('BEGIN EXCLUSIVE')
            with self.assertRaises(sqlite3.OperationalError):self.store.snapshot()
            con.rollback()
        with retained_handles() as handles:
            self.store.play();self.store.snapshot();assert_closed(self,handles)
        cap=self.store.capability;self.store.close()
        moved=self.store.db_path.with_suffix('.released');self.store.db_path.rename(moved);moved.rename(self.store.db_path)
        self.store=practice.PracticeStore.resume(cap,self.lab)
        self.store.close()
        original=self.store.db_path.read_bytes()
        with tempfile.TemporaryDirectory(prefix='stage114-retain-') as outside:
            retained=Path(outside)/'retained';self.store.db_path.rename(retained)
            self.store.db_path.write_bytes(original)
            with patch.object(sqlite3,'connect',side_effect=AssertionError('no replaced SQL')):
                with self.assertRaises(ValueError):practice.PracticeStore.resume(cap,self.lab)

    def test_roster_only_unaccepted_foreign_source_and_unknown_history_refused(self):
        from phase2_engine.saved_school_roster_source import SavedSchoolRosterSource
        with tempfile.TemporaryDirectory(prefix='stage114-unused-') as owner:
            for source in (object(),SavedSchoolRosterSource.__new__(SavedSchoolRosterSource)):
                with self.assertRaises(ValueError):practice.PracticeStore(source,owner,opt_in=True)
            with self.assertRaises(ValueError):practice.PracticeStore(self.lab,owner)
            self.assertFalse(list(Path(owner).iterdir()))
        owner=tempfile.TemporaryDirectory(prefix='stage114-partial-');self.addCleanup(owner.cleanup)
        incomplete=annual.AnnualRosterLab(self.source,owner,opt_in=True)
        try:
            with self.assertRaises(ValueError):practice.practice_input(incomplete)
        finally:incomplete.close()
        owner=tempfile.TemporaryDirectory(prefix='stage114-other-');self.addCleanup(owner.cleanup)
        other=annual.AnnualRosterLab(self.source,owner,opt_in=True)
        try:
            other.advance()
            with self.assertRaises(ValueError):self.store._audit(practice.saved_authority(other))
        finally:other.close()
        view=self.store.snapshot()
        with self.assertRaises(ValueError):view.school('unknown')
        with self.assertRaises(ValueError):view.player('unknown')
        for year in (True,2028,'2027'):
            with self.assertRaises(ValueError):view._games(year)

    def test_schema_index_result_and_source_sql_tampering_rejected_readonly(self):
        self.store.play()
        original=self.store.db_path.read_bytes()
        for statement in ('CREATE TABLE unexpected(x)',
                          'INSERT INTO practice_players VALUES ("unknown","unknown",2027,"fictional_practice","'+practice.MATCH+'")',
                          'DELETE FROM practice_schools'):
            with closing(sqlite3.connect(self.store.db_path)) as con,con:
                if statement.startswith('DELETE'):
                    con.execute('DROP TRIGGER practice_practice_schools_delete')
                con.execute(statement)
            before=pin(self.store.db_path)
            with self.assertRaises(ValueError):self.store.snapshot()
            self.assertEqual(before,pin(self.store.db_path))
            self.store.db_path.write_bytes(original)  # only this newly created destructive fixture
        raw=self.lab.db_path.read_bytes()
        try:
            with closing(sqlite3.connect(self.lab.db_path)) as con,con:
                con.execute('DROP TRIGGER annual_career_school_rosters_no_update')
                con.execute('UPDATE career_school_rosters SET payload_json="{}" WHERE year=2027')
            before=pin(self.lab.db_path)
            with self.assertRaises(ValueError):self.store.snapshot()
            self.assertEqual(before,pin(self.lab.db_path))
        finally:self.lab.db_path.write_bytes(raw)  # self-created fault fixture only
