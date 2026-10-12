"""Stage43G-81: explicit health audit and versioned rebuild of fictional-v2 school indexes.

The original match and calendar SQLite are always read-only. A stale or
tampered derived school index is never silently repaired, replaced or chosen
by the Tk pilot. Versioned refresh writes *only* a new, caller-named index.
A "current" result means every original full-A record and every membership
within the indexed source years has been verified; it does NOT prove a real
nationwide tournament simulation or unbounded school history.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from .career_history_scale_benchmark import file_sha256
from .career_calendar_v2 import CareerCalendarV2Archive
from .career_option_a_storage_profile import _read_only
from .career_v2_school_read_index import (
    SCHEMA, _paths, _check_index_meta, _verify_index_years,
    build_v2_school_read_index,
)


def audit_v2_school_index_health(
    v2_path: str | Path, calendar_path: str | Path,
    index_path: str | Path,
) -> dict:
    """Read-only complete source/index integrity audit.

    'ready' also requires all saved source years to fit the indexed range.
    'extension_required' means a strict check of existing indexed years
    succeeded, but a new source year is not indexed. 'integrity_conflict'
    means source/calendar/index proof failed and use must be refused.
    """
    source, calendar, index = _paths(v2_path, calendar_path, index_path)
    if not source.is_file() or not calendar.is_file():
        raise FileNotFoundError("fictional v2 source and calendar required")
    source_hash_before = {
        "v2": file_sha256(source), "calendar": file_sha256(calendar),
    }
    if index.is_file():
        source_hash_before["index"] = file_sha256(index)
    # The source list is independent of the old index so that appended
    # sealed years cannot be hidden by an outdated index's year boundaries.
    with closing(_read_only(source)) as conn:
        conn.row_factory = sqlite3.Row
        years = conn.execute(
            "SELECT year,status FROM v2_game_years ORDER BY year"
        ).fetchall()
    saved_years = [r["year"] for r in years]
    unsealed_years = [
        r["year"] for r in years if r["status"] != "sealed"
    ]
    result = {
        "status": "missing_index" if not index.exists() else "integrity_conflict",
        "source_kind": "explicit_fictional_v2_option_a_not_official",
        "saved_years": saved_years,
        "unsealed_years": unsealed_years,
        "indexed_years": [],
        "outside_index_years": [],
        "strict_original_payloads_verified": False,
        "strict_derived_memberships_verified": False,
        "source_files_read_only": True,
        "original_saved_files_unmodified": False,
        "automatic_rebuild_or_switch": False,
        "all_3000_school_100_year_gameplay_proven": False,
        "reason": None,
    }
    if not index.exists():
        result["reason"] = "derived school index was not created"
    else:
        try:
            cal = CareerCalendarV2Archive(calendar)
            with closing(_read_only(source)) as original, closing(
                _read_only(index)
            ) as derived:
                original.row_factory = sqlite3.Row
                derived.row_factory = sqlite3.Row
                original.execute("BEGIN")
                derived.execute("BEGIN")
                meta = derived.execute(
                    "SELECT schema_version, source_path, calendar_path,"
                    " start_year, end_year FROM meta"
                ).fetchall()
                if len(meta) != 1 or meta[0]["schema_version"] != SCHEMA:
                    raise ValueError("unsupported derived index metadata")
                first, last = meta[0]["start_year"], meta[0]["end_year"]
                _check_index_meta(derived, source, calendar, first, last)
                result["indexed_range"] = [first, last]
                # Fully verify payloads and membership of *every* indexed
                # year, even when its school is not selected for display.
                plans = _verify_index_years(
                    original, derived, cal, first, last,
                    verify_scope="selected_years",
                )
                result["indexed_years"] = sorted(plans)
                result["strict_original_payloads_verified"] = True
                result["strict_derived_memberships_verified"] = True
                result["outside_index_years"] = [
                    year for year in saved_years
                    if year < first or year > last
                ]
                if unsealed_years:
                    result["status"] = "unsealed_source_years"
                    result["reason"] = "source contains unsealed game years"
                elif result["outside_index_years"]:
                    result["status"] = "extension_required"
                    result["reason"] = "saved fictional years outside this index"
                elif not saved_years:
                    result["status"] = "empty_source"
                    result["reason"] = "no sealed saved game years exist"
                else:
                    result["status"] = "ready"
        except (ValueError, KeyError, TypeError, sqlite3.DatabaseError,
                OSError) as exc:
            # Never treat a structurally unreadable index as valid or
            # try to repair it during this read operation.
            result["status"] = "integrity_conflict"
            result["reason"] = str(exc)
    after = {
        "v2": file_sha256(source), "calendar": file_sha256(calendar),
    }
    if index.is_file():
        after["index"] = file_sha256(index)
    result["original_saved_files_unmodified"] = (
        source_hash_before == after
    )
    if not result["original_saved_files_unmodified"]:
        raise RuntimeError("v2 index health audit changed source bytes")
    return result


def prepare_versioned_v2_school_index(
    v2_path: str | Path, calendar_path: str | Path,
    existing_index_path: str | Path, new_index_path: str | Path,
) -> dict:
    """Explicit rebuild into an unused pathname, never an in-place repair.

    Refresh covers the *entire* set of saved source years if it fits within
    the v2 single-index 100-year limit. The existing index is neither
    altered nor removed, including when it is corrupt. The caller must
    separately choose the newly created index for browsing.
    """
    source, calendar, old = _paths(
        v2_path, calendar_path, existing_index_path,
    )
    new = Path(new_index_path).resolve()
    if new in (source, calendar, old):
        raise ValueError("new versioned index must have a distinct filename")
    if new.exists():
        raise FileExistsError("new versioned index must not overwrite a file")
    prior = audit_v2_school_index_health(source, calendar, old)
    if prior["unsealed_years"]:
        raise ValueError("unsealed saved source years cannot be indexed")
    years = prior["saved_years"]
    if not years:
        raise ValueError("cannot refresh an empty fictional v2 archive")
    if min(years) < 10000 or max(years) - min(years) >= 100:
        raise ValueError("full saved source exceeds one 100-year index range")
    originals_before = (file_sha256(source), file_sha256(calendar))
    old_sha = file_sha256(old) if old.exists() else None
    build = build_v2_school_read_index(
        source, calendar, new,
        start_year=min(years), end_year=max(years),
    )
    # Do not issue a success report until the fresh sidecar's entire
    # membership is checked against every authoritative full-A JSON row.
    verified = audit_v2_school_index_health(source, calendar, new)
    if verified["status"] != "ready":
        raise RuntimeError("new versioned index failed strict source audit")
    if (originals_before != (file_sha256(source), file_sha256(calendar))
            or old_sha != (file_sha256(old) if old.exists() else None)):
        raise RuntimeError("refresh altered an existing original or old index")
    return {
        "previous_status": prior["status"],
        "previous_index_retained": True,
        "previous_index_path": str(old),
        "new_index_path": str(new),
        "new_index_status": verified["status"],
        "new_indexed_years": verified["indexed_years"],
        "new_index_matches": build["indexed_source_matches"],
        "v2_source_and_calendar_unchanged": True,
        "previous_index_unchanged": True,
        "automatic_gui_selection": False,
        "old_index_not_overwritten": True,
        "new_index_strict_membership_verified": True,
        "source_records_are_fictional": True,
    }
