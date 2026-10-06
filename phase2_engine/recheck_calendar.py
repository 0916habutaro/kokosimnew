from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, List


@dataclass(frozen=True)
class RecheckDueItem:
    tracking_id: str
    tracking_scope: str
    tracking_stage: str
    competition_id: str
    competition_name: str
    latest_confirmed_date: str
    next_scheduled_date: str
    final_scheduled_date: str
    due_status: str
    remaining_planned_dates: str
    schedule_source_id: str
    shared_competition: str
    notes: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_recheck_calendar(path: str | Path) -> List[dict]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _planned_dates(row: dict) -> List[str]:
    values = [
        value.strip()
        for value in (row.get("remaining_planned_dates") or "").split(";")
        if value.strip()
    ]
    return values


def validate_recheck_calendar(rows: Iterable[dict]) -> List[dict]:
    items = list(rows)
    seen_tracking_ids = set()

    for row in items:
        tracking_id = (row.get("tracking_id") or "").strip()
        competition_id = (row.get("competition_id") or "").strip()
        if not tracking_id:
            raise ValueError("tracking_id is required")
        if tracking_id in seen_tracking_ids:
            raise ValueError(f"duplicate tracking_id: {tracking_id}")
        seen_tracking_ids.add(tracking_id)
        if not competition_id:
            raise ValueError(f"competition_id is required: {tracking_id}")

        dates = _planned_dates(row)
        if not dates:
            raise ValueError(f"remaining_planned_dates is required: {tracking_id}")
        for value in dates:
            _parse_date(value)
        if dates != sorted(dates):
            raise ValueError(f"remaining_planned_dates must be sorted: {tracking_id}")
        if len(dates) != len(set(dates)):
            raise ValueError(f"duplicate planned date: {tracking_id}")

        next_date = (row.get("next_scheduled_date") or "").strip()
        final_date = (row.get("final_scheduled_date") or "").strip()
        if next_date != dates[0]:
            raise ValueError(f"next_scheduled_date must equal first planned date: {tracking_id}")
        if final_date != dates[-1]:
            raise ValueError(f"final_scheduled_date must equal last planned date: {tracking_id}")

    return items


def build_due_queue(
    rows: Iterable[dict],
    as_of: date,
) -> List[RecheckDueItem]:
    items = validate_recheck_calendar(rows)
    out: List[RecheckDueItem] = []

    for row in items:
        next_value = (row.get("next_scheduled_date") or "").strip()
        next_date = _parse_date(next_value)
        if next_date > as_of:
            continue

        due_status = "today_pending" if next_date == as_of else "overdue"
        out.append(RecheckDueItem(
            tracking_id=(row.get("tracking_id") or "").strip(),
            tracking_scope=(row.get("tracking_scope") or "").strip(),
            tracking_stage=(row.get("tracking_stage") or "").strip(),
            competition_id=(row.get("competition_id") or "").strip(),
            competition_name=(row.get("competition_name") or "").strip(),
            latest_confirmed_date=(row.get("latest_confirmed_date") or "").strip(),
            next_scheduled_date=next_value,
            final_scheduled_date=(row.get("final_scheduled_date") or "").strip(),
            due_status=due_status,
            remaining_planned_dates=";".join(_planned_dates(row)),
            schedule_source_id=(row.get("schedule_source_id") or "").strip(),
            shared_competition=(row.get("shared_competition") or "").strip(),
            notes=(row.get("notes") or "").strip(),
        ))

    return sorted(
        out,
        key=lambda x: (
            x.next_scheduled_date,
            x.tracking_scope,
            x.competition_id,
            x.tracking_id,
        ),
    )


def summarize_due_queue(
    due_rows: Iterable[RecheckDueItem],
    calendar_rows: Iterable[dict],
    as_of: date,
) -> dict:
    due = list(due_rows)
    calendar = validate_recheck_calendar(calendar_rows)
    future_dates = [
        (row.get("next_scheduled_date") or "").strip()
        for row in calendar
        if _parse_date((row.get("next_scheduled_date") or "").strip()) > as_of
    ]
    return {
        "as_of": as_of.isoformat(),
        "total_tracking": len(calendar),
        "due_count": len(due),
        "today_pending": sum(row.due_status == "today_pending" for row in due),
        "overdue": sum(row.due_status == "overdue" for row in due),
        "unique_due_competitions": len({row.competition_id for row in due}),
        "next_future_date": min(future_dates, default=""),
    }


def write_due_queue_csv(
    rows: Iterable[RecheckDueItem],
    path: str | Path,
) -> None:
    items = list(rows)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(RecheckDueItem.__dataclass_fields__)
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in items:
            writer.writerow(row.to_dict())
