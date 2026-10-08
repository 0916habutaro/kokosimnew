"""Opt-in 2026 Shizuoka inter-block ranking fixture.

The I/J bracket is NOT a federation area and must not be registered as a
geographic group. Its participants earned prefectural MAIN berths separately
before the extra ranking match. No historical scores/winners are imported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .post_qualification_ranking import RankingOnlyEventRuntime
from .post_qualification_schedule import ScheduledRankingSidecar
from .ranking_reference_2026 import load_2026_ranking_observations
from .ranking_school_reconciliation_2026 import (
    CROSS_AREA, CROSS_BLOCK_FILE, _load, audit_ranking_school_mapping_2026,
    load_ranking_school_mapping_2026,
)


def build_verified_2026_cross_block_sidecar(
    data_dir: str | Path,
    *,
    reference_id: str,
    locked_school_ids: Sequence[str],
    qualification_locked_on: str,
) -> ScheduledRankingSidecar:
    """Return a pending optional match ONLY for a fully evidenced pair.

    The locked pair is validated independently; it cannot issue or alter any
    qualification, even when both schools belong to distinct district areas.
    """
    root = Path(data_dir)
    report = audit_ranking_school_mapping_2026(root)
    if not report["ok"]:
        raise ValueError("invalid official school/area or paired-block mapping")
    profiles = _load(root / CROSS_BLOCK_FILE)
    lookup = {r["reference_id"]: r for r in profiles}
    if reference_id not in lookup:
        raise ValueError("unknown or unapproved cross-block event")
    profile = lookup[reference_id]
    observation = next(
        r for r in load_2026_ranking_observations(root)
        if r["reference_id"] == reference_id
    )
    mapping = next(
        r for r in load_ranking_school_mapping_2026(root)
        if r["reference_id"] == reference_id
    )
    if (
        observation["reference_classification"] != "verified_ranking_only"
        or mapping["mapping_status"] != CROSS_AREA
        or mapping["team1_area_id"] == mapping["team2_area_id"]
        or profile["qualification_effect"] != "none"
    ):
        raise ValueError("fixture is not a verified post-qualification cross-block match")
    participants = (
        mapping["team1_school_id"], mapping["team2_school_id"]
    )
    if len(locked_school_ids) != 2 or set(locked_school_ids) != set(participants):
        raise ValueError("both bracket-block winners must be locked qualifiers")
    event = RankingOnlyEventRuntime.create(
        competition_id=observation["competition_id"],
        stage_id=observation["stage_id"],
        stage_code="BRANCH_QUALIFIER",
        group_id=f'XBLOCK_{profile["source_block1"]}_{profile["source_block2"]}',
        format_model_id="FMT025",
        mode="pairwise_deciders",
        locked_school_ids=locked_school_ids,
        pairings=[participants],
        event_id="D" + profile["match_date"].replace("-", ""),
    )
    return ScheduledRankingSidecar.create(
        event,
        qualification_locked_on=qualification_locked_on,
        match_dates=[profile["match_date"]],
    )


def hiroshima_2026_qualification_guard(data_dir: str | Path) -> dict:
    """Refuse to infer optional matches from '1st/2nd/rank' bracket titles.

    Audit both the protected three match-level examples AND every named
    spring/autumn route through which prefectural berths were allocated.
    """
    from .hiroshima_district_qualification_2026 import (
        audit_2026_hiroshima_qualification_routes,
    )
    route_audit = audit_2026_hiroshima_qualification_routes(data_dir)
    rows = [
        r for r in load_2026_ranking_observations(data_dir)
        if r["competition_id"] in {"CMP000135", "CMP000136"}
    ]
    excluded = [r["reference_id"] for r in rows
                if r["reference_classification"]
                == "qualification_decider_not_ranking"]
    errors = []
    if len(rows) != 3 or len(excluded) != 3:
        errors.append("Hiroshima's three known qualifier games must stay excluded")
    mapping = {r["reference_id"]: r for r in
               load_ranking_school_mapping_2026(data_dir)}
    if any(mapping[ref]["mapping_status"] != "excluded_qualification_decider"
           for ref in excluded):
        errors.append("Hiroshima ranking/qualification classification mismatch")
    if not route_audit["ok"]:
        errors.extend(route_audit["errors"])
    return {
        "ok": not errors,
        "errors": errors,
        "route_audit": route_audit,
        "district_sub_tournament_route_count": route_audit["sub_tournament_route_count"],
        "district_route_scope": route_audit["matching_scope"],
        "excluded_qualification_reference_ids": sorted(excluded),
        "verified_optional_ranking_count": 0,
        "federation_main_berths_per_season": 32,
        "needs_full_2026_bracket_outcome_review": True,
    }
