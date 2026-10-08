"""Stage 13E-3G-14: audit two source-page fixture inventories.

Distinguishes a manually checked secondary HTML results census (only
spring-west and autumn-east) from the eight official federation bracket
PDFs, whose *links* are known but whose body contents are inaccessible.
Never promote an HTML census to official PDF verification or FMT025.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_qualification_timeline_2026 import (
    TIMELINE_FILE, audit_2026_hiroshima_qualification_timeline,
)
from .hiroshima_stage13e3g13 import audit_2026_hiroshima_stage13e3g13

ADDITIONS = "competitions/2026/hiroshima_nonaward_fixtures_stage13e3g14.csv"
CENSUS = "competitions/2026/hiroshima_fixture_census_2026.csv"
OFFICIAL_PDF_LIST = "competitions/2026/hiroshima_bracket_pdf_review_2026.csv"
COMPLETE_SECONDARY = {("spring", "west"): 24, ("autumn", "east"): 30}
EXPECTED_DISTRICTS = {
    ("spring", "west"), ("spring", "north"), ("spring", "south"), ("spring", "east"),
    ("autumn", "west"), ("autumn", "north"), ("autumn", "south"), ("autumn", "east"),
}


def audit_2026_hiroshima_stage13e3g14(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    fixtures = _read(root, TIMELINE_FILE)
    additions = _read(root, ADDITIONS)
    matrix = _read(root, CENSUS)
    official = _read(root, OFFICIAL_PDF_LIST)
    previous = audit_2026_hiroshima_stage13e3g13(root)
    timeline = audit_2026_hiroshima_qualification_timeline(root)
    errors = list(previous["errors"]) + list(timeline["errors"])

    byid = {r["match_id"]: r for r in fixtures}
    counts = Counter((r["season"], r["district_code"]) for r in fixtures)
    newcounts = Counter()
    seen = set()
    for r in additions:
        mid = r["match_id"]
        if mid in seen or mid not in byid:
            errors.append(f"missing or duplicated source-page fixture: {mid}")
            continue
        seen.add(mid)
        f = byid[mid]
        sd = (r["season"], r["district_code"])
        newcounts[sd] += 1
        if sd not in COMPLETE_SECONDARY:
            errors.append(f"unapproved Stage14 supplementary group: {mid}")
        for csv_key, live_key in (
            ("season", "season"), ("district_code", "district_code"),
            ("match_date", "match_date"), ("start_time", "start_time"),
            ("winner_name", "winner_name"), ("loser_name", "team2_name"),
            ("winner_score", "team1_score"), ("loser_score", "team2_score"),
            ("round_label", "round_label"), ("winner_berth_status", "winner_berth_status"),
            ("secondary_source_url", "source_url"),
        ):
            if r[csv_key] != f[live_key]:
                errors.append(f"source page evidence mismatch {mid} {csv_key}")
        if (f["team1_name"] != r["winner_name"]
                or f["winner_berth_status"] != "not_proven"
                or f["verification_scope"] != "secondary_dated_result_page"
                or r["official_pdf_reconciled"] != "no"):
            errors.append(f"unsupported qualification or official PDF claim: {mid}")

    if newcounts != {("spring", "west"): 4, ("autumn", "east"): 21}:
        errors.append(f"expected 4+21 supplementary non-award matches, found {dict(newcounts)}")
    if len(additions) != 25 or len(fixtures) != 108:
        errors.append(f"expected 108 total matches/25 additions, found {len(fixtures)}/{len(additions)}")

    pdf_by_group = {(r["season"], r["district_code"]): r for r in official}
    matrix_by_group = {(r["season"], r["district_code"]): r for r in matrix}
    if (len(matrix) != 8 or set(matrix_by_group) != EXPECTED_DISTRICTS
            or len(official) != 8 or set(pdf_by_group) != EXPECTED_DISTRICTS):
        errors.append("all eight PDF records and secondary-census statuses are required")
    for sd in EXPECTED_DISTRICTS:
        m = matrix_by_group.get(sd)
        p = pdf_by_group.get(sd)
        if not m or not p:
            continue
        if any(m[k] != p[k] for k in ("season","district_code","competition_id","stage_group_id")):
            errors.append(f"PDF row identity mismatch {sd}")
        if (m["pdf_url"] != p["official_pdf_url"]
                or m["secondary_source_url"] != p["secondary_result_url"]
                or p["source_access"] != "official_link_located_pdf_not_read"
                or p["full_fixture_review_status"] != "pending_full_match_review"
                or m["pdf_body_status"] != "link_only_pdf_body_inaccessible"
                or m["full_official_census_complete"] != "no"
                or m["candidate_ranking_only_proved"] != "no"):
            errors.append(f"unsupported PDF completeness claim {sd}")
        if m["registered_dated_result_games"] != str(counts[sd]):
            errors.append(f"registered result count disagrees with district timeline {sd}")
        if sd in COMPLETE_SECONDARY:
            if (m["secondary_html_status"] != "full_displayed_results_transcribed"
                    or m["secondary_listed_games_transcribed"] != str(COMPLETE_SECONDARY[sd])
                    or counts[sd] != COMPLETE_SECONDARY[sd]):
                errors.append(f"secondary HTML census mismatch {sd}")
        elif (m["secondary_html_status"] != "pending_full_result_transcription"
              or m["secondary_listed_games_transcribed"]):
            errors.append(f"unsubstantiated secondary complete status {sd}")

    qualification_count = sum(x["winner_berth_status"] == "berth_award" for x in fixtures)
    if qualification_count != 63:
        errors.append(f"63 historical qualification locks must remain unchanged: {qualification_count}")
    both_previously_qualified = timeline["potential_both_locked_match_ids"]

    return {
        "ok": not errors,
        "errors": errors,
        "source_page_new_non_award_fixtures": len(additions),
        "historical_sample_fixture_count": len(fixtures),
        "verified_berth_award_events": qualification_count,
        "secondarily_fully_transcribed_district_seasons": 2,
        "district_seasons_without_complete_secondary_transcription": 6,
        "source_page_transcribed_fixture_counts": {
            f"{s}_{d}": counts[(s,d)] for s,d in sorted(COMPLETE_SECONDARY)
        },
        "stage14_new_by_district": {
            f"{s}_{d}": newcounts[(s,d)] for s,d in sorted(COMPLETE_SECONDARY)
        },
        "both_previously_qualified_match_candidates": list(both_previously_qualified),
        "candidate_classification_is_ranking_evidence": False,
        "official_federation_pdf_bodies_read": 0,
        "full_official_match_census_complete": False,
        "fmt025_release_allowed": False,
        "review_scope": "two_complete_secondary_html_result_pages_not_any_official_pdf_body",
    }
