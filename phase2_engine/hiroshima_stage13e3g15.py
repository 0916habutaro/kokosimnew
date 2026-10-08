"""2026 Hiroshima: final six secondary HTML district-season result censuses.

All eight source pages are transcribed at match level. This is a
secondary-publication inventory, NOT a reading of the eight official
federation PDF brackets. FMT025 therefore remains design_pending.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g14 import (
    ALL_SECONDARY_COUNTS, CENSUS, OFFICIAL_PDF_LIST,
    audit_2026_hiroshima_stage13e3g14,
)
from .hiroshima_qualification_timeline_2026 import (
    TIMELINE_FILE, audit_2026_hiroshima_qualification_timeline,
)

ADDITIONS = "competitions/2026/hiroshima_nonaward_fixtures_stage13e3g15.csv"
EXPECTED_NEW = {
    ("spring", "north"): 17, ("spring", "south"): 24, ("spring", "east"): 22,
    ("autumn", "west"): 18, ("autumn", "north"): 16, ("autumn", "south"): 18,
}
EXISTING_COMPLETE = {("spring", "west"), ("autumn", "east")}


def audit_2026_hiroshima_stage13e3g15(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    fixtures = _read(root, TIMELINE_FILE)
    new = _read(root, ADDITIONS)
    matrix = _read(root, CENSUS)
    official = _read(root, OFFICIAL_PDF_LIST)
    prior = audit_2026_hiroshima_stage13e3g14(root)
    timeline = audit_2026_hiroshima_qualification_timeline(root)
    errors = list(prior["errors"]) + list(timeline["errors"])
    by_id = {r["match_id"]: r for r in fixtures}
    if len(by_id) != len(fixtures):
        errors.append("duplicate fixture match_id")

    seen_fixtures = set()
    for m in fixtures:
        key = (m["season"], m["match_date"], tuple(sorted((m["team1_name"], m["team2_name"]))))
        if key in seen_fixtures:
            errors.append(f"duplicate fixture season/date/pair: {m['match_id']}")
        seen_fixtures.add(key)

    new_by_region = Counter()
    new_ids = set()
    for row in new:
        mid = row["match_id"]
        if not mid or mid in new_ids or mid not in by_id:
            errors.append(f"missing or duplicate secondary fixture ID: {mid}")
            continue
        new_ids.add(mid)
        r = by_id[mid]
        sd = (row["season"], row["district_code"])
        new_by_region[sd] += 1
        if sd not in EXPECTED_NEW:
            errors.append(f"unexpected supplemental district: {mid}")
        for src_col, timeline_col in (
            ("season", "season"), ("district_code", "district_code"),
            ("match_date", "match_date"), ("start_time", "start_time"),
            ("winner_name", "winner_name"), ("loser_name", "team2_name"),
            ("winner_score", "team1_score"), ("loser_score", "team2_score"),
            ("round_label", "round_label"), ("source_url", "source_url"),
        ):
            if row[src_col] != r[timeline_col]:
                errors.append(f"source-page match mismatch {mid} / {src_col}")
        if row["winner_name"] != r["team1_name"]:
            errors.append(f"winning side has changed: {mid}")
        if (r["winner_berth_status"] != "not_proven"
            or row["qualification_effect_confirmed"] != "no"
            or row["source_scope"] != "published_secondary_html"
            or row["official_pdf_compared"] != "no"
            or r["verification_scope"] != "secondary_dated_result_page"):
            errors.append(f"unproven official PDF or rank-only assertion: {mid}")
        if not row["route_block"]:
            errors.append(f"missing route block {mid}")

    if new_by_region != Counter(EXPECTED_NEW) or len(new) != 115:
        errors.append(f"115 new non-award games / six groups required: {dict(new_by_region)}")
    if len(fixtures) != 223:
        errors.append(f"223 total secondary-source fixture rows expected, got {len(fixtures)}")

    group_counts = Counter((m["season"], m["district_code"]) for m in fixtures)
    if group_counts != Counter(ALL_SECONDARY_COUNTS):
        errors.append(f"all eight secondary source-page totals must reconcile: {dict(group_counts)}")
    mat = {(r["season"],r["district_code"]):r for r in matrix}
    official_map = {(r["season"],r["district_code"]):r for r in official}
    if len(mat) != 8 or len(official_map) != 8:
        errors.append("eight independent district season matrix/PDF link records required")
    for sd, expected in ALL_SECONDARY_COUNTS.items():
        m = mat.get(sd)
        p = official_map.get(sd)
        if m is None or p is None:
            errors.append(f"missing PDF link or HTML result-source group {sd}")
            continue
        if (m["secondary_html_status"] != "full_displayed_results_transcribed"
                or m["secondary_listed_games_transcribed"] != str(expected)
                or m["registered_dated_result_games"] != str(expected)
                or m["secondary_source_url"] != p["secondary_result_url"]
                or m["pdf_url"] != p["official_pdf_url"]):
            errors.append(f"published result count or URL mismatch {sd}")
        if (m["pdf_body_status"] != "link_only_pdf_body_inaccessible"
                or m["full_official_census_complete"] != "no"
                or m["candidate_ranking_only_proved"] != "no"
                or p["source_access"] != "official_link_located_pdf_not_read"
                or p["full_fixture_review_status"] != "pending_full_match_review"):
            errors.append(f"unsupported official federation PDF completeness {sd}")

    qualifications = sum(m["winner_berth_status"] == "berth_award" for m in fixtures)
    if qualifications != 63:
        errors.append(f"63 winning qualification locks must remain; now {qualifications}")
    unknown = sum(m["winner_berth_status"] == "not_proven" for m in fixtures)
    if unknown != 160:
        errors.append(f"nonaward fixtures must remain 160 unclassified; now {unknown}")
    if not (prior["ok"] and timeline["ok"]):
        errors.append("earlier independent source/result audits must pass")

    return {
        "ok": not errors, "errors": errors,
        "new_partial_qualifier_matches": len(new),
        "cumulative_source_page_matches": len(fixtures),
        "nonaward_matches_not_conclusively_classified": unknown,
        "confirmed_qualification_award_matches": qualifications,
        "added_by_district_season": {f"{s}_{d}": new_by_region[(s,d)]
                                     for s,d in sorted(EXPECTED_NEW)},
        "all_eight_html_result_censuses": {f"{s}_{d}": group_counts[(s,d)]
                                           for s,d in sorted(ALL_SECONDARY_COUNTS)},
        "secondary_source_transcriptions_complete": not errors,
        "official_pdf_body_verification_count": 0,
        "official_pdf_full_census_complete": False,
        "fmt025_release_allowed": False,
        "optional_ranking_only_matches_proven": 0,
        "review_scope": "all_eight_secondary_html_pages_not_official_bracket_PDFs",
    }
