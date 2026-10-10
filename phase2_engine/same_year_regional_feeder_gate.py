"""Stage 43G-3: verify same-year spring prefecture -> regional entrants.

This gate does *not* start a regional competition or treat the 2026 rules
as officially verified for 2027. It emits a partial, evidence-bound list
only after the original game's MAIN outcome and SQLite match rows agree.
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
import sqlite3

from .career_competition_outcomes import (
    CareerCompetitionOutcomes,
    CareerOutcomeConflictError,
    _main_result,
)
from .career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService,
    CareerMultiPreviewSession,
    CareerPreviewSaveError,
    _checkpoint,
    _digest,
)
from .paths import resolve_data_file


class RegionalFeederNotReady(CareerPreviewSaveError):
    """Requested feeder has no validated game results / event format."""


def _csv_rows(data_root: Path, name: str) -> list[dict]:
    with resolve_data_file(data_root, name).open(
        "r", encoding="utf-8-sig", newline=""
    ) as fh:
        return list(csv.DictReader(fh))


def project_same_year_regional_feeders(
    service: CareerMultiPreviewCheckpointService,
    session: CareerMultiPreviewSession,
    destination_competition_id: str,
) -> dict:
    """Project game-qualified schools without granting final entry or seeds.

    Only same-year, direct, no-playoff rank_range selectors are inspected.
    Ambiguous 3rd-place cutoffs remain unresolved, as a semifinal loss
    does not by itself specify third vs fourth place.
    """
    if session.year <= 2026 or not isinstance(session.year, int):
        raise RegionalFeederNotReady("future sandbox year required")
    slot = service.solo.slots.validate_slot_id(session.slot_id)
    saved = _checkpoint(service._path(slot, session.year))
    if (saved["payload_checksum"] != session.checkpoint_checksum
            or saved.get("plan_fingerprint") != service._fingerprint(session)
            or saved.get("processed_dates") != session.processed_dates):
        raise RegionalFeederNotReady(
            "uncommitted or stale multi-preview checkpoint"
        )
    service._assert_prior(session)

    repo = service.solo.repo
    destination = repo.competition(destination_competition_id)
    if (destination.get("season_segment") != "spring"
            or destination.get("competition_type") != "spring_regional"
            or not destination.get("region_id")):
        raise RegionalFeederNotReady("destination is not a spring regional event")
    master = _csv_rows(service.solo.data_root, "regional_feeder_rules.csv")
    rules = sorted(
        (
            r for r in master
            if r.get("destination_competition_id") == destination_competition_id
            and r.get("season_segment") == "spring"
        ),
        key=lambda r: (int(r.get("priority") or 0), r["feeder_rule_id"]),
    )
    if not rules:
        raise RegionalFeederNotReady("regional feeder rule not registered")
    if any(r.get("region_id") != destination["region_id"] for r in rules):
        raise RegionalFeederNotReady("regional feeder region mismatch")
    stages = repo.stages(destination_competition_id)
    if len(stages) != 1 or stages[0]["stage_code"] != "MAIN":
        raise RegionalFeederNotReady("regional MAIN format not verified")
    quota_sum = 0
    for rule in rules:
        if (rule.get("source_type") != "prefectural_result"
                or rule.get("selector") != "rank_range"
                or rule.get("rank_from") != "1"
                or rule.get("qualification_mode") != "direct"
                or rule.get("playoff_id")
                or rule.get("source_region_filter")
                or rule.get("exclude_already_selected") != "yes"
                or rule.get("fill_to_quota") != "yes"
                or rule.get("effective_year") != "2026"):
            raise RegionalFeederNotReady(
                f"unsupported game projection feeder rule: {rule['feeder_rule_id']}"
            )
        count = int(rule["quota"])
        if (count < 1 or int(rule["rank_to"]) != count
                or not rule.get("source_prefecture_code")):
            raise RegionalFeederNotReady(
                f"invalid fixed regional quota: {rule['feeder_rule_id']}"
            )
        source = repo.competition(rule["source_competition_id"])
        if (source.get("competition_type") != "spring_prefectural"
                or source.get("prefecture_code")
                != rule["source_prefecture_code"]):
            raise RegionalFeederNotReady("regional source competition mismatch")
        quota_sum += count
    required = int(stages[0].get("team_count") or 0)
    if required < 2 or quota_sum != required:
        raise RegionalFeederNotReady(
            "regional feeder total does not equal MAIN team count"
        )

    # The 2026 schedule is *only* a future-year game-day projection.
    calendars = _csv_rows(service.solo.data_root, "season_calendar.csv")
    match = [r for r in calendars
             if r["competition_id"] == destination_competition_id]
    if len(match) != 1 or not match[0]["start_date"]:
        raise RegionalFeederNotReady("no projected regional start date")
    game_start = date.fromisoformat(
        f"{session.year}{match[0]['start_date'][4:]}"
    )

    archive = service.solo._archive(slot)
    if not archive.db_path.is_file():
        raise RegionalFeederNotReady("current year archive missing")
    runs = session.completed_runs()
    verified = []
    statuses = []
    all_selected = set()
    with sqlite3.connect(archive.db_path) as conn:
        conn.row_factory = sqlite3.Row
        identity = conn.execute(
            "SELECT status, metadata_json "
            "FROM career_years WHERE year=?", (session.year,),
        ).fetchone()
        metadata = json.loads(identity["metadata_json"]) if identity else {}
        if (identity is None or identity["status"] != "active"
                or metadata.get("rng_seed") != session.inputs[0]["base_seed"]
                or metadata.get("resolver_contract") !=
                "career_multi_preview_ability_v1"
                or metadata.get("plan_fingerprint") != service._fingerprint(session)):
            raise RegionalFeederNotReady("current year archive identity mismatch")
        for rule in rules:
            cid = rule["source_competition_id"]
            quota = int(rule["quota"])
            base = {
                "feeder_rule_id": rule["feeder_rule_id"],
                "source_competition_id": cid,
                "source_prefecture_code": rule["source_prefecture_code"],
                "quota": quota,
                "school_ids": [],
                "evidence_sha256": "",
            }
            if cid not in session.previews:
                base["status"] = "source_not_in_preview"
            elif cid not in runs:
                base["status"] = "source_not_completed"
            elif quota > 2:
                # Ranking of tied semifinal losers can be arbitrary without
                # the game recording a valid third-place tie breaker.
                base["status"] = "ranking_cutoff_requires_tiebreak_rule"
            else:
                try:
                    outcome, matches = _main_result(runs[cid])
                    manifest = CareerCompetitionOutcomes._check_source_matches(
                        conn, session.year, cid, matches,
                    )
                except (CareerOutcomeConflictError, ValueError) as exc:
                    raise RegionalFeederNotReady(
                        f"source MAIN outcome does not match archived games: {cid}"
                    ) from exc
                dates = []
                for match_id, _ in manifest:
                    row = conn.execute(
                        "SELECT match_date FROM historical_matches "
                        "WHERE year=? AND competition_id=? AND match_id=?",
                        (session.year, cid, match_id),
                    ).fetchone()
                    if not row or not row["match_date"]:
                        raise RegionalFeederNotReady(
                            "qualified match has no archived game date"
                        )
                    day = date.fromisoformat(row["match_date"])
                    if day.year != session.year:
                        raise RegionalFeederNotReady(
                            "qualified match belongs to another year"
                        )
                    dates.append(day)
                if max(dates) >= game_start:
                    raise RegionalFeederNotReady(
                        "prefectural final must finish before regional event"
                    )
                teams = outcome["ranked_school_ids"][:quota]
                if len(teams) != quota or any(
                    repo.schools.get(sid, {}).get("prefecture_code") !=
                    rule["source_prefecture_code"] for sid in teams
                ):
                    raise RegionalFeederNotReady(
                        "qualified schools are missing or outside prefecture"
                    )
                if all_selected.intersection(teams):
                    raise RegionalFeederNotReady(
                        "same school qualified through multiple feeder rules"
                    )
                all_selected.update(teams)
                base["school_ids"] = teams
                base["evidence_sha256"] = _digest({
                    "year": session.year, "competition_id": cid,
                    "main_match_manifest": manifest,
                    "source_ranking": outcome["ranked_school_ids"],
                })
                base["status"] = "verified_game_qualification"
                verified.extend(teams)
            statuses.append(base)

    unresolved = [
        item["feeder_rule_id"] for item in statuses
        if item["status"] != "verified_game_qualification"
    ]
    ready = not unresolved and len(verified) == required
    return {
        "year": session.year,
        "destination_competition_id": destination_competition_id,
        "destination_start_date_game_projection": game_start.isoformat(),
        "provenance": "game_projection_from_2026_feeder_structure",
        "official_future_rule_verified": False,
        "full_year_gameplay": False,
        "feeder_rule_count": len(statuses),
        "expected_entrant_count": required,
        "verified_entrant_count": len(verified),
        "verified_school_ids": verified,
        "unresolved_feeder_rule_ids": unresolved,
        "feeder_rules": statuses,
        "all_feeder_results_verified": ready,
        # Even when fully verified, a separate annual regional tournament
        # planner, draw, dated runtime, roster and seed audit is mandatory.
        "regional_runtime_ready": False,
        "automatic_qualification_committed": False,
    }
