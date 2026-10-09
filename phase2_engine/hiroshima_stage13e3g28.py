"""Stage13E-3G-28: 2026 Hiroshima autumn-west official drawing REVIEW QUEUE.

Two separate sources must never be conflated:
- 25 played games and 32 chronological school continuations are from
  secondary dated results (Stage25).
- the official federation image preview demonstrates the 2026 *macro*
  zones but is not a verified full match-numbered arrow transcript.

This file maintains the 25+32 unfinished review questions, tests the
historical match/outcome join, and preflights externally proposed
transcriptions. Successful preflight means internally consistent CANDIDATE,
not independent evidence review, official certification, or live FMT025.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g24 import OFFICIAL_SOURCE
from .hiroshima_stage13e3g25 import (
    NODES_FILE, EDGES_FILE, audit_2026_hiroshima_stage13e3g25,
)
from .hiroshima_stage13e3g27 import audit_2026_hiroshima_stage13e3g27

NUMBER_QUEUE_FILE = "research/2026/hiroshima_autumn_west_official_number_review_queue_2026.csv"
ARROW_QUEUE_FILE = "research/2026/hiroshima_autumn_west_official_arrow_review_queue_2026.csv"
NUMBER_STATUS = "requires_high_resolution_official_number_pairing_review"
ARROW_STATUS = "requires_high_resolution_official_number_arrow_review"
NUMBER_SOURCE = "official_2026_image_preview_no_original_pdf"


class DrawReviewError(ValueError):
    """Invalid candidate data; no assertion about document authenticity."""


@dataclass(frozen=True)
class DrawMatchProposal:
    match_id: str
    official_match_number: str
    first_team: str
    second_team: str
    pinpoint: str
    document_url: str = OFFICIAL_SOURCE


@dataclass(frozen=True)
class DrawArrowProposal:
    transition_id: str
    official_from_number: str
    official_to_number: str
    participant: str
    upstream_outcome: str
    pinpoint: str
    document_url: str = OFFICIAL_SOURCE


@dataclass(frozen=True)
class DrawPreflightReport:
    candidate_match_count: int
    candidate_arrow_count: int
    candidate_only: bool = True
    independently_official_verified: bool = False
    runtime_enabled: bool = False


def _row_maps(nodes: list[dict], edges: list[dict]) -> tuple[dict, dict]:
    by_match = {x["match_id"]: x for x in nodes}
    by_transition = {x["transition_id"]: x for x in edges}
    if (len(by_match) != len(nodes) or len(by_transition) != len(edges)):
        raise DrawReviewError("duplicate match or transition ID")
    return by_match, by_transition


def preflight_proposed_2026_draw(
    *,
    historical_nodes: list[dict],
    historical_edges: list[dict],
    matches: tuple[DrawMatchProposal, ...],
    arrows: tuple[DrawArrowProposal, ...],
) -> DrawPreflightReport:
    """Validate *untrusted manual suggestions* against already played games.

    This is deliberately not a proof of reading a source: pinpoint strings and
    official page URLs are supplied by a caller and require outside review.
    No implicit drawn schedule, unplayed result, or optional ranking is built.
    Partial submissions are supported for incremental manual verification.
    """
    by_match, by_transition = _row_maps(historical_nodes, historical_edges)
    seen_ids: set[str] = set()
    number_by_match: dict[str, str] = {}
    used_numbers: set[str] = set()
    for proposal in matches:
        source = by_match.get(proposal.match_id)
        if source is None or proposal.match_id in seen_ids:
            raise DrawReviewError("unknown or duplicate historical match proposal")
        seen_ids.add(proposal.match_id)
        number = proposal.official_match_number
        if (not number.isascii() or not number.isdecimal()
                or int(number) < 1 or number != str(int(number))):
            raise DrawReviewError("positive canonical official game number required")
        if number in used_numbers:
            raise DrawReviewError("duplicate proposed official game number")
        if (set((proposal.first_team, proposal.second_team)) !=
                set((source["team1_name"], source["team2_name"]))
                or proposal.first_team == proposal.second_team):
            raise DrawReviewError("draw pairing does not match played match")
        if proposal.document_url != OFFICIAL_SOURCE or not proposal.pinpoint.strip():
            raise DrawReviewError("official 2026 source and distinct human locator required")
        used_numbers.add(number)
        number_by_match[proposal.match_id] = number

    seen_arrows: set[str] = set()
    for proposed in arrows:
        source = by_transition.get(proposed.transition_id)
        if source is None or proposed.transition_id in seen_arrows:
            raise DrawReviewError("unknown or duplicate historical arrow proposal")
        seen_arrows.add(proposed.transition_id)
        upstream = source["from_match_id"]
        downstream = source["to_match_id"]
        if upstream not in number_by_match or downstream not in number_by_match:
            raise DrawReviewError("both endpoint matches require explicitly numbered candidates")
        if (proposed.official_from_number != number_by_match[upstream]
                or proposed.official_to_number != number_by_match[downstream]):
            raise DrawReviewError("proposed arrow number does not equal endpoint match number")
        if (proposed.participant != source["school_display_name"]
                or proposed.upstream_outcome != source["from_result"]):
            raise DrawReviewError("draw transfer outcome disagrees with played result")
        if proposed.document_url != OFFICIAL_SOURCE or not proposed.pinpoint.strip():
            raise DrawReviewError("each proposed arrow requires official source and precise locator")
    return DrawPreflightReport(len(matches), len(arrows))


def audit_2026_hiroshima_stage13e3g28(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    numbers = _read(root, NUMBER_QUEUE_FILE)
    arrows = _read(root, ARROW_QUEUE_FILE)
    historical_nodes = _read(root, NODES_FILE)
    historical_edges = _read(root, EDGES_FILE)
    errors: list[str] = []
    prior = audit_2026_hiroshima_stage13e3g25(root)
    all_regions = audit_2026_hiroshima_stage13e3g27(root)
    if not prior["ok"]:
        errors.append("Stage25 historical 25/32 source audit failed")
    if not all_regions["ok"]:
        errors.append("Stage27 official eight-region macro audit failed")

    try:
        old_nodes, old_edges = _row_maps(historical_nodes, historical_edges)
        cur_numbers = {x["match_id"]: x for x in numbers}
        cur_arrows = {x["transition_id"]: x for x in arrows}
        if (len(historical_nodes) != 25 or len(historical_edges) != 32
                or len(numbers) != 25 or len(cur_numbers) != 25
                or set(cur_numbers) != set(old_nodes)
                or len(arrows) != 32 or len(cur_arrows) != 32
                or set(cur_arrows) != set(old_edges)):
            errors.append("all 25 games and 32 observed continuations need separate proof tasks")
        if len(numbers) != len(cur_numbers) or len(arrows) != len(cur_arrows):
            errors.append("duplicate evidence review tasks are prohibited")
    except DrawReviewError as exc:
        errors.append(str(exc))
        old_nodes, old_edges = {}, {}
    prios = Counter()
    for index, new in enumerate(numbers, 1):
        old = old_nodes.get(new["match_id"])
        if not old:
            continue
        zone = old["zone_scope"]
        role = old["phase_execution_role"]
        panel = ("cross_C_D_decider" if zone == "C;D" else
                 zone + "_" + ("first_place" if role == "PRIMARY" else "second_place"))
        expected = {
            "review_id": f"HNVR2026{index:03d}",
            "document_year": "2026",
            "season": "autumn", "district_code": "west",
            "stage_group_id": "SGR000144", "match_id": old["match_id"],
            "observed_node_id": old["node_audit_id"],
            "zone_scope": zone, "phase_execution_role": role,
            "draw_panel_hint": panel,
            "secondary_pairing_team1": old["team1_name"],
            "secondary_pairing_team2": old["team2_name"],
            "secondary_recorded_winner": old["observed_winner"],
            "secondary_result_source": old["secondary_result_url"],
            "official_document_url": OFFICIAL_SOURCE,
            "official_document_displayed_as": NUMBER_SOURCE,
            "official_match_number": "", "official_number_locator": "",
            "official_number_verified": "no",
            "official_pairing_verified": "no",
            "official_independent_reviewer": "",
            "official_review_status": NUMBER_STATUS,
            "live_runtime_enabled": "no",
        }
        for field, value in expected.items():
            if new.get(field) != value:
                errors.append(f"unfounded match drawing proof {old['match_id']}/{field}")

    for index, new in enumerate(arrows, 1):
        old = old_edges.get(new["transition_id"])
        if not old:
            continue
        source = old_nodes.get(old["from_match_id"])
        target = old_nodes.get(old["to_match_id"])
        if not source or not target:
            errors.append(f"missing historical endpoint {old['transition_id']}")
            continue
        priority = (
            "primary_loser_to_repechage"
            if old["from_result"] == "loser" and old["from_phase"] == "PRIMARY"
            else "runnerup_C_D_cross_gate"
            if old["to_match_id"] == "HT20260072"
            else "other_observed_continuation"
        )
        prios[priority] += 1
        expected = {
            "review_id": f"HEVR2026{index:03d}",
            "document_year": "2026",
            "season": "autumn", "district_code": "west",
            "stage_group_id": "SGR000144",
            "transition_id": old["transition_id"],
            "school_display_name": old["school_display_name"],
            "from_match_id": old["from_match_id"],
            "to_match_id": old["to_match_id"],
            "observed_outcome": old["from_result"],
            "transition_kind": old["transition_kind"],
            "from_zone_scope": source["zone_scope"],
            "to_zone_scope": target["zone_scope"],
            "official_document_url": OFFICIAL_SOURCE,
            "from_official_match_number": "",
            "to_official_match_number": "",
            "official_from_number_locator": "",
            "official_to_number_locator": "",
            "official_arrow_locator": "",
            "official_arrow_verified": "no",
            "official_independent_reviewer": "",
            "official_review_status": ARROW_STATUS,
            "review_priority": priority,
            "live_runtime_enabled": "no",
        }
        for field, value in expected.items():
            if new.get(field) != value:
                errors.append(f"unfounded arrow drawing proof {old['transition_id']}/{field}")

    expected_prios = {
        "primary_loser_to_repechage": 14,
        "runnerup_C_D_cross_gate": 2,
        "other_observed_continuation": 16,
    }
    if prios != expected_prios:
        errors.append(f"high priority review paths must total 14 and 2: {prios}")
    trial = preflight_proposed_2026_draw(
        historical_nodes=historical_nodes,
        historical_edges=historical_edges,
        matches=(),
        arrows=(),
    )
    if trial.candidate_match_count or trial.candidate_arrow_count or trial.runtime_enabled:
        errors.append("empty manual candidate proof must not unlock official draw")
    return {
        "ok": not errors,
        "errors": errors,
        "official_number_review_tasks": len(numbers),
        "official_arrow_review_tasks": len(arrows),
        "high_priority": dict(prios),
        "historical_fixture_count": len(historical_nodes),
        "historical_continuation_count": len(historical_edges),
        "official_match_numbers_independently_verified": 0,
        "official_individual_arrows_independently_verified": 0,
        "official_pdf_bytes_acquired": False,
        "annual_loser_rule_verified": False,
        "live_fmt025_runtime_changed": False,
    }
