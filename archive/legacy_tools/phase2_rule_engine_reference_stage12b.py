#!/usr/bin/env python3
"""Phase 2 Stage 12B exact-format reference planner / validator.

制度（format model）と、その年度の抽選位置・学校名を分離する。
学校名を方式テーブルへ固定せず、group membership + access/seed rules + annual drawで実行する。
"""
from __future__ import annotations
import argparse,csv,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from phase2_engine.paths import resolve_data_file

def rows(p):
    with open(p,encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))

def load(d):
    ns=["competition_stages.csv","competition_stage_groups.csv","competition_stage_transitions.csv","competition_stage_action_bindings.csv","bracket_generation_policies.csv","competition_access_rules.csv","competition_seed_rules.csv","competition_stage_format_models.csv","competition_stage_format_phases.csv","competition_stage_internal_transitions.csv","competition_stage_format_assignments.csv","competition_stage_group_format_overrides.csv","competition_stage_format_parameters.csv"]
    return {n:rows(resolve_data_file(d,n)) for n in ns}

def validate(x):
    err=[]
    stage_ids={r['stage_id'] for r in x['competition_stages.csv']}; group_ids={r['stage_group_id'] for r in x['competition_stage_groups.csv']}; model_ids={r['format_model_id'] for r in x['competition_stage_format_models.csv']}
    access_ids={r['access_rule_id'] for r in x['competition_access_rules.csv']}; seed_ids={r['seed_rule_id'] for r in x['competition_seed_rules.csv']}
    for r in x['competition_stage_groups.csv']:
        if r['stage_id'] not in stage_ids:err.append('group stage FK '+r['stage_group_id'])
    for r in x['competition_stage_format_assignments.csv']:
        if r['stage_id'] not in stage_ids:err.append('assignment stage FK '+r['format_assignment_id'])
        if r['default_format_model_id'] not in model_ids:err.append('assignment model FK '+r['format_assignment_id'])
    for r in x['competition_stage_group_format_overrides.csv']:
        if r['stage_group_id'] not in group_ids:err.append('override group FK '+r['group_format_id'])
        if r['format_model_id'] not in model_ids:err.append('override model FK '+r['group_format_id'])
    for r in x['competition_stage_format_phases.csv']:
        if r['format_model_id'] not in model_ids:err.append('phase model FK '+r['format_phase_id'])
    for r in x['competition_stage_format_parameters.csv']:
        if r['format_model_id'] not in model_ids:err.append('param model FK '+r['parameter_id'])
        if r['stage_group_id'] and r['stage_group_id'] not in group_ids:err.append('param group FK '+r['parameter_id'])
    for r in x['competition_stage_action_bindings.csv']:
        ok=(r['rule_family']=='access' and r['rule_id'] in access_ids) or (r['rule_family']=='seed' and r['rule_id'] in seed_ids)
        if not ok:err.append('binding rule FK '+r['binding_id'])
    target=[r for r in x['competition_stages.csv'] if r['stage_type'] in ('branch_qualifier','seed_event')]
    if len(target)!=44:err.append(f'target stage count {len(target)} !=44')
    if len(x['competition_stage_format_assignments.csv'])!=45:err.append('assignment coverage !=45 (44 core + 1 auxiliary)')
    if len(x['competition_stage_group_format_overrides.csv'])!=len(x['competition_stage_groups.csv']):err.append('group format coverage incomplete')
    if any(r['execution_readiness']!='exact_format_ready' for r in x['competition_stage_groups.csv']):err.append('non-ready stage group remains')
    return err

def plan(x,cid):
    ass=[r for r in x['competition_stage_format_assignments.csv'] if r['competition_id']==cid]
    if not ass:raise SystemExit('no Stage12B assignment for '+cid)
    mids={r['default_format_model_id'] for r in ass}
    ovs=[r for r in x['competition_stage_group_format_overrides.csv'] if r['competition_id']==cid]; mids|={r['format_model_id'] for r in ovs}
    models=[r for r in x['competition_stage_format_models.csv'] if r['format_model_id'] in mids]
    phases=[r for r in x['competition_stage_format_phases.csv'] if r['format_model_id'] in mids]
    phases.sort(key=lambda r:(r['format_model_id'],int(r['phase_sequence'])))
    return {'competition_id':cid,'assignment':ass,'groups':[r for r in x['competition_stage_groups.csv'] if r['competition_id']==cid],'group_formats':ovs,'format_models':models,'format_phases':phases,'format_parameters':[r for r in x['competition_stage_format_parameters.csv'] if r['competition_id']==cid],'action_bindings':[r for r in x['competition_stage_action_bindings.csv'] if r['competition_id']==cid],'transitions':[r for r in x['competition_stage_transitions.csv'] if r['competition_id']==cid]}

def main():
    a=argparse.ArgumentParser();a.add_argument('--data-dir',default='data');a.add_argument('--validate',action='store_true');a.add_argument('--competition-id');z=a.parse_args();x=load(Path(z.data_dir))
    if z.validate:
        e=validate(x);print(json.dumps({'status':'PASS' if not e else 'FAIL','errors':e},ensure_ascii=False,indent=2));
        if e:raise SystemExit(1)
    if z.competition_id:print(json.dumps(plan(x,z.competition_id),ensure_ascii=False,indent=2))
    if not z.validate and not z.competition_id:a.print_help()
if __name__=='__main__':main()
