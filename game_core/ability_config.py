from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class ConfigDocument:
    path: Path
    config_id: str
    revision: int
    status: str
    canonical_sha256: str
    payload: dict[str, Any]


def canonical_config_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_config(
    path: str | Path,
    *,
    expected_config_id: str | None = None,
) -> ConfigDocument:
    config_path = Path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{config_path}: top level must be an object")

    for key in ("config_id", "revision", "status"):
        if key not in payload:
            raise ValueError(f"{config_path}: missing {key}")

    config_id = str(payload["config_id"])
    if expected_config_id and config_id != expected_config_id:
        raise ValueError(
            f"{config_path}: expected config_id={expected_config_id}, "
            f"got {config_id}"
        )

    revision = payload["revision"]
    if not isinstance(revision, int) or revision < 1:
        raise ValueError(f"{config_path}: revision must be integer >= 1")

    status = str(payload["status"])
    if not status:
        raise ValueError(f"{config_path}: status is required")

    return ConfigDocument(
        path=config_path,
        config_id=config_id,
        revision=revision,
        status=status,
        canonical_sha256=canonical_config_sha256(payload),
        payload=payload,
    )


def _require_number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label}: numeric value required")
    return float(value)


def _require_probability_weights(
    weights: Mapping[str, Any],
    label: str,
    *,
    tolerance: float = 1e-9,
) -> None:
    if not weights:
        raise ValueError(f"{label}: weights must not be empty")
    values = []
    for key, value in weights.items():
        number = _require_number(value, f"{label}.{key}")
        if number < 0:
            raise ValueError(f"{label}.{key}: must be >= 0")
        values.append(number)
    if abs(sum(values) - 1.0) > tolerance:
        raise ValueError(
            f"{label}: normalized weights must sum to 1.0; got {sum(values)}"
        )


def validate_ability_catalog(document: ConfigDocument) -> None:
    payload = document.payload
    abilities = payload.get("abilities")
    if not isinstance(abilities, list) or not abilities:
        raise ValueError("ability catalog: abilities must be a non-empty list")

    ids: list[str] = []
    value_types = payload.get("value_types")
    if not isinstance(value_types, dict) or not value_types:
        raise ValueError("ability catalog: value_types must be defined")

    for item in abilities:
        if not isinstance(item, dict):
            raise ValueError("ability catalog: each ability must be an object")
        for key in (
            "ability_id",
            "subject",
            "value_type",
            "definition_ja",
            "used_for",
            "not_for",
        ):
            if key not in item:
                raise ValueError(
                    f"ability catalog: missing {key} in {item!r}"
                )
        ability_id = str(item["ability_id"])
        ids.append(ability_id)
        if item["value_type"] not in value_types:
            raise ValueError(
                f"{ability_id}: unknown value_type {item['value_type']}"
            )

    if len(ids) != len(set(ids)):
        raise ValueError("ability catalog: duplicate ability_id")


def validate_ability_scale(document: ConfigDocument) -> None:
    payload = document.payload
    scalar = payload.get("scalar_scale")
    if not isinstance(scalar, dict):
        raise ValueError("ability scale: scalar_scale is required")

    scale_min = int(scalar["min"])
    scale_max = int(scalar["max"])
    if (scale_min, scale_max) != (1, 100):
        raise ValueError("ability scale v1 must use 1..100")

    bands = payload.get("display_bands")
    if not isinstance(bands, list) or not bands:
        raise ValueError("ability scale: display_bands is required")

    covered: dict[int, str] = {}
    for band in bands:
        grade = str(band["grade"])
        low = int(band["min"])
        high = int(band["max"])
        if low > high:
            raise ValueError(f"display band {grade}: min > max")
        for value in range(low, high + 1):
            if value in covered:
                raise ValueError(
                    f"display band overlap at {value}: "
                    f"{covered[value]} / {grade}"
                )
            covered[value] = grade

    expected = set(range(scale_min, scale_max + 1))
    if set(covered) != expected:
        missing = sorted(expected - set(covered))
        extra = sorted(set(covered) - expected)
        raise ValueError(
            f"display bands must cover 1..100; missing={missing}, extra={extra}"
        )


def validate_player_generation(
    document: ConfigDocument,
    *,
    catalog: ConfigDocument,
) -> None:
    payload = document.payload
    catalog_ids = {
        str(item["ability_id"])
        for item in catalog.payload["abilities"]
    }

    grade_adjustment = payload.get("grade_adjustment")
    if set(grade_adjustment or {}) != {"1", "2", "3"}:
        raise ValueError(
            "player generation: grade_adjustment must define 1/2/3"
        )

    sections = (
        "batter_abilities",
        "catcher_only_abilities",
        "pitcher_abilities",
    )
    referenced: set[str] = set()
    for section_name in sections:
        section = payload.get(section_name)
        if not isinstance(section, dict) or not section:
            raise ValueError(
                f"player generation: {section_name} must be non-empty"
            )
        referenced.update(section)
        for ability_id, params in section.items():
            if ability_id not in catalog_ids:
                raise ValueError(
                    f"player generation: unknown ability_id {ability_id}"
                )
            if not isinstance(params, dict):
                raise ValueError(
                    f"player generation: {ability_id} params must be object"
                )
            stddev = _require_number(
                params.get("stddev"),
                f"{section_name}.{ability_id}.stddev",
            )
            if stddev <= 0:
                raise ValueError(
                    f"{section_name}.{ability_id}.stddev must be > 0"
                )

    required = {
        "contact",
        "power",
        "plate_discipline",
        "strikeout_resistance",
        "bunt",
        "speed",
        "baserunning",
        "stealing",
        "arm_strength",
        "fielding",
        "throwing",
        "catching",
        "game_calling",
        "velocity_kmh",
        "control",
        "stamina",
        "stuff",
        "strikeout",
        "groundball",
        "composure",
    }
    if not required.issubset(referenced):
        raise ValueError(
            "player generation: required scalar abilities are missing "
            f"{sorted(required - referenced)}"
        )

    aptitude = payload.get("position_aptitude")
    if not isinstance(aptitude, dict):
        raise ValueError("player generation: position_aptitude required")

    repertoire = payload.get("pitch_repertoire")
    if not isinstance(repertoire, dict):
        raise ValueError("player generation: pitch_repertoire required")
    pitch_types = repertoire.get("pitch_types")
    if not isinstance(pitch_types, list) or len(pitch_types) < 2:
        raise ValueError(
            "player generation: at least two pitch types required"
        )

    school_context = payload.get("school_context")
    if school_context.get("direct_match_strength_bonus") is not False:
        raise ValueError(
            "player generation: direct school match bonus must remain false"
        )

    namespaces = payload.get("rng_namespace_policy")
    if not isinstance(namespaces, dict) or not namespaces:
        raise ValueError("player generation: rng_namespace_policy required")
    for key, template in namespaces.items():
        if "_v1:" not in str(template):
            raise ValueError(
                f"player generation: {key} namespace must be versioned"
            )


def validate_team_strength(
    document: ConfigDocument,
    *,
    catalog: ConfigDocument,
) -> None:
    payload = document.payload
    source_contract = payload.get("source_contract")
    if not isinstance(source_contract, dict):
        raise ValueError("team strength: source_contract required")
    if source_contract.get("direct_school_rating_bonus") is not False:
        raise ValueError(
            "team strength: direct_school_rating_bonus must remain false"
        )

    _require_probability_weights(
        payload["batting"]["lineup_weights"],
        "team_strength.batting.lineup_weights",
    )
    _require_probability_weights(
        payload["batting"]["bench_depth"]["composite_weights"],
        "team_strength.batting.bench_depth.composite_weights",
    )
    _require_probability_weights(
        payload["running"]["weights"],
        "team_strength.running.weights",
    )
    _require_probability_weights(
        payload["defense"]["player_formula_weights"],
        "team_strength.defense.player_formula_weights",
    )
    _require_probability_weights(
        payload["defense"]["catcher_override"]["weights"],
        "team_strength.defense.catcher_override.weights",
    )
    _require_probability_weights(
        payload["pitching"]["pitcher_quality_weights"],
        "team_strength.pitching.pitcher_quality_weights",
    )
    _require_probability_weights(
        payload["pitching"]["staff_weights"],
        "team_strength.pitching.staff_weights",
    )

    for position, value in payload["defense"]["position_importance"].items():
        if _require_number(
            value,
            f"team_strength.defense.position_importance.{position}",
        ) <= 0:
            raise ValueError(
                f"team strength: {position} importance must be > 0"
            )

    catalog_ids = {
        str(item["ability_id"])
        for item in catalog.payload["abilities"]
    }
    referenced = set(payload["batting"]["lineup_weights"]) - {"bench_depth"}
    referenced |= set(
        payload["batting"]["bench_depth"]["composite_weights"]
    )
    referenced |= set(payload["running"]["weights"])
    referenced |= set(payload["defense"]["player_formula_weights"])
    referenced |= set(payload["defense"]["catcher_override"]["weights"])
    referenced |= (
        set(payload["pitching"]["pitcher_quality_weights"])
        - {"velocity_component"}
    )
    unknown = referenced - catalog_ids
    if unknown:
        raise ValueError(
            f"team strength: unknown ability references {sorted(unknown)}"
        )

    rules = payload.get("rules")
    if rules.get("team_strength_is_snapshot_not_school_master") is not True:
        raise ValueError(
            "team strength: snapshot rule must remain true"
        )
    if rules.get(
        "match_simulation_should_use_components_not_single_overall"
    ) is not True:
        raise ValueError(
            "team strength: match simulation must use components"
        )


def load_and_validate_ability_configs(
    config_dir: str | Path,
) -> dict[str, ConfigDocument]:
    root = Path(config_dir)
    catalog = load_config(
        root / "ability_catalog_v1.json",
        expected_config_id="ability_catalog_v1",
    )
    scale = load_config(
        root / "ability_scale_v1.json",
        expected_config_id="ability_scale_v1",
    )
    generation = load_config(
        root / "player_generation_v1.json",
        expected_config_id="player_generation_v1",
    )
    team = load_config(
        root / "team_strength_v1.json",
        expected_config_id="team_strength_v1",
    )

    validate_ability_catalog(catalog)
    validate_ability_scale(scale)
    validate_player_generation(generation, catalog=catalog)
    validate_team_strength(team, catalog=catalog)

    return {
        document.config_id: document
        for document in (catalog, scale, generation, team)
    }
