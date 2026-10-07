from __future__ import annotations

from pathlib import Path
from typing import Any

from .ability_config import ConfigDocument, load_config


REQUIRED_EVENT_TYPES = {
    "strikeout",
    "walk",
    "hit_by_pitch",
    "single",
    "double",
    "triple",
    "home_run",
    "field_out",
    "fielder_choice",
    "reached_on_error",
    "sacrifice_bunt",
    "sacrifice_fly",
}


def _require_bool(value: Any, label: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{label}: boolean required")


def validate_match_simulation_config(document: ConfigDocument) -> None:
    payload = document.payload
    if payload.get("score_source") != "ability_model_v1":
        raise ValueError(
            "match simulation: score_source must be ability_model_v1"
        )

    team_order = payload.get("team_order")
    if team_order != {
        "team1": "top_offense",
        "team2": "bottom_offense",
    }:
        raise ValueError(
            "match simulation: team order contract mismatch"
        )

    innings = payload.get("innings")
    if not isinstance(innings, dict):
        raise ValueError("match simulation: innings required")
    regulation = innings.get("default_regulation_innings")
    if not isinstance(regulation, int) or regulation < 1:
        raise ValueError(
            "match simulation: default_regulation_innings must be >= 1"
        )
    if innings.get("tie_allowed") is not False:
        raise ValueError(
            "match simulation: completed tournament game cannot allow tie"
        )
    if innings.get("competition_rule_override") is not True:
        raise ValueError(
            "match simulation: competition rule override must remain enabled"
        )

    ownership = payload.get("ownership")
    if not isinstance(ownership, dict):
        raise ValueError("match simulation: ownership required")
    for key in (
        "simulator_determines_score",
        "simulator_determines_winner",
        "tournament_match_must_be_synchronized_before_result_view",
    ):
        if ownership.get(key) is not True:
            raise ValueError(
                f"match simulation: ownership.{key} must be true"
            )

    result_view = payload.get("result_view")
    if not isinstance(result_view, dict):
        raise ValueError("match simulation: result_view required")
    if result_view.get("score_source_precedence") != [
        "override",
        "ability_model_v1",
        "generated_v1",
    ]:
        raise ValueError(
            "match simulation: ResultView precedence contract mismatch"
        )
    if result_view.get(
        "actual_score_override_remains_highest_priority"
    ) is not True:
        raise ValueError(
            "match simulation: actual override must remain highest priority"
        )
    if result_view.get("winner_consistency_required") is not True:
        raise ValueError(
            "match simulation: winner consistency must be required"
        )

    rules = payload.get("rules")
    if not isinstance(rules, dict):
        raise ValueError("match simulation: rules required")
    if rules.get("team_strength_direct_bonus_for_score") is not False:
        raise ValueError(
            "match simulation: direct team strength score bonus forbidden"
        )
    for key in (
        "use_component_strengths",
        "player_abilities_drive_events",
        "complete_game_stats_required",
        "event_stats_reconciliation_required",
    ):
        if rules.get(key) is not True:
            raise ValueError(
                f"match simulation: rules.{key} must be true"
            )

    namespaces = payload.get("rng_namespace_policy")
    if set(namespaces or {}) != {
        "match",
        "plate_appearance",
        "event",
    }:
        raise ValueError(
            "match simulation: RNG namespace keys mismatch"
        )
    required_placeholders = {
        "match": ("{competition_id}", "{reference_year}", "{match_id}"),
        "plate_appearance": ("{match_id}", "{plate_appearance_no}"),
        "event": ("{match_id}", "{event_no}"),
    }
    for key, placeholders in required_placeholders.items():
        template = str(namespaces[key])
        if "_v1:" not in template:
            raise ValueError(
                f"match simulation: {key} namespace must be versioned"
            )
        if any(value not in template for value in placeholders):
            raise ValueError(
                f"match simulation: {key} namespace placeholders mismatch"
            )


def validate_event_catalog(document: ConfigDocument) -> None:
    items = document.payload.get("event_types")
    if not isinstance(items, list) or not items:
        raise ValueError("event catalog: event_types required")

    by_id: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("event catalog: each event must be object")
        event_type = str(item.get("event_type", ""))
        if not event_type:
            raise ValueError("event catalog: event_type required")
        if event_type in by_id:
            raise ValueError(
                f"event catalog: duplicate event_type {event_type}"
            )
        by_id[event_type] = item
        if item.get("is_plate_appearance") is not True:
            raise ValueError(
                f"event catalog: {event_type} must be plate appearance in v1"
            )
        _require_bool(
            item.get("counts_as_at_bat"),
            f"event catalog.{event_type}.counts_as_at_bat",
        )
        hit_value = item.get("hit_value")
        if (
            not isinstance(hit_value, int)
            or isinstance(hit_value, bool)
            or not 0 <= hit_value <= 4
        ):
            raise ValueError(
                f"event catalog: invalid hit_value for {event_type}"
            )
        outs = item.get("default_outs_on_play")
        if (
            not isinstance(outs, int)
            or isinstance(outs, bool)
            or not 0 <= outs <= 3
        ):
            raise ValueError(
                f"event catalog: invalid outs for {event_type}"
            )

    missing = REQUIRED_EVENT_TYPES - set(by_id)
    if missing:
        raise ValueError(
            f"event catalog: required event types missing {sorted(missing)}"
        )
    expected_hits = {
        "single": 1,
        "double": 2,
        "triple": 3,
        "home_run": 4,
    }
    for event_type, value in expected_hits.items():
        if by_id[event_type]["hit_value"] != value:
            raise ValueError(
                f"event catalog: {event_type} hit_value must be {value}"
            )


def validate_game_stats_contract(document: ConfigDocument) -> None:
    payload = document.payload
    expected_batter = {
        "plate_appearances",
        "at_bats",
        "runs",
        "hits",
        "doubles",
        "triples",
        "home_runs",
        "rbi",
        "walks",
        "strikeouts",
        "hit_by_pitch",
        "sacrifice_flies",
        "sacrifice_bunts",
        "stolen_bases",
        "caught_stealing",
    }
    expected_pitcher = {
        "outs_recorded",
        "batters_faced",
        "runs_allowed",
        "earned_runs",
        "hits_allowed",
        "home_runs_allowed",
        "walks",
        "strikeouts",
        "hit_batters",
    }
    expected_team = {"runs", "hits", "errors"}

    if set(payload.get("batter_fields", [])) != expected_batter:
        raise ValueError("game stats: batter_fields mismatch")
    if set(payload.get("pitcher_fields", [])) != expected_pitcher:
        raise ValueError("game stats: pitcher_fields mismatch")
    if set(payload.get("team_fields", [])) != expected_team:
        raise ValueError("game stats: team_fields mismatch")

    rules = payload.get("rules")
    if not isinstance(rules, dict):
        raise ValueError("game stats: rules required")
    if rules.get("store_rate_stats") is not False:
        raise ValueError("game stats: rate stats must not be stored")
    for key in (
        "derive_rate_stats_in_read_model",
        "hits_equal_single_plus_extra_base_hits",
        "team_runs_equal_batter_runs",
        "team_hits_equal_batter_hits",
        "opponent_runs_equal_pitcher_runs_allowed",
        "team_plate_appearances_equal_opponent_batters_faced",
    ):
        if rules.get(key) is not True:
            raise ValueError(f"game stats: rules.{key} must be true")
    if rules.get("batter_pa_formula") != "AB+BB+HBP+SF+SH":
        raise ValueError("game stats: batter PA formula mismatch")


def load_and_validate_match_configs(
    config_dir: str | Path = "config/match",
) -> dict[str, ConfigDocument]:
    root = Path(config_dir)
    match = load_config(
        root / "match_simulation_v1.json",
        expected_config_id="match_simulation_v1",
    )
    events = load_config(
        root / "event_catalog_v1.json",
        expected_config_id="event_catalog_v1",
    )
    stats = load_config(
        root / "game_stats_contract_v1.json",
        expected_config_id="game_stats_contract_v1",
    )

    validate_match_simulation_config(match)
    validate_event_catalog(events)
    validate_game_stats_contract(stats)

    return {
        document.config_id: document
        for document in (match, events, stats)
    }
