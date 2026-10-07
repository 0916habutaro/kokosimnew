from __future__ import annotations

import argparse
import json
from pathlib import Path

from phase2_engine.repository import DataRepository

from .players import PlayerRosterGenerator, write_players_csv


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate deterministic fictional high-school rosters"
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--school-id",
        help="Generate one school. Omit to generate all active hardball schools.",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo = DataRepository(Path(args.data_dir))
    generator = PlayerRosterGenerator()

    if args.school_id:
        rosters = [
            generator.generate_for_school_id(
                repo,
                args.school_id,
                args.year,
                args.seed,
            )
        ]
    else:
        rosters = generator.iter_all_rosters(
            repo,
            args.year,
            args.seed,
        )

    summary = write_players_csv(rosters, args.output)
    summary.update(
        {
            "reference_year": args.year,
            "seed": args.seed,
            "school_id": args.school_id or "",
        }
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
