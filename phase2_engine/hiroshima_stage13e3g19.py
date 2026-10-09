"""Stage13E-3G-19: audited *candidate* second-chance gate contracts.

2026 secondary result sequences support 6 after-loss re-appearances in 5
subsequent games. They do NOT prove any general year-independent draw
transfer condition, because the federation bracket PDF bodies are unread.
The separate pure prototype must remain disconnected from the live FMT025
season runtime until independently verified routing inputs are available.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g18 import (
    SECOND_CHANCE_FILE, TRANSITION_FILE,
    audit_2026_hiroshima_stage13e3g18,
)
from .hiroshima_stage13e3g17 import GROUP_CONTRACT_FILE, CROSSWALK_FILE
from .hiroshima_stage13e3g16 import EVENT_FILE
from .hiroshima_qualification_timeline_2026 import TIMELINE_FILE

GATE_OBSERVATIONS_FILE = "competitions/2026/hiroshima_retry_gate_observations_2026.csv"
GATE_POLICY_FILE = "competitions/2026/hiroshima_retry_gate_group_policies_2026.csv"

EXPECTED_SEASONAL_GROUPS = {
    ("spring","west"), ("spring","north"), ("spring","south"), ("spring","east"),
    ("autumn","west"), ("autumn","north"), ("autumn","south"), ("autumn","east"),
}
EXPECTED_OBSERVED_COUNTS = {
    ("spring","west"):0, ("spring","north"):1,
    ("spring","south"):0, ("spring","east"):1,
    ("autumn","west"):0, ("autumn","north"):0,
    ("autumn","south"):2, ("autumn","east"):2,
}


def audit_2026_hiroshima_stage13e3g19(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    observed = _read(root, GATE_OBSERVATIONS_FILE)
    policies = _read(root, GATE_POLICY_FILE)
    examples = _read(root, SECOND_CHANCE_FILE)
    transitions = _read(root, TRANSITION_FILE)
    events = _read(root, EVENT_FILE)
    crosswalk = _read(root, CROSSWALK_FILE)
    groups = _read(root, GROUP_CONTRACT_FILE)
    matches = _read(root, TIMELINE_FILE)
    previous = audit_2026_hiroshima_stage13e3g18(root)
    errors = list(previous["errors"])
    if not previous["ok"]:
        errors.append("earlier chronology/source audit must succeed")
    if len(observed) != 6 or len(examples) != 6:
        errors.append("six observed after-loss cases required")
    if len(policies) != 8:
        errors.append("eight separate season-district gate policies required")
    if len(matches) != 223:
        errors.append("223 secondary result source matches required")

    event_by_match = {r["matched_match_id"]: r for r in events}
    route_by_event = {
        r["matched_publisher_event_check_id"]:r
        for r in crosswalk if r["matched_publisher_event_check_id"]
    }
    trans_by_id = {r["transition_id"]:r for r in transitions}
    match_by_id = {r["match_id"]:r for r in matches}
    group_by_key = {(r["season"],r["district_code"]):r for r in groups}
    by_policy_key = {(r["season"],r["district_code"]):r for r in policies}

    if (len(event_by_match) != 15 or len(route_by_event) != 15
        or len(trans_by_id) != 287 or len(match_by_id) != 223
        or len(group_by_key) != 8):
        errors.append("published parent event, legacy match and group keys must be unique")
    if (len(by_policy_key) != len(policies)
        or set(by_policy_key) != EXPECTED_SEASONAL_GROUPS):
        errors.append("eight unique seasonal district policy records required")

    observed_keys = set()
    per_group = Counter()
    followup_by_group: dict[tuple, list[str]] = {}
    for source, rec in zip(examples, observed):
        k = (rec["season"], rec["district_code"])
        source_event = event_by_match.get(source["first_qualification_decider_loss_id"])
        subsequent_event = event_by_match.get(source["second_qualification_decider_id"])
        subsequent_route = (
            route_by_event.get(subsequent_event["check_id"])
            if subsequent_event else None
        )
        from_game = match_by_id.get(source["first_qualification_decider_loss_id"])
        to_game = match_by_id.get(source["second_qualification_decider_id"])
        t = trans_by_id.get(source["evidence_transition_id"])
        if rec["observation_id"] in observed_keys:
            errors.append(f"duplicate after-loss observation: {rec['observation_id']}")
        observed_keys.add(rec["observation_id"])
        per_group[k] += 1
        dests = followup_by_group.setdefault(k, [])
        if rec["subsequent_decider_match_id"] not in dests:
            dests.append(rec["subsequent_decider_match_id"])

        fields = {
            "observation_id":source["special_case_id"],
            "season":source["season"],
            "district_code":source["district_code"],
            "school_display_name":source["school_display_name"],
            "losing_decider_match_id":source["first_qualification_decider_loss_id"],
            "subsequent_decider_match_id":source["second_qualification_decider_id"],
            "observed_transition_id":source["evidence_transition_id"],
            "losing_publisher_event_check_id":(
                source_event["check_id"] if source_event else ""
            ),
            "subsequent_publisher_event_check_id":(
                subsequent_event["check_id"] if subsequent_event else ""
            ),
            "subsequent_publisher_route_id":(
                subsequent_route["route_id"] if subsequent_route else ""
            ),
            "subsequent_gate_role":(
                subsequent_event["stage_role"] if subsequent_event else ""
            ),
            "observed_second_gate_winner":source["second_match_winner"],
            "observed_second_gate_berth_award":source["second_match_winner_has_berth_award"],
            "observed_transition_scope":"secondary_result_two_dated_matches",
            "official_loser_transfer_rule_verified":"no",
            "annual_independent_retry_authorized":"no",
            "runtime_retry_gate_enabled":"no",
            "result_source_url":source["source_url"],
        }
        for field, value in fields.items():
            if rec.get(field) != value:
                errors.append(f"retry gate observation differs from source: {rec['observation_id']} {field}")
        if (
            from_game is None or to_game is None or t is None
            or subsequent_event is None or subsequent_route is None
        ):
            errors.append(f"missing existing event/transition evidence: {rec['observation_id']}")
            continue
        if (
            t["transition_kind"] != "LOSS_REPECHAGE_TO_REPECHAGE"
            or t["from_match_id"] != from_game["match_id"]
            or t["to_match_id"] != to_game["match_id"]
            or t["school_display_name"] != source["school_display_name"]
            or subsequent_event["season"] != k[0]
            or subsequent_event["district_code"] != k[1]
            or subsequent_route["stage_group_id"] != from_game["stage_group_id"]
            or from_game["match_date"] >= to_game["match_date"]
            or from_game["team2_name"] != source["school_display_name"]
            or to_game["winner_berth_status"] != "berth_award"
        ):
            errors.append(f"invalid observed qualifier gate continuity: {rec['observation_id']}")

    if per_group != Counter({k:v for k,v in EXPECTED_OBSERVED_COUNTS.items() if v}):
        errors.append(f"six observed retry group distribution changed: {per_group}")
    if len({r["subsequent_decider_match_id"] for r in observed}) != 5:
        errors.append("six observed retry entrants must reach five distinct second games")

    total_quota = Counter()
    for key in EXPECTED_SEASONAL_GROUPS:
        row = by_policy_key.get(key)
        g = group_by_key.get(key)
        if row is None or g is None:
            errors.append(f"gate policy/season group missing: {key}")
            continue
        want = {
            "season":key[0], "district_code":key[1],
            "stage_group_id":g["stage_group_id"], "format_model_id":"FMT025",
            "required_qualifier_awards":g["required_qualifier_awards"],
            "primary_berth_slots":g["observed_first_place_event_slots"],
            "nonprimary_berth_slots":g["expected_nonprimary_awards"],
            "published_cross_zone_gate_event_count":g["observed_cross_decider_event_count"],
            "observed_loser_to_new_decider_transition_count":str(per_group[key]),
            "observed_next_gate_match_ids":";".join(followup_by_group.get(key,[])),
            "generic_gate_candidate_policy":"require_named_upstream_outcome_and_explicit_target",
            "retry_policy":"deny_by_default_unless_annual_rule_authorized",
            "retry_gate_proof":"historical_match_sequence_only",
            "supports_arbitrary_team_ids_in_prototype":"yes",
            "official_draw_gate_edges_verified":"no",
            "game_runtime_enabled":"no",
            "optional_ranking_release_allowed":"no",
        }
        for field, value in want.items():
            if row.get(field) != value:
                errors.append(f"seasonal retry gate policy mismatch: {key} {field}")
        if not row.get("policy_id"):
            errors.append(f"unnamed group gate policy: {key}")
        total_quota["qualifiers"] += int(g["required_qualifier_awards"])
        total_quota["primary"] += int(g["observed_first_place_event_slots"])
        total_quota["nonprimary"] += int(g["expected_nonprimary_awards"])
        total_quota["publisher_gates"] += int(g["observed_cross_decider_event_count"])
    if len({r["policy_id"] for r in policies}) != 8:
        errors.append("group gate policy IDs must be unique")
    if total_quota != {"qualifiers":63,"primary":38,"nonprimary":25,"publisher_gates":14}:
        errors.append(f"63/38/25 qualifiers and 14 published cross gates changed: {total_quota}")

    return {
        "ok":not errors,
        "errors":errors,
        "observed_retry_participant_sequences":len(observed),
        "distinct_observed_retry_target_matches":len({
            r["subsequent_decider_match_id"] for r in observed
        }),
        "seasonal_group_policies":len(policies),
        "group_retry_counts":{
            f"{s}_{d}":per_group[(s,d)] for s,d in sorted(EXPECTED_SEASONAL_GROUPS)
        },
        "quota":dict(total_quota),
        "historical_match_continuity_covered":len(transitions),
        "candidate_graph_requires_explicit_loser_target":True,
        "inferred_annual_draw_edges_authorized":0,
        "official_federation_pdf_body_verified":0,
        "active_fmt025_runtime_changed":False,
        "optional_ranking_game_enabled":False,
        "source_scope":"secondary_2026_results_and_publisher_events_not_general_draw",
    }
