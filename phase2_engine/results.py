from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import CompetitionRun


def _write_csv(
    path: Path,
    fieldnames: list[str],
    rows: list[dict],
) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _save_match_simulation_results(
    run: CompetitionRun,
    out: Path,
    stem: str,
) -> dict[str, str]:
    details = dict(run.match_simulation_results or {})
    if not details:
        return {}

    match_rows: list[dict] = []
    batter_rows: list[dict] = []
    pitcher_rows: list[dict] = []
    team_rows: list[dict] = []
    event_rows: list[dict] = []

    for match_id, detail in sorted(details.items()):
        match_rows.append({
            "match_id": match_id,
            "competition_id": detail.get("competition_id", ""),
            "reference_year": detail.get("reference_year", ""),
            "generation_seed": detail.get("generation_seed", ""),
            "team1_school_id": detail.get("team1_school_id", ""),
            "team2_school_id": detail.get("team2_school_id", ""),
            "team1_score": detail.get("team1_score", ""),
            "team2_score": detail.get("team2_score", ""),
            "winner_id": detail.get("winner_id", ""),
            "loser_id": detail.get("loser_id", ""),
            "last_inning": detail.get("last_inning", ""),
            "ending_half": detail.get("ending_half", ""),
            "score_source": detail.get("score_source", ""),
            "match_config_id": detail.get("match_config_id", ""),
            "match_config_revision": detail.get("match_config_revision", ""),
            "match_config_sha256": detail.get("match_config_sha256", ""),
            "event_catalog_id": detail.get("event_catalog_id", ""),
            "event_catalog_revision": detail.get("event_catalog_revision", ""),
            "event_catalog_sha256": detail.get("event_catalog_sha256", ""),
            "stats_config_id": detail.get("stats_config_id", ""),
            "stats_config_revision": detail.get("stats_config_revision", ""),
            "stats_config_sha256": detail.get("stats_config_sha256", ""),
        })

        for row in detail.get("batter_stats", []):
            batter_rows.append({"match_id": match_id, **row})
        for row in detail.get("pitcher_stats", []):
            pitcher_rows.append({"match_id": match_id, **row})
        for row in detail.get("team_stats", []):
            team_rows.append({"match_id": match_id, **row})
        for row in detail.get("events", []):
            item = dict(row)
            metadata = item.pop("metadata", {})
            event_rows.append({
                "match_id": match_id,
                **item,
                "metadata_json": json.dumps(
                    metadata,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            })

    paths: dict[str, str] = {}

    match_path = out / f"{stem}_ability_matches.csv"
    _write_csv(
        match_path,
        [
            "match_id",
            "competition_id",
            "reference_year",
            "generation_seed",
            "team1_school_id",
            "team2_school_id",
            "team1_score",
            "team2_score",
            "winner_id",
            "loser_id",
            "last_inning",
            "ending_half",
            "score_source",
            "match_config_id",
            "match_config_revision",
            "match_config_sha256",
            "event_catalog_id",
            "event_catalog_revision",
            "event_catalog_sha256",
            "stats_config_id",
            "stats_config_revision",
            "stats_config_sha256",
        ],
        match_rows,
    )
    paths["ability_matches_csv"] = str(match_path)

    batter_path = out / f"{stem}_batter_game_stats.csv"
    _write_csv(
        batter_path,
        [
            "match_id",
            "player_id",
            "school_id",
            "plate_appearances",
            "at_bats",
            "runs",
            "hits",
            "doubles",
            "triples",
            "home_runs",
            "rbi",
            "walks",
            "strikeouts",
            "hit_by_pitch",
            "sacrifice_flies",
            "sacrifice_bunts",
            "stolen_bases",
            "caught_stealing",
            "singles",
        ],
        batter_rows,
    )
    paths["batter_game_stats_csv"] = str(batter_path)

    pitcher_path = out / f"{stem}_pitcher_game_stats.csv"
    _write_csv(
        pitcher_path,
        [
            "match_id",
            "player_id",
            "school_id",
            "outs_recorded",
            "batters_faced",
            "runs_allowed",
            "earned_runs",
            "hits_allowed",
            "home_runs_allowed",
            "walks",
            "strikeouts",
            "hit_batters",
        ],
        pitcher_rows,
    )
    paths["pitcher_game_stats_csv"] = str(pitcher_path)

    team_path = out / f"{stem}_team_game_stats.csv"
    _write_csv(
        team_path,
        [
            "match_id",
            "school_id",
            "runs",
            "hits",
            "errors",
        ],
        team_rows,
    )
    paths["team_game_stats_csv"] = str(team_path)

    event_path = out / f"{stem}_match_events.csv"
    _write_csv(
        event_path,
        [
            "match_id",
            "event_no",
            "plate_appearance_no",
            "inning",
            "half",
            "offense_school_id",
            "defense_school_id",
            "batter_id",
            "pitcher_id",
            "event_type",
            "runs_scored",
            "outs_on_play",
            "rbi",
            "metadata_json",
        ],
        event_rows,
    )
    paths["match_events_csv"] = str(event_path)

    return paths


def save_competition_run(run: CompetitionRun, output_dir: str | Path) -> dict:
    """Persist one finished competition as GUI/database-friendly files."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{run.competition_id}_{run.year}"

    summary_path = out / f"{stem}_summary.json"
    summary_path.write_text(
        json.dumps(run.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    matches_path = out / f"{stem}_matches.csv"
    fields = [
        "match_id",
        "competition_id",
        "stage_id",
        "stage_code",
        "phase_code",
        "round_no",
        "round_name",
        "group_id",
        "group_name",
        "team1",
        "team2",
        "winner",
        "loser",
        "is_bye",
        "score_source",
        "team1_score",
        "team2_score",
        "next_match_id",
        "next_match_side",
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
                    "score_source": m.metadata.get("score_source", ""),
                    "team1_score": m.metadata.get("team1_score", ""),
                    "team2_score": m.metadata.get("team2_score", ""),
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
            for i, sid in enumerate(
                run.outcome.semifinalist_school_ids,
                start=1,
            ):
                rows.append(("semifinalist", i, sid))
            for i, sid in enumerate(
                run.outcome.quarterfinalist_school_ids,
                start=1,
            ):
                rows.append(("quarterfinalist", i, sid))
            for group, ordinal, sid in rows:
                w.writerow({
                    "placement_group": group,
                    "ordinal": ordinal,
                    "school_id": sid,
                })

    paths = {
        "summary_json": str(summary_path),
        "matches_csv": str(matches_path),
        "placements_csv": str(placements_path),
    }
    paths.update(_save_match_simulation_results(run, out, stem))
    return paths
