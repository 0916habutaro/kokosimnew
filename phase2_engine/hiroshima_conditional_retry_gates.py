"""Pure, opt-in FMT025-style second-chance gate *prototype*.

This small deterministic gate evaluator does not belong to the live
tournament scheduler. A loser never gains another match unless the
upstream match explicitly names the target gate and the next gate consumes
that exact outcome token. It neither guesses draw edges from a 2026 team
list nor simulates optional post-qualification ranking fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass


class GateContractError(ValueError):
    """An unsafe, incomplete or contradictory proposed gate graph."""


@dataclass(frozen=True)
class RepechageGateSpec:
    gate_id: str
    left_source: str
    right_source: str
    winner_awards_berth: bool
    winner_to_gate: str | None = None
    loser_to_gate: str | None = None
    gate_role: str = "cross_zone_decider"


@dataclass(frozen=True)
class GateReplayResult:
    qualifiers: tuple[str, ...]
    played_gate_ids: tuple[str, ...]
    retried_loser_ids: tuple[str, ...]


_ALLOWED_GATE_ROLES = frozenset((
    "zone_runner_up", "cross_zone_decider", "conditional_retry_decider",
))


def replay_explicit_gate_graph(
    *,
    eligible_ids: tuple[str, ...],
    gate_specs: tuple[RepechageGateSpec, ...],
    winners_by_gate: dict[str, str],
    qualifier_slots: int,
    direct_main_entry_ids: tuple[str, ...] = (),
) -> GateReplayResult:
    """Check a *supplied* gate plan and results without creating a draw.

    Entrant sources: `entrant:arbitrary-id`.
    Upstream outcome sources: `winner:gate-id` or `loser:gate-id`.
    Every outcome source requires a matching upstream `*_to_gate`.
    Winners already given a berth cannot be drawn again; losers are
    eliminated unless the gate authorizes a *named* subsequent gate.
    """
    entrants = tuple(eligible_ids)
    direct = tuple(direct_main_entry_ids)
    if (
        len(set(entrants)) != len(entrants)
        or len(set(direct)) != len(direct)
        or set(entrants).intersection(direct)
    ):
        raise GateContractError("entrant/direct MAIN candidate sets must be unique and disjoint")
    if not entrants or not isinstance(qualifier_slots, int) or qualifier_slots < 1:
        raise GateContractError("nonempty entrant pool and positive qualifier quota required")
    gate_ids = [s.gate_id for s in gate_specs]
    if not gate_ids or any(not x for x in gate_ids) or len(set(gate_ids)) != len(gate_ids):
        raise GateContractError("at least one uniquely named gate is required")
    if set(winners_by_gate) != set(gate_ids):
        raise GateContractError("one externally determined winner is required for every gate")

    specs = {s.gate_id: s for s in gate_specs}
    for s in gate_specs:
        if s.gate_role not in _ALLOWED_GATE_ROLES:
            raise GateContractError(f"optional ranking or unknown gate role prohibited: {s.gate_id}")
        for target in (s.winner_to_gate, s.loser_to_gate):
            if target is not None and (
                target == s.gate_id or target not in specs
            ):
                raise GateContractError(f"forwarding must refer to another declared gate: {s.gate_id}")
        if s.winner_awards_berth and s.winner_to_gate is not None:
            raise GateContractError(f"qualified winner cannot enter another gate: {s.gate_id}")

    outcomes: dict[str, tuple[str, str]] = {}
    used_initial = set()
    used_outcome_sources = set()
    awarded = set()
    qualifiers: list[str] = []
    retries: list[str] = []
    for s in gate_specs:
        participants: list[str] = []
        for token in (s.left_source, s.right_source):
            typ, sep, value = token.partition(":")
            if sep != ":" or not value or typ not in ("entrant", "winner", "loser"):
                raise GateContractError(f"invalid gate candidate source {token!r}")
            if typ == "entrant":
                if value not in entrants or value in used_initial:
                    raise GateContractError(f"unknown or reused entrant source: {token}")
                used_initial.add(value)
                candidate = value
            else:
                if value not in outcomes:
                    raise GateContractError(f"future or unknown outcome referenced: {token}")
                if token in used_outcome_sources:
                    raise GateContractError(f"outcome source reused: {token}")
                upstream = specs[value]
                authorized_target = (
                    upstream.winner_to_gate if typ == "winner"
                    else upstream.loser_to_gate
                )
                if authorized_target != s.gate_id:
                    raise GateContractError(f"missing explicit directed transfer for {token}")
                used_outcome_sources.add(token)
                candidate = outcomes[value][0 if typ == "winner" else 1]
                if typ == "loser":
                    retries.append(candidate)
            if candidate in awarded:
                raise GateContractError(f"qualified team incorrectly re-entered: {candidate}")
            participants.append(candidate)

        if len(set(participants)) != 2:
            raise GateContractError(f"team cannot compete against itself in gate {s.gate_id}")
        chosen = winners_by_gate[s.gate_id]
        if chosen not in participants:
            raise GateContractError(f"winner not a participant in gate {s.gate_id}")
        loser = next(t for t in participants if t != chosen)
        outcomes[s.gate_id] = (chosen, loser)
        if s.winner_awards_berth:
            if chosen in awarded or len(qualifiers) >= qualifier_slots:
                raise GateContractError(f"duplicate/excess qualification winner: {chosen}")
            awarded.add(chosen)
            qualifiers.append(chosen)

    for spec in gate_specs:
        for typ, target in (("winner", spec.winner_to_gate), ("loser", spec.loser_to_gate)):
            if target is not None and f"{typ}:{spec.gate_id}" not in used_outcome_sources:
                raise GateContractError(
                    f"declared outcome transfer not consumed by target {target}: {spec.gate_id}"
                )
    if len(qualifiers) != qualifier_slots:
        raise GateContractError(
            f"gate output quota mismatch: {len(qualifiers)} vs {qualifier_slots}"
        )
    return GateReplayResult(
        qualifiers=tuple(qualifiers),
        played_gate_ids=tuple(gate_ids),
        retried_loser_ids=tuple(retries),
    )
