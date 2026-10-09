"""Stage 13E-3G-21: audit 2026 observed first-loss transitions vs release gates.

The input rows record 121 historical *next played matches*; they are not
season-independent selectors. FMT025 game runtime stays unchanged. This
audit checks the completeness of published stage labels and *missing*
annual draw transfer evidence, rather than releasing unverified fixtures.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g17 import GROUP_CONTRACT_FILE
from .hiroshima_stage13e3g18 import TRANSITION_FILE, SUMMARY_FILE
from .hiroshima_stage13e3g19 import GATE_OBSERVATIONS_FILE
from .hiroshima_stage13e3g20 import ROUTE_REQUIREMENTS_FILE, ZONE_CONTRACT_FILE

LOSS_TRACE_FILE = "competitions/2026/hiroshima_primary_loser_forwarding_observations_2026.csv"
ROUTE_EVIDENCE_FILE = "competitions/2026/hiroshima_annual_route_evidence_requirements_2026.csv"
GROUP_REVIEW_FILE = "competitions/2026/hiroshima_annual_route_release_review_2026.csv"
_REQUIRED = {
    "PRIMARY": (
        "annual_entrant_zone_assignment", "official_primary_bracket_pairings",
    ),
    "REPECHAGE_ZONE": (
        "primary_loser_round_to_secondary_selector", "secondary_zone_bracket_pairings",
    ),
    "REPECHAGE_CROSS_ZONE_GATE": (
        "runnerup_gate_candidate_selector","conditional_loser_retry_selector",
        "cross_zone_bracket_pairings",
    ),
}
_GROUP_ORDER = (
    ("spring","west"),("spring","north"),("spring","south"),("spring","east"),
    ("autumn","west"),("autumn","north"),("autumn","south"),("autumn","east"),
)


def audit_2026_hiroshima_stage13e3g21(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    originals=_read(root,TRANSITION_FILE)
    summaries=_read(root,SUMMARY_FILE)
    retry=_read(root,GATE_OBSERVATIONS_FILE)
    zone_groups=_read(root,ZONE_CONTRACT_FILE)
    stage_groups=_read(root,GROUP_CONTRACT_FILE)
    route_inputs=_read(root,ROUTE_REQUIREMENTS_FILE)
    actual_trace=_read(root,LOSS_TRACE_FILE)
    actual_route=_read(root,ROUTE_EVIDENCE_FILE)
    actual_groups=_read(root,GROUP_REVIEW_FILE)
    errors: list[str]=[]

    eligible=[x for x in originals if x["transition_kind"]=="LOSS_PRIMARY_TO_REPECHAGE"]
    if len(eligible)!=121 or len(originals)!=287:
        errors.append("121 primary-loss -> repechage transitions from 287 entries required")
    calculated=[]
    for t in eligible:
        block_known = "yes" if t["from_block_hint"] and t["to_block_hint"] else "no"
        label_same = (
            ("yes" if t["from_block_hint"]==t["to_block_hint"] else "no")
            if block_known=="yes" else "unknown"
        )
        calculated.append({
            "trace_id":"HLF2026"+str(len(calculated)+1).zfill(4),
            "observed_transition_id":t["transition_id"],
            "season":t["season"],"district_code":t["district_code"],
            "stage_group_id":t["stage_group_id"],
            "team_display_name":t["school_display_name"],
            "primary_loss_match_id":t["from_match_id"],
            "primary_loss_round":t["from_round_label"],
            "primary_loss_date":t["from_match_date"],
            "next_repechage_match_id":t["to_match_id"],
            "next_repechage_round":t["to_round_label"],
            "next_repechage_date":t["to_match_date"],
            "prior_block_display":t["from_block_hint"],
            "next_block_display":t["to_block_hint"],
            "block_display_both_known":block_known,
            "block_label_same":label_same,
            "observed_result_trace_verified":"yes",
            "source_provenance":"two_secondary_dated_match_results_not_official_draw",
            "annual_loser_selector_verified":"no",
            "annual_policy_source_id":"",
            "runtime_forwarding_authorized":"no",
            "source_result_from_url":t["from_result_source_url"],
            "source_result_to_url":t["to_result_source_url"],
        })
    if len(actual_trace)!=len(calculated):
        errors.append(f"121 primary-loser history ledger required: {len(actual_trace)}")
    for i,(got,want) in enumerate(zip(actual_trace,calculated),1):
        if got!=want:
            cols=[k for k in want if got.get(k)!=want[k]]
            errors.append(f"primary-loser historical row {i} mismatch: {cols}")
            break
    both=sum(x["block_display_both_known"]=="yes" for x in calculated)
    same=sum(x["block_label_same"]=="yes" for x in calculated)
    if both!=103 or same!=103:
        errors.append(f"block labels in 103 of 121 losing progressions changed: {both}/{same}")

    named={x["route_id"]:x for x in route_inputs}
    evidence={x["route_id"]:x for x in actual_route}
    if len(route_inputs)!=87 or len(named)!=87 or len(actual_route)!=87 or len(evidence)!=87 or set(named)!=set(evidence):
        errors.append("87 unique Stage20 named routes and 87 evidence requirements required")
    target_counts=Counter(x["target_publisher_route_id"] for x in originals
                          if x["target_publisher_route_id"])
    role_counts=Counter()
    for rid,src in named.items():
        record=evidence.get(rid)
        if not record:
            errors.append(f"missing route evidence {rid}")
            continue
        role=src["phase_execution_role"]
        requires=_REQUIRED.get(role)
        if requires is None:
            errors.append(f"unexpected Stage20 route role: {rid}")
            continue
        role_counts[role]+=1
        fields={
            "route_id":rid,
            "season":src["season"],"district_code":src["district_code"],
            "stage_group_id":src["stage_group_id"],"role":role,
            "named_zone_hint":src["named_zone_hint"],
            "required_annual_evidence_items":";".join(requires),
            "publisher_event_label_exists":"yes",
            "observed_2026_transition_target_count":str(target_counts[rid]),
            "zone_entrant_assignment_verified":"no",
            "primary_loser_transfer_verified":"no",
            "secondary_candidate_transfer_verified":"no",
            "conditional_retry_transfer_verified":"no",
            "official_pairings_verified":"no",
            "approved_simulation_policy_id":"",
            "official_provenance_document_id":"",
            "draw_readiness":"blocked_missing_official_transfer_and_pairing_evidence",
            "safe_preview_only":"yes",
            "live_fmt025_runtime_allowed":"no",
            "ranking_additional_matches_allowed":"no",
        }
        for col,value in fields.items():
            if record.get(col)!=value:
                errors.append(f"annual route evidence mismatch: {rid}/{col}")
    if role_counts!={"PRIMARY":38,"REPECHAGE_ZONE":35,"REPECHAGE_CROSS_ZONE_GATE":14}:
        errors.append(f"38/35/14 route evidence groups changed: {role_counts}")

    by_key={(r["season"],r["district_code"]):r for r in actual_groups}
    summary_by_key={(r["season"],r["district_code"]):r for r in summaries}
    zone_by_key={(r["season"],r["district_code"]):r for r in zone_groups}
    stage_by_key={(r["season"],r["district_code"]):r for r in stage_groups}
    if (len(by_key)!=8 or len(actual_groups)!=8 or len(summary_by_key)!=8
        or len(summaries)!=8 or len(zone_by_key)!=8 or len(zone_groups)!=8
        or len(stage_by_key)!=8 or len(stage_groups)!=8):
        errors.append("exactly eight distinct seasonal group reviews and upstream contracts required")
    totals=Counter()
    for i,key in enumerate(_GROUP_ORDER):
        record=by_key.get(key)
        stage=stage_by_key.get(key)
        source=summary_by_key.get(key)
        zone=zone_by_key.get(key)
        if any(x is None for x in (record,stage,source,zone)):
            errors.append(f"season district incomplete: {key}")
            continue
        traced=[x for x in calculated if (x["season"],x["district_code"])==key]
        retried=[x for x in retry if (x["season"],x["district_code"])==key]
        routes=[x for x in actual_route if (x["season"],x["district_code"])==key]
        fields={
            "review_id":"HGR2026"+str(i+1).zfill(3),
            "season":key[0],"district_code":key[1],
            "stage_group_id":zone["stage_group_id"],
            "primary_zone_count":zone["primary_zone_count"],
            "primary_loser_to_repechage_observed":str(len(traced)),
            "both_block_labels_known":str(sum(x["block_display_both_known"]=="yes" for x in traced)),
            "published_secondary_zone_event_count":zone["secondary_child_event_count"],
            "published_cross_decider_event_count":zone["cross_zone_decider_child_event_count"],
            "observed_second_chance_participants":str(len(retried)),
            "route_rows":str(len(routes)),
            "qualifier_award_slots":zone["qualifier_award_quota"],
            "direct_main_exempt_slots":zone["direct_main_exempt_slots"],
            "first_place_award_slots":zone["primary_award_quota"],
            "other_award_slots":zone["nonprimary_award_quota"],
            "annual_entrant_zone_assignment_proven":"no",
            "loser_round_selector_proven":"no",
            "secondary_to_cross_candidate_selector_proven":"no",
            "conditional_retry_selector_proven":"no",
            "all_pairings_proven":"no",
            "exact_fmt025_route_release_approved":"no",
            "reason":"2026_results_and_publisher_event_labels_not_general_draw_or_official_pdf",
            "source_status":"official_federation_bracket_pdf_eight_bodies_not_read",
        }
        for col,value in fields.items():
            if record.get(col)!=value:
                errors.append(f"season district route release mismatch: {key}/{col}")
        if (str(len(traced))!=source["primary_loser_to_repechage"]
            or zone["qualifier_award_quota"]!=stage["required_qualifier_awards"]
            or zone["stage_group_id"]!=stage["stage_group_id"]
            or str(len(retried))!=source["repechage_loser_continuation"]):
            errors.append(f"Stage18-20 source counts drifted: {key}")
        for col in ("qualifier_award_quota","primary_award_quota","nonprimary_award_quota"):
            totals[col]+=int(zone[col])
        totals["direct_main_exempt_slots"]+=int(zone["direct_main_exempt_slots"])
        totals["cross_decider_events"]+=int(zone["cross_zone_decider_child_event_count"])
    if totals!={"qualifier_award_quota":63,"primary_award_quota":38,
               "nonprimary_award_quota":25,"direct_main_exempt_slots":1,
               "cross_decider_events":14}:
        errors.append(f"season group qualification conservation changed: {totals}")
    return {
        "ok":not errors,"errors":errors,
        "secondary_dated_fixture_progressions":len(originals),
        "primary_loser_observed_forwardings":len(calculated),
        "both_block_labels_available":both,
        "same_display_block_label":same,
        "seasonal_release_reviews":len(actual_groups),
        "route_evidence_checklists":len(actual_route),
        "route_role_counts":dict(role_counts),
        "historical_publisher_dest_annotated_edges":sum(target_counts.values()),
        "slot_conservation":dict(totals),
        "verified_official_loser_forwarding_rules":0,
        "verified_official_runnerup_to_cross_gate_rules":0,
        "verified_official_retry_rules":0,
        "official_pdf_bodies_inspected":0,
        "fmt025_live_route_release_allowed":False,
        "ranking_only_game_release_allowed":False,
        "scope":"2026_secondary_result_history_not_verifiable_annual_route_policy",
    }
