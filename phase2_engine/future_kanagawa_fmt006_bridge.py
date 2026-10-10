"""Stage 43G-9: Kanagawa FMT006 spring qualifier with verified Senbatsu access.

Future years are explicitly sandbox projections of the 2026 structures.
No missing selection, district membership or actual future date is inferred.
"""
from __future__ import annotations

from math import ceil, log2
from pathlib import Path
from typing import Mapping, Sequence

from game_core.tournament_bridge import AbilityMatchResolver

from .engine import TournamentEngine
from .future_competition_bridge import (
    FutureCompetitionPreview, FutureCompetitionNotReady,
    SANDBOX_ENTRANTS, PROJECTED_DATES,
)
from .future_qualifier_bridge import _projected_days
from .future_season_blueprint import build_future_season_blueprint
from .models import AnnualCompetitionInput
from .premain_runtime_fmt006 import Fmt006QualifierGroupRuntime
from .repository import DataRepository

TARGET = "CMP000095"
EXPECTED_GROUP_SLOTS = (23, 23, 18, 17)


def prepare_future_kanagawa_spring_preview(
    *, data_root: str | Path, year: int, entrant_school_ids: Sequence[str],
    group_entrant_school_ids: Mapping[str, Sequence[str]],
    invitation_audit: Mapping[str, object],
    roster_archive, repo: DataRepository, base_seed: int, career_seed: int,
    ability_config_dir: str | Path = "config/abilities",
    match_config_dir: str | Path = "config/match",
    entry_source: str = SANDBOX_ENTRANTS,
) -> FutureCompetitionPreview:
    if entry_source != SANDBOX_ENTRANTS:
        raise FutureCompetitionNotReady("only sandbox entrants supported")
    if not isinstance(year, int) or isinstance(year, bool) or not 2026 < year <= 9999:
        raise FutureCompetitionNotReady("invalid game year")
    if any(not isinstance(x, int) or isinstance(x, bool)
           for x in (base_seed, career_seed)):
        raise FutureCompetitionNotReady("invalid seeds")
    if (invitation_audit.get("status") != "complete_same_year_sandbox_participant_manifest"
            or invitation_audit.get("game_participant_manifest_verified") is not True
            or invitation_audit.get("year") != year
            or invitation_audit.get("source_year") != year
            or invitation_audit.get("source_competition_id") != "CMP000001"
            or invitation_audit.get("source_school_count") != 32
            or invitation_audit.get("access_rule_id") != "ACR000008"
            or invitation_audit.get("future_official_participants_confirmed") is not False
            or invitation_audit.get("main_seed_school_ids") != []
            or not invitation_audit.get("source_manifest_sha256")):
        raise FutureCompetitionNotReady("verified same-year Senbatsu manifest required")

    direct = invitation_audit.get("direct_main_school_ids")
    if (not isinstance(direct, list)
            or len(direct) != len(set(direct))
            or not all(isinstance(s, str) and s for s in direct)):
        raise FutureCompetitionNotReady("invalid Senbatsu direct entrant set")
    if set(direct) != set(invitation_audit.get("preliminary_exempt_school_ids", [])):
        raise FutureCompetitionNotReady("Senbatsu direct entry / exemption mismatch")
    source = repo.competition(TARGET)
    if (source.get("prefecture_code") != "14"
            or source.get("competition_type") != "spring_prefectural"
            or source.get("season_segment") != "spring"):
        raise FutureCompetitionNotReady("Kanagawa source graph changed")
    stages = repo.stages(TARGET)
    if len(stages) != 2 or {s["stage_code"] for s in stages} != {
        "BRANCH_QUALIFIER", "MAIN"
    }:
        raise FutureCompetitionNotReady("Kanagawa stage graph changed")
    qualifier = next(s for s in stages if s["stage_code"] == "BRANCH_QUALIFIER")
    fmt = repo.assignments_by_stage.get(qualifier["stage_id"], {})
    if fmt.get("default_format_model_id") != "FMT006":
        raise FutureCompetitionNotReady("Kanagawa requires FMT006 league+playoff")
    groups = sorted(repo.groups_by_stage[qualifier["stage_id"]],
                    key=lambda g: int(g["group_order"]))
    if (len(groups) != 4 or tuple(int(g["advance_slots_to_next"]) for g in groups)
            != EXPECTED_GROUP_SLOTS):
        raise FutureCompetitionNotReady("Kanagawa four-region quota graph changed")
    for g in groups:
        override = repo.group_format.get(g["stage_group_id"], {})
        if override.get("format_model_id", "FMT006") not in ("", "FMT006"):
            raise FutureCompetitionNotReady("unsupported mixed FMT006 region")
        slots = repo.param(qualifier["stage_id"], "output_slots",
                           g["stage_group_id"], int(g["advance_slots_to_next"]))
        if slots != int(g["advance_slots_to_next"]):
            raise FutureCompetitionNotReady("Kanagawa output quota changed")

    entrants = list(entrant_school_ids)
    if (not entrants or len(entrants) != len(set(entrants))
            or any(not isinstance(s, str) or not s
                   or s not in repo.school_to_program
                   or repo.schools[s]["prefecture_code"] != "14"
                   for s in entrants)):
        raise FutureCompetitionNotReady("invalid Kanagawa hardball entrants")
    if not set(direct).issubset(entrants):
        raise FutureCompetitionNotReady("Senbatsu schools missing from spring entrants")
    expected_groups = {g["stage_group_id"] for g in groups}
    supplied = dict(group_entrant_school_ids)
    if set(supplied) != expected_groups:
        raise FutureCompetitionNotReady("four exact annual districts must be supplied")
    all_qualifier = []
    for g in groups:
        gid = g["stage_group_id"]
        member = supplied[gid]
        if not isinstance(member, (list, tuple)):
            raise FutureCompetitionNotReady("invalid annual district list")
        if len(member) != len(set(member)):
            raise FutureCompetitionNotReady("duplicated school within district")
        try:
            Fmt006QualifierGroupRuntime._solve_3_or_4_pool_plan(
                len(member), int(g["advance_slots_to_next"]),
            )
        except ValueError as exc:
            raise FutureCompetitionNotReady(
                f"{gid}: no valid FMT006 3/4 school pool for required quota"
            ) from exc
        all_qualifier.extend(member)
    if (len(all_qualifier) != len(set(all_qualifier))
            or set(all_qualifier) != set(entrants) - set(direct)):
        raise FutureCompetitionNotReady(
            "all non-recommended schools must belong to exactly one district"
        )

    blueprint = build_future_season_blueprint(
        data_root, year=year, base_seed=base_seed,
    )
    events = [x for x in blueprint["competitions"] if x["competition_id"] == TARGET]
    calendars = [x for x in blueprint["calendars"] if x["competition_id"] == TARGET]
    stagecal = [x for x in blueprint["stage_calendars"] if x["competition_id"] == TARGET]
    if (len(events) != 1 or len(calendars) != 1 or len(stagecal) != 1
            or blueprint.get("live_runtime_ready") is not False
            or blueprint.get("official_calendar") is not False):
        raise FutureCompetitionNotReady("unverified game season blueprint")
    event, cal, qual_cal = events[0], calendars[0], stagecal[0]
    if (event.get("reference_year") != year
            or event.get("participant_status") != "unresolved"
            or cal.get("real_world_verified") is not False
            or cal.get("date_source") != PROJECTED_DATES
            or qual_cal.get("stage_id") != qualifier["stage_id"]
            or qual_cal.get("stage_code") != "BRANCH_QUALIFIER"
            or qual_cal.get("date_source") != PROJECTED_DATES
            or qual_cal.get("real_world_verified") is not False):
        raise FutureCompetitionNotReady("Kanagawa future schedule provenance differs")
    days = _projected_days(cal["game_date_list"], year, "MAIN")
    qdays = _projected_days(qual_cal["date_list"], year, "FMT006")
    if (qdays[-1] >= days[0] or len(qdays) < 4
            or len(days) < ceil(log2(sum(EXPECTED_GROUP_SLOTS) + len(direct)))):
        raise FutureCompetitionNotReady("FMT006 and MAIN projected days insufficient")

    for school in entrants:
        roster = roster_archive.roster(year, school)
        if (roster is None or roster.reference_year != year
                or roster.school_id != school or roster.rng_seed != career_seed
                or roster.cohort_policy != "career_v1"):
            raise FutureCompetitionNotReady(
                f"saved future roster missing/invalid: {school}"
            )
    resolver = AbilityMatchResolver(
        repo, roster_provider=roster_archive.roster,
        team_generation_seed=career_seed,
        ability_config_dir=ability_config_dir,
        match_config_dir=match_config_dir,
    )
    resolver.begin_season(year, career_seed)
    annual = AnnualCompetitionInput(
        competition_id=TARGET, year=year,
        rng_seed=int(event["rng_seed"]),
        entrant_school_ids=entrants,
        direct_main_entry_school_ids=list(direct),
        group_entrant_school_ids={
            gid: list(supplied[gid]) for gid in sorted(supplied)
        },
        main_seed_school_ids=[],
    )
    engine = TournamentEngine(
        repo, pre_main_match_resolver=resolver,
        main_match_resolver=resolver,
    )
    scheduled = engine.prepare_scheduled_competition_runtime(
        annual, cal, stage_date_lists={"BRANCH_QUALIFIER": qdays},
    )
    if scheduled.calendar_gap_match_ids:
        raise FutureCompetitionNotReady("Kanagawa initial FMT006 calendar gap")
    scheduled.competition_name = str(event["display_name"])
    return FutureCompetitionPreview(
        year=year, competition_id=TARGET,
        competition_display_name=scheduled.competition_name,
        entry_source=entry_source, annual=annual, scheduled=scheduled,
    )
