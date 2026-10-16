"""Saved SQL authority, independent JSON oracle, hard exits and fail-closed gates."""
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter
import tracemalloc
import unittest
from unittest.mock import patch

from phase2_engine.repository import DataRepository
from phase2_engine.cross_prefecture_roster_selection import audit_selection
from phase2_engine.saved_school_roster_source import SavedSchoolRosterSource, SavedSchoolRosterTrial, competition_start_gate
from phase2_engine.school_roster_trial import MasterRosterSandbox
from phase2_engine.career_roster_archive import CareerRosterArchive
from stage43g99_fixture_support import retained_handles, assert_closed
from stage43g113_support import ROOT, SEED, worker, peak_rss_bytes

MEASUREMENTS = {}


def pin(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sql(path, query, args=()):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as con:
        return con.execute(query, args).fetchall()


class SavedRosterTests(unittest.TestCase):
    def setUp(self):
        self.repo = DataRepository(ROOT / 'data')
        self.audit = audit_selection(self.repo)
        self.ids = tuple(sorted(r['school_id'] for r in self.audit['schools']))
        self.owners = [tempfile.TemporaryDirectory(prefix='stage113-owned-') for _ in range(2)]
        for owner in self.owners:
            self.addCleanup(owner.cleanup)
        began = perf_counter();tracemalloc.start()
        self.source = SavedSchoolRosterSource(self.repo, self.ids, self.owners[0], year=2026, career_seed=SEED, opt_in=True)
        self.addCleanup(lambda: self.source.close())
        MEASUREMENTS.setdefault('initial_source_seconds', round(perf_counter()-began, 6))
        MEASUREMENTS.setdefault('initial_source_traced_peak_bytes',tracemalloc.get_traced_memory()[1])
        MEASUREMENTS.setdefault('initial_source_process_peak_rss_bytes',peak_rss_bytes())
        MEASUREMENTS.setdefault('initial_source_database_bytes',self.source.db_path.stat().st_size)
        tracemalloc.stop()
        self.source_sha = pin(self.source.db_path)
        began = perf_counter();tracemalloc.start()
        self.lab = SavedSchoolRosterTrial(self.source, self.owners[1], next_year=2027, career_seed=SEED, opt_in=True)
        self.addCleanup(lambda: self.lab.close())
        MEASUREMENTS.setdefault('target_initial_copy_seconds', round(perf_counter()-began, 6))
        MEASUREMENTS.setdefault('target_initial_copy_traced_peak_bytes',tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()

    def test_master_saved_authority_and_strict_opt_in(self):
        self.assertEqual({'19':33,'20':33,'22':34}, self.audit['counts'])
        self.assertEqual(200, self.audit['membership_count'])
        self.assertEqual(106, len(self.audit['master_csv_bytes_sha256']))
        with patch('game_core.players.PlayerRosterGenerator.generate_for_school_id', side_effect=AssertionError('no regeneration')):
            self.assertEqual(100, len(self.source.snapshot()[0]))
        with tempfile.TemporaryDirectory(prefix='stage113-unused-') as owner:
            with self.assertRaises(ValueError):
                SavedSchoolRosterSource(self.repo, self.ids, owner, year=2026, career_seed=SEED)
            with self.assertRaises(ValueError):
                SavedSchoolRosterTrial(MasterRosterSandbox(self.repo,self.ids,year=2026,career_seed=SEED), owner,
                    next_year=2027,career_seed=SEED,opt_in=True)
            self.assertEqual([], list(Path(owner).iterdir()))
        MEASUREMENTS['master_audit'] = {k:v for k,v in self.audit.items() if k != 'schools'}

    def test_full100_sql_json_lineage_profiles_history_and_measurement(self):
        began = perf_counter(); tracemalloc.start()
        try:
            with retained_handles() as handles:
                state = self.lab.advance(career_seed=SEED)
                assert_closed(self, handles)
            advance_elapsed=perf_counter()-began
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertTrue(state['accepted'])
        self.assertEqual((800,1200,800,2000), tuple(state['summary'][k] for k in ('graduated','returning','newcomers','active')))
        rows = sql(self.lab.db_path, 'SELECT year,school_id,payload_json FROM career_school_rosters ORDER BY year,school_id')
        by_year = {year:{sid:json.loads(raw) for y,sid,raw in rows if y==year} for year in (2026,2027)}
        original = {sid:json.loads(raw) for sid,raw in sql(self.source.db_path,'SELECT school_id,payload_json FROM career_school_rosters')}
        self.assertEqual(original, by_year[2026])
        identities = {pid:(sid,entry,json.loads(raw)) for pid,sid,entry,raw in sql(self.lab.db_path,
            'SELECT player_id,school_id,entry_year,identity_json FROM career_player_identities')}
        self.assertEqual(2800,len(identities))
        all_old, all_new = set(), set()
        for sid in self.ids:
            old = {p['player_id']:p for p in by_year[2026][sid]['players']}
            new = {p['player_id']:p for p in by_year[2027][sid]['players']}
            grads = {pid for pid,p in old.items() if p['academic_year']==3}
            self.assertEqual(8,len(grads)); self.assertFalse(grads & new.keys())
            self.assertEqual(12,len(old.keys() & new.keys())); self.assertEqual(8,len(new.keys()-old.keys()))
            for pid,p in new.items():
                if pid in old:
                    self.assertEqual(old[pid]['academic_year']+1,p['academic_year'])
                    self.assertEqual({k:v for k,v in old[pid].items() if k!='academic_year'},
                                     {k:v for k,v in p.items() if k!='academic_year'})
                else:
                    self.assertEqual((1,2027,sid),(p['academic_year'],p['entry_year'],p['school_id']))
            for p in (*old.values(),*new.values()):
                profile = {k:v for k,v in p.items() if k!='academic_year'}
                self.assertEqual((sid,p['entry_year'],profile),identities[p['player_id']])
            self.assertFalse(all_old & old.keys()); self.assertFalse(all_new & new.keys())
            all_old.update(old); all_new.update(new)
        self.assertEqual(800,len(all_new-all_old)); self.assertEqual(1200,len(all_new&all_old))
        self.assertEqual(self.source_sha,pin(self.source.db_path))
        mark=perf_counter(); before=pin(self.lab.db_path);tracemalloc.start()
        view=self.lab.browse()
        archive=CareerRosterArchive(self.lab.db_path)
        for pid in sorted(identities):
            history=archive.player_history(pid)
            self.assertTrue(history)
            self.assertEqual(identities[pid][0],history[0]['school_id'])
        with closing(sqlite3.connect(self.lab.db_path)) as con:
            plan=con.execute('EXPLAIN QUERY PLAN SELECT year FROM career_school_rosters WHERE school_id=? AND year BETWEEN ? AND ?',
                             (self.ids[0],2026,2027)).fetchall()
        self.assertTrue(any('INDEX' in str(row) for row in plan))
        self.assertEqual(before,pin(self.lab.db_path))
        MEASUREMENTS['full100']=dict(advance_accept_seconds=round(advance_elapsed,6), traced_peak_bytes=peak,
            source_bytes=self.source.db_path.stat().st_size,target_bytes=self.lab.db_path.stat().st_size,
            process_peak_rss_bytes=peak_rss_bytes(),
            browse_all2800_history_seconds=round(perf_counter()-mark,6),
            browse_traced_peak_bytes=tracemalloc.get_traced_memory()[1],query_plan=plan,
            schools=100,identities=2800,graduated=800,returning=1200,newcomers=800,active=2000)
        tracemalloc.stop()

    def test_hard_exit_after_school1_50_100_then_other_process_resume(self):
        durations={}
        for count in (1,50,100):
            with self.subTest(count=count), tempfile.TemporaryDirectory(prefix='stage113-private-') as private:
                # Fresh target per scenario, reusing immutable source only.
                if count != 1:
                    self.lab.close()
                    owner=tempfile.TemporaryDirectory(prefix='stage113-target-');self.addCleanup(owner.cleanup)
                    self.lab=SavedSchoolRosterTrial(self.source,owner,next_year=2027,career_seed=SEED,opt_in=True)
                cap,scap=self.lab.capability,self.source.capability
                self.lab.close();self.source.close()
                began=perf_counter();worker(self.source,self.lab,Path(private),at='school_committed',count=count)
                self.source=SavedSchoolRosterSource.resume(scap,self.repo)
                self.lab=SavedSchoolRosterTrial.resume(cap,self.source)
                self.assertEqual(count,self.lab.status()['generated_schools'])
                with self.assertRaises(ValueError):self.lab.browse()
                self.lab.close();self.source.close()
                resumed=worker(self.source,self.lab,Path(private))
                self.assertTrue(resumed['accepted'])
                MEASUREMENTS.setdefault('resume_process_metrics',{})[str(count)]=resumed['resume_metrics']
                self.source=SavedSchoolRosterSource.resume(scap,self.repo)
                self.lab=SavedSchoolRosterTrial.resume(cap,self.source)
                durations[str(count)]=round(perf_counter()-began,6)
                before=pin(self.lab.db_path)
                self.lab.advance(career_seed=SEED)
                self.assertEqual(before,pin(self.lab.db_path))
                self.assertEqual(self.source_sha,pin(self.source.db_path))
        MEASUREMENTS['hard_exit_and_resume_seconds']=durations

    def test_acceptance_commit_before_exception_after_process_exit_and_hot_journal(self):
        def fail(at,sid):
            if at=='before_acceptance_commit':raise RuntimeError('injected')
        with self.assertRaises(RuntimeError):self.lab.advance(career_seed=SEED,fault=fail)
        self.assertFalse(self.lab.status()['accepted'])
        self.assertEqual(100,self.lab.status()['generated_schools'])
        cap,scap=self.lab.capability,self.source.capability
        self.lab.close();self.source.close()
        with tempfile.TemporaryDirectory(prefix='stage113-private-') as private:
            worker(self.source,self.lab,Path(private),at='after_acceptance_commit')
        self.source=SavedSchoolRosterSource.resume(scap,self.repo)
        self.lab=SavedSchoolRosterTrial.resume(cap,self.source)
        self.assertTrue(self.lab.status()['accepted'])
        self.lab.close()
        owner=tempfile.TemporaryDirectory(prefix='stage113-dirty-');self.addCleanup(owner.cleanup)
        self.lab=SavedSchoolRosterTrial(self.source,owner,next_year=2027,career_seed=SEED,opt_in=True)
        cap=self.lab.capability; self.lab.close();self.source.close()
        with tempfile.TemporaryDirectory(prefix='stage113-private-') as private:
            worker(self.source,self.lab,Path(private),at='before_acceptance_commit')
        self.source=SavedSchoolRosterSource.resume(scap,self.repo)
        journal=Path(str(self.lab.db_path)+'-journal')
        self.assertGreater(journal.stat().st_size,512)
        with patch.object(sqlite3,'connect',side_effect=AssertionError('no implicit recovery')):
            with self.assertRaises(ValueError):SavedSchoolRosterTrial.resume(cap,self.source)

    def test_wrong_seed_recipe_source_extra_missing_school_rejected(self):
        before=pin(self.lab.db_path)
        for kwargs in (dict(career_seed=SEED+1),dict(career_seed=SEED,recipe='unknown')):
            with self.assertRaises(ValueError):self.lab.advance(**kwargs)
        cap=self.lab.capability;self.lab.close()
        for ids,seed in ((self.ids[:-1],SEED),(self.ids+('SCH001669',),SEED),(self.ids,SEED+1),(self.ids,SEED)):
            owner=tempfile.TemporaryDirectory(prefix='stage113-other-source-')
            self.addCleanup(owner.cleanup)
            other=SavedSchoolRosterSource(self.repo,ids,owner,year=2026,career_seed=seed,opt_in=True)
            try:
                if ids==self.ids and seed==SEED:
                    self.assertEqual(self.source_sha,pin(other.db_path))
                with self.assertRaises(ValueError):SavedSchoolRosterTrial.resume(cap,other)
            finally:other.close()
        self.assertEqual(before,pin(self.lab.db_path))
        self.lab=SavedSchoolRosterTrial.resume(cap,self.source)

    def test_files_links_sidecars_source_and_target_replacement_refused_before_sql(self):
        import os
        # Native Windows pins deliberately deny DELETE sharing. Release them
        # before manufacturing a hard link, and test resume before SQL opens.
        for is_source in (True,False):
            obj=self.source if is_source else self.lab
            cap=obj.capability;obj.close()
            with tempfile.TemporaryDirectory(prefix='stage113-link-') as outside:
                linked=Path(outside)/'linked.sqlite3'
                os.link(obj.db_path,linked)
                try:
                    with patch.object(sqlite3,'connect',side_effect=AssertionError('no linked file')):
                        with self.assertRaises(ValueError):
                            if is_source:SavedSchoolRosterSource.resume(cap,self.repo)
                            else:SavedSchoolRosterTrial.resume(cap,self.source)
                finally:linked.unlink()
            if is_source:
                self.source=SavedSchoolRosterSource.resume(cap,self.repo)
                self.lab.source=self.source
            else:
                self.lab=SavedSchoolRosterTrial.resume(cap,self.source)
        for obj in (self.source,self.lab):
            side=obj.db_path.parent/'unexpected-wal';side.write_bytes(b'foreign')
            try:
                with patch.object(sqlite3,'connect',side_effect=AssertionError('no dirty input')):
                    with self.assertRaises(ValueError):obj.snapshot() if obj is self.source else obj.status()
            finally:side.unlink()
            # Close native Windows pins before the deliberate physical swap.
            cap=obj.capability;obj.close()
            original=obj.db_path.with_suffix('.retained');obj.db_path.rename(original)
            obj.db_path.write_bytes(original.read_bytes())
            # Remove extra filename so the file-ID guard itself must reject.
            retained=original.read_bytes();original.unlink()
            with patch.object(sqlite3,'connect',side_effect=AssertionError('no replaced input')):
                with self.assertRaises(ValueError):
                    if obj is self.source:SavedSchoolRosterSource.resume(cap,self.repo)
                    else:SavedSchoolRosterTrial.resume(cap,self.source)
            # This test intentionally abandons the replaced capability.
            if obj is self.source:
                # Target operations need no further source reads in this case.
                pass

    def test_collision_and_partial_publication_rollback(self):
        from game_core.career_rosters import _newcomer_id
        old=self.source.snapshot()[0]
        foreign=old[1].players[0].player_id
        slot=[p.roster_no for p in old[0].players if p.academic_year==3][-1]
        def collide(seed,year,sid,number):
            return foreign if sid==old[0].school_id and number==slot else _newcomer_id(seed,year,sid,number)
        before=pin(self.lab.db_path)
        with patch('game_core.career_rosters._newcomer_id',side_effect=collide):
            with self.assertRaises(ValueError):self.lab.advance(career_seed=SEED,limit=1)
            # Bypass the trial's preflight to test the shared writer transaction
            # itself: earlier newcomers insert before the last-slot collision.
            with self.assertRaises(ValueError):
                CareerRosterArchive(self.lab.db_path).advance_and_save(
                    self.repo.team(old[0].school_id),next_year=2027,career_seed=SEED)
        self.assertEqual(before,pin(self.lab.db_path))
        self.lab.advance(career_seed=SEED,limit=50)
        with self.assertRaises(ValueError):self.lab.school(self.ids[0],year=2027)
        with self.assertRaises(ValueError):self.lab.player(old[0].players[0].player_id)

    def test_roster_acceptance_never_authorizes_competition(self):
        self.assertFalse(competition_start_gate(self.lab.status())['season_start_authorized'])
        state=self.lab.advance(career_seed=SEED)
        gate=competition_start_gate(state)
        self.assertTrue(gate['rosters_accepted']);self.assertFalse(gate['season_start_authorized'])
        self.assertEqual('not_scheduled_not_played',gate['tournament_status'])
        view=self.lab.browse()
        self.assertEqual((),view['matches']);self.assertIsNone(view['school_standalone_outcomes'])
        school=self.lab.school(self.ids[0],year=2027)
        self.assertFalse(school['season_start_authorized'])
        first=self.source.snapshot()[0][0].players[0]
        self.assertEqual(self.ids[0],self.lab.player(first.player_id)['history'][0]['school_id'])
        self.assertFalse(competition_start_gate(dict(accepted=True,season_start_authorized=True))['season_start_authorized'])

    def test_native_close_rename_reopen_source_and_target(self):
        with retained_handles() as handles:
            self.source.snapshot();self.lab.advance(career_seed=SEED,limit=1)
            assert_closed(self,handles)
        caps=(self.source.capability,self.lab.capability)
        self.lab.close();self.source.close()
        for path in (self.source.db_path,self.lab.db_path):
            moved=path.with_suffix('.released');path.rename(moved);moved.rename(path)
            with closing(sqlite3.connect(path)) as con:
                self.assertEqual([('ok',)],con.execute('PRAGMA integrity_check').fetchall())
        self.source=SavedSchoolRosterSource.resume(caps[0],self.repo)
        self.lab=SavedSchoolRosterTrial.resume(caps[1],self.source)
        self.assertEqual(1,self.lab.status()['generated_schools'])
