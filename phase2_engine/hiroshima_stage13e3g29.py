"""Stage13E-3G-29: current raw official PDF recovery audit.

The official listing, file HTML shell and preview/download attempts are
different evidence grades. Five attempts were made on 2026-10-09; none
delivered the original bytes. The earlier official *image* observation of
Stage24 is immutable and does not contradict this later 403 result.

A local-PDF inspection and 300 dpi render tool exists separately, but the
absence of the real source means none of 25 official match numbers and 32
arrow endpoints can legitimately be marked verified.
"""
from __future__ import annotations

from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g23 import ACCESS_FILE, SOURCE_FILE, OFFICIAL_PAGE
from .hiroshima_stage13e3g24 import PREVIEW_FILE
from .hiroshima_stage13e3g28 import (
    NUMBER_QUEUE_FILE, ARROW_QUEUE_FILE, audit_2026_hiroshima_stage13e3g28,
)
from .hiroshima_official_pdf_intake import OFFICIAL_2026_WEST_SOURCE

ATTEMPT_FILE = "research/2026/hiroshima_autumn_west_pdf_acquisition_attempts_stage13e3g29.csv"
EXPECTED_ATTEMPTS = (
    ("federation_hardball_events_listing", OFFICIAL_PAGE,
     "public_web_text", "official_pdf_link_present",
     "verified_official_link_metadata_not_document_body"),
    ("google_drive_file_page", OFFICIAL_2026_WEST_SOURCE,
     "public_web_drive_html", "html_loading_shell_with_image_link",
     "html_shell_is_not_original_pdf"),
    ("google_drive_preview_image_endpoint", OFFICIAL_2026_WEST_SOURCE,
     "public_web_image_follow", "http_403_forbidden_at_this_attempt",
     "previous_visual_preview_not_recoverable_as_original_pdf"),
    ("google_drive_uc_direct_download",
     "https://drive.google.com/uc?export=download&id=1VxVW_r_L5MwnP3hkqZToGe3o5StK5NQ-",
     "public_web_direct_link", "not_accessible_pdf_body_not_returned",
     "download_attempt_no_raw_pdf_bytes"),
    ("runtime_direct_download",
     "https://drive.usercontent.google.com/download?id=1VxVW_r_L5MwnP3hkqZToGe3o5StK5NQ-&export=download&confirm=t",
     "isolated_runtime_https", "dns_resolution_unavailable",
     "runtime_transport_failure_no_document_bytes"),
)


def audit_2026_hiroshima_stage13e3g29(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    attempts = _read(root, ATTEMPT_FILE)
    sources = _read(root, SOURCE_FILE)
    prev_stage23 = _read(root, ACCESS_FILE)
    prev_stage24 = _read(root, PREVIEW_FILE)
    games = _read(root, NUMBER_QUEUE_FILE)
    arrows = _read(root, ARROW_QUEUE_FILE)
    old = audit_2026_hiroshima_stage13e3g28(root)
    errors: list[str] = []
    if not old["ok"]:
        errors.append("Stage28 25-match/32-arrow proof queue must still pass")
    if len(attempts) != 5 or len({r["attempt_id"] for r in attempts}) != 5:
        errors.append("five distinct dated raw-PDF recovery observations required")

    for index, expected in enumerate(EXPECTED_ATTEMPTS, 1):
        if index > len(attempts):
            break
        method, entry, tool, result, scope = expected
        fields = {
            "attempt_id": f"HPI2026{index:03d}",
            "document_year": "2026", "season": "autumn",
            "district_code": "west", "stage_group_id": "SGR000144",
            "checked_date": "2026-10-09",
            "target_official_pdf_url": OFFICIAL_2026_WEST_SOURCE,
            "attempt_method": method,
            "attempt_entry_url": entry,
            "tool_visibility": tool,
            "observed_outcome": result,
            "raw_pdf_received": "no", "pdf_bytes_sha256": "",
            "actual_official_match_numbers_verified": "0",
            "actual_official_individual_arrows_verified": "0",
            "root_evidence_scope": scope,
            "allow_fmt025_runtime": "no",
        }
        for field, value in fields.items():
            if attempts[index - 1].get(field) != value:
                errors.append(f"unjustified 2026 original-PDF acquisition claim: {index}/{field}")

    old_source = [
        r for r in sources if (r["season"], r["district_code"]) == ("autumn", "west")
    ]
    if (len(old_source) != 1
            or old_source[0]["official_pdf_url"] != OFFICIAL_2026_WEST_SOURCE
            or old_source[0]["source_access"] != "official_link_located_pdf_not_read"):
        errors.append("link exists but cannot be mistaken for recovered PDF")
    frozen = [
        r for r in prev_stage23
        if (r["season"], r["district_code"]) == ("autumn", "west")
    ]
    if (len(frozen) != 1 or frozen[0]["pdf_body_bytes_obtained"] != "no"
            or frozen[0]["preview_outcome"] != "drive_html_loading_only"
            or frozen[0]["pdf_sha256"] != ""):
        errors.append("Stage23 previous acquisition state must stay an immutable snapshot")
    if (len(prev_stage24) != 1 or prev_stage24[0]["official_image_render_access"] != "yes"
            or prev_stage24[0]["source_pdf_bytes_downloaded"] != "no"):
        errors.append("prior visual preview is separate from failed raw PDF retrieval")
    if (len(games) != 25 or len(arrows) != 32
            or any(r["official_number_verified"] != "no"
                   or r["official_match_number"] != "" for r in games)
            or any(r["official_arrow_verified"] != "no"
                   or r["from_official_match_number"] != ""
                   or r["to_official_match_number"] != "" for r in arrows)):
        errors.append("official numbered arrows remain unverified without original document")

    return {
        "ok": not errors,
        "errors": errors,
        "document_year": "2026",
        "district": "autumn/west",
        "federation_url_verified": True,
        "new_pdf_acquisition_attempts": len(attempts),
        "original_pdf_bytes_recovered": 0,
        "sha256_original_available": False,
        "official_match_numbers_independently_confirmed": 0,
        "official_arrows_independently_confirmed": 0,
        "offline_pdf_sha256_and_300dpi_importer_ready": True,
        "historical_games_with_review_slots": len(games),
        "historical_arrows_with_review_slots": len(arrows),
        "live_fmt025_runtime_enabled": False,
        "optional_ranking_enabled": False,
        "next_blocker": "supply_actual_official_2026_autumn_west_pdf_and_independently_review_its_draw",
    }
