"""Stage13E-3G-31: generic, read-only *sandbox* replay of explicit match DAGs.

All matches, both entrants for each match, and both winner/loser transfers must
be explicitly supplied.  This does NOT choose a bracket, infer a loser's
destination, schedule dates, decide games, prove an official 2026 drawing,
or attach to the production FMT025 scheduler.

Unlike the existing repechage-only gate evaluator, this model accepts
PRIMARY and secondary matches together, enabling mechanical verification of
primary-loss -> repechage and optional *explicit* conditional retry.
"""
from __future__ import annotations

from dataclasses import dataclass


class ExplicitMatchReplayError(ValueError):
    """Incomplete or contradictory sandbox match-outcome topology."""


@dataclass(frozen=True)
class ExplicitMatch:
    match_id: str
    left_source: str
    right_source: str
    phase: str
    winner_to_match: str | None = None
    loser_to_match: str | None = None
    winner_awards_berth: bool = False
    loser_retry_authorized: bool = False


@dataclass(frozen=True)
class ExplicitMatchTrace:
    match_id: str
    phase: str
    left_entrant_id: str
    right_entrant_id: str
    winner_id: str
    loser_id: str
    winner_awards_berth: bool


@dataclass(frozen=True)
class ExplicitMatchReplay:
    match_traces: tuple[ExplicitMatchTrace, ...]
    qualifier_ids: tuple[str, ...]
    direct_main_entry_ids: tuple[str, ...]
    all_main_entry_ids: tuple[str, ...]
    consumed_initial_entrant_ids: tuple[str, ...]
    consumed_declared_outcome_transfers: int
    retried_loser_ids: tuple[str, ...]
    proof_scope: str = "supplied_graph_and_winners_sandbox_not_an_official_draw"
    official_draw_verified: bool = False
    generated_bracket: bool = False
    live_fmt025_runtime_enabled: bool = False
    optional_ranking_enabled: bool = False


PHASE_PRIMARY = "PRIMARY"
PHASE_REPECHAGE = "REPECHAGE_ZONE"
PHASE_CROSS = "REPECHAGE_CROSS_ZONE_GATE"
PHASE_CONDITIONAL = "CONDITIONAL_RETRY"
PHASES = frozenset((PHASE_PRIMARY, PHASE_REPECHAGE, PHASE_CROSS, PHASE_CONDITIONAL))
_ALLOWED_SECONDARY_WINNER_TARGETS = frozenset(
    (PHASE_REPECHAGE, PHASE_CROSS, PHASE_CONDITIONAL)
)


def replay_explicit_match_dag(
    *,
    entrant_ids: tuple[str, ...],
    matches: tuple[ExplicitMatch, ...],
    winners_by_match: dict[str, str],
    qualifier_slots: int,
    direct_main_entry_ids: tuple[str, ...] = (),
) -> ExplicitMatchReplay:
    """Deterministically validate an *externally specified* full match graph.

    Gate inputs must be 'entrant:<school-id>', 'winner:<match-id>' or
    'loser:<match-id>'.  Every target/source pair is consumed exactly once.
    There are never automatic loser destinations. Every initial entrant
    appears exactly once at the beginning of their chronological path.
    """
    if (not entrant_ids or any(not isinstance(x, str) or not x for x in entrant_ids)
            or len(set(entrant_ids)) != len(entrant_ids)):
        raise ExplicitMatchReplayError("unique, nonempty initial entrant IDs are required")
    direct = tuple(direct_main_entry_ids)
    if (any(not isinstance(x, str) or not x for x in direct)
            or len(set(direct)) != len(direct) or set(direct) & set(entrant_ids)):
        raise ExplicitMatchReplayError("direct MAIN exemptions must be unique and disjoint")
    if (not isinstance(qualifier_slots, int) or isinstance(qualifier_slots, bool)
            or qualifier_slots < 1 or qualifier_slots > len(entrant_ids)):
        raise ExplicitMatchReplayError("positive bounded qualifier berth count required")
    if not matches:
        raise ExplicitMatchReplayError("at least one explicitly paired match required")
    ids = [m.match_id for m in matches]
    if (any(not isinstance(i, str) or not i or ":" in i for i in ids)
            or len(set(ids)) != len(ids)):
        raise ExplicitMatchReplayError("unique, nonempty match IDs without ':' required")
    if set(winners_by_match) != set(ids):
        raise ExplicitMatchReplayError("a declared winner is required for every played match")
    plans = {m.match_id: m for m in matches}
    expected_sources: dict[str, str] = {}
    for m in matches:
        if m.phase not in PHASES:
            raise ExplicitMatchReplayError("unknown or ranking-only match phase forbidden")
        if m.left_source == m.right_source:
            raise ExplicitMatchReplayError("both pairing slots cannot use one outcome token")
        if m.loser_retry_authorized and (
            m.phase == PHASE_PRIMARY or m.loser_to_match is None
        ):
            raise ExplicitMatchReplayError("conditional repeat only after an explicitly routed secondary loss")
        if m.winner_awards_berth and m.winner_to_match is not None:
            raise ExplicitMatchReplayError("qualified winner cannot play again")
        for side, to in (("winner", m.winner_to_match), ("loser", m.loser_to_match)):
            if to is None:
                continue
            destination = plans.get(to)
            if destination is None or to == m.match_id:
                raise ExplicitMatchReplayError("transfer target must be a distinct declared match")
            if side == "winner":
                if m.phase == PHASE_PRIMARY and destination.phase != PHASE_PRIMARY:
                    raise ExplicitMatchReplayError("primary winner must stay in primary or qualify")
                if m.phase != PHASE_PRIMARY and destination.phase not in _ALLOWED_SECONDARY_WINNER_TARGETS:
                    raise ExplicitMatchReplayError("secondary winner cannot enter a primary bracket")
            elif m.phase == PHASE_PRIMARY:
                if destination.phase != PHASE_REPECHAGE:
                    raise ExplicitMatchReplayError("primary loser must enter an explicitly named repechage match")
            elif not m.loser_retry_authorized or destination.phase != PHASE_CONDITIONAL:
                raise ExplicitMatchReplayError("secondary loser requires explicit conditional-retry authorization")
            token = f"{side}:{m.match_id}"
            expected_sources[token] = to

    used_initial: set[str] = set()
    used_tokens: set[str] = set()
    outcomes: dict[str, tuple[str, str]] = {}
    awarded: set[str] = set()
    qualifiers: list[str] = []
    retries: list[str] = []
    traces: list[ExplicitMatchTrace] = []
    for m in matches:
        participants: list[str] = []
        for token in (m.left_source, m.right_source):
            kind, sep, key = token.partition(":")
            if sep != ":" or not key or kind not in {"entrant", "winner", "loser"}:
                raise ExplicitMatchReplayError(f"invalid match slot source: {token}")
            if kind == "entrant":
                if key not in entrant_ids or key in used_initial:
                    raise ExplicitMatchReplayError(f"unknown or duplicated first entry: {token}")
                used_initial.add(key)
                candidate = key
            else:
                if key not in outcomes:
                    raise ExplicitMatchReplayError(f"outcome must come from a prior played match: {token}")
                if token in used_tokens or expected_sources.get(token) != m.match_id:
                    raise ExplicitMatchReplayError(f"outcome used twice or without explicit forwarding: {token}")
                used_tokens.add(token)
                candidate = outcomes[key][0 if kind == "winner" else 1]
                if kind == "loser" and plans[key].phase != PHASE_PRIMARY:
                    retries.append(candidate)
            if candidate in awarded:
                raise ExplicitMatchReplayError("qualified entrant cannot enter another match")
            participants.append(candidate)
        if participants[0] == participants[1]:
            raise ExplicitMatchReplayError("a school cannot face itself")
        winner = winners_by_match[m.match_id]
        if winner not in participants:
            raise ExplicitMatchReplayError(f"externally supplied match winner is not a participant: {m.match_id}")
        loser = participants[1] if winner == participants[0] else participants[0]
        outcomes[m.match_id] = (winner, loser)
        if m.winner_awards_berth:
            if winner in awarded:
                raise ExplicitMatchReplayError("duplicate qualification berth")
            qualifiers.append(winner)
            awarded.add(winner)
        traces.append(ExplicitMatchTrace(
            m.match_id, m.phase, participants[0], participants[1],
            winner, loser, m.winner_awards_berth,
        ))

    if used_initial != set(entrant_ids):
        raise ExplicitMatchReplayError("each initial entrant must appear exactly once in a first-match slot")
    if used_tokens != set(expected_sources):
        raise ExplicitMatchReplayError("declared outcome forwarding must have exactly one matching consumer")
    if len(qualifiers) != qualifier_slots or len(set(qualifiers)) != qualifier_slots:
        raise ExplicitMatchReplayError("actual qualifiers must match the declared berth quota")
    all_main = tuple(qualifiers) + direct
    if len(set(all_main)) != len(all_main):
        raise ExplicitMatchReplayError("MAIN entry duplicates qualification or exemptions")
    return ExplicitMatchReplay(
        match_traces=tuple(traces), qualifier_ids=tuple(qualifiers),
        direct_main_entry_ids=direct, all_main_entry_ids=all_main,
        consumed_initial_entrant_ids=tuple(sorted(used_initial)),
        consumed_declared_outcome_transfers=len(used_tokens),
        retried_loser_ids=tuple(retries),
    )
