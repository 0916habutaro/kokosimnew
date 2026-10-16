"""Self-created temporary annual roster read demo; accepts no save/SQLite path."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-created-only', action='store_true')
    parser.add_argument('--school-id', default='SCH000202')
    parser.add_argument('--player-state', choices=('graduated', 'returning', 'newcomer'), default='graduated')
    args = parser.parse_args()
    if not args.self_created_only:
        parser.error('--self-created-only opt-in is required; existing saves are never inputs')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from phase2_engine.yamanashi_annual_rosters import SelfCreated2026, AnnualRosterLab
    from phase2_engine.yamanashi_tournament_registration import SCHOOLS
    if args.school_id not in SCHOOLS:
        parser.error('one of the verified 33 school IDs is required')
    with ExitStack() as stack:
        source_owner = tempfile.TemporaryDirectory(prefix='stage111-example-source-')
        stack.enter_context(source_owner)
        source = SelfCreated2026(source_owner, opt_in=True)
        stack.callback(source.close)
        for _ in range(31):
            source.store.play_next()
        target_owner = tempfile.TemporaryDirectory(prefix='stage111-example-annual-')
        stack.enter_context(target_owner)
        lab = AnnualRosterLab(source, target_owner, opt_in=True)
        stack.callback(lab.close)
        status = lab.advance()
        view = lab.browse()
        schools = [view.school(args.school_id, year=year) for year in (2026, 2027)]
        prior = {p['player_id'] for p in schools[0]['roster']['players']}
        current = {p['player_id'] for p in schools[1]['roster']['players']}
        ids = {'graduated': prior - current, 'returning': prior & current, 'newcomer': current - prior}
        pid = sorted(ids[args.player_state])[0]
        for school in schools:
            school['matches'] = [dict(match_id=r['match_id'], team1_id=r['team1_id'], team2_id=r['team2_id'],
                score=[r['team1_score'], r['team2_score']]) for r in school['matches']]
        print(json.dumps(dict(status=status, schools=schools,
            player=[view.player(pid, year=year) for year in (2026, 2027)]), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
