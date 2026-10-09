"""Stage 13E-3G-24: 2026 Hiroshima autumn west official visual preview audit.

The official federation link's Google Drive image preview became readable on
2026-10-09. It provides the 2026 zone and berth-gate macrograph. The original
PDF bytes and a manually checked complete 25-fixture arrow transcription are
not available. This module cannot certify source authenticity by itself and
must never unlock the live FMT025 runner.
"""
from __future__ import annotations

from pathlib import Path
from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g22 import (
    PUBLISHER_GROUPS_FILE, PRIOR_YEAR_PDF_FILE, audit_2026_hiroshima_stage13e3g22,
)
from .hiroshima_stage13e3g21 import GROUP_REVIEW_FILE
from .hiroshima_stage13e3g23 import ACCESS_FILE
from .hiroshima_qualification_timeline_2026 import TIMELINE_FILE

PREVIEW_FILE = "research/2026/hiroshima_autumn_west_official_image_evidence_2026.csv"
GRAPH_FILE = "competitions/2026/hiroshima_autumn_west_official_visual_phase_graph_2026.csv"
OFFICIAL_SOURCE = "https://drive.google.com/file/d/1VxVW_r_L5MwnP3hkqZToGe3o5StK5NQ-/view?usp=sharing"
OFFICIAL_LISTING = "https://hiroshima.hhbf1950.or.jp/大会関連/硬式部各種大会"

# Only zone-level and cross-gate relationships can be claimed from the
# legible image; no individual match-number arrows are asserted here.
EXPECTED_GRAPH = (
    ("A", "PRIMARY", "広島商", "MAIN", "yes"),
    ("A", "REPECHAGE_ZONE", "広島井口", "MAIN", "yes"),
    ("B", "PRIMARY", "山陽", "MAIN", "yes"),
    ("B", "REPECHAGE_ZONE", "基町", "MAIN", "yes"),
    ("C", "PRIMARY", "広島国泰寺", "MAIN", "yes"),
    ("C", "REPECHAGE_ZONE", "広島工大", "C_D_CROSS", "no"),
    ("D", "PRIMARY", "崇徳", "MAIN", "yes"),
    ("D", "REPECHAGE_ZONE", "広島城北", "C_D_CROSS", "no"),
    ("C;D", "REPECHAGE_CROSS_ZONE_GATE", "広島工大", "MAIN", "yes"),
)
EXPECTED_PREVIEW = {
    "evidence_id": "HIV2026001",
    "document_year": "2026",
    "season": "autumn", "district_code": "west",
    "stage_group_id": "SGR000144",
    "source_official_listing_url": OFFICIAL_LISTING,
    "source_official_pdf_url": OFFICIAL_SOURCE,
    "official_document_title": "R8秋季地区トーナメント表(西部).pdf",
    "inspection_date": "2026-10-09",
    "official_image_render_access": "yes",
    "preview_pages_visually_inspected": "1",
    "observed_initial_participants": "18",
    "observed_primary_zones": "4",
    "observed_five_team_zones": "2",
    "observed_four_team_zones": "2",
    "observed_main_berths": "7",
    "observed_a_b_second_place_direct_berths": "2",
    "observed_cd_cross_zone_berths": "1",
    "observed_event_phase_nodes": "9",
    "source_pdf_bytes_downloaded": "no",
    "source_pdf_sha256": "",
    "all_official_match_numbers_transcribed": "no",
    "all_pairings_and_loser_arrows_reviewed": "no",
    "annual_generic_loser_rule_proven": "no",
    "fmt025_runtime_enabled": "no",
    "source_scope": "federation_pdf_visual_render_macro_graph_not_raw_pdf_or_complete_edges",
}
GRAPH_SOURCE_MEDIA = "federation_google_drive_pdf_visual_render"
GRAPH_SCOPE = "zone_and_gate_level_only"


def audit_2026_hiroshima_stage13e3g24(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    original = _read(root, PUBLISHER_GROUPS_FILE)
    graph = _read(root, GRAPH_FILE)
    preview = _read(root, PREVIEW_FILE)
    games = _read(root, TIMELINE_FILE)
    stages = _read(root, GROUP_REVIEW_FILE)
    previous = _read(root, PRIOR_YEAR_PDF_FILE)
    stage23_snapshot = _read(root, ACCESS_FILE)
    errors: list[str] = []

    if len(preview) != 1:
        errors.append("one 2026 official visual preview record required")
    else:
        for field, value in EXPECTED_PREVIEW.items():
            if preview[0].get(field) != value:
                errors.append(f"unverified official image claim or metadata changed: {field}")

    if len(graph) != 9 or len(original) != 9:
        errors.append("nine autumn west phase nodes and original events required")

    by_event = {r["event_audit_id"]: r for r in original}
    seen_events = set()
    winners = {}
    first_zone_teams = set()
    phase_counts = {"PRIMARY": 0, "REPECHAGE_ZONE": 0, "REPECHAGE_CROSS_ZONE_GATE": 0}
    berth_names = set()
    history = {r["match_id"]: r for r in games
               if (r["season"], r["district_code"]) == ("autumn", "west")}
    if len(history) != 25:
        errors.append("25 recorded 2026 autumn west games required")

    for idx, expected in enumerate(EXPECTED_GRAPH):
        if idx >= len(graph):
            break
        record = graph[idx]
        zone, role, expected_winner, destination, berth = expected
        source = by_event.get(record["event_audit_id"])
        if record["event_audit_id"] in seen_events:
            errors.append(f"duplicate phase evidence event: {idx}")
        seen_events.add(record["event_audit_id"])
        required = {
            "evidence_id": f"HOV2026{idx+1:03d}",
            "document_year": "2026",
            "season": "autumn", "district_code": "west",
            "competition_id": "CMP000136", "stage_group_id": "SGR000144",
            "event_audit_id": f"HAW2026{idx+1:03d}",
            "zone_scope": zone, "phase_execution_role": role,
            "observed_winner": expected_winner,
            "official_2026_graph_destination": destination,
            "verified_berth_from_this_event": berth,
            "source_official_pdf_url": OFFICIAL_SOURCE,
            "source_media_observed": GRAPH_SOURCE_MEDIA,
            "official_image_structural_scope": GRAPH_SCOPE,
            "pdf_original_bytes_obtained": "no",
            "complete_pairing_edges_transcribed": "no",
            "season_independent_transfer_selector_verified": "no",
            "fmt025_live_route_approved": "no",
        }
        if not source:
            errors.append(f"unknown existing 2026 publisher event: {idx}")
            continue
        required.update({
            "route_id": source["published_route_id"],
            "expected_real_teams": source["real_participant_count"],
            "observed_decider_match_id": source["observed_decider_match_id"],
        })
        for field, value in required.items():
            if record.get(field) != value:
                errors.append(f"official visual phase mismatch {idx+1}/{field}")

        teams = set(source["normalized_real_team_names"].split(";"))
        if expected_winner not in teams:
            errors.append(f"observed winner outside phase participants: {zone}/{role}")
        game = history.get(source["observed_decider_match_id"])
        if not game or game["winner_name"] != expected_winner:
            errors.append(f"phase winner disagrees with dated results: {zone}/{role}")
        elif (game["winner_berth_status"] == "berth_award") != (berth == "yes"):
            errors.append(f"date-result berth attribution changed: {zone}/{role}")

        phase_counts[role] += 1
        if role == "PRIMARY":
            if first_zone_teams.intersection(teams):
                errors.append("zone primary school assigned twice")
            first_zone_teams.update(teams)
        if role == "REPECHAGE_ZONE":
            winners[zone] = expected_winner
        if berth == "yes":
            berth_names.add(expected_winner)

    if len(seen_events) != 9 or phase_counts != {
        "PRIMARY": 4, "REPECHAGE_ZONE": 4, "REPECHAGE_CROSS_ZONE_GATE": 1
    }:
        errors.append("four first-place, four second-place, one C/D gate required")
    if len(first_zone_teams) != 18:
        errors.append("official first-zone 18-entrant census changed")
    if (len(berth_names) != 7
            or sum(r["verified_berth_from_this_event"] == "yes" for r in graph) != 7):
        errors.append("four direct primary and three second-chance berths required")

    cross = original[8] if len(original) >= 9 else None
    if (winners.get("C") != "広島工大" or winners.get("D") != "広島城北"
            or not cross or set(cross["normalized_real_team_names"].split(";"))
            != {winners.get("C"), winners.get("D")}):
        errors.append("2026 C/D second-place winners must contest single final gate")

    west_review = [r for r in stages if
                   (r["season"], r["district_code"]) == ("autumn", "west")]
    if (len(west_review) != 1 or west_review[0]["qualifier_award_slots"] != "7"
            or west_review[0]["exact_fmt025_route_release_approved"] != "no"
            or west_review[0]["all_pairings_proven"] != "no"):
        errors.append("confirmed macrograph must not release full FMT025 runtime")

    if (len(previous) != 1 or previous[0]["prior_year"] != "2025"
            or previous[0]["prior_year_graph_reusable_for_2026"] != "no"
            or previous[0]["official_2025_cross_zone_gate_27"]
            != "winner_A2_vs_winner_B2"):
        errors.append("2025 gate 27 must stay isolated from the 2026 A/B direct paths")

    stage23_west = [r for r in stage23_snapshot if
                    (r["season"], r["district_code"]) == ("autumn", "west")]
    if (len(stage23_snapshot) != 8 or len(stage23_west) != 1
            or stage23_west[0]["preview_outcome"] != "drive_html_loading_only"
            or stage23_west[0]["pdf_body_bytes_obtained"] != "no"):
        errors.append("previous Stage23 dated no-preview snapshot is immutable")
    if not audit_2026_hiroshima_stage13e3g22(root)["ok"]:
        errors.append("Stage22 published-team history audit must still pass")

    return {
        "ok": not errors, "errors": errors,
        "new_2026_federation_image_visual_inspections": len(preview),
        "2026_autumn_west_initial_teams": len(first_zone_teams),
        "2026_autumn_west_official_macro_phase_nodes": len(graph),
        "2026_autumn_west_awarded_main_berths": len(berth_names),
        "2026_graph_direct_a_b_second_place_berths": 2,
        "2026_graph_cd_second_place_final_gate": 1,
        "2026_official_pdf_original_bytes": 0,
        "2026_25_match_number_edges_fully_transcribed": False,
        "2026_reusable_full_fmt025_policy_verified": False,
        "live_fmt025_runtime_changed": False,
    }
