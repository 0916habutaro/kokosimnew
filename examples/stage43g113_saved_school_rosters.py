"""Run an explicitly opted-in disposable100 trial, no existing saves or games."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import tracemalloc

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from phase2_engine.repository import DataRepository
from phase2_engine.cross_prefecture_roster_selection import audit_selection
from phase2_engine.saved_school_roster_source import SavedSchoolRosterSource, SavedSchoolRosterTrial, competition_start_gate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--opt-in-disposable-rosters',action='store_true',required=True)
    parser.add_argument('--selection-json',type=Path)
    args=parser.parse_args()
    repo=DataRepository(Path(__file__).resolve().parents[1]/'data')
    audit=audit_selection(repo)
    if args.selection_json:
        with args.selection_json.open('x',encoding='utf-8') as out:
            json.dump(audit,out,ensure_ascii=False,indent=2);out.write('\n')
    ids=tuple(r['school_id'] for r in audit['schools'])
    source_owner=tempfile.TemporaryDirectory(prefix='stage113-source-')
    target_owner=tempfile.TemporaryDirectory(prefix='stage113-target-')
    with source_owner, target_owner:
        began=perf_counter();tracemalloc.start()
        source=SavedSchoolRosterSource(repo,ids,source_owner,year=2026,career_seed=430113,opt_in=True)
        try:
            saved=perf_counter()
            target=SavedSchoolRosterTrial(source,target_owner,next_year=2027,career_seed=430113,opt_in=True)
            try:
                state=target.advance(career_seed=430113)
                print(json.dumps(dict(source_save_seconds=saved-began,advance_accept_seconds=perf_counter()-saved,
                    traced_peak_bytes=tracemalloc.get_traced_memory()[1],source_bytes=source.db_path.stat().st_size,
                    target_bytes=target.db_path.stat().st_size,summary=state['summary'],
                    competition=competition_start_gate(state)),ensure_ascii=False))
            finally:target.close()
        finally:source.close();tracemalloc.stop()


if __name__=='__main__':main()
