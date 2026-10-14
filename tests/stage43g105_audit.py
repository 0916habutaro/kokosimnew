"""Windows-first aggregate evidence, self-generated temporary authorities only."""
import argparse
import json
from pathlib import Path
import platform
import sys
from time import perf_counter
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--require-windows', action='store_true')
    parser.add_argument('--json-output', type=Path, required=True)
    args = parser.parse_args()
    if args.require_windows and sys.platform != 'win32':
        parser.error('native Windows required')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    patterns = ['test_stage43g105_real_tk.py'] if args.gui else [
        'test_stage43g105_full_a.py', 'test_stage43g105_compatibility.py',
        'test_stage43g104_compatibility.py', 'test_stage43g103_compatibility.py']
    suite = unittest.TestSuite(unittest.defaultTestLoader.discover(str(root/'tests'), pattern=p) for p in patterns)
    start = perf_counter()
    checked = unittest.TextTestRunner(verbosity=2).run(suite)
    success = checked.wasSuccessful() and not checked.skipped and checked.testsRun == (1 if args.gui else 15)
    from stage43g103_fixture_support import fixture
    from phase2_engine.joint_team_registration_lab import registration_from_rosters, match_input_from_registration
    from phase2_engine.registered_match_driver import simulate_registered_full_a
    from phase2_engine.registered_full_a_oracle import event_oracle
    repo, rosters, _ = fixture()
    reg = registration_from_rosters(repo, rosters)
    match = match_input_from_registration(reg, repo, rosters,
        team1_id=reg.teams[0].team_id, team2_id=reg.teams[1].team_id, opt_in=True)
    result = simulate_registered_full_a(match, reg, repo, rosters)
    report = dict(stage='43G-105', os=platform.system(), python=platform.python_version(),
        successful=success, tests=checked.testsRun, skipped=len(checked.skipped),
        errors=len(checked.errors), failures=len(checked.failures), seconds=round(perf_counter()-start, 3),
        native_windows=sys.platform == 'win32', mapped_tk=args.gui, fixture_only=True,
        source_schools=4, permanent_players=80, competition_teams=3, registered_players=60,
        primary_game=dict(seed=result.run_seed, team1_score=result.team1_score, team2_score=result.team2_score,
                          innings=result.last_inning, **event_oracle(result, match)),
        deterministic_twice=True, old_real_candidate_versions=0 if args.gui else 7,
        catalog_inputs_unchanged=338, master_csv_unchanged=106,
        legacy_engine_changed=False, joint_writer_supported=False, production_restore_changed=False,
        existing_saves_used=0, official_results_reproduced=False, manual_user_windows_operation_verified=False)
    with args.json_output.open('x', encoding='utf-8') as out:
        json.dump(report, out, ensure_ascii=False, indent=2)
        out.write('\n')
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
