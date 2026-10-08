from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Mapping, Sequence

from .models import CompetitionRun, MatchResolution
from .repository import DataRepository


SCHEDULE_PENDING = "pending"
SCHEDULE_COMPLETED = "completed"


def _iso_date(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be YYYY-MM-DD")
    normalized = value.strip()
    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError as exc:
        raise ValueError(
            f"{label}: invalid ISO date {value}"
        ) from exc


def _date_list(values: Iterable[str], label: str) -> list[str]:
    normalized = [
        _iso_date(value, label)
        for value in values
        if str(value).strip()
    ]
    if normalized != sorted(normalized):
        raise ValueError(f"{label} must be sorted")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} contains duplicate date")
    return normalized


def _calendar_dates(calendar_row: Mapping[str, str]) -> list[str]:
    return _date_list(
        (calendar_row.get("game_date_list") or "").split(";"),
        "game_date_list",
    )


@dataclass
class ScheduledRuntimeMatch:
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
    status: str = SCHEDULE_PENDING
    completed_on: str = ""
    winner_id: str = ""
    loser_id: str = ""
    team1_score: int | None = None
    team2_score: int | None = None
    score_source: str = ""
    ability_detail: dict | None = None

    def public_dict(self) -> dict:
        row = asdict(self)
        row.pop("ability_detail", None)
        return row


@dataclass
class ScheduledCompetitionRuntime:
    """Date scheduler for an incremental competition runtime.

    Only the currently ready wave receives a date. Dependent rounds/phases remain
    absent until the previous wave is resolved. This preserves Stage 13E's
    no-future-result contract and also avoids exposing future participants.

    The ordinary season_calendar row can be used as one competition-wide date
    pool. When exact pre-MAIN dates are known, stage_date_lists can override the
    pool per stage_code. If no date remains, the scheduler stops and exposes a
    calendar gap instead of inventing a date.
    """

    repo: DataRepository
    runtime: object
    competition_id: str
    competition_name: str
    calendar_dates: List[str]
    stage_date_lists: Dict[str, List[str]]
    calendar_status: str
    matches: Dict[str, ScheduledRuntimeMatch] = field(default_factory=dict)
    processed_dates: List[str] = field(default_factory=list)
    last_scheduled_date: str = ""
    calendar_gap_match_ids: List[str] = field(default_factory=list)

    @classmethod
    def from_calendar_row(
        cls,
        repo: DataRepository,
        runtime: object,
        calendar_row: Mapping[str, str],
        *,
        stage_date_lists: Mapping[str, Sequence[str]] | None = None,
    ) -> "ScheduledCompetitionRuntime":
        competition_id = getattr(
            runtime,
            "competition_id",
            "",
        )
        if not competition_id:
            annual = getattr(runtime, "annual", None)
            competition_id = getattr(
                annual,
                "competition_id",
                "",
            )
        if not competition_id:
            raise ValueError(
                "competition runtime must expose competition_id "
                "or annual.competition_id"
            )
        if calendar_row.get("competition_id") != competition_id:
            raise ValueError(
                "calendar competition_id does not match runtime"
            )

        overrides = {}
        for stage_code, values in dict(
            stage_date_lists or {}
        ).items():
            overrides[stage_code] = _date_list(
                values,
                f"{stage_code} stage dates",
            )

        state = cls(
            repo=repo,
            runtime=runtime,
            competition_id=competition_id,
            competition_name=repo.competition(
                competition_id
            ).get("competition_name", ""),
            calendar_dates=_calendar_dates(calendar_row),
            stage_date_lists=overrides,
            calendar_status=calendar_row.get(
                "calendar_status",
                "",
            ),
        )
        state.ensure_next_wave_scheduled()
        return state

    @property
    def is_complete(self) -> bool:
        return bool(getattr(self.runtime, "is_complete"))

    def _school_name(self, school_id: str) -> str:
        if not school_id:
            return ""
        return self.repo.schools.get(
            school_id,
            {},
        ).get("school_name", school_id)

    @staticmethod
    def _row_sort_key(row: Mapping[str, object]) -> tuple:
        return (
            str(row.get("stage_code") or ""),
            int(row.get("round_no") or 0),
            str(row.get("group_id") or ""),
            int(row.get("match_no_in_round") or 0),
            str(row.get("match_id") or ""),
        )

    def _pending_records(self) -> list[ScheduledRuntimeMatch]:
        return sorted(
            (
                match
                for match in self.matches.values()
                if match.status == SCHEDULE_PENDING
            ),
            key=lambda match: (
                match.match_date,
                match.stage_code,
                match.round_no,
                match.group_id,
                match.match_id,
            ),
        )

    def _available_dates_for_stage(
        self,
        stage_code: str,
    ) -> list[str]:
        pool = self.stage_date_lists.get(
            stage_code,
            self.calendar_dates,
        )
        floor = self.last_scheduled_date
        used = {
            match.match_date
            for match in self.matches.values()
            if match.match_date
        }
        return [
            value
            for value in pool
            if (not floor or value > floor)
            and value not in used
        ]

    def _record_from_ready_row(
        self,
        row: Mapping[str, object],
        match_date: str,
        date_source: str,
    ) -> ScheduledRuntimeMatch:
        match_id = str(row["match_id"])
        team1 = str(row.get("team1") or "")
        team2 = str(row.get("team2") or "")
        return ScheduledRuntimeMatch(
            competition_id=self.competition_id,
            competition_name=self.competition_name,
            match_id=match_id,
            match_date=match_date,
            date_source=date_source,
            stage_code=str(row.get("stage_code") or ""),
            phase_code=str(row.get("phase_code") or ""),
            round_no=int(row.get("round_no") or 0),
            round_name=str(
                row.get("round_name")
                or row.get("phase_code")
                or ""
            ),
            group_id=str(row.get("group_id") or ""),
            group_name=str(row.get("group_name") or ""),
            team1_id=team1,
            team1_name=self._school_name(team1),
            team2_id=team2,
            team2_name=self._school_name(team2),
        )

    def _frontier_ready_rows(
        self,
        ready: Sequence[Mapping[str, object]],
    ) -> list[Mapping[str, object]]:
        """Keep only the current round frontier for each independent runtime lane.

        MAIN brackets with structural byes can expose some round-2 matches as READY
        before every round-1 game is resolved. Legacy resolve_ready_round() always
        consumes the minimum round first. The same rule is required here so outcome
        cohort ordering and resolver call order remain identical.
        """
        minimum_round: dict[tuple[str, str, str], int] = {}
        for row in ready:
            key = (
                str(row.get("stage_code") or ""),
                str(row.get("phase_code") or ""),
                str(row.get("group_id") or ""),
            )
            round_no = int(row.get("round_no") or 0)
            if key not in minimum_round:
                minimum_round[key] = round_no
            else:
                minimum_round[key] = min(
                    minimum_round[key],
                    round_no,
                )
        return [
            row
            for row in ready
            if int(row.get("round_no") or 0)
            == minimum_round[(
                str(row.get("stage_code") or ""),
                str(row.get("phase_code") or ""),
                str(row.get("group_id") or ""),
            )]
        ]

    def ensure_next_wave_scheduled(
        self,
    ) -> list[ScheduledRuntimeMatch]:
        if self.is_complete:
            self.calendar_gap_match_ids = []
            return []
        pending = self._pending_records()
        if pending:
            return pending

        ready = sorted(
            self._frontier_ready_rows(
                self.runtime.ready_matches()
            ),
            key=self._row_sort_key,
        )
        if not ready:
            self.calendar_gap_match_ids = []
            return []

        stage_codes = []
        for row in ready:
            stage = str(row.get("stage_code") or "")
            if stage not in stage_codes:
                stage_codes.append(stage)

        assigned: list[ScheduledRuntimeMatch] = []
        unresolved_gap: list[str] = []
        for stage_code in stage_codes:
            stage_rows = [
                row
                for row in ready
                if str(row.get("stage_code") or "")
                == stage_code
            ]
            dates = self._available_dates_for_stage(
                stage_code
            )
            if not dates:
                unresolved_gap.extend(
                    str(row["match_id"])
                    for row in stage_rows
                )
                continue
            target = dates[0]
            source = (
                "stage_date_list"
                if stage_code in self.stage_date_lists
                else "runtime_wave_v1"
            )
            for row in stage_rows:
                match_id = str(row["match_id"])
                if match_id in self.matches:
                    raise ValueError(
                        f"duplicate scheduled runtime match: {match_id}"
                    )
                record = self._record_from_ready_row(
                    row,
                    target,
                    source,
                )
                self.matches[match_id] = record
                assigned.append(record)
            self.last_scheduled_date = target

        self.calendar_gap_match_ids = sorted(
            unresolved_gap
        )
        return assigned

    def matches_for_date(
        self,
        target: str,
    ) -> list[dict]:
        normalized = _iso_date(target, "target_date")
        self.ensure_next_wave_scheduled()
        return [
            match.public_dict()
            for match in sorted(
                self.matches.values(),
                key=lambda match: (
                    match.match_date,
                    match.stage_code,
                    match.round_no,
                    match.group_id,
                    match.match_id,
                ),
            )
            if match.match_date == normalized
        ]

    def next_scheduled_date(self) -> str:
        pending = self._pending_records()
        if pending:
            return pending[0].match_date
        self.ensure_next_wave_scheduled()
        pending = self._pending_records()
        return pending[0].match_date if pending else ""

    def _complete_record(
        self,
        record: ScheduledRuntimeMatch,
        resolution: MatchResolution,
    ) -> None:
        record.winner_id = resolution.winner_id
        record.loser_id = resolution.loser_id
        record.team1_score = resolution.team1_score
        record.team2_score = resolution.team2_score
        record.score_source = resolution.score_source
        record.ability_detail = (
            dict(resolution.detail)
            if resolution.detail
            else None
        )
        record.completed_on = record.match_date
        record.status = SCHEDULE_COMPLETED

    def play_date(
        self,
        target: str,
    ) -> list[MatchResolution]:
        normalized = _iso_date(target, "target_date")
        self.ensure_next_wave_scheduled()
        earlier = [
            match
            for match in self._pending_records()
            if match.match_date < normalized
        ]
        if earlier:
            raise ValueError(
                "cannot skip pending scheduled date "
                f"{earlier[0].match_date}"
            )

        target_records = [
            match
            for match in self._pending_records()
            if match.match_date == normalized
        ]
        if not target_records:
            return []

        results: list[MatchResolution] = []
        for record in target_records:
            resolution = self.runtime.resolve_match(
                record.match_id
            )
            self._complete_record(
                record,
                resolution,
            )
            results.append(resolution)

        if normalized not in self.processed_dates:
            self.processed_dates.append(normalized)
            self.processed_dates.sort()

        # Deliberately assign the dependent wave only after the current date has
        # finished. _available_dates_for_stage() requires a strictly later date,
        # so newly activated rounds can never leak back onto the same date.
        self.ensure_next_wave_scheduled()
        return results

    def advance_through(
        self,
        target: str,
    ) -> dict:
        normalized = _iso_date(target, "target_date")
        played = 0
        processed: list[str] = []
        while True:
            next_date = self.next_scheduled_date()
            if not next_date or next_date > normalized:
                break
            results = self.play_date(next_date)
            played += len(results)
            processed.append(next_date)

        return {
            "processed_dates": processed,
            "played_match_count": played,
            "is_complete": self.is_complete,
            "calendar_gap_count": len(
                self.calendar_gap_match_ids
            ),
        }

    def completed_results(self) -> dict[str, dict]:
        return {
            match_id: match.public_dict()
            for match_id, match in sorted(
                self.matches.items()
            )
            if match.status == SCHEDULE_COMPLETED
        }

    def calendar_gap_matches(self) -> list[dict]:
        if not self.calendar_gap_match_ids:
            self.ensure_next_wave_scheduled()
        if not self.calendar_gap_match_ids:
            return []

        ready_by_id = {
            str(row["match_id"]): row
            for row in self.runtime.ready_matches()
        }
        rows = []
        for match_id in self.calendar_gap_match_ids:
            row = dict(ready_by_id.get(match_id, {}))
            if not row:
                continue
            row["match_date"] = ""
            row["date_source"] = "calendar_gap"
            row["competition_name"] = self.competition_name
            row["team1_name"] = self._school_name(
                str(row.get("team1") or "")
            )
            row["team2_name"] = self._school_name(
                str(row.get("team2") or "")
            )
            rows.append(row)
        return sorted(rows, key=self._row_sort_key)

    def to_competition_run(self) -> CompetitionRun:
        if not self.is_complete:
            raise ValueError(
                "competition run unavailable before completion"
            )
        return self.runtime.to_competition_run()

    def summary(self) -> dict:
        self.ensure_next_wave_scheduled()
        pending = self._pending_records()
        completed = [
            match
            for match in self.matches.values()
            if match.status == SCHEDULE_COMPLETED
        ]
        return {
            "competition_id": self.competition_id,
            "competition_name": self.competition_name,
            "calendar_status": self.calendar_status,
            "is_complete": self.is_complete,
            "activated_match_count": len(self.matches),
            "completed_match_count": len(completed),
            "pending_match_count": len(pending),
            "next_scheduled_date": (
                pending[0].match_date
                if pending
                else ""
            ),
            "calendar_gap_count": len(
                self.calendar_gap_match_ids
            ),
            "processed_dates": list(
                self.processed_dates
            ),
        }

    def public_snapshot(self) -> dict:
        self.ensure_next_wave_scheduled()
        return {
            **self.summary(),
            "matches": [
                match.public_dict()
                for match in sorted(
                    self.matches.values(),
                    key=lambda match: (
                        match.match_date,
                        match.stage_code,
                        match.round_no,
                        match.group_id,
                        match.match_id,
                    ),
                )
            ],
            "calendar_gap_matches": (
                self.calendar_gap_matches()
            ),
        }
