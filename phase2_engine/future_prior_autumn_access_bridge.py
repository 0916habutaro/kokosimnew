"""Stage 43F-5: apply verified prior-autumn top-N bypass to a future MAIN.

This opt-in bridge uses only a *sealed* previous-year game archive and an
explicit sandbox entrant/group roster. It never infers real 2027 entrants,
district membership, committee decisions, or unverified seed orders.
"""
from __future__ import annotations

from math import ceil, log2
from pathlib import Path
from typing import Mapping, Sequence

from game_core.tournament_bridge import AbilityMatchResolver

from .career_competition_outcomes import (
    CareerCompetitionOutcomes,
    build_future_blueprint_from_archive,
)
from .career_roster_archive import CareerRosterArchive
from .engine import TournamentEngine
from .future_competition_bridge import (
    FutureCompetitionNotReady,
    FutureCompetitionPreview,
    SANDBOX_ENTRANTS,
)
from .future_qualifier_bridge import _projected_days
from .historical_match_archive import HistoricalMatchArchive
from .models import AnnualCompetitionInput
from .repository import DataRepository


def _check_rule(repo: DataRepository, competition_id: str, year: int) -> dict:
    rules = repo.access_rules(competition_id)
    if len(rules) != 1:
        raise FutureCompetitionNotReady(
            "the target must have exactly one previous-autumn access rule"
        )
    rule = rules[0]
    if (
        rule.get("source_year_offset") != "-1"
        or rule.get("source_event_kind") != "autumn_prefectural"
        or rule.get("source_result_selector") != "top_n"
        or rule.get("action_type") not in {
            "grant_main_entry_bypass_branch_qualifier",
            "grant_main_entry_bypass_preliminary_qualifier",
        }
        or rule.get("grants_main_entry") != "yes"
        or rule.get("bypassed_stage_participation_policy")
           != "excluded_from_bypassed_stage"
        or rule.get("deduplicate_by_team") != "yes"
        or rule.get("automation_status") != "machine_resolvable"
    ):
        raise FutureCompetitionNotReady(
            "rule is not a verified previous-autumn direct MAIN bypass"
        )
    start = int(rule.get("effective_from_year") or 2026)
    end = int(rule["effective_to_year"]) if rule.get("effective_to_year") else None
    if year < start or (end is not None and year > end):
        raise FutureCompetitionNotReady("access rule outside effective years")
    if rule.get("seed_on_entry") not in ("no", "destination_policy"):
        raise FutureCompetitionNotReady(
            "source rank does not establish an automatic seed assignment"
        )
    # A linked MAIN seeding contract must have a separate, verified adapter.
    # Silently discarding such a rule would turn a protected seed into an
    # ordinary draw; guessing its rank from the previous autumn is no better.
    linked_seed_rules = [
        sr["seed_rule_id"] for sr in repo.seed_rules(competition_id)
        if sr.get("linked_access_rule_id") == rule["access_rule_id"]
        and int(sr.get("effective_from_year") or 2026) <= year
        and (
            not sr.get("effective_to_year")
            or year <= int(sr["effective_to_year"])
        )
    ]
    if linked_seed_rules:
        raise FutureCompetitionNotReady(
            "linked MAIN seed contract requires separate validation: "
            + ", ".join(sorted(linked_seed_rules))
        )
    return rule


def prepare_future_prior_autumn_bypass_preview(
    *,
    data_root: str | Path,
    year: int,
    competition_id: str,
    entrant_school_ids: Sequence[str],
    group_entrant_school_ids: Mapping[str, Sequence[str]],
    match_archive: HistoricalMatchArchive,
    roster_archive: CareerRosterArchive,
    repo: DataRepository,
    base_seed: int,
    career_seed: int,
    ability_config_dir: str | Path = "config/abilities",
    match_config_dir: str | Path = "config/match",
    entry_source: str = SANDBOX_ENTRANTS,
    prior_source_competition_id: str | None = None,
) -> FutureCompetitionPreview:
    """Connect archived qualified schools to FMT001 qualifier + MAIN.

    All non-direct competitors must be explicitly mapped to the year's
    groups. The previous game's top-N are *not* rerolled or allowed to
    consume qualifier slots. No seed is awarded without a separate
    destination seed contract.
    """
    if entry_source != SANDBOX_ENTRANTS:
        raise FutureCompetitionNotReady(
            "only explicitly specified sandbox participants are supported"
        )
    if not isinstance(year, int) or isinstance(year, bool) or not 2026 < year <= 9999:
        raise FutureCompetitionNotReady("invalid future year")
    if not isinstance(career_seed, int) or isinstance(career_seed, bool):
        raise FutureCompetitionNotReady("invalid career seed")
    if not isinstance(base_seed, int) or isinstance(base_seed, bool):
        raise FutureCompetitionNotReady("invalid tournament seed")
    rule = _check_rule(repo, competition_id, year)
    try:
        blueprint = build_future_blueprint_from_archive(
            data_root, year=year, base_seed=base_seed,
            match_archive=match_archive,
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise FutureCompetitionNotReady(
            "previous year game outcomes not sealed and verified"
        ) from exc
    matched = [
        r for r in blueprint["prior_autumn_access"]
        if r["destination_competition_id"] == competition_id
    ]
    if len(matched) != 1 or matched[0]["access_rule_id"] != rule["access_rule_id"]:
        raise FutureCompetitionNotReady("unexpected prior-autumn rule")
    result = matched[0]
    # The 2026 master has no Tokyo autumn-prefectural competition row.
    # Do not pretend its 64 prior-year MAIN entrants exist in that master.
    # An explicitly bound *sandbox* competition is permitted only when it
    # has its own completed MAIN outcome in the sealed prior-year game DB.
    if competition_id == "CMP000094":
        if (not isinstance(prior_source_competition_id, str)
                or not prior_source_competition_id.strip()
                or prior_source_competition_id == competition_id):
            raise FutureCompetitionNotReady(
                "Tokyo requires explicitly bound previous-autumn game competition"
            )
        try:
            verified = CareerCompetitionOutcomes(match_archive).previous_results(
                year - 1
            ).get(prior_source_competition_id)
        except (ValueError, KeyError) as exc:
            raise FutureCompetitionNotReady(
                "previous year game outcomes not sealed and verified"
            ) from exc
        if not verified or len(verified["ranked_school_ids"]) < 64:
            raise FutureCompetitionNotReady(
                "Tokyo autumn source must contain at least 64 verified schools"
            )
        direct = list(verified["ranked_school_ids"][:64])
    else:
        if prior_source_competition_id is not None:
            raise FutureCompetitionNotReady(
                "explicit prior source override is only for Tokyo sandbox"
            )
        if (result["status"] != "resolved"
                or result["source_year"] != year - 1
                or result["provenance"] != "previous_year_saved_game_result"):
            raise FutureCompetitionNotReady(
                "previous autumn qualification is not resolved from sealed games"
            )
        direct = result["school_ids"]
    target = int(rule.get("quota") or rule.get("observed_2026_count") or 0)
    if (target < 1 or len(direct) != target
            or not isinstance(direct, list)
            or len(set(direct)) != len(direct)):
        raise FutureCompetitionNotReady("invalid previous-autumn direct entrant count")
    if (rule.get("source_rank_from") != "1"
            or int(rule.get("source_rank_to") or 0) != target):
        raise FutureCompetitionNotReady("unsupported previous-autumn ranking range")

    comps = [c for c in blueprint["competitions"]
             if c["competition_id"] == competition_id]
    calendars = [c for c in blueprint["calendars"]
                 if c["competition_id"] == competition_id]
    stage_dates = [s for s in blueprint["stage_calendars"]
                   if s["competition_id"] == competition_id]
    if len(comps) != 1 or len(calendars) != 1 or len(stage_dates) != 1:
        raise FutureCompetitionNotReady("ambiguous future competition calendar")
    comp, cal = comps[0], calendars[0]
    if (blueprint["official_calendar"] is not False
            or blueprint["live_runtime_ready"] is not False
            or comp["reference_year"] != year
            or cal["year"] != year
            or cal.get("date_source") != "game_projection_v1"
            or cal.get("calendar_status") != "provisional_game_schedule"
            or cal.get("real_world_verified") is not False):
        raise FutureCompetitionNotReady("future game date provenance invalid")
    main_days = _projected_days(cal["game_date_list"], year, "MAIN")
    stages = repo.stages(competition_id)
    stage_kind = rule.get("bypass_stage_kind")
    stage_map = {
        "grant_main_entry_bypass_branch_qualifier": (
            "branch_qualifier", "BRANCH_QUALIFIER", {"FMT001", "FMT002"}
        ),
        "grant_main_entry_bypass_preliminary_qualifier": (
            "preliminary_qualifier", "PRELIMINARY_QUALIFIER", {"FMT001"}
        ),
    }
    kind, qualifier_code, allowed_formats = stage_map[rule["action_type"]]
    if stage_kind != kind or len(stages) != 2 or {
        r["stage_code"] for r in stages
    } != {qualifier_code, "MAIN"}:
        raise FutureCompetitionNotReady(
            "previous-autumn bypass stage mismatches qualifier -> MAIN graph"
        )
    qualifier = next(r for r in stages if r["stage_code"] == qualifier_code)
    assignment = repo.assignments_by_stage.get(qualifier["stage_id"], {})
    model = assignment.get("default_format_model_id")
    if model not in allowed_formats:
        raise FutureCompetitionNotReady(
            "unsupported future qualifier model for prior-autumn bypass"
        )
    if (model == "FMT002" and competition_id != "CMP000109") or (
        qualifier_code == "PRELIMINARY_QUALIFIER"
        and competition_id != "CMP000094"
    ):
        raise FutureCompetitionNotReady(
            "future composite/preliminary bypass needs a verified adapter"
        )
    stage = stage_dates[0]
    if (stage["stage_id"] != qualifier["stage_id"]
            or stage["stage_code"] != qualifier_code
            or stage["reference_year"] != year
            or stage["date_source"] != "game_projection_v1"
            or stage["date_status"] != "provisional_game_schedule"
            or stage["real_world_verified"] is not False):
        raise FutureCompetitionNotReady("qualifier date provenance invalid")
    qualifier_days = _projected_days(stage["date_list"], year, "qualifier")
    if qualifier_days[-1] >= main_days[0]:
        raise FutureCompetitionNotReady("qualifier must finish before MAIN")

    entrants = list(entrant_school_ids)
    if not entrants or len(entrants) != len(set(entrants)):
        raise FutureCompetitionNotReady("missing or duplicate competition entrants")
    if set(direct) - set(entrants):
        raise FutureCompetitionNotReady(
            "previous-autumn direct school must be in current entrants"
        )
    prefecture = rule["destination_prefecture_code"]
    base = repo.competition(competition_id)
    if not prefecture or base.get("prefecture_code") != prefecture:
        raise FutureCompetitionNotReady("destination prefecture not confirmed")
    if any(sid not in repo.school_to_program for sid in entrants):
        raise FutureCompetitionNotReady("unknown/non-hardball entrant school")
    if any(repo.schools[sid].get("prefecture_code") != prefecture
           for sid in entrants):
        raise FutureCompetitionNotReady("entrant outside destination prefecture")

    groups = repo.groups_by_stage.get(qualifier["stage_id"], [])
    known = {g["stage_group_id"]: g for g in groups}
    supplied = dict(group_entrant_school_ids)
    if not known or set(supplied) != set(known):
        raise FutureCompetitionNotReady(
            "all future branch group memberships must be supplied"
        )
    candidates: list[str] = []
    total_qualifier_slots = 0
    longest_group_rounds = 0
    for gid, group in known.items():
        model = (repo.group_format.get(gid, {}).get("format_model_id")
                 or assignment["default_format_model_id"])
        if model != assignment["default_format_model_id"]:
            raise FutureCompetitionNotReady("unsupported mixed qualifier group model")
        members = supplied[gid]
        if not isinstance(members, (list, tuple)) or not members:
            raise FutureCompetitionNotReady(
                f"{gid}: explicit non-direct entrants are required"
            )
        slots = repo.param(
            qualifier["stage_id"], "output_slots", gid,
            int(group.get("advance_slots_to_next") or 0),
        )
        if not isinstance(slots, int) or slots < 1 or len(members) < slots:
            raise FutureCompetitionNotReady(
                f"{gid}: insufficient group entrants for output quota"
            )
        total_qualifier_slots += slots
        longest_group_rounds = max(
            longest_group_rounds, ceil(log2(ceil(len(members) / slots)))
        )
        candidates.extend(members)
    if len(candidates) != len(set(candidates)) or set(candidates) != (
        set(entrants) - set(direct)
    ):
        raise FutureCompetitionNotReady(
            "branch groups must partition every non-direct school once"
        )
    if set(candidates) & set(direct):
        raise FutureCompetitionNotReady(
            "direct qualified schools cannot consume qualifier slots"
        )
    if len(qualifier_days) < longest_group_rounds:
        raise FutureCompetitionNotReady("insufficient qualifier dates")
    main_count = total_qualifier_slots + len(direct)
    if len(main_days) < ceil(log2(main_count)):
        raise FutureCompetitionNotReady("insufficient MAIN dates")
    if model == "FMT002" and len(qualifier_days) < 2:
        raise FutureCompetitionNotReady(
            "FMT002 primary/repechage needs at least two qualifier dates"
        )
    main_stage = next(r for r in stages if r["stage_code"] == "MAIN")
    # Tokyo's 47 qualifier blocks + 64 direct entrants is an explicit
    # 111-place structure. A partial or surplus draw must never be treated as
    # a verified 2027 promotion rule.
    if qualifier_code == "PRELIMINARY_QUALIFIER":
        expected = int(main_stage.get("team_count") or 0)
        if expected != 111 or main_count != expected or target != 64:
            raise FutureCompetitionNotReady(
                "Tokyo preliminary must supply 47 + 64 = 111 MAIN teams"
            )
    # School membership from 2026 is not reused to fill missing 2027 places.
    missing = []
    for sid in entrants:
        roster = roster_archive.roster(year, sid)
        if (roster is None or roster.school_id != sid
                or roster.reference_year != year
                or roster.rng_seed != career_seed
                or roster.cohort_policy != "career_v1"):
            missing.append(sid)
    if missing:
        raise FutureCompetitionNotReady(
            "missing next-year career rosters: " + ", ".join(missing[:8])
        )

    annual = AnnualCompetitionInput(
        competition_id=competition_id,
        year=year,
        rng_seed=int(comp["rng_seed"]),
        entrant_school_ids=entrants,
        direct_main_entry_school_ids=list(direct),
        group_entrant_school_ids={
            gid: list(supplied[gid]) for gid in sorted(supplied)
        },
        # "seed_on_entry=destination_policy" is NOT a known rank->seed rule;
        # it grants access only. Do not guess slot positions.
        main_seed_school_ids=[],
    )
    resolver = AbilityMatchResolver(
        repo, roster_provider=roster_archive.roster,
        team_generation_seed=career_seed,
        ability_config_dir=ability_config_dir,
        match_config_dir=match_config_dir,
    )
    resolver.begin_season(year, career_seed)
    engine = TournamentEngine(
        repo, pre_main_match_resolver=resolver, main_match_resolver=resolver,
    )
    scheduled = engine.prepare_scheduled_competition_runtime(
        annual, cal,
        stage_date_lists={qualifier_code: qualifier_days},
    )
    if scheduled.calendar_gap_match_ids:
        raise FutureCompetitionNotReady("initial qualifier calendar has gaps")
    scheduled.competition_name = str(comp["display_name"])
    return FutureCompetitionPreview(
        year=year,
        competition_id=competition_id,
        competition_display_name=scheduled.competition_name,
        entry_source=entry_source,
        annual=annual,
        scheduled=scheduled,
    )
