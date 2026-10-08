"""2026 Hiroshima district-bracket evidence and explicit FMT025 safety gate.

Eight official PDF links are identified, but their contents were not extracted.
Eight *anchor fixtures* are cross-checked from dated result pages. Neither
an official link nor an anchor constitutes an exhaustive match-by-match audit.
No historical optional ranking game may be inferred from route/title wording.
"""
from __future__ import annotations

import csv
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

PDF_FILE = "competitions/2026/hiroshima_bracket_pdf_review_2026.csv"
ANCHOR_FILE = "competitions/2026/hiroshima_match_level_anchors_2026.csv"
ROUTE_FILE = "competitions/2026/hiroshima_district_qualification_routes.csv"
PRIOR_FILE = "competitions/2026/hiroshima_qualification_examples.csv"
DISTRICTS = ("west", "north", "south", "east")
SEASONS = {"spring": "CMP000135", "autumn": "CMP000136"}
EXPECTED = {(season, district) for season in SEASONS for district in DISTRICTS}


def _read(root: Path, rel: str) -> list[dict[str, str]]:
    with (root / rel).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def audit_2026_hiroshima_match_level_evidence(data_dir: str | Path) -> dict:
    """Audit source locations and dated qualifier anchors; fail closed.

    A future release of FMT025 requires a separate exhaustive source/game
    inventory and independently documented two-sided prior berth locks.
    This method *never* grants that release solely from 8 source links.
    """
    root = Path(data_dir)
    pdfs = _read(root, PDF_FILE)
    anchors = _read(root, ANCHOR_FILE)
    routes = _read(root, ROUTE_FILE)
    prior = _read(root, PRIOR_FILE)
    errors: list[str] = []
    route_groups: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for row in routes:
        key = (row["season"], row["district_code"])
        route_groups.setdefault(key, set()).add(
            (row["competition_id"], row["stage_group_id"])
        )
    pdf_keys: set[tuple[str, str]] = set()
    pdf_ids: set[str] = set()
    for row in pdfs:
        key = (row["season"], row["district_code"])
        if key not in EXPECTED or key in pdf_keys:
            errors.append(f"duplicate or unknown PDF season/district: {key}")
        pdf_keys.add(key)
        if (row["competition_id"], row["stage_group_id"]) not in route_groups.get(key, set()):
            errors.append(f"incorrect competition/group mapping for {key}")
        url = row["official_pdf_url"]
        parts = urlparse(url)
        if (parts.scheme != "https" or parts.hostname != "drive.google.com"
                or "/file/d/" not in parts.path or "/view" not in parts.path):
            errors.append(f"incorrect official PDF link for {key}")
        try:
            doc_id = parts.path.split("/file/d/", 1)[1].split("/", 1)[0]
        except IndexError:
            doc_id = ""
        if not doc_id or doc_id in pdf_ids:
            errors.append(f"duplicate or missing official PDF identity for {key}")
        pdf_ids.add(doc_id)
        # This branch is intentionally an evidence-only milestone; declaring
        # source or full-match verification without the PDF is a hard failure.
        if row["source_access"] != "official_link_located_pdf_not_read":
            errors.append(f"unsupported claim of direct PDF inspection: {key}")
        if row["full_fixture_review_status"] != "pending_full_match_review":
            errors.append(f"unsupported claim of exhaustive fixture review: {key}")
        p = urlparse(row["secondary_result_url"])
        if p.scheme != "https" or not p.hostname:
            errors.append(f"missing independent result source for {key}")
    if pdf_keys != EXPECTED or len(pdfs) != 8:
        errors.append(f"expected eight unique district-season PDF references: {pdf_keys}")

    anchor_keys: set[tuple[str, str]] = set()
    anchor_ids: set[str] = set()
    fixture_keys: set[tuple] = set()
    for row in anchors:
        key = (row["season"], row["district_code"])
        aid = row["anchor_id"]
        if key not in EXPECTED or key in anchor_keys or aid in anchor_ids or not aid:
            errors.append(f"duplicate or unknown anchor: {aid}/{key}")
        anchor_keys.add(key)
        anchor_ids.add(aid)
        if row["competition_id"] != SEASONS.get(row["season"]):
            errors.append(f"competition mismatch for anchor {aid}")
        try:
            when = date.fromisoformat(row["match_date"])
            start, end = ((date(2026, 3, 21), date(2026, 4, 12))
                          if row["season"] == "spring"
                          else (date(2026, 8, 22), date(2026, 9, 13)))
            if not start <= when <= end:
                errors.append(f"fixture date outside district tournament: {aid}")
            a, b = int(row["team1_score"]), int(row["team2_score"])
            if min(a, b) < 0 or a == b or (
                row["winner_name"] !=
                (row["team1_name"] if a > b else row["team2_name"])
            ):
                errors.append(f"score/winner mismatch: {aid}")
        except (ValueError, KeyError):
            errors.append(f"invalid anchor date or score: {aid}")
        if (not row["team1_name"] or not row["team2_name"]
                or row["team1_name"] == row["team2_name"]):
            errors.append(f"invalid anchor participants: {aid}")
        if (row["classification"] != "qualification_decider"
                or row["pre_match_proof"] != "at_least_one_side_unqualified_before_match"):
            errors.append(f"unsubstantiated ranking-only interpretation: {aid}")
        p = urlparse(row["match_result_source_url"])
        if p.scheme != "https" or not p.hostname:
            errors.append(f"missing dated match provenance: {aid}")
        fixture_keys.add((row["season"], row["match_date"],
                          frozenset((row["team1_name"], row["team2_name"]))))
    if len(anchors) != 8 or anchor_keys != EXPECTED or len(fixture_keys) != 8:
        errors.append("need exactly one distinct qualifier anchor per district-season")

    old_matches = {
        (r["season"], r["match_date"], frozenset((r["team1_name"], r["team2_name"]))): r
        for r in prior
    }
    matched_old = 0
    for row in anchors:
        key = (row["season"], row["match_date"],
               frozenset((row["team1_name"], row["team2_name"])))
        old = old_matches.get(key)
        if old is not None:
            matched_old += 1
            scores = {row["team1_name"]: row["team1_score"],
                      row["team2_name"]: row["team2_score"]}
            old_scores = {old["team1_name"]: old["team1_score"],
                          old["team2_name"]: old["team2_score"]}
            if (scores != old_scores or row["winner_name"] != old["winner_name"]
                    or old["qualification_effect"] != "qualifier_effect"):
                errors.append(f"prior qualification evidence conflicts: {row['anchor_id']}")
    if matched_old != 2:
        errors.append(f"expected exactly two overlaps with Stage 13E-3G-7: {matched_old}")

    return {
        "ok": not errors,
        "errors": errors,
        "official_pdf_links_identified": len(pdfs),
        "official_pdf_bodies_checked": 0,
        "district_seasons_with_anchor": len(anchor_keys),
        "new_qualification_anchor_records": len(anchors),
        "overlap_with_previous_examples": matched_old,
        "combined_unique_named_match_examples": len(prior) + len(anchors) - matched_old,
        "verified_additional_optional_ranking_matches": 0,
        "full_individual_match_audit_complete": False,
        "fmt025_release_allowed": False,
        "review_scope": "eight_dated_qualifier_anchors_plus_pdf_link_inventory_only",
    }
