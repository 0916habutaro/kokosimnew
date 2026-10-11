"""Stage43G-39: explicit sandbox entrants for non-Kanto regional MAIN events.

Uses the 2026 regional membership *only to reject schools outside the region*.
It does not claim that arbitrary entrants are actual prefectural qualifiers,
derive host-dependent quotas, or certify future-year official tournament rules.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Sequence

from .career_roster_archive import CareerRosterArchive
from .future_competition_bridge import (
    FutureCompetitionNotReady,
    FutureCompetitionPreview,
    prepare_future_direct_main_preview,
)
from .future_season_blueprint import build_future_season_blueprint
from .paths import resolve_data_file
from .repository import DataRepository


# 2026 verified single-stage spring regionals; Hokkaido and Kanto require
# distinct entry/qualification logic and are intentionally excluded.
NON_KANTO_REGIONAL_MAIN_IDS = frozenset((
    "CMP000005", "CMP000007", "CMP000008", "CMP000009",
    "CMP000010", "CMP000011", "CMP000012",
))


def _allowed_region_prefectures(data_root: str | Path,
                                region_id: str) -> set[str]:
    path = resolve_data_file(data_root, "prefecture_region_memberships.csv")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    selected = [
        row for row in rows
        if row.get("region_id") == region_id
        and row.get("season_segment") == "spring"
        and row.get("effective_year") == "2026"
    ]
    prefectures = [row["prefecture_code"] for row in selected]
    if len(prefectures) < 2 or len(prefectures) != len(set(prefectures)):
        raise FutureCompetitionNotReady(
            "missing or duplicated canonical 2026 regional memberships"
        )
    return set(prefectures)


def prepare_future_non_kanto_regional_main_preview(
    *, data_root: str | Path, year: int, competition_id: str,
    entrant_school_ids: Sequence[str],
    roster_archive: CareerRosterArchive, repo: DataRepository,
    base_seed: int, career_seed: int,
    ability_config_dir: str | Path = "config/abilities",
    match_config_dir: str | Path = "config/match",
) -> FutureCompetitionPreview:
    """Prepare a 2027+ opt-in MAIN only with explicit teams and saved rosters."""
    if competition_id not in NON_KANTO_REGIONAL_MAIN_IDS:
        raise FutureCompetitionNotReady("regional MAIN is not whitelisted")
    source_comp = repo.competition(competition_id)
    if (source_comp.get("reference_year") != "2026"
            or source_comp.get("competition_type") != "spring_regional"
            or not source_comp.get("region_id")
            or source_comp.get("prefecture_code")):
        raise FutureCompetitionNotReady("invalid 2026 regional competition reference")
    stages = repo.stages(competition_id)
    if len(stages) != 1 or stages[0].get("stage_code") != "MAIN":
        raise FutureCompetitionNotReady(
            "non-Kanto sandbox requires single-stage regional MAIN"
        )
    allowed = _allowed_region_prefectures(
        data_root, source_comp["region_id"],
    )
    entrants = list(entrant_school_ids)
    if not entrants or len(entrants) != len(set(entrants)):
        raise FutureCompetitionNotReady("explicit distinct regional entrants required")
    if any(sid not in repo.school_to_program or
           repo.schools[sid].get("prefecture_code") not in allowed
           for sid in entrants):
        raise FutureCompetitionNotReady("school outside verified 2026 region")
    if len({repo.schools[sid]["prefecture_code"] for sid in entrants}) < 2:
        raise FutureCompetitionNotReady(
            "regional sandbox must include at least two prefectures"
        )

    # No winner of an unfinished prefectural event is inferred. All schools
    # are an explicit sandbox list, not an approved qualification manifest.
    blueprint = build_future_season_blueprint(
        data_root, year=year, base_seed=base_seed,
    )
    return prepare_future_direct_main_preview(
        blueprint=blueprint, competition_id=competition_id,
        entrant_school_ids=entrants, roster_archive=roster_archive,
        repo=repo, career_seed=career_seed,
        ability_config_dir=ability_config_dir,
        match_config_dir=match_config_dir,
    )
