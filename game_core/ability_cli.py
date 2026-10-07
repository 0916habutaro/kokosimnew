from __future__ import annotations

import argparse
import json
from itertools import islice
from pathlib import Path
from typing import Iterator

from phase2_engine.repository import DataRepository

from .abilities import (
    PlayerAbilityGenerator,
    PlayerAbilitySnapshot,
    write_ability_snapshots_csv,
)
from .ability_audit import (
    audit_ability_snapshots,
    write_ability_audit_csv,
)
from .players import PlayerRosterGenerator


def _iter_snapshots(
    repo: DataRepository,
    ability_generator: PlayerAbilityGenerator,
    roster_generator: PlayerRosterGenerator,
    *,
    year: int,
    seed: int,
    school_id: str = "",
    school_limit: int | None = None,
) -> Iterator[PlayerAbilitySnapshot]:
    if school_id:
        roster = roster_generator.generate_for_school_id(
            repo,
            school_id,
            year,
            seed,
        )
        yield from ability_generator.iter_roster(
            roster.players,
            year,
            seed,
        )
        return

    rosters = roster_generator.iter_all_rosters(repo, year, seed)
    if school_limit is not None:
        rosters = islice(rosters, school_limit)
    for roster in rosters:
        yield from ability_generator.iter_roster(
            roster.players,
            year,
            seed,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and audit deterministic player abilities"
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--config-dir", default="config/abilities")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--school-id", default="")
    parser.add_argument("--school-limit", type=int)
    parser.add_argument("--output")
    parser.add_argument("--audit-output")
    args = parser.parse_args()

    if not args.output and not args.audit_output:
        parser.error("--output or --audit-output is required")
    if args.school_limit is not None and args.school_limit < 1:
        parser.error("--school-limit must be >= 1")
    if args.school_id and args.school_limit is not None:
        parser.error("--school-id and --school-limit cannot be combined")

    repo = DataRepository(Path(args.data_dir))
    roster_generator = PlayerRosterGenerator()
    ability_generator = PlayerAbilityGenerator(Path(args.config_dir))

    summary: dict[str, object] = {
        "reference_year": args.year,
        "seed": args.seed,
        "school_id": args.school_id,
        "school_limit": args.school_limit,
    }

    def snapshots():
        return _iter_snapshots(
            repo,
            ability_generator,
            roster_generator,
            year=args.year,
            seed=args.seed,
            school_id=args.school_id,
            school_limit=args.school_limit,
        )

    if args.output:
        summary["snapshot_export"] = write_ability_snapshots_csv(
            snapshots(),
            args.output,
        )

    if args.audit_output:
        rows = audit_ability_snapshots(
            snapshots(),
            seed=args.seed,
        )
        summary["audit_export"] = write_ability_audit_csv(
            rows,
            args.audit_output,
        )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
