"""Verified historical placement references for the 2026 season.

This is source evidence, not a patch to fictional/seeded outcomes. Explicitly
mapped 2026 FMT022 observations may be used as *unresolved fixtures* only after
the actual four qualified school IDs are independently locked. FMT025's
regional group assignment remains incomplete and is never auto-applied.
"""
from __future__ import annotations

import csv
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from .post_qualification_ranking import (
    RankingOnlyEventRuntime, load_post_qualification_profiles,
)
from .post_qualification_schedule import ScheduledRankingSidecar


VERIFIED = "verified_ranking_only"
NOT_RANKING = "qualification_decider_not_ranking"
KNOWN = {VERIFIED, NOT_RANKING}
REFERENCE_PATH = "competitions/2026/post_qualification_rank_observations.csv"


def load_2026_ranking_observations(data_dir: str | Path) -> list[dict]:
    path = Path(data_dir) / REFERENCE_PATH
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def validate_ranking_observations(
    data_dir: str | Path,
    *,
    year: int = 2026,
) -> dict:
    records = load_2026_ranking_observations(data_dir)
    profiles = load_post_qualification_profiles(data_dir)
    errors: list[str] = []
    seen: set[str] = set()
    pairs: set[tuple[str, str, str, str]] = set()
    counts = Counter()
    for row in records:
        rid, cid = row["reference_id"], row["competition_id"]
        context = f"{rid}/{cid}"
        if not rid or rid in seen:
            errors.append(f"{context}: duplicate reference_id")
        seen.add(rid)
        profile = profiles.get(cid)
        if not profile:
            errors.append(f"{context}: unexpected competition")
            continue
        if (row["stage_id"] != profile["stage_id"]
                or row["format_model_id"] != profile["format_model_id"]):
            errors.append(f"{context}: incompatible stage or format")
        if row["reference_classification"] not in KNOWN:
            errors.append(f"{context}: invalid fixture classification")
        if not row["source_url"].startswith("https://"):
            errors.append(f"{context}: verifiable HTTPS source required")
        try:
            if (date.fromisoformat(row["match_date"]).isoformat()
                    != row["match_date"]
                    or not row["match_date"].startswith(f"{year}-")):
                raise ValueError("wrong date")
        except ValueError:
            errors.append(f"{context}: invalid date")
        if not row["team1_name"] or not row["team2_name"]:
            errors.append(f"{context}: unknown teams")
        if row["team1_name"] == row["team2_name"]:
            errors.append(f"{context}: self match")
        try:
            s1, s2 = int(row["team1_score"]), int(row["team2_score"])
            round_no = int(row["ranking_round_no"])
            if s1 < 0 or s2 < 0 or s1 == s2 or round_no < 1:
                raise ValueError("invalid scoring")
            expected = row["team1_name"] if s1 > s2 else row["team2_name"]
            if row["winner_name"] != expected:
                raise ValueError("winner mismatch")
        except (ValueError, TypeError):
            errors.append(f"{context}: invalid score, round, or winner")
        fixture_key = (
            cid, row["match_date"],
            *sorted((row["team1_name"], row["team2_name"])),
        )
        if fixture_key in pairs:
            errors.append(f"{context}: duplicate dated matchup")
        pairs.add(fixture_key)
        if (row["reference_classification"] == NOT_RANKING
                and row["stage_group_id"]):
            errors.append(f"{context}: qualifying match cannot enter ranking sidecar")
        if row["format_model_id"] == "FMT022" and (
                row["stage_group_id"] not in ("SGR000171", "SGR000184")):
            errors.append(f"{context}: FMT022 requires a verified group")
        if (cid in ("CMP000135", "CMP000136")
                and row["reference_classification"] == VERIFIED):
            # The Hiroshima district sources also contain matches deciding
            # prefectural qualification. Post-cut proof is still missing;
            # never infer a nonblocking sidecar from a tournament title.
            errors.append(
                f"{context}: Hiroshima placement requires proof both teams qualified"
            )
        if row["reference_classification"] == VERIFIED:
            counts[cid] += 1
    for cid, size in (("CMP000140", 2), ("CMP000162", 3),
                      ("CMP000111", 13), ("CMP000112", 13)):
        if counts[cid] != size:
            errors.append(f"{cid}: expected {size} verified post-cut games")
    return {
        "year": year,
        "ok": not errors,
        "errors": errors,
        "record_count": len(records),
        "verified_ranking_match_count": sum(counts.values()),
        "qualification_only_count": sum(
            r["reference_classification"] == NOT_RANKING for r in records
        ),
        "verified_by_competition": dict(sorted(counts.items())),
        "unmapped_group_count": sum(
            not r["stage_group_id"] for r in records
            if r["reference_classification"] == VERIFIED
        ),
    }


def build_verified_fmt022_2026_sidecar(
    data_dir: str | Path,
    *,
    competition_id: str,
    school_id_by_official_name: Mapping[str, str],
    locked_school_ids: Sequence[str],
    qualification_locked_on: str,
) -> ScheduledRankingSidecar:
    """Create *unplayed* historical fixtures when all school IDs match.

    This method DOES NOT import actual historical score/winner values. The
    caller must explicitly resolve fictional match outcomes independently.
    """
    report = validate_ranking_observations(data_dir)
    if not report["ok"]:
        raise ValueError("invalid 2026 reference evidence: " + str(report["errors"]))
    profiles = load_post_qualification_profiles(data_dir)
    p = profiles.get(competition_id)
    if not p or p["format_model_id"] != "FMT022":
        raise ValueError("only FMT022 verified groups may be imported")
    rows = [r for r in load_2026_ranking_observations(data_dir)
            if r["competition_id"] == competition_id
            and r["reference_classification"] == VERIFIED]
    # Historical participants must be mapped explicitly: no school-name guessing.
    names = {name for r in rows
             for name in (r["team1_name"], r["team2_name"])}
    if set(school_id_by_official_name) != names:
        raise ValueError("all historical school names must be mapped exactly")
    mapped = dict(school_id_by_official_name)
    if (any(not sid for sid in mapped.values())
            or len(set(mapped.values())) != len(names)
            or set(mapped.values()) != set(locked_school_ids)
            or len(locked_school_ids) != 4):
        raise ValueError("qualified school IDs do not match historical four seeds")
    rounds = sorted({int(r["ranking_round_no"]) for r in rows})
    if rounds != list(range(1, len(rounds) + 1)):
        raise ValueError("invalid historical ranking round numbering")
    if any(len({r["match_date"] for r in rows
                if int(r["ranking_round_no"]) == round_no}) != 1
           for round_no in rounds):
        raise ValueError("ranking matches in a round require one actual date")
    r1 = [r for r in rows if int(r["ranking_round_no"]) == 1]
    if len(r1) != 2:
        raise ValueError("FMT022 first ranking round must contain two matches")
    pairs = [
        (mapped[r["team1_name"]], mapped[r["team2_name"]])
        for r in sorted(r1, key=lambda x: x["reference_id"])
    ]
    event = RankingOnlyEventRuntime.create(
        competition_id=competition_id,
        stage_id=p["stage_id"],
        stage_code="SEED_EVENT",
        group_id=r1[0]["stage_group_id"],
        format_model_id="FMT022",
        mode=p["ranking_event_mode"],
        locked_school_ids=list(locked_school_ids),
        pairings=pairs,
    )
    if event.mode == "semifinal_final":
        final = [r for r in rows if int(r["ranking_round_no"]) == 2]
        if len(final) != 1:
            raise ValueError("FMT022 needs one final")
        # Historical final teams must be among the four locked schools.
        if {mapped[final[0]["team1_name"]], mapped[final[0]["team2_name"]]} - set(
                locked_school_ids):
            raise ValueError("unqualified school in historical final")
    dates = [next(r["match_date"] for r in rows
                  if int(r["ranking_round_no"]) == round_no)
             for round_no in rounds]
    return ScheduledRankingSidecar.create(
        event, qualification_locked_on=qualification_locked_on,
        match_dates=dates,
    )
