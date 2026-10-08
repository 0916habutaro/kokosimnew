"""Stage 13E-3F-4: full-season calendar and dependency integrity audit.

A known same-day pre-MAIN/MAIN overlap is valid only when explicitly
documented in known_same_day_stage_overlaps.csv. This avoids both
double-counting 1st-round-only dates and deleting legitimate parallel
matches from different stages on the same day.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _dates(raw: str, context: str, errors: list[str]) -> list[str]:
    values = [item for item in raw.split(";") if item]
    if not values:
        return values
    if values != sorted(set(values)):
        errors.append(f"{context}: dates must be unique and sorted")
    for value in values:
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError(value)
        except ValueError:
            errors.append(f"{context}: invalid ISO date {value}")
    return values


def build_final_season_integrity_report(
    data_dir: str | Path,
    *,
    year: int = 2026,
    live_audit: Any = None,
) -> dict[str, Any]:
    """Recompute independent CSV checks; optionally combine live E2E results.

    PASS means data consistency, DEFERRED is an explicitly tracked future
    publication/design item, and FAIL is an actionable data error.
    """
    root = Path(data_dir)
    calendar_dir = root / "schedules" / str(year)
    research_dir = root / "research" / str(year)
    competitions = [
        r for r in _rows(root / "competitions/competitions.csv")
        if r["reference_year"] == str(year)
    ]
    competition_by_id = {r["competition_id"]: r for r in competitions}
    stages = [
        r for r in _rows(root / "competitions/competition_stages.csv")
        if r["competition_id"] in competition_by_id
    ]
    stage_by_id = {r["stage_id"]: r for r in stages}
    main = _rows(calendar_dir / "season_calendar.csv")
    premain = _rows(calendar_dir / "competition_stage_calendar.csv")
    tasks = _rows(research_dir / "research_pending_queue.csv")
    overlap_rules = _rows(
        calendar_dir / "known_same_day_stage_overlaps.csv"
    )
    checks: list[dict[str, str]] = []

    def check(check_id: str, errors: list[str], success: str) -> None:
        checks.append({
            "check": check_id,
            "status": "FAIL" if errors else "PASS",
            "detail": "; ".join(errors) if errors else success,
        })

    # Referential and uniqueness contracts.
    ids = [r["competition_id"] for r in competitions]
    main_ids = [r["competition_id"] for r in main]
    stage_ids = [r["stage_calendar_id"] for r in premain]
    ref_errors = []
    if len(ids) != len(set(ids)):
        ref_errors.append("duplicate competition_id")
    if len(main_ids) != len(set(main_ids)):
        ref_errors.append("duplicate MAIN competition_id")
    if len(stage_ids) != len(set(stage_ids)):
        ref_errors.append("duplicate stage_calendar_id")
    if set(main_ids) != set(ids):
        ref_errors.append("MAIN calendar coverage differs from competitions")
    if any(r["stage_id"] not in stage_by_id for r in premain):
        ref_errors.append("pre-MAIN refers to unknown stage_id")
    for row in premain:
        stage = stage_by_id.get(row["stage_id"])
        if stage and (
            row["competition_id"] != stage["competition_id"]
            or row["stage_code"] != stage["stage_code"]
            or row["stage_code"] == "MAIN"
        ):
            ref_errors.append("mismatched stage " + row["stage_calendar_id"])
    check("calendar_referential_integrity", ref_errors,
          f"{len(competitions)} competitions and {len(premain)} stage rows")

    date_errors: list[str] = []
    main_by_comp = {r["competition_id"]: r for r in main}
    main_dates: dict[str, set[str]] = {}
    for row in main:
        name = "MAIN " + row["competition_id"]
        days = _dates(row["game_date_list"], name, date_errors)
        main_dates[row["competition_id"]] = set(days)
        if row["start_date"] and row["end_date"] and (
            row["start_date"] > row["end_date"]
        ):
            date_errors.append(name + ": start_date after end_date")
        for day in days:
            if not (row["start_date"] <= day <= row["end_date"]):
                date_errors.append(name + ": game_date out of MAIN period " + day)
            if not day.startswith(str(year) + "-"):
                date_errors.append(name + ": wrong reference year " + day)
    pre_days: dict[str, set[str]] = {}
    for row in premain:
        name = "pre-MAIN " + row["stage_calendar_id"]
        days = _dates(row["date_list"], name, date_errors)
        pre_days[row["stage_calendar_id"]] = set(days)
        if row["date_status"] != "verified" or not days:
            date_errors.append(name + ": not verified or no dates")
        for day in days:
            if not day.startswith(str(year) + "-"):
                date_errors.append(name + ": wrong reference year " + day)
    check("calendar_dates_and_status", date_errors,
          "sorted unique ISO game dates; all pre-MAIN stages verified")

    # Validate all same-day overlap exemptions against actual data.
    overlaps = {
        (row["competition_id"], row["stage_calendar_id"], day)
        for row in premain
        for day in (
            pre_days[row["stage_calendar_id"]]
            & main_dates.get(row["competition_id"], set())
        )
    }
    approved = {
        (r["competition_id"], r["stage_calendar_id"], r["date"])
        for r in overlap_rules
    }
    overlap_errors = []
    if len(approved) != len(overlap_rules):
        overlap_errors.append("duplicate same-day exception")
    for rule in overlap_rules:
        if not rule["reason"] or not rule["source_url"]:
            overlap_errors.append("missing evidence for " + rule["competition_id"])
    if overlaps - approved:
        overlap_errors.append("unapproved stage overlap: " + str(sorted(overlaps - approved)))
    if approved - overlaps:
        overlap_errors.append("stale stage exception: " + str(sorted(approved - overlaps)))
    check("pre_main_main_boundary", overlap_errors,
          f"{len(overlaps)} evidenced same-day overlap(s); no unapproved overlaps")

    # A stage-calendar task must be closed exactly when its stage is verified.
    stage_by_calendar_id = {r["stage_calendar_id"]: r for r in premain}
    stage_tasks = [t for t in tasks if t["task_type"] == "stage_calendar"]
    queue_errors = []
    seen_tasks: set[str] = set()
    for task in stage_tasks:
        sid = task["stage_calendar_id"]
        if sid in seen_tasks:
            queue_errors.append("duplicate stage task " + sid)
        seen_tasks.add(sid)
        stage = stage_by_calendar_id.get(sid)
        if stage is None:
            queue_errors.append("orphaned stage task " + sid)
        elif task["competition_id"] != stage["competition_id"]:
            queue_errors.append("stage task mismatch " + sid)
        elif task["status"] != "resolved":
            queue_errors.append("unresolved stage task " + sid)
    check("stage_research_queue", queue_errors,
          f"{len(stage_tasks)} stage research tasks resolved")

    # Open work is explicitly classified, never treated as completed.
    open_items = [
        {
            "task_id": t["task_id"],
            "task_type": t["task_type"],
            "competition_id": t["competition_id"],
            "status": t["status"],
            "review_not_before": t["review_not_before"],
        }
        for t in tasks if t["status"] != "resolved"
    ]
    blank_main = [
        r["competition_id"] for r in main
        if not r["game_date_list"]
    ]
    deferred_main = {
        t["competition_id"]
        for t in tasks
        if t["task_type"] == "main_calendar"
        and t["status"] == "awaiting_publication"
    }
    main_errors = []
    for cid in blank_main:
        if cid not in deferred_main:
            main_errors.append("untracked blank MAIN calendar " + cid)
    for cid in deferred_main:
        if cid not in blank_main:
            main_errors.append("outdated publication hold " + cid)
    check("deferred_main_publications", main_errors,
          f"{len(blank_main)} missing MAIN date list(s), all tracked")
    if open_items:
        checks.append({
            "check": "tracked_follow_up",
            "status": "DEFERRED",
            "detail": "; ".join(
                f'{r["task_id"]}:{r["task_type"]}:{r["status"]}'
                for r in open_items
            ),
        })

    summary = {
        "competition_count": len(competitions),
        "main_calendar_count": len(main),
        "pre_main_stage_count": len(premain),
        "verified_pre_main_stage_count": sum(
            r["date_status"] == "verified" for r in premain
        ),
        "pending_pre_main_stage_count": sum(
            r["date_status"] != "verified" for r in premain
        ),
        "stage_research_task_count": len(stage_tasks),
        "open_research_count": len(open_items),
        "known_same_day_overlap_count": len(approved),
        "blank_main_calendar_count": len(blank_main),
    }
    live_summary = None
    if live_audit is not None:
        live_summary = live_audit.summary()
        blocked_ids = sorted(
            r.competition_id for r in live_audit.competition_rows
            if r.blocker_kind != "complete"
        )
        runtime_errors = []
        if live_summary["competition_count"] != len(competitions):
            runtime_errors.append("runtime and master competition totals differ")
        if live_summary["pending_stage_row_count"] != summary[
            "pending_pre_main_stage_count"
        ]:
            runtime_errors.append("runtime and CSV pending stages differ")
        if live_summary["completed_competition_count"] + len(blocked_ids) != len(competitions):
            runtime_errors.append("completed and blocked counts differ")
        if set(blocked_ids) != set(blank_main):
            runtime_errors.append("runtime blocked IDs differ from blank MAIN calendars")
        if live_summary["unique_downstream_blocked_competition_count"] != 0:
            runtime_errors.append("downstream dependency still blocked")
        if live_summary["dependency_wait_competition_count"] != 0:
            runtime_errors.append("upstream dependency still waiting")
        check("full_season_live_dependencies", runtime_errors,
              f'{live_summary["completed_competition_count"]}/{len(competitions)} '
              'simulated competitions complete; no downstream waits')
        summary["simulated_completed_competition_count"] = (
            live_summary["completed_competition_count"]
        )
        summary["simulated_incomplete_competition_ids"] = blocked_ids
        summary["simulated_completed_match_count"] = live_summary[
            "completed_match_count"
        ]
    return {
        "year": year,
        "checks": checks,
        "ok": not any(c["status"] == "FAIL" for c in checks),
        "summary": summary,
        "same_day_overlaps": [
            {"competition_id": cid, "stage_calendar_id": sid, "date": day}
            for cid, sid, day in sorted(overlaps)
        ],
        "open_research": open_items,
        "live_summary": live_summary,
    }


def save_final_season_integrity_report(
    report: dict[str, Any], output_dir: str | Path
) -> dict[str, str]:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    summary_path = path / "final_season_integrity_summary.json"
    checks_path = path / "final_season_integrity_checks.csv"
    summary_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with checks_path.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=("check", "status", "detail"))
        writer.writeheader()
        writer.writerows(report["checks"])
    return {"summary": str(summary_path), "checks": str(checks_path)}
