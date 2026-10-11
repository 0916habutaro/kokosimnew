"""Stage43G-46: explicit Aomori 4-group FMT018-021 seed event -> MAIN.

All entrants, rosters and game dates here are game-only projections.
The 2026 seed-event area groups are only a structural validation source.
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
    PROJECTED_DATES, SANDBOX_ENTRANTS,
)
from .future_qualifier_bridge import _projected_days
from .future_season_blueprint import build_future_season_blueprint
from .models import AnnualCompetitionInput
from .repository import DataRepository


AOMORI_SPRING = "CMP000072"
SEED_FORMATS = {"FMT018", "FMT019", "FMT020", "FMT021"}


def prepare_future_aomori_seed_main_preview(
    *, data_root: str | Path, year: int,
    entrant_school_ids: Sequence[str],
    group_entrant_school_ids: Mapping[str, Sequence[str]],
    roster_archive: CareerRosterArchive, repo: DataRepository,
    base_seed: int, career_seed: int,
    ability_config_dir: str | Path = "config/abilities",
    match_config_dir: str | Path = "config/match",
    entry_source: str = SANDBOX_ENTRANTS,
) -> FutureCompetitionPreview:
    """Run the seed-only graph; all entrants continue to the MAIN draw.

    FMT018-021 decide protection/seed positions, *not* who qualifies for
    the prefectural MAIN. Require a complete explicit group partition.
    """
    if entry_source != SANDBOX_ENTRANTS:
        raise FutureCompetitionNotReady("only explicit sandbox entrants allowed")
    if type(year) is not int or not 2026 < year <= 9999:
        raise FutureCompetitionNotReady("future Aomori year invalid")
    if any(type(seed) is not int for seed in (base_seed, career_seed)):
        raise FutureCompetitionNotReady("future Aomori seeds must be integers")
    stages = repo.stages(AOMORI_SPRING)
    if (len(stages) != 2
            or {s["stage_code"] for s in stages} != {"SEED_EVENT", "MAIN"}):
        raise FutureCompetitionNotReady("Aomori must have SEED_EVENT -> MAIN")
    seed_stage = next(s for s in stages if s["stage_code"] == "SEED_EVENT")
    assign = repo.assignments_by_stage.get(seed_stage["stage_id"], {})
    if assign.get("default_format_model_id") != "FMT018":
        raise FutureCompetitionNotReady("Aomori seed format changed")
    if repo.access_rules(AOMORI_SPRING):
        raise FutureCompetitionNotReady("Aomori external entry rules unresolved")
    base = repo.competition(AOMORI_SPRING)
    if (base.get("competition_type") != "spring_prefectural"
            or base.get("prefecture_code") != "02"):
        raise FutureCompetitionNotReady("source Aomori competition changed")
    groups = repo.groups_by_stage[seed_stage["stage_id"]]
    if len(groups) != 4 or set(group_entrant_school_ids) != {
        g["stage_group_id"] for g in groups
    }:
        raise FutureCompetitionNotReady("four Aomori seed groups required")
    entrants = list(entrant_school_ids)
    if (len(entrants) < 16 or len(entrants) != len(set(entrants))
            or any(type(s) is not str
                   or s not in repo.school_to_program
                   or repo.schools[s].get("prefecture_code") != "02"
                   for s in entrants)):
        raise FutureCompetitionNotReady("invalid Aomori 2027 explicit school IDs")
    assigned = []
    manifest = {}
    for group in groups:
        gid = group["stage_group_id"]
        members = list(group_entrant_school_ids[gid])
        model = repo.group_format[gid]["format_model_id"]
        quota = repo.param(seed_stage["stage_id"], "output_slots", gid, 4)
        if (model not in SEED_FORMATS or quota != 4
                or len(members) < quota + 1
                or len(members) != len(set(members))
                or any(s not in repo.group_school_ids(group, 2026)
                       for s in members)):
            raise FutureCompetitionNotReady(
                f"{gid}: group seed model, quota or membership invalid"
            )
        assigned.extend(members)
        manifest[gid] = members
    if len(assigned) != len(set(assigned)) or set(assigned) != set(entrants):
        raise FutureCompetitionNotReady(
            "seed groups must partition explicit Aomori school IDs"
        )

    blueprint = build_future_season_blueprint(
        data_root, year=year, base_seed=base_seed,
    )
    if (blueprint.get("source_structure_year") != 2026
            or blueprint.get("official_calendar") is not False
            or blueprint.get("provenance") != PROJECTED_DATES):
        raise FutureCompetitionNotReady("Aomori future provenance invalid")
    comp = [
        row for row in blueprint["competitions"]
        if row["competition_id"] == AOMORI_SPRING
    ]
    cal = [
        row for row in blueprint["calendars"]
        if row["competition_id"] == AOMORI_SPRING
    ]
    stage_rows = [
        row for row in blueprint["stage_calendars"]
        if row["competition_id"] == AOMORI_SPRING
        and row["stage_code"] == "SEED_EVENT"
    ]
    if len(comp) != 1 or len(cal) != 1 or len(stage_rows) != 1:
        raise FutureCompetitionNotReady("Aomori future calendars incomplete")
    c, calendar, seed_calendar = comp[0], cal[0], stage_rows[0]
    if (calendar["real_world_verified"] is not False
            or seed_calendar["real_world_verified"] is not False
            or calendar["date_source"] != PROJECTED_DATES
            or seed_calendar["date_source"] != PROJECTED_DATES
            or c["reference_year"] != year):
        raise FutureCompetitionNotReady("Aomori projected date proof changed")
    seed_days = _projected_days(
        seed_calendar["date_list"], year, "Aomori seed event",
    )
    main_days = _projected_days(
        calendar["game_date_list"], year, "Aomori prefectural MAIN",
    )
    if (seed_days[-1] >= main_days[0]
            or len(main_days) < ceil(log2(len(entrants)))):
        raise FutureCompetitionNotReady("seed/M MAIN game schedule is not feasible")
    for sid in entrants:
        roster = roster_archive.roster(year, sid)
        if (roster is None or roster.school_id != sid
                or roster.reference_year != year
                or roster.rng_seed != career_seed
                or roster.cohort_policy != "career_v1"):
            raise FutureCompetitionNotReady(
                "Aomori archived career roster missing or changed"
            )
    resolver = AbilityMatchResolver(
        repo, roster_provider=roster_archive.roster,
        team_generation_seed=career_seed,
        ability_config_dir=ability_config_dir,
        match_config_dir=match_config_dir,
    )
    resolver.begin_season(year, career_seed)
    annual = AnnualCompetitionInput(
        competition_id=AOMORI_SPRING, year=year,
        entrant_school_ids=entrants,
        group_entrant_school_ids=manifest,
        rng_seed=int(c["rng_seed"]),
    )
    scheduled = TournamentEngine(
        repo, pre_main_match_resolver=resolver,
        main_match_resolver=resolver,
    ).prepare_scheduled_competition_runtime(
        annual, calendar, stage_date_lists={"SEED_EVENT": seed_days},
    )
    if scheduled.calendar_gap_match_ids:
        raise FutureCompetitionNotReady("Aomori seed-event calendar gap")
    scheduled.competition_name = str(c["display_name"])
    return FutureCompetitionPreview(
        year=year, competition_id=AOMORI_SPRING,
        competition_display_name=scheduled.competition_name,
        entry_source=entry_source, annual=annual, scheduled=scheduled,
    )
