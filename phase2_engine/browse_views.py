from __future__ import annotations

import csv
from datetime import date
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from .models import CompetitionRun
from .paths import resolve_data_file
from .repository import DataRepository
from .result_view import ResultViewRow, build_competition_result_view
from .season import SeasonExecution


@dataclass(frozen=True)
class DatedMatchRow:
    match_date: str
    date_source: str
    competition_id: str
    competition_name: str
    season_segment: str
    competition_type: str
    competition_level: str
    match_id: str
    stage_code: str
    phase_code: str
    round_no: int
    round_name: str
    group_id: str
    group_name: str
    team1_id: str
    team1_name: str
    team1_score: int | None
    team2_id: str
    team2_name: str
    team2_score: int | None
    winner_id: str
    winner_name: str
    loser_id: str
    loser_name: str
    is_bye: bool
    score_source: str
    result_text: str

    def to_dict(self) -> dict:
        row = asdict(self)
        row["is_bye"] = "yes" if self.is_bye else "no"
        return row


@dataclass(frozen=True)
class CompetitionResultRow:
    competition_id: str
    competition_name: str
    season_segment: str
    competition_type: str
    competition_level: str
    start_date: str
    end_date: str
    calendar_status: str
    scheduled_date_count: int
    first_match_date: str
    last_match_date: str
    date_sources: str
    match_count: int
    played_match_count: int
    bye_count: int
    participant_count: int
    champion_id: str
    champion_name: str
    runner_up_id: str
    runner_up_name: str
    total_runs: int
    average_total_runs: float
    score_sources: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SchoolRecordRow:
    school_id: str
    school_name: str
    prefecture_code: str
    competition_count: int
    competition_ids: str
    games: int
    wins: int
    losses: int
    win_pct: float
    runs_for: int
    runs_against: int
    run_differential: int
    titles: int
    runner_up_finishes: int
    last_game_date: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SeasonBrowseViews:
    matches_by_date: list[DatedMatchRow] = field(default_factory=list)
    competition_results: list[CompetitionResultRow] = field(default_factory=list)
    school_records: list[SchoolRecordRow] = field(default_factory=list)


def load_season_calendar(data_dir: str | Path) -> list[dict]:
    path = resolve_data_file(data_dir, "season_calendar.csv")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _parse_iso_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label}: invalid ISO date {value}") from exc


def _calendar_dates(row: dict) -> list[str]:
    values = [
        value.strip()
        for value in (row.get("game_date_list") or "").split(";")
        if value.strip()
    ]
    for value in values:
        _parse_iso_date(value, row.get("competition_id", "calendar"))
    if values != sorted(values):
        raise ValueError(
            f"{row.get('competition_id', 'calendar')}: game_date_list must be sorted"
        )
    if len(values) != len(set(values)):
        raise ValueError(
            f"{row.get('competition_id', 'calendar')}: duplicate game_date_list date"
        )
    return values


def _project_date_indices(match_count: int, date_count: int) -> list[int]:
    if match_count <= 0:
        return []
    if date_count <= 0:
        return [-1] * match_count
    if match_count == 1:
        return [date_count - 1]
    if date_count == 1:
        return [0] * match_count
    return [
        round(i * (date_count - 1) / (match_count - 1))
        for i in range(match_count)
    ]


def _dated_rows_for_competition(
    run: CompetitionRun,
    repo: DataRepository,
    calendar_row: dict,
    *,
    score_overrides: Mapping[str, object] | None = None,
    match_date_overrides: Mapping[str, str] | None = None,
) -> list[DatedMatchRow]:
    result_rows = build_competition_result_view(
        run,
        repo,
        score_overrides=score_overrides,
    )
    overrides = dict(match_date_overrides or {})
    result_by_id = {row.match_id: row for row in result_rows}
    unknown = set(overrides) - set(result_by_id)
    if unknown:
        raise ValueError(
            f"{run.competition_id}: date overrides reference unknown match ids: "
            f"{sorted(unknown)}"
        )
    for match_id in overrides:
        if result_by_id[match_id].is_bye:
            raise ValueError(f"{match_id}: bye match cannot have a match_date override")

    dates = _calendar_dates(calendar_row)
    normalized_overrides: dict[str, str] = {}
    for match_id, value in overrides.items():
        if not isinstance(value, str):
            raise ValueError(f"{match_id}: match_date override must be YYYY-MM-DD")
        parsed = _parse_iso_date(value, match_id)
        normalized_overrides[match_id] = parsed.isoformat()
    overrides = normalized_overrides

    actual_rows = [row for row in result_rows if not row.is_bye]
    projected_indices = _project_date_indices(len(actual_rows), len(dates))
    projected_by_id: dict[str, str] = {}
    for row, idx in zip(actual_rows, projected_indices):
        projected_by_id[row.match_id] = "" if idx < 0 else dates[idx]

    if dates:
        allowed = set(dates)
        outside = {
            match_id: value
            for match_id, value in overrides.items()
            if value not in allowed
        }
        if outside:
            raise ValueError(
                f"{run.competition_id}: date overrides outside game_date_list: {outside}"
            )
    elif overrides:
        start = (calendar_row.get("start_date") or "").strip()
        end = (calendar_row.get("end_date") or "").strip()
        if start:
            _parse_iso_date(start, f"{run.competition_id}:start_date")
        if end:
            _parse_iso_date(end, f"{run.competition_id}:end_date")
        outside = {
            match_id: value
            for match_id, value in overrides.items()
            if (start and value < start) or (end and value > end)
        }
        if outside:
            raise ValueError(
                f"{run.competition_id}: date overrides outside start/end: {outside}"
            )

    comp = repo.competition(run.competition_id)
    rows: list[DatedMatchRow] = []
    for row in result_rows:
        if row.is_bye:
            match_date = ""
            date_source = "bye"
        elif row.match_id in overrides:
            match_date = overrides[row.match_id]
            date_source = "override"
        elif dates:
            match_date = projected_by_id[row.match_id]
            date_source = "projected_v1"
        else:
            match_date = ""
            date_source = "undated"

        rows.append(DatedMatchRow(
            match_date=match_date,
            date_source=date_source,
            competition_id=run.competition_id,
            competition_name=comp.get("competition_name", ""),
            season_segment=comp.get("season_segment", ""),
            competition_type=comp.get("competition_type", ""),
            competition_level=comp.get("competition_level", ""),
            match_id=row.match_id,
            stage_code=row.stage_code,
            phase_code=row.phase_code,
            round_no=row.round_no,
            round_name=row.round_name,
            group_id=row.group_id,
            group_name=row.group_name,
            team1_id=row.team1_id,
            team1_name=row.team1_name,
            team1_score=row.team1_score,
            team2_id=row.team2_id,
            team2_name=row.team2_name,
            team2_score=row.team2_score,
            winner_id=row.winner_id,
            winner_name=row.winner_name,
            loser_id=row.loser_id,
            loser_name=row.loser_name,
            is_bye=row.is_bye,
            score_source=row.score_source,
            result_text=row.result_text,
        ))
    return rows


def _competition_summary(
    run: CompetitionRun,
    repo: DataRepository,
    calendar_row: dict,
    rows: list[DatedMatchRow],
) -> CompetitionResultRow:
    comp = repo.competition(run.competition_id)
    played = [row for row in rows if not row.is_bye]
    participants = {
        school_id
        for row in rows
        for school_id in (row.team1_id, row.team2_id)
        if school_id
    }
    dated = [row.match_date for row in played if row.match_date]
    total_runs = sum(
        int(row.team1_score or 0) + int(row.team2_score or 0)
        for row in played
    )
    champion_id = run.outcome.champion_school_id if run.outcome else ""
    runner_up_id = run.outcome.runner_up_school_id if run.outcome else ""
    score_sources = sorted({
        row.score_source for row in played if row.score_source
    })
    date_sources = sorted({
        row.date_source for row in played if row.date_source
    })
    return CompetitionResultRow(
        competition_id=run.competition_id,
        competition_name=comp.get("competition_name", ""),
        season_segment=comp.get("season_segment", ""),
        competition_type=comp.get("competition_type", ""),
        competition_level=comp.get("competition_level", ""),
        start_date=calendar_row.get("start_date", ""),
        end_date=calendar_row.get("end_date", ""),
        calendar_status=calendar_row.get("calendar_status", ""),
        scheduled_date_count=len(_calendar_dates(calendar_row)),
        first_match_date=min(dated, default=""),
        last_match_date=max(dated, default=""),
        date_sources=";".join(date_sources),
        match_count=len(rows),
        played_match_count=len(played),
        bye_count=sum(row.is_bye for row in rows),
        participant_count=len(participants),
        champion_id=champion_id,
        champion_name=repo.team(champion_id).display_name if champion_id else "",
        runner_up_id=runner_up_id,
        runner_up_name=repo.team(runner_up_id).display_name if runner_up_id else "",
        total_runs=total_runs,
        average_total_runs=round(total_runs / len(played), 3) if played else 0.0,
        score_sources=";".join(score_sources),
    )


def _school_records(
    season: SeasonExecution,
    repo: DataRepository,
    rows: list[DatedMatchRow],
) -> list[SchoolRecordRow]:
    state: dict[str, dict] = {}

    def ensure(school_id: str) -> dict:
        if school_id not in state:
            team = repo.team(school_id)
            state[school_id] = {
                "school_id": school_id,
                "school_name": team.display_name,
                "prefecture_code": team.prefecture_code,
                "competition_ids": set(),
                "games": 0,
                "wins": 0,
                "losses": 0,
                "runs_for": 0,
                "runs_against": 0,
                "titles": 0,
                "runner_up_finishes": 0,
                "last_game_date": "",
            }
        return state[school_id]

    for row in rows:
        for school_id in (row.team1_id, row.team2_id):
            if school_id:
                ensure(school_id)["competition_ids"].add(row.competition_id)

        if row.is_bye:
            continue

        if not row.team1_id or not row.team2_id:
            raise ValueError(f"{row.match_id}: played match requires two teams")
        if row.team1_score is None or row.team2_score is None:
            raise ValueError(f"{row.match_id}: played match requires scores")

        a = ensure(row.team1_id)
        b = ensure(row.team2_id)
        a["games"] += 1
        b["games"] += 1
        a["runs_for"] += row.team1_score
        a["runs_against"] += row.team2_score
        b["runs_for"] += row.team2_score
        b["runs_against"] += row.team1_score

        if row.winner_id == row.team1_id:
            a["wins"] += 1
            b["losses"] += 1
        elif row.winner_id == row.team2_id:
            b["wins"] += 1
            a["losses"] += 1
        else:
            raise ValueError(f"{row.match_id}: winner is not one of the teams")

        if row.match_date:
            a["last_game_date"] = max(a["last_game_date"], row.match_date)
            b["last_game_date"] = max(b["last_game_date"], row.match_date)

    for run in season.competition_runs.values():
        if not run.outcome:
            continue
        if run.outcome.champion_school_id:
            ensure(run.outcome.champion_school_id)["titles"] += 1
            ensure(run.outcome.champion_school_id)["competition_ids"].add(run.competition_id)
        if run.outcome.runner_up_school_id:
            ensure(run.outcome.runner_up_school_id)["runner_up_finishes"] += 1
            ensure(run.outcome.runner_up_school_id)["competition_ids"].add(run.competition_id)

    out: list[SchoolRecordRow] = []
    for school_id, item in state.items():
        games = item["games"]
        competition_ids = sorted(item["competition_ids"])
        out.append(SchoolRecordRow(
            school_id=school_id,
            school_name=item["school_name"],
            prefecture_code=item["prefecture_code"],
            competition_count=len(competition_ids),
            competition_ids=";".join(competition_ids),
            games=games,
            wins=item["wins"],
            losses=item["losses"],
            win_pct=round(item["wins"] / games, 3) if games else 0.0,
            runs_for=item["runs_for"],
            runs_against=item["runs_against"],
            run_differential=item["runs_for"] - item["runs_against"],
            titles=item["titles"],
            runner_up_finishes=item["runner_up_finishes"],
            last_game_date=item["last_game_date"],
        ))

    return sorted(
        out,
        key=lambda row: (
            -row.wins,
            -row.titles,
            row.school_name,
            row.school_id,
        ),
    )


def build_season_browse_views(
    season: SeasonExecution,
    repo: DataRepository,
    calendar_rows: Iterable[dict],
    *,
    score_overrides_by_competition: Mapping[str, Mapping[str, object]] | None = None,
    match_date_overrides_by_competition: Mapping[str, Mapping[str, str]] | None = None,
) -> SeasonBrowseViews:
    calendars = list(calendar_rows)
    calendar_by_comp = {
        row["competition_id"]: row
        for row in calendars
        if row.get("competition_id")
    }
    if len(calendar_by_comp) != len(calendars):
        raise ValueError("duplicate or empty competition_id in season calendar")

    score_overrides = dict(score_overrides_by_competition or {})
    date_overrides = dict(match_date_overrides_by_competition or {})
    unknown_score_comps = set(score_overrides) - set(season.competition_runs)
    unknown_date_comps = set(date_overrides) - set(season.competition_runs)
    if unknown_score_comps:
        raise ValueError(f"score overrides for unknown competition runs: {sorted(unknown_score_comps)}")
    if unknown_date_comps:
        raise ValueError(f"date overrides for unknown competition runs: {sorted(unknown_date_comps)}")

    matches: list[DatedMatchRow] = []
    competitions: list[CompetitionResultRow] = []

    for competition_id in sorted(season.competition_runs):
        run = season.competition_runs[competition_id]
        if competition_id not in calendar_by_comp:
            raise ValueError(f"missing calendar row for {competition_id}")
        calendar_row = calendar_by_comp[competition_id]
        rows = _dated_rows_for_competition(
            run,
            repo,
            calendar_row,
            score_overrides=score_overrides.get(competition_id),
            match_date_overrides=date_overrides.get(competition_id),
        )
        matches.extend(rows)
        competitions.append(_competition_summary(
            run,
            repo,
            calendar_row,
            rows,
        ))

    matches.sort(key=lambda row: (
        row.match_date or "9999-12-31",
        row.competition_id,
        row.round_no,
        row.match_id,
    ))
    competitions.sort(key=lambda row: (
        row.start_date or "9999-12-31",
        row.competition_id,
    ))
    school_records = _school_records(season, repo, matches)

    return SeasonBrowseViews(
        matches_by_date=matches,
        competition_results=competitions,
        school_records=school_records,
    )


def _write_csv(path: Path, rows: Iterable[object], fieldnames: list[str]) -> None:
    items = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in items:
            writer.writerow(row.to_dict())


def save_season_browse_views(
    season: SeasonExecution,
    repo: DataRepository,
    data_dir: str | Path,
    output_dir: str | Path,
    *,
    score_overrides_by_competition: Mapping[str, Mapping[str, object]] | None = None,
    match_date_overrides_by_competition: Mapping[str, Mapping[str, str]] | None = None,
) -> dict:
    views = build_season_browse_views(
        season,
        repo,
        load_season_calendar(data_dir),
        score_overrides_by_competition=score_overrides_by_competition,
        match_date_overrides_by_competition=match_date_overrides_by_competition,
    )
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    matches_path = out / f"season_{season.year}_matches_by_date.csv"
    competitions_path = out / f"season_{season.year}_competition_results.csv"
    schools_path = out / f"season_{season.year}_school_records.csv"

    _write_csv(
        matches_path,
        views.matches_by_date,
        list(DatedMatchRow.__dataclass_fields__),
    )
    _write_csv(
        competitions_path,
        views.competition_results,
        list(CompetitionResultRow.__dataclass_fields__),
    )
    _write_csv(
        schools_path,
        views.school_records,
        list(SchoolRecordRow.__dataclass_fields__),
    )
    return {
        "matches_by_date_csv": str(matches_path),
        "competition_results_csv": str(competitions_path),
        "school_records_csv": str(schools_path),
    }
