from __future__ import annotations

import argparse
import json
from pathlib import Path

from .repository import DataRepository
from .season import SeasonOrchestrator
from .season_results import save_season_execution
from .browse_views import save_season_browse_views
from .browse_repository import save_season_browse_repository


def main():
    p = argparse.ArgumentParser(description="Phase 2 season end-to-end structural execution and audit")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--seed", type=int, default=2026100501)
    p.add_argument("--result-dir")
    p.add_argument(
        "--match-model",
        choices=("legacy", "ability"),
        default="legacy",
        help="tournament match resolver: legacy random winner or Stage 13 ability model",
    )
    p.add_argument(
        "--ability-config-dir",
        default="config/abilities",
        help="Stage 13 ability config directory used with --match-model ability",
    )
    p.add_argument(
        "--match-config-dir",
        default="config/match",
        help="Stage 13 match config directory used with --match-model ability",
    )
    p.add_argument("--sqlite-db", help="persist browse views and ability GameStats to SQLite")
    p.add_argument("--output")
    args = p.parse_args()

    data_dir = Path(args.data_dir)
    repo = DataRepository(data_dir)
    match_resolver = None
    if args.match_model == "ability":
        from game_core.tournament_bridge import AbilityMatchResolver

        match_resolver = AbilityMatchResolver(
            repo,
            ability_config_dir=args.ability_config_dir,
            match_config_dir=args.match_config_dir,
        )
    season = SeasonOrchestrator(
        repo,
        data_dir,
        match_resolver=match_resolver,
    ).run_structural_season(args.year, args.seed)
    if args.result_dir:
        save_season_execution(season, args.result_dir)
        save_season_browse_views(season, repo, data_dir, args.result_dir)
    if args.sqlite_db:
        save_season_browse_repository(
            season,
            repo,
            data_dir,
            args.sqlite_db,
        )
    payload = json.dumps(season.summary(), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
