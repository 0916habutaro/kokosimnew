"""Stage43G-42: same-year Senbatsu -> Hokkaido spring recommendation gate.

A *completed*, saved Senbatsu game and every archived MAIN match are the
evidence for who was an actual (fictional) Senbatsu entrant in that year.
One completed game, an arbitrary school list, or previous year's Senbatsu is
not evidence. The archive year is usually still active in March, so do not
require sealing the whole year before Hokkaido spring.

This read-only verifier does not automatically enroll a spring competition
in an existing multi-event checkpoint. It provides a ready-to-run preview
AFTER a same-year Senbatsu completes; durable dependent-event save scheduling
remains a separate contract.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Mapping, Sequence

from game_core.tournament_bridge import AbilityMatchResolver

from .career_competition_outcomes import _main_result, _canonical
from .career_option_a_storage_profile import _read_only
from .career_roster_archive import CareerRosterArchive
from .engine import TournamentEngine
from .future_competition_bridge import (
    FutureCompetitionNotReady, FutureCompetitionPreview,
    SANDBOX_ENTRANTS,
)
from .future_qualifier_bridge import _projected_days
from .future_season_blueprint import build_future_season_blueprint
from .historical_match_archive import HistoricalMatchArchive
from .models import AnnualCompetitionInput, CompetitionRun
from .repository import DataRepository

SENBATSU_ID = "CMP000001"
SPRING_HOKKAIDO_ID = "CMP000004"
ACCESS_RULE_ID = "ACR000001"


class HokkaidoRecommendationNotReady(FutureCompetitionNotReady):
    """No complete, verified, same-year saved Senbatsu participation evidence."""


def _rule(repo: DataRepository) -> dict:
    rules = repo.access_rules(SPRING_HOKKAIDO_ID)
    if (len(rules) != 1 or rules[0].get("access_rule_id") != ACCESS_RULE_ID):
        raise HokkaidoRecommendationNotReady("Hokkaido spring access rule not unique")
    rule = rules[0]
    required = {
        "source_year_offset": "0",
        "source_event_kind": "national_invitational",
        "source_competition_id_2026": SENBATSU_ID,
        "source_result_selector": "participant_from_destination_prefecture",
        "destination_prefecture_code": "01",
        "action_type": "grant_main_entry_bypass_branch_qualifier",
        "bypassed_stage_participation_policy":
            "allowed_without_qualification_effect",
        "grants_main_entry": "yes",
        "deduplicate_by_team": "yes",
        "automation_status": "machine_resolvable",
    }
    if any(rule.get(k) != v for k, v in required.items()):
        raise HokkaidoRecommendationNotReady(
            "Hokkaido spring Senbatsu recommendation contract changed"
        )
    return rule


def certify_saved_senbatsu_hokkaido(
    repo: DataRepository, archive: HistoricalMatchArchive,
    run: CompetitionRun, *, year: int,
) -> dict:
    """Check every source game row and its SHA without writing the active year."""
    if (type(year) is not int or not 2026 < year <= 9999
            or run.year != year or run.competition_id != SENBATSU_ID):
        raise HokkaidoRecommendationNotReady("same-year Senbatsu run required")
    rule = _rule(repo)
    if not archive.db_path.is_file():
        raise HokkaidoRecommendationNotReady("same-year game archive absent")
    try:
        outcome, matches = _main_result(run)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HokkaidoRecommendationNotReady(
            "Senbatsu final and every bracket game must be completed"
        ) from exc
    all_teams = outcome["main_entrant_school_ids"]
    if (len(all_teams) != 32 or len(matches) != 31
            or any(sid not in repo.school_to_program for sid in all_teams)):
        raise HokkaidoRecommendationNotReady(
            "Senbatsu needs 32 real master IDs and all 31 completed games"
        )
    recommendation = [
        sid for sid in all_teams
        if repo.schools[sid]["prefecture_code"] == "01"
    ]

    try:
        with closing(_read_only(archive.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            metadata = conn.execute(
                "SELECT status FROM career_years WHERE year=?", (year,),
            ).fetchone()
            if metadata is None or metadata["status"] not in ("active", "sealed"):
                raise HokkaidoRecommendationNotReady(
                    "source year not registered as a saved game year"
                )
            rows = conn.execute(
                "SELECT match_id,payload_json,record_sha256 FROM historical_matches "
                "WHERE year=? AND competition_id=? ORDER BY match_id",
                (year, SENBATSU_ID),
            ).fetchall()
            expected = {m.match_id: m for m in matches}
            if len(rows) != 31 or {r["match_id"] for r in rows} != set(expected):
                raise HokkaidoRecommendationNotReady(
                    "archived Senbatsu games are missing or unexpected"
                )
            manifest = []
            for row in rows:
                raw = row["payload_json"]
                actual_sha = sha256(raw.encode("utf-8")).hexdigest()
                if actual_sha != row["record_sha256"]:
                    raise HokkaidoRecommendationNotReady(
                        "same-year Senbatsu match checksum changed"
                    )
                game = json.loads(raw)
                match = expected[row["match_id"]]
                if (game.get("year") != year
                        or game.get("competition_id") != SENBATSU_ID
                        or game.get("match_id") != match.match_id
                        or game.get("stage_code") != "MAIN"
                        or {game.get("team1_id"), game.get("team2_id")}
                        != {match.team1, match.team2}
                        or game.get("winner_id") != match.winner
                        or game.get("loser_id") != match.loser
                        or game.get("score_source") != "ability_model_v1"
                        or not game.get("inning_scores")
                        or not game.get("batter_stats")
                        or not game.get("pitcher_stats")):
                    raise HokkaidoRecommendationNotReady(
                        "source game differs or has no saved A-type results"
                    )
                try:
                    played = date.fromisoformat(game["match_date"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise HokkaidoRecommendationNotReady(
                        "invalid saved Senbatsu game date"
                    ) from exc
                if played.year != year or played >= date(year, 5, 8):
                    raise HokkaidoRecommendationNotReady(
                        "Senbatsu games must finish before the projected qualifier"
                    )
                manifest.append([match.match_id, row["record_sha256"]])
    except (sqlite3.DatabaseError, OSError, json.JSONDecodeError) as exc:
        raise HokkaidoRecommendationNotReady(
            "Senbatsu source archive cannot be verified"
        ) from exc
    fingerprint = sha256(_canonical(manifest).encode("utf-8")).hexdigest()
    return {
        "year": year,
        "source_competition_id": SENBATSU_ID,
        "destination_competition_id": SPRING_HOKKAIDO_ID,
        "access_rule_id": rule["access_rule_id"],
        "qualified_senbatsu_school_ids": list(all_teams),
        "recommended_hokkaido_school_ids": recommendation,
        "source_match_count": 31,
        "source_matches_sha256": fingerprint,
        "source_year_sealing_required": False,
        "verified_same_year_saved_A_games": True,
        "official_entrant_list": False,
        "same_year_checkpoint_automatically_wired": False,
    }


def prepare_hokkaido_spring_after_senbatsu(
    *, data_root: str | Path, year: int, repo: DataRepository,
    source_archive: HistoricalMatchArchive, completed_senbatsu: CompetitionRun,
    group_entrant_school_ids: Mapping[str, Sequence[str]],
    roster_archive: CareerRosterArchive, base_seed: int, career_seed: int,
    ability_config_dir: str | Path = "config/abilities",
    match_config_dir: str | Path = "config/match",
) -> tuple[FutureCompetitionPreview, dict]:
    """Opt-in spring preview after full same-year game evidence is verified.

    For simulation, a recommended school is excluded from the qualifier
    quota competition (even if it was supplied as a potential branch entrant).
    This reflects the engine's documented approximation; it does not deny that
    real-world rules may let the team play branch exhibition/qualifier games.
    """
    proof = certify_saved_senbatsu_hokkaido(
        repo, source_archive, completed_senbatsu, year=year,
    )
    blueprint = build_future_season_blueprint(
        data_root, year=year, base_seed=base_seed,
    )
    qualifier = repo.stage_by_code(
        SPRING_HOKKAIDO_ID, "BRANCH_QUALIFIER",
    )
    main = repo.stage_by_code(SPRING_HOKKAIDO_ID, "MAIN")
    stage_assignment = repo.assignments_by_stage[qualifier["stage_id"]]
    if (stage_assignment["default_format_model_id"] != "FMT001"
            or main["stage_code"] != "MAIN"):
        raise HokkaidoRecommendationNotReady("spring graph not FMT001 -> MAIN")
    known = repo.groups_by_stage[qualifier["stage_id"]]
    if set(group_entrant_school_ids) != {g["stage_group_id"] for g in known}:
        raise HokkaidoRecommendationNotReady(
            "all ten spring branches require explicit entrants"
        )
    direct = proof["recommended_hokkaido_school_ids"]
    direct_set = set(direct)
    supplied = []
    groups = {}
    slot_total = 0
    for row in known:
        gid = row["stage_group_id"]
        members = list(group_entrant_school_ids[gid])
        if (not members or len(members) != len(set(members))
                or any(type(sid) is not str
                       or sid not in repo.school_to_program
                       or repo.schools[sid]["prefecture_code"] != "01"
                       for sid in members)):
            raise HokkaidoRecommendationNotReady(
                f"{gid}: invalid or duplicated Hokkaido school IDs"
            )
        supplied.extend(members)
        groups[gid] = [sid for sid in members if sid not in direct_set]
        quota = repo.param(
            qualifier["stage_id"], "output_slots", gid,
            int(row.get("advance_slots_to_next") or 0),
        )
        if type(quota) is not int or quota <= 0 or len(groups[gid]) < quota:
            raise HokkaidoRecommendationNotReady(
                f"{gid}: recommended team must not consume a branch quota"
            )
        slot_total += quota
    if len(supplied) != len(set(supplied)):
        raise HokkaidoRecommendationNotReady(
            "Hokkaido school cannot appear in two branches"
        )
    entrants = list(dict.fromkeys([*supplied, *direct]))
    if slot_total != 15:
        raise HokkaidoRecommendationNotReady(
            "2026 spring structure must have 15 qualifier quotas"
        )
    if any(
        (roster := roster_archive.roster(year, sid)) is None
        or roster.reference_year != year or roster.school_id != sid
        or roster.rng_seed != career_seed or roster.cohort_policy != "career_v1"
        for sid in entrants
    ):
        raise HokkaidoRecommendationNotReady(
            "complete 2027 saved rosters required for every entrant"
        )

    calendars = [
        c for c in blueprint["calendars"]
        if c["competition_id"] == SPRING_HOKKAIDO_ID
    ]
    stage_calendars = [
        c for c in blueprint["stage_calendars"]
        if c["competition_id"] == SPRING_HOKKAIDO_ID
        and c["stage_code"] == "BRANCH_QUALIFIER"
    ]
    if len(calendars) != 1 or len(stage_calendars) != 1:
        raise HokkaidoRecommendationNotReady("projected stage dates missing")
    calendar, stage_date = calendars[0], stage_calendars[0]
    if (calendar.get("year") != year
            or calendar.get("date_source") != "game_projection_v1"
            or calendar.get("real_world_verified") is not False
            or stage_date.get("real_world_verified") is not False):
        raise HokkaidoRecommendationNotReady(
            "only provisional future spring dates are allowed"
        )
    qdays = _projected_days(stage_date["date_list"], year, "spring qualifier")
    mdays = _projected_days(calendar["game_date_list"], year, "spring MAIN")
    if qdays[-1] >= mdays[0]:
        raise HokkaidoRecommendationNotReady("spring qualifier dates overlap MAIN")

    comp = next(
        c for c in blueprint["competitions"]
        if c["competition_id"] == SPRING_HOKKAIDO_ID
    )
    annual = AnnualCompetitionInput(
        competition_id=SPRING_HOKKAIDO_ID, year=year,
        entrant_school_ids=entrants, direct_main_entry_school_ids=list(direct),
        group_entrant_school_ids=groups, rng_seed=int(comp["rng_seed"]),
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
        annual, calendar, stage_date_lists={"BRANCH_QUALIFIER": qdays},
    )
    if scheduled.calendar_gap_match_ids:
        raise HokkaidoRecommendationNotReady("spring qualifier date gap")
    display = str(comp["display_name"])
    scheduled.competition_name = display
    preview = FutureCompetitionPreview(
        year=year, competition_id=SPRING_HOKKAIDO_ID,
        competition_display_name=display, entry_source=SANDBOX_ENTRANTS,
        annual=annual, scheduled=scheduled,
    )
    proof["qualifier_slots"] = slot_total
    proof["total_main_school_count_projected"] = slot_total + len(direct)
    proof["direct_recommendations_have_qualifier_quota_effect"] = False
    proof["save_checkpoint_connected"] = False
    return preview, proof
