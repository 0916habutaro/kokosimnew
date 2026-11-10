"""Lightweight structural validation of changed docs/research CSV files.

No game data or code is loaded. Deletes are allowed; existing changed CSVs
must be UTF-8, rectangular, nonempty, and free of duplicated records.
"""
from __future__ import annotations

import csv
import io
import os
from pathlib import Path
import re
import subprocess

from ci_change_scope import ROOT, changed_paths, is_research_csv_path

_SHA = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")
_UNIQUE_KEYS = {
    "prefectural_seed_rules_2026.csv": ("年度", "季節", "都道府県"),
    "regional_seed_rules_2026.csv": ("年度", "季節", "地区"),
    "seed_examples_2026.csv": ("年度", "季節", "区分", "大会名", "学校名（原資料表記）"),
}


class CSVValidationError(ValueError):
    pass


def validate_csv(path: Path, repository_path: str = "") -> int:
    """Check UTF-8, rectangular shape, header/keys and duplicates; allow varying data row counts."""
    try:
        data = path.read_bytes()
        if b"\x00" in data:
            raise CSVValidationError("NUL byte in CSV")
        text = data.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, None)
        if not header:
            raise CSVValidationError("missing header")
        names = [name.strip() for name in header]
        if any(not name for name in names) or len(set(names)) != len(names):
            raise CSVValidationError("empty or duplicate header column")
        unique = _UNIQUE_KEYS.get(path.name, ())
        if unique and any(column not in names for column in unique):
            raise CSVValidationError(f"missing key columns: {unique}")
        key_columns = tuple(names.index(column) for column in unique)
        seen_rows: set[tuple[str, ...]] = set()
        seen_keys: set[tuple[str, ...]] = set()
        count = 0
        for row in reader:
            line = reader.line_num
            if len(row) != len(header):
                raise CSVValidationError(
                    f"line {line}: expected {len(header)} columns, got {len(row)}")
            if not any(value.strip() for value in row):
                raise CSVValidationError(f"line {line}: empty record")
            record = tuple(row)
            if record in seen_rows:
                raise CSVValidationError(f"line {line}: duplicate record")
            seen_rows.add(record)
            if key_columns:
                key = tuple(row[index].strip() for index in key_columns)
                if any(not value for value in key):
                    raise CSVValidationError(f"line {line}: empty key field")
                if key in seen_keys:
                    raise CSVValidationError(f"line {line}: duplicate document key {key}")
                seen_keys.add(key)
            count += 1
        if count == 0:
            raise CSVValidationError("no data rows")
        return count
    except (UnicodeError, csv.Error, OSError) as exc:
        raise CSVValidationError(str(exc)) from exc


def head_research_paths(head: str) -> set[str]:
    """Find paths tracked in the comparison head; a missing path means deletion."""
    completed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", head, "--", "docs/research"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=60, check=False,
    )
    if completed.returncode != 0 or (completed.stdout and not completed.stdout.endswith(b"\x00")):
        raise CSVValidationError("cannot inspect Git head tree")
    return set(path for path in completed.stdout.decode("utf-8").split("\x00") if path)


def main() -> int:
    base = os.environ.get("CI_BASE_SHA", "")
    head = os.environ.get("CI_HEAD_SHA", "")
    if (not _SHA.fullmatch(base or "") or not _SHA.fullmatch(head or "")
            or base == head or set(base) == {"0"}):
        print("research CSV validation: invalid comparison revisions")
        return 1
    paths = changed_paths(base, head)
    if not paths:
        print("research CSV validation: cannot inspect changed paths")
        return 1
    csv_paths = sorted(path for path in paths if is_research_csv_path(path))
    if not csv_paths:
        print("research CSV validation: no changed CSV files")
        return 0
    try:
        at_head = head_research_paths(head)
        checked = 0
        for name in csv_paths:
            if name not in at_head:
                print(f"SKIP deleted CSV: {name}")
                continue
            path = ROOT / name
            if not path.is_file():
                raise CSVValidationError(f"missing checked-out CSV: {name}")
            count = validate_csv(path, name)
            print(f"OK {name}: {count} data rows")
            checked += 1
        print(f"research CSV validation: {checked} files passed")
        return 0
    except (CSVValidationError, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        print(f"research CSV validation FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
