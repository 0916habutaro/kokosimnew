"""Stage43G-52: build Aichi/Mie qualifier->MAIN alongside the Senbatsu.

All entrants, direct invitations and district groups are frozen *before*
the first national match. The same-year 31-game Senbatsu audit later
certifies these frozen direct entrants without rewriting March matches.
"""
from __future__ import annotations

from math import ceil, log2
from pathlib import Path
from typing import Mapping

from game_core.tournament_bridge import AbilityMatchResolver

from .career_roster_archive import CareerRosterArchive
from .engine import TournamentEngine
from .future_competition_bridge import (
    FutureCompetitionNotReady, FutureCompetitionPreview, SANDBOX_ENTRANTS,
)
from .future_qualifier_bridge import _projected_days
from .future_season_blueprint import build_future_season_blueprint
from .models import AnnualCompetitionInput
from .repository import DataRepository

TOKAI_AICHI = "CMP000113"
TOKAI_MIE = "CMP000115"
TOKAI_CIDS = (TOKAI_AICHI, TOKAI_MIE)


def prepare_future_tokai_concurrent_previews(
    *, data_root: str | Path, year: int, repo: DataRepository,
    frozen: Mapping[str, object], roster_archive: CareerRosterArchive,
    base_seed: int, career_seed: int,
    ability_config_dir: str | Path = "config/abilities",
    match_config_dir: str | Path = "config/match",
) -> dict[str, FutureCompetitionPreview]:
    """Use only frozen explicit Senbatsu selections and grouped school IDs."""
    if type(year) is not int or not 2026 < year <= 9999:
        raise FutureCompetitionNotReady("invalid future game year")
    if type(base_seed) is not int or type(career_seed) is not int:
        raise FutureCompetitionNotReady("invalid future game RNG seed")
    if (frozen.get("year") != year
            or frozen.get("senbatsu_results_verified_at_freeze") is not False
            or frozen.get("auto_prefectural_activation_enabled") is not False
            or frozen.get("same_year_concurrent_schedule_required") is not True):
        raise FutureCompetitionNotReady("requires immutable preseason Tokai input")
    inputs = frozen.get("qualifier_groups_by_competition")
    calendar_meta = frozen.get("destination_schedule")
    if (not isinstance(inputs, dict) or not isinstance(calendar_meta, dict)
            or set(inputs) != set(TOKAI_CIDS)
            or set(calendar_meta) != set(TOKAI_CIDS)):
        raise FutureCompetitionNotReady("both frozen Tokai prefectures required")
    blueprint = build_future_season_blueprint(
        data_root, year=year, base_seed=base_seed,
    )
    if (blueprint.get("source_structure_year") != 2026
            or blueprint.get("official_calendar") is not False
            or blueprint.get("live_runtime_ready") is not False):
        raise FutureCompetitionNotReady("Tokai calendar is not a game projection")
    previews = {}
    for cid, pcode, expected_formats, group_count, slots in (
        (TOKAI_AICHI, "23", {"FMT010", "FMT011", "FMT012", "FMT013", "FMT014"}, 5, 48),
        (TOKAI_MIE, "24", {"FMT016"}, 3, 25),
    ):
        info = calendar_meta[cid]
        groups = inputs[cid]
        if (not isinstance(groups, dict)
                or not isinstance(info, dict)
                or type(info.get("qualifier_slots")) is not int
                or info["qualifier_slots"] != slots):
            raise FutureCompetitionNotReady("frozen Tokai quotas differ")
        comp = repo.competition(cid)
        stages = repo.stages(cid)
        if (comp.get("prefecture_code") != pcode
                or comp.get("competition_type") != "spring_prefectural"
                or len(stages) != 2
                or {x["stage_code"] for x in stages} != {"BRANCH_QUALIFIER", "MAIN"}):
            raise FutureCompetitionNotReady("Tokai prefectural graph changed")
        qualifier = next(s for s in stages if s["stage_code"] == "BRANCH_QUALIFIER")
        known = repo.groups_by_stage[qualifier["stage_id"]]
        if (len(known) != group_count
                or set(groups) != {g["stage_group_id"] for g in known}
                or {repo.group_format[g["stage_group_id"]]["format_model_id"]
                    for g in known} != expected_formats):
            raise FutureCompetitionNotReady("Tokai group format changed")
        direct = list(info["additional_main_bypass_school_ids"])
        if (len(direct) != len(set(direct))
                or any(sid not in repo.school_to_program
                       or repo.schools[sid]["prefecture_code"] != pcode
                       for sid in direct)):
            raise FutureCompetitionNotReady("frozen national byes invalid")
        # Revalidate each saved manifest against verified leaf membership,
        # including Mie's eight child areas under North/Central/South.
        from .career_tokai_concurrent_preflight import _reference_group_members
        other = []
        quotas = 0
        for group in known:
            gid = group["stage_group_id"]
            members = groups[gid]
            if not isinstance(members, list):
                raise FutureCompetitionNotReady("district school list must be frozen")
            quota = repo.param(
                qualifier["stage_id"], "output_slots", gid,
                int(group.get("advance_slots_to_next") or 0),
            )
            if (type(quota) is not int or quota <= 0
                    or len(members) < quota
                    or len(members) != len(set(members))
                    or any(sid not in _reference_group_members(repo, group)
                           for sid in members)):
                raise FutureCompetitionNotReady("invalid Tokai district roster/quota")
            quotas += quota
            other.extend(members)
        if quotas != slots:
            raise FutureCompetitionNotReady("Tokai main qualification slots changed")
        entrants = list(dict.fromkeys([*direct, *other]))
        if (len(entrants) != len(direct) + len(other)
                or any(sid not in repo.school_to_program
                       or repo.schools[sid]["prefecture_code"] != pcode
                       for sid in other)):
            raise FutureCompetitionNotReady("Tokai direct and qualifier entrant overlap")
        if any(
            (roster := roster_archive.roster(year, sid)) is None
            or roster.school_id != sid or roster.reference_year != year
            or roster.rng_seed != career_seed or roster.cohort_policy != "career_v1"
            for sid in entrants
        ):
            raise FutureCompetitionNotReady("complete saved career rosters required")
        calendars = [x for x in blueprint["calendars"] if x["competition_id"] == cid]
        qcal = [x for x in blueprint["stage_calendars"]
                if x["competition_id"] == cid
                and x["stage_code"] == "BRANCH_QUALIFIER"]
        competition = [x for x in blueprint["competitions"]
                       if x["competition_id"] == cid]
        if len(calendars) != 1 or len(qcal) != 1 or len(competition) != 1:
            raise FutureCompetitionNotReady("missing projected Tokai dates")
        cal, qrow, crow = calendars[0], qcal[0], competition[0]
        if (cal.get("date_source") != "game_projection_v1"
                or qrow.get("date_source") != "game_projection_v1"
                or cal.get("real_world_verified") is not False
                or qrow.get("real_world_verified") is not False):
            raise FutureCompetitionNotReady("Tokai date source must be fictional")
        qdays = _projected_days(qrow["date_list"], year, "Tokai groups")
        mdays = _projected_days(cal["game_date_list"], year, "Tokai MAIN")
        if (not qdays or not mdays or qdays[-1] >= mdays[0]
                or qdays[0] != info["qualifier_first_date"]
                or qdays[-1] != info["qualifier_last_date"]
                or mdays[0] != info["main_first_date"]
                or len(mdays) < ceil(log2(slots + len(direct)))):
            raise FutureCompetitionNotReady("Tokai future fixture dates changed")
        annual = AnnualCompetitionInput(
            competition_id=cid, year=year, rng_seed=int(crow["rng_seed"]),
            entrant_school_ids=entrants,
            direct_main_entry_school_ids=direct,
            group_entrant_school_ids={
                gid: list(groups[gid]) for gid in sorted(groups)
            },
            main_seed_school_ids=[],
        )
        resolver = AbilityMatchResolver(
            repo, roster_provider=roster_archive.roster,
            team_generation_seed=career_seed,
            ability_config_dir=ability_config_dir,
            match_config_dir=match_config_dir,
        )
        resolver.begin_season(year, career_seed)
        scheduled = TournamentEngine(
            repo, pre_main_match_resolver=resolver,
            main_match_resolver=resolver,
        ).prepare_scheduled_competition_runtime(
            annual, cal, stage_date_lists={"BRANCH_QUALIFIER": qdays},
        )
        if scheduled.calendar_gap_match_ids:
            raise FutureCompetitionNotReady("Tokai initial group date gap")
        scheduled.competition_name = str(crow["display_name"])
        previews[cid] = FutureCompetitionPreview(
            year=year, competition_id=cid,
            competition_display_name=scheduled.competition_name,
            entry_source=SANDBOX_ENTRANTS, annual=annual, scheduled=scheduled,
        )
    return previews
