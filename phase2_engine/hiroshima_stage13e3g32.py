"""Stage 13E-3G-32: cross-check versioned preflight input and 2026 release locks.

8 seasonal districts each have six explicitly unresolved federation route
questions from Stage30. The new read-only input API accepts either fictional
DAGs or the fixed Stage25 secondary-results observation for autumn/west.
Neither candidate path constitutes production FMT025 authorisation.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g30 import (
    GROUPS, RULE_REQUIREMENTS, UNRESOLVED_ROUTE_RULES_FILE,
    audit_2026_hiroshima_stage13e3g30,
)
from .hiroshima_stage13e3g31 import audit_2026_hiroshima_stage13e3g31
from .hiroshima_fmt025_input_preflight import (
    ROUTE_LOCK_FILE, Fmt025PreflightError, HISTORICAL, SANDBOX,
    load_preflight_payload_json, preflight_fmt025_input,
    require_live_fmt025_release,
)

EXAMPLE_SANDBOX_FILE = (
    "research/2026/hiroshima_fmt025_preflight_example_"
    "fictional_four_schools_stage13e3g32.json"
)
EXAMPLE_OBSERVED_FILE = (
    "research/2026/hiroshima_fmt025_preflight_example_"
    "observed_2026_autumn_west_stage13e3g32.json"
)
LOCK_STATUS = "blocked_pending_verified_annual_draw_and_loser_destinations"


def audit_2026_hiroshima_stage13e3g32(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    locks = _read(root, ROUTE_LOCK_FILE)
    pending = _read(root, UNRESOLVED_ROUTE_RULES_FILE)
    errors: list[str] = []
    previous30 = audit_2026_hiroshima_stage13e3g30(root)
    previous31 = audit_2026_hiroshima_stage13e3g31(root)
    if not previous30["ok"]:
        errors.append("Stage30 official written-rule evidence or six needs per group failed")
    if not previous31["ok"]:
        errors.append("Stage31 historical match replay audit failed")
    lock_map = {(x["season"], x["district_code"]): x for x in locks}
    grouped = Counter((x["season"], x["district_code"]) for x in pending)
    expected_keys = {(season,district) for season,district,_ in GROUPS}
    if (len(locks) != 8 or len(lock_map) != 8 or set(lock_map) != expected_keys):
        errors.append("eight unique annual FMT025 release-lock records required")
    if (len(pending) != 48 or set(grouped) != expected_keys
            or any(grouped[key] != 6 for key in expected_keys)):
        errors.append("all eight districts need exactly six unverified official route claims")

    for idx, (season,district,stage) in enumerate(GROUPS,1):
        row = lock_map.get((season,district))
        if row is None:
            continue
        expected = {
            "lock_id": f"HFPL2026{idx:03d}",
            "document_year": "2026", "season": season,
            "district_code": district, "stage_group_id": stage,
            "format_model_id": "FMT025",
            "unverified_required_draw_items": str(len(RULE_REQUIREMENTS)),
            "annual_primary_pairing_verified": "no",
            "annual_primary_loser_transfer_verified": "no",
            "annual_second_place_pairing_verified": "no",
            "annual_cross_gate_verified": "no",
            "independent_release_approved": "no",
            "stage25_secondary_read_only_replay_available":
                "yes" if (season,district)==("autumn","west") else "no",
            "fmt025_live_scheduler_connected": "no",
            "optional_ranking_authorized": "no",
            "release_status": LOCK_STATUS,
        }
        for key,value in expected.items():
            if row.get(key) != value:
                errors.append(f"annual FMT025 preflight release boundary changed: {season}/{district}/{key}")
    previews = {}
    for scenario, file in (("fictional_inline", EXAMPLE_SANDBOX_FILE),
                           ("observed_secondary", EXAMPLE_OBSERVED_FILE)):
        try:
            payload = load_preflight_payload_json((root / file).read_text(encoding="utf-8"))
            is_history = scenario == "observed_secondary"
            if payload.get("source_kind") != (HISTORICAL if is_history else SANDBOX):
                errors.append(f"incorrect input provenance kind for {scenario}")
                continue
            output = preflight_fmt025_input(
                payload, data_dir=root if is_history else None,
            )
            try:
                require_live_fmt025_release(output)
                errors.append(f"{scenario} illegitimately released FMT025 live scheduler")
            except Fmt025PreflightError:
                pass
            if (output.authorized_for_live_fmt025
                    or output.optional_ranking_allowed or output.full_official_draw_verified
                    or not output.accepted_for_read_only_preview
                    or len(output.payload_sha256) != 64):
                errors.append(f"{scenario} cannot claim release or official truth")
            if is_history:
                if (output.match_count,output.first_entry_count,output.transfer_count,
                    output.qualifier_count,output.direct_exemption_count)!=(25,18,32,7,0):
                    errors.append("Stage25 historical 25/18/32/7 identity changed in preflight")
            else:
                if (output.match_count,output.first_entry_count,output.transfer_count,
                    output.qualifier_count,output.direct_exemption_count)!=(3,4,2,3,0):
                    errors.append("fictional four-school dry run is inconsistent")
            previews[scenario]={
                "matches": output.match_count,
                "first_entrants": output.first_entry_count,
                "outcome_transfers": output.transfer_count,
                "qualifiers": output.qualifier_count,
                "read_only": output.accepted_for_read_only_preview,
            }
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append(f"versioned input preflight rejected {scenario}: {exc}")
    return {
        "ok": not errors, "errors": errors,
        "season_district_release_locks": len(locks),
        "official_unresolved_route_requirements": len(pending),
        "preview_scenarios": previews,
        "source_trust_2026_autumn_west": "observed_secondary_results_only",
        "full_official_match_arrows_verified": 0,
        "production_fmt025_release_paths": 0,
        "optional_ranking_unlocked": False,
        "official_future_year_policy_claimed": False,
    }
