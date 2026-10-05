from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .models import CompetitionRun


def save_competition_run(run: CompetitionRun, output_dir: str | Path) -> dict:
    """Persist one finished competition as GUI/database-friendly files."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{run.competition_id}_{run.year}"

    summary_path = out / f"{stem}_summary.json"
    summary_path.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    matches_path = out / f"{stem}_matches.csv"
    fields = [
        "match_id", "competition_id", "stage_id", "stage_code", "phase_code", "round_no",
        "round_name", "group_id", "group_name", "team1", "team2", "winner", "loser",
        "is_bye", "next_match_id", "next_match_side",
    ]
    with matches_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for execution in run.stage_executions:
            for m in execution.matches:
                w.writerow({
                    "match_id": m.match_id,
                    "competition_id": m.competition_id,
                    "stage_id": m.stage_id,
                    "stage_code": m.stage_code,
                    "phase_code": m.phase_code,
                    "round_no": m.round_no,
                    "round_name": m.metadata.get("round_name", ""),
                    "group_id": m.group_id,
                    "group_name": m.group_name,
                    "team1": m.team1,
                    "team2": m.team2,
                    "winner": m.winner,
                    "loser": m.loser,
                    "is_bye": "yes" if m.is_bye else "no",
                    "next_match_id": m.metadata.get("next_match_id", ""),
                    "next_match_side": m.metadata.get("next_match_side", ""),
                })

    placements_path = out / f"{stem}_placements.csv"
    with placements_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields2 = ["placement_group", "ordinal", "school_id"]
        w = csv.DictWriter(f, fieldnames=fields2)
        w.writeheader()
        if run.outcome:
            rows = []
            if run.outcome.champion_school_id:
                rows.append(("champion", 1, run.outcome.champion_school_id))
            if run.outcome.runner_up_school_id:
                rows.append(("runner_up", 2, run.outcome.runner_up_school_id))
            for i, sid in enumerate(run.outcome.semifinalist_school_ids, start=1):
                rows.append(("semifinalist", i, sid))
            for i, sid in enumerate(run.outcome.quarterfinalist_school_ids, start=1):
                rows.append(("quarterfinalist", i, sid))
            for group, ordinal, sid in rows:
                w.writerow({"placement_group": group, "ordinal": ordinal, "school_id": sid})

    return {
        "summary_json": str(summary_path),
        "matches_csv": str(matches_path),
        "placements_csv": str(placements_path),
    }
