from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .live_season_dependency import (
    DEPENDENCY_BLOCKED,
    DEPENDENCY_BLOCKED_DATE,
    DEPENDENCY_WAITING,
    DEPENDENCY_WAITING_EXTERNAL,
)
from .live_season_planner import (
    LiveSeasonGraphPlan,
)


BLOCKER_COMPLETE = "complete"
BLOCKER_CALENDAR_GAP = "calendar_gap"
BLOCKER_WAITING_DEPENDENCY = "waiting_dependency"
BLOCKER_BLOCKED = "blocked"
BLOCKER_INCOMPLETE_ACTIVE = "incomplete_active"

PRIORITY_NATIONAL = "P0_national_chain"
PRIORITY_REGIONAL = "P1_regional_chain"
PRIORITY_LOCAL = "P2_local_only"


@dataclass(frozen=True)
class CompetitionBlockerAuditRow:
    competition_id: str
    competition_name: str
    competition_type: str
    season_segment: str
    runtime_status: str
    blocker_kind: str
    is_active: bool
    is_complete: bool
    calendar_gap_count: int
    pending_stage_ids: tuple[str, ...]
    pending_stage_codes: tuple[str, ...]
    unresolved_source_competition_ids: tuple[str, ...]
    downstream_blocked_competition_ids: tuple[str, ...]
    downstream_national_competition_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "competition_id": self.competition_id,
            "competition_name": self.competition_name,
            "competition_type": self.competition_type,
            "season_segment": self.season_segment,
            "runtime_status": self.runtime_status,
            "blocker_kind": self.blocker_kind,
            "is_active": self.is_active,
            "is_complete": self.is_complete,
            "calendar_gap_count": self.calendar_gap_count,
            "pending_stage_ids": list(
                self.pending_stage_ids
            ),
            "pending_stage_codes": list(
                self.pending_stage_codes
            ),
            "unresolved_source_competition_ids": list(
                self.unresolved_source_competition_ids
            ),
            "downstream_blocked_competition_ids": list(
                self.downstream_blocked_competition_ids
            ),
            "downstream_national_competition_ids": list(
                self.downstream_national_competition_ids
            ),
        }


@dataclass(frozen=True)
class StageCalendarPriorityRow:
    stage_calendar_id: str
    competition_id: str
    competition_name: str
    competition_type: str
    season_segment: str
    stage_id: str
    stage_code: str
    calendar_relation: str
    primary_source_id: str
    priority_tier: str
    downstream_blocked_competition_count: int
    downstream_blocked_competition_ids: tuple[str, ...]
    downstream_national_competition_ids: tuple[str, ...]
    calendar_gap_count: int

    def to_dict(self) -> dict:
        return {
            "stage_calendar_id": self.stage_calendar_id,
            "competition_id": self.competition_id,
            "competition_name": self.competition_name,
            "competition_type": self.competition_type,
            "season_segment": self.season_segment,
            "stage_id": self.stage_id,
            "stage_code": self.stage_code,
            "calendar_relation": self.calendar_relation,
            "primary_source_id": self.primary_source_id,
            "priority_tier": self.priority_tier,
            "downstream_blocked_competition_count": (
                self.downstream_blocked_competition_count
            ),
            "downstream_blocked_competition_ids": list(
                self.downstream_blocked_competition_ids
            ),
            "downstream_national_competition_ids": list(
                self.downstream_national_competition_ids
            ),
            "calendar_gap_count": self.calendar_gap_count,
        }


@dataclass
class FullSeasonLiveBlockerAudit:
    plan: LiveSeasonGraphPlan
    state: object
    competition_rows: list[CompetitionBlockerAuditRow]
    stage_priority_rows: list[StageCalendarPriorityRow]
    progress: dict

    def summary(self) -> dict:
        blocker_counts: dict[str, int] = {}
        for row in self.competition_rows:
            blocker_counts[row.blocker_kind] = (
                blocker_counts.get(
                    row.blocker_kind,
                    0,
                )
                + 1
            )

        priority_counts: dict[str, int] = {}
        for row in self.stage_priority_rows:
            priority_counts[row.priority_tier] = (
                priority_counts.get(
                    row.priority_tier,
                    0,
                )
                + 1
            )

        blocked_ids = {
            row.competition_id
            for row in self.competition_rows
            if row.blocker_kind
            != BLOCKER_COMPLETE
        }
        downstream_blocked_ids = {
            destination
            for row in self.competition_rows
            if row.blocker_kind
            == BLOCKER_CALENDAR_GAP
            for destination in (
                row.downstream_blocked_competition_ids
            )
        }
        national_blocked_ids = sorted({
            destination
            for row in self.competition_rows
            for destination in (
                row.downstream_national_competition_ids
            )
        })

        return {
            "year": self.plan.year,
            "rng_seed": self.plan.rng_seed,
            "processed_through": self.progress.get(
                "processed_through",
                "",
            ),
            "competition_count": len(
                self.competition_rows
            ),
            "completed_competition_count": (
                blocker_counts.get(
                    BLOCKER_COMPLETE,
                    0,
                )
            ),
            "blocked_competition_count": len(
                blocked_ids
            ),
            "blocker_counts": dict(
                sorted(blocker_counts.items())
            ),
            "pending_stage_row_count": len(
                self.stage_priority_rows
            ),
            "pending_stage_competition_count": len({
                row.competition_id
                for row in self.stage_priority_rows
            }),
            "priority_counts": dict(
                sorted(priority_counts.items())
            ),
            "direct_calendar_gap_competition_count": (
                blocker_counts.get(
                    BLOCKER_CALENDAR_GAP,
                    0,
                )
            ),
            "dependency_wait_competition_count": (
                blocker_counts.get(
                    BLOCKER_WAITING_DEPENDENCY,
                    0,
                )
            ),
            "unique_downstream_blocked_competition_count": (
                len(downstream_blocked_ids)
            ),
            "unique_downstream_blocked_competition_ids": (
                sorted(downstream_blocked_ids)
            ),
            "blocked_national_competition_ids": (
                national_blocked_ids
            ),
            "completed_match_count": len(
                self.state.completed_results()
            ),
        }

    def public_snapshot(self) -> dict:
        return {
            "summary": self.summary(),
            "competition_rows": [
                row.to_dict()
                for row in self.competition_rows
            ],
            "stage_priority_rows": [
                row.to_dict()
                for row in self.stage_priority_rows
            ],
        }


def _descendants(
    adjacency: dict[str, set[str]],
    source: str,
) -> tuple[str, ...]:
    seen: set[str] = set()
    queue = [source]
    while queue:
        current = queue.pop(0)
        for destination in sorted(
            adjacency.get(
                current,
                set(),
            )
        ):
            if destination in seen:
                continue
            seen.add(destination)
            queue.append(destination)
    return tuple(sorted(seen))


def _competition_name(
    plan: LiveSeasonGraphPlan,
    competition_id: str,
) -> str:
    return str(
        plan.repo.competitions.get(
            competition_id,
            {},
        ).get(
            "competition_name",
            competition_id,
        )
    )


def _competition_type(
    plan: LiveSeasonGraphPlan,
    competition_id: str,
) -> str:
    return str(
        plan.repo.competitions.get(
            competition_id,
            {},
        ).get(
            "competition_type",
            "",
        )
    )


def _is_national_type(
    competition_type: str,
) -> bool:
    return competition_type.startswith(
        "national_"
    )


def audit_full_season_live_runtime(
    plan: LiveSeasonGraphPlan,
    *,
    engine=None,
    start_date: str | None = None,
) -> FullSeasonLiveBlockerAudit:
    state = plan.build_runtime(
        engine=engine,
        start_date=start_date,
    )
    progress = state.advance_through(
        f"{plan.year}-12-31"
    )

    pending_by_comp: dict[
        str,
        list[dict],
    ] = {}
    for row in plan.stage_calendar_rows:
        if row.get("date_status") != (
            "research_pending"
        ):
            continue
        pending_by_comp.setdefault(
            str(row["competition_id"]),
            [],
        ).append(dict(row))

    adjacency: dict[str, set[str]] = {}
    for source, destination in (
        plan.dependency_edges
    ):
        adjacency.setdefault(
            source,
            set(),
        ).add(destination)

    state_by_comp = {
        cid: state.dependency_state(cid)
        for cid in plan.topological_order
    }

    competition_rows: list[
        CompetitionBlockerAuditRow
    ] = []
    for cid in plan.topological_order:
        dependency = state_by_comp[cid]
        scheduled = state.competitions.get(
            cid
        )
        scheduled_summary = (
            scheduled.summary()
            if scheduled is not None
            else {}
        )
        is_complete = bool(
            dependency["is_complete"]
        )
        is_active = bool(
            dependency["is_active"]
        )
        calendar_gap_count = int(
            dependency["calendar_gap_count"]
            or 0
        )

        status = str(
            dependency["status"]
        )
        if is_complete:
            blocker_kind = BLOCKER_COMPLETE
        elif (
            is_active
            and calendar_gap_count > 0
        ):
            blocker_kind = (
                BLOCKER_CALENDAR_GAP
            )
        elif status in {
            DEPENDENCY_WAITING,
            DEPENDENCY_WAITING_EXTERNAL,
        }:
            blocker_kind = (
                BLOCKER_WAITING_DEPENDENCY
            )
        elif status in {
            DEPENDENCY_BLOCKED,
            DEPENDENCY_BLOCKED_DATE,
        }:
            blocker_kind = BLOCKER_BLOCKED
        else:
            blocker_kind = (
                BLOCKER_INCOMPLETE_ACTIVE
            )

        unresolved_sources = tuple(
            sorted(
                source
                for source in (
                    dependency[
                        "dependency_source_competition_ids"
                    ]
                )
                if not state_by_comp.get(
                    source,
                    {},
                ).get(
                    "is_complete",
                    False,
                )
            )
        )

        all_descendants = _descendants(
            adjacency,
            cid,
        )
        downstream_blocked = tuple(
            destination
            for destination in all_descendants
            if not state_by_comp[
                destination
            ]["is_complete"]
        )
        downstream_national = tuple(
            destination
            for destination in downstream_blocked
            if _is_national_type(
                _competition_type(
                    plan,
                    destination,
                )
            )
        )

        pending_rows = pending_by_comp.get(
            cid,
            [],
        )
        competition_rows.append(
            CompetitionBlockerAuditRow(
                competition_id=cid,
                competition_name=_competition_name(
                    plan,
                    cid,
                ),
                competition_type=(
                    _competition_type(
                        plan,
                        cid,
                    )
                ),
                season_segment=(
                    plan.entries[
                        cid
                    ].season_segment
                ),
                runtime_status=status,
                blocker_kind=blocker_kind,
                is_active=is_active,
                is_complete=is_complete,
                calendar_gap_count=(
                    calendar_gap_count
                ),
                pending_stage_ids=tuple(
                    row["stage_id"]
                    for row in pending_rows
                ),
                pending_stage_codes=tuple(
                    row["stage_code"]
                    for row in pending_rows
                ),
                unresolved_source_competition_ids=(
                    unresolved_sources
                ),
                downstream_blocked_competition_ids=(
                    downstream_blocked
                ),
                downstream_national_competition_ids=(
                    downstream_national
                ),
            )
        )

    competition_by_id = {
        row.competition_id: row
        for row in competition_rows
    }
    stage_priority_rows: list[
        StageCalendarPriorityRow
    ] = []
    for stage in plan.stage_calendar_rows:
        if stage.get("date_status") != (
            "research_pending"
        ):
            continue
        cid = str(
            stage["competition_id"]
        )
        blocker = competition_by_id[cid]
        if (
            blocker
            .downstream_national_competition_ids
        ):
            priority = PRIORITY_NATIONAL
        elif (
            blocker
            .downstream_blocked_competition_ids
        ):
            priority = PRIORITY_REGIONAL
        else:
            priority = PRIORITY_LOCAL

        stage_priority_rows.append(
            StageCalendarPriorityRow(
                stage_calendar_id=str(
                    stage[
                        "stage_calendar_id"
                    ]
                ),
                competition_id=cid,
                competition_name=(
                    blocker.competition_name
                ),
                competition_type=(
                    blocker.competition_type
                ),
                season_segment=(
                    blocker.season_segment
                ),
                stage_id=str(
                    stage["stage_id"]
                ),
                stage_code=str(
                    stage["stage_code"]
                ),
                calendar_relation=str(
                    stage.get(
                        "calendar_relation",
                        "",
                    )
                ),
                primary_source_id=str(
                    stage.get(
                        "primary_source_id",
                        "",
                    )
                ),
                priority_tier=priority,
                downstream_blocked_competition_count=(
                    len(
                        blocker
                        .downstream_blocked_competition_ids
                    )
                ),
                downstream_blocked_competition_ids=(
                    blocker
                    .downstream_blocked_competition_ids
                ),
                downstream_national_competition_ids=(
                    blocker
                    .downstream_national_competition_ids
                ),
                calendar_gap_count=(
                    blocker.calendar_gap_count
                ),
            )
        )

    priority_order = {
        PRIORITY_NATIONAL: 0,
        PRIORITY_REGIONAL: 1,
        PRIORITY_LOCAL: 2,
    }
    stage_priority_rows.sort(
        key=lambda row: (
            priority_order[
                row.priority_tier
            ],
            -row.downstream_blocked_competition_count,
            row.season_segment,
            row.competition_id,
            row.stage_calendar_id,
        )
    )

    return FullSeasonLiveBlockerAudit(
        plan=plan,
        state=state,
        competition_rows=competition_rows,
        stage_priority_rows=stage_priority_rows,
        progress=progress,
    )


def _csv_value(value) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ";".join(
            str(item)
            for item in value
        )
    return str(value)


def write_audit_csv(
    path: str | Path,
    rows: Iterable[dict],
) -> None:
    rows = list(rows)
    destination = Path(path)
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    if not rows:
        destination.write_text(
            "",
            encoding="utf-8",
        )
        return
    fieldnames = list(
        rows[0].keys()
    )
    with destination.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: _csv_value(
                    row.get(key, "")
                )
                for key in fieldnames
            })


def save_full_season_live_audit(
    audit: FullSeasonLiveBlockerAudit,
    output_dir: str | Path,
) -> dict[str, str]:
    root = Path(output_dir)
    root.mkdir(
        parents=True,
        exist_ok=True,
    )
    competition_path = (
        root
        / "competition_blockers.csv"
    )
    stage_path = (
        root
        / "stage_calendar_priorities.csv"
    )
    summary_path = (
        root / "summary.json"
    )

    write_audit_csv(
        competition_path,
        [
            row.to_dict()
            for row
            in audit.competition_rows
        ],
    )
    write_audit_csv(
        stage_path,
        [
            row.to_dict()
            for row
            in audit.stage_priority_rows
        ],
    )

    import json

    summary_path.write_text(
        json.dumps(
            audit.summary(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "competition_blockers": str(
            competition_path
        ),
        "stage_calendar_priorities": str(
            stage_path
        ),
        "summary": str(
            summary_path
        ),
    }
