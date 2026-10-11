"""Stage43G-49: Gifu 2027 spring FMT002 bypass bound to sealed 2026 games.

This wrapper closes the district-membership boundary when the already
verified Stage43F-7 previous-autumn bypass adapter runs inside a multi-year
career checkpoint. It does not manufacture 2027 official entrants or seed
positions.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from .career_roster_archive import CareerRosterArchive
from .future_competition_bridge import FutureCompetitionNotReady, FutureCompetitionPreview
from .future_prior_autumn_access_bridge import (
    prepare_future_prior_autumn_bypass_preview,
)
from .historical_match_archive import HistoricalMatchArchive
from .repository import DataRepository

GIFU_SPRING = "CMP000109"
GIFU_AUTUMN = "CMP000110"
GIFU_PREFECTURE = "21"
GIFU_QUALIFIER_MODEL = "FMT002"
GIFU_EXPECTED_MAIN_COUNT = 24
GIFU_DIRECT_COUNT = 4


def prepare_future_gifu_sealed_autumn_preview(
    *, data_root: str | Path, year: int,
    entrant_school_ids: Sequence[str],
    group_entrant_school_ids: Mapping[str, Sequence[str]],
    match_archive: HistoricalMatchArchive,
    roster_archive: CareerRosterArchive,
    repo: DataRepository,
    base_seed: int, career_seed: int,
    ability_config_dir: str | Path = "config/abilities",
    match_config_dir: str | Path = "config/match",
) -> FutureCompetitionPreview:
    """Authenticate the previous-year autumn top four; draw other schools.

    Every explicitly supplied qualifier school must have belonged to its
    reference 2026 Gifu group. Current-year membership changes require an
    independent verified master update and cannot be inferred here.
    """
    source = repo.competition(GIFU_AUTUMN)
    target = repo.competition(GIFU_SPRING)
    if (source.get("prefecture_code") != GIFU_PREFECTURE
            or source.get("competition_type") != "autumn_prefectural"
            or target.get("prefecture_code") != GIFU_PREFECTURE
            or target.get("competition_type") != "spring_prefectural"):
        raise FutureCompetitionNotReady("Gifu spring/autumn master changed")
    rules = repo.access_rules(GIFU_SPRING)
    if (len(rules) != 1 or rules[0].get("access_rule_id") != "ACR000010"
            or rules[0].get("source_rank_to") != "4"
            or rules[0].get("quota") != "4"):
        raise FutureCompetitionNotReady("Gifu prior-autumn four-seat rule changed")
    stages = repo.stages(GIFU_SPRING)
    qstages = [r for r in stages if r["stage_code"] == "BRANCH_QUALIFIER"]
    if len(stages) != 2 or len(qstages) != 1:
        raise FutureCompetitionNotReady("Gifu FMT002 qualifier graph changed")
    qstage = qstages[0]
    assignment = repo.assignments_by_stage.get(qstage["stage_id"], {})
    known = repo.groups_by_stage.get(qstage["stage_id"], [])
    if (assignment.get("default_format_model_id") != GIFU_QUALIFIER_MODEL
            or len(known) != 4
            or set(group_entrant_school_ids) != {
                g["stage_group_id"] for g in known
            }):
        raise FutureCompetitionNotReady("Gifu four district manifests required")
    memberships = []
    slot_sum = 0
    for group in known:
        gid = group["stage_group_id"]
        members = list(group_entrant_school_ids[gid])
        allowed = repo.group_school_ids(group, 2026)
        quota = repo.param(
            qstage["stage_id"], "output_slots", gid,
            int(group.get("advance_slots_to_next") or 0),
        )
        if (repo.group_format[gid]["format_model_id"] != GIFU_QUALIFIER_MODEL
                or type(quota) is not int or quota <= 0
                or len(members) < quota
                or len(members) != len(set(members))
                or any(sid not in allowed for sid in members)):
            raise FutureCompetitionNotReady(
                f"{gid}: invalid Gifu 2026 district membership or quota"
            )
        slot_sum += quota
        memberships.extend(members)
    if (len(memberships) != len(set(memberships))
            or slot_sum + GIFU_DIRECT_COUNT != GIFU_EXPECTED_MAIN_COUNT):
        raise FutureCompetitionNotReady("Gifu qualification slot structure changed")
    result = prepare_future_prior_autumn_bypass_preview(
        data_root=data_root, year=year, competition_id=GIFU_SPRING,
        entrant_school_ids=entrant_school_ids,
        group_entrant_school_ids=group_entrant_school_ids,
        match_archive=match_archive, roster_archive=roster_archive,
        repo=repo, base_seed=base_seed, career_seed=career_seed,
        ability_config_dir=ability_config_dir,
        match_config_dir=match_config_dir,
        prior_source_competition_id=None,
    )
    direct = list(result.annual.direct_main_entry_school_ids)
    if (len(direct) != GIFU_DIRECT_COUNT
            or set(direct) & set(memberships)
            or set(direct) | set(memberships) != set(entrant_school_ids)
            or any(repo.schools.get(sid, {}).get("prefecture_code")
                   != GIFU_PREFECTURE for sid in direct)
            or result.annual.main_seed_school_ids):
        raise FutureCompetitionNotReady(
            "sealed autumn direct entrants cannot be seeded or enter a district"
        )
    return result
