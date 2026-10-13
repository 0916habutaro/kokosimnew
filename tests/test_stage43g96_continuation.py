"""Actual replay/continuation and fail-closed faults, self-generated inputs only."""
from contextlib import closing
from dataclasses import replace
import errno
import hashlib
import json
import os
import sqlite3
import subprocess
import unittest
from unittest.mock import patch

import stage43g96_continuation_harness as lab
from phase2_engine.live_season_save import rechecksum_live_season_save_payload, LiveSeasonSaveReplayError

REFUSALS = []


def snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


class Stage43G96ContinuationTests(unittest.TestCase):
    def experiment(self, phase='active', source='manual'):
        c = lab.Continuation(phase, source)
        self.addCleanup(c.close)
        return c

    def pins(self, c):
        return [snapshot(p) for p in (c.e.fixture.slot, c.e.fixture.destination, c.e.target)]

    def refused(self, c, operation=None, errors=(lab.product.BackupRefused,)):
        before = self.pins(c)
        with patch.object(lab.LiveGameService, 'load_game', side_effect=AssertionError('protected or unverified load')) as load:
            with self.assertRaises(errors):
                (operation or c.prepare)()
            self.assertEqual(load.call_count, 0)
        self.assertEqual(before, self.pins(c))
        REFUSALS.append(self._testMethodName)

    def work(self, c):
        c.prepare()
        return c.roots['isolated-work']/'owned94'

    def reanchor_work(self, c):
        # Deliberately bypass byte pin to exercise independent product/SQL guard.
        c.work_pins['isolated-work'] = lab.anchor(c.roots['isolated-work']/'owned94')

    def alter_json(self, path, **fields):
        p = json.loads(path.read_text(encoding='utf-8'))
        p.update(fields)
        path.write_text(json.dumps(rechecksum_live_season_save_payload(p)),encoding='utf-8')

    def test_six_states_two_actual_series_all_records_equal(self):
        for phase in ('active','sealed','registered'):
            for source in ('manual','autosave'):
                with self.subTest(phase=phase,source=source):
                    c = self.experiment(phase,source)
                    before = self.pins(c)
                    original = lab.LiveGameService.load_game
                    calls = []
                    def guarded(service, sid, **kwargs):
                        self.assertIn(service.slots.root_dir, c.roots.values())
                        self.assertEqual(sid,'owned94')
                        self.assertEqual(kwargs['source'],source)
                        calls.append(service.slots.root_dir)
                        return original(service,sid,**kwargs)
                    with patch.object(lab.LiveGameService,'load_game',guarded):
                        m = c.compare(measure=True)
                    self.assertEqual(len(calls),4)
                    self.assertEqual(before,self.pins(c))
                    self.assertEqual(m['continued_matches_per_series'],1 if phase=='active' else 0)
                    self.assertEqual(m['replay_matches_per_series'],6 if phase=='active' else 7)
                    self.assertEqual(m['years'],2 if phase=='registered' else 1)
                    self.assertTrue(m['next_year_refused'])
                    # All handles released, including new live/roster/outcome handles.
                    for root in c.roots.values():
                        moved = root.with_name(root.name+'-closed')
                        root.rename(moved)
                        self.assertEqual(len(lab.browse(moved/'owned94')['details']),7)

    def test_original_candidate_evidence_tampering(self):
        for key in ('source','candidate','evidence'):
            c = self.experiment()
            root = {'source':c.e.fixture.slot,'candidate':c.e.fixture.destination,'evidence':c.e.target}[key]
            path = root/'manual.json' if key=='source' else root/'payload'/'owned94'/'manual.json'
            path.write_bytes(b'changed')
            self.refused(c)

    def test_missing_preceding_receipts_and_private_evidence(self):
        for name in ('COMPLETE','evidence.json','compatibility/data/master/schools.csv'):
            c = self.experiment()
            (c.e.target/name).unlink()
            self.refused(c)
        c=self.experiment(); c.evidence_pin={}; self.refused(c)
        c=self.experiment(); self.work(c); c.work_pins.clear()
        self.refused(c,lambda:c.run_one('isolated-work'))

    def test_catalog_changed_unknown_generation_and_planner(self):
        c=self.experiment()
        p=c.e.target/'evidence.json'
        v=json.loads(p.read_text(encoding='utf-8'));v['catalog_version']='unknown';p.write_text(json.dumps(v),encoding='utf-8')
        self.refused(c)
        c=self.experiment(); c.generated_compatibility_known=False; self.refused(c)
        c=self.experiment();c.plan=replace(c.plan,rng_seed=SEED_DIFFERENT);self.refused(c)
        c=self.experiment()
        with patch.object(lab.product,'_compatibility',side_effect=lab.product.BackupRefused('compatibility_missing_or_unknown_version')):
            self.refused(c)

    def test_explicit_manual_autosave_selection_cannot_be_switched(self):
        for source in ('autosave','latest','manual_backup_001',''):
            c=self.experiment();c.source=source;self.refused(c)

    def test_foreign_slot_and_mixed_provenance(self):
        c=self.experiment();slot=self.work(c)
        (slot/'slot_metadata.json').write_text('{"slot_id":"foreign"}',encoding='utf-8')
        self.reanchor_work(c)
        self.refused(c,lambda:c.run_one('isolated-work'))
        c=self.experiment();slot=self.work(c)
        self.alter_json(slot/'manual.json',rng_seed=SEED_DIFFERENT)
        self.reanchor_work(c)
        self.refused(c,lambda:c.run_one('isolated-work'))

    def test_history_ahead_of_selected_json_refused_before_load(self):
        c=self.experiment('sealed');slot=self.work(c)
        old=next(p for p in (slot/'backups').glob('manual*.json') if len(json.loads(p.read_text())['completed_match_results'])<7)
        (slot/'manual.json').write_bytes(old.read_bytes())
        self.reanchor_work(c)
        self.refused(c,lambda:c.run_one('isolated-work'))

    def test_ledger_outcomes_and_previous_rosters_refused(self):
        for db,sql in (
            ('historical_matches.sqlite3',"UPDATE career_years SET ledger_sha256='bad' WHERE status='sealed'"),
            ('historical_matches.sqlite3',"UPDATE career_years SET status='active' WHERE status='sealed'"),
            ('historical_matches.sqlite3',"UPDATE historical_competition_outcomes SET record_sha256='bad'"),
            ('career_rosters.sqlite3','DELETE FROM career_school_rosters WHERE year=2026')):
            c=self.experiment('registered');slot=self.work(c)
            with closing(sqlite3.connect(slot/db)) as con:
                con.execute(sql);con.commit()
            self.reanchor_work(c)
            self.refused(c,lambda:c.run_one('isolated-work'))

    def test_career_feeder_qualification_rulebook_and_v2_refused(self):
        from phase2_engine.save_inventory_audit import CHECKPOINT_DIRS
        for directory in sorted(CHECKPOINT_DIRS):
            c=self.experiment();slot=self.work(c)
            (slot/directory).mkdir();(slot/directory/'2027.json').write_bytes(b'{}')
            self.reanchor_work(c)
            self.refused(c,lambda:c.run_one('isolated-work'))
        for name in ('fictional_option_a_v2.sqlite3','sandbox_calendar_v2.sqlite3'):
            c=self.experiment();slot=self.work(c);(slot/name).write_bytes(b'fixture-only-v2')
            self.reanchor_work(c)
            self.refused(c,lambda:c.run_one('isolated-work'))
        for field in ('regional_feeder_resolution_count','qualification_resolution_count'):
            c=self.experiment();slot=self.work(c)
            p=json.loads((slot/'manual.json').read_text());p['runtime_summary'][field]=1
            self.alter_json(slot/'manual.json',runtime_summary=p['runtime_summary'])
            self.reanchor_work(c)
            self.refused(c,lambda:c.run_one('isolated-work'))

    def test_work_byte_and_partial_writer_artifacts(self):
        for name in ('manual.json','manual.json.tmp','historical_matches.sqlite3-wal',
                     'career_rosters.sqlite3-shm','historical_matches.sqlite3-journal'):
            c=self.experiment();slot=self.work(c);(slot/name).write_bytes(b'late-writer')
            self.refused(c,lambda:c.run_one('isolated-work'))

    def test_existing_empty_populated_work_and_retry_preserved(self):
        for populated in (False,True):
            c=self.experiment();root=c.roots['isolated-work'];root.mkdir()
            if populated:(root/'retain').write_bytes(b'retain')
            before=snapshot(root);self.refused(c);self.assertEqual(before,snapshot(root))
        c=self.experiment();c.prepare();before=[snapshot(p) for p in c.roots.values()]
        self.refused(c);self.assertEqual(before,[snapshot(p) for p in c.roots.values()])

    def test_external_or_protected_destination_refused(self):
        for key in ('source','candidate','evidence','outside'):
            c=self.experiment()
            c.roots['isolated-work']={'source':c.e.fixture.slot,'candidate':c.e.fixture.destination,
                'evidence':c.e.target,'outside':c.e.fixture.root.parent/'stage96-not-owned'}[key]
            self.refused(c)

    def test_copy_enospc_eio_interrupt_no_game_and_no_retry(self):
        for error in (OSError(errno.ENOSPC,'fixture'),OSError(errno.EIO,'fixture'),KeyboardInterrupt()):
            c=self.experiment();original=lab.copy_file;calls=0
            def fail(src,dst):
                nonlocal calls
                calls+=1
                if calls==3:raise error
                original(src,dst)
            with patch.object(lab,'copy_file',fail):
                self.refused(c,errors=(OSError,KeyboardInterrupt))
            self.assertEqual(c.work_pins,{})
            self.refused(c)

    def test_copy_corruption_and_late_work_change(self):
        c=self.experiment();original=lab.copy_file
        def corrupt(src,dst):
            original(src,dst)
            if dst.name=='manual.json':dst.write_bytes(b'copy-fault')
        with patch.object(lab,'copy_file',corrupt):self.refused(c)
        c=self.experiment();slot=self.work(c)
        original=c.preflight
        def change():
            original();(slot/'manual.json').write_bytes(b'writer-before-load')
        with patch.object(c,'preflight',change):self.refused(c,lambda:c.run_one('isolated-work'))

    def test_links_hardlinks_and_windows_junction(self):
        c=self.experiment();slot=self.work(c)
        os.link(slot/'manual.json',slot/'foreign.json')
        self.refused(c,lambda:c.run_one('isolated-work'))
        c=self.experiment();root=c.roots['isolated-work']
        if os.name=='nt':
            r=subprocess.run(['cmd','/c','mklink','/J',str(root),str(c.e.target)],capture_output=True)
            self.assertEqual(r.returncode,0)
        else:root.symlink_to(c.e.target,target_is_directory=True)
        self.refused(c)

    def test_busy_db_only_work_slot_can_fail(self):
        c=self.experiment();slot=self.work(c);before=self.pins(c)
        con=sqlite3.connect(slot/'historical_matches.sqlite3');self.addCleanup(con.close)
        con.execute('BEGIN EXCLUSIVE')
        original=sqlite3.connect
        def short_timeout(*args,**kwargs):
            kwargs['timeout']=0.05
            return original(*args,**kwargs)
        with patch.object(sqlite3,'connect',short_timeout),lab.owned_sqlite_handles():
            with self.assertRaises(sqlite3.OperationalError):c.run_one('isolated-work')
        con.rollback();con.close()
        self.assertEqual(before,self.pins(c));REFUSALS.append(self._testMethodName)

    def test_readonly_writer_connection_fails_in_work_only(self):
        c=self.experiment();slot=self.work(c);before=self.pins(c)
        original=sqlite3.connect
        def readonly(*args,**kwargs):
            if args and str(args[0])==str(slot/'historical_matches.sqlite3'):
                return original((slot/'historical_matches.sqlite3').as_uri()+'?mode=ro',uri=True)
            return original(*args,**kwargs)
        with patch.object(sqlite3,'connect',readonly),lab.owned_sqlite_handles():
            with self.assertRaises(sqlite3.OperationalError):c.run_one('isolated-work')
        self.assertEqual(before,self.pins(c));REFUSALS.append(self._testMethodName)

    def test_nondeterministic_replay_refuses_and_protects_evidence(self):
        c=self.experiment();self.work(c);before=self.pins(c)
        original=lab.AbilityMatchResolver.__call__
        def changed(resolver,*args,**kwargs):
            result=original(resolver,*args,**kwargs)
            return replace(result,team1_score=result.team1_score+1)
        with patch.object(lab.AbilityMatchResolver,'__call__',changed):
            with self.assertRaises(LiveSeasonSaveReplayError):c.run_one('isolated-work')
        self.assertEqual(before,self.pins(c));REFUSALS.append(self._testMethodName)

    def test_reload_interrupt_and_checkpoint_io_failure_protect_inputs(self):
        c=self.experiment();self.work(c);before=self.pins(c)
        with patch.object(lab.LiveGameService,'_sync_history',side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):c.run_one('isolated-work')
        self.assertEqual(before,self.pins(c));REFUSALS.append(self._testMethodName)
        c=self.experiment();slot=self.work(c);before=self.pins(c)
        original=lab.Path.replace
        def fail(path,target):
            if path.parent==slot and path.name=='autosave.json.tmp':raise OSError(errno.EIO,'fixture')
            return original(path,target)
        with patch.object(lab.Path,'replace',fail):
            with self.assertRaises(OSError):c.run_one('isolated-work')
        self.assertTrue((slot/'autosave.json.tmp').exists())
        self.assertEqual(before,self.pins(c));REFUSALS.append(self._testMethodName)
        self.refused(c,lambda:c.run_one('isolated-work'))

    def test_real_process_exit_after_replay_does_not_touch_evidence(self):
        c=self.experiment();slot=self.work(c);before=self.pins(c)
        script='''
import os
from pathlib import Path
from stage43g96_continuation_harness import fixture_plan, ROOT, SEED, LiveGameService, StaticPlanner, AbilityMatchResolver, TournamentEngine
from test_stage43g92_legacy_replay import Stage43G92LegacyReplayTests as Base
Base.setUpClass()
root=Path(os.environ['STAGE96_OWNED_WORK_ROOT'])
service=LiveGameService(Base.repo,ROOT/'data',save_root=root,planner_factory=lambda *args:StaticPlanner(fixture_plan()))
resolver=AbilityMatchResolver(Base.repo,ability_config_dir=ROOT/'config'/'abilities',match_config_dir=ROOT/'config'/'match',team_generation_seed=SEED)
engine=TournamentEngine(Base.repo,main_match_resolver=resolver,pre_main_match_resolver=resolver)
def stop(session):
    assert len(session.state.public_snapshot()['active_competitions']) > 0
    (root/'owned94'/'interrupted.txt').write_bytes(b'after-actual-replay-before-sync')
    os._exit(77)
service._sync_history=stop
service.load_game('owned94',source='manual',engine=engine)
'''
        env=dict(os.environ,PYTHONPATH=os.pathsep.join((str(lab.ROOT/'tests'),str(lab.ROOT))),
            STAGE96_OWNED_WORK_ROOT=str(c.roots['isolated-work']))
        result=subprocess.run([os.sys.executable,'-c',script],env=env,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,77,result.stderr.decode(errors='replace'))
        self.assertTrue((slot/'interrupted.txt').is_file())
        self.assertEqual(before,self.pins(c))
        self.refused(c,lambda:c.run_one('isolated-work'))


SEED_DIFFERENT=2026101202
