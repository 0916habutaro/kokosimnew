"""Audit the final 22 *berth-deciding* results in the 2026 Hiroshima sample.

Every game is a secondary published result. The 2026 spring/autumn
district match inventories and the federation's bracket PDF bodies have
NOT been exhaustively audited: 63/63 observed nonexempt MAIN entrants
with a winning qualification game is not 100% of played matches.
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
from .hiroshima_stage13e3g12 import (
    EVIDENCE_FILE as PREVIOUS_EVIDENCE_FILE, QUEUE_FILE,
    audit_2026_hiroshima_stage13e3g12,
)

EVIDENCE_FILE = "competitions/2026/hiroshima_award_game_evidence_stage13e3g13.csv"
EXPECTED_REGIONS = {
    ("spring", "north"): 6, ("spring", "west"): 1,
    ("autumn", "west"): 6, ("autumn", "north"): 5,
    ("autumn", "south"): 4,
}
JOINT_LOSERS = {
    "HT20260075": "加計芸北・千代田・三次青陵",
    "HT20260083": "並木学院・五日市",
}


def audit_2026_hiroshima_stage13e3g13(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    evidence = _read(root, EVIDENCE_FILE)
    matches = _read(root, TIMELINE_FILE)
    roster = _read(root, ROSTER_FILE)
    queue = _read(root, QUEUE_FILE)
    previous = audit_2026_hiroshima_stage13e3g12(root)
    timeline = audit_2026_hiroshima_qualification_timeline(root)
    berth = audit_2026_hiroshima_prefectural_berth_roster(root)
    errors = list(previous["errors"]) + list(timeline["errors"]) + list(berth["errors"])
    by_id = {m["match_id"]: m for m in matches}
    entrants = {
        (x["season"], x["district_code"], x["school_name"]): x
        for x in roster
    }
    count_by_region = Counter()
    seen_ids = set()
    for entry in evidence:
        ident = entry["match_id"]
        if not ident or ident in seen_ids or ident not in by_id:
            errors.append(f"duplicate or missing last-stage match: {ident}")
            continue
        seen_ids.add(ident)
        m = by_id[ident]
        region = (entry["season"], entry["district_code"])
        count_by_region[region] += 1
        if region not in EXPECTED_REGIONS:
            errors.append(f"last-stage game outside expected district: {ident}")
        if (entry["season"] != m["season"]
                or entry["district_code"] != m["district_code"]
                or entry["date"] != m["match_date"]
                or entry["qualifying_school"] != m["winner_name"]
                or entry["qualifying_school"] != m["team1_name"]
                or entry["losing_team_display"] != m["team2_name"]
                or entry["score"] != f"{m['team1_score']}-{m['team2_score']}"
                or entry["round_label"] != m["round_label"]
                or m["winner_berth_status"] != "berth_award"):
            errors.append(f"unmatched result/qualification lock: {ident}")
        roster_row = entrants.get((*region, entry["qualifying_school"]))
        if roster_row is None or roster_row["route_block"] != entry["route_block"]:
            errors.append(f"missing MAIN entrant or wrong qualifier route: {ident}")
        if (m["source_url"] != entry["source_url"]
                or entry["source_level"] != "secondary_dated_result_page"
                or m["verification_scope"] != "secondary_dated_result_page"
                or entry["official_pdf_inspected"] != "no"
                or entry["research_status"] != "berth_award_result_recorded"):
            errors.append(f"unsupported federation PDF/source confirmation: {ident}")
        composite = ident in JOINT_LOSERS
        if entry["combined_team_display"] != ("yes" if composite else "no"):
            errors.append(f"invalid combined-team classification: {ident}")
        if composite and (entry["losing_team_display"] != JOINT_LOSERS[ident]
                          or m["team2_name"] != JOINT_LOSERS[ident]):
            errors.append(f"combined-team display lost: {ident}")

    if len(evidence) != 22 or dict(count_by_region) != EXPECTED_REGIONS:
        errors.append(f"expected 22 new winning berth deciders in five regions, found {dict(count_by_region)}")
    if any(x["match_id"] not in seen_ids for x in evidence):
        errors.append("some evidence rows have empty or duplicate match ID")
    if len(matches) != 83:
        errors.append(f"expected 83 cumulative dated fixtures, got {len(matches)}")
    all_awards = {
        (m["season"], m["district_code"], m["winner_name"])
        for m in matches if m["winner_berth_status"] == "berth_award"
    }
    nonexempt = {
        (r["season"], r["district_code"], r["school_name"])
        for r in roster if r["qualification_basis"] == "district_result_list"
    }
    exemption = [r for r in roster if r["qualification_basis"] == "selection_tournament_exemption"]
    if (len(all_awards) != 63 or len(nonexempt) != 63
            or all_awards != nonexempt or len(exemption) != 1):
        errors.append("historical qualification winners do not cover the 63 non-exempt seasonal entrants exactly")
    if queue:
        errors.append(f"expected 0 missing qualification awards, found {len(queue)}")
    if not (previous["ok"] and timeline["ok"] and berth["ok"]):
        errors.append("earlier Stage 3G-9/10/12 audits failed")
    return {
        "ok": not errors,
        "errors": errors,
        "newly_documented_qualification_games": len(evidence),
        "new_games_by_region": {f"{s}_{d}": count_by_region[(s,d)]
                                for s,d in sorted(EXPECTED_REGIONS)},
        "cumulative_sample_match_count": len(matches),
        "match_proven_qualification_school_count": len(all_awards),
        "exempt_seasonal_entrant_count": len(exemption),
        "secondary_source_seasonal_entrant_count": len(roster),
        "secondary_roster_qualification_award_coverage_complete": (
            all_awards == nonexempt and len(exemption) == 1 and not queue
        ),
        "qualification_award_investigation_queue_remaining": len(queue),
        "all_official_federation_pdf_game_cards_inspected": False,
        "ranking_only_optional_matches_confirmed": 0,
        "fmt025_release_allowed": False,
        "scope": "full_berth_winner_coverage_not_full_match_census",
    }
