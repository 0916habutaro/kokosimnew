"""Stage 43G-5: direct-MAIN sandbox adapter for three Kanto prefectures.

Tochigi, Gunma and Yamanashi's 2026 graphs have MAIN only, with no
machine-verified future entrant count. Explicit sandbox cohorts are required.
A hypothetical 2027 entrant count is NEVER presented as a 2027 official fact.
"""
from __future__ import annotations

from math import ceil, log2
from pathlib import Path
from typing import Sequence

from game_core.tournament_bridge import AbilityMatchResolver

from .career_roster_archive import CareerRosterArchive
from .engine import TournamentEngine
from .future_competition_bridge import (
    FutureCompetitionNotReady,
    FutureCompetitionPreview,
    SANDBOX_ENTRANTS,
)
from .future_season_blueprint import build_future_season_blueprint
from .models import AnnualCompetitionInput
from .repository import DataRepository

DIRECT_MAIN_PREFECTURES = {
    "CMP000086": "09",  # Tochigi
    "CMP000088": "10",  # Gunma
    "CMP000105": "19",  # Yamanashi
}


def prepare_future_kanto_direct_main_preview(
    *, data_root: str | Path, year: int, competition_id: str,
    entrant_school_ids: Sequence[str], roster_archive: CareerRosterArchive,
    repo: DataRepository, base_seed: int, career_seed: int,
    ability_config_dir: str | Path = "config/abilities",
    match_config_dir: str | Path = "config/match",
    entry_source: str = SANDBOX_ENTRANTS,
) -> FutureCompetitionPreview:
    """Make a deterministic MAIN draw using an *explicit* annual sandbox cohort.

    It is not safe to infer the number of 2027 teams from an unconfirmed 2026
    team_count. This adapter has an explicit narrow competition whitelist.
    """
    if competition_id not in DIRECT_MAIN_PREFECTURES:
        raise FutureCompetitionNotReady("direct MAIN Kanto adapter not supported here")
    if entry_source != SANDBOX_ENTRANTS:
        raise FutureCompetitionNotReady("only explicit sandbox entrants supported")
    if not isinstance(year, int) or isinstance(year, bool) or not 2026 < year <= 9999:
        raise FutureCompetitionNotReady("invalid game year")
    for seed in (base_seed, career_seed):
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise FutureCompetitionNotReady("seeds must be integers")
    stages = repo.stages(competition_id)
    if len(stages) != 1 or stages[0]["stage_code"] != "MAIN":
        raise FutureCompetitionNotReady("future competition is not a direct MAIN")
    if repo.access_rules(competition_id):
        raise FutureCompetitionNotReady(
            "unverified future access rules cannot be skipped by direct MAIN"
        )
    base = repo.competition(competition_id)
    pcode = DIRECT_MAIN_PREFECTURES[competition_id]
    if (base["competition_type"] != "spring_prefectural"
            or base["season_segment"] != "spring"
            or base["prefecture_code"] != pcode):
        raise FutureCompetitionNotReady("unexpected prefectural MAIN structure")
    entrants = list(entrant_school_ids)
    if (len(entrants) < 4 or len(entrants) != len(set(entrants))
            or any(not isinstance(s, str) or not s for s in entrants)):
        raise FutureCompetitionNotReady(
            "direct MAIN requires four or more unique named sandbox schools"
        )
    if any(sid not in repo.school_to_program for sid in entrants):
        raise FutureCompetitionNotReady("unknown or non-hardball school")
    if any(repo.schools[sid]["prefecture_code"] != pcode for sid in entrants):
        raise FutureCompetitionNotReady("entrant outside destination prefecture")
    # The 2026 source is a structural model only, not a 2027 source of truth.
    blueprint = build_future_season_blueprint(
        data_root, year=year, base_seed=base_seed,
    )
    if (blueprint.get("official_calendar") is not False
            or blueprint.get("live_runtime_ready") is not False):
        raise FutureCompetitionNotReady("not a fictional game calendar")
    comp = [x for x in blueprint["competitions"]
            if x["competition_id"] == competition_id]
    cal = [x for x in blueprint["calendars"]
           if x["competition_id"] == competition_id]
    if len(comp) != 1 or len(cal) != 1:
        raise FutureCompetitionNotReady("missing or repeated projected competition")
    event, calendar = comp[0], cal[0]
    if (event["reference_year"] != year
            or event["structure_status"] != "requires_future_year_validation"
            or event["participant_status"] != "unresolved"
            or calendar["year"] != year
            or calendar["date_source"] != "game_projection_v1"
            or calendar["calendar_status"] != "provisional_game_schedule"
            or calendar["real_world_verified"] is not False):
        raise FutureCompetitionNotReady("future sandbox provenance mismatch")
    days = [x for x in calendar["game_date_list"].split(";") if x]
    if len(days) < ceil(log2(len(entrants))) or days != sorted(set(days)):
        raise FutureCompetitionNotReady("MAIN projected calendar insufficient")
    if any(not day.startswith(f"{year}-") for day in days):
        raise FutureCompetitionNotReady("projected game day outside requested year")

    for sid in entrants:
        roster = roster_archive.roster(year, sid)
        if (roster is None or roster.reference_year != year
                or roster.school_id != sid or roster.rng_seed != career_seed
                or roster.cohort_policy != "career_v1"):
            raise FutureCompetitionNotReady(
                f"missing saved career roster for {year}/{sid}"
            )
    resolver = AbilityMatchResolver(
        repo, roster_provider=roster_archive.roster,
        team_generation_seed=career_seed,
        ability_config_dir=ability_config_dir,
        match_config_dir=match_config_dir,
    )
    resolver.begin_season(year, career_seed)
    annual = AnnualCompetitionInput(
        competition_id=competition_id, year=year,
        rng_seed=int(event["rng_seed"]), entrant_school_ids=entrants,
        main_seed_school_ids=[],
    )
    engine = TournamentEngine(
        repo, pre_main_match_resolver=resolver, main_match_resolver=resolver,
    )
    scheduled = engine.prepare_scheduled_competition_runtime(annual, calendar)
    if scheduled.calendar_gap_match_ids:
        raise FutureCompetitionNotReady("game MAIN date has a calendar gap")
    scheduled.competition_name = str(event["display_name"])
    return FutureCompetitionPreview(
        year=year, competition_id=competition_id,
        competition_display_name=scheduled.competition_name,
        entry_source=entry_source, annual=annual, scheduled=scheduled,
    )
