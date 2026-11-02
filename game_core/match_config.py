from __future__ import annotations

import copy
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
    "ground_out",
    "fly_out",
    "double_play",
    "bunt_pop_out",
    "bunt_double_play",
    "line_drive_double_play",
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

    model = payload.get("plate_appearance_model")
    if not isinstance(model, dict):
        raise ValueError("match simulation: plate_appearance_model required")
    base = model.get("base_probabilities")
    if not isinstance(base, dict):
        raise ValueError("match simulation: base_probabilities required")
    expected_events = {
        "strikeout",
        "walk",
        "hit_by_pitch",
        "single",
        "double",
        "triple",
        "home_run",
        "reached_on_error",
        "fielder_choice",
        "field_out",
    }
    if set(base) != expected_events:
        raise ValueError(
            "match simulation: base probability event keys mismatch"
        )
    total = 0.0
    for event_type, value in base.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(
                f"match simulation: invalid base probability {event_type}"
            )
        value = float(value)
        if value <= 0 or value >= 1:
            raise ValueError(
                f"match simulation: base probability {event_type} must be 0..1"
            )
        total += value
    if abs(total - 1.0) > 1e-9:
        raise ValueError(
            f"match simulation: base probabilities must sum to 1.0, got {total}"
        )

    effects = model.get("ability_effect_scale")
    expected_effects = {
        "strikeout",
        "walk",
        "single",
        "extra_base_hit",
        "home_run",
        "error",
        "field_out",
    }
    if not isinstance(effects, dict) or set(effects) != expected_effects:
        raise ValueError(
            "match simulation: ability_effect_scale keys mismatch"
        )
    for key, value in effects.items():
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or float(value) < 0
        ):
            raise ValueError(
                f"match simulation: ability effect {key} must be >= 0"
            )
    floor = model.get("probability_floor")
    if (
        not isinstance(floor, (int, float))
        or isinstance(floor, bool)
        or not 0 < float(floor) < 0.05
    ):
        raise ValueError(
            "match simulation: probability_floor must be in (0, 0.05)"
        )

    situational = payload.get("situational_events")
    if not isinstance(situational, dict):
        raise ValueError("match simulation: situational_events required")
    if set(situational) != {"sacrifice_fly"}:
        raise ValueError(
            "match simulation: situational event keys mismatch"
        )
    for key, settings in situational.items():
        if not isinstance(settings, dict):
            raise ValueError(
                f"match simulation: situational {key} must be object"
            )
        if settings.get("enabled") is not True:
            raise ValueError(
                f"match simulation: situational {key} must remain enabled"
            )
        probability = settings.get("base_probability")
        if (
            not isinstance(probability, (int, float))
            or isinstance(probability, bool)
            or not 0 <= float(probability) <= 1
        ):
            raise ValueError(
                f"match simulation: invalid {key} base_probability"
            )

    outs_in_play = payload.get("outs_in_play")
    if not isinstance(outs_in_play, dict):
        raise ValueError("match simulation: outs_in_play required")
    for section, keys in (
        ("ground_share", ("base", "min", "max")),
        ("double_play", ("base", "min", "max")),
        ("advance", ("ground_second_to_third", "ground_third_scores", "fly_second_to_third")),
    ):
        values = outs_in_play.get(section)
        if not isinstance(values, dict):
            raise ValueError(f"match simulation: outs_in_play.{section} required")
        for key in keys:
            value = values.get(key)
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not 0 <= float(value) <= 1):
                raise ValueError(f"match simulation: invalid outs_in_play.{section}.{key}")
    for key in ("per_groundball_point", "per_power_point", "per_contact_point"):
        if not isinstance(outs_in_play["ground_share"].get(key), (int, float)):
            raise ValueError(f"match simulation: invalid outs_in_play.ground_share.{key}")
    for key in ("speed_effect_per_point", "defense_effect_per_point"):
        if not isinstance(outs_in_play["double_play"].get(key), (int, float)):
            raise ValueError(f"match simulation: invalid outs_in_play.double_play.{key}")

    steals = payload.get("stolen_bases")
    if not isinstance(steals, dict):
        raise ValueError("match simulation: stolen_bases required")
    for section, keys in (
        ("attempt", ("second_base", "third_base", "max_probability")),
        ("success", ("second_base", "third_base", "min", "max")),
        ("pickoff", ("base", "min", "max")),
    ):
        values = steals.get(section)
        if not isinstance(values, dict):
            raise ValueError(f"match simulation: stolen_bases.{section} required")
        for key in keys:
            value = values.get(key)
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not 0 <= float(value) <= 1):
                raise ValueError(f"match simulation: invalid stolen_bases.{section}.{key}")
    outs_multiplier = steals["attempt"].get("outs_multiplier")
    if not (isinstance(outs_multiplier, list) and len(outs_multiplier) == 3
            and all(isinstance(v, (int, float)) and v >= 0 for v in outs_multiplier)):
        raise ValueError("match simulation: stolen_bases.attempt.outs_multiplier needs 3 values")

    _validate_strategy(payload.get("strategy"))
    _validate_substitutions(payload.get("substitutions"))
    _validate_h1(payload)

    fatigue = payload.get("fatigue")
    if not isinstance(fatigue, dict):
        raise ValueError("match simulation: fatigue required")
    for section, keys in (
        ("in_game", ("base_pitches", "per_stamina", "per_pitch")),
        ("carry", ("free_pitches", "per_pitch", "recovery_per_day", "recovery_per_stamina",
                   "min_recovery_per_day")),
        ("drop", ("velocity_kmh", "stuff", "control", "pitch_quality", "pitch_command")),
        ("change", ("starter_points", "reliever_points")),
    ):
        values = fatigue.get(section)
        if not isinstance(values, dict) or not all(
                isinstance(values.get(k), (int, float)) and not isinstance(values.get(k), bool)
                for k in keys):
            raise ValueError(f"match simulation: invalid fatigue.{section}")
    if not (isinstance(fatigue.get("stage_points"), (int, float)) and fatigue["stage_points"] > 0
            and isinstance(fatigue.get("max_stage"), int) and fatigue["max_stage"] >= 0
            and isinstance(fatigue.get("rest_starter_points"), (int, float))
            and isinstance(fatigue.get("labels"), list)):
        raise ValueError("match simulation: invalid fatigue stages")
    relief = fatigue.get("rested_ace_relief")
    if not isinstance(relief, dict) or not all(
            isinstance(relief.get(k), (int, float)) and not isinstance(relief.get(k), bool)
            for k in ("late_inning_from", "close_margin", "max_carry_points", "quality_gap_points",
                      "base_probability", "max_probability")):
        raise ValueError("match simulation: invalid fatigue.rested_ace_relief")

    effects = payload.get("pitcher_effects")
    if not isinstance(effects, dict):
        raise ValueError("match simulation: pitcher_effects required")
    for key in ("velocity_center", "points_per_kmh", "control_pivot", "command_weight"):
        if not isinstance(effects.get(key), (int, float)) or isinstance(effects.get(key), bool):
            raise ValueError(f"match simulation: invalid pitcher_effects.{key}")
    if not 0 <= float(effects["command_weight"]) <= 1:
        raise ValueError("match simulation: pitcher_effects.command_weight must be 0..1")
    components = {"velocity", "stuff", "pitch_quality", "groundball", "control_low"}
    weights = effects.get("weights")
    if not isinstance(weights, dict) or set(weights) != {
            "whiff", "single", "extra_base_hit", "home_run", "field_out"}:
        raise ValueError("match simulation: pitcher_effects.weights keys mismatch")
    for outcome, values in weights.items():
        if not isinstance(values, dict) or not set(values) <= components or not all(
                isinstance(v, (int, float)) and v >= 0 for v in values.values()):
            raise ValueError(f"match simulation: invalid pitcher_effects.weights.{outcome}")

    platoon = payload.get("platoon")
    if not isinstance(platoon, dict):
        raise ValueError("match simulation: platoon required")
    same = platoon.get("same_side_points")
    if not isinstance(same, dict) or set(same) != {"R", "L"}:
        raise ValueError("match simulation: platoon.same_side_points needs R and L")
    for value in (*same.values(), platoon.get("opposite_side_points"), platoon.get("trait_points")):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValueError("match simulation: platoon points must be >= 0")
    weights = platoon.get("ability_weights")
    if not isinstance(weights, dict) or not set(weights) <= {
            "contact", "power", "plate_discipline", "strikeout_resistance"}:
        raise ValueError("match simulation: invalid platoon.ability_weights")

    baserunning = payload.get("baserunning")
    if not isinstance(baserunning, dict):
        raise ValueError("match simulation: baserunning required")
    probability_keys = (
        "single_runner_from_second_score_base",
        "single_runner_from_first_to_third_base",
        "double_runner_from_first_score_base",
        "error_runner_from_second_score_base",
        "min_probability",
        "max_probability",
    )
    for key in probability_keys:
        value = baserunning.get(key)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not 0 <= float(value) <= 1
        ):
            raise ValueError(
                f"match simulation: invalid baserunning {key}"
            )
    if float(baserunning["min_probability"]) >= float(
        baserunning["max_probability"]
    ):
        raise ValueError(
            "match simulation: baserunning min_probability must be < max_probability"
        )
    for key in ("speed_effect_per_point", "defense_effect_per_point"):
        value = baserunning.get(key)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or float(value) < 0
        ):
            raise ValueError(
                f"match simulation: invalid baserunning {key}"
            )

    pitching_usage = payload.get("pitching_usage")
    if not isinstance(pitching_usage, dict):
        raise ValueError("match simulation: pitching_usage required")
    for key in (
        "starter_bf_base",
        "starter_stamina_effect",
        "reliever_bf_base",
        "reliever_stamina_effect",
        "minimum_bf_before_change",
        "runs_allowed_quick_hook",
        "starter_minimum_pitches",
        "reliever_minimum_pitches",
        "emergency_pitcher_ability",
    ):
        value = pitching_usage.get(key)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or float(value) < 0
        ):
            raise ValueError(
                f"match simulation: invalid pitching_usage {key}"
            )

    by_event = (payload.get("pitch_count") or {}).get("by_event")
    if not isinstance(by_event, dict) or not by_event:
        raise ValueError("match simulation: pitch_count.by_event required")
    for event_type, pair in by_event.items():
        if (
            not isinstance(pair, list) or len(pair) != 2
            or any(not isinstance(v, int) or isinstance(v, bool) for v in pair)
            or pair[0] < 1 or pair[1] < 0
        ):
            raise ValueError(
                f"match simulation: invalid pitch_count {event_type}"
            )

    namespaces = payload.get("rng_namespace_policy")
    if set(namespaces or {}) != {
        "match",
        "plate_appearance",
        "event",
        "pitches",
        "steal",
        "relief",
        "tactic",
        "wild_pitch",
    }:
        raise ValueError(
            "match simulation: RNG namespace keys mismatch"
        )
    required_placeholders = {
        "match": ("{competition_id}", "{reference_year}", "{match_id}"),
        "plate_appearance": ("{match_id}", "{plate_appearance_no}"),
        "event": ("{match_id}", "{event_no}"),
        "pitches": ("{match_id}", "{plate_appearance_no}"),
        "steal": ("{match_id}", "{plate_appearance_no}"),
        "relief": ("{match_id}", "{plate_appearance_no}"),
        "tactic": ("{match_id}", "{plate_appearance_no}"),
        "wild_pitch": ("{match_id}", "{plate_appearance_no}"),
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


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _probability(value) -> bool:
    return _number(value) and 0 <= float(value) <= 1


def _validate_strategy(strategy) -> None:
    """作戦（段階F1）の値。確率は0〜1、倍率・係数は数、失敗の重みは正。"""
    if not isinstance(strategy, dict):
        raise ValueError("match simulation: strategy required")
    shapes = {
        "sacrifice_bunt": (("max_probability",), ("close_margin", "ahead_far_multiplier",
                           "behind_far_multiplier", "late_inning_from", "late_close_multiplier",
                           "batter_hitting_log_per_point", "bunt_log_per_point")),
        "squeeze": (("max_probability",), ("max_margin", "close_margin", "late_inning_from",
                    "late_close_multiplier", "batter_hitting_log_per_point")),
        "hit_and_run": (("base", "max_probability", "far_margin_multiplier", "double_play_multiplier",
                        "single_first_to_third_bonus", "double_first_scores_bonus",
                        "fly_runner_doubled_off"),
                        ("max_outs", "max_margin", "contact_log_per_point",
                         "strikeout_resistance_log_per_point", "runner_speed_log_per_point",
                         "strikeout_multiplier", "walk_multiplier")),
        "two_strike": ((), ("strikeout_multiplier", "walk_multiplier", "extra_pitches")),
    }
    for section, (probabilities, numbers) in shapes.items():
        values = strategy.get(section)
        if not isinstance(values, dict):
            raise ValueError(f"match simulation: strategy.{section} required")
        if not all(_probability(values.get(k)) for k in probabilities):
            raise ValueError(f"match simulation: invalid strategy.{section} probability")
        if not all(_number(values.get(k)) and float(values[k]) >= 0 for k in numbers):
            raise ValueError(f"match simulation: invalid strategy.{section} value")
    bunt = strategy["sacrifice_bunt"]
    if set(bunt.get("base", {})) != {"0", "1"} or not all(
            set(row) == {"first", "second", "first_second"} and all(_probability(v) for v in row.values())
            for row in bunt["base"].values()):
        raise ValueError("match simulation: invalid strategy.sacrifice_bunt.base")
    squeeze = strategy["squeeze"]
    if not (isinstance(squeeze.get("base"), list) and len(squeeze["base"]) == 2
            and all(_probability(v) for v in squeeze["base"])):
        raise ValueError("match simulation: invalid strategy.squeeze.base")
    for section, kinds, extra in (("sacrifice_bunt", {"foul", "pop", "fc", "dp"},
                                   ("per_bunt_point", "per_speed_point", "per_defense_point")),
                                  ("squeeze", {"fc", "pop", "dp"},
                                   ("per_bunt_point", "per_runner_speed_point"))):
        success = strategy[section].get("success")
        if not (isinstance(success, dict) and all(_probability(success.get(k)) for k in ("base", "min", "max"))
                and success["min"] <= success["max"] and all(_number(success.get(k)) for k in extra)):
            raise ValueError(f"match simulation: invalid strategy.{section}.success")
        weights = strategy[section].get("failure_weights")
        if not (isinstance(weights, dict) and set(weights) == kinds
                and all(_number(v) and v >= 0 for v in weights.values()) and sum(weights.values()) > 0):
            raise ValueError(f"match simulation: invalid strategy.{section}.failure_weights")


def _validate_h1(payload) -> None:
    """度胸（G）・暴投と捕逸・重盗と本盗・球数の傾向（H1）の値。"""
    pressure = payload.get("pressure")
    if not (isinstance(pressure, dict) and all(_number(pressure.get(k)) and float(pressure[k]) >= 0 for k in (
            "late_inning_from", "close_margin", "pivot", "control_per_point", "stuff_per_point", "max_points"))):
        raise ValueError("match simulation: invalid pressure")
    wild = payload.get("wild_pitches")
    if not (isinstance(wild, dict) and _number(wild.get("catcher_catching_default"))
            and all(isinstance(wild.get(k), dict) and _probability(wild[k].get("base"))
                    and _probability(wild[k].get("max")) for k in ("wild_pitch", "passed_ball"))):
        raise ValueError("match simulation: invalid wild_pitches")
    steals = payload["stolen_bases"]
    double, home = steals.get("double_steal"), steals.get("home_steal")
    if not (isinstance(double, dict) and _number(double.get("attempt_multiplier"))
            and _number(double.get("success_bonus"))):
        raise ValueError("match simulation: invalid stolen_bases.double_steal")
    if not (isinstance(home, dict) and _probability(home.get("base")) and _probability(home.get("max_probability"))
            and isinstance(home.get("success"), dict)
            and all(_probability(home["success"].get(k)) for k in ("base", "min", "max"))):
        raise ValueError("match simulation: invalid stolen_bases.home_steal")
    tendency = payload["pitch_count"].get("tendency")
    if not (isinstance(tendency, dict) and _probability(tendency.get("base"))
            and _probability(tendency.get("max_probability"))
            and isinstance(tendency.get("max_extra"), int) and tendency["max_extra"] >= 0):
        raise ValueError("match simulation: invalid pitch_count.tendency")


def _validate_substitutions(subs) -> None:
    """選手の交代（段階F2）の値。回・点差・人数は0以上の整数、能力の差は0以上の数。"""
    if not isinstance(subs, dict) or not isinstance(subs.get("late_inning_from"), int):
        raise ValueError("match simulation: substitutions required")
    shapes = {
        "pinch_hitter": (("max_deficit", "max_lead", "max_per_game"), ("min_gain", "pitcher_slot_min_gain")),
        "pinch_runner": (("inning_from", "max_deficit", "max_lead", "max_runner_speed", "max_per_game"),
                         ("min_speed_gain",)),
        "defensive_replacement": (("min_lead", "max_lead", "max_per_half"), ("min_gain", "entered_min_gain")),
        "platoon_lineup": (("max_selection_swaps", "max_order_swaps"),
                           ("selection_min_gain", "max_defense_loss", "order_min_gain")),
        "platoon_relief": (("inning_from", "close_margin", "lookahead", "min_same_side", "min_batters_faced"),
                           ("max_quality_gap",)),
    }
    for section, (integers, numbers) in shapes.items():
        values = subs.get(section)
        if not isinstance(values, dict):
            raise ValueError(f"match simulation: substitutions.{section} required")
        if not all(isinstance(values.get(k), int) and not isinstance(values.get(k), bool)
                   and values[k] >= 0 for k in integers):
            raise ValueError(f"match simulation: invalid substitutions.{section} count")
        if not all(_number(values.get(k)) and float(values[k]) >= 0 for k in numbers):
            raise ValueError(f"match simulation: invalid substitutions.{section} value")
    relief = subs["platoon_relief"]
    if relief["min_same_side"] > relief["lookahead"]:
        raise ValueError("match simulation: platoon_relief.min_same_side exceeds lookahead")


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
        "grounded_into_double_plays",
        "picked_off",
        "catcher_steal_attempts",
        "catcher_caught_stealing",
        "passed_balls",
        *(f"vs_{hand}_{key}" for hand in ("rhp", "lhp")
          for key in ("at_bats", "hits", "home_runs", "walks", "strikeouts")),
        "pinch_hit_at_bats",
        "pinch_hit_hits",
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
        "pitches",
        "exit_fatigue",
        "wild_pitches",
        *(f"vs_{hand}_{key}" for hand in ("rhb", "lhb")
          for key in ("at_bats", "hits", "home_runs", "walks", "strikeouts")),
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


MATCH_CONFIG_FILES = (
    "match_simulation_v1.json",
    "event_catalog_v1.json",
    "game_stats_contract_v1.json",
)
# 試合の記録を1球ごとに検査するたびに読み直さないよう、検査済みの設定を
# ファイルの更新時刻ごとに覚えておく。
_VALIDATED: dict[tuple, dict[str, ConfigDocument]] = {}


def load_and_validate_match_configs(
    config_dir: str | Path = "config/match",
) -> dict[str, ConfigDocument]:
    root = Path(config_dir)
    key = (str(root.resolve()),) + tuple(
        (root / name).stat().st_mtime_ns for name in MATCH_CONFIG_FILES
    )
    cached = _VALIDATED.get(key)
    if cached is None:
        cached = _load_and_validate_match_configs(root)
        _VALIDATED[key] = cached
    # 呼び出し側が params を書き換えても、覚えておいた設定（ほかの試合計算）に漏れないよう写しを返す
    return copy.deepcopy(cached)


def _load_and_validate_match_configs(
    root: Path,
) -> dict[str, ConfigDocument]:
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
