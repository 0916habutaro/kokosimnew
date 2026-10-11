"""Stage43G-50: verify same-year Senbatsu exemptions for Aichi and Mie.

Only a completed 32-team / 31-game national *simulation*, verified against
same-year saved Option-A game records, establishes who may bypass the 2027
prefectural branch qualifiers. This read-only gate NEVER inserts entrants
into a partially progressed spring event: 2026-projected calendars overlap.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date
from hashlib import sha256
import json
import sqlite3

from .career_competition_outcomes import _main_result, _canonical
from .career_multi_preview_checkpoint import CareerMultiPreviewCheckpointService
from .career_option_a_storage_profile import _read_only
from .career_preview_checkpoint import CareerPreviewSaveError
from .future_competition_bridge import FutureCompetitionNotReady
from .future_season_blueprint import build_future_season_blueprint
from .historical_match_archive import HistoricalMatchArchive
from .models import CompetitionRun
from .repository import DataRepository


SENBATSU_ID = "CMP000001"
TOKAI_PREFECTURES = {
    "CMP000113": ("23", "ACR000012", "FMT010", 5),  # Aichi
    "CMP000115": ("24", "ACR000013", "FMT016", 3),  # Mie
}


class TokaiSenbatsuNotReady(FutureCompetitionNotReady):
    """Full same-year saved Senbatsu evidence or safe schedule is missing."""


def _verify_rule(repo: DataRepository, destination_id: str, year: int) -> dict:
    spec = TOKAI_PREFECTURES.get(destination_id)
    if spec is None or type(year) is not int or not 2026 < year <= 9999:
        raise TokaiSenbatsuNotReady("invalid destination or future game year")
    pcode, access_id, format_id, groups = spec
    competition = repo.competition(destination_id)
    rules = repo.access_rules(destination_id)
    stages = repo.stages(destination_id)
    if (competition.get("prefecture_code") != pcode
            or competition.get("competition_type") != "spring_prefectural"
            or len(rules) != 1
            or len(stages) != 2
            or {s["stage_code"] for s in stages} != {"BRANCH_QUALIFIER", "MAIN"}):
        raise TokaiSenbatsuNotReady("Tokai destination contract changed")
    rule = rules[0]
    required = {
        "access_rule_id": access_id,
        "source_year_offset": "0",
        "source_event_kind": "national_invitational",
        "source_competition_id_2026": SENBATSU_ID,
        "source_result_selector": "participant_from_destination_prefecture",
        "action_type": "grant_main_entry_bypass_branch_qualifier",
        "bypassed_stage_participation_policy": "excluded_from_bypassed_stage",
        "grants_main_entry": "yes",
        "deduplicate_by_team": "yes",
        "quota_mode": "all_matches",
        "seed_on_entry": "destination_policy",
        "automation_status": "machine_resolvable",
        "destination_prefecture_code": pcode,
    }
    if (any(rule.get(k) != v for k, v in required.items())
            or int(rule.get("effective_from_year") or 2026) > year
            or (rule.get("effective_to_year")
                and year > int(rule["effective_to_year"]))):
        raise TokaiSenbatsuNotReady("Tokai Senbatsu access contract changed")
    qualifier = next(s for s in stages if s["stage_code"] == "BRANCH_QUALIFIER")
    assignment = repo.assignments_by_stage.get(qualifier["stage_id"], {})
    if (assignment.get("default_format_model_id") != format_id
            or len(repo.groups_by_stage.get(qualifier["stage_id"], [])) != groups):
        raise TokaiSenbatsuNotReady("prefectural qualifier graph changed")
    return rule


def certify_saved_tokai_senbatsu(
    repo: DataRepository, archive: HistoricalMatchArchive,
    run: CompetitionRun, *, year: int,
) -> dict:
    """Read-only verification of every national MAIN game and both access rules.

    Do not accept an operator-supplied school list, a partial match archive,
    an unofficial participant manifest, or the final champion alone.
    """
    for cid in TOKAI_PREFECTURES:
        _verify_rule(repo, cid, year)
    if (run.year != year or run.competition_id != SENBATSU_ID
            or repo.competition(SENBATSU_ID).get("competition_type")
            != "national_invitational"):
        raise TokaiSenbatsuNotReady("same-year Senbatsu MAIN required")
    stage = repo.stages(SENBATSU_ID)
    if len(stage) != 1 or stage[0].get("stage_code") != "MAIN":
        raise TokaiSenbatsuNotReady("Senbatsu source MAIN format changed")
    try:
        outcome, matches = _main_result(run)
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise TokaiSenbatsuNotReady("complete Senbatsu match outcome required") from exc
    schools = list(outcome["main_entrant_school_ids"])
    if (len(schools) != 32 or len(set(schools)) != 32
            or len(matches) != 31
            or any(sid not in repo.school_to_program for sid in schools)):
        raise TokaiSenbatsuNotReady("all 32 Senbatsu teams and 31 games required")
    if not archive.db_path.is_file():
        raise TokaiSenbatsuNotReady("saved same-year Senbatsu archive missing")
    expected = {m.match_id: m for m in matches}
    if len(expected) != 31:
        raise TokaiSenbatsuNotReady("duplicate Senbatsu match IDs")
    manifest = []
    dates = []
    try:
        with closing(_read_only(archive.db_path)) as db:
            db.row_factory = sqlite3.Row
            current = db.execute(
                "SELECT status FROM career_years WHERE year=?", (year,),
            ).fetchone()
            if current is None or current["status"] not in ("active", "sealed"):
                raise TokaiSenbatsuNotReady("same-year career archive not registered")
            rows = db.execute(
                "SELECT match_id,payload_json,record_sha256,match_date "
                "FROM historical_matches "
                "WHERE year=? AND competition_id=? ORDER BY match_id",
                (year, SENBATSU_ID),
            ).fetchall()
            if len(rows) != 31 or {x["match_id"] for x in rows} != set(expected):
                raise TokaiSenbatsuNotReady(
                    "Senbatsu archive incomplete or has unexpected games"
                )
            for row in rows:
                raw = row["payload_json"]
                if sha256(raw.encode("utf-8")).hexdigest() != row["record_sha256"]:
                    raise TokaiSenbatsuNotReady("Senbatsu archived checksum modified")
                saved = json.loads(raw)
                game = expected[row["match_id"]]
                if (saved.get("year") != year
                        or saved.get("competition_id") != SENBATSU_ID
                        or saved.get("match_id") != game.match_id
                        or saved.get("stage_code") != "MAIN"
                        or {saved.get("team1_id"), saved.get("team2_id")}
                        != {game.team1, game.team2}
                        or saved.get("winner_id") != game.winner
                        or saved.get("loser_id") != game.loser
                        or saved.get("score_source") != "ability_model_v1"
                        or saved.get("date_source") != "game_projection_v1"
                        or not saved.get("inning_scores")
                        or not saved.get("batter_stats")
                        or not saved.get("pitcher_stats")
                        or saved.get("match_date") != row["match_date"]):
                    raise TokaiSenbatsuNotReady(
                        "Senbatsu match/game A-stats differ from saved source"
                    )
                played = date.fromisoformat(row["match_date"])
                if played.year != year:
                    raise TokaiSenbatsuNotReady("other-year game date in Senbatsu")
                dates.append(played)
                manifest.append([game.match_id, row["record_sha256"]])
    except (sqlite3.DatabaseError, OSError, KeyError, TypeError,
            json.JSONDecodeError, ValueError) as exc:
        raise TokaiSenbatsuNotReady(
            "Senbatsu source archive cannot be verified"
        ) from exc
    source_hash = sha256(_canonical(manifest).encode("utf-8")).hexdigest()
    return {
        "year": year,
        "source_competition_id": SENBATSU_ID,
        "source_match_count": 31,
        "source_entrant_count": 32,
        "source_games_sha256": source_hash,
        "source_last_game_date": max(dates).isoformat(),
        "participants_by_prefecture": {
            cid: [
                sid for sid in schools
                if repo.schools[sid]["prefecture_code"]
                == TOKAI_PREFECTURES[cid][0]
            ]
            for cid in TOKAI_PREFECTURES
        },
        "full_same_year_saved_A_games_verified": True,
        "official_2027_selection": False,
    }


class CareerTokaiSenbatsuAccessService:
    """Return verified per-prefecture candidates, never auto-enroll a school."""

    def __init__(self, multi: CareerMultiPreviewCheckpointService):
        self.multi = multi

    def audit(self, slot_id: str, *, year: int) -> dict:
        repo = self.multi.solo.repo
        for cid in TOKAI_PREFECTURES:
            _verify_rule(repo, cid, year)
        session = self.multi.load(slot_id, year=year)
        source = session.previews.get(SENBATSU_ID)
        complete = (
            source is not None
            and source.scheduled.is_complete
            and any(row.get("competition_id") == SENBATSU_ID
                    and row.get("entry_mode") == "national_invitational_main_v1"
                    for row in session.inputs)
        )
        if not complete:
            return {
                "year": year,
                "source_competition_id": SENBATSU_ID,
                "status": "complete_saved_senbatsu_required",
                "participants_by_prefecture": None,
                "zero_senbatsu_entrants_confirmed": False,
                "automatic_bypass_enabled": False,
                "regional_runtime_ready": False,
            }
        try:
            proof = certify_saved_tokai_senbatsu(
                repo, self.multi.solo._archive(session.slot_id),
                source.scheduled.to_competition_run(), year=year,
            )
        except (CareerPreviewSaveError, ValueError, TypeError, KeyError) as exc:
            raise TokaiSenbatsuNotReady(
                "same-year saved Senbatsu certification failed"
            ) from exc
        blueprint = build_future_season_blueprint(
            self.multi.solo.data_root, year=year,
            base_seed=session.inputs[0]["base_seed"],
        )
        results = {}
        last_source = date.fromisoformat(proof["source_last_game_date"])
        for cid, (pcode, access_id, format_id, count) in TOKAI_PREFECTURES.items():
            cal = [
                x for x in blueprint["stage_calendars"]
                if x["competition_id"] == cid
                and x["stage_code"] == "BRANCH_QUALIFIER"
            ]
            mains = [
                x for x in blueprint["calendars"]
                if x["competition_id"] == cid
            ]
            if len(cal) != 1 or len(mains) != 1:
                raise TokaiSenbatsuNotReady("missing Tokai projected calendar")
            pre = cal[0]
            main = mains[0]
            if (pre.get("date_source") != "game_projection_v1"
                    or pre.get("real_world_verified") is not False
                    or main.get("date_source") != "game_projection_v1"
                    or main.get("real_world_verified") is not False):
                raise TokaiSenbatsuNotReady(
                    "future Tokai projected date contract changed"
                )
            days = [
                date.fromisoformat(d) for d in pre["date_list"].split(";") if d
            ]
            first_main = date.fromisoformat(main["game_date_list"].split(";")[0])
            if (not days or last_source >= first_main
                    or any(d.year != year for d in days)):
                raise TokaiSenbatsuNotReady(
                    "Senbatsu game must finish before Tokai MAIN"
                )
            participants = proof["participants_by_prefecture"][cid]
            results[cid] = {
                "access_rule_id": access_id,
                "eligible_direct_main_school_ids": participants,
                "verified_participant_count": len(participants),
                "qualifier_first_projected_date": min(days).isoformat(),
                "qualifier_last_projected_date": max(days).isoformat(),
                "senbatsu_finishes_after_qualifier_starts":
                    last_source >= min(days),
                "membership_verified": True,
                "qualifier_format": format_id,
                "main_seed_school_ids": [],
                "automatic_bypass_enabled": False,
                "future_official_participants_confirmed": False,
            }
        return {
            **proof,
            "status": "complete_same_year_saved_senbatsu_verified",
            "prefectures": results,
            "schedule_conflict_requires_separate_activation_contract":
                any(x["senbatsu_finishes_after_qualifier_starts"]
                    for x in results.values()),
            "automatic_bypass_enabled": False,
            "regional_runtime_ready": False,
        }
