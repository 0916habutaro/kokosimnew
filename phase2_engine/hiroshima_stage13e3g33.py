"""Stage13E-3G-33: audit incremental read-only fixture result checkpoints.

Stage32 accepts fictional and Stage25 secondary historical sources only.
Historical 2026 autumn-west 25 games are revealed progressively, but their
outcomes are NOT fresh simulation and their 32 observed transitions are NOT
the federation's independently confirmed drawing arrows.
"""
from __future__ import annotations

import json
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g25 import NODES_FILE, EDGES_FILE
from .hiroshima_stage13e3g31 import replay_stage25_historical_observations
from .hiroshima_stage13e3g32 import (
    EXAMPLE_SANDBOX_FILE, EXAMPLE_OBSERVED_FILE,
    audit_2026_hiroshima_stage13e3g32,
)
from .hiroshima_fmt025_input_preflight import load_preflight_payload_json
from .hiroshima_fmt025_incremental_preview import (
    IncrementalPreviewError, start_read_only_preview, inspect_read_only_preview,
    record_preapproved_match_result, export_read_only_checkpoint,
    restore_read_only_checkpoint, CHECKPOINT_VERSION,
)

EXPECTED_EVENTS_FILE = "research/2026/hiroshima_fmt025_preview_expected_events_stage13e3g33.json"


def audit_2026_hiroshima_stage13e3g33(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    prev = audit_2026_hiroshima_stage13e3g32(root)
    errors: list[str] = []
    if not prev["ok"]:
        errors.append("Stage32 versioned preflight and 8-year-group locks must pass")
    try:
        manifest = load_preflight_payload_json((root / EXPECTED_EVENTS_FILE).read_text(encoding="utf-8"))
        payload = load_preflight_payload_json((root / EXAMPLE_SANDBOX_FILE).read_text(encoding="utf-8"))
        if (set(manifest) != {
                "scenario", "input_file", "checkpoint_version", "type", "events",
                "source_authority", "official_annual_draw_verified",
                "live_fmt025_runtime_enabled", "optional_ranking_enabled"
            }
            or manifest["scenario"] != "fictional_stage32_4_schools"
            or manifest["input_file"] != EXAMPLE_SANDBOX_FILE
            or manifest["checkpoint_version"] != CHECKPOINT_VERSION
            or manifest["type"] != "historical_outcome_reveal_not_new_game_simulation"
            or manifest["source_authority"] != "fictional_dry_run_only"
            or manifest["official_annual_draw_verified"] is not False
            or manifest["live_fmt025_runtime_enabled"] is not False
            or manifest["optional_ranking_enabled"] is not False):
            errors.append("fictional four-stage snapshot manifest must remain read-only")
        events = manifest["events"]
        if len(events) != 4:
            errors.append("initial and three result-confirmation snapshots required")
        elif [(r.get("after_match_id"), r.get("recorded_winner_id"))
              for r in events] != [
                  (None, None), ("P1", "A"), ("P2", "C"), ("R1", "B")
              ]:
            errors.append("fictional input event ordering or oracle winners were altered")
        state = start_read_only_preview(payload)
        for idx, event in enumerate(events):
            if idx > 0:
                state = record_preapproved_match_result(
                    payload, state.checkpoint,
                    match_id=event["after_match_id"],
                    recorded_winner_id=event["recorded_winner_id"],
                )
            expected = {
                "ready_match_ids": list(state.ready_match_ids),
                "waiting_match_ids": list(state.waiting_match_ids),
                "played_match_ids": list(state.played_match_ids),
                "confirmed_qualifier_ids": list(state.confirmed_qualifier_ids),
                "remaining_qualifier_slots": state.remaining_qualifier_slots,
                "replay_completed": state.replay_completed,
            }
            for field, value in expected.items():
                if event.get(field) != value:
                    errors.append(f"recorded fictional step {idx} not reproduced: {field}")
            if state.official_draw_verified or state.live_fmt025_runtime_enabled or state.optional_ranking_enabled:
                errors.append("fictional state cannot become official or live")
            restored = restore_read_only_checkpoint(
                payload, export_read_only_checkpoint(state.checkpoint)
            )
            if restored != state:
                errors.append(f"JSON restore differs from original: step {idx}")
    except (OSError, TypeError, KeyError, ValueError, IncrementalPreviewError) as exc:
        errors.append(f"fictional checkpoint validation failed: {exc}")

    try:
        hist = load_preflight_payload_json((root / EXAMPLE_OBSERVED_FILE).read_text(encoding="utf-8"))
        original = replay_stage25_historical_observations(
            _read(root, NODES_FILE), _read(root, EDGES_FILE),
        )
        oracles = {trace.match_id: trace.winner_id for trace in original.match_traces}
        current = start_read_only_preview(hist, data_dir=root)
        initial_ready_count = len(current.ready_match_ids)
        for _ in range(25):
            if not current.ready_match_ids:
                raise IncrementalPreviewError("historical DAG has no ready match before completion")
            chosen = current.ready_match_ids[0]
            current = record_preapproved_match_result(
                hist, current.checkpoint, match_id=chosen,
                recorded_winner_id=oracles[chosen], data_dir=root,
            )
        if (not current.replay_completed
                or len(current.played_match_ids) != 25
                or current.ready_match_ids or current.waiting_match_ids
                or len(current.confirmed_qualifier_ids) != 7
                or current.remaining_qualifier_slots != 0
                or len(current.checkpoint.applied_results) != 25
                or not current.evidence_grade.endswith("not_official_drawing")
                or current.live_fmt025_runtime_enabled):
            errors.append("Stage25 observed 25-match incremental playback is inconsistent")
        recovered = restore_read_only_checkpoint(
            hist, export_read_only_checkpoint(current.checkpoint),
            data_dir=root,
        )
        if recovered != current:
            errors.append("2026 autumn-west historical checkpoint roundtrip failed")
        staged_result = {
            "historical_matches_revealed": len(current.played_match_ids),
            "historical_berths_revealed": len(current.confirmed_qualifier_ids),
            "initial_ready_match_count": initial_ready_count,
            "replay_completed": current.replay_completed,
        }
    except (OSError, TypeError, KeyError, ValueError, IncrementalPreviewError) as exc:
        errors.append(f"historical incremental replay failed: {exc}")
        staged_result = {}

    return {
        "ok": not errors, "errors": errors,
        "fictional_expected_progress_states": 4,
        "historical_incremental_replay": staged_result,
        "official_2026_verified_individual_arrows": 0,
        "unverified_2026_season_district_route_rules": 48,
        "production_fmt025_runtime_connected": False,
        "optional_ranking_unlocked": False,
        "checkpoint_trust": "payload_and_underlying_source_digests_checked_no_official_proof",
    }
