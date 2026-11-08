"""Fail-closed docs-only CI route for pull_request and main push.

Only whitelisted prose docs and research CSVs bypass game tests.
Manual triggers, unknown revisions and git errors always run the full workload.
"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
_SHA = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")
_ROOT_DOCS = frozenset({"README.md", "CHANGELOG.md", "CONTRIBUTING.md",
                        "AGENTS.md", "CLAUDE.md"})
_DOC_EXT = frozenset({".md", ".markdown", ".rst"})


def _safe_repo_path(name: str) -> bool:
    return bool(name and not name.startswith("/") and "\\" not in name
                and "\x00" not in name
                and all(part not in ("", ".", "..") for part in name.split("/")))


def is_research_csv_path(name: str) -> bool:
    """Only CSVs under docs/research; other CSVs can affect the game."""
    if not _safe_repo_path(name):
        return False
    path = PurePosixPath(name)
    return (len(path.parts) >= 3 and path.parts[:2] == ("docs", "research")
            and path.suffix.lower() == ".csv")


def is_documentation_path(name: str) -> bool:
    """Only explicitly whitelisted docs and research CSV, not scripts/config."""
    if not _safe_repo_path(name):
        return False
    path = PurePosixPath(name)
    if len(path.parts) == 1:
        return name in _ROOT_DOCS
    return ((path.parts[0] == "docs" and path.suffix.lower() in _DOC_EXT)
            or is_research_csv_path(name))



def changed_paths(base: str, head: str):
    """Return all changed paths or None when complete diff cannot be verified."""
    try:
        completed = subprocess.run(
            ["git", "diff", "--no-ext-diff", "--no-renames", "--name-only",
             "--diff-filter=ACDMRTUXB", "-z", base, head],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=60, check=False,
        )
        if completed.returncode != 0:
            return None
        raw = completed.stdout.decode("utf-8")
        if not raw or not raw.endswith("\x00"):
            return None
        paths = raw[:-1].split("\x00")
        if not paths or any(not path for path in paths):
            return None
        return paths
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return None


def route(event: str, ref: str, base: str, head: str, *, paths=None):
    """Returns (docs_only, explanation). Unknown => full CI."""
    if event not in ("pull_request", "push"):
        return False, "manual/unknown event requires full CI"
    if event == "push" and ref != "refs/heads/main":
        return False, "non-main push requires full CI"
    if (not _SHA.fullmatch(base or "") or not _SHA.fullmatch(head or "")
            or base == head or set(base) == {"0"}):
        return False, "invalid/unknown comparison revisions"
    if paths is None:
        paths = changed_paths(base, head)
    if not paths:
        return False, "missing/empty git diff; fail closed"
    if all(is_documentation_path(p) for p in paths):
        return True, "all changes are allowlisted documentation/research CSV"
    return False, "non-documentation or mixed changes require full CI"


def main() -> int:
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    ref = os.environ.get("GITHUB_REF", "")
    base = os.environ.get("CI_BASE_SHA", "")
    head = os.environ.get("CI_HEAD_SHA", "")
    docs_only, reason = route(event, ref, base, head)
    mode = "docs-only" if docs_only else "full"
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"docs_only={'true' if docs_only else 'false'}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(f"### CI workload: {mode}\n\n{reason}.\n\n")
    print(f"CI workload: {mode}; {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
