"""Stage13E-3G-17 Hiroshima FMT025 read-only phase compatibility contract.

The 87 SportsOnline child events are route/stage names, not individual
match IDs or a verified 2026 draw DAG. Four groups have an observed
first-place count that differs from the current generic runtime's
ceil(effective_quota/2) split. Only analysis data is produced; do not
silently change runtime or permit optional ranking-only matches.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_berth_roster_2026 import (
    ROSTER_FILE, STAGE_GROUP_FILE, EXPECTED_SLOTS,
)
from .hiroshima_stage13e3g16 import EVENT_FILE, STRUCTURE_FILE
from .hiroshima_qualification_timeline_2026 import TIMELINE_FILE

ROUTE_FILE = "competitions/2026/hiroshima_district_qualification_routes.csv"
CROSSWALK_FILE = "competitions/2026/hiroshima_fmt025_route_phase_crosswalk_2026.csv"
GROUP_CONTRACT_FILE = "competitions/2026/hiroshima_fmt025_group_phase_contract_2026.csv"
FORMAT_PHASE_FILE = "competitions/competition_stage_format_phases.csv"
FORMAT_OVERRIDE_FILE = "competitions/competition_stage_group_format_overrides.csv"
FORMAT_PARAMETER_FILE = "competitions/competition_stage_format_parameters.csv"
RANKING_PHASE = "FPH051"
MAP = {
    "first_place_berth_path": (
        "FPH049", "PRIMARY", "named_zone_eligible_entrants",
        "zone_first_place_to_qualifier_award"
    ),
    "second_place_berth_path": (
        "FPH050", "REPECHAGE_ZONE",
        "prior_primary_losers_according_to_published_draw",
        "requires_secondary_result_or_cross_gate"
    ),
    "cross_zone_berth_decider": (
        "FPH050", "REPECHAGE_CROSS_ZONE_GATE",
        "zone_runnerup_survivors_to_named_decider",
        "requires_secondary_result_or_cross_gate"
    ),
}
EAST_E = ("spring", "east", "E二位校")
CROSS_MATCH_COUNT = 14


def default_primary_slots(effective_output_slots: int) -> int:
    """Read-only mirror of generic FMT025 PRIMARY split; NOT draw-accurate."""
    return max(1, (effective_output_slots + 1) // 2)


def _zone(title: str) -> str:
    if title and title[0] in "ABCDEF":
        parts = title.split("二位校")[0].split("一位校")[0]
        return parts.replace("・", ";")
    if "（" in title and "）" in title:
        return title.split("（",1)[1].split("）",1)[0]
    return "unresolved_from_child_title"


def audit_2026_hiroshima_stage13e3g17(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    routes = _read(root, ROUTE_FILE)
    mapping = _read(root, CROSSWALK_FILE)
    plans = _read(root, GROUP_CONTRACT_FILE)
    published = _read(root, STRUCTURE_FILE)
    linked_events = _read(root, EVENT_FILE)
    roster = _read(root, ROSTER_FILE)
    games = _read(root, TIMELINE_FILE)
    stages = _read(root, STAGE_GROUP_FILE)
    overrides = _read(root, FORMAT_OVERRIDE_FILE)
    phases = _read(root, FORMAT_PHASE_FILE)
    params = _read(root, FORMAT_PARAMETER_FILE)
    errors: list[str] = []
    groups = {(r["season"],r["district_code"]):r for r in published}
    plan_by_key = {(r["season"],r["district_code"]):r for r in plans}
    by_group = {r["stage_group_id"]:r for r in stages}
    by_override = {r["stage_group_id"]:r for r in overrides}
    by_route = {r["route_id"]:r for r in routes}
    by_match = {r["match_id"]:r for r in games}
    by_event_id = {r["check_id"]:r for r in linked_events}
    if len(plans) != 8 or len(plan_by_key) != 8 or set(plan_by_key) != set(EXPECTED_SLOTS):
        errors.append("eight unique FMT025 stage group design contracts required")
    if len(routes) != 87 or len(by_route) != 87 or len(mapping) != 87:
        errors.append("87 unique published routes and 87 crosswalk rows required")
    if len(linked_events) != 15 or len(by_event_id) != 15:
        errors.append("15 unique publisher stage-game crosslinks required")
    fmt_phases = {r["format_phase_id"]:r for r in phases}
    for phase_id, code in (("FPH049","PRIMARY"),("FPH050","REPECHAGE"),("FPH051","RANKING")):
        item = fmt_phases.get(phase_id)
        if item is None or item["format_model_id"] != "FMT025" or item["phase_code"] != code:
            errors.append(f"FMT025 phase specification changed: {phase_id}")

    route_seen = set()
    event_seen = set()
    by_region_kind = Counter()
    by_phase = Counter()
    for r in mapping:
        rid = r["route_id"]
        if rid in route_seen or rid not in by_route:
            errors.append(f"missing or duplicate route in phase crosswalk: {rid}")
            continue
        route_seen.add(rid)
        src = by_route[rid]
        kind = src["route_kind"]
        expected = MAP.get(kind)
        if expected is None:
            errors.append(f"unknown qualification route type {rid}: {kind}")
            continue
        by_region_kind[(src["season"],src["district_code"],kind)] += 1
        by_phase[expected[1]] += 1
        for key in ("season", "district_code","competition_id","stage_group_id"):
            if r[key] != src[key]:
                errors.append(f"route identity mismatch: {rid}/{key}")
        if (
            r["format_model_id"] != "FMT025"
            or r["published_event_name"] != src["sub_tournament_name"]
            or r["route_kind"] != kind
            or r["source_route_start"] != src["first_calendar_day"]
            or r["source_route_end"] != src["last_calendar_day"]
            or r["model_phase_id"] != expected[0]
            or r["phase_execution_role"] != expected[1]
            or r["local_zone_scope"] != _zone(src["sub_tournament_name"])
            or r["participant_selector_contract"] != expected[2]
            or r["winner_award_contract"] != expected[3]
            or r["publisher_event_url"] != src["bracket_source_url"]
        ):
            errors.append(f"route phase/selector/zone contract mismatch: {rid}")
        if (
            r["routing_edge_status"] != "named_event_only_actual_annual_draw_edges_not_inspected"
            or r["official_federation_pdf_verified"] != "no"
            or r["can_materialize_draw_accurate_runtime"] != "no"
        ):
            errors.append(f"unverified draw edge/official PDF release forbidden: {rid}")
        ev_id = r["matched_publisher_event_check_id"]
        match_id = r["matched_qualification_decider_match_id"]
        if bool(ev_id) != bool(match_id):
            errors.append(f"partial evidence link: {rid}")
        if ev_id:
            if ev_id in event_seen:
                errors.append(f"publisher event reused in multiple route rows: {ev_id}")
            event_seen.add(ev_id)
            ev = by_event_id.get(ev_id)
            game = by_match.get(match_id)
            allowed = (
                kind == "cross_zone_berth_decider" and ev is not None
                and ev["stage_role"] == "entry_decider"
            ) or (
                (src["season"],src["district_code"],src["sub_tournament_name"]) == EAST_E
                and ev is not None and ev["stage_role"] == "second_place_zone_award"
            )
            if (not allowed or game is None or ev["matched_match_id"] != match_id
                    or ev["season"] != src["season"]
                    or ev["district_code"] != src["district_code"]
                    or game["winner_berth_status"] != "berth_award"
                    or game["season"] != src["season"]
                    or game["district_code"] != src["district_code"]
                    or r["matched_result_evidence_scope"] != "publisher_event_label_plus_secondary_match"):
                errors.append(f"unsupported publisher result/route binding: {rid}")
        elif r["matched_result_evidence_scope"] != "published_child_event_name_only":
            errors.append(f"unproven route has fabricated match evidence: {rid}")

    if len(route_seen) != 87 or len(event_seen) != 15 or event_seen != set(by_event_id):
        errors.append(f"87 route rows/15 evidence mappings must be complete: {len(route_seen)}/{len(event_seen)}")
    if by_phase != {"PRIMARY":38, "REPECHAGE_ZONE":35, "REPECHAGE_CROSS_ZONE_GATE":14}:
        errors.append(f"published event route-kind split changed: {by_phase}")

    overrides_needed = []
    split_rows = []
    quotas = Counter()
    all_awards = {
        (r["season"],r["district_code"],r["winner_name"])
        for r in games if r["winner_berth_status"] == "berth_award"
    }
    if len(games) != 223 or len(all_awards) != 63:
        errors.append("historical 223 fixture/63 qualification-winner baseline changed")

    for key in EXPECTED_SLOTS:
        s = groups.get(key)
        p = plan_by_key.get(key)
        if p is None or s is None:
            errors.append(f"published group summary or proposed phase contract missing: {key}")
            continue
        gid = s["stage_group_id"]
        stage = by_group.get(gid)
        override = by_override.get(gid)
        if stage is None or override is None:
            errors.append(f"stage group/override missing: {gid}")
            continue
        quota = int(stage["advance_slots_to_next"])
        exempt = sum(r["season"]==key[0] and r["district_code"]==key[1]
                     and r["qualification_basis"]=="selection_tournament_exemption"
                     for r in roster)
        nonexempt = sum(r["season"]==key[0] and r["district_code"]==key[1]
                        and r["qualification_basis"]=="district_result_list"
                        for r in roster)
        effective = quota - exempt
        first = by_region_kind[(*key,"first_place_berth_path")]
        second = by_region_kind[(*key,"second_place_berth_path")]
        cross = by_region_kind[(*key,"cross_zone_berth_decider")]
        historical_awards = sum(x[:2]==key for x in all_awards)
        projected = default_primary_slots(effective)
        group_params = {x["parameter_name"]:x["parameter_value"]
                        for x in params if x["stage_group_id"]==gid}
        if ("rank_order_required" in group_params
                and group_params["rank_order_required"].lower() not in ("false","0","no")):
            errors.append(f"ranking-only event enabled without evidence: {gid}")
        if (group_params.get("output_slots") != str(quota)
                or (exempt and group_params.get("group_quota_includes_direct_access") != "true")
                or (not exempt and "group_quota_includes_direct_access" in group_params)):
            errors.append(f"existing group quota/2026 direct berth params drifted: {gid}")
        if (
            quota != EXPECTED_SLOTS[key] or stage["competition_id"] != s["competition_id"]
            or override["format_model_id"] != "FMT025"
            or override["stage_group_id"] != gid
            or nonexempt != effective or historical_awards != effective
        ):
            errors.append(f"onfield award, exemption, FMT025 or historical quota mismatch: {gid}")
        checked = {
            "season":key[0], "district_code":key[1], "competition_id":s["competition_id"],
            "stage_group_id":gid, "format_model_id":"FMT025",
            "primary_phase_id":"FPH049","repechage_phase_id":"FPH050",
            "ranking_phase_id":RANKING_PHASE,
            "group_quota_total":str(quota),
            "direct_main_exempt_slots":str(exempt),
            "required_qualifier_awards":str(effective),
            "observed_first_place_event_slots":str(first),
            "observed_second_place_event_count":str(second),
            "observed_cross_decider_event_count":str(cross),
            "expected_nonprimary_awards":str(effective-first),
            "runtime_default_primary_slots":str(projected),
            "primary_slots_need_override":"yes" if first!=projected else "no",
            "annual_draw_edges_verified":"no",
            "runtime_current_behavior":"generic_primary_then_repechage_forest",
            "design_readiness":"aggregate_phase_counts_only_draw_edges_pending",
            "ranking_only_release_allowed":"no",
            "source_url":s["source_url"]
        }
        for col, expected in checked.items():
            if p[col] != expected:
                errors.append(f"phase split crosswalk mismatch: {gid} / {col}")
        if (first!=int(s["first_place_child_events"])
            or second!=int(s["second_place_child_events"])
            or cross!=int(s["cross_zone_entry_decider_child_events"])):
            errors.append(f"87 child-event group counts differ from published index: {gid}")
        if effective-first < cross or first > effective:
            errors.append(f"invalid observed primary/nonprimary berth budget: {gid}")
        quotas["all"]=quotas["all"]+quota
        quotas["direct"]=quotas["direct"]+exempt
        quotas["onfield"]=quotas["onfield"]+effective
        quotas["primary"]=quotas["primary"]+first
        quotas["nonprimary"]=quotas["nonprimary"]+effective-first
        if first!=projected:
            overrides_needed.append(gid)
        split_rows.append({"group_id":gid,"first_place":first,
                           "generic_primary":projected,"secondary_slots":effective-first})
    if quotas != {"all":64,"direct":1,"onfield":63,"primary":38,"nonprimary":25}:
        errors.append(f"64/1/63/38/25 quota conservation violated: {quotas}")
    if set(overrides_needed) != {"SGR000140","SGR000142","SGR000145","SGR000146"}:
        errors.append(f"four observed first-phase quota differences changed: {overrides_needed}")

    return {
        "ok":not errors,
        "errors":errors,
        "published_child_route_count":len(routes),
        "fmt025_primary_child_event_count":by_phase["PRIMARY"],
        "fmt025_repechage_zone_child_event_count":by_phase["REPECHAGE_ZONE"],
        "fmt025_cross_zone_entry_gate_count":by_phase["REPECHAGE_CROSS_ZONE_GATE"],
        "publisher_result_events_mapped_to_route":len(event_seen),
        "all_group_quota":quotas["all"],
        "direct_main_exempt_slots":quotas["direct"],
        "nonexempt_qualification_slots":quotas["onfield"],
        "expected_first_place_award_slots":quotas["primary"],
        "remaining_nonprimary_award_slots":quotas["nonprimary"],
        "generic_primary_split_mismatch_groups":sorted(overrides_needed),
        "per_group_phase_split":split_rows,
        "verified_annual_draw_edges":0,
        "exact_path_runtime_ready":False,
        "ranking_only_route_verified":False,
        "fmt025_optional_ranking_release_allowed":False,
        "official_pdf_bodies_inspected":0,
        "historical_fixtures_are_runtime_generated":False,
        "scope":"read_only_publisher_child_routes_to_existing_FMT025_phases",
    }
