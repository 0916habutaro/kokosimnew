"""Stage13E-3G-41: nonvisual acceptance audit for browse/preview navigation.

Do NOT infer native Windows Tk rendering success from a headless CI job.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g40 import audit_2026_hiroshima_stage13e3g40

ACCEPTANCE_FILE = "research/2026/hiroshima_gui_stage13e3g41_acceptance_checklist.csv"
AUTOMATED = 13
MANUAL = 10


def audit_2026_hiroshima_stage13e3g41(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    previous = audit_2026_hiroshima_stage13e3g40(root)
    errors: list[str] = []
    if not previous["ok"]:
        errors.append("Stage40 18-school browse handoff audit failed")
    rows = _read(root,ACCEPTANCE_FILE)
    if len(rows) != AUTOMATED + MANUAL:
        errors.append("stage41 acceptance manifest must contain exactly 23 steps")
    if len({item.get("check_id") for item in rows}) != len(rows):
        errors.append("acceptance step IDs are duplicated")
    if any(row.get("official_draw_claim") != "no" or
           row.get("live_fmt025_authorized") != "no" for row in rows):
        errors.append("GUI acceptance cannot assert official bracket or live runtime")

    for index,item in enumerate(rows):
        manual=index>=AUTOMATED
        expected={
            "check_id":f"G41-{index+1:02d}",
            "verification_category":"windows_gui_manual" if manual else (
                "headless_static_callback" if index==12 else "headless_gui_callback"
            ),
            "automation_status":"not_run" if manual else "covered_by_unittest",
            "windows_visual_status":"not_run",
        }
        if not item.get("action") or not item.get("expected_result"):
            errors.append(f"empty GUI acceptance action: {index+1}")
        for key,value in expected.items():
            if item.get(key)!=value:
                errors.append(f"{key} acceptance evidence mismatch: {index+1}")

    # Important: GUI callback tests are not evidence that a native window
    # was opened. The 10 Windows checks remain pending.
    manual_rows=[x for x in rows if x.get("verification_category")=="windows_gui_manual"]
    if len(manual_rows)!=MANUAL:
        errors.append("Windows manual GUI checks must be kept separately")
    return {
        "ok":not errors, "errors":errors,
        "stage40_verified_school_count":previous["handoff"].get("verified_preview_schools",0),
        "automated_headless_navigation_checks":AUTOMATED,
        "manual_windows_checks_pending":len(manual_rows),
        "native_gui_visual_accepted":False,
        "visual_status_counts":dict(Counter(x.get("windows_visual_status") for x in rows)),
        "sqlite_historical_results_written":False,
        "official_2026_west_individual_numbers_verified":0,
        "official_2026_west_transfer_arrows_verified":0,
        "official_2026_8_group_route_requirements_unresolved":48,
        "production_fmt025_enabled":False,
        "optional_ranking_enabled":False,
    }
