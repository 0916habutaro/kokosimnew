"""Windows-first gate; public artifacts contain only aggregate test results."""
import argparse
import json
from pathlib import Path
import platform
import sys
from time import perf_counter
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--require-windows", action="store_true")
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()
    if args.require_windows and sys.platform != "win32":
        parser.error("Windows native runner required")
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    patterns = ["test_stage43g102_real_tk.py"] if args.gui else [
        "test_stage43g102_master_scale.py", "test_stage43g102_compatibility.py"]
    suite = unittest.TestSuite(unittest.defaultTestLoader.discover(str(root / "tests"), pattern=p)
        for p in patterns)
    start = perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    successful = result.wasSuccessful() and not result.skipped and result.testsRun == (1 if args.gui else 14)
    from stage43g102_fixture_support import MEASUREMENTS
    report = dict(measurements=MEASUREMENTS, stage="43G-102", os=platform.system(), python=platform.python_version(),
        tests=result.testsRun, skipped=len(result.skipped), errors=len(result.errors),
        failures=len(result.failures), successful=successful,
        seconds=round(perf_counter() - start, 3), native_windows=sys.platform == "win32",
        mapped_tk=args.gui, fixture_only=True, competitions=1, official_team_count=32, master_school_count=33,
        unique_school_rosters=33, permanent_players=660, actual_games=32,
        old_real_candidate_versions=4, explicit_service_contract=True,
        multiple_store_atomicity_guaranteed=False, current_code_replay_authorized=False,
        official_2026_participants_and_bracket_reproduced=False, next_year_gameplay_started=False,
        production_restore_added=False, manual_user_windows_operation_verified=False,
        existing_save_candidates=sum(p.is_dir() for p in (root / "out/saves").glob("*")),
        existing_saves_used=0, existing_save_verification="未検証・試験入力利用なし")
    with args.json_output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
