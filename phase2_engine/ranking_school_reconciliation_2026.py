"""2026 school-ID / area membership proof for ranking-only reference fixtures.

Mapping is an independently verifiable bridge between historical source names,
the committed Phase 1 school/program/area masters and annual stage groups.

In particular, a played match between two registered areas must NOT be
silently assigned to one of the two groups.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Sequence

from .post_qualification_ranking import (
    RankingOnlyEventRuntime,
    load_post_qualification_profiles,
)
from .post_qualification_schedule import ScheduledRankingSidecar
from .ranking_reference_2026 import (
    VERIFIED, NOT_RANKING, load_2026_ranking_observations,
)


BASE = Path("competitions/2026")
MAP_FILE = BASE / "post_qualification_rank_school_mapping.csv"
ALIAS_FILE = BASE / "post_qualification_rank_school_aliases.csv"
PREFECTURES = {
    "CMP000111": "22", "CMP000112": "22",
    "CMP000135": "34", "CMP000136": "34",
    "CMP000140": "36", "CMP000162": "47",
}
STAGE_GROUP_SCHEMES = {
    "FMT025": {"22": "ASM000051", "34": "ASM000077"},
}
GROUP_MAPPED = "mapped_same_area_ranking_reference"
SEED_MAPPED = "verified_ready_for_locked_cohort_check"
CROSS_AREA = "review_cross_area_fixture"
EXCLUDED = "excluded_qualification_decider"


def _load(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_ranking_school_mapping_2026(
    data_dir: str | Path,
) -> list[dict[str, str]]:
    return _load(Path(data_dir) / MAP_FILE)


def audit_ranking_school_mapping_2026(data_dir: str | Path) -> dict:
    """Fail closed on incorrect IDs, aliases, groups or qualification labels."""
    root = Path(data_dir)
    observations = load_2026_ranking_observations(root)
    mappings = load_ranking_school_mapping_2026(root)
    aliases = _load(root / ALIAS_FILE)
    schools = _load(root / "master/schools.csv")
    programs = _load(root / "master/baseball_programs.csv")
    memberships = _load(root / "areas/school_area_memberships.csv")
    groups = _load(root / "competitions/competition_stage_groups.csv")

    errors: list[str] = []
    school_by_id = {s["school_id"]: s for s in schools}
    program_by_school = {
        p["school_id"]: p
        for p in programs
        if p["discipline"] == "hardball" and p["reference_year"] == "2026"
    }
    member_by_program_scheme: dict[tuple[str, str], list[str]] = {}
    for row in memberships:
        if row["reference_year"] != "2026":
            continue
        member_by_program_scheme.setdefault(
            (row["program_id"], row["scheme_id"]), []
        ).append(row["area_id"])
    group_by_comp_area = {}
    group_by_id = {}
    for group in groups:
        group_by_id[group["stage_group_id"]] = group
        for area_id in group["source_area_ids"].split(";"):
            if area_id:
                group_by_comp_area[group["competition_id"], area_id] = group

    alias_by_name = {}
    for alias in aliases:
        key = (alias["prefecture_code"], alias["observed_name"])
        if key in alias_by_name:
            errors.append(f"duplicate school alias {key}")
        alias_by_name[key] = alias
        master = school_by_id.get(alias["school_id"])
        if not master or (
            master["prefecture_code"] != alias["prefecture_code"]
            or master["official_name"] != alias["master_official_name"]
        ):
            errors.append(f"stale or incorrect master school alias {key}")
    if len(aliases) != 11:
        errors.append("expected 11 reviewed 2026 school-name aliases")

    obs_by_id = {r["reference_id"]: r for r in observations}
    seen: set[str] = set()
    observed_name_ids: dict[tuple[str, str], str] = {}
    mapping_counts: Counter[str] = Counter()
    area_gaps = []
    for mapping in mappings:
        rid = mapping["reference_id"]
        if rid in seen:
            errors.append(f"duplicate mapped fixture {rid}")
        seen.add(rid)
        observation = obs_by_id.get(rid)
        if observation is None:
            errors.append(f"mapping has no source observation: {rid}")
            continue
        cid = observation["competition_id"]
        pref = PREFECTURES.get(cid)
        if not pref or mapping["competition_id"] != cid:
            errors.append(f"competition mismatch {rid}")
            continue
        mapping_counts[mapping["mapping_status"]] += 1
        expected_group = None
        resolved_areas: list[str] = []
        for n in ("1", "2"):
            name = observation[f"team{n}_name"]
            school_id = mapping[f"team{n}_school_id"]
            school = school_by_id.get(school_id)
            if not school:
                errors.append(f"unknown school {rid} team{n}: {school_id}")
                continue
            if school["prefecture_code"] != pref:
                errors.append(f"wrong prefecture {rid} team{n}")
            name_key = (pref, name)
            old_id = observed_name_ids.setdefault(name_key, school_id)
            if old_id != school_id:
                errors.append(f"inconsistent school alias {rid}: {name}")
            alias = alias_by_name.get(name_key)
            if school["federation_name"] == name:
                method = "official_federation_name"
            elif alias and alias["school_id"] == school_id:
                method = "checked_official_name_alias"
            else:
                errors.append(f"unverified observed name {rid}: {name}")
                method = ""
            if mapping[f"team{n}_resolution"] != method:
                errors.append(f"resolution method mismatch {rid} team{n}")
            program = program_by_school.get(school_id)
            if not program:
                errors.append(f"missing 2026 hardball program {rid} team{n}")
            if observation["format_model_id"] == "FMT025":
                scheme = STAGE_GROUP_SCHEMES["FMT025"][pref]
                found = member_by_program_scheme.get(
                    (program["program_id"], scheme), []
                ) if program else []
                if len(found) != 1:
                    errors.append(f"missing or ambiguous 2026 area {rid} team{n}")
                    resolved_areas.append("")
                else:
                    if mapping[f"team{n}_area_id"] != found[0]:
                        errors.append(f"wrong 2026 area {rid} team{n}")
                    resolved_areas.append(found[0])
            elif mapping[f"team{n}_area_id"]:
                errors.append(f"FMT022 has unexpected regional area {rid}")
        status = mapping["mapping_status"]
        group_id = mapping["stage_group_id"]
        if observation["format_model_id"] == "FMT022":
            if status != SEED_MAPPED or group_id != observation["stage_group_id"]:
                errors.append(f"FMT022 locked seed group mismatch {rid}")
        elif observation["reference_classification"] == NOT_RANKING:
            if status != EXCLUDED:
                errors.append(f"qualification match was treated as ranking {rid}")
        elif len(resolved_areas) == 2 and resolved_areas[0] != resolved_areas[1]:
            if status != CROSS_AREA or group_id:
                errors.append(f"cross-area fixture must remain quarantined {rid}")
            area_gaps.append({
                "reference_id": rid, "competition_id": cid,
                "team1_area_id": resolved_areas[0],
                "team2_area_id": resolved_areas[1],
            })
        else:
            if status != GROUP_MAPPED or len(resolved_areas) != 2:
                errors.append(f"FMT025 same-area ranking not mapped {rid}")
            elif (
                (cid, resolved_areas[0]) not in group_by_comp_area
                or group_by_comp_area[cid, resolved_areas[0]]["stage_group_id"]
                != group_id
            ):
                errors.append(f"ranking stage group differs from master {rid}")

        if group_id:
            group = group_by_id.get(group_id)
            if (not group or group["competition_id"] != cid
                    or group["stage_id"] != observation["stage_id"]):
                errors.append(f"ranking stage group identity mismatch {rid}")
        if observation["mapping_status"] != status:
            errors.append(f"observation and school mapping status disagree {rid}")

    if seen != set(obs_by_id):
        errors.append("not all ranking reference fixtures were mapped")
    expected = {
        SEED_MAPPED: 5, GROUP_MAPPED: 25, CROSS_AREA: 1, EXCLUDED: 3
    }
    if dict(mapping_counts) != expected:
        errors.append(f"unexpected mapped fixture categories: {dict(mapping_counts)}")
    return {
        "ok": not errors,
        "errors": errors,
        "year": 2026,
        "school_master_count": len(schools),
        "baseball_program_count": len(programs),
        "area_membership_count": len(memberships),
        "observation_count": len(observations),
        "unique_observed_school_count": len(observed_name_ids),
        "reviewed_alias_count": len(aliases),
        "classification_counts": dict(mapping_counts),
        "cross_area_review": area_gaps,
    }


def build_verified_fmt025_2026_daily_sidecar(
    data_dir: str | Path,
    *,
    competition_id: str,
    stage_group_id: str,
    match_date: str,
    locked_school_ids: Sequence[str],
    qualification_locked_on: str,
) -> ScheduledRankingSidecar:
    """Create one explicit date's optional FMT025 matches, without winners.

    Some 2026 group ranking fixtures occurred on different dates. The current
    ScheduledCompetitionRuntime permits only one sidecar per group; callers
    must not attach overlapping batches for that group until a separate
    multi-day ranking instance-key contract exists.
    """
    report = audit_ranking_school_mapping_2026(data_dir)
    if not report["ok"]:
        raise ValueError("unverified school or area mapping: " + str(report["errors"]))
    profile = load_post_qualification_profiles(data_dir).get(competition_id)
    if not profile or profile["format_model_id"] != "FMT025":
        raise ValueError("only FMT025 is supported by this group/day adapter")
    observation_by_id = {
        r["reference_id"]: r for r in load_2026_ranking_observations(data_dir)
    }
    candidates = [
        (r, observation_by_id[r["reference_id"]])
        for r in load_ranking_school_mapping_2026(data_dir)
        if (r["competition_id"] == competition_id
            and r["stage_group_id"] == stage_group_id
            and r["mapping_status"] == GROUP_MAPPED
            and observation_by_id[r["reference_id"]]["match_date"] == match_date)
    ]
    if not candidates:
        raise ValueError("no verified same-area ranking fixtures for this group/date")
    participants = [
        sid for mapping, _ in candidates
        for sid in (mapping["team1_school_id"], mapping["team2_school_id"])
    ]
    if len(participants) != len(set(participants)):
        raise ValueError("a school cannot appear twice in the same dated ranking round")
    if not set(participants).issubset(locked_school_ids):
        raise ValueError("not all ranking participants are locked qualifiers")
    pairings = [
        (m["team1_school_id"], m["team2_school_id"]) for m, _ in candidates
    ]
    state = RankingOnlyEventRuntime.create(
        competition_id=competition_id,
        stage_id=profile["stage_id"],
        stage_code="BRANCH_QUALIFIER",
        group_id=stage_group_id,
        format_model_id="FMT025",
        mode=profile["ranking_event_mode"],
        locked_school_ids=locked_school_ids,
        pairings=pairings,
    )
    return ScheduledRankingSidecar.create(
        state,
        qualification_locked_on=qualification_locked_on,
        match_dates=[match_date],
    )
