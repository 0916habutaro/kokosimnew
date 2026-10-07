from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from .abilities import (
    BATTER_ABILITIES,
    CATCHER_ABILITIES,
    PITCHER_ABILITIES,
    PlayerAbilitySnapshot,
)


@dataclass(frozen=True)
class AbilityAuditRow:
    seed: int
    dimension: str
    segment: str
    metric: str
    n: int
    mean: float
    stdev: float
    minimum: int
    p01: int
    p05: int
    p25: int
    p50: int
    p75: int
    p95: int
    p99: int
    maximum: int
    lower_bound: int
    upper_bound: int
    lower_clip_rate: float
    upper_clip_rate: float

    def to_dict(self) -> dict:
        return asdict(self)


def _percentile(sorted_values: list[int], q: float) -> int:
    if not sorted_values:
        raise ValueError("percentile requires at least one value")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(len(sorted_values) - 1, lower + 1)
    fraction = position - lower
    value = (
        sorted_values[lower] * (1.0 - fraction)
        + sorted_values[upper] * fraction
    )
    return int(round(value))


def _metric_bounds(metric: str) -> tuple[int, int]:
    if metric == "velocity_kmh":
        return 100, 165
    if metric == "pitch_count":
        return 2, 4
    if metric == "primary_position_aptitude":
        return 60, 100
    return 1, 100


def _row(
    *,
    seed: int,
    dimension: str,
    segment: str,
    metric: str,
    values: list[int],
) -> AbilityAuditRow:
    ordered = sorted(values)
    low, high = _metric_bounds(metric)
    return AbilityAuditRow(
        seed=seed,
        dimension=dimension,
        segment=segment,
        metric=metric,
        n=len(ordered),
        mean=round(statistics.fmean(ordered), 4),
        stdev=round(
            statistics.pstdev(ordered) if len(ordered) > 1 else 0.0,
            4,
        ),
        minimum=ordered[0],
        p01=_percentile(ordered, 0.01),
        p05=_percentile(ordered, 0.05),
        p25=_percentile(ordered, 0.25),
        p50=_percentile(ordered, 0.50),
        p75=_percentile(ordered, 0.75),
        p95=_percentile(ordered, 0.95),
        p99=_percentile(ordered, 0.99),
        maximum=ordered[-1],
        lower_bound=low,
        upper_bound=high,
        lower_clip_rate=round(
            sum(value == low for value in ordered) / len(ordered),
            6,
        ),
        upper_clip_rate=round(
            sum(value == high for value in ordered) / len(ordered),
            6,
        ),
    )


def audit_ability_snapshots(
    snapshots: Iterable[PlayerAbilitySnapshot],
    *,
    seed: int,
) -> list[AbilityAuditRow]:
    buckets: dict[tuple[str, str, str], list[int]] = defaultdict(list)

    def add(
        dimension: str,
        segment: str,
        metric: str,
        value: int,
    ) -> None:
        buckets[(dimension, segment, metric)].append(value)

    for snapshot in snapshots:
        scalar_metrics = [
            *BATTER_ABILITIES,
            *CATCHER_ABILITIES,
            *PITCHER_ABILITIES,
        ]
        for metric in scalar_metrics:
            value = snapshot.ability(metric)
            if value is None:
                continue
            add("overall", "all", metric, value)
            add("grade", str(snapshot.academic_year), metric, value)
            add(
                "position",
                snapshot.primary_position,
                metric,
                value,
            )

        primary_aptitude = snapshot.aptitude(
            snapshot.primary_position
        )
        add(
            "overall",
            "all",
            "primary_position_aptitude",
            primary_aptitude,
        )
        add(
            "grade",
            str(snapshot.academic_year),
            "primary_position_aptitude",
            primary_aptitude,
        )
        add(
            "position",
            snapshot.primary_position,
            "primary_position_aptitude",
            primary_aptitude,
        )

        if snapshot.primary_position == "P":
            add(
                "overall",
                "all",
                "pitch_count",
                len(snapshot.pitch_repertoire),
            )
            add(
                "grade",
                str(snapshot.academic_year),
                "pitch_count",
                len(snapshot.pitch_repertoire),
            )
            for pitch in snapshot.pitch_repertoire:
                add("overall", "all", "pitch_quality", pitch.quality)
                add("overall", "all", "pitch_command", pitch.command)
                add("overall", "all", "pitch_usage", pitch.usage)
                add(
                    "pitch_type",
                    pitch.pitch_type,
                    "pitch_quality",
                    pitch.quality,
                )
                add(
                    "pitch_type",
                    pitch.pitch_type,
                    "pitch_command",
                    pitch.command,
                )
                add(
                    "pitch_type",
                    pitch.pitch_type,
                    "pitch_usage",
                    pitch.usage,
                )

    rows = [
        _row(
            seed=seed,
            dimension=dimension,
            segment=segment,
            metric=metric,
            values=values,
        )
        for (dimension, segment, metric), values in buckets.items()
        if values
    ]
    return sorted(
        rows,
        key=lambda row: (
            row.dimension,
            row.segment,
            row.metric,
        ),
    )


def write_ability_audit_csv(
    rows: Iterable[AbilityAuditRow],
    path: str | Path,
) -> dict:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(AbilityAuditRow.__dataclass_fields__)

    count = 0
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())
            count += 1

    return {"audit_row_count": count, "output": str(output)}
