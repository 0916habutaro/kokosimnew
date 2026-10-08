"""Stage 13E-3G-12: 24 supplemental dated berth-deciding games.

The games were checked against *secondary* district result listings.
This does NOT establish complete official federation PDF transcription
or authorize any optional ranking-only FMT025 fixture.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_qualification_timeline_2026 import (
    TIMELINE_FILE, audit_2026_hiroshima_qualification_timeline,
)
from .hiroshima_berth_roster_2026 import (
    ROSTER_FILE, audit_2026_hiroshima_prefectural_berth_roster,
)

EVIDENCE_FILE = "competitions/2026/hiroshima_award_game_evidence_stage13e3g12.csv"
QUEUE_FILE = "competitions/2026/hiroshima_qualification_missing_award_queue_2026.csv"
REGIONS = {("spring", "east"), ("spring", "south"), ("autumn", "east")}


def audit_2026_hiroshima_stage13e3g12(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    evidence = _read(root, EVIDENCE_FILE)
    matches = _read(root, TIMELINE_FILE)
    roster = _read(root, ROSTER_FILE)
    queue = _read(root, QUEUE_FILE)
    timeline = audit_2026_hiroshima_qualification_timeline(root)
    berth = audit_2026_hiroshima_prefectural_berth_roster(root)
    errors = list(timeline["errors"]) + list(berth["errors"])
    by_id = {m["match_id"]: m for m in matches}
    roster_by_school = {
        (r["season"], r["district_code"], r["school_name"]): r
        for r in roster
    }
    counts = Counter()
    seen_matches = set()
    historical_awards = {
        (r["season"], r["district_code"], r["winner_name"])
        for r in matches if r["winner_berth_status"] == "berth_award"
    }

    for row in evidence:
        ident = row["match_id"]
        if ident in seen_matches or ident not in by_id:
            errors.append(f"evidence duplicate or match missing: {ident}")
            continue
        seen_matches.add(ident)
        game = by_id[ident]
        region = (row["season"], row["district_code"])
        counts[region] += 1
        if region not in REGIONS:
            errors.append(f"new award recorded outside researched districts: {ident}")
        if game["season"] != row["season"] or game["district_code"] != row["district_code"]:
            errors.append(f"evidence district/season mismatch: {ident}")
        if (
            game["winner_berth_status"] != "berth_award"
            or game["winner_name"] != row["qualifying_school"]
            or game["team1_name"] != row["qualifying_school"]
            or game["team2_name"] != row["losing_school"]
            or row["score"] != f"{game['team1_score']}-{game['team2_score']}"
            or game["match_date"] != row["date"]
            or game["round_label"] != row["recorded_round"]
        ):
            errors.append(f"award evidence contradicts dated game: {ident}")
        key = (row["season"], row["district_code"], row["qualifying_school"])
        r = roster_by_school.get(key)
        if r is None or r["route_block"] != row["route_block"]:
            errors.append(f"award school missing or in wrong official route block: {ident}")
        if game["source_url"] != row["source_url"]:
            errors.append(f"unmatched source provenance: {ident}")
        if (
            row["official_pdf_match_review"] != "not_inspected"
            or row["verification_basis"] != "secondary_dated_result_page"
            or game["verification_scope"] != "secondary_dated_result_page"
        ):
            errors.append(f"unsupported federation PDF validation claim: {ident}")
        if key not in historical_awards:
            errors.append(f"unlocked historical berth: {ident}")

    if len(evidence) != 24 or set(counts) != REGIONS or set(counts.values()) != {8}:
        errors.append(f"expected 8 new award games from each of 3 groups, found {dict(counts)}")
    if len(matches) != 223 or len(historical_awards) != 63:
        errors.append("Stage 13E-3G-12 match total or unique qualification locks changed")
    expected_missing = {
        (r["season"], r["district_code"], r["school_name"])
        for r in roster
        if r["qualification_basis"] != "selection_tournament_exemption"
        and (r["season"], r["district_code"], r["school_name"]) not in historical_awards
    }
    actual_missing = {
        (r["season"], r["district_code"], r["school_name"])
        for r in queue
    }
    if actual_missing != expected_missing or len(queue) != 0:
        errors.append(f"remaining gap queue and qualifying roster differ: {len(queue)}")
    if len(actual_missing) != len(queue):
        errors.append("remaining gap queue contains duplicate schools")
    if any(r["status"] != "award_match_not_yet_documented" for r in queue):
        errors.append("unsupported declared status in historical evidence queue")

    # The distinctive comeback paths must not be converted to ranking-only games.
    by_winner = {
        (m["season"], m["district_code"], m["winner_name"]): m
        for m in matches if m["winner_berth_status"] == "berth_award"
    }
    for season, district, school, date, losing_team in (
        ("spring", "east", "総合技術", "2026-04-05", "大門"),
        ("autumn", "east", "神辺旭", "2026-09-05", "英数学館"),
    ):
        x = by_winner.get((season, district, school))
        if not x or x["match_date"] != date or x["team2_name"] != losing_team:
            errors.append(f"repechage route lost for {season}/{school}")

    return {
        "ok": not errors,
        "errors": errors,
        "supplemental_qualifying_games": len(evidence),
        "cumulative_dated_matches": len(matches),
        "cumulative_evidenced_qualification_events": len(historical_awards),
        "remaining_unlinked_qualifying_schools": len(queue),
        "supplemental_by_district": {f"{s}_{d}": counts[(s,d)] for s,d in sorted(REGIONS)},
        "historic_match_timeline_pass": timeline["ok"],
        "prefectural_roster_pass": berth["ok"],
        "official_federation_pdf_full_review_complete": False,
        "ranking_only_post_qualification_games_proven": 0,
        "fmt025_release_allowed": False,
        "review_scope": "supplemental_secondary_dated_match_winner_evidence_only",
    }
