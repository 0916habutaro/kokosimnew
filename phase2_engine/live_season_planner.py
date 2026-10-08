from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .engine import TournamentEngine
from .live_season_dependency import (
    LiveSeasonDependencyRuntimeState,
)
from .models import AnnualCompetitionInput
from .paths import resolve_data_file
from .randomness import shuffled
from .repository import DataRepository
from .season import (
    SeasonOrchestrator,
    StructuralAnnualInputFactory,
)
from .stage_calendar import (
    load_competition_stage_calendar,
)


PLAN_ROOT = "root"
PLAN_ACCESS = "access"
PLAN_QUALIFICATION = "qualification"
PLAN_REGIONAL_FEEDER = "regional_feeder"
PLAN_OVERLAP = "overlap"

STRATEGY_SENBATSU_BOOTSTRAP = "senbatsu_bootstrap"
STRATEGY_SUMMER_AREA = "summer_area"
STRATEGY_STRUCTURAL = "structural"
STRATEGY_DEFERRED_STRUCTURAL = "deferred_structural"
STRATEGY_DEPENDENCY_AGGREGATE = "dependency_aggregate"


@dataclass(frozen=True)
class ExternalAccessBootstrapResolution:
    access_rule_id: str
    destination_competition_id: str
    source_event_kind: str
    source_year_offset: int
    resolved_school_ids: tuple[str, ...]
    expected_count: int
    action_type: str
    resolution_source: str
    status: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "access_rule_id": self.access_rule_id,
            "destination_competition_id": (
                self.destination_competition_id
            ),
            "source_event_kind": self.source_event_kind,
            "source_year_offset": self.source_year_offset,
            "resolved_school_ids": list(
                self.resolved_school_ids
            ),
            "expected_count": self.expected_count,
            "action_type": self.action_type,
            "resolution_source": self.resolution_source,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class LiveSeasonPlanEntry:
    competition_id: str
    competition_type: str
    season_segment: str
    strategy: str
    dependency_family: str
    dependency_source_competition_ids: tuple[str, ...]
    rng_seed: int
    calendar_start_date: str
    calendar_end_date: str
    has_pre_main: bool
    external_bootstrap_rule_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "competition_id": self.competition_id,
            "competition_type": self.competition_type,
            "season_segment": self.season_segment,
            "strategy": self.strategy,
            "dependency_family": self.dependency_family,
            "dependency_source_competition_ids": list(
                self.dependency_source_competition_ids
            ),
            "rng_seed": self.rng_seed,
            "calendar_start_date": self.calendar_start_date,
            "calendar_end_date": self.calendar_end_date,
            "has_pre_main": self.has_pre_main,
            "external_bootstrap_rule_ids": list(
                self.external_bootstrap_rule_ids
            ),
        }


@dataclass
class LiveSeasonGraphPlan:
    repo: DataRepository = field(repr=False)
    data_dir: Path = field(repr=False)
    year: int = 2026
    rng_seed: int = 0
    entries: dict[str, LiveSeasonPlanEntry] = field(
        default_factory=dict
    )
    annual_templates: dict[
        str,
        AnnualCompetitionInput,
    ] = field(default_factory=dict, repr=False)
    annual_build_strategies: dict[str, str] = field(
        default_factory=dict
    )
    calendar_rows: list[dict] = field(
        default_factory=list,
        repr=False,
    )
    stage_calendar_rows: list[dict] = field(
        default_factory=list,
        repr=False,
    )
    dependency_edges: list[tuple[str, str]] = field(
        default_factory=list
    )
    topological_order: list[str] = field(
        default_factory=list
    )
    external_bootstrap_resolutions: list[
        ExternalAccessBootstrapResolution
    ] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        strategy_counts: dict[str, int] = {}
        family_counts: dict[str, int] = {}
        segment_counts: dict[str, int] = {}
        for entry in self.entries.values():
            strategy_counts[entry.strategy] = (
                strategy_counts.get(
                    entry.strategy,
                    0,
                )
                + 1
            )
            family_counts[
                entry.dependency_family
            ] = (
                family_counts.get(
                    entry.dependency_family,
                    0,
                )
                + 1
            )
            segment_counts[entry.season_segment] = (
                segment_counts.get(
                    entry.season_segment,
                    0,
                )
                + 1
            )
        pending_stage_count = sum(
            row.get("date_status")
            == "research_pending"
            for row in self.stage_calendar_rows
        )
        verified_stage_count = sum(
            row.get("date_status")
            == "verified"
            for row in self.stage_calendar_rows
        )
        return {
            "year": self.year,
            "rng_seed": self.rng_seed,
            "competition_count": len(self.entries),
            "template_count": len(
                self.annual_templates
            ),
            "calendar_count": len(
                self.calendar_rows
            ),
            "dependency_edge_count": len(
                self.dependency_edges
            ),
            "topological_count": len(
                self.topological_order
            ),
            "strategy_counts": dict(
                sorted(strategy_counts.items())
            ),
            "dependency_family_counts": dict(
                sorted(family_counts.items())
            ),
            "season_segment_counts": dict(
                sorted(segment_counts.items())
            ),
            "external_bootstrap_count": len(
                self.external_bootstrap_resolutions
            ),
            "external_bootstrap_pass_count": sum(
                row.status == "PASS"
                for row
                in self.external_bootstrap_resolutions
            ),
            "external_bootstrap_unresolved_count": sum(
                row.status != "PASS"
                for row
                in self.external_bootstrap_resolutions
            ),
            "stage_calendar_pending_count": (
                pending_stage_count
            ),
            "stage_calendar_verified_count": (
                verified_stage_count
            ),
            "warning_count": len(self.warnings),
        }

    def public_snapshot(self) -> dict:
        return {
            "summary": self.summary(),
            "topological_order": list(
                self.topological_order
            ),
            "entries": {
                cid: entry.to_dict()
                for cid, entry
                in sorted(self.entries.items())
            },
            "external_bootstrap_resolutions": [
                row.to_dict()
                for row
                in self.external_bootstrap_resolutions
            ],
            "warnings": list(self.warnings),
        }

    def build_runtime(
        self,
        *,
        engine: TournamentEngine | None = None,
        start_date: str | None = None,
    ) -> LiveSeasonDependencyRuntimeState:
        structural_factory = (
            StructuralAnnualInputFactory(
                self.repo,
                self.data_dir,
                self.rng_seed,
            )
        )
        return (
            LiveSeasonDependencyRuntimeState
            .from_annual_templates(
                engine=(
                    engine
                    if engine is not None
                    else TournamentEngine(
                        self.repo
                    )
                ),
                repo=self.repo,
                annual_templates=[
                    self.annual_templates[cid]
                    for cid
                    in self.topological_order
                ],
                calendar_rows=self.calendar_rows,
                rng_seed=self.rng_seed,
                start_date=start_date,
                stage_calendar_rows=(
                    self.stage_calendar_rows
                ),
                annual_build_strategies=(
                    self.annual_build_strategies
                ),
                structural_factory=(
                    structural_factory
                ),
            )
        )


class LiveSeasonGraphPlanner:
    """Build the complete annual live dependency graph from repository masters.

    No future result-derived school ids are invented. Same-year access destinations
    use a deferred structural builder and are materialized only after their source
    results resolve. Prior-year/newcomer access rules retain the deterministic
    structural bootstrap already used by SeasonOrchestrator.
    """

    def __init__(
        self,
        repo: DataRepository,
        data_dir: str | Path,
        rng_seed: int,
        *,
        year: int = 2026,
    ):
        self.repo = repo
        self.data_dir = Path(data_dir)
        self.rng_seed = rng_seed
        self.year = year
        self.factory = StructuralAnnualInputFactory(
            repo,
            data_dir,
            rng_seed,
        )
        self.orchestrator = SeasonOrchestrator(
            repo,
            data_dir,
        )

    def _read(
        self,
        name: str,
    ) -> list[dict]:
        path = resolve_data_file(
            self.data_dir,
            name,
        )
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            return list(csv.DictReader(f))

    def _seed(
        self,
        competition_id: str,
    ) -> int:
        return SeasonOrchestrator._seed(
            self.rng_seed,
            competition_id,
        )

    def _competition_rows(self) -> list[dict]:
        rows = self._read("competitions.csv")
        selected = [
            row
            for row in rows
            if row.get("reference_year")
            == str(self.year)
        ]
        selected.sort(
            key=lambda row: row[
                "competition_id"
            ]
        )
        return selected

    def _calendar_rows(self) -> list[dict]:
        rows = self._read("season_calendar.csv")
        rows = [
            row
            for row in rows
            if row.get("competition_id")
            in self.repo.competitions
        ]
        rows.sort(
            key=lambda row: row[
                "competition_id"
            ]
        )
        return rows

    def _effective_access_rules(
        self,
    ) -> list[dict]:
        rows = self._read(
            "competition_access_rules.csv"
        )
        selected = []
        for row in rows:
            start = int(
                row.get("effective_from_year")
                or self.year
            )
            end_raw = row.get(
                "effective_to_year",
                "",
            )
            end = (
                int(end_raw)
                if end_raw
                else self.year
            )
            if start <= self.year <= end:
                selected.append(row)
        return selected

    def _qualification_rules(
        self,
    ) -> list[dict]:
        return [
            row
            for row in self._read(
                "qualification_rules.csv"
            )
            if row.get("effective_year")
            == str(self.year)
        ]

    def _regional_feeder_rules(
        self,
    ) -> list[dict]:
        return [
            row
            for row in self._read(
                "regional_feeder_rules.csv"
            )
            if row.get("effective_year")
            == str(self.year)
        ]

    def _external_access_bootstrap(
        self,
        access_rules: list[dict],
    ) -> tuple[
        dict[str, list[str]],
        dict[str, list[str]],
        list[ExternalAccessBootstrapResolution],
        list[str],
    ]:
        prior_pref, prior_reg = (
            self.orchestrator
            ._bootstrap_prior_context(
                self.year,
                self.rng_seed,
            )
        )
        direct: dict[str, list[str]] = {}
        bypass: dict[str, list[str]] = {}
        resolutions = []
        warnings = []

        for rule in access_rules:
            offset = int(
                rule.get("source_year_offset")
                or 0
            )
            source_id = rule.get(
                "source_competition_id_2026",
                "",
            )
            if offset == 0 and source_id:
                continue

            destination = rule[
                "destination_competition_id"
            ]
            kind = rule.get(
                "source_event_kind",
                "",
            )
            pcode = rule.get(
                "destination_prefecture_code",
                "",
            )
            ids: list[str] = []
            resolution_source = ""
            notes = ""

            if (
                offset == -1
                and kind
                == "autumn_prefectural"
            ):
                ranking = prior_pref.get(
                    pcode,
                    [],
                )
                lo = int(
                    rule.get("source_rank_from")
                    or 1
                )
                hi = int(
                    rule.get("source_rank_to")
                    or lo
                )
                ids = ranking[lo - 1:hi]
                resolution_source = (
                    "prior_year_structural_bootstrap"
                )
            elif (
                offset == -1
                and kind == "autumn_regional"
            ):
                ids = list(
                    prior_reg.get(pcode, [])
                )
                resolution_source = (
                    "prior_year_structural_bootstrap"
                )
            elif (
                offset == 0
                and not source_id
                and kind
                == "prefectural_newcomer_tournament"
            ):
                expected = int(
                    rule.get(
                        "observed_2026_count"
                    )
                    or rule.get("quota")
                    or 0
                )
                candidates = sorted(
                    school_id
                    for school_id, school
                    in self.repo.schools.items()
                    if school.get(
                        "prefecture_code"
                    )
                    == pcode
                )
                ids = shuffled(
                    candidates,
                    self.rng_seed,
                    (
                        f"{destination}:"
                        f"{rule['access_rule_id']}:"
                        "newcomer_bootstrap"
                    ),
                )[:expected]
                resolution_source = (
                    "current_year_structural_event_bootstrap"
                )
                notes = (
                    "newcomer event competition is "
                    "not materialized"
                )
            else:
                notes = (
                    "unsupported external access source: "
                    f"{kind}/offset={offset}/"
                    f"source={source_id}"
                )

            expected = int(
                rule.get("observed_2026_count")
                or rule.get("quota")
                or 0
            )
            if expected and len(ids) > expected:
                ids = ids[:expected]
            status = (
                "PASS"
                if (
                    resolution_source
                    and (
                        not expected
                        or len(ids) == expected
                    )
                )
                else "UNRESOLVED"
            )
            resolution = (
                ExternalAccessBootstrapResolution(
                    access_rule_id=rule[
                        "access_rule_id"
                    ],
                    destination_competition_id=(
                        destination
                    ),
                    source_event_kind=kind,
                    source_year_offset=offset,
                    resolved_school_ids=tuple(
                        ids
                    ),
                    expected_count=expected,
                    action_type=rule.get(
                        "action_type",
                        "",
                    ),
                    resolution_source=(
                        resolution_source
                    ),
                    status=status,
                    notes=notes,
                )
            )
            resolutions.append(resolution)
            if status != "PASS":
                warnings.append(
                    f"{rule['access_rule_id']}: "
                    f"{notes}"
                )
                continue

            if (
                rule.get("grants_main_entry")
                == "yes"
            ):
                direct.setdefault(
                    destination,
                    [],
                ).extend(ids)
            elif (
                rule.get("action_type")
                == "bypass_branch_seed_event_assign_seed"
            ):
                bypass.setdefault(
                    destination,
                    [],
                ).extend(ids)
            else:
                warnings.append(
                    f"{rule['access_rule_id']}: "
                    "resolved external access has "
                    "unsupported action"
                )

        for mapping in (direct, bypass):
            for cid in list(mapping):
                mapping[cid] = list(
                    dict.fromkeys(mapping[cid])
                )
        return (
            direct,
            bypass,
            resolutions,
            warnings,
        )

    @staticmethod
    def _topological_order(
        competition_ids: list[str],
        edges: list[tuple[str, str]],
        calendar_by_comp: Mapping[
            str,
            Mapping[str, str],
        ],
    ) -> list[str]:
        nodes = set(competition_ids)
        outgoing = {
            node: set()
            for node in nodes
        }
        indegree = {
            node: 0
            for node in nodes
        }
        for source, destination in edges:
            if (
                source not in nodes
                or destination not in nodes
            ):
                continue
            if destination in outgoing[source]:
                continue
            outgoing[source].add(destination)
            indegree[destination] += 1

        def sort_key(cid: str) -> tuple:
            row = calendar_by_comp.get(
                cid,
                {},
            )
            return (
                row.get("start_date")
                or "9999-12-31",
                cid,
            )

        ready = sorted(
            [
                node
                for node, count
                in indegree.items()
                if count == 0
            ],
            key=sort_key,
        )
        ordered: list[str] = []
        while ready:
            node = ready.pop(0)
            ordered.append(node)
            for destination in sorted(
                outgoing[node],
                key=sort_key,
            ):
                indegree[destination] -= 1
                if indegree[destination] == 0:
                    ready.append(destination)
                    ready.sort(key=sort_key)

        if len(ordered) != len(nodes):
            cyclic = sorted(
                node
                for node, count
                in indegree.items()
                if count > 0
            )
            raise ValueError(
                "live dependency graph contains "
                f"cycle(s): {cyclic}"
            )
        return ordered

    def build_plan(self) -> LiveSeasonGraphPlan:
        competitions = self._competition_rows()
        competition_ids = [
            row["competition_id"]
            for row in competitions
        ]
        competition_by_id = {
            row["competition_id"]: row
            for row in competitions
        }
        calendar_rows = self._calendar_rows()
        calendar_by_comp = {
            row["competition_id"]: row
            for row in calendar_rows
        }
        missing_calendar = sorted(
            set(competition_ids)
            - set(calendar_by_comp)
        )
        if missing_calendar:
            raise ValueError(
                "full-season planner missing calendars: "
                f"{missing_calendar}"
            )

        access_rules = (
            self._effective_access_rules()
        )
        same_year_access = [
            rule
            for rule in access_rules
            if (
                int(
                    rule.get("source_year_offset")
                    or 0
                )
                == 0
                and rule.get(
                    "source_competition_id_2026"
                )
            )
        ]
        qualification_rules = (
            self._qualification_rules()
        )
        feeder_rules = (
            self._regional_feeder_rules()
        )

        access_by_dest: dict[
            str,
            list[dict],
        ] = {}
        qualification_by_dest: dict[
            str,
            list[dict],
        ] = {}
        feeder_by_dest: dict[
            str,
            list[dict],
        ] = {}
        for rule in same_year_access:
            access_by_dest.setdefault(
                rule[
                    "destination_competition_id"
                ],
                [],
            ).append(rule)
        for rule in qualification_rules:
            qualification_by_dest.setdefault(
                rule[
                    "destination_competition_id"
                ],
                [],
            ).append(rule)
        for rule in feeder_rules:
            feeder_by_dest.setdefault(
                rule[
                    "destination_competition_id"
                ],
                [],
            ).append(rule)

        edges = []
        for rule in same_year_access:
            edges.append((
                rule[
                    "source_competition_id_2026"
                ],
                rule[
                    "destination_competition_id"
                ],
            ))
        for rule in qualification_rules:
            edges.append((
                rule["source_competition_id"],
                rule[
                    "destination_competition_id"
                ],
            ))
        for rule in feeder_rules:
            source = rule.get(
                "source_competition_id",
                "",
            )
            if source:
                edges.append((
                    source,
                    rule[
                        "destination_competition_id"
                    ],
                ))
        edges = sorted(set(edges))

        (
            external_direct,
            external_bypass,
            external_resolutions,
            external_warnings,
        ) = self._external_access_bootstrap(
            access_rules
        )

        pref_index = self._read(
            "prefectural_competition_index_2026.csv"
        )
        structural_ids = {
            row["competition_id"]
            for row in pref_index
        }

        senbatsu_ids = (
            self.orchestrator
            ._bootstrap_senbatsu_participants(
                self.year,
                self.rng_seed,
            )
        )

        templates: dict[
            str,
            AnnualCompetitionInput,
        ] = {}
        strategies: dict[str, str] = {}
        entries: dict[
            str,
            LiveSeasonPlanEntry,
        ] = {}
        warnings = list(external_warnings)

        for cid in competition_ids:
            competition = competition_by_id[cid]
            ctype = competition.get(
                "competition_type",
                "",
            )
            access = access_by_dest.get(
                cid,
                [],
            )
            qualification = (
                qualification_by_dest.get(
                    cid,
                    [],
                )
            )
            feeders = feeder_by_dest.get(
                cid,
                [],
            )
            family_count = sum([
                bool(access),
                bool(qualification),
                bool(feeders),
            ])
            if family_count > 1:
                family = PLAN_OVERLAP
            elif access:
                family = PLAN_ACCESS
            elif qualification:
                family = PLAN_QUALIFICATION
            elif feeders:
                family = PLAN_REGIONAL_FEEDER
            else:
                family = PLAN_ROOT

            direct = external_direct.get(
                cid,
                [],
            )
            bypass = external_bypass.get(
                cid,
                [],
            )
            seed = self._seed(cid)

            if ctype == "national_invitational":
                strategy = (
                    STRATEGY_SENBATSU_BOOTSTRAP
                )
                annual = AnnualCompetitionInput(
                    competition_id=cid,
                    year=self.year,
                    entrant_school_ids=list(
                        senbatsu_ids
                    ),
                    rng_seed=seed,
                )
            elif (
                ctype
                == "summer_local_qualifier"
            ):
                strategy = STRATEGY_SUMMER_AREA
                annual = AnnualCompetitionInput(
                    competition_id=cid,
                    year=self.year,
                    entrant_school_ids=(
                        self.factory
                        .summer_area_school_ids(
                            cid,
                            self.year,
                        )
                    ),
                    rng_seed=seed,
                )
            elif qualification or feeders:
                strategy = (
                    STRATEGY_DEPENDENCY_AGGREGATE
                )
                annual = AnnualCompetitionInput(
                    competition_id=cid,
                    year=self.year,
                    entrant_school_ids=[],
                    rng_seed=seed,
                )
            elif cid in structural_ids:
                if access:
                    strategy = (
                        STRATEGY_DEFERRED_STRUCTURAL
                    )
                    annual = AnnualCompetitionInput(
                        competition_id=cid,
                        year=self.year,
                        entrant_school_ids=[],
                        direct_main_entry_school_ids=list(
                            direct
                        ),
                        seed_event_bypass_school_ids=list(
                            bypass
                        ),
                        rng_seed=seed,
                    )
                else:
                    strategy = STRATEGY_STRUCTURAL
                    annual = (
                        self.factory
                        .build_prefectural(
                            cid,
                            self.year,
                            direct_main_entry_school_ids=(
                                direct
                            ),
                            seed_event_bypass_school_ids=(
                                bypass
                            ),
                            rng_seed=seed,
                        )
                    )
            else:
                raise ValueError(
                    f"{cid}: no annual template "
                    f"strategy for {ctype}"
                )

            templates[cid] = annual
            strategies[cid] = strategy
            source_ids = list(
                dict.fromkeys(
                    [
                        rule[
                            "source_competition_id_2026"
                        ]
                        for rule in access
                    ]
                    + [
                        rule[
                            "source_competition_id"
                        ]
                        for rule in qualification
                    ]
                    + [
                        rule.get(
                            "source_competition_id",
                            "",
                        )
                        for rule in feeders
                        if rule.get(
                            "source_competition_id"
                        )
                    ]
                )
            )
            calendar = calendar_by_comp[cid]
            external_rule_ids = tuple(
                row.access_rule_id
                for row in external_resolutions
                if row.destination_competition_id
                == cid
            )
            entries[cid] = LiveSeasonPlanEntry(
                competition_id=cid,
                competition_type=ctype,
                season_segment=competition.get(
                    "season_segment",
                    "",
                ),
                strategy=strategy,
                dependency_family=family,
                dependency_source_competition_ids=tuple(
                    source_ids
                ),
                rng_seed=seed,
                calendar_start_date=calendar.get(
                    "start_date",
                    "",
                ),
                calendar_end_date=calendar.get(
                    "end_date",
                    "",
                ),
                has_pre_main=any(
                    stage["stage_code"]
                    != "MAIN"
                    for stage in self.repo.stages(
                        cid
                    )
                ),
                external_bootstrap_rule_ids=(
                    external_rule_ids
                ),
            )

        order = self._topological_order(
            competition_ids,
            edges,
            calendar_by_comp,
        )
        stage_calendar_rows = (
            load_competition_stage_calendar(
                self.data_dir,
                year=self.year,
            )
        )

        return LiveSeasonGraphPlan(
            repo=self.repo,
            data_dir=self.data_dir,
            year=self.year,
            rng_seed=self.rng_seed,
            entries=entries,
            annual_templates=templates,
            annual_build_strategies=strategies,
            calendar_rows=calendar_rows,
            stage_calendar_rows=(
                stage_calendar_rows
            ),
            dependency_edges=edges,
            topological_order=order,
            external_bootstrap_resolutions=(
                external_resolutions
            ),
            warnings=warnings,
        )
