"""長野4校の自己生成ロスター試行。保存ファイル入力・大会生成はありません。"""
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile


def main():
    if sys.argv[1:] != ['--self-created-only']:
        raise SystemExit('python examples/stage43g112_roster_only_read.py --self-created-only')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from phase2_engine.repository import DataRepository
    from phase2_engine.school_roster_trial import MasterRosterSandbox, SchoolRosterTrial
    repo = DataRepository(Path(__file__).resolve().parents[1] / 'data')
    source = MasterRosterSandbox(repo, ('SCH001636', 'SCH001637', 'SCH001638', 'SCH001639'),
                                 year=2026, career_seed=430112)
    owner = tempfile.TemporaryDirectory(prefix='stage112-self-created-')
    try:
        lab = SchoolRosterTrial(source, owner, next_year=2027, career_seed=430112, opt_in=True)
        try:
            status = lab.advance(career_seed=430112)
            view = lab.browse()
            rows = [dict(県='長野県', 学校ID=r['school_id'], 学校=r['school_name'], 年度=r['reference_year'],
                         学年別人数=dict(Counter(p['academic_year'] for p in r['players']))) for r in view['rosters']]
            print(json.dumps(dict(範囲='roster-only trial（学校ロスターのみ）',
                シーズン開始承認=False, 試合生成=0, 集計=status['summary'], 学校年度=rows), ensure_ascii=False, indent=2))
        finally:
            lab.close()
    finally:
        owner.cleanup()


if __name__ == '__main__':
    main()
