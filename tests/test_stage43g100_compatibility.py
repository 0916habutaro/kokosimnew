"""True Stage94/99 candidates and before/after demo sources remain independent."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from phase2_engine import manual_save_backup as product
from phase2_engine.legacy_backup_compatibility import CATALOG, CATALOG_VERSION
from phase2_engine.live_game_service import LiveGameService
from phase2_engine.live_game_demo_worker import services, SEED, SLOT
from stage43g94_fixture_support import Fixture, owned_sqlite_handles
from stage43g95_isolated_harness import anchor
import stage43g99_fixture_support as support
from test_stage43g100_persistence import raw_records

STAGE99_MAIN = '4ee0f9199b0c40811e3c33c10bc0ba2de3ed97f4'


class Stage43G100CompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='stage100-two-old-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name).resolve()
        cls.candidates = {}
        for label,commit in [('94',support.OLD_MAIN),('99',STAGE99_MAIN)]:
            root = cls.root/label
            root.mkdir()
            with patch.object(support,'OLD_MAIN',commit):
                cls.candidates[label] = support.old_candidate(root)
        cls.pins = {k:anchor(p) for k,p in cls.candidates.items()}

    def test_true_two_old_exports_verify_readonly_and_current_replay_refused(self):
        for label,path in self.candidates.items():
            with self.subTest(version=label):
                evidence=json.loads((path/'evidence.json').read_text())
                self.assertEqual(338,len(evidence['compatibility_files']))
                self.assertNotEqual(CATALOG_VERSION,evidence['catalog_version'])
                with patch.object(LiveGameService,'load_game',side_effect=AssertionError('no replay')):
                    self.assertTrue(product.verify_candidate(candidate=path)['candidate_consistent'])
                    result=product.diagnose_candidate_compatibility(candidate=path)
                self.assertEqual('catalog_mismatch_refused',result['replay_status'])
                self.assertFalse(result['current_code_replay_allowed'])
                self.assertFalse(result['candidate_code_executed'])
                self.assertEqual(self.pins[label],anchor(path))
        oldroot=self.root/'99'/'old-main'
        oldnames={p.relative_to(oldroot/'data') for p in (oldroot/'data').rglob('*') if p.is_file()}
        currentnames={p.relative_to(support.ROOT/'data') for p in (support.ROOT/'data').rglob('*') if p.is_file()}
        self.assertEqual(oldnames,currentnames)
        self.assertEqual(106,sum(p.suffix=='.csv' for p in oldnames))
        self.assertTrue(all((oldroot/'data'/p).read_bytes()==(support.ROOT/'data'/p).read_bytes() for p in oldnames))
        evidence=json.loads((self.candidates['99']/'evidence.json').read_text())
        current=product._compatibility(support.ROOT)
        self.assertEqual({'game_core/tournament_bridge.py','phase2_engine/live_game_service.py'},
                         {name for name in CATALOG if current[name]!=evidence['compatibility_files'][name]})

    def test_current_export_never_authorizes_replay_and_old_candidate_relabel_refused(self):
        with owned_sqlite_handles(): f=Fixture('sealed')
        self.addCleanup(f.close)
        product.export_backup(**f.args())
        result=product.diagnose_candidate_compatibility(candidate=f.destination)
        self.assertTrue(result['installed_catalog_match'])
        self.assertEqual('separate_replay_review_required',result['replay_status'])
        self.assertFalse(result['current_code_replay_allowed'])
        import shutil
        target=self.root/'relabel'
        shutil.copytree(self.candidates['99'],target)
        path=target/'evidence.json'
        evidence=json.loads(path.read_text());evidence['catalog_version']=CATALOG_VERSION
        path.write_bytes(product._encoded(evidence))
        (target/'COMPLETE').write_text(product.VERSION+'\n'+product._sha(path.read_bytes())+'\n',newline='\n')
        before=anchor(target)
        with self.assertRaises(product.BackupRefused): product.verify_candidate(candidate=target)
        self.assertEqual(before,anchor(target))

    def test_actual_pre_worker_post_service_option_a_roster_and_ranking_equal(self):
        old=self.root/'99'/'old-main'
        saves=self.root/'old-generated'
        output=self.root/'baseline.json'
        # Reviewed Git checkout only, not Python copied out of a backup candidate.
        code='''
from pathlib import Path
import json,sys
from phase2_engine.live_game_demo_worker import services,SEED,SLOT
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
s,r,e=services(Path(sys.argv[1]))
ss=s.new_game(SLOT,rng_seed=SEED,engine=e,start_date='2026-07-01')
s.advance_through(ss,'2026-12-31');s.finalize_season(ss)
for roster in r._roster_cache.values(): CareerRosterArchive(s.slots.slot_dir(SLOT)/'career_rosters.sqlite3').save_initial_roster(roster)
for run in ss.state.completed_runs().values(): CareerCompetitionOutcomes(s.slots.slot_dir(SLOT)/'historical_matches.sqlite3').record_completed(run)
s.save_game(ss);s.autosave_game(ss)
'''
        env=dict(os.environ,PYTHONUTF8='1',PYTHONPATH=str(old))
        result=subprocess.run([sys.executable,'-c',code,str(saves)],cwd=old,env=env,capture_output=True,timeout=180)
        self.assertEqual(0,result.returncode,'pre-change demo baseline failed')
        before=raw_records(saves/SLOT)
        service,resolver,engine=services(self.root/'new-generated')
        session=service.new_game(SLOT,rng_seed=SEED,engine=engine,start_date='2026-07-01')
        service.advance_through(session,'2026-12-31');service.finalize_season(session);service.autosave_game(session)
        after=raw_records(service.slots.slot_dir(SLOT))
        self.assertEqual(before,after)
        self.assertEqual((8,160,7,1),tuple(len(after[k]) for k in ('rosters','identities','matches','outcomes')))
        self.assertEqual(self.pins,{k:anchor(p) for k,p in self.candidates.items()})


if __name__=='__main__': unittest.main()
