"""Stage43G-82: discover slot-local fictional v2 school index *candidates*.

Discovery is metadata-only: a name in this list is NEVER a statement of
integrity or approval. Opting into a version separately performs the complete
Stage43G-81 strict original/source/index proof. No file is generated or
rewritten by discovery or by selecting a saved version.
"""
from __future__ import annotations

from pathlib import Path
import re

from .career_v2_school_index_health import audit_v2_school_index_health

DEFAULT_INDEX_NAME = "fictional_v2_school_read_index.sqlite3"
_VERSION = re.compile(
    r"fictional_v2_school_read_index(?:_[A-Za-z0-9][A-Za-z0-9_-]{0,47})?\.sqlite3\Z"
)
MAX_VERSIONS = 32


def _source_directory(v2_path: str | Path,
                      calendar_path: str | Path) -> Path:
    source, calendar = Path(v2_path).resolve(), Path(calendar_path).resolve()
    if source.parent != calendar.parent:
        raise ValueError("index candidates must belong to a single save slot")
    return source.parent


def _candidate_path(v2_path: str | Path, calendar_path: str | Path,
                    name: str) -> Path:
    folder = _source_directory(v2_path, calendar_path)
    if (type(name) is not str or _VERSION.fullmatch(name) is None
            or name in (Path(v2_path).name, Path(calendar_path).name)):
        raise ValueError("invalid slot-local v2 school index version")
    path = folder / name
    if path.is_symlink() or path.resolve().parent != folder:
        raise ValueError("derived index must be a local non-symlink file")
    return path


def list_v2_school_index_versions(v2_path: str | Path,
                                  calendar_path: str | Path) -> tuple[str, ...]:
    """List 0..32 filename candidates. No integrity verdict or side effects."""
    folder = _source_directory(v2_path, calendar_path)
    if not folder.is_dir():
        return ()
    matches = sorted(
        child.name for child in folder.iterdir()
        if _VERSION.fullmatch(child.name)
        and child.is_file() and not child.is_symlink()
    )
    if len(matches) > MAX_VERSIONS:
        raise ValueError("too many index versions; choose a smaller save set")
    return tuple(matches)


def verify_v2_school_index_version(v2_path: str | Path,
                                   calendar_path: str | Path,
                                   name: str) -> dict:
    """Demand a strict, full-source 'ready' proof before manual selection."""
    path = _candidate_path(v2_path, calendar_path, name)
    if not path.is_file():
        raise FileNotFoundError("selected school index version is missing")
    health = audit_v2_school_index_health(
        v2_path, calendar_path, path,
    )
    if (health["status"] != "ready"
            or health["strict_original_payloads_verified"] is not True
            or health["strict_derived_memberships_verified"] is not True
            or health["original_saved_files_unmodified"] is not True):
        raise ValueError(
            "school index version is not ready: " + health["status"]
        )
    return {
        "filename": name,
        "path": str(path),
        "status": "ready",
        "indexed_saved_years": tuple(health["indexed_years"]),
        "strict_original_payloads_verified": True,
        "strict_derived_memberships_verified": True,
        "not_automatically_activated": True,
        "source_records_fictional": True,
    }
