from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from math import log2
from typing import Callable, Dict, List, Sequence

from .brackets import random_winner_resolver
from .main_tournament import (
    _round_name,
    generate_main_slots,
    ordered_seed_ids,
)
from .models import (
    AnnualCompetitionInput,
    CompetitionOutcome,
    CompetitionRun,
    Match,
    MatchResolution,
    SeedAssignment,
    StageExecution,
)
from .randomness import shuffled
from .repository import DataRepository


MATCH_WAITING = "waiting"
MATCH_READY = "ready"
MATCH_COMPLETED = "completed"
MATCH_BYE = "bye"


@dataclass
class RuntimeBracketMatch:
    match_id: str
    competition_id: str
    stage_id: str
    round_no: int
    round_name: str
    match_no_in_round: int
    next_match_id: str = ""
    next_match_side: str = ""
    team1: str = ""
    team2: str = ""
    status: str = MATCH_WAITING
    winner: str = ""
    loser: str = ""
    is_bye: bool = False
    metadata: dict = field(default_factory=dict)

    def public_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "competition_id": self.competition_id,
            "stage_id": self.stage_id,
            "stage_code": "MAIN",
            "phase_code": "MAIN_BRACKET",
            "round_no": self.round_no,
            "round_name": self.round_name,
            "match_no_in_round": self.match_no_in_round,
            "next_match_id": self.next_match_id,
            "next_match_side": self.next_match_side,
            "team1": self.team1,
            "team2": self.team2,
            "status": self.status,
            "winner": self.winner,
            "loser": self.loser,
            "is_bye": self.is_bye,
            "metadata": dict(self.metadata),
        }


@dataclass
class MainTournamentRuntimeState:
    competition_id: str
    reference_year: int
    generation_seed: int
    stage_id: str
    entrant_school_ids: List[str]
    seed_assignments: List[SeedAssignment]
    annual_seed_order: List[str]
    initial_slots: List[str]
    seed_slots: Dict[str, int]
    bracket_size: int
    total_rounds: int
    matches: Dict[str, RuntimeBracketMatch]
    match_ids_by_round: Dict[int, List[str]]
    match_resolver: Callable | None = field(default=None, repr=False)
    winner_overrides: Dict[str, str] = field(default_factory=dict)
    match_simulation_results: Dict[str, dict] = field(default_factory=dict)
    eliminated_by_round: Dict[int, List[str]] = field(
        default_factory=lambda: defaultdict(list)
    )
    champion_school_id: str = ""
    runner_up_school_id: str = ""
    draw_source: str = "deterministic_standard"

    @classmethod
    def create(
        cls,
        *,
        competition_id: str,
        reference_year: int,
        generation_seed: int,
        stage_id: str,
        entrants: Sequence[str],
        seed_assignments: Sequence[SeedAssignment] = (),
        annual_seed_order: Sequence[str] = (),
        slot_override: Sequence[str] | None = None,
        winner_overrides: Dict[str, str] | None = None,
        match_resolver=None,
    ) -> "MainTournamentRuntimeState":
        entrants = list(dict.fromkeys(entrants))
        if not entrants:
            raise ValueError("MAIN entrants cannot be empty")

        seed_ids = ordered_seed_ids(
            entrants,
            seed_assignments,
            annual_seed_order,
            base_seed=generation_seed,
            namespace=f"{competition_id}:{stage_id}:MAIN",
        )
        slots, seed_slots = generate_main_slots(
            entrants,
            seed_ids=seed_ids,
            base_seed=generation_seed,
            namespace=f"{competition_id}:{stage_id}:MAIN",
            slot_override=slot_override,
        )
        bracket_size = len(slots)
        total_rounds = (
            0 if bracket_size == 1 else int(log2(bracket_size))
        )

        state = cls(
            competition_id=competition_id,
            reference_year=reference_year,
            generation_seed=generation_seed,
            stage_id=stage_id,
            entrant_school_ids=list(entrants),
            seed_assignments=list(seed_assignments),
            annual_seed_order=list(annual_seed_order),
            initial_slots=list(slots),
            seed_slots=dict(seed_slots),
            bracket_size=bracket_size,
            total_rounds=total_rounds,
            matches={},
            match_ids_by_round={},
            match_resolver=match_resolver,
            winner_overrides=dict(winner_overrides or {}),
            draw_source=(
                "annual_override"
                if slot_override is not None and len(slot_override)
                else "deterministic_standard"
            ),
        )
        state._build_bracket_skeleton()
        state._validate()
        return state

    @classmethod
    def from_direct_main(
        cls,
        repo: DataRepository,
        annual: AnnualCompetitionInput,
        *,
        match_resolver=None,
    ) -> "MainTournamentRuntimeState":
        stages = repo.stages(annual.competition_id)
        stage_by_code = {row["stage_code"]: row for row in stages}
        if set(stage_by_code) != {"MAIN"}:
            raise ValueError(
                "from_direct_main requires a competition whose only stage is MAIN"
            )
        entrants: list[str] = []
        seen = set()
        competition = repo.competition(annual.competition_id)
        for school_id in annual.entrant_school_ids:
            if school_id in seen:
                continue
            if school_id not in repo.schools:
                raise ValueError(f"unknown school_id: {school_id}")
            if (
                competition.get("prefecture_code")
                and repo.schools[school_id].get("prefecture_code")
                != competition["prefecture_code"]
            ):
                raise ValueError(
                    f"entrant {school_id} is outside destination prefecture"
                )
            seen.add(school_id)
            entrants.append(school_id)
        if not entrants:
            raise ValueError("entrant_school_ids is required")

        outside_seeds = (
            set(annual.main_seed_school_ids) - set(entrants)
        )
        if outside_seeds:
            raise ValueError(
                f"MAIN seeds outside MAIN entrant set: {sorted(outside_seeds)}"
            )

        main_stage = stage_by_code["MAIN"]
        if main_stage.get("format_type") not in {
            "",
            "single_elimination",
        }:
            raise NotImplementedError(
                f"MAIN format {main_stage.get('format_type')} is not supported"
            )

        return cls.create(
            competition_id=annual.competition_id,
            reference_year=annual.year,
            generation_seed=annual.rng_seed,
            stage_id=main_stage["stage_id"],
            entrants=entrants,
            seed_assignments=(),
            annual_seed_order=annual.main_seed_school_ids,
            slot_override=(
                annual.main_bracket_slots
                if annual.main_bracket_slots
                else None
            ),
            winner_overrides=annual.main_match_winner_overrides,
            match_resolver=match_resolver,
        )

    def _build_bracket_skeleton(self) -> None:
        if self.bracket_size == 1:
            self.champion_school_id = self.entrant_school_ids[0]
            return

        for round_no in range(1, self.total_rounds + 1):
            count = self.bracket_size // (2 ** round_no)
            ids: list[str] = []
            for match_no in range(1, count + 1):
                match_id = self._match_id(round_no, match_no)
                next_match_id = (
                    self._match_id(
                        round_no + 1,
                        ((match_no - 1) // 2) + 1,
                    )
                    if round_no < self.total_rounds
                    else ""
                )
                next_side = (
                    "team1"
                    if match_no % 2 == 1
                    else "team2"
                )
                if round_no == 1:
                    team1 = self.initial_slots[(match_no - 1) * 2]
                    team2 = self.initial_slots[
                        (match_no - 1) * 2 + 1
                    ]
                else:
                    team1 = ""
                    team2 = ""

                self.matches[match_id] = RuntimeBracketMatch(
                    match_id=match_id,
                    competition_id=self.competition_id,
                    stage_id=self.stage_id,
                    round_no=round_no,
                    round_name=_round_name(
                        round_no,
                        self.total_rounds,
                    ),
                    match_no_in_round=match_no,
                    next_match_id=next_match_id,
                    next_match_side=next_side,
                    team1=team1,
                    team2=team2,
                )
                ids.append(match_id)
            self.match_ids_by_round[round_no] = ids

        self._refresh_all_statuses()

    def _match_id(self, round_no: int, match_no: int) -> str:
        return (
            f"{self.stage_id}-MAIN-R{round_no:02d}-M{match_no:03d}"
        )

    def _refresh_all_statuses(self) -> None:
        changed = True
        while changed:
            changed = False
            for round_no in range(1, self.total_rounds + 1):
                for match_id in self.match_ids_by_round[round_no]:
                    match = self.matches[match_id]
                    if match.status in {
                        MATCH_COMPLETED,
                        MATCH_BYE,
                    }:
                        continue
                    if not match.team1 and not match.team2:
                        match.status = MATCH_WAITING
                        continue
                    if bool(match.team1) ^ bool(match.team2):
                        if round_no != 1:
                            match.status = MATCH_WAITING
                            continue
                        winner = match.team1 or match.team2
                        match.winner = winner
                        match.loser = ""
                        match.is_bye = True
                        match.status = MATCH_BYE
                        match.metadata.update({
                            "round_name": match.round_name,
                            "bracket_size": self.bracket_size,
                            "match_no_in_round": (
                                match.match_no_in_round
                            ),
                            "next_match_id": match.next_match_id,
                            "next_match_side": match.next_match_side,
                        })
                        self._propagate_winner(match)
                        changed = True
                        continue
                    if match.team1 and match.team2:
                        match.status = MATCH_READY

    def _propagate_winner(
        self,
        match: RuntimeBracketMatch,
    ) -> None:
        if not match.next_match_id:
            self.champion_school_id = match.winner
            self.runner_up_school_id = match.loser
            return
        next_match = self.matches[match.next_match_id]
        if match.next_match_side == "team1":
            if (
                next_match.team1
                and next_match.team1 != match.winner
            ):
                raise ValueError(
                    f"{match.next_match_id}: team1 already populated"
                )
            next_match.team1 = match.winner
        elif match.next_match_side == "team2":
            if (
                next_match.team2
                and next_match.team2 != match.winner
            ):
                raise ValueError(
                    f"{match.next_match_id}: team2 already populated"
                )
            next_match.team2 = match.winner
        else:
            raise ValueError(
                f"{match.match_id}: invalid next_match_side"
            )

    def ready_matches(self) -> list[dict]:
        return [
            self.matches[match_id].public_dict()
            for round_no in range(1, self.total_rounds + 1)
            for match_id in self.match_ids_by_round[round_no]
            if self.matches[match_id].status == MATCH_READY
        ]

    def waiting_matches(self) -> list[dict]:
        return [
            self.matches[match_id].public_dict()
            for round_no in range(1, self.total_rounds + 1)
            for match_id in self.match_ids_by_round[round_no]
            if self.matches[match_id].status == MATCH_WAITING
        ]

    def completed_matches(self) -> list[dict]:
        return [
            self.matches[match_id].public_dict()
            for round_no in range(1, self.total_rounds + 1)
            for match_id in self.match_ids_by_round[round_no]
            if self.matches[match_id].status
            in {MATCH_COMPLETED, MATCH_BYE}
        ]

    def resolve_match(
        self,
        match_id: str,
    ) -> MatchResolution:
        if match_id not in self.matches:
            raise KeyError(f"unknown match_id: {match_id}")
        match = self.matches[match_id]
        if match.status != MATCH_READY:
            raise ValueError(
                f"{match_id}: match is not ready "
                f"(status={match.status})"
            )

        resolution = self._resolve_ready_match(match)
        match.winner = resolution.winner_id
        match.loser = resolution.loser_id
        match.status = MATCH_COMPLETED
        match.metadata.update({
            "round_name": match.round_name,
            "bracket_size": self.bracket_size,
            "match_no_in_round": match.match_no_in_round,
            "next_match_id": match.next_match_id,
            "next_match_side": match.next_match_side,
            "winner_source": (
                "annual_override"
                if match_id in self.winner_overrides
                else (
                    resolution.score_source
                    if resolution.score_source
                    else "resolver"
                )
            ),
        })
        if resolution.team1_score is not None:
            match.metadata["score_source"] = (
                resolution.score_source
            )
            match.metadata["team1_score"] = (
                resolution.team1_score
            )
            match.metadata["team2_score"] = (
                resolution.team2_score
            )

        self.eliminated_by_round[match.round_no].append(
            match.loser
        )
        self._store_resolution_detail(match, resolution)
        self._propagate_winner(match)
        self._refresh_all_statuses()
        self._validate()
        return resolution

    def _resolve_ready_match(
        self,
        match: RuntimeBracketMatch,
    ) -> MatchResolution:
        t1 = match.team1
        t2 = match.team2
        if match.match_id in self.winner_overrides:
            winner = self.winner_overrides[match.match_id]
            if winner not in {t1, t2}:
                raise ValueError(
                    f"winner override for {match.match_id} "
                    "is not a participant"
                )
            loser = t2 if winner == t1 else t1
            return MatchResolution(
                winner_id=winner,
                loser_id=loser,
                score_source="annual_override",
            )

        if self.match_resolver is None:
            resolver = random_winner_resolver(
                self.generation_seed
            )
            namespace = (
                f"{self.competition_id}:{self.stage_id}:MAIN:"
                f"R{match.round_no}:M{match.match_no_in_round}:"
                f"{t1}:{t2}"
            )
            winner = resolver(t1, t2, namespace)
            loser = t2 if winner == t1 else t1
            return MatchResolution(
                winner_id=winner,
                loser_id=loser,
                score_source="resolver",
            )

        resolution = self.match_resolver(
            match_id=match.match_id,
            competition_id=self.competition_id,
            reference_year=self.reference_year,
            generation_seed=self.generation_seed,
            team1=t1,
            team2=t2,
        )
        self._validate_resolution(match, resolution)
        return resolution

    @staticmethod
    def _validate_resolution(
        match: RuntimeBracketMatch,
        resolution,
    ) -> None:
        if not isinstance(resolution, MatchResolution):
            raise TypeError(
                "match_resolver must return MatchResolution"
            )
        if resolution.winner_id not in {
            match.team1,
            match.team2,
        }:
            raise ValueError(
                "match_resolver winner is not a participant"
            )
        expected_loser = (
            match.team2
            if resolution.winner_id == match.team1
            else match.team1
        )
        if resolution.loser_id != expected_loser:
            raise ValueError(
                "match_resolver loser is inconsistent with winner"
            )
        if (
            (resolution.team1_score is None)
            != (resolution.team2_score is None)
        ):
            raise ValueError(
                "match_resolver scores must be both present "
                "or both absent"
            )
        if resolution.team1_score is not None:
            if (
                isinstance(resolution.team1_score, bool)
                or isinstance(resolution.team2_score, bool)
                or not isinstance(resolution.team1_score, int)
                or not isinstance(resolution.team2_score, int)
            ):
                raise ValueError(
                    "match_resolver scores must be integers"
                )
            if (
                resolution.team1_score < 0
                or resolution.team2_score < 0
            ):
                raise ValueError(
                    "match_resolver scores must be non-negative"
                )
            if (
                resolution.team1_score
                == resolution.team2_score
            ):
                raise ValueError(
                    "match_resolver cannot return a tied score"
                )
            expected_winner = (
                match.team1
                if (
                    resolution.team1_score
                    > resolution.team2_score
                )
                else match.team2
            )
            if resolution.winner_id != expected_winner:
                raise ValueError(
                    "match_resolver score winner mismatch"
                )

    def _store_resolution_detail(
        self,
        match: RuntimeBracketMatch,
        resolution: MatchResolution,
    ) -> None:
        if not resolution.detail:
            return
        if match.match_id in self.match_simulation_results:
            raise ValueError(
                f"duplicate resolved match id: {match.match_id}"
            )
        detail = dict(resolution.detail)
        detail.setdefault("match_id", match.match_id)
        detail.setdefault(
            "competition_id",
            self.competition_id,
        )
        detail.setdefault(
            "reference_year",
            self.reference_year,
        )
        detail.setdefault(
            "generation_seed",
            self.generation_seed,
        )
        detail.setdefault(
            "team1_school_id",
            match.team1,
        )
        detail.setdefault(
            "team2_school_id",
            match.team2,
        )
        detail.setdefault(
            "team1_score",
            resolution.team1_score,
        )
        detail.setdefault(
            "team2_score",
            resolution.team2_score,
        )
        detail.setdefault(
            "winner_id",
            resolution.winner_id,
        )
        detail.setdefault(
            "loser_id",
            resolution.loser_id,
        )
        detail.setdefault(
            "score_source",
            resolution.score_source,
        )
        self.match_simulation_results[match.match_id] = detail

    def resolve_ready_round(self) -> list[MatchResolution]:
        ready = [
            row["match_id"]
            for row in self.ready_matches()
        ]
        if not ready:
            return []
        min_round = min(
            self.matches[match_id].round_no
            for match_id in ready
        )
        target_ids = [
            match_id
            for match_id in ready
            if self.matches[match_id].round_no == min_round
        ]
        return [
            self.resolve_match(match_id)
            for match_id in target_ids
        ]

    def resolve_all(self) -> CompetitionRun:
        while not self.is_complete:
            resolved = self.resolve_ready_round()
            if not resolved:
                raise RuntimeError(
                    "tournament runtime stalled with no ready match"
                )
        return self.to_competition_run()

    @property
    def is_complete(self) -> bool:
        if self.bracket_size == 1:
            return bool(self.champion_school_id)
        return bool(self.champion_school_id) and all(
            match.status
            in {MATCH_COMPLETED, MATCH_BYE}
            for match in self.matches.values()
        )

    def _validate(self) -> None:
        valid = {
            MATCH_WAITING,
            MATCH_READY,
            MATCH_COMPLETED,
            MATCH_BYE,
        }
        for match_id, match in self.matches.items():
            if match.status not in valid:
                raise ValueError(
                    f"{match_id}: invalid status {match.status}"
                )
            if match.status == MATCH_READY:
                if not match.team1 or not match.team2:
                    raise ValueError(
                        f"{match_id}: ready match lacks participants"
                    )
                if match.winner or match.loser:
                    raise ValueError(
                        f"{match_id}: ready match has result"
                    )
            if match.status == MATCH_WAITING:
                if match.winner or match.loser:
                    raise ValueError(
                        f"{match_id}: waiting match has result"
                    )
            if match.status == MATCH_COMPLETED:
                if not match.winner or not match.loser:
                    raise ValueError(
                        f"{match_id}: completed match lacks result"
                    )
            if match.status == MATCH_BYE:
                if not match.winner or match.loser:
                    raise ValueError(
                        f"{match_id}: invalid bye result"
                    )
        if self.champion_school_id:
            if self.champion_school_id not in set(
                self.entrant_school_ids
            ):
                raise ValueError(
                    "champion is outside MAIN entrant set"
                )

    def _outcome(self) -> CompetitionOutcome:
        if not self.is_complete:
            raise ValueError(
                "competition outcome is unavailable before completion"
            )
        if self.bracket_size == 1:
            return CompetitionOutcome(
                champion_school_id=self.champion_school_id,
                runner_up_school_id="",
                semifinalist_school_ids=[],
                quarterfinalist_school_ids=[],
                final_ranking_school_ids=[
                    self.champion_school_id
                ],
                eliminated_by_round={},
                match_count=0,
                bye_count=0,
                bracket_size=1,
            )

        runner_up = self.runner_up_school_id
        semifinalists = (
            list(
                self.eliminated_by_round.get(
                    self.total_rounds - 1,
                    [],
                )
            )
            if self.total_rounds >= 2
            else []
        )
        quarterfinalists = (
            list(
                self.eliminated_by_round.get(
                    self.total_rounds - 2,
                    [],
                )
            )
            if self.total_rounds >= 3
            else []
        )

        final_ranking = [self.champion_school_id]
        for round_no in range(
            self.total_rounds,
            0,
            -1,
        ):
            cohort = list(
                self.eliminated_by_round.get(
                    round_no,
                    [],
                )
            )
            if (
                round_no == self.total_rounds
                and runner_up
            ):
                cohort = [runner_up]
            elif len(cohort) > 1:
                cohort = shuffled(
                    cohort,
                    self.generation_seed,
                    f"{self.competition_id}:"
                    f"{self.stage_id}:MAIN:"
                    f"ranking:{round_no}",
                )
            final_ranking.extend(cohort)

        return CompetitionOutcome(
            champion_school_id=self.champion_school_id,
            runner_up_school_id=runner_up,
            semifinalist_school_ids=semifinalists,
            quarterfinalist_school_ids=quarterfinalists,
            final_ranking_school_ids=final_ranking,
            eliminated_by_round={
                str(key): list(value)
                for key, value
                in self.eliminated_by_round.items()
            },
            match_count=sum(
                match.status == MATCH_COMPLETED
                for match in self.matches.values()
            ),
            bye_count=sum(
                match.status == MATCH_BYE
                for match in self.matches.values()
            ),
            bracket_size=self.bracket_size,
        )

    def stage_execution(self) -> StageExecution:
        matches: list[Match] = []
        for round_no in range(1, self.total_rounds + 1):
            for match_id in self.match_ids_by_round[round_no]:
                item = self.matches[match_id]
                matches.append(Match(
                    match_id=item.match_id,
                    competition_id=self.competition_id,
                    stage_id=self.stage_id,
                    stage_code="MAIN",
                    phase_code="MAIN_BRACKET",
                    round_no=item.round_no,
                    team1=item.team1,
                    team2=item.team2,
                    winner=item.winner,
                    loser=item.loser,
                    is_bye=item.is_bye,
                    metadata=dict(item.metadata),
                ))

        output = (
            [self.champion_school_id]
            if self.is_complete
            else []
        )
        seed_ids = ordered_seed_ids(
            self.entrant_school_ids,
            self.seed_assignments,
            self.annual_seed_order,
            base_seed=self.generation_seed,
            namespace=(
                f"{self.competition_id}:"
                f"{self.stage_id}:MAIN"
            ),
        )
        return StageExecution(
            stage_id=self.stage_id,
            stage_code="MAIN",
            format_model_id="MAIN_SINGLE_ELIMINATION",
            entrant_school_ids=list(self.entrant_school_ids),
            output_school_ids=output,
            matches=matches,
            metadata={
                "bracket_size": self.bracket_size,
                "bye_count": (
                    self.bracket_size
                    - len(self.entrant_school_ids)
                ),
                "seed_count": len(seed_ids),
                "seed_order_school_ids": seed_ids,
                "seed_slots": dict(self.seed_slots),
                "draw_source": self.draw_source,
                "initial_slots": list(self.initial_slots),
                "total_rounds": self.total_rounds,
                "match_ids_by_round": {
                    key: list(value)
                    for key, value
                    in self.match_ids_by_round.items()
                },
            },
        )

    def to_competition_run(self) -> CompetitionRun:
        if not self.is_complete:
            raise ValueError(
                "cannot materialize CompetitionRun before completion"
            )
        execution = self.stage_execution()
        return CompetitionRun(
            competition_id=self.competition_id,
            year=self.reference_year,
            rng_seed=self.generation_seed,
            entrant_school_ids=list(self.entrant_school_ids),
            seed_assignments=list(self.seed_assignments),
            stage_executions=[execution],
            main_entrant_school_ids=list(self.entrant_school_ids),
            warnings=[],
            outcome=self._outcome(),
            match_simulation_results=dict(
                self.match_simulation_results
            ),
        )

    def public_snapshot(self) -> dict:
        return {
            "competition_id": self.competition_id,
            "reference_year": self.reference_year,
            "generation_seed": self.generation_seed,
            "bracket_size": self.bracket_size,
            "total_rounds": self.total_rounds,
            "is_complete": self.is_complete,
            "champion_school_id": (
                self.champion_school_id
                if self.is_complete
                else ""
            ),
            "ready_match_ids": [
                row["match_id"]
                for row in self.ready_matches()
            ],
            "matches": [
                self.matches[match_id].public_dict()
                for round_no in range(
                    1,
                    self.total_rounds + 1,
                )
                for match_id
                in self.match_ids_by_round[round_no]
            ],
        }
