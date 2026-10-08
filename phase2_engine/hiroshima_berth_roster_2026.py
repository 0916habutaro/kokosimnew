"""2026 Hiroshima spring/autumn berth-roster reconciliation (source-granular).

A secondary dated-results website lists 32 prefectural MAIN entrants in
each season.  The federation also publishes official PDF entrant lists,
but their contents have NOT been compared in this audit.  The spring
west exception is a preliminary-exempt team (Sotoku), not a seventh
on-field winner.  Never use these observations to generate actual game
results, award runtime slots, or release FMT025.
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from .hiroshima_match_level_2026 import _read, EXPECTED, SEASONS
from .hiroshima_qualification_timeline_2026 import (
    TIMELINE_FILE, audit_2026_hiroshima_qualification_timeline,
)

ROSTER_FILE = "competitions/2026/hiroshima_2026_prefectural_main_berth_roster.csv"
STAGE_GROUP_FILE = "competitions/competition_stage_groups.csv"
EXPECTED_SLOTS = {
    ("spring", "west"): 7, ("spring", "north"): 7,
    ("spring", "south"): 9, ("spring", "east"): 9,
    ("autumn", "west"): 7, ("autumn", "north"): 6,
    ("autumn", "south"): 10, ("autumn", "east"): 9,
}
EXPECTED_SPRING_EXEMPT = ("spring", "west", "崇徳")


def audit_2026_hiroshima_prefectural_berth_roster(data_dir: str | Path) -> dict:
    """Reconcile entrant count, district assignment, exemption and sampled wins.

    `district_result_list` documents a place in the published secondary
    entrant summary, NOT a proven game time / direct official-PDF lock.
    """
    root = Path(data_dir)
    roster = _read(root, ROSTER_FILE)
    stage_groups = {
        r["stage_group_id"]: r for r in _read(root, STAGE_GROUP_FILE)
    }
    timeline = _read(root, TIMELINE_FILE)
    previous = audit_2026_hiroshima_qualification_timeline(root)
    errors: list[str] = list(previous["errors"])
    roster_ids: set[str] = set()
    team_keys: set[tuple[str, str]] = set()
    district_entries: dict[tuple[str, str], dict[str, dict]] = {}
    expected_by_group: dict[tuple[str, str], str] = {}
    stage_quota: dict[tuple[str, str], int] = {}
    for group in stage_groups.values():
        if group["stage_group_id"] not in {
            f"SGR{i:06d}" for i in range(140, 148)
        }:
            continue
        season = next((s for s, c in SEASONS.items()
                       if c == group["competition_id"]), None)
        district = next((d for d in ("west", "north", "south", "east")
                         if d == {
                             "広島西部地区": "west", "広島北部地区": "north",
                             "広島南部地区": "south", "広島東部地区": "east",
                         }.get(group["group_name"])), None)
        if season is None or district is None:
            errors.append(f"invalid Hiroshima official stage group: {group['stage_group_id']}")
            continue
        key = (season, district)
        if key in expected_by_group:
            errors.append(f"duplicate stage group: {key}")
        expected_by_group[key] = group["stage_group_id"]
        try:
            stage_quota[key] = int(group["advance_slots_to_next"])
        except ValueError:
            errors.append(f"invalid stage quota: {key}")

    for r in roster:
        ident = r["roster_id"]
        sd = (r["season"], r["district_code"])
        name = r["school_name"]
        if not ident or ident in roster_ids:
            errors.append(f"duplicate/blank roster ID: {ident}")
        roster_ids.add(ident)
        if sd not in EXPECTED or r["competition_id"] != SEASONS.get(r["season"]):
            errors.append(f"unsupported season/district/competition: {ident}")
        if r["stage_group_id"] != expected_by_group.get(sd):
            errors.append(f"incorrect stage group: {ident}")
        if not name or (r["season"], name) in team_keys:
            errors.append(f"duplicate or blank seasonal qualifier school: {ident}")
        team_keys.add((r["season"], name))
        byschool = district_entries.setdefault(sd, {})
        if name in byschool:
            errors.append(f"duplicate district qualifier: {ident}")
        byschool[name] = r
        if r["route_block"] not in set("ABCDEF") | {"EXEMPT"}:
            errors.append(f"invalid qualifier block: {ident}")
        exemption = (r["season"], r["district_code"], name) == EXPECTED_SPRING_EXEMPT
        if exemption != (r["qualification_basis"] == "selection_tournament_exemption"
                          and r["route_block"] == "EXEMPT"):
            errors.append(f"incorrect exemption classification: {ident}")
        if not exemption and r["qualification_basis"] != "district_result_list":
            errors.append(f"incorrect qualifier classification: {ident}")
        expected_source = (
            "https://www.reiwa-hb-sch-and-res-gatr-fod.com/hiroshima/"
            f"2026{r['season']}/{r['district_code']}-area/"
        )
        if r["source_url"] != expected_source:
            errors.append(f"mismatched regional source: {ident}")
        if (r["provenance_level"] != "secondary_result_summary"
                or r["federation_pdf_comparison"] != "not_verified"):
            errors.append(f"unsupported official PDF verification claim: {ident}")

    if set(district_entries) != EXPECTED or len(roster) != 64:
        errors.append("spring+autumn roster must contain exactly 64 entrants in eight districts")
    if set(expected_by_group) != EXPECTED:
        errors.append("all eight official stage groups must exist")
    exemptions = [r for r in roster if r["qualification_basis"] == "selection_tournament_exemption"]
    if (len(exemptions) != 1
            or (exemptions[0]["season"], exemptions[0]["district_code"],
                exemptions[0]["school_name"]) != EXPECTED_SPRING_EXEMPT):
        errors.append("spring-west preliminary exemption must be exactly one Sotoku")
    for sd, target in EXPECTED_SLOTS.items():
        actual = len(district_entries.get(sd, {}))
        if actual != target:
            errors.append(f"district entrant quota mismatch {sd}: {actual} vs {target}")
        if stage_quota.get(sd) != target:
            errors.append(f"stage-group quota mismatch {sd}: {stage_quota.get(sd)} vs {target}")

    # A berth-awarding historical game must award to a school in the
    # observed entrant list for the *same season and district*.
    locks = {}
    for game in timeline:
        if game["winner_berth_status"] != "berth_award":
            continue
        sd = (game["season"], game["district_code"])
        school = game["winner_name"]
        if school not in district_entries.get(sd, {}):
            errors.append(
                f"game awards berth to school absent from district entrant roster: {game['match_id']}"
            )
        if (sd, school) in locks:
            errors.append(f"duplicated sampled historical berth event: {game['match_id']}")
        locks[(sd, school)] = game["match_id"]
    for sd, school in locks:
        if district_entries.get(sd, {}).get(school, {}).get("qualification_basis") != "district_result_list":
            errors.append(f"berth-award game incorrectly applied to exempt school: {sd}/{school}")

    counted = Counter(r["season"] for r in roster)
    if counted != {"spring": 32, "autumn": 32}:
        errors.append(f"seasonal MAIN entrant counts differ: {dict(counted)}")
    if len(locks) != 63:
        errors.append(f"Stage13E-3G-9 historical lock anchor count changed: {len(locks)}")
    qualifier_without_sampled_lock = sum(
        1 for sd, entrants in district_entries.items() for name, r in entrants.items()
        if r["qualification_basis"] != "selection_tournament_exemption"
        and (sd, name) not in locks
    )
    return {
        "ok": not errors, "errors": errors, "season_berth_counts": dict(counted),
        "district_berth_counts": {
            f"{s}_{d}": len(district_entries.get((s,d), {})) for s,d in sorted(EXPECTED)
        },
        "stage_group_quota_sum_by_season": {
            s: sum(stage_quota.get((s,d), 0) for d in ("west","north","south","east"))
            for s in SEASONS
        },
        "confirmed_in_secondary_source_exemption": ["崇徳"] if len(exemptions) == 1 else [],
        "sampled_match_berth_winners_reconciled": len(locks),
        "qualifying_teams_lacking_sampled_award_game": qualifier_without_sampled_lock,
        "official_pdf_roster_comparison_complete": False,
        "match_by_match_federation_pdf_census_complete": False,
        "secondary_source_qualifier_count": len(roster),
        "fmt025_release_allowed": False,
        "previous_timeline_ok": previous["ok"],
        "review_scope": "eight_regional_secondary_qualifier_lists_reconciled_not_official_pdf",
    }
