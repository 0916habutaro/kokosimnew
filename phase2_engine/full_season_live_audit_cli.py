from __future__ import annotations

import argparse
import json
from pathlib import Path

from .full_season_live_audit import (
    audit_full_season_live_runtime,
    save_full_season_live_audit,
)
from .live_season_planner import (
    LiveSeasonGraphPlanner,
)
from .repository import DataRepository


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit full-season live runtime blockers"
        )
    )
    parser.add_argument(
        "--data-dir",
        default="data",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2026,
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=2026100827,
    )
    parser.add_argument(
        "--output-dir",
        default=(
            "out/full_season_live_audit"
        ),
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    repo = DataRepository(data_dir)
    plan = LiveSeasonGraphPlanner(
        repo,
        data_dir,
        args.seed,
        year=args.year,
    ).build_plan()
    audit = audit_full_season_live_runtime(
        plan
    )
    paths = save_full_season_live_audit(
        audit,
        args.output_dir,
    )
    payload = {
        "summary": audit.summary(),
        "outputs": paths,
    }
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
