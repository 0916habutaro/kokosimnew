"""Stage43G-47: Iwate/Miyagi/Fukushima spring qualifiers -> MAIN sandbox.

Strictly bounded to the three verified 2026 group graphs, FMT002/FMT003.
Future entrants are explicitly supplied, never inferred to be official.
"""
from __future__ import annotations

from math import ceil, log2
from pathlib import Path
from typing import Mapping, Sequence

from game_core.tournament_bridge import AbilityMatchResolver

from .career_roster_archive import CareerRosterArchive
from .engine import TournamentEngine
from .future_competition_bridge import (
    FutureCompetitionNotReady, FutureCompetitionPreview,
    SANDBOX_ENTRANTS, PROJECTED_DATES,
)
from .future_qualifier_bridge import _projected_days
from .future_season_blueprint import build_future_season_blueprint
from .models import AnnualCompetitionInput
from .repository import DataRepository

TOHOKU_COMPOSITE_PREFECTURES = {
    "CMP000074": ("03", "FMT002", 5, 24),  # Iwate
    "CMP000076": ("04", "FMT003", 4, 25),  # Miyagi
    "CMP000082": ("07", "FMT002", 6, 28),  # Fukushima
}


def prepare_future_tohoku_composite_preview(
    *, data_root: str | Path, year: int, competition_id: str,
    entrant_school_ids: Sequence[str],
    group_entrant_school_ids: Mapping[str, Sequence[str]],
    roster_archive: CareerRosterArchive, repo: DataRepository,
    base_seed: int, career_seed: int,
    ability_config_dir: str | Path = "config/abilities",
    match_config_dir: str | Path = "config/match",
    entry_source: str = SANDBOX_ENTRANTS,
) -> FutureCompetitionPreview:
    """Execute all group qualifications on 2027 simulated fixture dates."""
    contract = TOHOKU_COMPOSITE_PREFECTURES.get(competition_id)
    if not contract:
        raise FutureCompetitionNotReady("unsupported Tohoku composite event")
    if entry_source != SANDBOX_ENTRANTS:
        raise FutureCompetitionNotReady("explicit sandbox entrants required")
    if type(year) is not int or not 2026 < year <= 9999:
        raise FutureCompetitionNotReady("future year invalid")
    if any(type(seed) is not int for seed in (base_seed, career_seed)):
        raise FutureCompetitionNotReady("seeds must be integers")
    pcode, model, count, main_count = contract
    if (repo.competition(competition_id).get("prefecture_code") != pcode
            or repo.competition(competition_id).get("competition_type")
            != "spring_prefectural"):
        raise FutureCompetitionNotReady("prefectural 2026 contract changed")
    if repo.access_rules(competition_id):
        raise FutureCompetitionNotReady("external access rules not verified")
    stages = repo.stages(competition_id)
    if len(stages) != 2 or {r["stage_code"] for r in stages} != {
        "BRANCH_QUALIFIER", "MAIN",
    }:
        raise FutureCompetitionNotReady("qualifier->MAIN structure not verified")
    qstage = next(r for r in stages if r["stage_code"] == "BRANCH_QUALIFIER")
    assignment = repo.assignments_by_stage.get(qstage["stage_id"], {})
    if assignment.get("default_format_model_id") != model:
        raise FutureCompetitionNotReady("qualifier model changed")
    known = repo.groups_by_stage[qstage["stage_id"]]
    if (len(known) != count or
            set(group_entrant_school_ids) != {
                r["stage_group_id"] for r in known
            }):
        raise FutureCompetitionNotReady("explicit membership for every group required")
    supplied = list(entrant_school_ids)
    if (len(supplied) < main_count or
            len(supplied) != len(set(supplied)) or
            any(type(sid) is not str
                or sid not in repo.school_to_program
                or repo.schools[sid].get("prefecture_code") != pcode
                for sid in supplied)):
        raise FutureCompetitionNotReady("invalid/duplicate prefectural entrants")
    groups = {}
    all_members = []
    quota_sum = 0
    for group in known:
        gid = group["stage_group_id"]
        members = list(group_entrant_school_ids[gid])
        format_id = repo.group_format[gid]["format_model_id"]
        quota = repo.param(
            qstage["stage_id"], "output_slots", gid,
            int(group.get("advance_slots_to_next") or 0),
        )
        eligible = repo.group_school_ids(group, 2026)
        if (format_id != model or not isinstance(quota, int)
                or quota <= 0 or len(members) < quota
                or len(members) != len(set(members))
                or any(sid not in eligible for sid in members)):
            raise FutureCompetitionNotReady(
                f"{gid}: invalid model, quota or 2026 reference affiliation"
            )
        groups[gid] = members
        all_members.extend(members)
        quota_sum += quota
    if quota_sum != main_count or set(all_members) != set(supplied) or (
        len(all_members) != len(set(all_members))
    ):
        raise FutureCompetitionNotReady("composite memberships/quotas mismatch")
    blueprint = build_future_season_blueprint(
        data_root, year=year, base_seed=base_seed,
    )
    if (blueprint.get("source_structure_year") != 2026
            or blueprint.get("provenance") != PROJECTED_DATES
            or blueprint.get("official_calendar") is not False
            or blueprint.get("live_runtime_ready") is not False):
        raise FutureCompetitionNotReady("future source is not a sandbox projection")
    comps = [x for x in blueprint["competitions"]
             if x["competition_id"] == competition_id]
    calendars = [x for x in blueprint["calendars"]
                 if x["competition_id"] == competition_id]
    stage_cals = [x for x in blueprint["stage_calendars"]
                  if x["competition_id"] == competition_id
                  and x["stage_code"] == "BRANCH_QUALIFIER"]
    if len(comps) != 1 or len(calendars) != 1 or len(stage_cals) != 1:
        raise FutureCompetitionNotReady("missing/duplicate projected dates")
    comp, cal, qcal = comps[0], calendars[0], stage_cals[0]
    if (comp.get("reference_year") != year
            or cal.get("year") != year
            or cal.get("date_source") != PROJECTED_DATES
            or qcal.get("date_source") != PROJECTED_DATES
            or cal.get("real_world_verified") is not False
            or qcal.get("real_world_verified") is not False):
        raise FutureCompetitionNotReady("future event provenance invalid")
    qdays = _projected_days(
        qcal["date_list"], year, "Tohoku branch qualifiers",
    )
    mdays = _projected_days(
        cal["game_date_list"], year, "Tohoku spring MAIN",
    )
    if (qdays[-1] >= mdays[0] or
            len(mdays) < ceil(log2(main_count))):
        raise FutureCompetitionNotReady("provisional group/MAIN date gap")
    for sid in supplied:
        roster = roster_archive.roster(year, sid)
        if (roster is None or roster.reference_year != year
                or roster.school_id != sid or
                roster.rng_seed != career_seed or
                roster.cohort_policy != "career_v1"):
            raise FutureCompetitionNotReady(
                f"missing saved 2027 game roster: {sid}"
            )
    resolver = AbilityMatchResolver(
        repo, roster_provider=roster_archive.roster,
        team_generation_seed=career_seed,
        ability_config_dir=ability_config_dir,
        match_config_dir=match_config_dir,
    )
    resolver.begin_season(year, career_seed)
    annual = AnnualCompetitionInput(
        competition_id=competition_id,
        year=year, entrant_school_ids=supplied,
        rng_seed=int(comp["rng_seed"]),
        group_entrant_school_ids=groups,
    )
    scheduled = TournamentEngine(
        repo, pre_main_match_resolver=resolver,
        main_match_resolver=resolver,
    ).prepare_scheduled_competition_runtime(
        annual, cal,
        stage_date_lists={"BRANCH_QUALIFIER": qdays},
    )
    if scheduled.calendar_gap_match_ids:
        raise FutureCompetitionNotReady(
            "composite qualifier has no initial game date"
        )
    scheduled.competition_name = str(comp["display_name"])
    return FutureCompetitionPreview(
        year=year, competition_id=competition_id,
        competition_display_name=scheduled.competition_name,
        entry_source=entry_source, annual=annual, scheduled=scheduled,
    )
