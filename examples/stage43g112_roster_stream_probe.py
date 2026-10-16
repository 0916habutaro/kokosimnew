"""Self-created structural roster stream measurement; no SQLite or matches."""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
import tracemalloc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-created-only', action='store_true')
    parser.add_argument('--schools', type=int, default=1000)
    args = parser.parse_args()
    if not args.self_created_only or not 1 <= args.schools <= 1000:
        parser.error('explicit self-created opt-in and 1..1000 schools required')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from phase2_engine.repository import DataRepository
    from phase2_engine.school_roster_contract import accept_roster_source, stream_school_transitions
    from game_core.players import PlayerRosterGenerator
    repo = DataRepository(Path(__file__).resolve().parents[1] / 'data')
    ids = tuple(sid for sid in sorted(repo.schools) if repo.team(sid).program_id)[:args.schools]
    def rosters():
        for sid in ids:
            yield PlayerRosterGenerator().generate_for_school_id(repo, sid, 2036, 430112)
    tracemalloc.start()
    began = perf_counter()
    try:
        receipt = accept_roster_source(rosters(), repo, year=2036, career_seed=430112,
                                       evidence='self-generated structural stream probe')
        accepted = perf_counter()
        count = 0
        for t in stream_school_transitions(rosters(), repo, receipt, next_year=2037, career_seed=430112):
            assert len(t.roster.players) == 20
            count += 1
        report = dict(schools=count, receipt_seconds=accepted-began,
            transition_seconds=perf_counter()-accepted, traced_peak_bytes=tracemalloc.get_traced_memory()[1],
            matches_generated=0, sqlite_writes=0, season_start_authorized=False,
            source='self-generated structural roster probe; not saved game acceptance')
    finally:
        tracemalloc.stop()
    print(json.dumps(report))


if __name__ == '__main__':
    main()
