from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from .models import Match, MatchResolution
from .premain_runtime_common import RuntimePreMainMatch, resolve_runtime_match
from .premain_runtime_round_robin import RoundRobinRuntimeState
from .randomness import shuffled
from .tournament_runtime import MATCH_BYE, MATCH_COMPLETED, MATCH_READY


@dataclass
class Fmt006QualifierGroupRuntime:
    group: dict
    eligible_school_ids: List[str]
    output_slots: int
    pools: List[List[str]]
    pool_runtimes: List[RoundRobinRuntimeState]
    generation_seed: int
    competition_id: str
    reference_year: int
    stage_id: str
    stage_code: str
    match_resolver: object | None = field(default=None, repr=False)
    match_simulation_results: Dict[str, dict] = field(default_factory=dict)
    cross_matches: Dict[str, RuntimePreMainMatch] = field(default_factory=dict)
    cross_order: List[str] = field(default_factory=list)
    cross_activated: bool = False
    direct_school_ids: List[str] = field(default_factory=list)
    runnerup_3_school_ids: List[str] = field(default_factory=list)
    standings_by_pool: Dict[str, dict] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        group: dict,
        eligible_school_ids: Sequence[str],
        output_slots: int,
        competition_id: str,
        reference_year: int,
        stage_id: str,
        stage_code: str,
        generation_seed: int,
        supplied_pools: Sequence[Sequence[str]] | None = None,
        match_resolver=None,
        resolved_match_sink: Dict[str, dict] | None = None,
    ) -> "Fmt006QualifierGroupRuntime":
        gid = group["stage_group_id"]
        eligible = list(eligible_school_ids)
        if supplied_pools:
            pools = [list(pool) for pool in supplied_pools]
            flat = [team for pool in pools for team in pool]
            if len(flat) != len(set(flat)) or set(flat) != set(eligible):
                raise ValueError(
                    f"{gid}: supplied pools must contain each eligible team exactly once"
                )
            if any(len(pool) not in {3, 4} for pool in pools):
                raise ValueError(f"{gid}: FMT006 pools must have 3 or 4 teams")
        else:
            four_count, three_count = cls._solve_3_or_4_pool_plan(
                len(eligible), output_slots
            )
            sizes = [4] * four_count + [3] * three_count
            sizes = shuffled(
                sizes,
                generation_seed,
                f"{competition_id}:{stage_id}:{gid}:pool_sizes",
            )
            drawn = shuffled(
                eligible,
                generation_seed,
                f"{competition_id}:{stage_id}:{gid}:pool_draw",
            )
            pools = []
            pos = 0
            for size in sizes:
                pools.append(drawn[pos:pos + size])
                pos += size

        sink = resolved_match_sink if resolved_match_sink is not None else {}
        pool_runtimes = [
            RoundRobinRuntimeState.create(
                pool,
                competition_id=competition_id,
                reference_year=reference_year,
                stage_id=stage_id,
                stage_code=stage_code,
                phase_code="POOL_RR",
                group_id=gid,
                group_name=group["group_name"],
                pool_no=pool_no,
                generation_seed=generation_seed,
                match_resolver=match_resolver,
                resolved_match_sink=sink,
            )
            for pool_no, pool in enumerate(pools, start=1)
        ]
        return cls(
            group=dict(group),
            eligible_school_ids=eligible,
            output_slots=output_slots,
            pools=pools,
            pool_runtimes=pool_runtimes,
            generation_seed=generation_seed,
            competition_id=competition_id,
            reference_year=reference_year,
            stage_id=stage_id,
            stage_code=stage_code,
            match_resolver=match_resolver,
            match_simulation_results=sink,
        )

    @staticmethod
    def _solve_3_or_4_pool_plan(
        entrant_count: int,
        output_slots: int,
    ) -> tuple[int, int]:
        candidates = []
        for three in range(0, entrant_count // 3 + 1):
            rem = entrant_count - 3 * three
            if rem < 0 or rem % 4:
                continue
            four = rem // 4
            outputs = 2 * four + three + (three + 1) // 2
            if outputs == output_slots:
                candidates.append((four, three))
        if not candidates:
            raise ValueError(
                f"cannot partition entrants={entrant_count} into 3/4-team pools "
                f"for output_slots={output_slots}"
            )
        return sorted(candidates, key=lambda item: (item[1], -item[0]))[0]

    @property
    def format_model_id(self) -> str:
        return "FMT006"

    @property
    def pool_phase_complete(self) -> bool:
        return all(runtime.is_complete for runtime in self.pool_runtimes)

    @property
    def is_complete(self) -> bool:
        if not self.pool_phase_complete:
            return False
        self._activate_cross_playoff()
        return all(
            match.status in {MATCH_COMPLETED, MATCH_BYE}
            for match in self.cross_matches.values()
        )

    def contains_match(self, match_id: str) -> bool:
        return (
            any(match_id in runtime.matches for runtime in self.pool_runtimes)
            or match_id in self.cross_matches
        )

    def ready_matches(self) -> list[dict]:
        if not self.pool_phase_complete:
            return [
                row
                for runtime in self.pool_runtimes
                for row in runtime.ready_matches()
            ]
        self._activate_cross_playoff()
        return [
            self.cross_matches[mid].public_dict()
            for mid in self.cross_order
            if self.cross_matches[mid].status == MATCH_READY
        ]

    def resolve_match(self, match_id: str) -> MatchResolution:
        for runtime in self.pool_runtimes:
            if match_id in runtime.matches:
                resolution = runtime.resolve_match(match_id)
                if self.pool_phase_complete:
                    self._activate_cross_playoff()
                return resolution

        self._activate_cross_playoff()
        if match_id not in self.cross_matches:
            raise KeyError(f"unknown match_id: {match_id}")
        match = self.cross_matches[match_id]
        if match.status != MATCH_READY:
            raise ValueError(
                f"{match_id}: match is not ready (status={match.status})"
            )
        return resolve_runtime_match(
            match,
            competition_id=self.competition_id,
            reference_year=self.reference_year,
            generation_seed=self.generation_seed,
            namespace=(
                f"{self.competition_id}:{self.stage_id}:"
                f"{self.group['stage_group_id']}:CROSS_PLAYOFF:"
                f"M{match.match_seq}:{match.team1}:{match.team2}"
            ),
            match_resolver=self.match_resolver,
            resolved_match_sink=self.match_simulation_results,
        )

    def resolve_ready_round(self) -> list[MatchResolution]:
        if not self.pool_phase_complete:
            results = []
            for runtime in self.pool_runtimes:
                for row in list(runtime.ready_matches()):
                    results.append(runtime.resolve_match(row["match_id"]))
            self._activate_cross_playoff()
            return results

        self._activate_cross_playoff()
        return [
            self.resolve_match(row["match_id"])
            for row in list(self.ready_matches())
        ]

    def resolve_all(self) -> list[str]:
        while not self.is_complete:
            resolved = self.resolve_ready_round()
            if not resolved and not self.is_complete:
                raise RuntimeError("FMT006 runtime stalled")
        return self.output_school_ids()

    def _activate_cross_playoff(self) -> None:
        if self.cross_activated or not self.pool_phase_complete:
            return

        direct = []
        runnerups_3 = []
        standings = {}
        for pool_no, (pool, runtime) in enumerate(
            zip(self.pools, self.pool_runtimes),
            start=1,
        ):
            ranking = runtime.ranking()
            standings[str(pool_no)] = runtime.standings()
            if len(pool) == 4:
                direct.extend(ranking[:2])
            else:
                direct.append(ranking[0])
                runnerups_3.append(ranking[1])

        self.direct_school_ids = direct
        self.runnerup_3_school_ids = runnerups_3
        self.standings_by_pool = standings

        candidates = shuffled(
            runnerups_3,
            self.generation_seed,
            f"{self.competition_id}:{self.stage_id}:"
            f"{self.group['stage_group_id']}:cross_playoff_draw",
        )
        match_no = 1
        i = 0
        while i < len(candidates):
            team1 = candidates[i]
            match_id = (
                f"{self.stage_id}-{self.group['stage_group_id']}-"
                f"CROSS_PLAYOFF-M{match_no:03d}"
            )
            if i + 1 >= len(candidates):
                self.cross_matches[match_id] = RuntimePreMainMatch(
                    match_id=match_id,
                    competition_id=self.competition_id,
                    stage_id=self.stage_id,
                    stage_code=self.stage_code,
                    phase_code="CROSS_PLAYOFF",
                    round_no=1,
                    group_id=self.group["stage_group_id"],
                    group_name=self.group["group_name"],
                    team1=team1,
                    winner=team1,
                    status=MATCH_BYE,
                    is_bye=True,
                    match_seq=match_no,
                    metadata={"reason": "unpaired_3team_pool_runnerup"},
                )
                self.cross_order.append(match_id)
                break

            team2 = candidates[i + 1]
            self.cross_matches[match_id] = RuntimePreMainMatch(
                match_id=match_id,
                competition_id=self.competition_id,
                stage_id=self.stage_id,
                stage_code=self.stage_code,
                phase_code="CROSS_PLAYOFF",
                round_no=1,
                group_id=self.group["stage_group_id"],
                group_name=self.group["group_name"],
                team1=team1,
                team2=team2,
                status=MATCH_READY,
                match_seq=match_no,
            )
            self.cross_order.append(match_id)
            match_no += 1
            i += 2

        self.cross_activated = True

    def output_school_ids(self) -> list[str]:
        if not self.is_complete:
            raise ValueError("FMT006 output unavailable before completion")
        supplemental = [
            self.cross_matches[mid].winner
            for mid in self.cross_order
        ]
        output = list(self.direct_school_ids) + supplemental
        if len(output) != self.output_slots:
            raise AssertionError(
                f"{self.group['group_name']}: qualifiers={len(output)} "
                f"!= output_slots={self.output_slots}"
            )
        return output

    def metadata(self) -> dict:
        if not self.is_complete:
            raise ValueError("FMT006 metadata unavailable before completion")
        return {
            "entrant_count": len(self.eligible_school_ids),
            "output_slots": self.output_slots,
            "pool_sizes": [len(pool) for pool in self.pools],
            "four_team_pool_count": sum(
                1 for pool in self.pools if len(pool) == 4
            ),
            "three_team_pool_count": sum(
                1 for pool in self.pools if len(pool) == 3
            ),
            "direct_pool_qualifiers": len(self.direct_school_ids),
            "cross_playoff_qualifiers": len(self.cross_order),
            "standings": dict(self.standings_by_pool),
            "draw_source": (
                "annual_override"
                if self.group.get("_runtime_supplied_pools")
                else "simulated_draw"
            ),
        }

    def to_matches(self) -> list[Match]:
        if self.pool_phase_complete:
            self._activate_cross_playoff()
        matches = [
            match
            for runtime in self.pool_runtimes
            for match in runtime.to_matches()
        ]
        matches.extend(
            Match(
                match_id=m.match_id,
                competition_id=m.competition_id,
                stage_id=m.stage_id,
                stage_code=m.stage_code,
                phase_code=m.phase_code,
                round_no=m.round_no,
                group_id=m.group_id,
                group_name=m.group_name,
                team1=m.team1,
                team2=m.team2,
                winner=m.winner,
                loser=m.loser,
                is_bye=m.is_bye,
                metadata=dict(m.metadata),
            )
            for m in (
                self.cross_matches[mid]
                for mid in self.cross_order
            )
        )
        return matches
