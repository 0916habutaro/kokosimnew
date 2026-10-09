"""Stage 13E-3G-36: navigation/search-only GUI pilot audit.

This module checks headless read-model interaction and preserves a separate
manual Windows acceptance list. Headless CI NEVER means native Tk visual
inspection was completed, and the pilot cannot release FMT025.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g35 import audit_2026_hiroshima_stage13e3g35
from .hiroshima_stage13e3g35_preview_gui_model import (
    FICTIONAL, OBSERVED_2026_WEST,
    HiroshimaPreviewGuiModel, PreviewGuiModelError,
)

ACCEPTANCE_FILE = "research/2026/hiroshima_gui_stage13e3g36_acceptance_checklist.csv"


def audit_2026_hiroshima_stage13e3g36(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    previous = audit_2026_hiroshima_stage13e3g35(root)
    checks = _read(root, ACCEPTANCE_FILE)
    errors: list[str] = []
    if not previous["ok"]:
        errors.append("Stage35 headless GUI model was not stable")
    if len(checks) != 16 or len({row["check_id"] for row in checks}) != 16:
        errors.append("exactly 16 unique acceptance checks required")
    for i, row in enumerate(checks):
        is_manual = i >= 10
        expected = {
            "check_id": f"G36-{i+1:02d}",
            "automation_status": "not_run" if is_manual else "covered_by_unittest",
            "windows_visual_status": "not_run",
            "official_draw_claim": "no",
            "live_fmt025_authorized": "no",
            "verification_category": (
                "windows_gui_manual" if is_manual
                else ("headless_gui_callback" if i in (4,5,6,7)
                      else "headless_cli" if i == 8 else "headless_model")
            ),
        }
        for name, value in expected.items():
            if row.get(name) != value:
                errors.append(f"invalid headless/manual evidence separation: {row.get('check_id')}/{name}")
        if not row.get("action") or not row.get("expected_result"):
            errors.append(f"acceptance step is missing action/expected behavior: {i+1}")

    try:
        model = HiroshimaPreviewGuiModel(root)
        if model.search_visible_school_ids("A") != ("A",):
            errors.append("fictional school name search no longer exact")
        if model.render(school_query="unlisted_school").match_rows:
            errors.append("unknown school query leaked match rows")
        if model.render(school_query="unlisted_school").school_rows:
            errors.append("unknown school query leaked school rows")
        if model.render(school_query="unlisted_school").berth_rows:
            errors.append("unknown school query leaked qualifier rows")
        if model.show_preapproved_result_for_match("P2") != "P2":
            errors.append("independently ready P2 cannot be revealed first")
        if model.render(status_filter="completed", school_query="C").played_count != 1:
            errors.append("completed counts were incorrectly lost when filtering")
        if len(model.render(status_filter="completed", school_query="C").match_rows) != 1:
            errors.append("completed P2 could not be found from school")
        try:
            model.show_preapproved_result_for_match("R1")
            errors.append("unready repechage result was illegally revealed")
        except PreviewGuiModelError:
            pass
        model.show_preapproved_result_for_match("P1")
        model.show_preapproved_result_for_match("R1")
        final = model.render()
        if (not final.replay_completed or final.qualifier_count != 3
                or final.live_fmt025_runtime_enabled
                or final.optional_ranking_enabled or final.official_draw_verified):
            errors.append("fictional finish or official boundary changed")
        model.set_scenario(OBSERVED_2026_WEST)
        history = model.render()
        if (history.played_count != 0 or history.qualifier_count != 0
                or len(history.match_rows) != 25):
            errors.append("switch to 2026 west should reset all visible results")
        if model.search_visible_school_ids("future_unknown_school"):
            errors.append("unseen historical participant became searchable")
        details = {"fictional_completed": final.played_count,
                   "fictional_qualifiers": final.qualifier_count,
                   "historical_matches": len(history.match_rows)}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(f"stage36 headless navigation audit failed: {exc}")
        details = {}

    status = Counter(row["windows_visual_status"] for row in checks)
    return {
        "ok": not errors,
        "errors": errors,
        "headless_navigation": details,
        "automated_acceptance_items": len(checks)-6,
        "manual_windows_acceptance_items": 6,
        "native_gui_visual_inspection_completed": False,
        "native_gui_visual_status_counts": dict(status),
        "2026_official_individual_match_numbers_verified": 0,
        "2026_official_individual_arrows_verified": 0,
        "2026_unresolved_official_route_conditions": 48,
        "browse_sqlite_modified": False,
        "live_fmt025_runtime_enabled": False,
        "optional_ranking_enabled": False,
    }
