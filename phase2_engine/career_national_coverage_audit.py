"""Stage43G-38: nationwide 2026 saved-school master and tournament-input audit.

This is a cross-prefecture *coverage smoke check*, NOT a 47-prefecture
match-by-match or future-year career-save E2E. The 2026 annual plan can
contain structural bootstrap entrants; this report does not confer actual
qualification or imply real game results.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from .live_season_planner import LiveSeasonGraphPlan
from .paths import resolve_data_file
from .repository import DataRepository
from .school_year import competition_school_year


EXPECTED_PREFECTURES = tuple(f"{i:02d}" for i in range(1, 48))
DOUBLE_SUMMER_PREFECTURES = frozenset(("01", "13"))


def _prefectures(data_root: str | Path) -> dict[str, str]:
    path = resolve_data_file(Path(data_root), "prefectures.csv")
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    codes = [row.get("prefecture_code", "") for row in rows]
    if len(codes) != 47 or len(set(codes)) != 47 or set(codes) != set(EXPECTED_PREFECTURES):
        raise ValueError("47 canonical prefectures are required")
    names = {row["prefecture_code"]: row["prefecture_name"] for row in rows}
    if any(not name for name in names.values()):
        raise ValueError("empty prefecture display name")
    return names


def audit_national_competition_inputs(
    repo: DataRepository, plan: LiveSeasonGraphPlan,
    data_root: str | Path,
) -> dict:
    """Audit explicit school IDs, summer area splits and 2026 event coverage.

    The exceptions here refer only to the 2026 *catalog*: Hokkaido spring
    and autumn are separate regional championships, Tokyo autumn is a
    region-level competition. They are not permanent future-year rules.
    """
    if plan.year != 2026:
        raise ValueError("Stage43G-38 supports the verified 2026 catalog only")
    names = _prefectures(data_root)
    issues: list[str] = []

    schools = defaultdict(set)
    for sid in repo.school_to_program:
        school = repo.schools.get(sid)
        if school is None:
            issues.append(f"registered hardball school missing master row: {sid}")
            continue
        pcode = school.get("prefecture_code")
        if pcode not in names:
            issues.append(f"invalid school prefecture: {sid}/{pcode}")
            continue
        schools[pcode].add(sid)

    catalog = {
        cid: c for cid, c in repo.competitions.items()
        if competition_school_year(c) == plan.year
    }
    calendar_ids = [row["competition_id"] for row in plan.calendar_rows]
    if len(calendar_ids) != len(set(calendar_ids)):
        issues.append("duplicate annual calendar competition ID")
    if set(catalog) != set(plan.entries):
        issues.append("competition catalog and annual plan IDs differ")
    if set(catalog) != set(plan.annual_templates):
        issues.append("competition catalog and annual templates differ")
    if set(catalog) != set(calendar_ids):
        issues.append("competition catalog and annual calendar IDs differ")
    for cid in catalog:
        if not repo.stages(cid):
            issues.append(f"competition has no stage definition: {cid}")

    def relevant(pcode: str, segment: str) -> list[str]:
        kind = f"{segment}_prefectural"
        if pcode == "01":
            # Dedicated Hokkaido regional tournament in the 2026 catalog.
            return [
                cid for cid, c in catalog.items()
                if c.get("competition_type") == f"{segment}_regional"
                and c.get("region_id") == "REG01"
            ]
        if pcode == "13" and segment == "autumn":
            return [
                cid for cid, c in catalog.items()
                if c.get("competition_type") == "autumn_regional"
                and c.get("region_id") == "REG04"
            ]
        return [
            cid for cid, c in catalog.items()
            if c.get("competition_type") == kind
            and c.get("prefecture_code") == pcode
        ]

    rows = []
    total_examined = 0
    for pcode in EXPECTED_PREFECTURES:
        spring = relevant(pcode, "spring")
        autumn = relevant(pcode, "autumn")
        summer = [
            cid for cid, c in catalog.items()
            if c.get("competition_type") == "summer_local_qualifier"
            and c.get("prefecture_code") == pcode
        ]
        expected_summer = 2 if pcode in DOUBLE_SUMMER_PREFECTURES else 1
        if not schools[pcode]:
            issues.append(f"{pcode}: no master hardball schools")
        if len(spring) != 1 or len(autumn) != 1 or len(summer) != expected_summer:
            issues.append(
                f"{pcode}: spring={len(spring)}, autumn={len(autumn)}, "
                f"summer={len(summer)}; expected 1/1/{expected_summer}"
            )

        summer_school_ids = set()
        summer_entrant_count = 0
        for cid in spring + autumn + summer:
            entry = plan.annual_templates.get(cid)
            if entry is None:
                issues.append(f"{pcode}: missing annual tournament input {cid}")
                continue
            input_schools = list(entry.entrant_school_ids)
            if len(input_schools) != len(set(input_schools)):
                issues.append(f"{pcode}: duplicate entrant in {cid}")
            for sid in input_schools:
                if sid not in schools[pcode]:
                    issues.append(f"{pcode}: foreign or unknown entrant {cid}/{sid}")
            if cid in summer:
                summer_entrant_count += len(input_schools)
                if not input_schools:
                    issues.append(f"{pcode}: empty summer local-qualifier input {cid}")
                duplicates = summer_school_ids.intersection(input_schools)
                if duplicates:
                    issues.append(
                        f"{pcode}: school entered both summer areas: "
                        + ",".join(sorted(duplicates)[:3])
                    )
                summer_school_ids.update(input_schools)
            total_examined += len(input_schools)

        rows.append({
            "prefecture_code": pcode,
            "prefecture_name": names[pcode],
            "registered_hardball_school_count": len(schools[pcode]),
            "spring_competition_ids": sorted(spring),
            "autumn_competition_ids": sorted(autumn),
            "summer_competition_ids": sorted(summer),
            "summer_input_school_count": summer_entrant_count,
            "summer_school_ids_unique": len(summer_school_ids) == summer_entrant_count,
            "summer_sources_are_game_templates": True,
        })

    summer_all = [
        cid for cid, c in catalog.items()
        if c.get("competition_type") == "summer_local_qualifier"
    ]
    summary = {
        "reference_year": 2026,
        "prefecture_count": len(rows),
        "registered_hardball_school_count": sum(len(v) for v in schools.values()),
        "competition_count": len(catalog),
        "summer_local_competition_count": len(summer_all),
        "national_plan_entry_count": len(plan.entries),
        "input_school_references_checked": total_examined,
        "issue_count": len(issues),
        "match_simulation_executed": False,
        "career_year_continuity_verified": False,
        "official_real_2026_entrant_results": False,
    }
    return {
        "ok": not issues,
        "summary": summary,
        "prefectures": rows,
        "issues": issues,
    }
