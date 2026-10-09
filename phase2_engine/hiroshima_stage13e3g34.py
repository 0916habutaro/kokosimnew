"""Stage13E-3G-34: prove preview-only browse rows do not contaminate browse DB.

A scored season's DatedMatchRow and persisted school records remain unchanged.
2026 Hiroshima autumn-west observed fixtures are not official numbered draws
or match simulations. In particular, no score or unplayed game outcome is
inferred from an already registered winner.
"""
from __future__ import annotations

from pathlib import Path

from .hiroshima_fmt025_input_preflight import load_preflight_payload_json
from .hiroshima_fmt025_incremental_preview import (
    start_read_only_preview, record_preapproved_match_result,
)
from .hiroshima_fmt025_preview_browse_model import (
    build_fmt025_preview_browse_views, DATE_SECONDARY, DATE_UNDATED,
    VIEW_SCOPE,
)
from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g25 import NODES_FILE, EDGES_FILE
from .hiroshima_stage13e3g31 import replay_stage25_historical_observations
from .hiroshima_stage13e3g32 import EXAMPLE_OBSERVED_FILE, EXAMPLE_SANDBOX_FILE
from .hiroshima_stage13e3g33 import audit_2026_hiroshima_stage13e3g33

SAMPLE_PHASE_ROWS_FILE = "research/2026/hiroshima_fmt025_browse_expected_states_stage13e3g34.csv"
EXPECTED = (
    ("start", 0, 2, 1, 0, 0, 3, "no"),
    ("after_P1", 1, 1, 1, 4, 1, 2, "no"),
    ("after_P2", 2, 1, 0, 4, 2, 1, "no"),
    ("after_R1", 3, 0, 0, 4, 3, 0, "yes"),
)


def audit_2026_hiroshima_stage13e3g34(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    prior = audit_2026_hiroshima_stage13e3g33(root)
    errors = []
    if not prior["ok"]:
        errors.append("Stage33 result checkpoint/replay audit failed")
    expected = _read(root, SAMPLE_PHASE_ROWS_FILE)
    if len(expected) != 4:
        errors.append("exactly four browse snapshot expectations required")
    payload = load_preflight_payload_json((root / EXAMPLE_SANDBOX_FILE).read_text(encoding="utf-8"))
    state = start_read_only_preview(payload)
    snapshots = []
    for i, stage in enumerate(EXPECTED):
        if i:
            mid, win = (("P1","A"),("P2","C"),("R1","B"))[i-1]
            state = record_preapproved_match_result(
                payload, state.checkpoint, match_id=mid, recorded_winner_id=win,
            )
        view = build_fmt025_preview_browse_views(payload,state.checkpoint)
        comp = view.competition_results[0]
        actual = (
            stage[0], comp.completed_count, comp.ready_count, comp.waiting_count,
            len(view.school_records), comp.confirmed_qualifier_count,
            comp.remaining_qualifier_slots, "yes" if comp.replay_completed else "no",
        )
        if i < len(expected):
            columns = ("stage", "completed", "ready", "waiting", "visible_schools",
                       "confirmed_qualifiers", "remaining_berths", "replay_completed")
            for key, value in zip(columns, actual):
                if expected[i].get(key) != str(value):
                    errors.append(f"browse milestone row {i}/{key} disagrees with runtime")
        if (len(view.matches_by_date) != 3 or comp.fixture_count != 3
                or view.proof_scope != VIEW_SCOPE or view.live_fmt025_runtime_enabled
                or view.optional_ranking_enabled
                or any(m.team1_score is not None or m.team2_score is not None
                       or m.official_match_number or m.is_official_draw_verified
                       or m.date_source != DATE_UNDATED for m in view.matches_by_date)):
            errors.append(f"fictional stage {i} invented result metadata")
        snapshots.append({
            "stage": stage[0], "completed": comp.completed_count,
            "ready": comp.ready_count, "waiting": comp.waiting_count,
            "qualified": comp.confirmed_qualifier_count,
        })
    if not state.replay_completed or len(view.confirmed_berths) != 3:
        errors.append("fictional three qualifying gates did not complete")

    history = load_preflight_payload_json(
        (root / EXAMPLE_OBSERVED_FILE).read_text(encoding="utf-8")
    )
    nodes,edges = _read(root,NODES_FILE),_read(root,EDGES_FILE)
    expected_qualifiers = replay_stage25_historical_observations(nodes,edges)
    winners = {t.match_id:t.winner_id for t in expected_qualifiers.match_traces}
    current = start_read_only_preview(history,data_dir=root)
    initial_browse = build_fmt025_preview_browse_views(history,current.checkpoint,data_dir=root)
    if (len(initial_browse.matches_by_date) != 25 or
            any(m.winner_id or m.match_date for m in initial_browse.matches_by_date)
            or initial_browse.competition_results[0].confirmed_qualifier_count):
        errors.append("historical initial browse leaked unplayed results")
    for i in range(25):
        if not current.ready_match_ids:
            errors.append("no ready historical match")
            break
        mid = current.ready_match_ids[0]
        current = record_preapproved_match_result(
            history,current.checkpoint,match_id=mid,recorded_winner_id=winners[mid],
            data_dir=root,
        )
    final_view = build_fmt025_preview_browse_views(
        history,current.checkpoint,data_dir=root,
    )
    competition = final_view.competition_results[0]
    if (len(final_view.matches_by_date) != 25
            or competition.completed_count != 25
            or competition.ready_count or competition.waiting_count
            or len(final_view.confirmed_berths) != 7
            or competition.confirmed_qualifier_count != 7
            or competition.remaining_qualifier_slots != 0
            or len(final_view.school_records) != 18):
        errors.append("25 historical match/7 berth read model totals wrong")
    dates_from_nodes = {x["match_id"]:x["match_date"] for x in nodes}
    for m in final_view.matches_by_date:
        if (m.match_date != dates_from_nodes[m.match_id]
                or m.date_source != DATE_SECONDARY
                or m.team1_score is not None or m.team2_score is not None
                or m.official_match_number or m.is_official_draw_verified):
            errors.append(f"historical score or official fixture invented: {m.match_id}")
    if (sum(x.games for x in final_view.school_records) != 50
            or sum(x.wins for x in final_view.school_records) != 25
            or sum(x.losses for x in final_view.school_records) != 25):
        errors.append("read-only school aggregate must be exactly 25 games")
    return {
        "ok": not errors, "errors": errors,
        "fictional_browse_milestones": snapshots,
        "2026_west_read_model": {
            "matches": competition.fixture_count,
            "completed": competition.completed_count,
            "schools": len(final_view.school_records),
            "confirmed_qualifiers": len(final_view.confirmed_berths),
            "source_grade": competition.evidence_grade,
        },
        "official_numbered_match_arrows_verified": 0,
        "unresolved_annual_route_rule_items": 48,
        "wrote_browse_sqlite": False,
        "official_draw_promoted": False,
        "fmt025_live_enabled": False,
        "optional_ranking_enabled": False,
    }
