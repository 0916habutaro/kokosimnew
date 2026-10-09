"""Stage13E-3G-30: scope-bound 2026 Hiroshima written-rule evidence audit.

Only statements actually present in the 2026 federation tournament webpage
are official written claims. A reference to the Hiroshima federation's
separate game regulations does not mean the referenced document was read.
Prefectural MAIN mercy/tiebreak rules cannot be silently promoted into
qualification draw/repechage rules. Reporting and a visual tournament macro
are different source grades. None proves 2026 match-numbered transfer arrows
or a general FMT025 selector for later years.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g20 import ZONE_CONTRACT_FILE
from .hiroshima_stage13e3g27 import EIGHT_COMPARISON_FILE, audit_2026_hiroshima_stage13e3g27
from .hiroshima_stage13e3g29 import audit_2026_hiroshima_stage13e3g29

WRITTEN_RULES_FILE = "research/2026/hiroshima_2026_written_rule_evidence_stage13e3g30.csv"
UNRESOLVED_ROUTE_RULES_FILE = "research/2026/hiroshima_2026_unresolved_route_rules_stage13e3g30.csv"
FEDERATION = "https://hiroshima.hhbf1950.or.jp/大会関連/硬式部各種大会"
REPORT = "https://www.hb-nippon.com/articles/16401"
RESULT_REPORT = "https://www.hb-nippon.com/articles/16781"
OFFICIAL_VISUAL = "https://drive.google.com/file/d/1VxVW_r_L5MwnP3hkqZToGe3o5StK5NQ-/view?usp=sharing"

# key -> season, district, scope, normalized_value, source_grade, pinpoint, source_url
WRITTEN_EVIDENCE = (
    ("autumn_MAIN_slots", "autumn", "all", "prefectural_MAIN_berths", "32",
     "federation_page_explicit", "秋季県大会 大会要項 出場チーム数", FEDERATION),
    ("autumn_west_quota", "autumn", "west", "district_qualifier_berths", "7",
     "federation_page_explicit", "秋季県大会 大会要項 西部7", FEDERATION),
    ("autumn_north_quota", "autumn", "north", "district_qualifier_berths", "6",
     "federation_page_explicit", "秋季県大会 大会要項 北部6", FEDERATION),
    ("autumn_south_quota", "autumn", "south", "district_qualifier_berths", "10",
     "federation_page_explicit", "秋季県大会 大会要項 南部10", FEDERATION),
    ("autumn_east_quota", "autumn", "east", "district_qualifier_berths", "9",
     "federation_page_explicit", "秋季県大会 大会要項 東部9", FEDERATION),
    ("autumn_qualifier_start", "autumn", "all", "district_qualifier_calendar",
     "2026-08-22", "federation_page_explicit", "秋季 地区予選大会 日程 開始", FEDERATION),
    ("autumn_qualifier_end", "autumn", "all", "district_qualifier_calendar",
     "2026-09-06", "federation_page_explicit", "秋季 地区予選大会 日程 終了", FEDERATION),
    ("autumn_qualifier_reserve_dates", "autumn", "all", "district_qualifier_calendar",
     "2026-09-12;2026-09-13", "federation_page_explicit", "秋季 地区予選大会 予備日", FEDERATION),
    ("autumn_MAIN_format", "autumn", "all", "prefectural_MAIN_rules",
     "single_elimination", "federation_page_explicit", "秋季県大会 大会要項 試合方法", FEDERATION),
    ("autumn_MAIN_mercy", "autumn", "all", "prefectural_MAIN_rules",
     "after5_10_runs;after7_7_runs;final_exempt", "federation_page_explicit",
     "秋季県大会 大会要項 コールドゲーム", FEDERATION),
    ("autumn_MAIN_tiebreak", "autumn", "all", "prefectural_MAIN_rules",
     "extra_inning_10_onward", "federation_page_explicit",
     "秋季県大会 大会要項 タイブレーク", FEDERATION),
    ("autumn_MAIN_continued_and_DH", "autumn", "all", "prefectural_MAIN_rules",
     "continued_game_and_DH", "federation_page_explicit",
     "秋季県大会 大会要項 継続試合 DH", FEDERATION),
    ("autumn_external_rule_references", "autumn", "all", "reference_only",
     "official_baseball_amateur_special_local_rules",
     "federation_page_reference_only", "秋季県大会 大会要項 試合規則 別規定参照", FEDERATION),
    ("spring_MAIN_slots", "spring", "all", "prefectural_MAIN_berths", "32",
     "federation_page_explicit", "春季県大会 大会要項 出場校数", FEDERATION),
    ("spring_qualifier_start", "spring", "all", "district_qualifier_calendar",
     "2026-03-21", "federation_page_explicit", "春季 地区予選大会 日程 開始", FEDERATION),
    ("spring_qualifier_end", "spring", "all", "district_qualifier_calendar",
     "2026-04-05", "federation_page_explicit",
     "春季 地区予選大会 日程 終了 予備日別記", FEDERATION),
    ("spring_qualifier_reserve_dates", "spring", "all", "district_qualifier_calendar",
     "2026-04-11;2026-04-12", "federation_page_explicit",
     "春季 地区予選大会 予備日", FEDERATION),
    ("autumn_west_report_entrant_18", "autumn", "west", "qualifier_macro_report_only",
     "18", "contemporary_independent_report", "2026-08-16 報道 西部18チーム", REPORT),
    ("autumn_west_report_zones_4", "autumn", "west", "qualifier_macro_report_only",
     "4", "contemporary_independent_report", "2026-08-16 報道 西部4ブロック", REPORT),
    ("autumn_west_report_first_winners", "autumn", "west", "qualifier_macro_report_only",
     "4", "contemporary_independent_report", "2026-08-16 報道 ブロック1位4", REPORT),
    ("autumn_west_report_repechage", "autumn", "west", "qualifier_macro_report_only",
     "3", "contemporary_independent_report", "2026-08-16 報道 敗者戦3", REPORT),
    ("autumn_west_repechage_actual_advancers", "autumn", "west",
     "qualifier_observed_results_only", "広島井口;基町;広島工大",
     "contemporary_independent_report", "2026-08-30 報道 敗者復活の3校", RESULT_REPORT),
    ("autumn_west_2026_macro_C_D_cross", "autumn", "west",
     "qualifier_image_macro_only", "A_B_second_direct_C_D_cross",
     "federation_image_visual_macro_only", "2026秋西 公式画像 A Bの二位校直通 C Dの決定戦", OFFICIAL_VISUAL),
)
RULE_REQUIREMENTS = (
    ("official_entrant_to_primary_zone_draw", "initial_school_draw",
     "must_read_the_official_annual_entrant_position_or_drawing_rule"),
    ("official_primary_bracket_pairing_edges", "primary_pairing",
     "must_read_individual_official_match_pairing_arrows"),
    ("official_primary_loser_to_repechage", "primary_loser_transfer",
     "must_read_loser_round_to_secondary_entry_rule"),
    ("official_repechage_bracket_pairings", "secondary_pairing",
     "must_read_secondary_match_pairing_edges"),
    ("official_secondary_winner_to_qualifying_gate", "runnerup_gate",
     "must_read_berth_or_cross_gate_candidate_selector"),
    ("official_conditional_retry_applicability_and_transfer", "conditional_retry",
     "must_confirm_whether_retry_exists_and_if_so_its_explicit_graph"),
)
GROUPS = (
    ("spring", "west", "SGR000140"), ("spring", "north", "SGR000141"),
    ("spring", "south", "SGR000142"), ("spring", "east", "SGR000143"),
    ("autumn", "west", "SGR000144"), ("autumn", "north", "SGR000145"),
    ("autumn", "south", "SGR000146"), ("autumn", "east", "SGR000147"),
)


@dataclass(frozen=True)
class WrittenRuleScopeDecision:
    can_use_as_year_limited_quota: bool = False
    can_use_as_year_limited_calendar: bool = False
    can_use_as_main_only_rules: bool = False
    can_determine_qualifier_bracket: bool = False
    can_select_primary_loser_destination: bool = False
    can_enable_fmt025_runtime: bool = False
    can_claim_year_independent_policy: bool = False
    may_unlock_optional_ranking: bool = False


def evaluate_written_rule_scope(record: dict) -> WrittenRuleScopeDecision:
    """Scope-locked use of an independently sourced statement.

    Caller-provided source strings alone cannot authorize live routing.
    Accepted *information categories* may support research/2026 calendar,
    quota or MAIN rules, never qualifier fixtures or a future year's draw.
    """
    required = {"claim_key", "evidence_grade", "applicability_scope",
                "source_url", "document_year", "season", "district_code",
                "normalized_claim_value", "source_body_reviewed",
                "document_pinpoint", "official_source_for_claim",
                "independently_verified_full_official_draw",
                "annual_loser_selector_proven",
                "runtime_use_as_2026_fmt025_selector",
                "year_independent_policy_approved"}
    if not required <= record.keys():
        raise ValueError("missing provenance fields for written source claim")
    expected = next((e for e in WRITTEN_EVIDENCE if e[0] == record["claim_key"]), None)
    if expected is None:
        raise ValueError("unrecognized claim cannot acquire normative status")
    _, season, district, scope, value, grade, pinpoint, url = expected
    if (record["document_year"] != "2026"
            or record["season"] != season
            or record["district_code"] != district
            or record["applicability_scope"] != scope
            or record["normalized_claim_value"] != value
            or record["evidence_grade"] != grade
            or record["source_url"] != url
            or record["document_pinpoint"] != pinpoint
            or record["official_source_for_claim"] != (
                "yes" if grade.startswith("federation_") else "no"
            )
            or record["source_body_reviewed"] != (
                "image_macro_only" if grade == "federation_image_visual_macro_only" else "yes"
            )
            or record["independently_verified_full_official_draw"] != "no"
            or record["annual_loser_selector_proven"] != "no"
            or record["runtime_use_as_2026_fmt025_selector"] != "no"
            or record["year_independent_policy_approved"] != "no"):
        raise ValueError("source scope or evidence level is inconsistent")
    if grade != "federation_page_explicit":
        return WrittenRuleScopeDecision()
    return WrittenRuleScopeDecision(
        can_use_as_year_limited_quota=scope in (
            "prefectural_MAIN_berths", "district_qualifier_berths"
        ),
        can_use_as_year_limited_calendar=scope == "district_qualifier_calendar",
        can_use_as_main_only_rules=scope == "prefectural_MAIN_rules",
    )


def audit_2026_hiroshima_stage13e3g30(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    written = _read(root, WRITTEN_RULES_FILE)
    pending = _read(root, UNRESOLVED_ROUTE_RULES_FILE)
    zones = _read(root, ZONE_CONTRACT_FILE)
    compare = _read(root, EIGHT_COMPARISON_FILE)
    errors: list[str] = []
    prev27 = audit_2026_hiroshima_stage13e3g27(root)
    prev29 = audit_2026_hiroshima_stage13e3g29(root)
    if not prev27["ok"]:
        errors.append("Stage27 eight-group official macro regression failed")
    if not prev29["ok"]:
        errors.append("Stage29 original-PDF not-acquired regression failed")

    if (len(written) != 23
            or len(set(x["evidence_id"] for x in written)) != 23
            or len(set(x["claim_key"] for x in written)) != 23):
        errors.append("23 distinct written/report/visual claims must remain")
    source_grades = Counter()
    authority = Counter()
    for index, expected in enumerate(WRITTEN_EVIDENCE, 1):
        if index > len(written):
            break
        key, season, district, scope, value, grade, pin, url = expected
        row = written[index - 1]
        fields = {
            "evidence_id": f"HWR2026{index:03d}",
            "claim_key": key,
            "document_year": "2026",
            "season": season,
            "district_code": district,
            "applicability_scope": scope,
            "normalized_claim_value": value,
            "evidence_grade": grade,
            "document_pinpoint": pin,
            "source_url": url,
            "source_body_reviewed": (
                "image_macro_only" if grade == "federation_image_visual_macro_only" else "yes"
            ),
            "official_source_for_claim": "yes" if grade.startswith("federation_") else "no",
            "independently_verified_full_official_draw": "no",
            "annual_loser_selector_proven": "no",
            "runtime_use_as_2026_fmt025_selector": "no",
            "year_independent_policy_approved": "no",
        }
        for field, wanted in fields.items():
            if row.get(field) != wanted:
                errors.append(f"written-source evidence scope violation: {key}/{field}")
        try:
            decision = evaluate_written_rule_scope(row)
            if (decision.can_determine_qualifier_bracket
                    or decision.can_select_primary_loser_destination
                    or decision.can_enable_fmt025_runtime
                    or decision.can_claim_year_independent_policy
                    or decision.may_unlock_optional_ranking):
                errors.append(f"unjustified qualifier promotion: {key}")
            authority["quota"] += int(decision.can_use_as_year_limited_quota)
            authority["calendar"] += int(decision.can_use_as_year_limited_calendar)
            authority["MAIN_rules_only"] += int(decision.can_use_as_main_only_rules)
        except ValueError:
            errors.append(f"written claim evaluator rejected record: {key}")
        source_grades[grade] += 1

    if source_grades != {
        "federation_page_explicit": 16,
        "federation_page_reference_only": 1,
        "contemporary_independent_report": 5,
        "federation_image_visual_macro_only": 1,
    }:
        errors.append(f"provenance categories changed: {source_grades}")
    if authority != {"quota": 6, "calendar": 6, "MAIN_rules_only": 4}:
        errors.append(f"year-limited authority counters changed: {authority}")

    zone_map = {(x["season"], x["district_code"]): x for x in zones}
    compare_map = {(x["season"], x["district_code"]): x for x in compare}
    if (len(zone_map) != 8 or len(compare_map) != 8
            or any((season, district) not in zone_map or
                   (season, district) not in compare_map
                   for season, district, _ in GROUPS)):
        errors.append("eight seasonal groups needed for official quota comparison")
    for district, claim in (
        ("west", "autumn_west_quota"),
        ("north", "autumn_north_quota"),
        ("south", "autumn_south_quota"),
        ("east", "autumn_east_quota"),
    ):
        row = next((x for x in written if x["claim_key"] == claim), None)
        g = zone_map.get(("autumn", district))
        c = compare_map.get(("autumn", district))
        if (not row or not g or not c
                or row["normalized_claim_value"] != g["qualifier_award_quota"]
                or row["normalized_claim_value"] != c["qualifier_berths"]):
            errors.append(f"official autumn quota does not match season ledger: {district}")
    if len(pending) != 48 or len({x["requirement_id"] for x in pending}) != 48:
        errors.append("8 season-district groups x 6 unresolved route proof needs required")
    seen_keys: set[tuple[str, str, str]] = set()
    for group_no, (season, district, stage) in enumerate(GROUPS):
        for rule_no, (key, category, evidence_type) in enumerate(RULE_REQUIREMENTS):
            index = group_no * len(RULE_REQUIREMENTS) + rule_no
            if index >= len(pending):
                continue
            record = pending[index]
            identity = (record["season"], record["district_code"], record["requested_rule_key"])
            if identity in seen_keys:
                errors.append(f"duplicate unresolved rule: {identity}")
            seen_keys.add(identity)
            fields = {
                "requirement_id": f"HRP2026{index + 1:03d}",
                "document_year": "2026", "season": season,
                "district_code": district, "stage_group_id": stage,
                "requested_rule_key": key, "rule_category": category,
                "evidence_type_needed": evidence_type,
                "official_public_page_checked": FEDERATION,
                "public_page_check_result": "not_spelled_out_in_reviewed_page_text",
                "official_individual_document_rule_located": "no",
                "verified_source_pinpoint": "",
                "explicit_2026_formula_available": "no",
                "eligible_for_repeatable_years": "no",
                "fmt025_runtime_authorized": "no",
                "optional_ranking_authorized": "no",
            }
            for field, value in fields.items():
                if record.get(field) != value:
                    errors.append(f"unverified route evidence promoted: {season}/{district}/{key}/{field}")
    return {
        "ok": not errors,
        "errors": errors,
        "written_source_claims": len(written),
        "evidence_grades": dict(source_grades),
        "authority_scoped_claims": dict(authority),
        "year_limited_official_autumn_berths": sum(
            int(r["normalized_claim_value"]) for r in written
            if r["claim_key"] in (
                "autumn_west_quota", "autumn_north_quota",
                "autumn_south_quota", "autumn_east_quota"
            )
        ),
        "unresolved_district_rule_proof_items": len(pending),
        "2026_match_numbered_draw_rules_proven": 0,
        "verified_primary_loser_round_selectors": 0,
        "year_independent_fmt025_policy_approved": False,
        "live_fmt025_runtime_changed": False,
        "optional_ranking_unlocked": False,
    }
