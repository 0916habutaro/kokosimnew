"""Stage13E-3G-31: audit a pure explicit-outcome replay without releasing FMT025.

The 2026 Hiroshima autumn-west 25/32 historical graph is translated in
memory solely to *exercise* the generic explicit DAG validator. It is
reconstructed from secondary dated results, NOT presented as 25/32 verified
official drawing arrows, and is never persisted as future-year rules.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g25 import (
    NODES_FILE, EDGES_FILE, audit_2026_hiroshima_stage13e3g25,
)
from .hiroshima_stage13e3g28 import NUMBER_QUEUE_FILE, ARROW_QUEUE_FILE
from .hiroshima_stage13e3g30 import (
    UNRESOLVED_ROUTE_RULES_FILE, audit_2026_hiroshima_stage13e3g30,
)
from .hiroshima_explicit_match_dag_sandbox import (
    ExplicitMatch, ExplicitMatchReplayError, replay_explicit_match_dag,
)

SANDBOX_EXAMPLES_FILE = "research/2026/hiroshima_explicit_match_sandbox_examples_stage13e3g31.csv"
SCENARIOS = {
    "simple_four_entrants": ("primary_then_repechage", ("A","B","C","D"), 3, 0,
                            ("A","C","B")),
    "conditional_six_entrants": ("explicit_conditional_retry", ("A","B","C","D","E","F"),
                                5, 2, ("A","C","E","B","D")),
}
KNOWN_AUTUMN_WEST_2026_QUALIFIERS = frozenset(
    ("広島商", "山陽", "広島国泰寺", "崇徳", "広島井口", "基町", "広島工大")
)


def _read_bool(token: str) -> bool:
    if token not in ("yes", "no"):
        raise ExplicitMatchReplayError("explicit yes/no values required")
    return token == "yes"


def replay_stage25_historical_observations(
    nodes: list[dict], edges: list[dict],
):
    """In-memory school-by-school 2026 *historical* replay, not a template."""
    if len(nodes) != 25 or len(edges) != 32:
        raise ExplicitMatchReplayError("expected 25 historical matches and 32 continuations")
    inbound: dict[tuple[str, str], dict] = {}
    outbound: dict[tuple[str, str], dict] = {}
    for record in edges:
        result = record["from_result"]
        if result not in ("winner", "loser"):
            raise ExplicitMatchReplayError("observed result must be winner or loser")
        a = (record["to_match_id"], record["school_display_name"])
        b = (record["from_match_id"], result)
        if a in inbound or b in outbound:
            raise ExplicitMatchReplayError("observed outcome was duplicated or reused")
        inbound[a] = record
        outbound[b] = record
    initial_ids = set()
    consumed = set()
    matches = []
    by_match = {x["match_id"]: x for x in nodes}
    if len(by_match) != len(nodes):
        raise ExplicitMatchReplayError("duplicate historical match")
    role_groups = Counter()
    winners = {}
    for node in sorted(nodes, key=lambda x:(x["match_date"], x["match_id"])):
        match_id = node["match_id"]
        slot_sources = []
        for school in (node["team1_name"], node["team2_name"]):
            incoming = inbound.get((match_id, school))
            if incoming is None:
                if school in initial_ids:
                    raise ExplicitMatchReplayError("repeated initial school has no recorded continuation")
                initial_ids.add(school)
                slot_sources.append(f"entrant:{school}")
            else:
                consumed.add(incoming["transition_id"])
                slot_sources.append(incoming["from_result"] + ":" + incoming["from_match_id"])
        phase = node["phase_execution_role"]
        role_groups[phase] += 1
        winner_edge = outbound.get((match_id, "winner"))
        loser_edge = outbound.get((match_id, "loser"))
        matches.append(ExplicitMatch(
            match_id=match_id,
            left_source=slot_sources[0],
            right_source=slot_sources[1],
            phase=phase,
            winner_to_match=winner_edge["to_match_id"] if winner_edge else None,
            loser_to_match=loser_edge["to_match_id"] if loser_edge else None,
            winner_awards_berth=(node["winner_berth_status"] == "berth_award"),
            loser_retry_authorized=False,
        ))
        winners[match_id] = node["observed_winner"]
    if consumed != {x["transition_id"] for x in edges}:
        raise ExplicitMatchReplayError("orphan historical continuation")
    actual = replay_explicit_match_dag(
        entrant_ids=tuple(sorted(initial_ids)), matches=tuple(matches),
        winners_by_match=winners, qualifier_slots=7,
    )
    if (role_groups != {"PRIMARY": 14, "REPECHAGE_ZONE": 10,
                        "REPECHAGE_CROSS_ZONE_GATE": 1}
            or len(actual.match_traces) != 25
            or len(actual.consumed_initial_entrant_ids) != 18
            or actual.consumed_declared_outcome_transfers != 32
            or actual.retried_loser_ids
            or frozenset(actual.qualifier_ids) != KNOWN_AUTUMN_WEST_2026_QUALIFIERS):
        raise ExplicitMatchReplayError("25-match historical replay invariant changed")
    return actual


def audit_2026_hiroshima_stage13e3g31(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    examples = _read(root, SANDBOX_EXAMPLES_FILE)
    nodes = _read(root, NODES_FILE)
    edges = _read(root, EDGES_FILE)
    official_numbers = _read(root, NUMBER_QUEUE_FILE)
    official_arrows = _read(root, ARROW_QUEUE_FILE)
    pending = _read(root, UNRESOLVED_ROUTE_RULES_FILE)
    errors: list[str] = []
    prev25 = audit_2026_hiroshima_stage13e3g25(root)
    prev30 = audit_2026_hiroshima_stage13e3g30(root)
    if not prev25["ok"]:
        errors.append("Stage25 observed match graph must still pass audit")
    if not prev30["ok"]:
        errors.append("Stage30 unresolved 48 official route requirements must still pass audit")
    if (len(official_numbers) != 25 or
            any(x["official_number_verified"] != "no" for x in official_numbers)
            or len(official_arrows) != 32 or
            any(x["official_arrow_verified"] != "no" for x in official_arrows)):
        errors.append("independent 2026 official drawing verification remains unresolved")
    if (len(pending) != 48 or
            any(x["fmt025_runtime_authorized"] != "no"
                or x["explicit_2026_formula_available"] != "no"
                for x in pending)):
        errors.append("official transfer formula cannot be inferred from sandbox")

    example_counts = Counter(x["scenario_id"] for x in examples)
    if example_counts != {"simple_four_entrants": 3, "conditional_six_entrants": 6}:
        errors.append(f"two separate fictional DAG examples with 3/5 matches required: {example_counts}")
    sandbox_runs = {}
    for name, (kind, entrants, quota, retry_count, winners) in SCENARIOS.items():
        rows = [x for x in examples if x["scenario_id"] == name]
        if not rows:
            continue
        specs = []
        outcome = {}
        for idx, row in enumerate(rows, 1):
            expected = {
                "scenario_id": name, "scenario_kind": kind, "match_order": str(idx),
                "proof_scope": "hypothetical_fictional_ids_no_federation_rule",
                "official_2026_bracket_verified": "no",
                "live_fmt025_enabled": "no",
                "optional_ranking_enabled": "no",
            }
            for field, value in expected.items():
                if row.get(field) != value:
                    errors.append(f"sandbox proof scope was upgraded: {name}/{idx}/{field}")
            try:
                spec = ExplicitMatch(
                    match_id=row["match_id"],
                    phase=row["phase"],
                    left_source=row["left_source"],
                    right_source=row["right_source"],
                    winner_to_match=row["winner_to_match"] or None,
                    loser_to_match=row["loser_to_match"] or None,
                    winner_awards_berth=_read_bool(row["winner_awards_berth"]),
                    loser_retry_authorized=_read_bool(row["loser_retry_authorized"]),
                )
            except (KeyError, ExplicitMatchReplayError) as exc:
                errors.append(f"invalid sandbox fixture row: {name}/{idx}/{exc}")
                continue
            specs.append(spec)
            outcome[spec.match_id] = row["declared_winner"]
        if len(specs) != len(rows):
            continue
        try:
            replay = replay_explicit_match_dag(
                entrant_ids=entrants, matches=tuple(specs),
                winners_by_match=outcome, qualifier_slots=quota,
            )
            if (len(replay.match_traces) != len(rows)
                    or len(replay.retried_loser_ids) != retry_count
                    or replay.qualifier_ids != winners
                    or replay.live_fmt025_runtime_enabled
                    or replay.official_draw_verified
                    or replay.generated_bracket
                    or replay.optional_ranking_enabled):
                errors.append(f"fictional replay quota/retry result changed: {name}")
            sandbox_runs[name] = {
                "matches": len(replay.match_traces), "qualifiers": len(replay.qualifier_ids),
                "conditional_retries": len(replay.retried_loser_ids),
            }
        except ExplicitMatchReplayError as exc:
            errors.append(f"fictional explicit match graph rejected: {name}/{exc}")

    observed_replay = None
    try:
        observed_replay = replay_stage25_historical_observations(nodes, edges)
    except ExplicitMatchReplayError as exc:
        errors.append(f"historical 2026 25/32 mechanical replay failed: {exc}")
    return {
        "ok": not errors, "errors": errors,
        "fictional_sandbox_scenarios": sandbox_runs,
        "observed_2026_west_replay_matches": len(observed_replay.match_traces) if observed_replay else 0,
        "observed_2026_west_replay_initial_entrants":
            len(observed_replay.consumed_initial_entrant_ids) if observed_replay else 0,
        "observed_2026_west_replay_transfers":
            observed_replay.consumed_declared_outcome_transfers if observed_replay else 0,
        "observed_2026_west_replay_berths":
            len(observed_replay.qualifier_ids) if observed_replay else 0,
        "official_2026_independently_verified_match_arrows": 0,
        "remaining_unverified_season_district_rules": len(pending),
        "year_independent_loser_rule_verified": False,
        "automatic_match_pairings_generated": False,
        "live_fmt025_runtime_enabled": False,
        "optional_ranking_enabled": False,
    }
