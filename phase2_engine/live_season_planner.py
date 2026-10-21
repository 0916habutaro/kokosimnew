from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .engine import TournamentEngine
from .initial_state import PriorResults, load_prior_results
from .live_season_dependency import (
    LiveSeasonDependencyRuntimeState,
)
from .models import AnnualCompetitionInput
from .paths import resolve_data_file
from .randomness import shuffled
from .repository import DataRepository
from .school_year import (
    INVITATIONAL_TYPE,
)
from .senbatsu_selection import selection_region_ids
from .season_catalog import (
    TEMPLATE_YEAR,
    SeasonCompetition,
    is_previous_school_year_source,
    rules_year,
    season_competitions,
    shift_calendar_row,
    shift_stage_calendar_row,
)
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
PLAN_SELECTION = "selection"

STRATEGY_SENBATSU_SELECTION = "senbatsu_selection"
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
    display_name: str = ""
    year_offset: int = 0
    calendar_shift_days: int = 0

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
            "display_name": self.display_name,
            "year_offset": self.year_offset,
            "calendar_shift_days": self.calendar_shift_days,
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
    # 前の年度の3月の選抜の出場校。この年度の春季大会の推薦・予選免除に使う。
    prior_invitational_entrant_ids: tuple[str, ...] = ()
    # 前の年度のゲーム内の結果（2年目から）。セーブに書き、読込時に同じ
    # 計画をつくり直すのに使う。最初の年度（実際の結果）は None。
    prior_results: PriorResults | None = field(
        default=None,
        repr=False,
    )
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
        open_before_school_year: bool = False,
        school_days: dict | None = None,
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
                open_before_school_year=(
                    open_before_school_year
                ),
                school_days=school_days,
                stage_calendar_rows=(
                    self.stage_calendar_rows
                ),
                annual_build_strategies=(
                    self.annual_build_strategies
                ),
                structural_factory=(
                    structural_factory
                ),
                prior_invitational_entrant_ids=(
                    self.prior_invitational_entrant_ids
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
        prior_results: PriorResults | None = None,
    ):
        self.repo = repo
        self.data_dir = Path(data_dir)
        self.rng_seed = rng_seed
        self.year = year
        self.prior_results = prior_results
        self.rules_year = rules_year(year)
        self._season: dict[str, SeasonCompetition] | None = None
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
        # 組み合わせは年度ごとに抽選し直す。
        namespace = (
            competition_id
            if self.year == TEMPLATE_YEAR
            else f"{self.year}:{competition_id}"
        )
        return SeasonOrchestrator._seed(
            self.rng_seed,
            namespace,
        )

    def season_catalog(
        self,
    ) -> dict[str, SeasonCompetition]:
        if self._season is None:
            self._season = season_competitions(
                self._read("competitions.csv"),
                {
                    row["competition_id"]: row
                    for row in self._read(
                        "season_calendar.csv"
                    )
                },
                self.year,
            )
        return self._season

    def _competition_rows(self) -> list[dict]:
        rows = self._read("competitions.csv")
        season = self.season_catalog()
        selected = [
            row
            for row in rows
            if row["competition_id"] in season
            and row.get("reference_year")
            == str(TEMPLATE_YEAR)
        ]
        selected.sort(
            key=lambda row: row[
                "competition_id"
            ]
        )
        return selected

    def _calendar_rows(self) -> list[dict]:
        season = self.season_catalog()
        rows = [
            shift_calendar_row(
                row,
                season[row["competition_id"]].shift_days,
            )
            for row in self._read(
                "season_calendar.csv"
            )
            if row.get("competition_id") in season
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
            year = self.rules_year
            start = int(
                row.get("effective_from_year")
                or year
            )
            end_raw = row.get(
                "effective_to_year",
                "",
            )
            end = (
                int(end_raw)
                if end_raw
                else year
            )
            if start <= year <= end:
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
            == str(self.rules_year)
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
            == str(self.rules_year)
        ]

    def _external_access_bootstrap(
        self,
        access_rules: list[dict],
        competition_ids: set[str],
        prior: PriorResults | None,
        senbatsu_ids: list[str],
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
            if prior is None
            else ({}, {})
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
            if (
                offset == 0
                and source_id in competition_ids
                and not self._previous_year_source(
                    source_id,
                    rule[
                        "destination_competition_id"
                    ],
                )
            ):
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

            if prior is not None and (
                offset == -1
                or kind == INVITATIONAL_TYPE
            ):
                ids, resolution_source, notes = (
                    self._prior_results_ids(
                        prior,
                        rule,
                    )
                )
            elif (
                offset == 0
                and kind == INVITATIONAL_TYPE
            ):
                ids = [
                    school_id
                    for school_id in senbatsu_ids
                    if self.repo.schools[school_id].get(
                        "prefecture_code"
                    )
                    == pcode
                ]
                resolution_source = (
                    "prior_year_structural_bootstrap"
                )
            elif (
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
            if rule.get("quota_mode") == "all_matches":
                # 対象校すべてに適用する。人数は前の年度の結果で変わる。
                expected = len(ids)
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

    def _selection_sources(
        self,
        competition_ids: set[str],
    ) -> dict[str, list[str]]:
        """選抜 → 選考に使う秋季地区大会。"""
        rules: dict[str, list[dict]] = {}
        for row in self._read("selection_rules.csv"):
            destination = row["destination_competition_id"]
            if destination in competition_ids:
                rules.setdefault(destination, []).append(row)
        regionals = {
            row.get("region_id"): cid
            for cid, row in self.repo.competitions.items()
            if row.get("competition_type") == "autumn_regional"
            and cid in competition_ids
        }
        jingu = [
            cid
            for cid, row in self.repo.competitions.items()
            if row.get("competition_type")
            == "national_autumn_championship"
            and cid in competition_ids
        ]
        # 神宮枠はその年の神宮大会の優勝校の地区に付ける
        return {
            destination: [
                regionals[region]
                for region in selection_region_ids(rows)
                if region in regionals
            ]
            + jingu
            for destination, rows in rules.items()
        }

    @staticmethod
    def _previous_season_ids(
        prior: PriorResults,
        rule: Mapping[str, str],
    ) -> list[str] | None:
        """前の年度のゲーム内の秋の結果から、ルールの対象校を選ぶ。"""
        if not prior.from_game:
            return None
        kind = rule.get("source_event_kind")
        pcode = rule.get("destination_prefecture_code", "")
        if kind == "autumn_prefectural":
            ranking = prior.autumn_prefectural_rankings.get(pcode)
            if ranking is None:
                return None
            lo = int(rule.get("source_rank_from") or 1)
            hi = int(rule.get("source_rank_to") or lo)
            return list(ranking[lo - 1:hi])
        if kind == "autumn_regional":
            return list(prior.autumn_regional_entrants.get(pcode, ()))
        return None

    def _prior_invitational_entrants(
        self,
        prior: PriorResults | None,
    ) -> list[str]:
        if prior is not None:
            return [
                school_id
                for school_id, _
                in prior.senbatsu_entrants
            ]
        return list(
            self.orchestrator
            ._bootstrap_senbatsu_participants(
                rules_year(self.year - 1),
                SeasonOrchestrator._seed(
                    self.rng_seed,
                    f"{self.year - 1}:senbatsu",
                ),
            )
        )

    def _previous_year_source(
        self,
        source_id: str,
        destination_id: str,
    ) -> bool:
        return is_previous_school_year_source(
            self.repo.competitions,
            source_id,
            destination_id,
        )

    @staticmethod
    def _prior_results_ids(
        prior: PriorResults,
        rule: Mapping[str, str],
    ) -> tuple[list[str], str, str]:
        if (
            rule.get("source_event_kind")
            == INVITATIONAL_TYPE
        ):
            return (
                prior.senbatsu_entrants_from(
                    rule.get(
                        "destination_prefecture_code",
                        "",
                    )
                ),
                (
                    "previous_season_result"
                    if prior.from_game
                    else "initial_state_actual"
                ),
                "",
            )
        ids = prior.school_ids_by_rule.get(
            rule["access_rule_id"]
        )
        if ids is None:
            ids = LiveSeasonGraphPlanner._previous_season_ids(
                prior,
                rule,
            )
            if ids is not None:
                return ids, "previous_season_result", ""
        if ids is None:
            return (
                [],
                "",
                (
                    "initial_state prior_results has "
                    "no rows for this rule"
                ),
            )
        return list(ids), "initial_state_actual", ""

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
        calendar_rows = [
            row
            for row in self._calendar_rows()
            if row["competition_id"]
            in competition_by_id
        ]
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
        # 前の年度の結果（前年秋・3月の選抜）。最初の年度は実際の結果を使い、
        # データがない年度はルールの範囲内でランダムに決める。
        prior = self.prior_results or load_prior_results(
            self.data_dir,
            self.year,
        )
        prior_invitational = (
            self._prior_invitational_entrants(prior)
        )
        # 同じ年度の大会どうしのつながり。前の年度の大会（3月の選抜など）
        # からのルールは、外部の結果として _external_access_bootstrap で解決する。
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
                in competition_by_id
                and not self._previous_year_source(
                    rule[
                        "source_competition_id_2026"
                    ],
                    rule[
                        "destination_competition_id"
                    ],
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
            # 前の年度の大会（3月の選抜）の結果は計画の段階で解決済み。
            if (
                source in competition_by_id
                and not self._previous_year_source(
                    source,
                    rule[
                        "destination_competition_id"
                    ],
                )
            ):
                edges.append((
                    source,
                    rule[
                        "destination_competition_id"
                    ],
                ))
        # 選抜は秋季地区大会の結果から選ぶ
        selection_sources = self._selection_sources(
            set(competition_by_id)
        )
        for destination, sources in selection_sources.items():
            edges.extend(
                (source, destination) for source in sources
            )
        edges = sorted(set(edges))

        (
            external_direct,
            external_bypass,
            external_resolutions,
            external_warnings,
        ) = self._external_access_bootstrap(
            access_rules,
            set(competition_by_id),
            prior,
            prior_invitational,
        )

        pref_index = self._read(
            "prefectural_competition_index_2026.csv"
        )
        structural_ids = {
            row["competition_id"]
            for row in pref_index
        }

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
            selection = selection_sources.get(cid, [])
            family_count = sum([
                bool(access),
                bool(qualification),
                bool(feeders),
                bool(selection),
            ])
            if family_count > 1:
                family = PLAN_OVERLAP
            elif access:
                family = PLAN_ACCESS
            elif qualification:
                family = PLAN_QUALIFICATION
            elif feeders:
                family = PLAN_REGIONAL_FEEDER
            elif selection:
                family = PLAN_SELECTION
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

            if ctype == INVITATIONAL_TYPE:
                strategy = (
                    STRATEGY_SENBATSU_SELECTION
                )
                # 出場校は秋季地区大会が終わってから選ぶ
                annual = AnnualCompetitionInput(
                    competition_id=cid,
                    year=self.year,
                    entrant_school_ids=[],
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
                        in competition_by_id
                        and not self._previous_year_source(
                            rule[
                                "source_competition_id"
                            ],
                            cid,
                        )
                    ]
                    + list(selection)
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
                display_name=(
                    self.season_catalog()[cid]
                    .display_name
                ),
                year_offset=(
                    self.season_catalog()[cid]
                    .year_offset
                ),
                calendar_shift_days=(
                    self.season_catalog()[cid]
                    .shift_days
                ),
            )

        order = self._topological_order(
            competition_ids,
            edges,
            calendar_by_comp,
        )
        season = self.season_catalog()
        stage_calendar_rows = [
            shift_stage_calendar_row(
                row,
                season[row["competition_id"]].shift_days,
            )
            if row["competition_id"] in season
            else row
            for row in load_competition_stage_calendar(
                self.data_dir,
                year=self.rules_year,
            )
        ]

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
            prior_invitational_entrant_ids=tuple(
                prior_invitational
            ),
            prior_results=self.prior_results,
            warnings=warnings,
        )
