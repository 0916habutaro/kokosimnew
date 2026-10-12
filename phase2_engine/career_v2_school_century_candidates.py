"""Stage43G-85: bounded, read-only per-slot century shard candidate preview.

Filenames and saved-year headers are *hints*, not a trust decision.
Selection is explicit. Only the Stage43G-84 pager's strict full-source
verification is authorized to activate a selected shard combination.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from pathlib import Path
import re
import sqlite3

from .career_option_a_storage_profile import _read_only
from .career_v2_school_century_shards import (
    MAX_SHARDS_PER_REQUEST, _window,
)

MAX_CANDIDATE_FILES = 96
_NAME = re.compile(
    r"fictional_v2_school_read_index_G([0-9]+)_G([0-9]+)"
    r"(?:_([A-Za-z0-9][A-Za-z0-9_-]{0,15}))?\.sqlite3\Z"
)


def preview_v2_school_century_candidates(
    v2_path: str | Path, calendar_path: str | Path,
    *, start_year: int, end_year: int,
) -> dict:
    """Enumerate local filename candidates; never audit, write or activate."""
    if (type(start_year) is not int or type(end_year) is not int
            or start_year < 10000 or end_year < start_year):
        raise ValueError("invalid fictional-v2 preview year range")
    first, _ = _window(start_year)
    last, _ = _window(end_year)
    if (last - first) // 100 + 1 > MAX_SHARDS_PER_REQUEST:
        raise ValueError("candidate preview exceeds 32 century buckets")
    source, calendar = Path(v2_path).resolve(), Path(calendar_path).resolve()
    if (source == calendar or source.parent != calendar.parent
            or not source.is_file() or not calendar.is_file()):
        raise ValueError("v2 source and calendar must belong to one existing slot")
    with closing(_read_only(source)) as db:
        rows = db.execute(
            "SELECT year,status FROM v2_game_years "
            "WHERE year BETWEEN ? AND ? ORDER BY year",
            (start_year, end_year),
        ).fetchall()
    by_window: dict[tuple[int, int], list[tuple[int, str]]] = defaultdict(list)
    for year, status in rows:
        by_window[_window(year)].append((year, status))
    candidate_names: dict[tuple[int, int], list[str]] = defaultdict(list)
    total_candidates = 0
    for child in source.parent.iterdir():
        match = _NAME.fullmatch(child.name)
        if not match:
            continue
        # An in-slot symlink is not a trustworthy candidate; no traversal.
        if child.is_symlink() or not child.is_file():
            continue
        total_candidates += 1
        if total_candidates > MAX_CANDIDATE_FILES:
            raise ValueError("too many century index candidate files")
        first_year, last_year = int(match[1]), int(match[2])
        if (first_year < 10000
                or _window(first_year) != (first_year, last_year)):
            continue
        if (first_year, last_year) in by_window:
            candidate_names[(first_year, last_year)].append(child.name)
    windows = []
    for (from_year, to_year), saves in sorted(by_window.items()):
        names = sorted(candidate_names[(from_year, to_year)])
        windows.append({
            "start_year": from_year,
            "end_year": to_year,
            "saved_years": [year for year, _ in saves],
            "unsealed_years": [
                year for year, status in saves if status != "sealed"
            ],
            "candidate_names": names,
        })
    return {
        "start_year": start_year, "end_year": end_year,
        "saved_years": [year for year, _ in rows],
        "required_windows": windows,
        "missing_window_starts": [
            w["start_year"] for w in windows if not w["candidate_names"]
        ],
        "unsealed_saved_years": [
            year for year, status in rows if status != "sealed"
        ],
        "candidate_count": sum(len(w["candidate_names"]) for w in windows),
        "local_filename_candidates_only": True,
        "candidate_source_integrity_not_verified": True,
        "no_implicit_generation_or_activation": True,
        "legacy_source_combined": False,
    }


def stage_explicit_century_candidate_names(
    preview: dict, selected_names: list[str] | tuple[str, ...],
) -> tuple[str, ...]:
    """Validate exactly one user choice for every required saved-year bucket.

    This does NOT prove the selected index content. The consumer MUST invoke
    verified pager.select_century_shards before treating it as active.
    """
    if (type(preview) is not dict or
            preview.get("local_filename_candidates_only") is not True or
            preview.get("candidate_source_integrity_not_verified") is not True
            or not isinstance(selected_names, (list, tuple))
            or any(type(x) is not str for x in selected_names)):
        raise ValueError("invalid, untrusted candidate selection")
    if preview.get("unsealed_saved_years"):
        raise ValueError("unsealed v2 year cannot be selected")
    windows = preview["required_windows"]
    if (not windows or len(windows) > MAX_SHARDS_PER_REQUEST
            or len(selected_names) != len(windows)
            or len(set(selected_names)) != len(selected_names)):
        raise ValueError("choose exactly one candidate per saved-year bucket")
    pool = {
        name: (w["start_year"], w["end_year"])
        for w in windows for name in w["candidate_names"]
    }
    selected = set(selected_names)
    if not selected.issubset(pool):
        raise ValueError("selected filename is not in this slot preview")
    for w in windows:
        matching = [
            name for name in selected_names
            if pool[name] == (w["start_year"], w["end_year"])
        ]
        if len(matching) != 1:
            raise ValueError("missing or duplicate choice for a saved-year bucket")
    # Canonical ordering by century, not selection order in the UI.
    return tuple(sorted(selected_names, key=lambda name: pool[name]))
