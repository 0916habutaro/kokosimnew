from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Mapping, Sequence

from .competition_schedule_runtime import (
    SCHEDULE_COMPLETED,
    SCHEDULE_PENDING,
    ScheduledCompetitionRuntime,
    _iso_date,
)
from .models import AnnualCompetitionInput
from .repository import DataRepository


@dataclass
class LiveSeasonRuntimeState:
    """Season clock backed by genuinely lazy competition runtimes.

    Unlike Stage 13E-1 SeasonRuntimeState.from_prepared_season(), this state never
    stores a prepared future CompetitionRun. Each competition is advanced through
    ScheduledCompetitionRuntime and MatchResolver is called only on the simulated
    game date.
    """

    year: int
    rng_seed: int
    current_date: date
    start_date: date
    end_date: date
    competitions: dict[str, ScheduledCompetitionRuntime]
    repo: DataRepository = field(repr=False)
    history: list[dict] = field(default_factory=list)

    @classmethod
    def from_annual_inputs(
        cls,
        *,
        engine,
        repo: DataRepository,
        annual_inputs: Sequence[AnnualCompetitionInput],
        calendar_rows: Sequence[Mapping[str, str]],
        rng_seed: int,
        start_date: str | date | None = None,
        stage_date_lists_by_competition: (
            Mapping[str, Mapping[str, Sequence[str]]] | None
        ) = None,
    ) -> "LiveSeasonRuntimeState":
        if not annual_inputs:
            raise ValueError("annual_inputs is required")
        years = {annual.year for annual in annual_inputs}
        if len(years) != 1:
            raise ValueError(
                "all annual inputs must use the same season year"
            )
        year = next(iter(years))
        calendar_by_comp = {
            row.get("competition_id", ""): row
            for row in calendar_rows
            if row.get("competition_id")
        }
        if len(calendar_by_comp) != len(calendar_rows):
            raise ValueError(
                "duplicate or empty competition_id in calendar rows"
            )

        initial = (
            start_date
            if isinstance(start_date, date)
            else (
                date.fromisoformat(
                    _iso_date(start_date, "start_date")
                )
                if start_date is not None
                else date(year, 1, 1)
            )
        )
        if initial.year != year:
            raise ValueError(
                "runtime start_date must be inside season year"
            )

        stage_dates = dict(
            stage_date_lists_by_competition or {}
        )
        competitions = {}
        for annual in annual_inputs:
            cid = annual.competition_id
            if cid in competitions:
                raise ValueError(
                    f"duplicate annual input for {cid}"
                )
            if cid not in calendar_by_comp:
                raise ValueError(
                    f"missing calendar row for {cid}"
                )
            runtime = engine.prepare_competition_runtime(
                annual
            )
            competitions[cid] = (
                ScheduledCompetitionRuntime.from_calendar_row(
                    repo,
                    runtime,
                    calendar_by_comp[cid],
                    stage_date_lists=stage_dates.get(cid),
                )
            )

        all_dates = [
            value
            for scheduled in competitions.values()
            for value in (
                scheduled.calendar_dates
                + [
                    item
                    for values
                    in scheduled.stage_date_lists.values()
                    for item in values
                ]
            )
        ]
        end = max(
            [initial]
            + (
                [date.fromisoformat(value) for value in all_dates]
                if all_dates
                else [date(year, 12, 31)]
            )
        )

        state = cls(
            year=year,
            rng_seed=rng_seed,
            current_date=initial,
            start_date=initial,
            end_date=end,
            competitions=competitions,
            repo=repo,
        )

        if initial > date(year, 1, 1):
            cutoff = initial - timedelta(days=1)
            for scheduled in state.competitions.values():
                scheduled.advance_through(
                    cutoff.isoformat()
                )
        state._validate()
        return state

    def _validate(self) -> None:
        if self.current_date.year != self.year:
            raise ValueError(
                "current_date must be inside season year"
            )
        if self.start_date.year != self.year:
            raise ValueError(
                "start_date must be inside season year"
            )
        if self.current_date < self.start_date:
            raise ValueError(
                "current_date cannot precede start_date"
            )

    def today_matches(self) -> list[dict]:
        target = self.current_date.isoformat()
        rows = [
            {
                **row,
                "competition_id": cid,
            }
            for cid, scheduled
            in self.competitions.items()
            for row in scheduled.matches_for_date(target)
            if row["status"] in {
                SCHEDULE_PENDING,
                SCHEDULE_COMPLETED,
            }
        ]
        return sorted(
            rows,
            key=lambda row: (
                row["competition_name"],
                row["stage_code"],
                row["round_no"],
                row["match_id"],
            ),
        )

    def matches_for_date(
        self,
        target: str | date,
    ) -> list[dict]:
        normalized = (
            target.isoformat()
            if isinstance(target, date)
            else _iso_date(target, "target_date")
        )
        rows = [
            {
                **row,
                "competition_id": cid,
            }
            for cid, scheduled
            in self.competitions.items()
            for row in scheduled.matches_for_date(
                normalized
            )
        ]
        return sorted(
            rows,
            key=lambda row: (
                row["competition_name"],
                row["stage_code"],
                row["round_no"],
                row["match_id"],
            ),
        )

    def play_today(self) -> list[dict]:
        target = self.current_date.isoformat()
        completed_before = set(
            self.completed_results()
        )
        for scheduled in self.competitions.values():
            scheduled.play_date(target)
        completed = self.completed_results()
        new_keys = sorted(
            set(completed) - completed_before
        )
        results = [
            completed[key]
            for key in new_keys
        ]
        self.history.append({
            "action": "play_today",
            "date": target,
            "match_keys": new_keys,
            "match_count": len(results),
        })
        self._validate()
        return results

    def next_day(self) -> dict:
        if self.current_date >= date(
            self.year,
            12,
            31,
        ):
            raise ValueError(
                "season runtime cannot advance beyond season year"
            )
        results = self.play_today()
        previous = self.current_date
        self.current_date = (
            previous + timedelta(days=1)
        )
        self.history.append({
            "action": "next_day",
            "from_date": previous.isoformat(),
            "to_date": self.current_date.isoformat(),
            "played_match_count": len(results),
        })
        self._validate()
        return {
            "from_date": previous.isoformat(),
            "to_date": self.current_date.isoformat(),
            "played_match_count": len(results),
        }

    def advance_to(
        self,
        target: str | date,
    ) -> dict:
        target_date = (
            target
            if isinstance(target, date)
            else date.fromisoformat(
                _iso_date(target, "target_date")
            )
        )
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
            played += int(
                result["played_match_count"]
            )
        return {
            "current_date": (
                self.current_date.isoformat()
            ),
            "advanced_days": days,
            "played_match_count": played,
        }

    def advance_through(
        self,
        target: str | date,
    ) -> dict:
        result = self.advance_to(target)
        played_today = len(self.play_today())
        result["played_match_count"] += (
            played_today
        )
        result["processed_through"] = (
            self.current_date.isoformat()
        )
        return result

    def completed_results(self) -> dict[str, dict]:
        return {
            f"{cid}:{match_id}": row
            for cid, scheduled
            in sorted(self.competitions.items())
            for match_id, row
            in scheduled.completed_results().items()
        }

    def completed_ability_results(
        self,
    ) -> dict[str, dict]:
        return {
            f"{cid}:{match_id}": dict(
                match.ability_detail
            )
            for cid, scheduled
            in sorted(self.competitions.items())
            for match_id, match
            in sorted(scheduled.matches.items())
            if (
                match.status == SCHEDULE_COMPLETED
                and match.ability_detail is not None
            )
        }

    def calendar_gaps(self) -> list[dict]:
        return [
            {
                **row,
                "competition_id": cid,
            }
            for cid, scheduled
            in sorted(self.competitions.items())
            for row in scheduled.calendar_gap_matches()
        ]

    def competition_state(
        self,
        competition_id: str,
    ) -> dict:
        if competition_id not in self.competitions:
            raise KeyError(
                f"unknown competition_id: {competition_id}"
            )
        scheduled = self.competitions[
            competition_id
        ]
        state = scheduled.summary()
        state["champion_school_id"] = ""
        state["runner_up_school_id"] = ""
        if scheduled.is_complete:
            run = scheduled.to_competition_run()
            if run.outcome is not None:
                state["champion_school_id"] = (
                    run.outcome.champion_school_id
                )
                state["runner_up_school_id"] = (
                    run.outcome.runner_up_school_id
                )
        return state

    def school_records(self) -> list[dict]:
        state: dict[str, dict] = {}

        def ensure(
            school_id: str,
            school_name: str,
        ) -> dict:
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

        for scheduled in self.competitions.values():
            for match in scheduled.matches.values():
                if (
                    match.status
                    != SCHEDULE_COMPLETED
                ):
                    continue
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
                if (
                    match.winner_id
                    == match.team1_id
                ):
                    team1["wins"] += 1
                    team2["losses"] += 1
                elif (
                    match.winner_id
                    == match.team2_id
                ):
                    team2["wins"] += 1
                    team1["losses"] += 1
                else:
                    raise ValueError(
                        f"{match.match_id}: winner "
                        "not a participant"
                    )
                if (
                    match.team1_score is not None
                    and match.team2_score
                    is not None
                ):
                    team1["runs_for"] += (
                        match.team1_score
                    )
                    team1["runs_against"] += (
                        match.team2_score
                    )
                    team2["runs_for"] += (
                        match.team2_score
                    )
                    team2["runs_against"] += (
                        match.team1_score
                    )

        for row in state.values():
            row["run_differential"] = (
                row["runs_for"]
                - row["runs_against"]
            )
        return sorted(
            state.values(),
            key=lambda row: (
                -row["wins"],
                row["school_name"],
                row["school_id"],
            ),
        )

    def summary(self) -> dict:
        states = [
            scheduled.summary()
            for scheduled
            in self.competitions.values()
        ]
        return {
            "year": self.year,
            "rng_seed": self.rng_seed,
            "current_date": (
                self.current_date.isoformat()
            ),
            "start_date": (
                self.start_date.isoformat()
            ),
            "end_date": self.end_date.isoformat(),
            "competition_count": len(states),
            "completed_competition_count": sum(
                row["is_complete"]
                for row in states
            ),
            "activated_match_count": sum(
                row["activated_match_count"]
                for row in states
            ),
            "completed_match_count": sum(
                row["completed_match_count"]
                for row in states
            ),
            "pending_match_count": sum(
                row["pending_match_count"]
                for row in states
            ),
            "calendar_gap_count": sum(
                row["calendar_gap_count"]
                for row in states
            ),
            "today_match_count": len(
                self.today_matches()
            ),
            "completed_ability_match_count": len(
                self.completed_ability_results()
            ),
            "history_count": len(self.history),
        }

    def public_snapshot(self) -> dict:
        return {
            "summary": self.summary(),
            "competitions": {
                cid: scheduled.public_snapshot()
                for cid, scheduled
                in sorted(
                    self.competitions.items()
                )
            },
        }
