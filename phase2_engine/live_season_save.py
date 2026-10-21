from __future__ import annotations

import base64
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
from .runtime_snapshot import (
    RuntimeSnapshotError,
    dump_runtime_state,
    load_runtime_state,
    snapshot_years,
)


# v2：進行中の状態をそのまま書き出す（読込時に最初から計算し直さない）。
# 旧形式は読み込まない（game_definition.md §5）。
SAVE_SCHEMA_VERSION = "live-season-save.v2"
DEFAULT_RESOLVER_CONTRACT = "default_deterministic_v1"
# 全国の試合を選手で行う（game_core.live_members.player_engine）。
PLAYER_RESOLVER_CONTRACT = "players_v1"


class LiveSeasonSaveError(ValueError):
    pass


class LiveSeasonSaveSchemaError(LiveSeasonSaveError):
    pass


class LiveSeasonSaveCompatibilityError(
    LiveSeasonSaveError
):
    pass


class LiveSeasonSaveStateError(LiveSeasonSaveError):
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


def rechecksum_live_season_save_payload(
    payload: Mapping[str, Any],
) -> dict:
    data = deepcopy(dict(payload))
    data.pop(
        "payload_checksum",
        None,
    )
    data["payload_checksum"] = (
        _fingerprint(data)
    )
    return data


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
    plans: Mapping[int, LiveSeasonGraphPlan] | None = None,
) -> dict:
    """``plan`` は今の年度の計画。年度の重なりでは ``plans`` に全年度の計画。"""
    plans = dict(
        plans
        or getattr(state, "plans", None)
        or {plan.year: plan}
    )
    years = snapshot_years(state)
    if sorted(plans) != years:
        raise LiveSeasonSaveSchemaError(
            "plans do not match the seasons in the runtime"
        )
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
        "season_years": years,
        "plan_fingerprints": {
            str(year): plan_fingerprint(plans[year])
            for year in years
        },
        "start_date": start_date,
        "current_date": current_date,
        "processed_dates": processed_dates,
        "completed_match_count": len(
            state.completed_results()
        ),
        "runtime_summary": _json_copy(
            state.summary()
        ),
        "runtime_state": base64.b64encode(
            dump_runtime_state(state)
        ).decode("ascii"),
    }
    body["payload_checksum"] = _fingerprint(
        body
    )
    return body


REQUIRED_FIELDS = frozenset({
    "season_years",
    "plan_fingerprints",
    "year",
    "rng_seed",
    "resolver_contract",
    "plan_fingerprint",
    "start_date",
    "current_date",
    "processed_dates",
    "completed_match_count",
    "runtime_summary",
    "runtime_state",
})


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
    if data.get("schema_version") != (
        SAVE_SCHEMA_VERSION
    ):
        raise LiveSeasonSaveCompatibilityError(
            "unsupported save schema_version: "
            f"{data.get('schema_version', '')}"
        )
    if _fingerprint(data) != checksum:
        raise LiveSeasonSaveSchemaError(
            "save payload checksum mismatch"
        )
    missing = sorted(
        REQUIRED_FIELDS - set(data)
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
    planner_for_year=None,
    engine_for_plan=None,
):
    """保存した状態をそのまま戻す。試合を最初からやり直さない。

    年度の重なりで複数の年度があるときは、``planner_for_year(year)`` で
    ほかの年度の計画を、``engine_for_plan(plan)`` で年度ごとの engine をつくる。
    """
    data = _validate_save_payload(payload)
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

    plans = {}
    for year in data["season_years"]:
        if year == planner.year:
            source = planner
        elif planner_for_year is not None:
            source = planner_for_year(year)
        else:
            raise LiveSeasonSaveCompatibilityError(
                f"no planner for season {year}"
            )
        plans[year] = source.build_plan()
        if data["plan_fingerprints"].get(str(year)) != (
            plan_fingerprint(plans[year])
        ):
            raise LiveSeasonSaveCompatibilityError(
                "season plan fingerprint mismatch; "
                "repository masters or planner output "
                "changed since the save was created"
            )
    plan = plans[planner.year]
    engines = {
        year: (
            engine_for_plan(season_plan)
            if engine_for_plan is not None
            else (engine if year == planner.year else None)
        )
        for year, season_plan in plans.items()
    }

    try:
        state = load_runtime_state(
            base64.b64decode(
                data["runtime_state"]
            ),
            plans,
            engines=engines,
        )
    except RuntimeSnapshotError as exc:
        raise LiveSeasonSaveStateError(
            str(exc)
        ) from exc
    if isinstance(getattr(state, "__dict__", {}).get("plans"), dict):
        state.plans = plans
    if (
        state.year != data["year"]
        or state.rng_seed != data["rng_seed"]
        or state.current_date.isoformat()
        != data["current_date"]
        or _json_copy(state.summary())
        != data["runtime_summary"]
    ):
        raise LiveSeasonSaveStateError(
            "restored runtime differs from save metadata"
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


def _read_payload(path: str | Path) -> dict:
    source = Path(path)
    try:
        return json.loads(
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


def inspect_live_season_save(
    path: str | Path,
) -> dict:
    data = _validate_save_payload(
        _read_payload(path)
    )
    return {
        "schema_version": data["schema_version"],
        "year": data["year"],
        "rng_seed": data["rng_seed"],
        "resolver_contract": (
            data["resolver_contract"]
        ),
        "start_date": data["start_date"],
        "current_date": data["current_date"],
        "processed_date_count": len(
            data["processed_dates"]
        ),
        "completed_match_count": (
            data["completed_match_count"]
        ),
        "plan_fingerprint": (
            data["plan_fingerprint"]
        ),
        "payload_checksum": (
            data["payload_checksum"]
        ),
        "runtime_summary": _json_copy(
            data["runtime_summary"]
        ),
    }


def read_live_season_save(
    path: str | Path,
    planner: LiveSeasonGraphPlanner,
    *,
    engine=None,
    resolver_contract: str = (
        DEFAULT_RESOLVER_CONTRACT
    ),
    **season_builders,
):
    """``season_builders`` は ``restore_live_season_save`` の
    ``planner_for_year`` と ``engine_for_plan``（年度の重なり）。"""
    return restore_live_season_save(
        planner,
        _read_payload(path),
        engine=engine,
        resolver_contract=resolver_contract,
        **season_builders,
    )
