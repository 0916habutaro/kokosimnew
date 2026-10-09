"""Stage13E-3G-35: headless audit for the experimental Tk GUI bridge."""
from __future__ import annotations

from pathlib import Path

from .hiroshima_stage13e3g34 import audit_2026_hiroshima_stage13e3g34
from .hiroshima_stage13e3g35_preview_gui_model import (
    FICTIONAL, OBSERVED_2026_WEST, HiroshimaPreviewGuiModel,
)

def audit_2026_hiroshima_stage13e3g35(data_dir: str | Path) -> dict:
    root=Path(data_dir)
    prior=audit_2026_hiroshima_stage13e3g34(root)
    errors=[]
    if not prior["ok"]:
        errors.append("Stage34 read model output and Stage33 checkpoints must pass")

    try:
        model=HiroshimaPreviewGuiModel(root,FICTIONAL)
        observed=[]
        for _ in range(4):
            render=model.render()
            observed.append((render.played_count,render.ready_count,
                             render.waiting_count,render.qualifier_count))
            if render.next_result_enabled:
                model.show_next_preapproved_result()
        if observed != [(0,2,1,0),(1,1,1,1),(2,1,0,2),(3,0,0,3)]:
            errors.append("fictional Tk presenter four-stage progression changed")
        final=model.render()
        if (len(final.match_rows)!=3 or len(final.school_rows)!=4
                or len(final.berth_rows)!=3 or not final.replay_completed
                or final.live_fmt025_runtime_enabled or final.official_draw_verified
                or final.optional_ranking_enabled):
            errors.append("fictional pilot projected unauthorized or inconsistent data")
        model.reset_preview()
        if model.render().played_count != 0:
            errors.append("reset did not discard in-memory event visibility")
        model.set_scenario(OBSERVED_2026_WEST)
        start=model.render()
        if (start.played_count!=0 or start.qualifier_count!=0
                or len(start.match_rows)!=25
                or any(x[6]!="－" or x[7]!="未定" for x in start.match_rows)):
            errors.append("historical preview leaked unplayed results")
        for _ in range(25):
            if model.show_next_preapproved_result() is None:
                errors.append("25 historical preapproved results were not available")
                break
        history=model.render()
        if (history.played_count!=25 or history.ready_count or history.waiting_count
                or history.qualifier_count!=7
                or len(history.school_rows)!=18 or len(history.berth_rows)!=7
                or not history.replay_completed
                or history.live_fmt025_runtime_enabled
                or history.official_draw_verified):
            errors.append("2026 west historic 25/18/7 headless GUI result changed")
        if (any(x[4]!="－" or x[8]!="二次結果日付" for x in history.match_rows)
                or any(x[1]!="県大会進出確定" for x in history.berth_rows)):
            errors.append("GUI pretended a score/official date/unknown berth")
        winner_filter=model.render(status_filter="completed")
        if len(winner_filter.match_rows)!=25:
            errors.append("completed-match status filter lost historical matches")
        model.set_scenario(FICTIONAL)
        if model.render().played_count!=0:
            errors.append("switching source must reset event history")
        model.restore_checkpoint(model.export_checkpoint())
        if model.render().played_count!=0:
            errors.append("checkpoint read-only recovery changed clean state")
        stats={
            "scenario_count":2,
            "fictional_states":len(observed),
            "historical_revealed_games":history.played_count,
            "historical_school_count":len(history.school_rows),
            "historical_qualifier_count":history.qualifier_count,
        }
    except (OSError,ValueError,TypeError,KeyError) as exc:
        errors.append(f"GUI presenter audit failed: {exc}")
        stats={}
    return {
        "ok":not errors, "errors":errors,
        "pilot":stats,
        "attached_to_existing_browse_gui":True,
        "sqlite_changes":False,
        "headless_presenter_verified":not errors,
        "native_window_visual_check_performed":False,
        "annual_unresolved_official_route_items":48,
        "newly_verified_official_match_numbers":0,
        "newly_verified_official_arrows":0,
        "live_fmt025_runtime_enabled":False,
        "optional_ranking_enabled":False,
    }
