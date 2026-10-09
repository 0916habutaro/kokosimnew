"""Stage13E-3G-20: yearly-independent named-zone planning and gate guards.

Crosswalk only: preserve 2026 published event labels and FMT025 quotas.
No PDF draw arrows were inspected; consequently none of the 87 named
events may be treated as a verified annual match scheduling graph.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g17 import GROUP_CONTRACT_FILE, CROSSWALK_FILE
from .hiroshima_stage13e3g19 import GATE_POLICY_FILE

ZONE_CONTRACT_FILE = "competitions/2026/hiroshima_annual_zone_rule_contract_2026.csv"
ROUTE_REQUIREMENTS_FILE = "competitions/2026/hiroshima_annual_child_route_input_requirements_2026.csv"
_PUBLISHED_GROUPS = {
    ("spring","west"): ("A","B","C","D"),
    ("spring","north"): ("A","B","C","D"),
    ("spring","south"): ("A","B","C","D","E","F"),
    ("spring","east"): ("A","B","C","D","E"),
    ("autumn","west"): ("A","B","C","D"),
    ("autumn","north"): ("A","B","C","D"),
    ("autumn","south"): ("A","B","C","D","E","F"),
    ("autumn","east"): ("A","B","C","D","E"),
}
_EXPECTED_ROLES = {
    "PRIMARY":38,"REPECHAGE_ZONE":35,"REPECHAGE_CROSS_ZONE_GATE":14,
}
_KNOWN_MERGED_ZONE_NAMES = {
    ("spring","east","C;D"),
    ("autumn","east","B;C"),
    ("autumn","east","D;E"),
}


def _expected_route(row: dict) -> dict:
    role = row["phase_execution_role"]
    name = row["published_event_name"]
    if role == "PRIMARY":
        match = re.fullmatch(r"([A-F])一位校",name)
        if not match:
            raise ValueError(f"unrecognized publisher primary label: {name}")
        zones = match.group(1)
        zone_scope = "single_primary_zone"
        source = "seeded_zone_entrant_ids_draft"
        proof = "not_required_for_zone_draft_only"
    elif role == "REPECHAGE_ZONE":
        match = re.fullmatch(r"([A-F](?:・[A-F])?)二位校",name)
        if not match:
            raise ValueError(f"unrecognized publisher second-place label: {name}")
        zones = match.group(1).replace("・",";")
        zone_scope = (
            "merged_named_secondary_zones" if ";" in zones
            else "single_secondary_zone"
        )
        source = "verified_primary_loser_transfer_required"
        proof = "annual_draw_selector_or_verified_rule_required"
    elif role == "REPECHAGE_CROSS_ZONE_GATE":
        match = re.search(r"（([^）]+)）",name)
        zones = match.group(1) if match else "unresolved"
        zone_scope = "cross_zone_label_hint_not_proof"
        source = "explicit_named_runnerup_outcome_and_retry_gate_required"
        proof = "annual_draw_selector_or_verified_rule_required"
    else:
        raise ValueError(f"unknown FMT025 child-event role {role}")
    return {
        "route_id":row["route_id"],
        "season":row["season"],
        "district_code":row["district_code"],
        "stage_group_id":row["stage_group_id"],
        "format_model_id":"FMT025",
        "phase_execution_role":role,
        "publisher_child_event_name":name,
        "named_zone_hint":zones,
        "zone_scope_class":zone_scope,
        "candidate_source_contract":source,
        "required_verified_edge":proof,
        "annual_draw_selector_present":"no",
        "loser_next_gate_rule_present":"no",
        "candidate_cohort_proven":"no",
        "is_publisher_label_evidence":"yes",
        "may_generate_draw_accurate_games":"no",
        "may_release_optional_ranking":"no",
    }


def audit_2026_hiroshima_stage13e3g20(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    proposed = _read(root,ZONE_CONTRACT_FILE)
    requirements = _read(root,ROUTE_REQUIREMENTS_FILE)
    existing = _read(root,CROSSWALK_FILE)
    upstream = _read(root,GROUP_CONTRACT_FILE)
    policy = _read(root,GATE_POLICY_FILE)
    errors: list[str] = []
    groups = {(r["season"],r["district_code"]):r for r in proposed}
    phase_by_group = {(r["season"],r["district_code"]):r for r in upstream}
    gates_by_group = {(r["season"],r["district_code"]):r for r in policy}
    source_by_id = {r["route_id"]:r for r in existing}
    named_by_id = {r["route_id"]:r for r in requirements}
    if (len(proposed)!=8 or len(groups)!=8 or set(groups)!=set(_PUBLISHED_GROUPS)
        or len(upstream)!=8 or len(phase_by_group)!=8
        or len(policy)!=8 or len(gates_by_group)!=8):
        errors.append("exactly eight distinct seasonal zone contracts and existing sources required")
    if (len(requirements)!=87 or len(named_by_id)!=87
        or len(existing)!=87 or len(source_by_id)!=87
        or set(source_by_id)!=set(named_by_id)):
        errors.append("87 published child routes and unique requirement mappings required")
    if len({r["contract_id"] for r in proposed}) != 8:
        errors.append("unique annual zone contract IDs required")
    roles = Counter()
    merged: set[tuple[str,str,str]] = set()
    coverage: dict[tuple, list[str]] = {}
    for rid, src in source_by_id.items():
        proposed_route = named_by_id.get(rid)
        if proposed_route is None:
            errors.append(f"missing route requirements {rid}")
            continue
        try:
            expected = _expected_route(src)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        role = src["phase_execution_role"]
        roles[role] += 1
        if role == "REPECHAGE_ZONE":
            normalized = expected["named_zone_hint"]
            coverage.setdefault((src["season"],src["district_code"]),[]).extend(normalized.split(";"))
            if ";" in normalized:
                merged.add((src["season"],src["district_code"],normalized))
        for field, value in expected.items():
            if proposed_route.get(field)!=value:
                errors.append(f"child route requirement mismatch: {rid}/{field}")
        if src["official_federation_pdf_verified"]!="no" or src["can_materialize_draw_accurate_runtime"]!="no":
            errors.append(f"unsupported official draw release in Stage17 source {rid}")
    if roles!=_EXPECTED_ROLES or merged!=_KNOWN_MERGED_ZONE_NAMES:
        errors.append(f"38/35/14 child role families or combined secondary events changed {roles}/{merged}")
    quotas=Counter()
    primary_zones=0
    for i,key in enumerate(_PUBLISHED_GROUPS):
        row = groups.get(key)
        source = phase_by_group.get(key)
        g = gates_by_group.get(key)
        if row is None or source is None or g is None:
            errors.append(f"missing published group/phase/retry policy {key}")
            continue
        codes = _PUBLISHED_GROUPS[key]
        if tuple(sorted(coverage.get(key,[])))!=codes:
            errors.append(f"each primary zone must be represented by exactly one secondary named event: {key}")
        primary_zones += len(codes)
        expected = {
            "contract_id":"HZC2026"+str(i+1).zfill(3),
            "season":key[0],"district_code":key[1],
            "competition_id":source["competition_id"],
            "stage_group_id":source["stage_group_id"],
            "format_model_id":"FMT025",
            "primary_zone_codes":";".join(codes),
            "primary_zone_count":str(len(codes)),
            "primary_child_event_count":source["observed_first_place_event_slots"],
            "secondary_child_event_count":source["observed_second_place_event_count"],
            "cross_zone_decider_child_event_count":source["observed_cross_decider_event_count"],
            "qualifier_award_quota":source["required_qualifier_awards"],
            "primary_award_quota":source["observed_first_place_event_slots"],
            "nonprimary_award_quota":source["expected_nonprimary_awards"],
            "direct_main_exempt_slots":source["direct_main_exempt_slots"],
            "secondary_zones_coverage":"all_primary_zones_names_cover_once",
            "entrant_partition_policy":"seeded_balanced_draft_only_not_official_draw",
            "entrant_group_school_ids_verified":"no",
            "primary_loser_forward_rule_verified":"no",
            "secondary_candidate_forward_rule_verified":"no",
            "conditional_retry_rule_verified":"no",
            "allow_live_runtime_integration":"no",
            "allow_optional_ranking":"no",
            "proof_scope":"publisher_child_event_labels_and_2026_secondary_results",
        }
        for field, want in expected.items():
            if row.get(field)!=want:
                errors.append(f"annual zone contract mismatch: {key}/{field}")
        if (g["stage_group_id"]!=source["stage_group_id"]
            or g["game_runtime_enabled"]!="no"
            or g["official_draw_gate_edges_verified"]!="no"):
            errors.append(f"unverified upstream gate policy: {key}")
        qualifiers=int(source["required_qualifier_awards"])
        pslots=int(source["observed_first_place_event_slots"])
        sslots=int(source["expected_nonprimary_awards"])
        if qualifiers!=pslots+sslots or pslots!=len(codes):
            errors.append(f"primary-secondary output conservation violated {key}")
        quotas["qualifying_winners"]+=qualifiers
        quotas["first_place"]+=pslots
        quotas["secondary"]+=sslots
        quotas["exempt"]+=int(source["direct_main_exempt_slots"])
        quotas["cross_gates"]+=int(source["observed_cross_decider_event_count"])
    if (primary_zones!=38 or quotas!={
        "qualifying_winners":63,"first_place":38,
        "secondary":25,"exempt":1,"cross_gates":14,
    }):
        errors.append(f"63/38/25/1/14 quota or 38 primary zone conservation changed: {quotas}")
    return {
        "ok":not errors,"errors":errors,
        "season_district_contracts":len(proposed),
        "published_child_route_requirements":len(requirements),
        "published_primary_zone_count":primary_zones,
        "stage_role_counts":dict(roles),
        "combined_secondary_zone_events":len(merged),
        "qualifying_slots":quotas["qualifying_winners"],
        "direct_main_exempt_slots":quotas["exempt"],
        "published_cross_zone_decider_events":quotas["cross_gates"],
        "named_zone_partition_draft_available":True,
        "individual_primary_loser_route_edges_verified":0,
        "individual_secondary_candidate_route_edges_verified":0,
        "official_bracket_pdf_bodies_inspected":0,
        "draw_accurate_match_runtime_enabled":False,
        "optional_ranking_enabled":False,
        "fmt025_design_pending":True,
        "source_scope":"publisher_named_child_event_structures_not_2026_official_draw_graph",
    }
