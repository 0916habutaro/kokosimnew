from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .models import CompetitionRun, Match
from .randomness import rng_for
from .repository import DataRepository


@dataclass(frozen=True)
class ResultViewRow:
    match_id: str
    competition_id: str
    stage_id: str
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


_LOSER_RUNS = list(range(10))
_LOSER_WEIGHTS = [7, 14, 19, 19, 15, 10, 7, 4, 3, 2]
_MARGIN_RUNS = list(range(1, 9))
_MARGIN_WEIGHTS = [34, 25, 16, 10, 7, 4, 2, 2]


def _display_name(repo: DataRepository, school_id: str) -> str:
    if not school_id:
        return ""
    return repo.team(school_id).display_name


def _generated_score(run: CompetitionRun, match: Match) -> tuple[int, int]:
    if not match.team1 or not match.team2:
        raise ValueError(f"{match.match_id}: non-bye match requires two teams")
    if match.team1 == match.team2:
        raise ValueError(f"{match.match_id}: team1 and team2 must differ")
    if match.winner not in {match.team1, match.team2}:
        raise ValueError(f"{match.match_id}: winner must be team1 or team2")
    if match.loser and match.loser not in {match.team1, match.team2}:
        raise ValueError(f"{match.match_id}: loser must be team1 or team2")
    if match.loser and match.loser == match.winner:
        raise ValueError(f"{match.match_id}: winner and loser must differ")

    rng = rng_for(
        run.rng_seed,
        f"score_v1:{run.competition_id}:{run.year}:{match.match_id}",
    )
    losing_score = rng.choices(_LOSER_RUNS, weights=_LOSER_WEIGHTS, k=1)[0]
    margin = rng.choices(_MARGIN_RUNS, weights=_MARGIN_WEIGHTS, k=1)[0]
    winning_score = losing_score + margin
    if match.winner == match.team1:
        return winning_score, losing_score
    return losing_score, winning_score


def _normalize_override(
    match_id: str,
    value,
) -> tuple[int, int]:
    if isinstance(value, Mapping):
        if "team1_score" not in value or "team2_score" not in value:
            raise ValueError(
                f"{match_id}: score override mapping requires team1_score/team2_score"
            )
        pair = (value["team1_score"], value["team2_score"])
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        pair = (value[0], value[1])
    else:
        raise ValueError(
            f"{match_id}: score override must be [team1_score, team2_score] "
            "or a mapping with team1_score/team2_score"
        )

    if any(isinstance(x, bool) or not isinstance(x, int) for x in pair):
        raise ValueError(f"{match_id}: scores must be integers")
    if any(x < 0 for x in pair):
        raise ValueError(f"{match_id}: scores must be non-negative")
    if pair[0] == pair[1]:
        raise ValueError(f"{match_id}: baseball result score cannot be tied")
    return pair


def _validate_score_winner(match: Match, team1_score: int, team2_score: int) -> None:
    expected = match.team1 if team1_score > team2_score else match.team2
    if match.winner != expected:
        raise ValueError(
            f"{match.match_id}: score winner {expected} does not match "
            f"tournament winner {match.winner}"
        )


def build_competition_result_view(
    run: CompetitionRun,
    repo: DataRepository,
    *,
    score_overrides: Mapping[str, object] | None = None,
) -> list[ResultViewRow]:
    overrides = dict(score_overrides or {})
    matches = [
        match
        for execution in run.stage_executions
        for match in execution.matches
    ]
    match_ids = [match.match_id for match in matches]
    if len(match_ids) != len(set(match_ids)):
        raise ValueError("duplicate match_id in competition run")

    unknown_override_ids = set(overrides) - set(match_ids)
    if unknown_override_ids:
        raise ValueError(
            f"score overrides reference unknown match ids: "
            f"{sorted(unknown_override_ids)}"
        )

    rows: list[ResultViewRow] = []
    for match in matches:
        team1_name = _display_name(repo, match.team1)
        team2_name = _display_name(repo, match.team2)
        winner_name = _display_name(repo, match.winner)
        loser_name = _display_name(repo, match.loser)

        if match.is_bye:
            if match.match_id in overrides:
                raise ValueError(f"{match.match_id}: bye match cannot have a score override")
            if match.team2:
                raise ValueError(f"{match.match_id}: bye match must not have team2")
            if match.winner and match.winner != match.team1:
                raise ValueError(f"{match.match_id}: bye winner must equal team1")
            result_text = f"{team1_name} 不戦勝" if team1_name else "不戦勝"
            team1_score = None
            team2_score = None
            score_source = "bye"
        else:
            if match.match_id in overrides:
                team1_score, team2_score = _normalize_override(
                    match.match_id,
                    overrides[match.match_id],
                )
                score_source = "override"
            else:
                team1_score, team2_score = _generated_score(run, match)
                score_source = "generated_v1"
            _validate_score_winner(match, team1_score, team2_score)
            result_text = f"{team1_name} {team1_score}-{team2_score} {team2_name}"

        rows.append(ResultViewRow(
            match_id=match.match_id,
            competition_id=match.competition_id,
            stage_id=match.stage_id,
            stage_code=match.stage_code,
            phase_code=match.phase_code,
            round_no=match.round_no,
            round_name=str(match.metadata.get("round_name", "")),
            group_id=match.group_id,
            group_name=match.group_name,
            team1_id=match.team1,
            team1_name=team1_name,
            team1_score=team1_score,
            team2_id=match.team2,
            team2_name=team2_name,
            team2_score=team2_score,
            winner_id=match.winner,
            winner_name=winner_name,
            loser_id=match.loser,
            loser_name=loser_name,
            is_bye=match.is_bye,
            score_source=score_source,
            result_text=result_text,
        ))

    return rows


def write_competition_result_view_csv(
    rows: Iterable[ResultViewRow],
    path: str | Path,
) -> None:
    items = list(rows)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(ResultViewRow.__dataclass_fields__)
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in items:
            writer.writerow(row.to_dict())


def save_competition_result_view(
    run: CompetitionRun,
    repo: DataRepository,
    output_dir: str | Path,
    *,
    score_overrides: Mapping[str, object] | None = None,
) -> str:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{run.competition_id}_{run.year}_result_view.csv"
    rows = build_competition_result_view(
        run,
        repo,
        score_overrides=score_overrides,
    )
    write_competition_result_view_csv(rows, path)
    return str(path)
