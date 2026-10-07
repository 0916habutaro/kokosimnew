from __future__ import annotations

import csv
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .team_strength import TEAM_STRENGTH_METRICS, TeamStrengthSnapshot


@dataclass(frozen=True)
class TeamStrengthAuditRow:
    seed: int
    metric: str
    n: int
    mean: float
    stdev: float
    p05: float
    p50: float
    p95: float
    min: float
    max: float

    def to_dict(self) -> dict:
        return asdict(self)


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires values")
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


def audit_team_strength_snapshots(
    snapshots: Iterable[TeamStrengthSnapshot],
    *,
    seed: int,
) -> list[TeamStrengthAuditRow]:
    buckets = {metric: [] for metric in TEAM_STRENGTH_METRICS}
    for snapshot in snapshots:
        for metric in TEAM_STRENGTH_METRICS:
            buckets[metric].append(float(getattr(snapshot, metric)))

    rows: list[TeamStrengthAuditRow] = []
    for metric, values in buckets.items():
        if not values:
            continue
        rows.append(
            TeamStrengthAuditRow(
                seed=seed,
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
                min=round(min(values), 2),
                max=round(max(values), 2),
            )
        )
    return rows


def write_team_strength_audit_csv(
    rows: Iterable[TeamStrengthAuditRow],
    path: str | Path,
) -> dict:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(TeamStrengthAuditRow.__dataclass_fields__)
    count = 0
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())
            count += 1
    return {"audit_row_count": count, "output": str(output)}
