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

ORIGIN_NONE = "none"
ORIGIN_PENDING_STAGE_CALENDAR = "pending_pre_main_calendar"
ORIGIN_CALENDAR_WITHOUT_STAGE = "calendar_gap_without_pending_stage"
ORIGIN_DEPENDENCY_RESOLUTION = "dependency_resolution_failure"
ORIGIN_UPSTREAM_DEPENDENCY = "upstream_dependency"
ORIGIN_RUNTIME_BLOCKED = "runtime_blocked"
ORIGIN_INCOMPLETE_ACTIVE = "incomplete_active"

PRIORITY_NATIONAL = "P0_national_chain"
PRIORITY_REGIONAL = "P1_regional_chain"
PRIORITY_LOCAL = "P2_local_only"

ACTION_VERIFY_STAGE_DATES = "verify_pre_main_stage_dates"
ACTION_REVIEW_STRUCTURE = "review_unmodeled_pre_main_structure"
ACTION_FIX_DEPENDENCY = "fix_dependency_resolution"


@dataclass(frozen=True)
class CompetitionBlockerAuditRow:
    competition_id: str
    competition_name: str
    competition_type: str
    season_segment: str
    runtime_status: str
    blocker_kind: str
    blocker_origin: str
    is_active: bool
    is_complete: bool
    calendar_gap_count: int
    pending_stage_ids: tuple[str, ...]
    pending_stage_codes: tuple[str, ...]
    resolution_failures: tuple[str, ...]
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
            "blocker_origin": self.blocker_origin,
            "is_active": self.is_active,
            "is_complete": self.is_complete,
            "calendar_gap_count": self.calendar_gap_count,
            "pending_stage_ids": list(
                self.pending_stage_ids
            ),
            "pending_stage_codes": list(
                self.pending_stage_codes
            ),
            "resolution_failures": list(
                self.resolution_failures
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
    runtime_blocker_kind: str
    runtime_blocker_origin: str
    stage_reached: bool
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
            "runtime_blocker_kind": self.runtime_blocker_kind,
            "runtime_blocker_origin": self.runtime_blocker_origin,
            "stage_reached": self.stage_reached,
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


@dataclass(frozen=True)
class BlockerActionRow:
    action_id: str
    action_type: str
    priority_tier: str
    competition_id: str
    competition_name: str
    season_segment: str
    stage_calendar_id: str
    stage_id: str
    stage_code: str
    blocker_origin: str
    detail: str
    downstream_blocked_competition_ids: tuple[str, ...]
    downstream_national_competition_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "priority_tier": self.priority_tier,
            "competition_id": self.competition_id,
            "competition_name": self.competition_name,
            "season_segment": self.season_segment,
            "stage_calendar_id": self.stage_calendar_id,
            "stage_id": self.stage_id,
            "stage_code": self.stage_code,
            "blocker_origin": self.blocker_origin,
            "detail": self.detail,
            "downstream_blocked_competition_ids": list(
                self.downstream_blocked_competition_ids
            ),
            "downstream_national_competition_ids": list(
                self.downstream_national_competition_ids
            ),
        }


@dataclass
class FullSeasonLiveBlockerAudit:
    plan: LiveSeasonGraphPlan
    state: object
    competition_rows: list[CompetitionBlockerAuditRow]
    stage_priority_rows: list[StageCalendarPriorityRow]
    action_rows: list[BlockerActionRow]
    progress: dict

    def summary(self) -> dict:
        blocker_counts: dict[str, int] = {}
        origin_counts: dict[str, int] = {}
        for row in self.competition_rows:
            blocker_counts[row.blocker_kind] = (
                blocker_counts.get(
                    row.blocker_kind,
                    0,
                )
                + 1
            )
            if row.blocker_origin != ORIGIN_NONE:
                origin_counts[row.blocker_origin] = (
                    origin_counts.get(
                        row.blocker_origin,
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

        action_counts: dict[str, int] = {}
        action_priority_counts: dict[str, int] = {}
        for row in self.action_rows:
            action_counts[row.action_type] = (
                action_counts.get(
                    row.action_type,
                    0,
                )
                + 1
            )
            action_priority_counts[row.priority_tier] = (
                action_priority_counts.get(
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
            if row.blocker_origin in {
                ORIGIN_PENDING_STAGE_CALENDAR,
                ORIGIN_CALENDAR_WITHOUT_STAGE,
                ORIGIN_DEPENDENCY_RESOLUTION,
            }
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
        unmodeled_gap_ids = sorted(
            row.competition_id
            for row in self.competition_rows
            if row.blocker_origin
            == ORIGIN_CALENDAR_WITHOUT_STAGE
        )
        resolution_blocked_ids = sorted(
            row.competition_id
            for row in self.competition_rows
            if row.blocker_origin
            == ORIGIN_DEPENDENCY_RESOLUTION
        )

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
            "blocker_origin_counts": dict(
                sorted(origin_counts.items())
            ),
            "pending_stage_row_count": len(
                self.stage_priority_rows
            ),
            "pending_stage_competition_count": len({
                row.competition_id
                for row in self.stage_priority_rows
            }),
            "pending_stage_reached_row_count": sum(
                row.stage_reached
                for row in self.stage_priority_rows
            ),
            "pending_stage_blocked_before_reach_row_count": sum(
                not row.stage_reached
                for row in self.stage_priority_rows
            ),
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
            "runtime_blocked_competition_count": (
                blocker_counts.get(
                    BLOCKER_BLOCKED,
                    0,
                )
            ),
            "calendar_gap_without_pending_stage_competition_ids": (
                unmodeled_gap_ids
            ),
            "dependency_resolution_blocked_competition_ids": (
                resolution_blocked_ids
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
            "action_count": len(
                self.action_rows
            ),
            "action_counts": dict(
                sorted(action_counts.items())
            ),
            "action_priority_counts": dict(
                sorted(action_priority_counts.items())
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
            "action_rows": [
                row.to_dict()
                for row in self.action_rows
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


def _priority_for(
    downstream_blocked: tuple[str, ...],
    downstream_national: tuple[str, ...],
) -> str:
    if downstream_national:
        return PRIORITY_NATIONAL
    if downstream_blocked:
        return PRIORITY_REGIONAL
    return PRIORITY_LOCAL


def _resolution_failures_by_destination(
    state,
) -> dict[str, tuple[str, ...]]:
    output: dict[str, list[str]] = {}
    resolution_groups = [
        getattr(state, "resolutions", []),
        getattr(
            state,
            "qualification_resolutions",
            [],
        ),
        getattr(
            state,
            "regional_feeder_resolutions",
            [],
        ),
    ]
    for group in resolution_groups:
        for row in group:
            status = str(
                getattr(row, "status", "")
            )
            if status in {"", "PASS", "WAITING"}:
                continue
            destination = str(
                getattr(
                    row,
                    "destination_competition_id",
                    "",
                )
            )
            if not destination:
                continue
            rule_id = str(
                getattr(
                    row,
                    "access_rule_id",
                    "",
                )
                or getattr(
                    row,
                    "rule_id",
                    "",
                )
                or getattr(
                    row,
                    "feeder_rule_id",
                    "",
                )
            )
            resolved_ids = tuple(
                getattr(
                    row,
                    "resolved_school_ids",
                    (),
                )
            )
            expected = int(
                getattr(
                    row,
                    "expected_count",
                    0,
                )
                or 0
            )
            notes = str(
                getattr(
                    row,
                    "notes",
                    "",
                )
            )
            detail = (
                f"{rule_id}:{status}:"
                f"resolved={len(resolved_ids)}:"
                f"expected={expected}"
            )
            if notes:
                detail += f":{notes}"
            output.setdefault(
                destination,
                [],
            ).append(detail)
    return {
        cid: tuple(values)
        for cid, values in output.items()
    }


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
    resolution_failures = (
        _resolution_failures_by_destination(
            state
        )
    )

    competition_rows: list[
        CompetitionBlockerAuditRow
    ] = []
    for cid in plan.topological_order:
        dependency = state_by_comp[cid]
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
        pending_rows = pending_by_comp.get(
            cid,
            [],
        )
        failures = resolution_failures.get(
            cid,
            (),
        )

        status = str(
            dependency["status"]
        )
        if is_complete:
            blocker_kind = BLOCKER_COMPLETE
            blocker_origin = ORIGIN_NONE
        elif (
            is_active
            and calendar_gap_count > 0
        ):
            blocker_kind = (
                BLOCKER_CALENDAR_GAP
            )
            blocker_origin = (
                ORIGIN_PENDING_STAGE_CALENDAR
                if pending_rows
                else ORIGIN_CALENDAR_WITHOUT_STAGE
            )
        elif status in {
            DEPENDENCY_WAITING,
            DEPENDENCY_WAITING_EXTERNAL,
        }:
            blocker_kind = (
                BLOCKER_WAITING_DEPENDENCY
            )
            blocker_origin = (
                ORIGIN_UPSTREAM_DEPENDENCY
            )
        elif status in {
            DEPENDENCY_BLOCKED,
            DEPENDENCY_BLOCKED_DATE,
        }:
            blocker_kind = BLOCKER_BLOCKED
            blocker_origin = (
                ORIGIN_DEPENDENCY_RESOLUTION
                if failures
                else ORIGIN_RUNTIME_BLOCKED
            )
        else:
            blocker_kind = (
                BLOCKER_INCOMPLETE_ACTIVE
            )
            blocker_origin = (
                ORIGIN_INCOMPLETE_ACTIVE
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
                blocker_origin=blocker_origin,
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
                resolution_failures=failures,
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
        priority = _priority_for(
            blocker.downstream_blocked_competition_ids,
            blocker.downstream_national_competition_ids,
        )

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
                runtime_blocker_kind=(
                    blocker.blocker_kind
                ),
                runtime_blocker_origin=(
                    blocker.blocker_origin
                ),
                stage_reached=(
                    blocker.blocker_origin
                    == ORIGIN_PENDING_STAGE_CALENDAR
                ),
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

    action_rows: list[
        BlockerActionRow
    ] = []
    for stage in stage_priority_rows:
        detail = (
            "research and verify exact pre-MAIN stage dates"
        )
        if not stage.stage_reached:
            detail += (
                "; resolve earlier runtime blocker before "
                "the stage can execute"
            )
        action_rows.append(
            BlockerActionRow(
                action_id=(
                    f"stage:{stage.stage_calendar_id}"
                ),
                action_type=(
                    ACTION_VERIFY_STAGE_DATES
                ),
                priority_tier=(
                    stage.priority_tier
                ),
                competition_id=(
                    stage.competition_id
                ),
                competition_name=(
                    stage.competition_name
                ),
                season_segment=(
                    stage.season_segment
                ),
                stage_calendar_id=(
                    stage.stage_calendar_id
                ),
                stage_id=stage.stage_id,
                stage_code=stage.stage_code,
                blocker_origin=(
                    stage.runtime_blocker_origin
                ),
                detail=detail,
                downstream_blocked_competition_ids=(
                    stage.downstream_blocked_competition_ids
                ),
                downstream_national_competition_ids=(
                    stage.downstream_national_competition_ids
                ),
            )
        )

    for blocker in competition_rows:
        priority = _priority_for(
            blocker.downstream_blocked_competition_ids,
            blocker.downstream_national_competition_ids,
        )
        if (
            blocker.blocker_origin
            == ORIGIN_CALENDAR_WITHOUT_STAGE
        ):
            action_rows.append(
                BlockerActionRow(
                    action_id=(
                        "structure:"
                        f"{blocker.competition_id}"
                    ),
                    action_type=(
                        ACTION_REVIEW_STRUCTURE
                    ),
                    priority_tier=priority,
                    competition_id=(
                        blocker.competition_id
                    ),
                    competition_name=(
                        blocker.competition_name
                    ),
                    season_segment=(
                        blocker.season_segment
                    ),
                    stage_calendar_id="",
                    stage_id="",
                    stage_code="",
                    blocker_origin=(
                        blocker.blocker_origin
                    ),
                    detail=(
                        "calendar gap exists without a "
                        "research_pending pre-MAIN stage; "
                        "review competition structure and "
                        "excluded preliminary dates"
                    ),
                    downstream_blocked_competition_ids=(
                        blocker.downstream_blocked_competition_ids
                    ),
                    downstream_national_competition_ids=(
                        blocker.downstream_national_competition_ids
                    ),
                )
            )
        if (
            blocker.blocker_origin
            == ORIGIN_DEPENDENCY_RESOLUTION
        ):
            action_rows.append(
                BlockerActionRow(
                    action_id=(
                        "dependency:"
                        f"{blocker.competition_id}"
                    ),
                    action_type=(
                        ACTION_FIX_DEPENDENCY
                    ),
                    priority_tier=priority,
                    competition_id=(
                        blocker.competition_id
                    ),
                    competition_name=(
                        blocker.competition_name
                    ),
                    season_segment=(
                        blocker.season_segment
                    ),
                    stage_calendar_id="",
                    stage_id="",
                    stage_code="",
                    blocker_origin=(
                        blocker.blocker_origin
                    ),
                    detail="; ".join(
                        blocker.resolution_failures
                    ),
                    downstream_blocked_competition_ids=(
                        blocker.downstream_blocked_competition_ids
                    ),
                    downstream_national_competition_ids=(
                        blocker.downstream_national_competition_ids
                    ),
                )
            )

    action_type_order = {
        ACTION_FIX_DEPENDENCY: 0,
        ACTION_REVIEW_STRUCTURE: 0,
        ACTION_VERIFY_STAGE_DATES: 1,
    }
    action_rows.sort(
        key=lambda row: (
            priority_order[
                row.priority_tier
            ],
            action_type_order[
                row.action_type
            ],
            -len(
                row.downstream_blocked_competition_ids
            ),
            row.competition_id,
            row.action_id,
        )
    )

    return FullSeasonLiveBlockerAudit(
        plan=plan,
        state=state,
        competition_rows=competition_rows,
        stage_priority_rows=stage_priority_rows,
        action_rows=action_rows,
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
    action_path = (
        root
        / "blocker_actions.csv"
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
    write_audit_csv(
        action_path,
        [
            row.to_dict()
            for row
            in audit.action_rows
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
        "blocker_actions": str(
            action_path
        ),
        "summary": str(
            summary_path
        ),
    }
