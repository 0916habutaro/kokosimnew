from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from .abilities import PlayerAbilityGenerator
from .players import Player
from .school_intake import SchoolAwarePlayerAbilityGenerator
from .team_strength import TEAM_STRENGTH_METRICS, TeamStrengthGenerator


POSITIONS = (
    "P", "P", "P", "P", "P",
    "C", "C",
    "1B",
    "2B", "2B",
    "3B", "3B",
    "SS", "SS",
    "LF", "LF",
    "CF", "CF",
    "RF", "RF",
)


@dataclass(frozen=True)
class Stage13B4AuditRow:
    seed: int
    model: str
    metric: str
    n: int
    mean: float
    stdev: float
    p05: float
    p50: float
    p95: float
    minimum: float
    maximum: float

    def to_dict(self) -> dict:
        return asdict(self)


def _position_group(position: str) -> str:
    if position == "P":
        return "pitcher"
    if position == "C":
        return "catcher"
    if position in {"1B", "2B", "3B", "SS"}:
        return "infielder"
    return "outfielder"


def _make_roster(
    *,
    school_id: str,
    reference_year: int,
    seed: int,
) -> list[Player]:
    grade_slots = [1] * 5 + [2] * 7 + [3] * 8
    players: list[Player] = []
    for index, position in enumerate(POSITIONS, start=1):
        grade = grade_slots[index - 1]
        players.append(
            Player(
                player_id=f"{school_id}:PLY:{index:02d}",
                school_id=school_id,
                program_id=f"{school_id}:PRG",
                display_name=f"監査選手{index:02d}",
                name_source="stage13b4_audit",
                academic_year=grade,
                entry_year=reference_year - grade + 1,
                roster_no=index,
                primary_position=position,
                position_group=_position_group(position),
                bats="R",
                throws="R",
                roster_status="active_core",
                generation_seed=seed,
            )
        )
    return players


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return (
        float(ordered[lower])
        + (float(ordered[upper]) - float(ordered[lower])) * fraction
    )


def _summarize(
    *,
    seed: int,
    model: str,
    metric: str,
    values: list[float],
) -> Stage13B4AuditRow:
    return Stage13B4AuditRow(
        seed=seed,
        model=model,
        metric=metric,
        n=len(values),
        mean=round(statistics.fmean(values), 4),
        stdev=round(
            statistics.pstdev(values) if len(values) > 1 else 0.0,
            4,
        ),
        p05=round(_percentile(values, 0.05), 2),
        p50=round(_percentile(values, 0.50), 2),
        p95=round(_percentile(values, 0.95), 2),
        minimum=round(min(values), 2),
        maximum=round(max(values), 2),
    )


def run_audit(
    *,
    config_dir: str | Path,
    reference_year: int,
    seed: int,
    school_count: int,
) -> list[Stage13B4AuditRow]:
    if school_count < 1:
        raise ValueError("school_count must be >= 1")

    baseline_generator = PlayerAbilityGenerator(config_dir)
    intake_generator = SchoolAwarePlayerAbilityGenerator(config_dir)
    team_generator = TeamStrengthGenerator(config_dir)

    buckets: dict[str, dict[str, list[float]]] = {
        "baseline": {
            metric: [] for metric in TEAM_STRENGTH_METRICS
        },
        "school_intake_v1": {
            metric: [] for metric in TEAM_STRENGTH_METRICS
        },
    }
    intake_quality: list[float] = []
    program_quality: list[float] = []

    for index in range(school_count):
        school_id = f"SYN_AUDIT_{index:05d}"
        roster = _make_roster(
            school_id=school_id,
            reference_year=reference_year,
            seed=seed,
        )
        baseline_abilities = list(
            baseline_generator.iter_roster(
                roster,
                reference_year,
                seed,
            )
        )
        intake_abilities = list(
            intake_generator.iter_roster(
                roster,
                reference_year,
                seed,
            )
        )
        baseline_team = team_generator.generate(baseline_abilities)
        intake_team = team_generator.generate(intake_abilities)

        for metric in TEAM_STRENGTH_METRICS:
            buckets["baseline"][metric].append(
                float(getattr(baseline_team, metric))
            )
            buckets["school_intake_v1"][metric].append(
                float(getattr(intake_team, metric))
            )

        intake_quality.append(
            statistics.fmean(
                player.intake_quality_z
                for player in intake_abilities
            )
        )
        program_quality.append(
            intake_abilities[0].intake_program_quality_z
        )

    rows: list[Stage13B4AuditRow] = []
    for model, metrics in buckets.items():
        for metric in TEAM_STRENGTH_METRICS:
            rows.append(
                _summarize(
                    seed=seed,
                    model=model,
                    metric=metric,
                    values=metrics[metric],
                )
            )
    rows.append(
        _summarize(
            seed=seed,
            model="school_intake_v1",
            metric="roster_mean_intake_quality_z",
            values=intake_quality,
        )
    )
    rows.append(
        _summarize(
            seed=seed,
            model="school_intake_v1",
            metric="program_quality_z",
            values=program_quality,
        )
    )
    return rows


def write_audit_csv(
    rows: list[Stage13B4AuditRow],
    path: str | Path,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(Stage13B4AuditRow.__dataclass_fields__),
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage 13B-4 baseline/intake team-strength distribution audit"
    )
    parser.add_argument("--config-dir", default="config/abilities")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument(
        "--seeds",
        default="2026100701,2026100702,2026100703",
    )
    parser.add_argument("--school-count", type=int, default=1000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    seeds = [
        int(value.strip())
        for value in args.seeds.split(",")
        if value.strip()
    ]
    if not seeds:
        parser.error("--seeds must contain at least one integer")

    rows: list[Stage13B4AuditRow] = []
    for seed in seeds:
        rows.extend(
            run_audit(
                config_dir=args.config_dir,
                reference_year=args.year,
                seed=seed,
                school_count=args.school_count,
            )
        )
    write_audit_csv(rows, args.output)

    summary = {
        "reference_year": args.year,
        "seeds": seeds,
        "school_count_per_seed": args.school_count,
        "audit_row_count": len(rows),
        "output": args.output,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
