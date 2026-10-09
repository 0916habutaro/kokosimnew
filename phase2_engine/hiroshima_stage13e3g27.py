"""Stage13E-3G-27: federation visual-preview coverage of all 8 2026 groups.

Seven newly visible 2026 official Drive image previews plus the autumn-west
Stage24 image establish seasonal macro-zone/berth-count visual evidence.
Separate publisher event counts and secondary dated results must NEVER be
upgraded into individually authenticated official draw edges or a future-year
FMT025 loser/retry selector.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g23 import ACCESS_FILE, SOURCE_FILE, OFFICIAL_PAGE
from .hiroshima_stage13e3g24 import PREVIEW_FILE, audit_2026_hiroshima_stage13e3g24
from .hiroshima_stage13e3g26 import audit_2026_hiroshima_stage13e3g26
from .hiroshima_stage13e3g20 import ZONE_CONTRACT_FILE
from .hiroshima_stage13e3g21 import GROUP_REVIEW_FILE

OTHER_SEVEN_FILE = "competitions/2026/hiroshima_other_seven_official_image_macro_2026.csv"
EIGHT_COMPARISON_FILE = "competitions/2026/hiroshima_eight_district_official_macro_comparison_2026.csv"
ORDER = (
    ("spring", "west"), ("spring", "north"),
    ("spring", "south"), ("spring", "east"),
    ("autumn", "west"), ("autumn", "north"),
    ("autumn", "south"), ("autumn", "east"),
)
SEVEN_KEYS = tuple(k for k in ORDER if k != ("autumn", "west"))
OTHER_SCOPE = "official_drive_image_macro_plus_separate_results_and_publisher_counts"
COMPARISON_SCOPE = "official_2026_macro_zones_and_award_totals_only"


def audit_2026_hiroshima_stage13e3g27(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    other = _read(root, OTHER_SEVEN_FILE)
    comparison = _read(root, EIGHT_COMPARISON_FILE)
    zoned = _read(root, ZONE_CONTRACT_FILE)
    reviews = _read(root, GROUP_REVIEW_FILE)
    links = _read(root, SOURCE_FILE)
    prior_snapshot = _read(root, ACCESS_FILE)
    autumn_west = _read(root, PREVIEW_FILE)
    errors: list[str] = []

    by_key = lambda rows: {(r["season"], r["district_code"]): r for r in rows}
    visual = by_key(other)
    compare = by_key(comparison)
    zone_map = by_key(zoned)
    review_map = by_key(reviews)
    link_map = by_key(links)
    snapshot_map = by_key(prior_snapshot)
    if (len(other) != 7 or len(visual) != 7 or set(visual) != set(SEVEN_KEYS)):
        errors.append("seven new official 2026 image-preview groups required")
    if (len(comparison) != 8 or len(compare) != 8 or set(compare) != set(ORDER)):
        errors.append("eight seasonal macro comparison rows required")
    for name, items, expected in (
        ("zone rules", zoned, zone_map),
        ("release reviews", reviews, review_map),
        ("official links", links, link_map),
        ("Stage23 immutable snapshot", prior_snapshot, snapshot_map),
    ):
        if len(items) != 8 or len(expected) != 8 or set(expected) != set(ORDER):
            errors.append(f"eight distinct {name} required")
    if (len(autumn_west) != 1 or autumn_west[0]["official_image_render_access"] != "yes"
            or autumn_west[0]["source_pdf_bytes_downloaded"] != "no"
            or autumn_west[0]["all_pairings_and_loser_arrows_reviewed"] != "no"):
        errors.append("Stage24 official autumn-west preview must remain limited to macro")

    totals = Counter()
    role_counts = Counter()
    for idx, key in enumerate(ORDER, 1):
        season, district = key
        g = zone_map.get(key)
        rv = review_map.get(key)
        ref = link_map.get(key)
        frozen = snapshot_map.get(key)
        macro = compare.get(key)
        if any(x is None for x in (g, rv, ref, frozen, macro)):
            errors.append(f"missing upstream macro or source record: {key}")
            continue
        expected_stage = "SGR" + str(139 + idx).zfill(6)
        if (g["stage_group_id"] != expected_stage
                or rv["stage_group_id"] != expected_stage
                or ref["stage_group_id"] != expected_stage
                or frozen["stage_group_id"] != expected_stage
                or g["format_model_id"] != "FMT025"):
            errors.append(f"staging identity or format changed: {key}")
        if (frozen["preview_outcome"] != "drive_html_loading_only"
                or frozen["independent_pdf_content_review"] != "no"
                or frozen["pdf_body_bytes_obtained"] != "no"
                or frozen["verified_pairing_edge_count"] != "0"):
            errors.append(f"Stage23 earlier access snapshot overwritten: {key}")
        if (rv["exact_fmt025_route_release_approved"] != "no"
                or rv["all_pairings_proven"] != "no"
                or g["allow_live_runtime_integration"] != "no"
                or g["allow_optional_ranking"] != "no"
                or g["primary_loser_forward_rule_verified"] != "no"
                or g["secondary_candidate_forward_rule_verified"] != "no"):
            errors.append(f"year-specific image does not authorize live routing: {key}")
        awards = int(g["qualifier_award_quota"])
        bypass = int(g["direct_main_exempt_slots"])
        first = int(g["primary_award_quota"])
        other_awards = int(g["nonprimary_award_quota"])
        if awards != first + other_awards:
            errors.append(f"qualification quota is not conserved: {key}")
        totals[season] += awards + bypass
        role_counts["primary"] += int(g["primary_child_event_count"])
        role_counts["second_place"] += int(g["secondary_child_event_count"])
        role_counts["cross"] += int(g["cross_zone_decider_child_event_count"])

        wanted = {
            "comparison_id": f"HMC2026{idx:03d}",
            "reference_year": "2026", "season": season, "district_code": district,
            "stage_group_id": expected_stage,
            "zone_count": g["primary_zone_count"],
            "zone_codes": g["primary_zone_codes"],
            "seasonal_group_berth_total": str(awards + bypass),
            "qualifier_berths": str(awards),
            "direct_main_exemption_berths": str(bypass),
            "first_place_berths": str(first),
            "other_qualifier_berths": str(other_awards),
            "publisher_second_place_event_count": g["secondary_child_event_count"],
            "publisher_cross_event_count": g["cross_zone_decider_child_event_count"],
            "observed_conditional_retry_participants": rv["observed_second_chance_participants"],
            "official_2026_image_preview_available": "yes",
            "official_preview_scope": COMPARISON_SCOPE,
            "official_complete_draw_edges_transcribed": "no",
            "annual_official_loser_selector_proven": "no",
            "annual_independent_generic_policy_proven": "no",
            "existing_fmt025_runtime_changed": "no",
            "optional_ranking_allowed": "no",
            "format_risk_class": g["primary_zone_count"] + "_zone_district_year_sensitive_routing",
        }
        for name, value in wanted.items():
            if macro.get(name) != value:
                errors.append(f"seasonal official macro misattributed: {key}/{name}")

        if key == ("autumn", "west"):
            continue
        newly_seen = visual.get(key)
        if newly_seen is None:
            errors.append(f"no new official image proof: {key}")
            continue
        proof = {
            "evidence_id": f"HIP2026{(SEVEN_KEYS.index(key) + 1):03d}",
            "document_year": "2026", "season": season, "district_code": district,
            "competition_id": ref["competition_id"],
            "stage_group_id": expected_stage,
            "official_file_title": frozen["official_file_title"],
            "official_pdf_url": ref["official_pdf_url"],
            "official_federation_listing_url": OFFICIAL_PAGE,
            "inspection_date": "2026-10-09",
            "preview_opened_via_drive_image_anchor": "yes",
            "preview_visual_year_and_district_checked": "yes",
            "visible_primary_zone_count": g["primary_zone_count"],
            "visible_primary_zone_codes": g["primary_zone_codes"],
            "qualifier_awards_correlated_with_results": g["qualifier_award_quota"],
            "direct_main_exempt_slots_from_year_rules": g["direct_main_exempt_slots"],
            "published_secondary_child_events": g["secondary_child_event_count"],
            "published_cross_child_events": g["cross_zone_decider_child_event_count"],
            "official_raw_pdf_bytes_downloaded": "no",
            "all_individual_pairing_arrows_verified": "no",
            "all_official_match_numbers_verified": "no",
            "annual_loser_round_selector_verified": "no",
            "annual_runnerup_to_gate_selector_verified": "no",
            "future_year_general_rule_verified": "no",
            "fmt025_live_runtime_enabled": "no",
            "optional_ranking_unlocked": "no",
            "source_scope": OTHER_SCOPE,
        }
        for name, value in proof.items():
            if newly_seen.get(name) != value:
                errors.append(f"official 2026 preview claim unsupported: {key}/{name}")

    if totals != {"spring": 32, "autumn": 32}:
        errors.append(f"2026 spring/autumn quota including direct exempt must total 32 each: {totals}")
    if role_counts != {"primary": 38, "second_place": 35, "cross": 14}:
        errors.append(f"38/35/14 publisher role census changed: {role_counts}")
    for title, audit in (
        ("Stage24", audit_2026_hiroshima_stage13e3g24),
        ("Stage26", audit_2026_hiroshima_stage13e3g26),
    ):
        baseline = audit(root)
        if not baseline["ok"]:
            errors.append(f"{title} historical west macro regression: {baseline['errors'][:2]}")
    return {
        "ok": not errors,
        "errors": errors,
        "official_2026_new_visual_previews": len(visual),
        "official_2026_seasonal_group_previews_total": len(visual) + len(autumn_west),
        "group_macro_counts": {f"{r['season']}/{r['district_code']}": int(r["zone_count"])
                               for r in comparison},
        "spring_total_berths": totals["spring"],
        "autumn_total_berths": totals["autumn"],
        "spring_exempt_berths": sum(int(r["direct_main_exemption_berths"])
                                     for r in comparison if r["season"] == "spring"),
        "publisher_role_counts": dict(role_counts),
        "official_2026_all_draw_arrows_verified": False,
        "source_pdf_bytes_acquired": 0,
        "official_year_independent_fmt025_policy_verified": False,
        "active_fmt025_runtime_changed": False,
        "optional_ranking_unlocked": False,
    }
