"""Stage 43F-2: opt-in *sandbox* bridge to a real future-year tournament.

Only a direct-MAIN competition with an explicitly supplied, fully archived
annual 20-player roster for EVERY participant can be started. This module
does not auto-select schools, imply official future fixtures, persist the
result, or enable a 2027 full season.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import ceil, log2
from typing import Mapping, Sequence

from game_core.tournament_bridge import AbilityMatchResolver

from .career_roster_archive import CareerRosterArchive
from .engine import TournamentEngine
from .models import AnnualCompetitionInput
from .repository import DataRepository


SANDBOX_ENTRANTS = "sandbox_manual_v1"
PROJECTED_DATES = "game_projection_v1"


class FutureCompetitionNotReady(ValueError):
    """Inputs are not sufficient to safely start this future-year preview."""


@dataclass
class FutureCompetitionPreview:
    """Uses the real TournamentEngine and ability scorer, never writes results."""

    year: int
    competition_id: str
    competition_display_name: str
    entry_source: str
    annual: AnnualCompetitionInput
    scheduled: object

    def snapshot(self) -> dict:
        return {
            "year": self.year,
            "competition_id": self.competition_id,
            "competition_display_name": self.competition_display_name,
            "entry_source": self.entry_source,
            "official_competition": False,
            "game_provenance": PROJECTED_DATES,
            "persistent_game_session": False,
            "year_rollover_implemented": False,
            "entrant_count": len(self.annual.entrant_school_ids),
            "schedule": self.scheduled.summary(),
        }

    def play_next_date(self) -> dict:
        """Run one ready wave on its provisional date, not a whole season."""
        scheduled_date = self.scheduled.next_scheduled_date()
        if not scheduled_date:
            raise FutureCompetitionNotReady(
                "no ready dated matches; examine calendar gaps or completion"
            )
        matches = self.scheduled.play_date(scheduled_date)
        return {
            "competition_id": self.competition_id,
            "year": self.year,
            "date": scheduled_date,
            "date_source": PROJECTED_DATES,
            "played_match_count": len(matches),
            "is_complete": self.scheduled.is_complete,
        }


def prepare_future_direct_main_preview(
    *,
    blueprint: Mapping[str, object],
    competition_id: str,
    entrant_school_ids: Sequence[str],
    roster_archive: CareerRosterArchive,
    repo: DataRepository,
    career_seed: int,
    ability_config_dir: str = "config/abilities",
    match_config_dir: str = "config/match",
    entry_source: str = SANDBOX_ENTRANTS,
) -> FutureCompetitionPreview:
    """Connect Stage43F's projection + Stage43E's roster to the live engine.

    This is an explicit opt-in sandbox, never the automatic 2027 career loop.
    Require exactly the expected MAIN entrants, an unambiguous known-school
    list, complete 2027 archived rosters and a provisional calendar with
    enough available days for the bracket's rounds. Missing data fails closed.
    """
    if entry_source != SANDBOX_ENTRANTS:
        raise FutureCompetitionNotReady(
            "only explicitly designated sandbox entrants are supported"
        )
    year = blueprint.get("year")
    if (not isinstance(year, int) or isinstance(year, bool)
            or not 2026 < year <= 9999):
        raise FutureCompetitionNotReady("invalid future year")
    if (blueprint.get("source_structure_year") != 2026
            or blueprint.get("provenance") != PROJECTED_DATES
            or blueprint.get("official_calendar") is not False
            or blueprint.get("live_runtime_ready") is not False):
        raise FutureCompetitionNotReady("invalid provisional blueprint provenance")
    if (not isinstance(career_seed, int)
            or isinstance(career_seed, bool)):
        raise FutureCompetitionNotReady("career_seed must be an integer")

    competitions = [
        row for row in blueprint.get("competitions", [])
        if row.get("competition_id") == competition_id
    ]
    calendars = [
        row for row in blueprint.get("calendars", [])
        if row.get("competition_id") == competition_id
    ]
    if len(competitions) != 1 or len(calendars) != 1:
        raise FutureCompetitionNotReady(
            "future competition and calendar must each be unique"
        )
    comp, calendar = competitions[0], calendars[0]
    base = repo.competition(competition_id)
    if (comp.get("reference_year") != year
            or comp.get("base_competition_id") != competition_id
            or comp.get("competition_type") != base["competition_type"]
            or comp.get("structure_status") != "requires_future_year_validation"
            or comp.get("draw_status") != "unresolved"
            or comp.get("participant_status") != "unresolved"):
        raise FutureCompetitionNotReady("future competition metadata mismatch")
    if (calendar.get("year") != year
            or calendar.get("date_source") != PROJECTED_DATES
            or calendar.get("calendar_status") != "provisional_game_schedule"
            or calendar.get("real_world_verified") is not False):
        raise FutureCompetitionNotReady("future calendar is not provisional")

    days = (calendar.get("game_date_list") or "").split(";")
    days = [x for x in days if x]
    if not days or days != sorted(set(days)):
        raise FutureCompetitionNotReady("future MAIN needs ordered distinct game days")
    try:
        parsed_days = [date.fromisoformat(d) for d in days]
    except ValueError as exc:
        raise FutureCompetitionNotReady("future calendar has malformed day") from exc
    if any(day.year != year for day in parsed_days):
        raise FutureCompetitionNotReady("future game days belong to wrong year")

    stages = repo.stages(competition_id)
    if len(stages) != 1 or stages[0]["stage_code"] != "MAIN":
        raise FutureCompetitionNotReady(
            "qualified pre-MAIN and dependency tournaments need separate wiring"
        )
    stage = stages[0]
    expected = int(stage.get("team_count") or 0)
    entrants = list(entrant_school_ids)
    if expected < 2 or len(entrants) != expected:
        raise FutureCompetitionNotReady(
            f"requires exactly {expected} explicitly entered schools"
        )
    # Lazy scheduling requires a *later* calendar date for each MAIN wave.
    if len(days) < ceil(log2(expected)):
        raise FutureCompetitionNotReady(
            "not enough future game days for every MAIN round"
        )
    if len(set(entrants)) != len(entrants):
        raise FutureCompetitionNotReady("duplicate future entrants")
    if any(sid not in repo.school_to_program for sid in entrants):
        raise FutureCompetitionNotReady("future entrants must be known hardball schools")
    if base.get("prefecture_code") and any(
        repo.schools[sid].get("prefecture_code") != base["prefecture_code"]
        for sid in entrants
    ):
        raise FutureCompetitionNotReady("school outside competition prefecture")

    # Do not convert a committee election or feeder result into an automatic
    # qualified team list. The caller alone supplies an explicit sandbox list.
    # All schools must have been explicitly advanced from their earlier saved
    # roster: re-rolling a 2027 roster would break permanent player identity.
    missing_rosters = []
    for sid in entrants:
        roster = roster_archive.roster(year, sid)
        if (roster is None
                or roster.school_id != sid
                or roster.reference_year != year
                or roster.rng_seed != career_seed
                or roster.cohort_policy != "career_v1"):
            missing_rosters.append(sid)
    if missing_rosters:
        raise FutureCompetitionNotReady(
            "future archived rosters missing/invalid: "
            + ", ".join(missing_rosters[:8])
        )

    resolver = AbilityMatchResolver(
        repo,
        roster_provider=roster_archive.roster,
        team_generation_seed=career_seed,
        ability_config_dir=ability_config_dir,
        match_config_dir=match_config_dir,
    )
    resolver.begin_season(year, career_seed)
    annual = AnnualCompetitionInput(
        competition_id=competition_id,
        year=year,
        entrant_school_ids=entrants,
        rng_seed=int(comp["rng_seed"]),
    )
    engine = TournamentEngine(
        repo, main_match_resolver=resolver,
        pre_main_match_resolver=resolver,
    )
    # The same Stage13E engine/scheduler will enforce ready rounds, dates and
    # A-type GameStats; no special winner generation is introduced.
    scheduled = engine.prepare_scheduled_competition_runtime(
        annual, calendar
    )
    if scheduled.calendar_gap_match_ids:
        raise FutureCompetitionNotReady(
            "insufficient projected game dates for first round"
        )
    # The repository name remains the verified 2026 title. Do not show it as
    # the actual title of an event in 2027.
    scheduled.competition_name = str(comp["display_name"])
    return FutureCompetitionPreview(
        year=year,
        competition_id=competition_id,
        competition_display_name=scheduled.competition_name,
        entry_source=entry_source,
        annual=annual,
        scheduled=scheduled,
    )
