from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from .season import SeasonExecution


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["status"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def save_season_execution(season: SeasonExecution, output_dir: str | Path) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = out / f"season_{season.year}_summary.json"
    summary.write_text(json.dumps(season.summary(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pref = out / f"season_{season.year}_prefectural.csv"
    _write_csv(pref, [asdict(x) for x in season.prefectural_rows])

    access = out / f"season_{season.year}_access_dependencies.csv"
    access_rows = []
    for x in season.access_resolutions:
        row = asdict(x); row["resolved_school_ids"] = ";".join(row["resolved_school_ids"])
        access_rows.append(row)
    _write_csv(access, access_rows)

    qual = out / f"season_{season.year}_qualification_dependencies.csv"
    qual_rows = []
    for x in season.qualification_resolutions:
        row = asdict(x); row["resolved_school_ids"] = ";".join(row["resolved_school_ids"])
        qual_rows.append(row)
    _write_csv(qual, qual_rows)

    feeder = out / f"season_{season.year}_regional_feeder_resolutions.csv"
    feeder_rows = []
    for x in season.regional_feeder_resolutions:
        row = asdict(x); row["resolved_school_ids"] = ";".join(row["resolved_school_ids"])
        feeder_rows.append(row)
    _write_csv(feeder, feeder_rows)

    playoff = out / f"season_{season.year}_regional_playoffs.csv"
    _write_csv(playoff, [asdict(x) for x in season.regional_playoff_resolutions])

    regionals = out / f"season_{season.year}_regional_competitions.csv"
    _write_csv(regionals, [asdict(x) for x in season.regional_rows])

    gaps = out / f"season_{season.year}_regional_bridge_gaps.csv"
    gap_rows = []
    for x in season.regional_bridge_gaps:
        row = asdict(x)
        row["source_prefectural_competition_ids"] = ";".join(row["source_prefectural_competition_ids"])
        row["member_prefecture_codes"] = ";".join(row["member_prefecture_codes"])
        gap_rows.append(row)
    _write_csv(gaps, gap_rows)

    calendar_gaps = out / f"season_{season.year}_calendar_gaps.csv"
    _write_csv(calendar_gaps, [asdict(x) for x in season.calendar_gaps])

    structure_gaps = out / f"season_{season.year}_internal_structure_gaps.csv"
    _write_csv(structure_gaps, [asdict(x) for x in season.internal_structure_gaps])

    return {
        "summary_json": str(summary),
        "prefectural_csv": str(pref),
        "access_csv": str(access),
        "qualification_csv": str(qual),
        "regional_feeder_csv": str(feeder),
        "regional_playoff_csv": str(playoff),
        "regional_competitions_csv": str(regionals),
        "regional_gaps_csv": str(gaps),
        "calendar_gaps_csv": str(calendar_gaps),
        "internal_structure_gaps_csv": str(structure_gaps),
    }
