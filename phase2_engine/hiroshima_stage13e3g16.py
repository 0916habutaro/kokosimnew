"""Stage 13E-3G-16: 2026 Hiroshima publisher-index and federation calendar cross-audit.

The 44 spring + 45 autumn child events belong to a tournament publishing
platform, NOT to the official federation PDF body. There are 87 qualifier
children + 2 MAIN children. Parent child event windows are NOT actual
game dates: five games fall on April 5 when a child index ends April 4.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_qualification_timeline_2026 import TIMELINE_FILE
from .hiroshima_stage13e3g14 import OFFICIAL_PDF_LIST

STRUCTURE_FILE = "competitions/2026/hiroshima_publisher_event_structure_2026.csv"
EVENT_FILE = "competitions/2026/hiroshima_publisher_berth_event_crosscheck_2026.csv"
CALENDAR_FILE = "competitions/2026/hiroshima_federation_qualifier_calendar_2026.csv"
PUBLISHER = {
    "spring": "https://www.sportsonline.jp/reportv2/PublisherFull/Rally.aspx?parentid=RX_ZV",
    "autumn": "https://www.sportsonline.jp/reportv2/PublisherFull/Rally.aspx?ParentID=RX%5DSZ",
}
FEDERATION = "https://hiroshima.hhbf1950.or.jp/大会関連/硬式部各種大会"
EXPECTED = {
    ("spring", "west"): (4, 4, 1),
    ("spring", "north"): (4, 4, 2),
    ("spring", "south"): (6, 6, 3),
    ("spring", "east"): (5, 4, 0),
    ("autumn", "west"): (4, 4, 1),
    ("autumn", "north"): (4, 4, 2),
    ("autumn", "south"): (6, 6, 4),
    ("autumn", "east"): (5, 3, 1),
}
EXACT_DATE_DISCREPANCY = {
    "HT20260033", "HT20260050", "HT20260053", "HT20260067", "HT20260044"
}
NORMAL_WINDOWS = {
    "spring": ("2026-03-21", "2026-04-05", "2026-04-11", "2026-04-12"),
    "autumn": ("2026-08-22", "2026-09-06", "2026-09-12", "2026-09-13"),
}
ROUTE_GROUPS = {
    ("spring", "west"): "SGR000140", ("spring", "north"): "SGR000141",
    ("spring", "south"): "SGR000142", ("spring", "east"): "SGR000143",
    ("autumn", "west"): "SGR000144", ("autumn", "north"): "SGR000145",
    ("autumn", "south"): "SGR000146", ("autumn", "east"): "SGR000147",
}


def audit_2026_hiroshima_stage13e3g16(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    structure = _read(root, STRUCTURE_FILE)
    crosscheck = _read(root, EVENT_FILE)
    federation = _read(root, CALENDAR_FILE)
    matches = _read(root, TIMELINE_FILE)
    pdfs = _read(root, OFFICIAL_PDF_LIST)
    errors = []

    groups = {(r["season"], r["district_code"]): r for r in structure}
    pdf_map = {(r["season"], r["district_code"]): r for r in pdfs}
    if len(groups) != 8 or len(structure) != 8 or set(groups) != set(EXPECTED):
        errors.append("eight unique district-season child-stage summaries required")
    if len(pdf_map) != 8 or len(pdfs) != 8 or set(pdf_map) != set(EXPECTED):
        errors.append("eight distinct official federation bracket links required")
    season_children = Counter()
    season_first = Counter()
    season_second = Counter()
    season_deciders = Counter()
    for sd, (first, second, deciders) in EXPECTED.items():
        row = groups.get(sd)
        official = pdf_map.get(sd)
        if row is None or official is None:
            continue
        season, district = sd
        count = first + second + deciders
        season_children[season] += count
        season_first[season] += first
        season_second[season] += second
        season_deciders[season] += deciders
        if (
            row["stage_group_id"] != ROUTE_GROUPS[sd]
            or row["competition_id"] != ("CMP000135" if season == "spring" else "CMP000136")
            or any(row[k] != str(x) for k, x in (
                ("first_place_child_events", first), ("second_place_child_events", second),
                ("cross_zone_entry_decider_child_events", deciders),
                ("qualifier_child_event_count", count),
                ("competition_parent_child_event_count", 44 if season == "spring" else 45),
                ("prefectural_main_child_event_count", 1)))
            or row["source_url"] != PUBLISHER[season]
            or row["source_scope"] != "tournament_publisher_event_index_not_official_bracket_pdf"
            or row["pdf_body_inspected"] != "no"
            or official["stage_group_id"] != ROUTE_GROUPS[sd]
            or official["source_access"] != "official_link_located_pdf_not_read"
            or official["full_fixture_review_status"] != "pending_full_match_review"
        ):
            errors.append(f"publisher district event counts/provenance mismatch: {sd}")

    if season_children != {"spring": 43, "autumn": 44}:
        errors.append(f"expected 43 spring + 44 autumn qualifier children: {season_children}")
    if (season_first != {"spring": 19, "autumn": 19}
            or season_second != {"spring": 18, "autumn": 17}
            or season_deciders != {"spring": 6, "autumn": 8}):
        errors.append("publisher first/second/entry-decider stage family counts changed")

    calendars = {r["season"]: r for r in federation}
    if len(federation) != 2 or set(calendars) != set(NORMAL_WINDOWS):
        errors.append("two distinct 2026 federation qualifier calendars required")
    for season, expected in NORMAL_WINDOWS.items():
        record = calendars.get(season)
        if record is None:
            continue
        if (
            tuple(record[k] for k in ("qualifier_normal_start", "qualifier_normal_end",
                                        "reserve_day1", "reserve_day2")) != expected
            or record["competition_id"] != ("CMP000135" if season == "spring" else "CMP000136")
            or record["source_url"] != FEDERATION
            or record["verified_by"] != "federation_public_html_calendar"
            or record["pdf_body_inspected"] != "no"
        ):
            errors.append(f"federation published calendar changed: {season}")

    matches_by_id = {r["match_id"]: r for r in matches}
    if len(matches) != 223 or len(matches_by_id) != 223:
        errors.append("223 distinct recorded games required for sample-level crosswalk")
    games_by_season = Counter()
    award_dates = {}
    for r in matches:
        season = r["season"]
        games_by_season[season] += 1
        allowed = NORMAL_WINDOWS.get(season)
        if allowed is None:
            errors.append(f"invalid season: {r['match_id']}")
            continue
        played = r["match_date"]
        if not (allowed[0] <= played <= allowed[1] or played in allowed[2:]):
            errors.append(f"match date outside federation calendar and reserve dates: {r['match_id']}")
        if r["winner_berth_status"] == "berth_award":
            ident = (season, r["district_code"], r["winner_name"])
            if ident in award_dates:
                errors.append(f"repeated award lock {ident}")
            award_dates[ident] = played
    if games_by_season != {"spring": 112, "autumn": 111} or len(award_dates) != 63:
        errors.append("seasonal 112/111 game inventory or 63 qualification locks changed")

    # Calendar-level evidence only: same-day timing is explicitly NOT ordered.
    previously_qualified_match_ids = []
    for r in matches:
        if any(award_dates.get((r["season"], r["district_code"], r[k]), "9999-99-99")
               < r["match_date"] for k in ("team1_name", "team2_name")):
            previously_qualified_match_ids.append(r["match_id"])

    observed_deciders = Counter()
    observed_second = Counter()
    disagree = set()
    checked = set()
    for row in crosscheck:
        mid = row["matched_match_id"]
        if mid in checked or mid not in matches_by_id:
            errors.append(f"duplicate or missing publisher-stage match: {mid}")
            continue
        checked.add(mid)
        game = matches_by_id[mid]
        season = row["season"]
        district = row["district_code"]
        sd = (season, district)
        role = row["stage_role"]
        if sd not in EXPECTED:
            errors.append(f"publisher source references unknown district: {mid}")
        if role == "entry_decider":
            observed_deciders[sd] += 1
            if "県大会出場決定戦" not in row["child_event_title"]:
                errors.append(f"no publisher entry-decider label: {mid}")
        elif role == "second_place_zone_award":
            observed_second[sd] += 1
            if "二位校" not in row["child_event_title"]:
                errors.append(f"no publisher runner-up-zone label: {mid}")
        else:
            errors.append(f"unrecognized child-stage role: {mid}")
        first = row["publisher_window_start"]
        last = row["publisher_window_end"]
        if first > last:
            errors.append(f"publisher child event inverted date interval: {mid}")
        outside = game["match_date"] < first or game["match_date"] > last
        if outside:
            disagree.add(mid)
        if (
            game["season"] != season or game["district_code"] != district
            or game["winner_berth_status"] != "berth_award"
            or row["actual_match_date"] != game["match_date"]
            or row["winner_name"] != game["winner_name"]
            or row["loser_name"] != game["team2_name"]
            or row["winner_score"] != game["team1_score"]
            or row["loser_score"] != game["team2_score"]
            or row["actual_date_outside_child_index_window"] != ("yes" if outside else "no")
            or row["event_index_source"] != PUBLISHER[season]
            or row["result_source"] != game["source_url"]
            or row["verification_scope"] != "publisher_child_event_index_plus_secondary_dated_result"
            or row["pdf_body_inspected"] != "no"
        ):
            errors.append(f"publisher child-event / played-game evidence mismatch: {mid}")

    for sd, (_, _, expected_count) in EXPECTED.items():
        if observed_deciders[sd] != expected_count:
            errors.append(f"explicit publisher entry-decider count mismatch: {sd}")
    if observed_second != {("spring", "east"): 1}:
        errors.append("spring east E-zone second-place award-stage check missing")
    if len(crosscheck) != 15 or len(checked) != 15:
        errors.append("exactly 14 explicit entry deciding matches plus one runner-up-zone award required")
    if disagree != EXACT_DATE_DISCREPANCY:
        errors.append(f"April 4 publisher / April 5 played date mismatches changed: {disagree}")
    if previously_qualified_match_ids:
        errors.append(f"unexpected prequalified participant in a later-date match: {previously_qualified_match_ids}")

    return {
        "ok": not errors,
        "errors": errors,
        "spring_publisher_child_events": 44,
        "autumn_publisher_child_events": 45,
        "qualifier_child_events": sum(season_children.values()),
        "explicit_entry_decider_child_events": sum(season_deciders.values()),
        "matched_publisher_stage_to_qualified_game_records": len(checked),
        "recorded_match_count": len(matches),
        "publisher_event_window_game_date_disagreement_ids": sorted(disagree),
        "publisher_event_window_game_date_disagreements": len(disagree),
        "already_qualified_on_prior_date_match_ids": previously_qualified_match_ids,
        "optional_ranking_only_games_proven": 0,
        "official_bracket_pdf_bodies_inspected": 0,
        "official_bracket_pdf_match_census_complete": False,
        "fmt025_release_allowed": False,
        "source_scope": "federation_html_calendar_and_tournament_publisher_index_not_pdf",
    }
