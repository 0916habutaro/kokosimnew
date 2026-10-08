from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .live_season_planner import (
    LiveSeasonGraphPlan,
    LiveSeasonGraphPlanner,
)


SAVE_SCHEMA_VERSION = "stage13e3e1.live-season-save.v1"
DEFAULT_RESOLVER_CONTRACT = "default_deterministic_v1"


class LiveSeasonSaveError(ValueError):
    pass


class LiveSeasonSaveSchemaError(LiveSeasonSaveError):
    pass


class LiveSeasonSaveCompatibilityError(
    LiveSeasonSaveError
):
    pass


class LiveSeasonSaveReplayError(LiveSeasonSaveError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _json_copy(value: Any) -> Any:
    return json.loads(_canonical_json(value))


def plan_identity(
    plan: LiveSeasonGraphPlan,
) -> dict:
    return {
        "year": plan.year,
        "rng_seed": plan.rng_seed,
        "entries": {
            cid: entry.to_dict()
            for cid, entry
            in sorted(plan.entries.items())
        },
        "annual_templates": {
            cid: asdict(annual)
            for cid, annual
            in sorted(
                plan.annual_templates.items()
            )
        },
        "annual_build_strategies": dict(
            sorted(
                plan.annual_build_strategies
                .items()
            )
        ),
        "calendar_rows": sorted(
            (
                dict(row)
                for row in plan.calendar_rows
            ),
            key=lambda row: row.get(
                "competition_id",
                "",
            ),
        ),
        "stage_calendar_rows": sorted(
            (
                dict(row)
                for row
                in plan.stage_calendar_rows
            ),
            key=lambda row: (
                row.get(
                    "competition_id",
                    "",
                ),
                row.get("stage_id", ""),
            ),
        ),
        "dependency_edges": [
            list(edge)
            for edge in plan.dependency_edges
        ],
        "topological_order": list(
            plan.topological_order
        ),
        "external_bootstrap_resolutions": [
            row.to_dict()
            for row
            in plan.external_bootstrap_resolutions
        ],
        "warnings": list(plan.warnings),
    }


def plan_fingerprint(
    plan: LiveSeasonGraphPlan,
) -> str:
    return _fingerprint(
        plan_identity(plan)
    )


def _completed_match_log(state) -> dict[str, dict]:
    output: dict[str, dict] = {}
    for cid, scheduled in sorted(
        state.competitions.items()
    ):
        for match_id, match in sorted(
            scheduled.matches.items()
        ):
            if match.status != "completed":
                continue
            output[
                f"{cid}:{match_id}"
            ] = asdict(match)
    return _json_copy(output)


def _processed_dates(state) -> list[str]:
    dates: list[str] = []
    seen = set()
    for item in state.history:
        if item.get("action") != "play_today":
            continue
        value = item.get("date", "")
        if not value or value in seen:
            continue
        date.fromisoformat(value)
        seen.add(value)
        dates.append(value)
    if dates != sorted(dates):
        raise LiveSeasonSaveSchemaError(
            "runtime history play_today dates "
            "must be nondecreasing"
        )
    return dates


def _validate_processed_dates(
    *,
    start_date: str,
    current_date: str,
    processed_dates: list[str],
) -> None:
    start = date.fromisoformat(start_date)
    current = date.fromisoformat(current_date)
    if current < start:
        raise LiveSeasonSaveSchemaError(
            "current_date precedes start_date"
        )
    if not processed_dates:
        if current != start:
            raise LiveSeasonSaveSchemaError(
                "runtime with no processed dates "
                "must remain at start_date"
            )
        return

    parsed = [
        date.fromisoformat(value)
        for value in processed_dates
    ]
    if parsed[0] != start:
        raise LiveSeasonSaveSchemaError(
            "processed dates must start at "
            "runtime start_date"
        )
    expected = [
        start + timedelta(days=index)
        for index in range(len(parsed))
    ]
    if parsed != expected:
        raise LiveSeasonSaveSchemaError(
            "processed dates must be contiguous"
        )

    last = parsed[-1]
    if current not in {
        last,
        last + timedelta(days=1),
    }:
        raise LiveSeasonSaveSchemaError(
            "current_date must equal the last "
            "processed date or the following day"
        )


def create_live_season_save(
    plan: LiveSeasonGraphPlan,
    state,
    *,
    resolver_contract: str = (
        DEFAULT_RESOLVER_CONTRACT
    ),
) -> dict:
    if state.year != plan.year:
        raise LiveSeasonSaveSchemaError(
            "plan/runtime year mismatch"
        )
    if state.rng_seed != plan.rng_seed:
        raise LiveSeasonSaveSchemaError(
            "plan/runtime rng_seed mismatch"
        )
    if set(state.annual_templates) != set(
        plan.annual_templates
    ):
        raise LiveSeasonSaveSchemaError(
            "runtime template set differs from plan"
        )
    if not resolver_contract:
        raise LiveSeasonSaveSchemaError(
            "resolver_contract is required"
        )

    processed_dates = _processed_dates(state)
    start_date = state.start_date.isoformat()
    current_date = (
        state.current_date.isoformat()
    )
    _validate_processed_dates(
        start_date=start_date,
        current_date=current_date,
        processed_dates=processed_dates,
    )

    body = {
        "schema_version": SAVE_SCHEMA_VERSION,
        "year": state.year,
        "rng_seed": state.rng_seed,
        "resolver_contract": resolver_contract,
        "plan_fingerprint": (
            plan_fingerprint(plan)
        ),
        "start_date": start_date,
        "current_date": current_date,
        "processed_dates": processed_dates,
        "completed_match_results": (
            _completed_match_log(state)
        ),
        "status_by_competition": dict(
            sorted(
                state.status_by_competition
                .items()
            )
        ),
        "activated_on": dict(
            sorted(state.activated_on.items())
        ),
        "runtime_summary": _json_copy(
            state.summary()
        ),
        "public_snapshot_fingerprint": (
            _fingerprint(
                state.public_snapshot()
            )
        ),
        "history": _json_copy(
            state.history
        ),
    }
    body["payload_checksum"] = _fingerprint(
        body
    )
    return body


def _validate_save_payload(
    payload: Mapping[str, Any],
) -> dict:
    if not isinstance(payload, Mapping):
        raise LiveSeasonSaveSchemaError(
            "save payload must be an object"
        )
    data = deepcopy(dict(payload))
    checksum = data.pop(
        "payload_checksum",
        "",
    )
    if not checksum:
        raise LiveSeasonSaveSchemaError(
            "payload_checksum is required"
        )
    if _fingerprint(data) != checksum:
        raise LiveSeasonSaveSchemaError(
            "save payload checksum mismatch"
        )
    if data.get("schema_version") != (
        SAVE_SCHEMA_VERSION
    ):
        raise LiveSeasonSaveSchemaError(
            "unsupported save schema_version: "
            f"{data.get('schema_version', '')}"
        )

    required = {
        "year",
        "rng_seed",
        "resolver_contract",
        "plan_fingerprint",
        "start_date",
        "current_date",
        "processed_dates",
        "completed_match_results",
        "status_by_competition",
        "activated_on",
        "runtime_summary",
        "public_snapshot_fingerprint",
        "history",
    }
    missing = sorted(
        required - set(data)
    )
    if missing:
        raise LiveSeasonSaveSchemaError(
            f"missing save fields: {missing}"
        )

    if not isinstance(
        data["processed_dates"],
        list,
    ):
        raise LiveSeasonSaveSchemaError(
            "processed_dates must be a list"
        )
    _validate_processed_dates(
        start_date=data["start_date"],
        current_date=data["current_date"],
        processed_dates=list(
            data["processed_dates"]
        ),
    )
    data["payload_checksum"] = checksum
    return data


def restore_live_season_save(
    planner: LiveSeasonGraphPlanner,
    payload: Mapping[str, Any],
    *,
    engine=None,
    resolver_contract: str = (
        DEFAULT_RESOLVER_CONTRACT
    ),
):
    data = _validate_save_payload(
        payload
    )
    if data["year"] != planner.year:
        raise LiveSeasonSaveCompatibilityError(
            "save year does not match planner"
        )
    if data["rng_seed"] != planner.rng_seed:
        raise LiveSeasonSaveCompatibilityError(
            "save rng_seed does not match planner"
        )
    if data["resolver_contract"] != (
        resolver_contract
    ):
        raise LiveSeasonSaveCompatibilityError(
            "resolver contract mismatch: "
            f"save={data['resolver_contract']} "
            f"load={resolver_contract}"
        )

    plan = planner.build_plan()
    actual_plan_fingerprint = (
        plan_fingerprint(plan)
    )
    if data["plan_fingerprint"] != (
        actual_plan_fingerprint
    ):
        raise LiveSeasonSaveCompatibilityError(
            "season plan fingerprint mismatch; "
            "repository masters or planner output "
            "changed since the save was created"
        )

    state = plan.build_runtime(
        engine=engine,
        start_date=data["start_date"],
    )

    processed_dates = list(
        data["processed_dates"]
    )
    if processed_dates:
        state.advance_through(
            processed_dates[-1]
        )

    saved_current = date.fromisoformat(
        data["current_date"]
    )
    if state.current_date != saved_current:
        if (
            processed_dates
            and saved_current
            == state.current_date
            + timedelta(days=1)
        ):
            state.current_date = (
                saved_current
            )
        else:
            raise LiveSeasonSaveReplayError(
                "restored current_date cannot be "
                "reconciled with processed dates"
            )

    replay_match_log = (
        _completed_match_log(state)
    )
    if replay_match_log != data[
        "completed_match_results"
    ]:
        expected_keys = set(
            data[
                "completed_match_results"
            ]
        )
        actual_keys = set(
            replay_match_log
        )
        missing = sorted(
            expected_keys - actual_keys
        )[:10]
        extra = sorted(
            actual_keys - expected_keys
        )[:10]
        changed = sorted(
            key
            for key
            in expected_keys & actual_keys
            if data[
                "completed_match_results"
            ][key] != replay_match_log[key]
        )[:10]
        raise LiveSeasonSaveReplayError(
            "completed match replay mismatch: "
            f"missing={missing} extra={extra} "
            f"changed={changed}"
        )

    if dict(
        state.status_by_competition
    ) != data["status_by_competition"]:
        raise LiveSeasonSaveReplayError(
            "competition dependency status "
            "differs after replay"
        )
    if dict(state.activated_on) != (
        data["activated_on"]
    ):
        raise LiveSeasonSaveReplayError(
            "competition activation dates "
            "differ after replay"
        )

    actual_snapshot_fingerprint = (
        _fingerprint(
            state.public_snapshot()
        )
    )
    if actual_snapshot_fingerprint != data[
        "public_snapshot_fingerprint"
    ]:
        raise LiveSeasonSaveReplayError(
            "public runtime snapshot differs "
            "after replay"
        )

    if _json_copy(
        state.summary()
    ) != data["runtime_summary"]:
        raise LiveSeasonSaveReplayError(
            "runtime summary differs after replay"
        )

    state.history = _json_copy(
        data["history"]
    )
    return plan, state


def write_live_season_save(
    path: str | Path,
    plan: LiveSeasonGraphPlan,
    state,
    *,
    resolver_contract: str = (
        DEFAULT_RESOLVER_CONTRACT
    ),
) -> dict:
    payload = create_live_season_save(
        plan,
        state,
        resolver_contract=resolver_contract,
    )
    destination = Path(path)
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temp = destination.with_name(
        destination.name + ".tmp"
    )
    temp.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temp.replace(destination)
    return payload


def read_live_season_save(
    path: str | Path,
    planner: LiveSeasonGraphPlanner,
    *,
    engine=None,
    resolver_contract: str = (
        DEFAULT_RESOLVER_CONTRACT
    ),
):
    source = Path(path)
    try:
        payload = json.loads(
            source.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise LiveSeasonSaveSchemaError(
            f"cannot read save file: {source}"
        ) from exc
    return restore_live_season_save(
        planner,
        payload,
        engine=engine,
        resolver_contract=resolver_contract,
    )
