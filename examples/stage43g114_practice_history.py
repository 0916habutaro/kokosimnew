"""Self-created test CLI: actual saved2027 practice and cross-year history.

No existing SQLite/save path is accepted. The temporary parent owns all files
across the exited worker; the final JSON is an explanation, not a product save.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-created-only',action='store_true')
    parser.add_argument('--player-state',choices=('returning','newcomer'),default='returning')
    args=parser.parse_args()
    if not args.self_created_only:parser.error('--self-created-only opt-in required')
    root=Path(__file__).resolve().parents[1]
    sys.path[:0]=[str(root),str(root/'tests')]
    from phase2_engine.yamanashi_annual_rosters import SelfCreated2026,AnnualRosterLab
    from phase2_engine.saved_practice_match import PracticeStore
    from stage43g114_support import worker
    with ExitStack() as stack:
        owners=[]
        for label in ('source','annual','practice','private'):
            owner=tempfile.TemporaryDirectory(prefix=f'stage114-example-{label}-')
            owners.append(owner);stack.callback(owner.cleanup)
        source=SelfCreated2026(owners[0],opt_in=True);stack.callback(source.close)
        for _ in range(31):source.store.play_next()
        lab=AnnualRosterLab(source,owners[1],opt_in=True);stack.callback(lab.close)
        lab.advance()
        store=PracticeStore(lab,owners[2],opt_in=True);stack.callback(store.close)
        store.play()
        store.close();lab.close();source.close()
        report=worker(lab,store,Path(owners[3].name))
        people=[p for p in report['player_histories'] if p['transition']==args.player_state]
        if args.player_state=='returning':people=[p for p in people if p['history'][0]['appearances']]
        if not people:raise ValueError('required actual cross-year appearance unavailable')
        for school in report['school_histories']:
            for year in school['history']:
                year.pop('roster')
                for match in year['matches']:
                    result=match.pop('result')
                    match.update(score=[result['team1_score'],result['team2_score']],inning_scores=result['inning_scores'])
        print(json.dumps(dict(message='2026大会記録と2027架空練習試合。公式2027資格・日程・順位は未確定。',
            match_id=report['match_id'],record_kind=report['record_kind'],restart_oracle=report['oracle'],
            schools=report['school_histories'],player=people[0]),ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
