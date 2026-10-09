"""Stage 13E-3G-23: 2026 Hiroshima official bracket acquisition audit.

An official federation *link* and a Google Drive HTML loading shell are not
the official PDF body. No draw edge or reusable FMT025 rule is released here.
The 2025 official PDF belongs to a distinct year and is never a substitute.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g21 import GROUP_REVIEW_FILE
from .hiroshima_stage13e3g22 import PRIOR_YEAR_PDF_FILE

SOURCE_FILE = "competitions/2026/hiroshima_bracket_pdf_review_2026.csv"
ACCESS_FILE = "research/2026/hiroshima_official_bracket_pdf_access_audit_2026.csv"
OFFICIAL_PAGE = "https://hiroshima.hhbf1950.or.jp/大会関連/硬式部各種大会"
EXPECTED = (
    ("spring", "west", "SGR000140", "080411_【西部】春季地区予選トーナメント表.pdf"),
    ("spring", "north", "SGR000141", "080405_【北部】春季地区予選トーナメント表.pdf"),
    ("spring", "south", "SGR000142", "080405_【南部】春季地区予選トーナメント表.pdf"),
    ("spring", "east", "SGR000143", "080405_【東部】春季地区予選トーナメント表.pdf"),
    ("autumn", "west", "SGR000144", "R8秋季地区トーナメント表(西部).pdf"),
    ("autumn", "north", "SGR000145", "R8秋季地区トーナメント表(北部).pdf"),
    ("autumn", "south", "SGR000146", "R8秋季地区トーナメント表(南部).pdf"),
    ("autumn", "east", "SGR000147", "R8秋季地区トーナメント表(東部).pdf"),
)
FILE_ID = re.compile(r"^/[Ff]ile/d/([A-Za-z0-9_-]+)/view/?$")


def _drive_id(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "drive.google.com":
        return None
    match = FILE_ID.fullmatch(parsed.path)
    return match.group(1) if match else None


def audit_2026_hiroshima_stage13e3g23(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    links = _read(root, SOURCE_FILE)
    observations = _read(root, ACCESS_FILE)
    release_reviews = _read(root, GROUP_REVIEW_FILE)
    prior_year = _read(root, PRIOR_YEAR_PDF_FILE)
    errors: list[str] = []
    expected_keys = {(season, district) for season, district, _, _ in EXPECTED}
    by_key = {(r["season"], r["district_code"]): r for r in links}
    seen = {(r["season"], r["district_code"]): r for r in observations}
    reviews = {(r["season"], r["district_code"]): r for r in release_reviews}

    if (len(links) != 8 or len(by_key) != 8
            or len(observations) != 8 or len(seen) != 8
            or len(release_reviews) != 8 or len(reviews) != 8
            or set(by_key) != expected_keys or set(seen) != expected_keys
            or set(reviews) != expected_keys):
        errors.append("all eight distinct 2026 seasonal district PDF slots are required")

    file_ids = set()
    for idx, (season, district, stage_group, filename) in enumerate(EXPECTED, 1):
        key = (season, district)
        ref = by_key.get(key)
        obs = seen.get(key)
        review = reviews.get(key)
        if ref is None or obs is None or review is None:
            errors.append(f"missing review entry: {key}")
            continue
        source_id = _drive_id(ref["official_pdf_url"])
        file_ids.add(source_id)
        wanted = {
            "audit_id": f"HPD2026{idx:03d}",
            "document_year": "2026",
            "season": season,
            "district_code": district,
            "stage_group_id": stage_group,
            "official_google_drive_file_id": source_id,
            "official_file_title": filename,
            "official_pdf_url": ref["official_pdf_url"],
            "origin_page": OFFICIAL_PAGE,
            "checked_date": "2026-10-09",
            "official_link_verified": "yes",
            "preview_outcome": "drive_html_loading_only",
            "pdf_body_bytes_obtained": "no",
            "independent_pdf_content_review": "no",
            "verified_pairing_edge_count": "0",
            "pdf_sha256": "",
            "allow_annual_bracket_graph": "no",
            "allow_live_fmt025_runtime": "no",
            "source_evidence_scope": "federation_link_metadata_not_pdf_body",
        }
        if source_id is None:
            errors.append(f"official PDF URL is not a Drive file reference: {key}")
        if (ref["stage_group_id"] != stage_group
                or ref["source_access"] != "official_link_located_pdf_not_read"
                or ref["full_fixture_review_status"] != "pending_full_match_review"):
            errors.append(f"upstream PDF review status changed without evidence: {key}")
        if (review["stage_group_id"] != stage_group
                or review["exact_fmt025_route_release_approved"] != "no"):
            errors.append(f"FMT025 release status must remain blocked: {key}")
        for field, value in wanted.items():
            if obs.get(field) != value:
                errors.append(f"access evidence or release field mismatch: {key}/{field}")

    if None in file_ids or len(file_ids) != 8:
        errors.append("eight unique identifiable official Drive file IDs required")
    if (len(prior_year) != 1 or prior_year[0]["prior_year"] != "2025"
            or prior_year[0]["prior_year_graph_reusable_for_2026"] != "no"
            or prior_year[0]["target_year_official_2026_pdf_body_inspected"] != "no"):
        errors.append("2025 official graph is separate and cannot serve as 2026 PDF")
    return {
        "ok": not errors,
        "errors": errors,
        "2026_federation_pdf_links": len(links),
        "2026_pdf_landing_shells_checked": len(observations),
        "2026_official_pdf_bodies_obtained": 0,
        "2026_official_draw_edges_verified": 0,
        "2025_official_document_not_2026_evidence": True,
        "2026_all_eight_annual_fmt025_graphs_blocked": not any(
            r.get("exact_fmt025_route_release_approved") == "yes"
            for r in release_reviews
        ),
        "active_runtime_changed": False,
        "next_step": "secure_2026_official_pdf_bytes_and_manual_draw_edge_review",
    }
