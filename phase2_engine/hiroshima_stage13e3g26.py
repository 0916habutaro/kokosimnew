"""Stage13E-3G-26: connect observed 2026 west berth macro to sandbox.

This is read-only research plumbing. It does not schedule FMT025 matches or
declare any official loser transfer policy. Year-independent code accepts
fictional entrant IDs only within tests; no 2026 school IDs get hardwired into
a future real draw.
"""
from __future__ import annotations

from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g24 import GRAPH_FILE, PREVIEW_FILE
from .hiroshima_stage13e3g25 import audit_2026_hiroshima_stage13e3g25
from .hiroshima_variable_qualification_macro import (
    WEST_2026_OBSERVED_MACRO_EXAMPLE,
    draft_qualification_macro,
    validate_macro_template,
)

MACRO_TEMPLATE_FILE = "competitions/2026/hiroshima_macro_template_stage13e3g26.csv"
EXPECTED_RECORD = {
    "template_id": "HMT2026001",
    "reference_year": "2026",
    "reference_season": "autumn",
    "reference_district": "west",
    "source_stage_group_id": "SGR000144",
    "observed_zone_codes": "A;B;C;D",
    "observed_direct_second_place_zones": "A;B",
    "observed_cross_second_place_pairs": "C+D",
    "observed_primary_awards": "4",
    "observed_direct_second_awards": "2",
    "observed_cross_awards": "1",
    "observed_qualifier_awards": "7",
    "sandbox_entrant_count_variable": "yes",
    "annual_official_loser_transfer_rule_proven": "no",
    "annual_official_draw_verified": "no",
    "general_future_year_regulation_claimed": "no",
    "live_fmt025_runtime_enabled": "no",
    "optional_ranking_enabled": "no",
    "proof_scope": "2026_observed_official_macro_only_future_use_is_hypothetical",
}


def audit_2026_hiroshima_stage13e3g26(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    baseline = audit_2026_hiroshima_stage13e3g25(root)
    policy_rows = _read(root, MACRO_TEMPLATE_FILE)
    official_preview = _read(root, PREVIEW_FILE)
    official_phases = _read(root, GRAPH_FILE)
    errors: list[str] = []
    if not baseline["ok"]:
        errors.append("Stage25 25-game/32-edge historical ledger is not valid")
    if len(policy_rows) != 1:
        errors.append("single year-limited west macro template policy required")
    else:
        for field, expected in EXPECTED_RECORD.items():
            if policy_rows[0].get(field) != expected:
                errors.append(f"unsupported annual generality or policy field: {field}")

    if (len(official_preview) != 1
            or official_preview[0]["document_year"] != "2026"
            or official_preview[0]["observed_main_berths"] != "7"
            or official_preview[0]["all_pairings_and_loser_arrows_reviewed"] != "no"):
        errors.append("2026 federation image macro only, not official full draw")
    role_groups: dict[str, set[str]] = {}
    for row in official_phases:
        role_groups.setdefault(row["phase_execution_role"], set()).add(row["zone_scope"])
        if (row["complete_pairing_edges_transcribed"] != "no"
                or row["season_independent_transfer_selector_verified"] != "no"
                or row["fmt025_live_route_approved"] != "no"):
            errors.append(f"official match routing incorrectly released: {row['route_id']}")
    if (len(official_phases) != 9 or role_groups != {
            "PRIMARY": {"A", "B", "C", "D"},
            "REPECHAGE_ZONE": {"A", "B", "C", "D"},
            "REPECHAGE_CROSS_ZONE_GATE": {"C;D"},
        }):
        errors.append("official nine event macro graph changed")

    template = WEST_2026_OBSERVED_MACRO_EXAMPLE
    if (validate_macro_template(template) != 7 or
            template.source_scope != "official_2026_west_macro_observed_not_2027_regulation"):
        errors.append("2026 source template is not a verified future regulation")
    examples = []
    for count in (18, 19, 23):
        ids = tuple(f"fictional_test_only_{i}" for i in range(count))
        draft = draft_qualification_macro(
            entrant_ids=ids, template=template, seed=f"stage26-sandbox-{count}",
        )
        sizes = [len(x) for _, x in draft.allocation.zone_school_ids]
        if (sum(sizes) != count or max(sizes) - min(sizes) > 1
                or draft.qualifier_slots != 7
                or draft.total_main_entry_slots != 7
                or draft.official_annual_draw_verified
                or draft.official_loser_selector_verified
                or draft.match_level_pairings_generated
                or draft.live_fmt025_runtime_enabled
                or draft.optional_ranking_enabled):
            errors.append(f"future-entrant-size sandbox invariants failed: {count}")
        examples.append({"participants": count, "zone_sizes": sizes})
    return {
        "ok": not errors, "errors": errors,
        "historical_2026_west_matches_rechecked": baseline["historical_played_games"],
        "historical_2026_west_edges_rechecked": baseline["school_continuation_edges"],
        "historical_main_qualifiers": baseline["historical_berth_awards"],
        "future_sandbox_entrant_sizes": examples,
        "observed_2026_macro_qualifier_slots": 7,
        "official_full_pairings_verified": False,
        "official_general_loser_selector_verified": False,
        "live_fmt025_runtime_changed": False,
        "optional_ranking_unlocked": False,
    }
