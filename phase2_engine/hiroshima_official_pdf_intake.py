"""Stage 13E-3G-29: fail-closed intake of an externally obtained official PDF.

Current source (Hiroshima federation 2026 autumn west) is reachable as a
public *link* and an image preview was previously seen, but the original PDF
bytes were NOT obtained here. This module does not download Google Drive
content, forge proof of authenticity, assign match numbers, or modify FMT025.

After separately obtaining the original PDF, an operator may use this
offline-only helper to reject HTML masquerading as PDF, record a SHA-256
fingerprint, and optionally render at 300 dpi using installed Poppler tools.
A valid local PDF remains an UNVERIFIED SOURCE CANDIDATE until reviewed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

OFFICIAL_2026_WEST_SOURCE = (
    "https://drive.google.com/file/d/"
    "1VxVW_r_L5MwnP3hkqZToGe3o5StK5NQ-/view?usp=sharing"
)
MAX_ORIGINAL_BYTES = 64 * 1024 * 1024
MIN_ORIGINAL_BYTES = 512
MAX_RENDER_PAGES = 12


class OfficialPdfIntakeError(ValueError):
    """Unverified source, invalid PDF candidate, or unavailable renderer."""


@dataclass(frozen=True)
class OfficialPdfCandidate:
    stage: str
    claimed_year: str
    claimed_season: str
    claimed_district: str
    intended_stage_group: str
    federation_pdf_listing_url: str
    intake_medium: str
    raw_pdf_bytes_received: bool
    sha256: str
    file_size_bytes: int
    parsed_page_count: int | None
    source_identity_independently_verified: bool = False
    official_match_numbers_independently_verified: int = 0
    official_transfer_arrows_independently_verified: int = 0
    annual_draw_rule_verified: bool = False
    runtime_enabled: bool = False
    optional_ranking_enabled: bool = False
    proof_status: str = "local_pdf_candidate_not_authenticity_proof"


def inspect_local_pdf_candidate(
    data: bytes, *,
    source_url: str,
    intake_medium: str,
    parsed_page_count: int | None = None,
) -> OfficialPdfCandidate:
    """Check basic byte-level plausibility, never official source identity.

    PDF structural validity beyond the magic/EOF must be checked with a PDF
    parser (pdfinfo) before treating a crop as a real page. Local bytes alone
    can never prove that they came from the linked Google Drive file.
    """
    if source_url != OFFICIAL_2026_WEST_SOURCE:
        raise OfficialPdfIntakeError("wrong federation file ID or official 2026 source")
    if intake_medium not in (
        "downloaded_from_federation_link_by_operator",
        "operator_supplied_original_pdf",
    ):
        raise OfficialPdfIntakeError("original PDF intake method must be explicit")
    if not isinstance(data, bytes):
        raise OfficialPdfIntakeError("raw immutable PDF bytes required")
    if len(data) < MIN_ORIGINAL_BYTES or len(data) > MAX_ORIGINAL_BYTES:
        raise OfficialPdfIntakeError("suspiciously small or excessive PDF size")
    if not re.match(rb"^%PDF-(?:1\.[0-7]|2\.0)(?:\r|\n)", data[:12]):
        raise OfficialPdfIntakeError("non-PDF body: Google Drive HTML/image is not a PDF")
    if b"%%EOF" not in data[-2048:]:
        raise OfficialPdfIntakeError("missing PDF EOF trailer; truncated or wrong content")
    if parsed_page_count is not None and (
        not isinstance(parsed_page_count, int) or isinstance(parsed_page_count, bool)
        or not 1 <= parsed_page_count <= MAX_RENDER_PAGES
    ):
        raise OfficialPdfIntakeError("positive bounded parser-confirmed page count required")
    return OfficialPdfCandidate(
        stage="13E-3G-29",
        claimed_year="2026",
        claimed_season="autumn",
        claimed_district="west",
        intended_stage_group="SGR000144",
        federation_pdf_listing_url=OFFICIAL_2026_WEST_SOURCE,
        intake_medium=intake_medium,
        raw_pdf_bytes_received=True,
        sha256=hashlib.sha256(data).hexdigest(),
        file_size_bytes=len(data),
        parsed_page_count=parsed_page_count,
    )


def inspect_with_poppler_pdfinfo(pdf_path: Path) -> int:
    """Require a real PDF parser before high-resolution page rendering."""
    exe = shutil.which("pdfinfo")
    if not exe:
        raise OfficialPdfIntakeError("pdfinfo (Poppler) is required for page validation")
    process = subprocess.run(
        [exe, str(pdf_path)], capture_output=True, text=True, check=False,
        timeout=30,
    )
    if process.returncode:
        raise OfficialPdfIntakeError("pdfinfo did not parse the PDF successfully")
    match = re.search(r"(?m)^Pages:\s*(\d+)\s*$", process.stdout)
    if not match:
        raise OfficialPdfIntakeError("pdfinfo returned no page count")
    count = int(match.group(1))
    if not 1 <= count <= MAX_RENDER_PAGES:
        raise OfficialPdfIntakeError("too many pages to render as a bracket")
    return count


def render_original_pdf_preview(
    pdf_path: Path, output_dir: Path, *, page_count: int,
) -> tuple[Path, ...]:
    """Render each original page at 300dpi, without OCR or edge inference."""
    exe = shutil.which("pdftoppm")
    if not exe:
        raise OfficialPdfIntakeError("pdftoppm (Poppler) must be installed")
    if not 1 <= page_count <= MAX_RENDER_PAGES:
        raise OfficialPdfIntakeError("unbounded or empty page range is forbidden")
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / "official_2026_hiroshima_autumn_west"
    process = subprocess.run(
        [exe, "-f", "1", "-l", str(page_count), "-r", "300", "-png",
         str(pdf_path), str(prefix)],
        capture_output=True, text=True, check=False, timeout=180,
    )
    if process.returncode:
        raise OfficialPdfIntakeError("PDF page rendering failed")
    rendered = tuple(sorted(output_dir.glob(prefix.name + "-*.png")))
    if len(rendered) != page_count:
        raise OfficialPdfIntakeError("rendered page count disagrees with parser")
    return rendered


def intake_offline_pdf(
    *, pdf_path: Path, output_dir: Path, render: bool = False,
    intake_medium: str = "operator_supplied_original_pdf",
) -> dict:
    """Write local provenance JSON; never mutate the repository's official queue."""
    raw = pdf_path.read_bytes()
    initial = inspect_local_pdf_candidate(
        raw, source_url=OFFICIAL_2026_WEST_SOURCE,
        intake_medium=intake_medium,
    )
    # Even a syntactically plausible file needs parser verification.
    pages = inspect_with_poppler_pdfinfo(pdf_path)
    candidate = inspect_local_pdf_candidate(
        raw, source_url=OFFICIAL_2026_WEST_SOURCE,
        intake_medium=intake_medium,
        parsed_page_count=pages,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered = render_original_pdf_preview(
        pdf_path, output_dir, page_count=pages,
    ) if render else ()
    manifest = asdict(candidate)
    manifest["pdf_parser"] = "poppler_pdfinfo"
    manifest["rendered_png_filenames"] = [x.name for x in rendered]
    manifest["high_resolution_render_dpi"] = 300 if render else None
    manifest["authenticity_note"] = (
        "Matching a PDF signature, parser and source URL argument does NOT "
        "prove these bytes came from the actual Hiroshima federation file. "
        "Independent source review is mandatory before accepting arrows."
    )
    manifest["original_bytes_sha256_before_parser"] = initial.sha256
    (output_dir / "original_pdf_candidate_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline preflight of a separately obtained 2026 Hiroshima autumn-west official PDF",
    )
    parser.add_argument("--pdf", required=True, type=Path,
                        help="Local original PDF supplied by an operator, not a Google Drive HTML page")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--render", action="store_true",
                        help="Use Poppler to produce 300dpi PNGs for human match-arrow review")
    args = parser.parse_args()
    try:
        result = intake_offline_pdf(
            pdf_path=args.pdf, output_dir=args.output_dir, render=args.render,
        )
    except (OSError, OfficialPdfIntakeError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f"OFFICIAL_PDF_INTAKE_REJECTED: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
