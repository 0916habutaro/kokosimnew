from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date, timedelta
from typing import Dict, Iterable, List, Mapping, Sequence

from .models import CompetitionRun, MatchResolution
from .repository import DataRepository


# 日程の最終日の後にとれる予備日の数（試合が重なって日がずれたときだけ使う）
RESERVE_DAYS_AFTER_SCHEDULE = 7

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
    dates = _date_list(
        (calendar_row.get("game_date_list") or "").split(";"),
        "game_date_list",
    )
    if dates or not (
        calendar_row.get("start_date") and calendar_row.get("end_date")
    ):
        return dates
    # 試合ごとの日付を出典で確認できず開催期間だけが分かる大会（神宮大会）は、
    # 開催期間の各日を試合日の候補にする。データには日付を書き足さない。
    start = date.fromisoformat(calendar_row["start_date"])
    end = date.fromisoformat(calendar_row["end_date"])
    return [
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    ]


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
    # 履歴（historical_match_archive）に保存済みか
    archived: bool = False

    def public_dict(self) -> dict:
        # 試合の詳細（1球ごとの記録）は大きいので写さない。
        return {
            name: getattr(self, name)
            for name in _PUBLIC_MATCH_FIELDS
        }


_PUBLIC_MATCH_FIELDS = tuple(
    item.name
    for item in fields(ScheduledRuntimeMatch)
    if item.name not in ("ability_detail", "archived")
)


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
    # Preserve game-projected dates as such when feeding the ordinary scheduler.
    date_source_override: str = ""
    matches: Dict[str, ScheduledRuntimeMatch] = field(default_factory=dict)
    processed_dates: List[str] = field(default_factory=list)
    last_scheduled_date: str = ""
    calendar_gap_match_ids: List[str] = field(default_factory=list)
    ranking_sidecars: Dict[str, object] = field(default_factory=dict, repr=False)
    # 学校ごとの試合の日（全大会・全年度で共有）。同じ日に2試合しないため。
    school_days: Dict[str, set] = field(default_factory=dict, repr=False)
    # 試合を空いている日へ回したことがあるか（日程が足りなくなったときの扱い）
    spread_matches: bool = False
    # 学校 → この日まで試合を入れない（甲子園に出ている学校の秋季大会。
    # 全大会で共有し、季節の進行が甲子園の結果から毎日つくり直す）
    school_holds: Dict[str, str] = field(default_factory=dict, repr=False)
    respect_holds: bool = False

    @classmethod
    def from_calendar_row(
        cls,
        repo: DataRepository,
        runtime: object,
        calendar_row: Mapping[str, str],
        *,
        stage_date_lists: Mapping[str, Sequence[str]] | None = None,
        school_days: Dict[str, set] | None = None,
        school_holds: Dict[str, str] | None = None,
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
            date_source_override=(
                "game_projection_v1"
                if (
                    calendar_row.get("date_source") == "game_projection_v1"
                    and calendar_row.get("calendar_status")
                    == "provisional_game_schedule"
                )
                else ""
            ),
        )
        if school_days is not None:
            state.school_days = school_days
        if school_holds is not None:
            state.school_holds = school_holds
            competition = repo.competition(competition_id)
            state.respect_holds = competition.get("season_segment") == "autumn" and (
                competition.get("competition_level") != "national"
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

    def _used_dates(self) -> set[str]:
        return {
            match.match_date
            for match in self.matches.values()
            if match.match_date
        }

    def _stage_limit(self, stage_code: str, after: str) -> date | None:
        """その段階に使える最後の日（次の段階が始まる前の日）。"""
        later_pools = [
            value
            for code, pool in self.stage_date_lists.items()
            if code != stage_code
            for value in pool
            if value > after
        ]
        if stage_code in self.stage_date_lists:
            later_pools.extend(
                value for value in self.calendar_dates
                if value > after
            )
        if later_pools:
            return date.fromisoformat(min(later_pools)) - timedelta(days=1)
        if self.calendar_dates:
            # 最後の段階は、日程の最終日の後にも予備日をとれる（雨天順延のように、
            # 同じ学校の試合が重なって日がずれたときに最後まで行えるように）
            return date.fromisoformat(max(self.calendar_dates)) + timedelta(
                days=RESERVE_DAYS_AFTER_SCHEDULE
            )
        return None

    def _reserve_dates(self, stage_code: str, after: str) -> list[str]:
        """日程にない空き日（予備日）。``after`` の翌日から次の段階の前まで。"""
        limit = self._stage_limit(stage_code, after)
        if limit is None:
            return []
        day = date.fromisoformat(after) + timedelta(days=1)
        days = []
        while day <= limit:
            days.append(day.isoformat())
            day += timedelta(days=1)
        return days

    def _round_plan(self, stage_code: str) -> list[tuple[int, int]]:
        """本大会の残りの回戦と試合数。分からない段階（予選など）は空。"""
        if stage_code != "MAIN":
            return []
        runtime = self.runtime
        main = (
            runtime if hasattr(runtime, "remaining_rounds")
            else getattr(runtime, "main_runtime", None)
        )
        if main is None or not hasattr(main, "remaining_rounds"):
            return []
        return main.remaining_rounds()

    def _round_dates(
        self, stage_code: str, round_no: int, dates: list[str],
    ) -> list[str]:
        """この回戦に使う日。決勝を最後の日、準決勝をその前の日…と後ろから
        決め、早い回戦は残りの日に分ける（1日の試合数がならべく同じになるよう）。
        回戦の数より日が少なければ空（前から1日ずつ使う）。"""
        plan = self._round_plan(stage_code)
        if not plan or plan[0][0] != round_no or len(dates) < len(plan):
            return []
        days = [1] * len(plan)
        for _ in range(len(dates) - len(plan)):
            busiest = max(
                range(len(plan)), key=lambda i: (plan[i][1] / days[i], -i),
            )
            days[busiest] += 1
        return dates[: days[0]]

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
            if (
                not dates
                and self.spread_matches
                and self.last_scheduled_date
            ):
                # 試合を空いている日へ回したために日程が足りなくなった。
                # 次の段階（本大会など）が始まる前の空いている日を予備日に使う。
                dates = self._reserve_dates(
                    stage_code, self.last_scheduled_date,
                )[:1]
            if not dates:
                unresolved_gap.extend(
                    str(row["match_id"])
                    for row in stage_rows
                )
                continue
            source = (
                self.date_source_override
                or (
                    "stage_date_list"
                    if stage_code in self.stage_date_lists
                    else "runtime_wave_v1"
                )
            )
            # 本大会は、この回戦に使う日へ試合を順に分ける
            round_dates = self._round_dates(
                stage_code, int(stage_rows[0].get("round_no") or 0), dates,
            )
            # 同じ学校が同じ日に2試合しないよう、両校とも空いている最初の日に
            # 入れる（総当たりの組・ほかの大会）。空いた日がなければ最初の日。
            chosen = []
            used_dates = self._used_dates()
            for index, row in enumerate(stage_rows):
                match_id = str(row["match_id"])
                if match_id in self.matches:
                    raise ValueError(
                        f"duplicate scheduled runtime match: {match_id}"
                    )
                teams = [
                    team
                    for team in (
                        str(row.get("team1") or ""),
                        str(row.get("team2") or ""),
                    )
                    if team
                ]
                # 最初の日がふさがっていれば、次の日程の日より前の空き日
                # （予備日）、次に残りの日程の日。予備日をあとの日程まで
                # 使うと次の回戦の日程が足りなくなるので、そこまでにする。
                reserve = [
                    day
                    for day in self._reserve_dates(stage_code, dates[0])
                    if (len(dates) < 2 or day < dates[1])
                    and day not in used_dates
                ]
                candidates = dates[:1] + reserve + dates[1:]
                if round_dates:
                    planned = round_dates[
                        index * len(round_dates) // len(stage_rows)
                    ]
                    # ふさがっていれば、この回戦の日、次の回戦の日までの予備日、
                    # 最後にあとの回戦の日（あとの回戦の日はなるべく使わない）
                    window_end = next(
                        (day for day in dates if day > round_dates[-1]), "9999",
                    )
                    window = [
                        day
                        for day in self._reserve_dates(stage_code, round_dates[0])
                        if day < window_end
                        and day not in round_dates
                        and day not in used_dates
                    ]
                    candidates = (
                        [planned]
                        + [day for day in round_dates if day != planned]
                        + window
                        + [day for day in dates if day > window_end or day == window_end]
                    )
                hold = max(
                    (self.school_holds.get(team, "") for team in teams),
                    default="",
                ) if self.respect_holds else ""
                if hold:
                    # 甲子園に出ている学校は、敗退した日の翌日より後にする
                    later = [day for day in candidates if day > hold]
                    if not later:
                        later = [
                            day for day in self._reserve_dates(stage_code, hold)
                            if day not in used_dates
                        ] or [(date.fromisoformat(hold) + timedelta(days=1)).isoformat()]
                    candidates = later
                target = next(
                    (
                        day for day in candidates
                        if not any(
                            day in self.school_days.get(team, ())
                            for team in teams
                        )
                    ),
                    candidates[0],
                )
                if target not in (round_dates or dates[:1]):
                    self.spread_matches = True
                for team in teams:
                    self.school_days.setdefault(team, set()).add(target)
                record = self._record_from_ready_row(
                    row,
                    target,
                    source,
                )
                self.matches[match_id] = record
                assigned.append(record)
                chosen.append(target)
            self.last_scheduled_date = max(chosen)

        self.calendar_gap_match_ids = sorted(
            unresolved_gap
        )
        return assigned

    def attach_ranking_sidecar(self, sidecar) -> None:
        """Attach an explicitly scheduled post-qualification event.

        Qualification was locked by the caller before creating the event;
        the ranking fixture cannot change MAIN entrants or runtime completion.
        """
        if sidecar.event.competition_id != self.competition_id:
            raise ValueError("ranking sidecar belongs to another competition")
        key = sidecar.instance_key
        if key in self.ranking_sidecars:
            raise ValueError("ranking sidecar instance is already attached")
        new_ids = {row["match_id"] for row in sidecar.snapshot()["matches"]}
        existing_ids = {
            row["match_id"] for existing in self.ranking_sidecars.values()
            for row in existing.snapshot()["matches"]
        }
        if new_ids & existing_ids:
            raise ValueError("ranking match IDs collide across event instances")
        self.ranking_sidecars[key] = sidecar

    def ranking_matches_for_date(self, target: str) -> list[dict]:
        """Ranking matches remain observable even after MAIN has completed."""
        normalized = _iso_date(target, "target_date")
        return sorted(
            ({
                **row,
                "competition_name": self.competition_name,
                "round_name": "順位決定戦",
                "group_name": self.repo.groups.get(
                    row["group_id"], {}
                ).get("group_name", ""),
                "team1_name": self._school_name(row["team1_id"]),
                "team2_name": self._school_name(row["team2_id"]),
            }
             for sidecar in self.ranking_sidecars.values()
             for row in sidecar.matches_for_date(normalized)),
            key=lambda row: (row["match_date"], row["group_id"],
                             row["round_no"], row["match_id"]),
        )

    def resolve_ranking_date(
        self,
        target: str,
        *,
        winners_by_group: Mapping[str, Mapping[str, str]],
        scores_by_group: Mapping[str, Mapping[str, tuple[int, int]]] | None = None,
    ) -> list[dict]:
        """Explicitly resolve optional placement matches, never progression."""
        date_value = _iso_date(target, "target_date")
        scores = dict(scores_by_group or {})
        active = {
            instance_key: sidecar
            for instance_key, sidecar in self.ranking_sidecars.items()
            if any(row["status"] == "pending"
                   for row in sidecar.matches_for_date(date_value))
        }
        if set(winners_by_group) != set(active):
            raise ValueError("winners must cover every active ranking group")
        if not set(scores).issubset(active):
            raise ValueError("scores reference an inactive ranking group")
        result = []
        for instance_key, sidecar in sorted(active.items()):
            result.extend(sidecar.resolve_date(
                date_value, winners_by_group[instance_key],
                scores=scores.get(instance_key),
            ))
        return result

    def ranking_snapshot(self) -> dict:
        return {
            instance_key: sidecar.snapshot()
            for instance_key, sidecar in sorted(self.ranking_sidecars.items())
        }

    def restore_ranking_snapshot(self, snapshot: Mapping[str, dict]) -> None:
        from .post_qualification_schedule import ScheduledRankingSidecar
        restored = {}
        for instance_key, payload in sorted(snapshot.items()):
            sidecar = ScheduledRankingSidecar.from_snapshot(payload)
            if (sidecar.event.competition_id != self.competition_id
                    or sidecar.instance_key != instance_key):
                raise ValueError("ranking snapshot does not belong to competition")
            restored[instance_key] = sidecar
        self.ranking_sidecars = restored

    def matches_for_date(
        self,
        target: str,
    ) -> list[dict]:
        normalized = _iso_date(target, "target_date")
        self.ensure_next_wave_scheduled()
        main_rows = [
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
        return main_rows + self.ranking_matches_for_date(normalized)

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
            **({"ranking_sidecars": self.ranking_snapshot()}
               if self.ranking_sidecars else {}),
        }
