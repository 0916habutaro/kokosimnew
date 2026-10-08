from __future__ import annotations

from copy import deepcopy
import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Mapping, Sequence

from .competition_schedule_runtime import (
    ScheduledCompetitionRuntime,
    _iso_date,
)
from .models import AnnualCompetitionInput
from .paths import resolve_data_file
from .randomness import shuffled
from .repository import DataRepository
from .stage_calendar import (
    stage_date_lists_by_competition,
    validate_competition_stage_calendar,
)


DEPENDENCY_WAITING = "waiting_dependencies"
DEPENDENCY_WAITING_EXTERNAL = "waiting_external_dependency"
DEPENDENCY_ACTIVE = "active"
DEPENDENCY_COMPLETED = "completed"
DEPENDENCY_BLOCKED = "blocked"
DEPENDENCY_BLOCKED_DATE = "blocked_date_dependency"


@dataclass(frozen=True)
class LiveAccessDependencyResolution:
    access_rule_id: str
    destination_competition_id: str
    source_competition_id: str
    source_result_selector: str
    action_type: str
    resolved_school_ids: tuple[str, ...]
    expected_count: int
    status: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "access_rule_id": self.access_rule_id,
            "destination_competition_id": (
                self.destination_competition_id
            ),
            "source_competition_id": (
                self.source_competition_id
            ),
            "source_result_selector": (
                self.source_result_selector
            ),
            "action_type": self.action_type,
            "resolved_school_ids": list(
                self.resolved_school_ids
            ),
            "expected_count": self.expected_count,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class LiveQualificationDependencyResolution:
    rule_id: str
    source_competition_id: str
    destination_competition_id: str
    source_result: str
    resolved_school_ids: tuple[str, ...]
    expected_count: int
    status: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "source_competition_id": self.source_competition_id,
            "destination_competition_id": self.destination_competition_id,
            "source_result": self.source_result,
            "resolved_school_ids": list(self.resolved_school_ids),
            "expected_count": self.expected_count,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class LiveRegionalFeederDependencyResolution:
    feeder_rule_id: str
    destination_competition_id: str
    source_competition_id: str
    source_prefecture_code: str
    selector: str
    qualification_mode: str
    resolved_school_ids: tuple[str, ...]
    expected_count: int
    status: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "feeder_rule_id": self.feeder_rule_id,
            "destination_competition_id": self.destination_competition_id,
            "source_competition_id": self.source_competition_id,
            "source_prefecture_code": self.source_prefecture_code,
            "selector": self.selector,
            "qualification_mode": self.qualification_mode,
            "resolved_school_ids": list(self.resolved_school_ids),
            "expected_count": self.expected_count,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class LiveRegionalPlayoffDependencyResolution:
    playoff_id: str
    destination_competition_id: str
    candidate_school_id_a: str
    candidate_school_id_b: str
    winner_school_id: str
    status: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "playoff_id": self.playoff_id,
            "destination_competition_id": self.destination_competition_id,
            "candidate_school_id_a": self.candidate_school_id_a,
            "candidate_school_id_b": self.candidate_school_id_b,
            "winner_school_id": self.winner_school_id,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass
class LiveSeasonDependencyRuntimeState:
    """Activate same-year destination competitions from completed source results.

    Stage 13E-3D-1 intentionally covers machine-resolvable
    competition_access_rules whose source competition is in the same live graph.
    It does not precompute the destination AnnualCompetitionInput result-dependent
    fields. The source competition must finish first; only then are direct-entry or
    seed-bypass school ids injected and the destination runtime constructed.
    """

    engine: object = field(repr=False)
    repo: DataRepository = field(repr=False)
    year: int = 2026
    rng_seed: int = 0
    current_date: date = date(2026, 1, 1)
    start_date: date = date(2026, 1, 1)
    end_date: date = date(2026, 12, 31)
    annual_templates: dict[str, AnnualCompetitionInput] = field(
        default_factory=dict,
        repr=False,
    )
    calendar_rows: dict[str, dict] = field(
        default_factory=dict,
        repr=False,
    )
    stage_date_lists: dict[
        str,
        dict[str, list[str]],
    ] = field(default_factory=dict, repr=False)
    dependency_rules: dict[str, list[dict]] = field(
        default_factory=dict,
        repr=False,
    )
    qualification_rules: dict[str, list[dict]] = field(
        default_factory=dict,
        repr=False,
    )
    regional_feeder_rules: dict[str, list[dict]] = field(
        default_factory=dict,
        repr=False,
    )
    regional_playoffs: dict[str, list[dict]] = field(
        default_factory=dict,
        repr=False,
    )
    competitions: dict[
        str,
        ScheduledCompetitionRuntime,
    ] = field(default_factory=dict)
    status_by_competition: dict[str, str] = field(
        default_factory=dict
    )
    activated_on: dict[str, str] = field(
        default_factory=dict
    )
    resolutions: list[
        LiveAccessDependencyResolution
    ] = field(default_factory=list)
    qualification_resolutions: list[
        LiveQualificationDependencyResolution
    ] = field(default_factory=list)
    regional_feeder_resolutions: list[
        LiveRegionalFeederDependencyResolution
    ] = field(default_factory=list)
    regional_playoff_resolutions: list[
        LiveRegionalPlayoffDependencyResolution
    ] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)

    @staticmethod
    def _read_csv(
        data_dir,
        name: str,
    ) -> list[dict]:
        path = resolve_data_file(
            data_dir,
            name,
        )
        if not path.exists():
            return []
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            return list(csv.DictReader(f))

    @classmethod
    def from_annual_templates(
        cls,
        *,
        engine,
        repo: DataRepository,
        annual_templates: Sequence[AnnualCompetitionInput],
        calendar_rows: Sequence[Mapping[str, str]],
        rng_seed: int,
        start_date: str | date | None = None,
        stage_calendar_rows: (
            Sequence[Mapping[str, str]] | None
        ) = None,
        stage_date_lists_by_competition_override: (
            Mapping[
                str,
                Mapping[str, Sequence[str]],
            ]
            | None
        ) = None,
    ) -> "LiveSeasonDependencyRuntimeState":
        if not annual_templates:
            raise ValueError(
                "annual_templates is required"
            )
        years = {
            annual.year
            for annual in annual_templates
        }
        if len(years) != 1:
            raise ValueError(
                "all annual templates must use one year"
            )
        year = next(iter(years))
        templates = {}
        for annual in annual_templates:
            if annual.competition_id in templates:
                raise ValueError(
                    "duplicate annual template: "
                    f"{annual.competition_id}"
                )
            templates[annual.competition_id] = (
                deepcopy(annual)
            )

        calendar_by_comp = {
            row.get("competition_id", ""): dict(row)
            for row in calendar_rows
            if row.get("competition_id")
        }
        missing_calendar = sorted(
            set(templates) - set(calendar_by_comp)
        )
        if missing_calendar:
            raise ValueError(
                "missing calendar rows: "
                f"{missing_calendar}"
            )

        stage_dates: dict[
            str,
            dict[str, list[str]],
        ] = {}
        if stage_calendar_rows is not None:
            validate_competition_stage_calendar(
                repo,
                stage_calendar_rows,
                year=year,
            )
            stage_dates = (
                stage_date_lists_by_competition(
                    stage_calendar_rows,
                    include_pending=True,
                )
            )

        for cid, mapping in dict(
            stage_date_lists_by_competition_override
            or {}
        ).items():
            stage_dates.setdefault(cid, {})
            for stage_code, values in mapping.items():
                normalized = [
                    _iso_date(
                        value,
                        f"{cid}/{stage_code}",
                    )
                    for value in values
                ]
                if normalized != sorted(normalized):
                    raise ValueError(
                        f"{cid}/{stage_code}: "
                        "stage dates must be sorted"
                    )
                if len(normalized) != len(
                    set(normalized)
                ):
                    raise ValueError(
                        f"{cid}/{stage_code}: "
                        "duplicate stage dates"
                    )
                stage_dates[cid][
                    stage_code
                ] = normalized

        initial = (
            start_date
            if isinstance(start_date, date)
            else (
                date.fromisoformat(
                    _iso_date(
                        start_date,
                        "start_date",
                    )
                )
                if start_date is not None
                else date(year, 1, 1)
            )
        )
        if initial.year != year:
            raise ValueError(
                "start_date must be inside season year"
            )

        rules: dict[str, list[dict]] = {}
        for destination in templates:
            selected = []
            for rule in repo.access_rules(destination):
                if not cls._rule_effective(
                    rule,
                    year,
                ):
                    continue
                if int(
                    rule.get("source_year_offset")
                    or 0
                ) != 0:
                    continue
                source = rule.get(
                    "source_competition_id_2026",
                    "",
                )
                if not source:
                    continue
                selected.append(dict(rule))
            selected.sort(
                key=lambda row: (
                    -int(row.get("priority") or 0),
                    row["access_rule_id"],
                )
            )
            rules[destination] = selected

        all_dates = []
        for cid, row in calendar_by_comp.items():
            if cid not in templates:
                continue
            all_dates.extend(
                value.strip()
                for value in (
                    row.get("game_date_list")
                    or ""
                ).split(";")
                if value.strip()
            )
        for mapping in stage_dates.values():
            for values in mapping.values():
                all_dates.extend(values)
        end = max(
            [date(year, 12, 31)]
            + [
                date.fromisoformat(value)
                for value in all_dates
            ]
        )

        state = cls(
            engine=engine,
            repo=repo,
            year=year,
            rng_seed=rng_seed,
            current_date=initial,
            start_date=initial,
            end_date=end,
            annual_templates=templates,
            calendar_rows=calendar_by_comp,
            stage_date_lists=stage_dates,
            dependency_rules=rules,
        )
        state._initialize_statuses()
        state._activate_roots()
        state._activate_ready_destinations(
            activation_date=(
                initial - timedelta(days=1)
            ).isoformat()
        )
        return state

    @staticmethod
    def _rule_effective(
        rule: Mapping[str, str],
        year: int,
    ) -> bool:
        start = int(
            rule.get("effective_from_year")
            or year
        )
        end_value = rule.get(
            "effective_to_year",
            "",
        )
        end = int(end_value) if end_value else year
        return start <= year <= end

    def _initialize_statuses(self) -> None:
        for cid in self.annual_templates:
            rules = self.dependency_rules.get(
                cid,
                [],
            )
            if not rules:
                self.status_by_competition[
                    cid
                ] = DEPENDENCY_ACTIVE
                continue
            missing_sources = {
                rule[
                    "source_competition_id_2026"
                ]
                for rule in rules
                if rule[
                    "source_competition_id_2026"
                ]
                not in self.annual_templates
            }
            self.status_by_competition[cid] = (
                DEPENDENCY_WAITING_EXTERNAL
                if missing_sources
                else DEPENDENCY_WAITING
            )

    def _activate_roots(self) -> None:
        roots = [
            cid
            for cid, status
            in self.status_by_competition.items()
            if status == DEPENDENCY_ACTIVE
        ]
        for cid in sorted(roots):
            self._activate_competition(
                cid,
                deepcopy(
                    self.annual_templates[cid]
                ),
                activation_date="",
            )

    def _activate_competition(
        self,
        competition_id: str,
        annual: AnnualCompetitionInput,
        *,
        activation_date: str,
    ) -> bool:
        scheduled = (
            self.engine
            .prepare_scheduled_competition_runtime(
                annual,
                self.calendar_rows[
                    competition_id
                ],
                stage_date_lists=(
                    self.stage_date_lists.get(
                        competition_id
                    )
                ),
            )
        )
        next_date = scheduled.next_scheduled_date()
        if (
            activation_date
            and next_date
            and next_date <= activation_date
        ):
            self.status_by_competition[
                competition_id
            ] = DEPENDENCY_BLOCKED_DATE
            self.history.append({
                "action": "block_activation",
                "competition_id": competition_id,
                "activation_date": activation_date,
                "first_scheduled_date": next_date,
                "reason": "source completes too late",
            })
            return False

        self.competitions[
            competition_id
        ] = scheduled
        self.status_by_competition[
            competition_id
        ] = (
            DEPENDENCY_COMPLETED
            if scheduled.is_complete
            else DEPENDENCY_ACTIVE
        )
        self.activated_on[
            competition_id
        ] = activation_date
        self.history.append({
            "action": "activate_competition",
            "competition_id": competition_id,
            "activation_date": activation_date,
            "direct_main_entry_school_ids": list(
                annual.direct_main_entry_school_ids
            ),
            "seed_event_bypass_school_ids": list(
                annual.seed_event_bypass_school_ids
            ),
        })
        return True

    def _competition_completion_date(
        self,
        competition_id: str,
    ) -> str:
        scheduled = self.competitions[
            competition_id
        ]
        # Dependency results must not be released earlier than the official
        # competition calendar's last game date. A generic wave scheduler can
        # finish an internal bracket earlier when the calendar has multiple
        # dates within one round, but the real champion is not available to a
        # downstream tournament until the source event's final date.
        if scheduled.calendar_dates:
            return max(scheduled.calendar_dates)
        values = [
            match.completed_on
            for match in scheduled.matches.values()
            if match.completed_on
        ]
        return max(values) if values else ""

    def _resolve_rule(
        self,
        rule: Mapping[str, str],
    ) -> LiveAccessDependencyResolution:
        source_id = rule[
            "source_competition_id_2026"
        ]
        scheduled = self.competitions.get(
            source_id
        )
        if (
            scheduled is None
            or not scheduled.is_complete
        ):
            return LiveAccessDependencyResolution(
                access_rule_id=rule[
                    "access_rule_id"
                ],
                destination_competition_id=rule[
                    "destination_competition_id"
                ],
                source_competition_id=source_id,
                source_result_selector=rule.get(
                    "source_result_selector",
                    "",
                ),
                action_type=rule.get(
                    "action_type",
                    "",
                ),
                resolved_school_ids=(),
                expected_count=int(
                    rule.get("observed_2026_count")
                    or rule.get("quota")
                    or 0
                ),
                status="WAITING",
                notes="source competition not complete",
            )

        run = scheduled.to_competition_run()
        selector = rule.get(
            "source_result_selector",
            "",
        )
        ids: list[str]
        if selector == "winner":
            ids = (
                [run.outcome.champion_school_id]
                if run.outcome
                and run.outcome.champion_school_id
                else []
            )
        elif selector in {
            "participant_from_destination_prefecture",
            "participants_from_destination_prefecture",
        }:
            pcode = rule.get(
                "destination_prefecture_code",
                "",
            )
            ids = [
                school_id
                for school_id
                in run.entrant_school_ids
                if self.repo.schools.get(
                    school_id,
                    {},
                ).get("prefecture_code")
                == pcode
            ]
        else:
            return LiveAccessDependencyResolution(
                access_rule_id=rule[
                    "access_rule_id"
                ],
                destination_competition_id=rule[
                    "destination_competition_id"
                ],
                source_competition_id=source_id,
                source_result_selector=selector,
                action_type=rule.get(
                    "action_type",
                    "",
                ),
                resolved_school_ids=(),
                expected_count=int(
                    rule.get("observed_2026_count")
                    or rule.get("quota")
                    or 0
                ),
                status="UNSUPPORTED",
                notes=(
                    "Stage 13E-3D-1 supports winner "
                    "and destination-prefecture "
                    "participant selectors"
                ),
            )

        ids = list(dict.fromkeys(ids))
        expected = int(
            rule.get("observed_2026_count")
            or rule.get("quota")
            or 0
        )
        status = (
            "PASS"
            if not expected or len(ids) == expected
            else "FAIL"
        )
        return LiveAccessDependencyResolution(
            access_rule_id=rule[
                "access_rule_id"
            ],
            destination_competition_id=rule[
                "destination_competition_id"
            ],
            source_competition_id=source_id,
            source_result_selector=selector,
            action_type=rule.get(
                "action_type",
                "",
            ),
            resolved_school_ids=tuple(ids),
            expected_count=expected,
            status=status,
            notes="",
        )

    def _build_destination_annual(
        self,
        competition_id: str,
    ) -> tuple[
        AnnualCompetitionInput | None,
        list[LiveAccessDependencyResolution],
    ]:
        rules = self.dependency_rules.get(
            competition_id,
            [],
        )
        resolutions = [
            self._resolve_rule(rule)
            for rule in rules
        ]
        if any(
            row.status != "PASS"
            for row in resolutions
        ):
            return None, resolutions

        annual = deepcopy(
            self.annual_templates[
                competition_id
            ]
        )
        entrants = list(
            dict.fromkeys(
                annual.entrant_school_ids
            )
        )
        direct = list(
            dict.fromkeys(
                annual.direct_main_entry_school_ids
            )
        )
        bypass = list(
            dict.fromkeys(
                annual.seed_event_bypass_school_ids
            )
        )

        rule_by_id = {
            rule["access_rule_id"]: rule
            for rule in rules
        }
        for resolution in resolutions:
            rule = rule_by_id[
                resolution.access_rule_id
            ]
            ids = list(
                resolution.resolved_school_ids
            )
            for school_id in ids:
                if school_id not in entrants:
                    entrants.append(school_id)
            if rule.get("grants_main_entry") == "yes":
                direct.extend(ids)
            elif (
                rule.get("action_type")
                == "bypass_branch_seed_event_assign_seed"
            ):
                bypass.extend(ids)
            else:
                return None, [
                    LiveAccessDependencyResolution(
                        access_rule_id=(
                            resolution.access_rule_id
                        ),
                        destination_competition_id=(
                            competition_id
                        ),
                        source_competition_id=(
                            resolution.source_competition_id
                        ),
                        source_result_selector=(
                            resolution.source_result_selector
                        ),
                        action_type=rule.get(
                            "action_type",
                            "",
                        ),
                        resolved_school_ids=(
                            resolution.resolved_school_ids
                        ),
                        expected_count=(
                            resolution.expected_count
                        ),
                        status="UNSUPPORTED",
                        notes=(
                            "unsupported live access action"
                        ),
                    )
                ]

        annual.entrant_school_ids = list(
            dict.fromkeys(entrants)
        )
        annual.direct_main_entry_school_ids = list(
            dict.fromkeys(direct)
        )
        annual.seed_event_bypass_school_ids = list(
            dict.fromkeys(bypass)
        )
        return annual, resolutions

    def _activate_ready_destinations(
        self,
        *,
        activation_date: str,
    ) -> None:
        progress = True
        while progress:
            progress = False
            for cid in sorted(
                self.annual_templates
            ):
                if (
                    self.status_by_competition.get(
                        cid
                    )
                    != DEPENDENCY_WAITING
                ):
                    continue
                rules = self.dependency_rules.get(
                    cid,
                    [],
                )
                source_ids = {
                    rule[
                        "source_competition_id_2026"
                    ]
                    for rule in rules
                }
                if not all(
                    source in self.competitions
                    and self.competitions[
                        source
                    ].is_complete
                    and (
                        not self._competition_completion_date(
                            source
                        )
                        or activation_date
                        >= self._competition_completion_date(
                            source
                        )
                    )
                    for source in source_ids
                ):
                    continue

                annual, resolutions = (
                    self._build_destination_annual(
                        cid
                    )
                )
                self.resolutions.extend(
                    resolutions
                )
                if annual is None:
                    self.status_by_competition[
                        cid
                    ] = DEPENDENCY_BLOCKED
                    progress = True
                    continue

                source_completion_dates = [
                    self._competition_completion_date(
                        source
                    )
                    for source in source_ids
                ]
                source_completion_dates = [
                    value
                    for value in source_completion_dates
                    if value
                ]
                effective_activation = max(
                    [activation_date]
                    + source_completion_dates
                )
                activated = (
                    self._activate_competition(
                        cid,
                        annual,
                        activation_date=(
                            effective_activation
                        ),
                    )
                )
                progress = progress or activated

    def today_matches(self) -> list[dict]:
        target = self.current_date.isoformat()
        rows = [
            {
                **row,
                "competition_id": cid,
            }
            for cid, scheduled
            in self.competitions.items()
            for row in scheduled.matches_for_date(
                target
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
        before = set(self.completed_results())
        for cid, scheduled in sorted(
            self.competitions.items()
        ):
            if scheduled.is_complete:
                self.status_by_competition[
                    cid
                ] = DEPENDENCY_COMPLETED
                continue
            scheduled.play_date(target)
            if scheduled.is_complete:
                self.status_by_competition[
                    cid
                ] = DEPENDENCY_COMPLETED

        self._activate_ready_destinations(
            activation_date=target
        )
        completed = self.completed_results()
        new_keys = sorted(
            set(completed) - before
        )
        self.history.append({
            "action": "play_today",
            "date": target,
            "match_keys": new_keys,
            "match_count": len(new_keys),
        })
        return [
            completed[key]
            for key in new_keys
        ]

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
                _iso_date(
                    target,
                    "target_date",
                )
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
            "current_date": self.current_date.isoformat(),
            "advanced_days": days,
            "played_match_count": played,
        }

    def advance_through(
        self,
        target: str | date,
    ) -> dict:
        result = self.advance_to(target)
        result["played_match_count"] += len(
            self.play_today()
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

    def completed_runs(self) -> dict[str, object]:
        return {
            cid: scheduled.to_competition_run()
            for cid, scheduled
            in sorted(self.competitions.items())
            if scheduled.is_complete
        }

    def dependency_state(
        self,
        competition_id: str,
    ) -> dict:
        if competition_id not in self.annual_templates:
            raise KeyError(
                f"unknown competition_id: {competition_id}"
            )
        rules = self.dependency_rules.get(
            competition_id,
            [],
        )
        sources = [
            rule["source_competition_id_2026"]
            for rule in rules
        ]
        scheduled = self.competitions.get(
            competition_id
        )
        return {
            "competition_id": competition_id,
            "status": self.status_by_competition[
                competition_id
            ],
            "dependency_source_competition_ids": (
                list(dict.fromkeys(sources))
            ),
            "activated_on": self.activated_on.get(
                competition_id,
                "",
            ),
            "is_active": scheduled is not None,
            "is_complete": (
                bool(scheduled and scheduled.is_complete)
            ),
            "calendar_gap_count": (
                scheduled.summary()[
                    "calendar_gap_count"
                ]
                if scheduled is not None
                else 0
            ),
        }

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for status in self.status_by_competition.values():
            counts[status] = (
                counts.get(status, 0) + 1
            )
        return {
            "year": self.year,
            "rng_seed": self.rng_seed,
            "current_date": self.current_date.isoformat(),
            "template_competition_count": len(
                self.annual_templates
            ),
            "active_runtime_count": len(
                self.competitions
            ),
            "completed_runtime_count": sum(
                scheduled.is_complete
                for scheduled
                in self.competitions.values()
            ),
            "status_counts": dict(
                sorted(counts.items())
            ),
            "resolution_count": len(
                self.resolutions
            ),
        }

    def public_snapshot(self) -> dict:
        return {
            "summary": self.summary(),
            "dependencies": {
                cid: self.dependency_state(cid)
                for cid in sorted(
                    self.annual_templates
                )
            },
            "active_competitions": {
                cid: scheduled.public_snapshot()
                for cid, scheduled
                in sorted(self.competitions.items())
            },
            "resolutions": [
                row.to_dict()
                for row in self.resolutions
            ],
        }
