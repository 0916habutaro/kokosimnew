from __future__ import annotations

import argparse
import json
from itertools import islice
from pathlib import Path
from typing import Iterator

from phase2_engine.repository import DataRepository

from .abilities import PlayerAbilityGenerator
from .players import PlayerRosterGenerator
from .school_intake import SchoolAwarePlayerAbilityGenerator
from .team_strength import (
    TeamStrengthGenerator,
    TeamStrengthSnapshot,
    write_team_strength_csv,
)
from .team_strength_audit import (
    audit_team_strength_snapshots,
    write_team_strength_audit_csv,
)


def _iter_snapshots(
    repo: DataRepository,
    team_generator: TeamStrengthGenerator,
    ability_generator: PlayerAbilityGenerator,
    roster_generator: PlayerRosterGenerator,
    *,
    year: int,
    seed: int,
    school_id: str = "",
    school_limit: int | None = None,
) -> Iterator[TeamStrengthSnapshot]:
    if school_id:
        roster = roster_generator.generate_for_school_id(
            repo, school_id, year, seed
        )
        abilities = list(
            ability_generator.iter_roster(roster.players, year, seed)
        )
        yield team_generator.generate(abilities)
        return

    rosters = roster_generator.iter_all_rosters(repo, year, seed)
    if school_limit is not None:
        rosters = islice(rosters, school_limit)
    for roster in rosters:
        abilities = list(
            ability_generator.iter_roster(roster.players, year, seed)
        )
        yield team_generator.generate(abilities)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate deterministic starting lineups, pitching staffs "
            "and team strengths"
        )
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--config-dir", default="config/abilities")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--school-id", default="")
    parser.add_argument("--school-limit", type=int)
    parser.add_argument("--output")
    parser.add_argument("--audit-output")
    parser.add_argument(
        "--baseline-no-school-intake",
        action="store_true",
        help="Disable Stage 13B-4 school intake adjustments for baseline audit",
    )
    args = parser.parse_args()

    if not args.output and not args.audit_output:
        parser.error("--output or --audit-output is required")
    if args.school_limit is not None and args.school_limit < 1:
        parser.error("--school-limit must be >= 1")
    if args.school_id and args.school_limit is not None:
        parser.error("--school-id and --school-limit cannot be combined")

    repo = DataRepository(Path(args.data_dir))
    roster_generator = PlayerRosterGenerator()
    ability_generator = (
        PlayerAbilityGenerator(Path(args.config_dir))
        if args.baseline_no_school_intake
        else SchoolAwarePlayerAbilityGenerator(Path(args.config_dir))
    )
    team_generator = TeamStrengthGenerator(Path(args.config_dir))

    summary: dict[str, object] = {
        "reference_year": args.year,
        "seed": args.seed,
        "school_id": args.school_id,
        "school_limit": args.school_limit,
        "school_intake_enabled": not args.baseline_no_school_intake,
    }

    def snapshots():
        return _iter_snapshots(
            repo,
            team_generator,
            ability_generator,
            roster_generator,
            year=args.year,
            seed=args.seed,
            school_id=args.school_id,
            school_limit=args.school_limit,
        )

    if args.output:
        summary["snapshot_export"] = write_team_strength_csv(
            snapshots(), args.output
        )

    if args.audit_output:
        rows = audit_team_strength_snapshots(
            snapshots(), seed=args.seed
        )
        summary["audit_export"] = write_team_strength_audit_csv(
            rows, args.audit_output
        )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
