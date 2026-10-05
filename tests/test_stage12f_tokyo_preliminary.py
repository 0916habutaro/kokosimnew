from __future__ import annotations
import csv, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA_ROOT=ROOT/"data"
sys.path.insert(0,str(ROOT))
from phase2_engine import DataRepository, SeasonOrchestrator
from phase2_engine.season import StructuralAnnualInputFactory
from phase2_engine import TournamentEngine

class Stage12FTokyoPreliminaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo=DataRepository(DATA_ROOT)
        cls.orch=SeasonOrchestrator(cls.repo,DATA_ROOT)
        cls.season=cls.orch.run_structural_season(2026,2026100501)

    def test_stage_graph_preliminary_then_main(self):
        stages=self.repo.stages('CMP000016')
        self.assertEqual(['PRELIMINARY_QUALIFIER','MAIN'],[s['stage_code'] for s in stages])
        self.assertEqual([1,2],[int(s['sequence']) for s in stages])

    def test_31_numbered_blocks_have_a_and_b_representatives(self):
        st=self.repo.stage_by_code('CMP000016','PRELIMINARY_QUALIFIER')
        groups=self.repo.groups_by_stage[st['stage_id']]
        self.assertEqual(62,len(groups))
        names={g['group_name'] for g in groups}
        for i in range(1,32):
            self.assertIn(f'第{i}ブロックA代表',names)
            self.assertIn(f'第{i}ブロックB代表',names)
        self.assertTrue(all(g['advance_slots_to_next']=='1' for g in groups))

    def test_two_summer_champions_are_direct_access_rules(self):
        rules=self.repo.access_rules('CMP000016')
        self.assertEqual(2,len(rules))
        self.assertEqual({'CMP000036','CMP000037'},{r['source_competition_id_2026'] for r in rules})
        self.assertTrue(all(r['grants_main_entry']=='yes' for r in rules))
        self.assertTrue(all(r['bypassed_stage_participation_policy']=='excluded_from_bypassed_stage' for r in rules))

    def test_structural_annual_input_matches_2026_team_unit_counts(self):
        direct=[self.season.competition_runs[c].outcome.champion_school_id for c in ('CMP000036','CMP000037')]
        factory=StructuralAnnualInputFactory(self.repo,DATA_ROOT,2026100501)
        annual=factory.build_prefectural('CMP000016',2026,direct_main_entry_school_ids=direct,rng_seed=1234)
        self.assertEqual(232,len(annual.entrant_school_ids))
        self.assertEqual(2,len(annual.direct_main_entry_school_ids))
        sizes=sorted(len(v) for v in annual.group_entrant_school_ids.values())
        self.assertEqual(62,len(sizes))
        self.assertEqual(18,sizes.count(3))
        self.assertEqual(44,sizes.count(4))
        self.assertEqual(230,sum(sizes))
        self.assertFalse(set(direct) & {x for v in annual.group_entrant_school_ids.values() for x in v})

    def test_tokyo_preliminary_outputs_62_plus_two_direct_equals_64(self):
        run=self.season.competition_runs['CMP000016']
        self.assertEqual(232,len(run.entrant_school_ids))
        self.assertEqual('PRELIMINARY_QUALIFIER',run.stage_executions[0].stage_code)
        self.assertEqual(62,len(run.stage_executions[0].output_school_ids))
        self.assertEqual(64,len(run.main_entrant_school_ids))
        self.assertEqual(63,run.outcome.match_count)
        self.assertEqual(64,len(run.outcome.final_ranking_school_ids))

    def test_summer_direct_entries_are_in_main_not_preliminary(self):
        run=self.season.competition_runs['CMP000016']
        summer={self.season.competition_runs[c].outcome.champion_school_id for c in ('CMP000036','CMP000037')}
        prelim=set(run.stage_executions[0].entrant_school_ids)
        main=set(run.main_entrant_school_ids)
        self.assertFalse(summer & prelim)
        self.assertTrue(summer <= main)

    def test_stage12f_closes_all_prefectural_internal_gaps(self):
        self.assertEqual(94,sum(r.status=='PASS' for r in self.season.prefectural_rows))
        self.assertEqual(0,len(self.season.internal_structure_gaps))
        self.assertEqual(19,len(self.season.access_resolutions))
        self.assertTrue(all(r.status=='PASS' for r in self.season.access_resolutions))

    def test_policy_preserves_school_vs_team_unit_distinction(self):
        with (DATA_ROOT/'competitions'/'tokyo_autumn_preliminary_policies.csv').open(encoding='utf-8-sig',newline='') as f:
            row=next(csv.DictReader(f))
        self.assertEqual('260',row['observed_participating_school_count'])
        self.assertEqual('232',row['observed_team_unit_count'])
        self.assertEqual('230',row['observed_preliminary_team_unit_count'])
        self.assertEqual('269',row['phase1_tokyo_school_master_count'])
        self.assertEqual('combined_team_mapping_not_materialized',row['exact_2026_team_unit_mapping_status'])

    def test_same_seed_reproduces_tokyo_champion_and_preliminary_draw(self):
        again=self.orch.run_structural_season(2026,2026100501)
        a=self.season.competition_runs['CMP000016']
        b=again.competition_runs['CMP000016']
        self.assertEqual(a.to_dict(),b.to_dict())

    def test_legacy_regional_and_jingu_flow_remains_complete(self):
        self.assertEqual(16,len(self.season.regional_rows))
        self.assertTrue(all(r.status=='PASS' for r in self.season.regional_rows))
        self.assertEqual(59,len(self.season.qualification_resolutions))
        self.assertTrue(all(r.status=='PASS' for r in self.season.qualification_resolutions))
        self.assertEqual(10,len(self.season.competition_runs['CMP000003'].entrant_school_ids))

if __name__=='__main__': unittest.main()
