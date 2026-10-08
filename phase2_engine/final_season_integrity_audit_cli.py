"""CLI for Stage 13E-3F-4 final season integration checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .final_season_integrity_audit import (
    build_final_season_integrity_report,
    save_final_season_integrity_report,
)
from .full_season_live_audit import audit_full_season_live_runtime
from .live_season_planner import LiveSeasonGraphPlanner
from .repository import DataRepository


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit season stages, dates, queues and full-season runtime"
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--seed", type=int, default=2026100827)
    parser.add_argument(
        "--output-dir", default="out/final_season_integrity_audit"
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    repo = DataRepository(data_dir)
    plan = LiveSeasonGraphPlanner(
        repo, data_dir, args.seed, year=args.year
    ).build_plan()
    runtime_audit = audit_full_season_live_runtime(plan)
    report = build_final_season_integrity_report(
        data_dir, year=args.year, live_audit=runtime_audit
    )
    paths = save_final_season_integrity_report(report, args.output_dir)
    print(json.dumps({
        "ok": report["ok"],
        "summary": report["summary"],
        "checks": report["checks"],
        "outputs": paths,
    }, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
