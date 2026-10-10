"""Provisional future-season competition blueprints (Stage 43F).

2026 remains the only official calendar source. Future dates here are *game
projections*, never official schedules, recorded results, or replayable runs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Mapping

from .paths import resolve_data_file


BASE_YEAR = 2026
GAME_PROJECTION = "game_projection_v1"


def _read(data_root: str | Path, name: str) -> list[dict[str, str]]:
    with resolve_data_file(data_root, name).open(
        encoding="utf-8-sig", newline=""
    ) as fh:
        return list(csv.DictReader(fh))


def _project_day(iso: str, year: int) -> str:
    if not iso:
        return ""
    anchor = date.fromisoformat(iso)
    if anchor.year != BASE_YEAR:
        raise ValueError(f"source calendar not {BASE_YEAR}: {iso}")
    try:
        return anchor.replace(year=year).isoformat()
    except ValueError as err:
        # Never silently move Feb 29 to another day or fabricate a date.
        raise ValueError(f"cannot project anchor date {iso} to {year}") from err


def _project_days(values: str, year: int) -> str:
    if not values:
        return ""
    dates = [_project_day(x.strip(), year) for x in values.split(";") if x.strip()]
    if len(dates) != len(set(dates)) or dates != sorted(dates):
        raise ValueError("projected schedule contains duplicate or unordered days")
    return ";".join(dates)


def _derived_seed(base_seed: int, year: int, competition_id: str) -> int:
    if not isinstance(base_seed, int) or isinstance(base_seed, bool):
        raise ValueError("base_seed must be integer")
    payload = f"{base_seed}:future_competition_v1:{year}:{competition_id}"
    return int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big")


def _future_competition(row: Mapping[str, str], year: int, seed: int) -> dict:
    original_code = row["competition_code"]
    if not original_code.endswith(f"_{BASE_YEAR}"):
        raise ValueError(f"unexpected 2026 competition code: {original_code}")
    return {
        "competition_id": row["competition_id"],
        "competition_code": original_code[: -len(str(BASE_YEAR))] + str(year),
        "reference_year": year,
        "season_segment": row["season_segment"],
        "competition_type": row["competition_type"],
        "competition_level": row["competition_level"],
        "prefecture_code": row["prefecture_code"],
        "region_id": row["region_id"],
        "qualifying_area_id": row["qualifying_area_id"],
        "parent_competition_id": row["parent_competition_id"],
        "format_type": row["format_type"],
        "rng_seed": _derived_seed(seed, year, row["competition_id"]),
        # 2026 titles often encode the edition/era/year: don't pass them off as
        # true names of tournaments held in the future.
        "display_name": f"ゲーム内{year}年度 {row['competition_id']}（仮大会）",
        "base_competition_id": row["competition_id"],
        "source_structure_year": BASE_YEAR,
        "structure_status": "requires_future_year_validation",
        "provenance": GAME_PROJECTION,
        "participant_status": "unresolved",
        "draw_status": "unresolved",
    }


def _future_calendar(row: Mapping[str, str], year: int) -> dict:
    result = {
        "calendar_id": f"GAME-{year}-{row['competition_id']}",
        "competition_id": row["competition_id"],
        "year": year,
        "start_date": _project_day(row.get("start_date", ""), year),
        "end_date": _project_day(row.get("end_date", ""), year),
        "draw_date": _project_day(row.get("draw_date", ""), year),
        "game_date_list": _project_days(row.get("game_date_list", ""), year),
        "date_source": GAME_PROJECTION,
        "calendar_status": "provisional_game_schedule",
        "source_calendar_status_2026": row.get("calendar_status", ""),
        "real_world_verified": False,
        "primary_source_id": "",
        "verified_at": "",
        "notes": "2026の月日をゲーム内候補日に写像。2027年以降の公式日程ではない。",
    }
    if result["start_date"] and result["end_date"] and (
        result["start_date"] > result["end_date"]
    ):
        raise ValueError(f"projected calendar reversed: {row['competition_id']}")
    return result


def _future_stage(row: Mapping[str, str], year: int) -> dict:
    return {
        "stage_calendar_id": f"GAME-{year}-{row['stage_calendar_id']}",
        "reference_year": year,
        "competition_id": row["competition_id"],
        "stage_id": row["stage_id"],
        "stage_code": row["stage_code"],
        "date_list": _project_days(row.get("date_list", ""), year),
        "date_status": "provisional_game_schedule",
        "calendar_relation": row.get("calendar_relation", ""),
        "date_source": GAME_PROJECTION,
        "real_world_verified": False,
        "primary_source_id": "",
        "verified_at": "",
    }


def _effective(rule: Mapping[str, str], year: int) -> bool:
    start = int(rule.get("effective_from_year") or BASE_YEAR)
    end = rule.get("effective_to_year") or ""
    return start <= year and (not end or year <= int(end))


def _prior_autumn_rule(
    rule: Mapping[str, str],
    competitions: list[dict[str, str]],
    year: int,
    previous_results: Mapping[str, Mapping[str, object]],
) -> dict:
    kind = rule["source_event_kind"]
    pcode = rule.get("destination_prefecture_code", "")
    candidates = [
        c for c in competitions
        if c["season_segment"] == "autumn"
        and c["competition_type"] == kind
        and c["prefecture_code"] == pcode
    ]
    output = {
        "access_rule_id": rule["access_rule_id"],
        "destination_competition_id": rule["destination_competition_id"],
        "source_year": year - 1,
        "source_event_kind": kind,
        "source_competition_id": candidates[0]["competition_id"]
        if len(candidates) == 1 else "",
        "expected_count": int(
            rule.get("quota") or rule.get("observed_2026_count") or 0
        ),
        "school_ids": [],
        "status": "unresolved",
        "provenance": "saved_game_results_required",
    }
    if kind != "autumn_prefectural":
        output["reason"] = "unsupported_prior_year_selector"
        return output
    if len(candidates) != 1:
        output["reason"] = "ambiguous_or_missing_prior_autumn_competition"
        return output
    source_id = candidates[0]["competition_id"]
    stored = previous_results.get(source_id)
    if stored is None:
        output["reason"] = "prior_year_result_not_supplied"
        return output
    if (
        stored.get("year") != year - 1
        or stored.get("status") != "completed"
        or stored.get("source") != "game_result"
    ):
        output["reason"] = "prior_result_not_verified_as_completed_game"
        return output
    ranks = stored.get("ranked_school_ids")
    if (
        not isinstance(ranks, list)
        or any(not isinstance(x, str) or not x for x in ranks)
        or len(set(ranks)) != len(ranks)
    ):
        output["reason"] = "invalid_or_duplicated_prior_ranking"
        return output
    if rule.get("source_result_selector") != "top_n":
        output["reason"] = "unsupported_prior_year_selector"
        return output
    low = int(rule.get("source_rank_from") or 1)
    high = int(rule.get("source_rank_to") or low)
    if low < 1 or high < low or len(ranks) < high:
        output["reason"] = "prior_result_insufficient_ranked_schools"
        return output
    selected = ranks[low - 1:high]
    if output["expected_count"] and len(selected) != output["expected_count"]:
        output["reason"] = "prior_result_quota_mismatch"
        return output
    output["school_ids"] = list(selected)
    output["status"] = "resolved"
    output["provenance"] = "previous_year_saved_game_result"
    output["reason"] = ""
    return output


def build_future_season_blueprint(
    data_root: str | Path,
    *,
    year: int,
    base_seed: int,
    previous_results: Mapping[str, Mapping[str, object]] | None = None,
) -> dict:
    """Generate *provisional* competition/calendar metadata, not a live plan.

    In particular no 2026 school memberships or participant quotas are
    reused as definitive next-year entrant lists. Previous-year access
    requires explicit completed game results; selection committee entries
    remain unavailable.
    """
    if not isinstance(year, int) or isinstance(year, bool) or not BASE_YEAR < year <= 9999:
        raise ValueError("future game date projection needs 2027 <= year <= 9999")
    previous_results = previous_results or {}
    competitions = _read(data_root, "competitions.csv")
    calendars = _read(data_root, "season_calendar.csv")
    stages = _read(data_root, "competition_stage_calendar.csv")
    access = _read(data_root, "competition_access_rules.csv")
    source = [c for c in competitions if c.get("reference_year") == str(BASE_YEAR)]
    ids = {c["competition_id"] for c in source}
    if len(ids) != len(source) or not source:
        raise ValueError("missing or duplicate base competition IDs")
    if {c["competition_id"] for c in calendars} != ids:
        raise ValueError("base calendars do not match competition IDs")
    if any(s["competition_id"] not in ids for s in stages):
        raise ValueError("stage calendar outside base competitions")
    if any(s.get("reference_year") != str(BASE_YEAR) for s in stages):
        raise ValueError("base stage calendar year mismatch")

    output_competitions = [
        _future_competition(row, year, base_seed)
        for row in sorted(source, key=lambda c: c["competition_id"])
    ]
    output_calendars = [
        _future_calendar(row, year)
        for row in sorted(calendars, key=lambda c: c["competition_id"])
    ]
    output_stages = [
        _future_stage(row, year)
        for row in sorted(
            stages, key=lambda c: (c["competition_id"], c["stage_id"])
        )
    ]
    prior = [
        _prior_autumn_rule(rule, source, year, previous_results)
        for rule in sorted(access, key=lambda r: r["access_rule_id"])
        if _effective(rule, year)
        and rule.get("source_year_offset") == "-1"
    ]
    # A committee selection is never an automatic qualification.
    committee = [
        {"competition_id": c["competition_id"],
         "status": "committee_selection_pending",
         "reason": "selection committee cannot be reproduced from ranks alone"}
        for c in source if c["competition_type"] == "national_invitational"
    ]
    unresolved = [
        r["access_rule_id"] for r in prior if r["status"] != "resolved"
    ]
    return {
        "year": year,
        "source_structure_year": BASE_YEAR,
        "provenance": GAME_PROJECTION,
        "official_calendar": False,
        "live_runtime_ready": False,
        "warning": "仮の日程・大会構造であり公式記録ではない。出場校・選手・進出枠は別途確定が必要。",
        "competition_count": len(output_competitions),
        "calendar_count": len(output_calendars),
        "stage_calendar_count": len(output_stages),
        "competitions": output_competitions,
        "calendars": output_calendars,
        "stage_calendars": output_stages,
        "prior_autumn_access": prior,
        "unresolved_prior_rule_ids": unresolved,
        "committee_selections": committee,
        "next_required": [
            "future_year_entrant_units_and_school_membership",
            "future_year_competition_rule_effectivity",
            "next_year_tournament_draw_generation",
            "previous_autumn_saved_results",
            "national_invitational_committee_selection",
            "live_season_planner_integration",
            "persistent_player_roster_integration",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage43F: 翌年度以降のゲーム内仮大会・仮日程を生成"
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--prior-results-json", help="前年秋のゲーム内確定順位JSON")
    parser.add_argument("--output", help="保存するブループリントJSON")
    args = parser.parse_args()
    prior = {}
    if args.prior_results_json:
        prior = json.loads(
            Path(args.prior_results_json).read_text(encoding="utf-8")
        )
    out = build_future_season_blueprint(
        args.data_dir, year=args.year, base_seed=args.seed,
        previous_results=prior,
    )
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
