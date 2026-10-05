from __future__ import annotations
import csv, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA_ROOT=ROOT/"data"
sys.path.insert(0,str(ROOT))
from phase2_engine import DataRepository, SeasonOrchestrator

class Stage12ERegionalFeederTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo=DataRepository(DATA_ROOT)
        cls.orch=SeasonOrchestrator(cls.repo,DATA_ROOT)
        cls.season=cls.orch.run_structural_season(2026,2026100501)
        with (DATA_ROOT/'competitions'/'regional_feeder_rules.csv').open(encoding='utf-8-sig',newline='') as f:
            cls.rules=list(csv.DictReader(f))
        with (DATA_ROOT/'competitions'/'regional_qualification_playoffs.csv').open(encoding='utf-8-sig',newline='') as f:
            cls.playoffs=list(csv.DictReader(f))

    def test_all_16_regional_destinations_structured(self):
        self.assertEqual(16,len({r['destination_competition_id'] for r in self.rules}))
        self.assertEqual(0,len(self.season.regional_bridge_gaps))

    def test_all_16_regional_competitions_execute_at_official_team_count(self):
        self.assertEqual(16,len(self.season.regional_rows))
        self.assertTrue(all(r.status=='PASS' for r in self.season.regional_rows))
        self.assertTrue(all(r.entrant_count==r.expected_team_count for r in self.season.regional_rows))
        self.assertEqual(8,sum(r.season_segment=='spring' for r in self.season.regional_rows))
        self.assertEqual(8,sum(r.season_segment=='autumn' for r in self.season.regional_rows))

    def test_spring_tohoku_allocation(self):
        rs={r['source_prefecture_code']:int(r['quota']) for r in self.rules if r['destination_competition_id']=='CMP000005'}
        self.assertEqual({'02':3,'03':2,'04':2,'05':3,'06':2,'07':2},rs)

    def test_spring_kanto_allocation_includes_tokyo(self):
        rs={r['source_prefecture_code']:int(r['quota']) for r in self.rules if r['destination_competition_id']=='CMP000006'}
        self.assertEqual(3,rs['12'])
        self.assertEqual(2,rs['13'])
        self.assertEqual(17,sum(rs.values()))

    def test_spring_kyushu_senbatsu_six_plus_prefectural_ten(self):
        rs=[r for r in self.rules if r['destination_competition_id']=='CMP000012']
        rec=[r for r in rs if r['source_type']=='national_invitational_participants']
        pref=[r for r in rs if r['source_type']=='prefectural_result']
        self.assertEqual(1,len(rec)); self.assertEqual(6,int(rec[0]['quota']))
        self.assertEqual(10,sum(int(r['quota']) for r in pref))
        run=self.season.competition_runs['CMP000012']
        self.assertEqual(16,len(run.entrant_school_ids))
        self.assertEqual(6,sum(self.repo.schools[s]['prefecture_code'] in {'40','41','42','43','44','45','46','47'} for s in self.season.senbatsu_participant_school_ids))

    def test_autumn_kinki_playoff_structure(self):
        rs=[r for r in self.rules if r['destination_competition_id']=='CMP000019']
        direct=sum(int(r['quota']) for r in rs if r['qualification_mode']=='direct')
        candidates=[r for r in rs if r['qualification_mode']=='playoff_candidate']
        self.assertEqual(14,direct)
        self.assertEqual(4,len(candidates))
        self.assertEqual(2,len(self.playoffs))
        self.assertEqual(2,len(self.season.regional_playoff_resolutions))
        self.assertTrue(all(p.status=='PASS' for p in self.season.regional_playoff_resolutions))
        self.assertEqual(16,len(self.season.competition_runs['CMP000019'].entrant_school_ids))

    def test_autumn_uniform_allocations(self):
        tohoku=[r for r in self.rules if r['destination_competition_id']=='CMP000014']
        tokai=[r for r in self.rules if r['destination_competition_id']=='CMP000018']
        shikoku=[r for r in self.rules if r['destination_competition_id']=='CMP000021']
        kyushu=[r for r in self.rules if r['destination_competition_id']=='CMP000022']
        self.assertTrue(all(int(r['quota'])==3 for r in tohoku))
        self.assertTrue(all(int(r['quota'])==3 for r in tokai))
        self.assertTrue(all(int(r['quota'])==3 for r in shikoku))
        self.assertTrue(all(int(r['quota'])==2 for r in kyushu))

    def test_all_jingu_qualifications_resolve_and_jingu_runs(self):
        j=[r for r in self.season.qualification_resolutions if r.destination_competition_id=='CMP000003']
        self.assertEqual(10,len(j)); self.assertTrue(all(r.status=='PASS' for r in j))
        self.assertIn('CMP000003',self.season.competition_runs)
        self.assertEqual(10,len(self.season.competition_runs['CMP000003'].entrant_school_ids))

    def test_existing_qualification_rules_stay_59_and_all_resolve(self):
        self.assertEqual(59,len(self.season.qualification_resolutions))
        self.assertTrue(all(r.status=='PASS' for r in self.season.qualification_resolutions))

    def test_same_seed_reproduces_regional_champions_and_playoffs(self):
        again=self.orch.run_structural_season(2026,2026100501)
        a=[(r.competition_id,r.champion_school_id) for r in self.season.regional_rows]
        b=[(r.competition_id,r.champion_school_id) for r in again.regional_rows]
        self.assertEqual(a,b)
        pa=[(p.playoff_id,p.winner_school_id) for p in self.season.regional_playoff_resolutions]
        pb=[(p.playoff_id,p.winner_school_id) for p in again.regional_playoff_resolutions]
        self.assertEqual(pa,pb)

if __name__=='__main__': unittest.main()
