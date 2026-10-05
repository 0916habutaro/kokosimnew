from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, List


@dataclass(frozen=True)
class ReconciliationStatus:
    competition_id: str
    prefecture_code: str
    prefecture: str
    latest_confirmed_date: str
    next_check_date: str
    status: str
    remaining_planned_dates: str
    remaining_count: int
    recheck_reason: str
    source_notes: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_reconciliation_queue(path: str | Path) -> List[dict]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _remaining_dates(row: dict) -> List[str]:
    values = [
        value.strip()
        for value in (row.get("remaining_planned_dates") or "").split(";")
        if value.strip()
    ]
    return sorted(dict.fromkeys(values))


def build_reconciliation_status(
    rows: Iterable[dict],
    as_of: date,
) -> List[ReconciliationStatus]:
    out: List[ReconciliationStatus] = []
    seen = set()

    for row in rows:
        competition_id = (row.get("competition_id") or "").strip()
        if not competition_id:
            raise ValueError("competition_id is required")
        if competition_id in seen:
            raise ValueError(f"duplicate competition_id: {competition_id}")
        seen.add(competition_id)

        remaining = _remaining_dates(row)
        for value in remaining:
            _parse_date(value)

        if not remaining:
            next_check = ""
            status = "complete"
            reason = "remaining_planned_datesが空のため再照合完了"
        else:
            next_check = remaining[0]
            next_date = _parse_date(next_check)
            if next_date < as_of:
                status = "recheck_due"
                reason = f"{next_check}の予定日を過ぎているため実績再照合が必要"
            elif next_date == as_of:
                status = "today_pending"
                reason = f"{next_check}が当日予定日のため試合終了後に実績再照合"
            else:
                status = "future_pending"
                reason = f"次回予定日{next_check}まで待機"

        out.append(ReconciliationStatus(
            competition_id=competition_id,
            prefecture_code=(row.get("prefecture_code") or "").strip(),
            prefecture=(row.get("prefecture") or "").strip(),
            latest_confirmed_date=(row.get("latest_confirmed_date") or "").strip(),
            next_check_date=next_check,
            status=status,
            remaining_planned_dates=";".join(remaining),
            remaining_count=len(remaining),
            recheck_reason=reason,
            source_notes=(row.get("notes") or "").strip(),
        ))

    return sorted(out, key=lambda x: (x.next_check_date or "9999-12-31", x.competition_id))


def write_reconciliation_status_csv(
    rows: Iterable[ReconciliationStatus],
    path: str | Path,
) -> None:
    items = list(rows)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(ReconciliationStatus.__dataclass_fields__)
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in items:
            writer.writerow(row.to_dict())


def summarize_reconciliation_status(rows: Iterable[ReconciliationStatus]) -> dict:
    items = list(rows)
    counts = {
        "complete": 0,
        "recheck_due": 0,
        "today_pending": 0,
        "future_pending": 0,
    }
    for row in items:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {
        "total": len(items),
        **counts,
        "next_check_date": min(
            (row.next_check_date for row in items if row.next_check_date),
            default="",
        ),
    }
