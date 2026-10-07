from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Iterable, Mapping

from .browse_views import (
    DatedMatchRow,
    build_season_browse_views,
    load_season_calendar,
)
from .repository import DataRepository
from .season import SeasonExecution


MATCH_PENDING = "pending"
MATCH_COMPLETED = "completed"
MATCH_UNSCHEDULED = "unscheduled"


@dataclass(frozen=True)
class RuntimeMatchResult:
    competition_id: str
    match_id: str
    team1_id: str
    team2_id: str
    team1_score: int | None
    team2_score: int | None
    winner_id: str
    loser_id: str
    score_source: str
    result_text: str
    ability_detail: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RuntimeMatchState:
    competition_id: str
    competition_name: str
    match_id: str
    match_date: str
    date_source: str
    stage_code: str
    phase_code: str
    round_no: int
    round_name: str
    group_id: str
    group_name: str
    team1_id: str
    team1_name: str
    team2_id: str
    team2_name: str
    is_bye: bool
    status: str
    completed_on: str = ""
    result: RuntimeMatchResult | None = None
    _prepared_result: RuntimeMatchResult | None = field(
        default=None,
        repr=False,
    )

    @property
    def key(self) -> str:
        return runtime_match_key(
            self.competition_id,
            self.match_id,
        )

    def public_dict(self) -> dict:
        row = {
            "competition_id": self.competition_id,
            "competition_name": self.competition_name,
            "match_id": self.match_id,
            "match_date": self.match_date,
            "date_source": self.date_source,
            "stage_code": self.stage_code,
            "phase_code": self.phase_code,
            "round_no": self.round_no,
            "round_name": self.round_name,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "team1_id": self.team1_id,
            "team1_name": self.team1_name,
            "team2_id": self.team2_id,
            "team2_name": self.team2_name,
            "is_bye": self.is_bye,
            "status": self.status,
            "completed_on": self.completed_on,
            "team1_score": None,
            "team2_score": None,
            "winner_id": "",
            "loser_id": "",
            "score_source": "",
            "result_text": "",
        }
        if self.result is not None:
            row.update({
                "team1_score": self.result.team1_score,
                "team2_score": self.result.team2_score,
                "winner_id": self.result.winner_id,
                "loser_id": self.result.loser_id,
                "score_source": self.result.score_source,
                "result_text": self.result.result_text,
            })
        return row


def runtime_match_key(
    competition_id: str,
    match_id: str,
) -> str:
    if not competition_id or not match_id:
        raise ValueError("competition_id and match_id are required")
    return f"{competition_id}:{match_id}"


def _parse_date(value: str | date, label: str) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{label}: invalid ISO date {value}"
        ) from exc


def _prepared_result(
    row: DatedMatchRow,
    season: SeasonExecution,
) -> RuntimeMatchResult:
    run = season.competition_runs[row.competition_id]
    ability_detail = run.match_simulation_results.get(row.match_id)
    return RuntimeMatchResult(
        competition_id=row.competition_id,
        match_id=row.match_id,
        team1_id=row.team1_id,
        team2_id=row.team2_id,
        team1_score=row.team1_score,
        team2_score=row.team2_score,
        winner_id=row.winner_id,
        loser_id=row.loser_id,
        score_source=row.score_source,
        result_text=row.result_text,
        ability_detail=(
            dict(ability_detail)
            if ability_detail is not None
            else None
        ),
    )


@dataclass
class SeasonRuntimeState:
    year: int
    rng_seed: int
    current_date: date
    matches: dict[str, RuntimeMatchState]
    start_date: date
    end_date: date
    history: list[dict] = field(default_factory=list)

    @classmethod
    def from_prepared_season(
        cls,
        season: SeasonExecution,
        repo: DataRepository,
        data_dir,
        *,
        start_date: str | date | None = None,
        score_overrides_by_competition: (
            Mapping[str, Mapping[str, object]] | None
        ) = None,
        match_date_overrides_by_competition: (
            Mapping[str, Mapping[str, str]] | None
        ) = None,
        calendar_rows: Iterable[dict] | None = None,
    ) -> "SeasonRuntimeState":
        calendars = (
            list(calendar_rows)
            if calendar_rows is not None
            else load_season_calendar(data_dir)
        )
        views = build_season_browse_views(
            season,
            repo,
            calendars,
            score_overrides_by_competition=(
                score_overrides_by_competition
            ),
            match_date_overrides_by_competition=(
                match_date_overrides_by_competition
            ),
        )

        dated_values = [
            _parse_date(row.match_date, row.match_id)
            for row in views.matches_by_date
            if row.match_date
        ]
        initial_date = (
            _parse_date(start_date, "start_date")
            if start_date is not None
            else date(season.year, 1, 1)
        )
        if initial_date.year != season.year:
            raise ValueError(
                "runtime start_date must be inside season year"
            )

        end = max(
            initial_date,
            (
                max(dated_values)
                if dated_values
                else date(season.year, 12, 31)
            ),
        )
        matches: dict[str, RuntimeMatchState] = {}

        for row in views.matches_by_date:
            key = runtime_match_key(
                row.competition_id,
                row.match_id,
            )
            if key in matches:
                raise ValueError(
                    f"duplicate runtime match key: {key}"
                )
            prepared = _prepared_result(row, season)
            if row.is_bye:
                status = MATCH_COMPLETED
                completed_on = initial_date.isoformat()
                result = prepared
            elif not row.match_date:
                status = MATCH_UNSCHEDULED
                completed_on = ""
                result = None
            elif _parse_date(row.match_date, row.match_id) < initial_date:
                status = MATCH_COMPLETED
                completed_on = row.match_date
                result = prepared
            else:
                status = MATCH_PENDING
                completed_on = ""
                result = None

            matches[key] = RuntimeMatchState(
                competition_id=row.competition_id,
                competition_name=row.competition_name,
                match_id=row.match_id,
                match_date=row.match_date,
                date_source=row.date_source,
                stage_code=row.stage_code,
                phase_code=row.phase_code,
                round_no=row.round_no,
                round_name=row.round_name,
                group_id=row.group_id,
                group_name=row.group_name,
                team1_id=row.team1_id,
                team1_name=row.team1_name,
                team2_id=row.team2_id,
                team2_name=row.team2_name,
                is_bye=row.is_bye,
                status=status,
                completed_on=completed_on,
                result=result,
                _prepared_result=prepared,
            )

        state = cls(
            year=season.year,
            rng_seed=season.rng_seed,
            current_date=initial_date,
            matches=matches,
            start_date=initial_date,
            end_date=end,
        )
        state._validate()
        return state

    def _validate(self) -> None:
        if self.current_date.year != self.year:
            raise ValueError("current_date must be inside season year")
        if self.start_date.year != self.year:
            raise ValueError("start_date must be inside season year")
        if self.current_date < self.start_date:
            raise ValueError("current_date cannot precede start_date")
        valid_statuses = {
            MATCH_PENDING,
            MATCH_COMPLETED,
            MATCH_UNSCHEDULED,
        }
        for key, match in self.matches.items():
            if key != match.key:
                raise ValueError(
                    f"{key}: runtime match key mismatch"
                )
            if match.status not in valid_statuses:
                raise ValueError(
                    f"{key}: unknown runtime match status"
                )
            if match.status == MATCH_COMPLETED:
                if match.result is None:
                    raise ValueError(
                        f"{key}: completed match requires result"
                    )
                if not match.completed_on:
                    raise ValueError(
                        f"{key}: completed match requires completed_on"
                    )
            else:
                if match.result is not None:
                    raise ValueError(
                        f"{key}: future result must stay hidden"
                    )

    def summary(self) -> dict:
        counts = {
            MATCH_PENDING: 0,
            MATCH_COMPLETED: 0,
            MATCH_UNSCHEDULED: 0,
        }
        for match in self.matches.values():
            counts[match.status] += 1
        completed_ability = sum(
            match.status == MATCH_COMPLETED
            and match.result is not None
            and match.result.ability_detail is not None
            for match in self.matches.values()
        )
        bye_count = sum(
            match.is_bye
            for match in self.matches.values()
        )
        completed_played = sum(
            match.status == MATCH_COMPLETED
            and not match.is_bye
            for match in self.matches.values()
        )
        return {
            "year": self.year,
            "rng_seed": self.rng_seed,
            "current_date": self.current_date.isoformat(),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "pending_match_count": counts[MATCH_PENDING],
            "completed_match_count": counts[MATCH_COMPLETED],
            "completed_played_match_count": completed_played,
            "unscheduled_match_count": counts[MATCH_UNSCHEDULED],
            "bye_count": bye_count,
            "today_match_count": len(self.today_matches()),
            "completed_ability_match_count": completed_ability,
            "history_count": len(self.history),
        }

    def today_matches(self) -> list[dict]:
        target = self.current_date.isoformat()
        rows = [
            match.public_dict()
            for match in self.matches.values()
            if match.match_date == target
            and match.status in {
                MATCH_PENDING,
                MATCH_COMPLETED,
            }
            and not match.is_bye
        ]
        return sorted(
            rows,
            key=lambda row: (
                row["competition_name"],
                row["round_no"],
                row["match_id"],
            ),
        )

    def matches_for_date(
        self,
        target: str | date,
    ) -> list[dict]:
        day = _parse_date(target, "target_date")
        rows = [
            match.public_dict()
            for match in self.matches.values()
            if match.match_date == day.isoformat()
            and not match.is_bye
        ]
        return sorted(
            rows,
            key=lambda row: (
                row["competition_name"],
                row["round_no"],
                row["match_id"],
            ),
        )

    def unscheduled_matches(self) -> list[dict]:
        return sorted(
            (
                match.public_dict()
                for match in self.matches.values()
                if match.status == MATCH_UNSCHEDULED
            ),
            key=lambda row: (
                row["competition_name"],
                row["round_no"],
                row["match_id"],
            ),
        )

    def play_today(self) -> list[RuntimeMatchResult]:
        target = self.current_date.isoformat()
        ready = sorted(
            (
                match
                for match in self.matches.values()
                if match.status == MATCH_PENDING
                and match.match_date == target
            ),
            key=lambda match: (
                match.competition_id,
                match.round_no,
                match.match_id,
            ),
        )
        results: list[RuntimeMatchResult] = []
        for match in ready:
            prepared = match._prepared_result
            if prepared is None:
                raise ValueError(
                    f"{match.key}: prepared result missing"
                )
            match.result = prepared
            match.completed_on = target
            match.status = MATCH_COMPLETED
            results.append(prepared)

        self.history.append({
            "action": "play_today",
            "date": target,
            "match_keys": [result_key(x) for x in results],
            "match_count": len(results),
        })
        self._validate()
        return results

    def next_day(self) -> dict:
        if self.current_date >= date(self.year, 12, 31):
            raise ValueError(
                "season runtime cannot advance beyond season year"
            )
        played = self.play_today()
        previous = self.current_date
        self.current_date = previous + timedelta(days=1)
        self.history.append({
            "action": "next_day",
            "from_date": previous.isoformat(),
            "to_date": self.current_date.isoformat(),
            "played_match_count": len(played),
        })
        self._validate()
        return {
            "from_date": previous.isoformat(),
            "to_date": self.current_date.isoformat(),
            "played_match_count": len(played),
        }

    def advance_to(
        self,
        target: str | date,
    ) -> dict:
        target_date = _parse_date(target, "target_date")
        if target_date.year != self.year:
            raise ValueError(
                "target_date must be inside season year"
            )
        if target_date < self.current_date:
            raise ValueError(
                "season runtime cannot move backward"
            )

        days = 0
        played = 0
        while self.current_date < target_date:
            result = self.next_day()
            days += 1
            played += int(result["played_match_count"])
        return {
            "current_date": self.current_date.isoformat(),
            "advanced_days": days,
            "played_match_count": played,
        }

    def advance_through(
        self,
        target: str | date,
    ) -> dict:
        result = self.advance_to(target)
        played_today = len(self.play_today())
        result["played_match_count"] += played_today
        result["processed_through"] = self.current_date.isoformat()
        return result

    def completed_results(self) -> dict[str, dict]:
        return {
            key: match.result.to_dict()
            for key, match in sorted(self.matches.items())
            if match.status == MATCH_COMPLETED
            and match.result is not None
            and not match.is_bye
        }

    def completed_ability_results(self) -> dict[str, dict]:
        return {
            key: dict(match.result.ability_detail)
            for key, match in sorted(self.matches.items())
            if match.status == MATCH_COMPLETED
            and match.result is not None
            and match.result.ability_detail is not None
            and not match.is_bye
        }

    def school_records(self) -> list[dict]:
        state: dict[str, dict] = {}

        def ensure(school_id: str, school_name: str) -> dict:
            row = state.get(school_id)
            if row is None:
                row = {
                    "school_id": school_id,
                    "school_name": school_name,
                    "games": 0,
                    "wins": 0,
                    "losses": 0,
                    "runs_for": 0,
                    "runs_against": 0,
                    "run_differential": 0,
                }
                state[school_id] = row
            return row

        for match in self.matches.values():
            if (
                match.status != MATCH_COMPLETED
                or match.is_bye
                or match.result is None
            ):
                continue
            result = match.result
            team1 = ensure(
                match.team1_id,
                match.team1_name,
            )
            team2 = ensure(
                match.team2_id,
                match.team2_name,
            )
            team1["games"] += 1
            team2["games"] += 1
            if result.winner_id == match.team1_id:
                team1["wins"] += 1
                team2["losses"] += 1
            elif result.winner_id == match.team2_id:
                team2["wins"] += 1
                team1["losses"] += 1
            else:
                raise ValueError(
                    f"{match.key}: winner not a participant"
                )

            if (
                result.team1_score is not None
                and result.team2_score is not None
            ):
                team1["runs_for"] += result.team1_score
                team1["runs_against"] += result.team2_score
                team2["runs_for"] += result.team2_score
                team2["runs_against"] += result.team1_score

        for row in state.values():
            row["run_differential"] = (
                row["runs_for"] - row["runs_against"]
            )
        return sorted(
            state.values(),
            key=lambda row: (
                -row["wins"],
                row["school_name"],
                row["school_id"],
            ),
        )

    def competition_state(
        self,
        competition_id: str,
    ) -> dict:
        items = [
            match
            for match in self.matches.values()
            if match.competition_id == competition_id
        ]
        if not items:
            raise KeyError(
                f"unknown competition_id: {competition_id}"
            )
        actual = [match for match in items if not match.is_bye]
        completed = [
            match
            for match in actual
            if match.status == MATCH_COMPLETED
        ]
        pending = [
            match
            for match in actual
            if match.status == MATCH_PENDING
        ]
        unscheduled = [
            match
            for match in actual
            if match.status == MATCH_UNSCHEDULED
        ]
        champion_id = ""
        if actual and len(completed) == len(actual):
            main_completed = [
                match
                for match in completed
                if match.stage_code == "MAIN"
            ]
            candidates = main_completed or completed
            last = max(
                candidates,
                key=lambda match: (
                    match.round_no,
                    match.match_date,
                    match.match_id,
                ),
            )
            champion_id = (
                last.result.winner_id
                if last.result is not None
                else ""
            )
        return {
            "competition_id": competition_id,
            "competition_name": items[0].competition_name,
            "match_count": len(actual),
            "completed_match_count": len(completed),
            "pending_match_count": len(pending),
            "unscheduled_match_count": len(unscheduled),
            "is_complete": bool(actual)
            and len(completed) == len(actual),
            "champion_school_id": champion_id,
        }

    def public_snapshot(self) -> dict:
        return {
            "year": self.year,
            "rng_seed": self.rng_seed,
            "current_date": self.current_date.isoformat(),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "summary": self.summary(),
            "matches": [
                match.public_dict()
                for _, match in sorted(self.matches.items())
            ],
            "history": [dict(item) for item in self.history],
        }


def result_key(result: RuntimeMatchResult) -> str:
    return runtime_match_key(
        result.competition_id,
        result.match_id,
    )
