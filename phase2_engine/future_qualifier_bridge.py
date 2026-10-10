"""Stage 43F-3: opt-in future-year FMT001 qualifier -> MAIN sandbox.

Connects explicit *game-only* school-to-qualifier-group memberships and
Stage43E saved player rosters to the existing Stage13E lazy engine.

No future official school affiliation, entrants, direct entry, committee
selection, annual results or career save is inferred by this module.
"""
from __future__ import annotations

from datetime import date
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
from .models import AnnualCompetitionInput
from .repository import DataRepository


def _projected_days(value: str, year: int, label: str) -> list[str]:
    if not isinstance(value, str):
        raise FutureCompetitionNotReady(f"{label}: invalid date list")
    dates = [d for d in value.split(";") if d]
    if not dates or dates != sorted(set(dates)):
        raise FutureCompetitionNotReady(
            f"{label}: missing, duplicate or unsorted projected dates"
        )
    try:
        parsed = [date.fromisoformat(d) for d in dates]
    except ValueError as exc:
        raise FutureCompetitionNotReady(f"{label}: invalid game date") from exc
    if any(d.year != year for d in parsed):
        raise FutureCompetitionNotReady(
            f"{label}: projected dates belong to wrong year"
        )
    return dates


def prepare_future_fmt001_qualifier_preview(
    *,
    blueprint: Mapping[str, object],
    competition_id: str,
    entrant_school_ids: Sequence[str],
    group_entrant_school_ids: Mapping[str, Sequence[str]],
    roster_archive: CareerRosterArchive,
    repo: DataRepository,
    career_seed: int,
    ability_config_dir: str | Path = "config/abilities",
    match_config_dir: str | Path = "config/match",
    entry_source: str = SANDBOX_ENTRANTS,
) -> FutureCompetitionPreview:
    """Run only a fully supplied FMT001 group-qualifier and MAIN preview.

    Group memberships MUST be passed by the caller as sandbox values.
    Ordinary 2026 school_area_memberships have no authority for 2027.
    """
    if entry_source != SANDBOX_ENTRANTS:
        raise FutureCompetitionNotReady("only sandbox manually entered schools are allowed")
    year = blueprint.get("year")
    if not isinstance(year, int) or isinstance(year, bool) or not 2026 < year <= 9999:
        raise FutureCompetitionNotReady("future competition requires year 2027-9999")
    if (blueprint.get("source_structure_year") != 2026
            or blueprint.get("provenance") != PROJECTED_DATES
            or blueprint.get("official_calendar") is not False
            or blueprint.get("live_runtime_ready") is not False):
        raise FutureCompetitionNotReady("invalid future blueprint provenance")
    if not isinstance(career_seed, int) or isinstance(career_seed, bool):
        raise FutureCompetitionNotReady("career_seed must be integer")

    entries = [
        c for c in blueprint.get("competitions", [])
        if c.get("competition_id") == competition_id
    ]
    calendars = [
        c for c in blueprint.get("calendars", [])
        if c.get("competition_id") == competition_id
    ]
    if len(entries) != 1 or len(calendars) != 1:
        raise FutureCompetitionNotReady("missing or duplicated future competition/calendar")
    comp, calendar = entries[0], calendars[0]
    base = repo.competition(competition_id)
    if (comp.get("reference_year") != year
            or comp.get("base_competition_id") != competition_id
            or comp.get("competition_type") != base.get("competition_type")
            or comp.get("structure_status") != "requires_future_year_validation"
            or comp.get("participant_status") != "unresolved"
            or comp.get("draw_status") != "unresolved"):
        raise FutureCompetitionNotReady("future competition metadata mismatch")
    if (calendar.get("year") != year
            or calendar.get("date_source") != PROJECTED_DATES
            or calendar.get("calendar_status") != "provisional_game_schedule"
            or calendar.get("real_world_verified") is not False):
        raise FutureCompetitionNotReady("future calendar is not provisional")
    main_days = _projected_days(
        calendar.get("game_date_list"), year, "MAIN calendar",
    )

    stages = repo.stages(competition_id)
    if len(stages) != 2 or {s["stage_code"] for s in stages} != {
        "BRANCH_QUALIFIER", "MAIN",
    }:
        raise FutureCompetitionNotReady(
            "only BRANCH_QUALIFIER -> MAIN two-stage graph is supported"
        )
    qualifier_stage = next(s for s in stages if s["stage_code"] == "BRANCH_QUALIFIER")
    main_stage = next(s for s in stages if s["stage_code"] == "MAIN")
    assignment = repo.assignments_by_stage.get(qualifier_stage["stage_id"], {})
    if assignment.get("default_format_model_id") != "FMT001":
        raise FutureCompetitionNotReady("only FMT001 group qualifier is supported")
    if repo.access_rules(competition_id):
        raise FutureCompetitionNotReady(
            "external access/direct-entry rules require actual results"
        )

    stage_rows = [
        row for row in blueprint.get("stage_calendars", [])
        if row.get("competition_id") == competition_id
    ]
    if len(stage_rows) != 1:
        raise FutureCompetitionNotReady("qualifier stage calendar missing/duplicated")
    stage_row = stage_rows[0]
    if (stage_row.get("reference_year") != year
            or stage_row.get("stage_id") != qualifier_stage["stage_id"]
            or stage_row.get("stage_code") != qualifier_stage["stage_code"]
            or stage_row.get("date_source") != PROJECTED_DATES
            or stage_row.get("date_status") != "provisional_game_schedule"
            or stage_row.get("real_world_verified") is not False):
        raise FutureCompetitionNotReady("qualifier stage calendar is not provisional")
    qualifier_days = _projected_days(
        stage_row.get("date_list"), year, "qualifier calendar",
    )
    if qualifier_days[-1] >= main_days[0]:
        raise FutureCompetitionNotReady(
            "qualifier must finish before MAIN provisional game dates"
        )

    groups = repo.groups_by_stage.get(qualifier_stage["stage_id"], [])
    known_groups = {g["stage_group_id"]: g for g in groups}
    supplied = dict(group_entrant_school_ids)
    if not known_groups or set(supplied) != set(known_groups):
        raise FutureCompetitionNotReady(
            "all qualifier groups require explicit sandbox memberships"
        )
    entrants = list(entrant_school_ids)
    if not entrants or len(entrants) != len(set(entrants)):
        raise FutureCompetitionNotReady("missing or duplicate competition entrants")
    if any(sid not in repo.school_to_program for sid in entrants):
        raise FutureCompetitionNotReady("unknown/non-hardball school in entrants")
    pcode = base.get("prefecture_code")
    if not pcode and base.get("region_id") == "REG01":
        # The 2026 Hokkaido region (REG01) is one prefecture in the
        # source master, but regional tournaments leave prefecture_code
        # blank. It must not silently admit a school from another region.
        pcode = "01"
    if not pcode:
        raise FutureCompetitionNotReady(
            "regional entrant eligibility is not verified for this competition"
        )
    if any(
        repo.schools[sid].get("prefecture_code") != pcode for sid in entrants
    ):
        raise FutureCompetitionNotReady("entrant outside competition prefecture")

    all_members: list[str] = []
    total_output_slots = 0
    required_qualifier_waves = 0
    for group_id, group in known_groups.items():
        if (repo.group_format.get(group_id, {}).get("format_model_id") or
                assignment["default_format_model_id"]) != "FMT001":
            raise FutureCompetitionNotReady("qualifier group has unsupported model")
        members = supplied[group_id]
        if not isinstance(members, (list, tuple)) or not members:
            raise FutureCompetitionNotReady(
                f"{group_id}: explicit sandbox school list required"
            )
        if any(not isinstance(sid, str) or not sid for sid in members):
            raise FutureCompetitionNotReady(f"{group_id}: invalid school ID")
        slots = repo.param(
            qualifier_stage["stage_id"], "output_slots", group_id,
            int(group.get("advance_slots_to_next") or
                group.get("qualifier_slots_generated") or 0),
        )
        if not isinstance(slots, int) or slots < 1 or len(members) < slots:
            raise FutureCompetitionNotReady(
                f"{group_id}: insufficient school count for qualification slots"
            )
        total_output_slots += slots
        required_qualifier_waves = max(
            required_qualifier_waves, ceil(log2(ceil(len(members) / slots)))
        )
        all_members.extend(members)
    if (len(all_members) != len(set(all_members))
            or set(all_members) != set(entrants)
            or len(all_members) != len(entrants)):
        raise FutureCompetitionNotReady(
            "group memberships must partition every entrant exactly once"
        )

    expected_main = int(main_stage.get("team_count") or 0)
    if total_output_slots != expected_main or expected_main < 2:
        raise FutureCompetitionNotReady(
            "qualifier output slots do not match MAIN entrant count"
        )
    if len(qualifier_days) < required_qualifier_waves:
        raise FutureCompetitionNotReady(
            "insufficient qualifier days for all group rounds"
        )
    if len(main_days) < ceil(log2(total_output_slots)):
        raise FutureCompetitionNotReady(
            "insufficient MAIN days for all rounds"
        )

    missing = []
    for sid in entrants:
        roster = roster_archive.roster(year, sid)
        if (roster is None or roster.reference_year != year
                or roster.school_id != sid or roster.rng_seed != career_seed
                or roster.cohort_policy != "career_v1"):
            missing.append(sid)
    if missing:
        raise FutureCompetitionNotReady(
            "saved career rosters missing for: " + ", ".join(missing[:8])
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
        group_entrant_school_ids={
            gid: list(supplied[gid]) for gid in sorted(supplied)
        },
    )
    engine = TournamentEngine(
        repo, pre_main_match_resolver=resolver, main_match_resolver=resolver,
    )
    # The existing staged runtime owns representatives; no qualifying winners
    # are preselected by this bridge. Provisional calendars are not official.
    scheduled = engine.prepare_scheduled_competition_runtime(
        annual, calendar,
        stage_date_lists={qualifier_stage["stage_code"]: qualifier_days},
    )
    if scheduled.calendar_gap_match_ids:
        raise FutureCompetitionNotReady("qualifier runtime calendar gap")
    scheduled.competition_name = str(comp["display_name"])
    return FutureCompetitionPreview(
        year=year,
        competition_id=competition_id,
        competition_display_name=scheduled.competition_name,
        entry_source=entry_source,
        annual=annual,
        scheduled=scheduled,
    )
