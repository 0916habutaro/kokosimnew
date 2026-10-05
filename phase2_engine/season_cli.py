from __future__ import annotations

import argparse
import json
from pathlib import Path

from .repository import DataRepository
from .season import SeasonOrchestrator
from .season_results import save_season_execution


def main():
    p = argparse.ArgumentParser(description="Phase 2 season end-to-end structural execution and audit")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--seed", type=int, default=2026100501)
    p.add_argument("--result-dir")
    p.add_argument("--output")
    args = p.parse_args()

    data_dir = Path(args.data_dir)
    repo = DataRepository(data_dir)
    season = SeasonOrchestrator(repo, data_dir).run_structural_season(args.year, args.seed)
    if args.result_dir:
        save_season_execution(season, args.result_dir)
    payload = json.dumps(season.summary(), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
