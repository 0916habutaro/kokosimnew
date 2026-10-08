from __future__ import annotations

import csv
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

from .paths import resolve_data_file
from .repository import DataRepository


STAGE_DATE_VERIFIED = "verified"
STAGE_DATE_PENDING = "research_pending"
STAGE_DATE_NOT_APPLICABLE = "not_applicable"
VALID_STAGE_DATE_STATUSES = {
    STAGE_DATE_VERIFIED,
    STAGE_DATE_PENDING,
    STAGE_DATE_NOT_APPLICABLE,
}


def _split_dates(value: str) -> list[str]:
    dates = [
        item.strip()
        for item in (value or "").split(";")
        if item.strip()
    ]
    for item in dates:
        date.fromisoformat(item)
    if dates != sorted(dates):
        raise ValueError("stage date_list must be sorted")
    if len(dates) != len(set(dates)):
        raise ValueError(
            "stage date_list contains duplicate dates"
        )
    return dates


def load_competition_stage_calendar(
    data_dir: str | Path,
    *,
    year: int = 2026,
) -> list[dict]:
    path = resolve_data_file(
        data_dir,
        "competition_stage_calendar.csv",
    )
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        rows = list(csv.DictReader(f))
    return [
        row
        for row in rows
        if int(row.get("reference_year") or 0)
        == year
    ]


def validate_competition_stage_calendar(
    repo: DataRepository,
    rows: Iterable[Mapping[str, str]],
    *,
    year: int = 2026,
) -> dict:
    items = [dict(row) for row in rows]
    ids = [row.get("stage_calendar_id", "") for row in items]
    stage_ids = [row.get("stage_id", "") for row in items]
    if any(not value for value in ids):
        raise ValueError(
            "stage_calendar_id is required"
        )
    if len(ids) != len(set(ids)):
        raise ValueError(
            "duplicate stage_calendar_id"
        )
    if len(stage_ids) != len(set(stage_ids)):
        raise ValueError(
            "duplicate stage_id in stage calendar"
        )

    expected = {}
    for competition_id, competition in repo.competitions.items():
        if int(competition.get("reference_year") or 0) != year:
            continue
        for stage in repo.stages(competition_id):
            if stage["stage_code"] == "MAIN":
                continue
            expected[stage["stage_id"]] = stage

    seen = {}
    for row in items:
        if int(row.get("reference_year") or 0) != year:
            raise ValueError(
                "stage calendar row has unexpected year"
            )
        stage_id = row.get("stage_id", "")
        if stage_id not in expected:
            raise ValueError(
                f"unknown/non-pre-MAIN stage_id: {stage_id}"
            )
        stage = expected[stage_id]
        if row.get("competition_id") != stage["competition_id"]:
            raise ValueError(
                f"{stage_id}: competition_id mismatch"
            )
        if row.get("stage_code") != stage["stage_code"]:
            raise ValueError(
                f"{stage_id}: stage_code mismatch"
            )

        status = row.get("date_status", "")
        if status not in VALID_STAGE_DATE_STATUSES:
            raise ValueError(
                f"{stage_id}: invalid date_status={status}"
            )
        dates = _split_dates(
            row.get("date_list", "")
        )
        if status == STAGE_DATE_VERIFIED and not dates:
            raise ValueError(
                f"{stage_id}: verified stage requires date_list"
            )
        if status != STAGE_DATE_VERIFIED and dates:
            raise ValueError(
                f"{stage_id}: unverified stage cannot carry dates"
            )
        seen[stage_id] = row

    missing = sorted(set(expected) - set(seen))
    extra = sorted(set(seen) - set(expected))
    if missing or extra:
        raise ValueError(
            "stage calendar coverage mismatch: "
            f"missing={missing} extra={extra}"
        )

    counts = Counter(
        row["date_status"]
        for row in items
    )
    relation_counts = Counter(
        row.get("calendar_relation", "")
        for row in items
    )
    return {
        "reference_year": year,
        "pre_main_stage_count": len(expected),
        "row_count": len(items),
        "verified_count": counts[STAGE_DATE_VERIFIED],
        "research_pending_count": counts[
            STAGE_DATE_PENDING
        ],
        "not_applicable_count": counts[
            STAGE_DATE_NOT_APPLICABLE
        ],
        "calendar_relation_counts": dict(
            sorted(relation_counts.items())
        ),
    }


def stage_date_lists_by_competition(
    rows: Iterable[Mapping[str, str]],
    *,
    include_pending: bool = True,
) -> dict[str, dict[str, list[str]]]:
    output: dict[str, dict[str, list[str]]] = {}
    for raw in rows:
        row = dict(raw)
        status = row.get("date_status", "")
        if status == STAGE_DATE_NOT_APPLICABLE:
            continue
        if (
            status != STAGE_DATE_VERIFIED
            and not include_pending
        ):
            continue
        dates = (
            _split_dates(row.get("date_list", ""))
            if status == STAGE_DATE_VERIFIED
            else []
        )
        output.setdefault(
            row["competition_id"],
            {},
        )[row["stage_code"]] = dates
    return output
