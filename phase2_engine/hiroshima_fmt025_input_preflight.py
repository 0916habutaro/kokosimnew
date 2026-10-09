"""Stage 13E-3G-32: versioned, fail-closed FMT025 admission preflight.

This is a READ-ONLY adapter between manually supplied explicit-match graphs
and Stage31's sandbox replay. It does not run the tournament scheduler,
create draws, admit self-certified official proof, or release rankings.
The only historical fixture source supported is the checked-in secondary
2026 Hiroshima autumn-west ledger; it is not an officially proven draw.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .hiroshima_explicit_match_dag_sandbox import (
    ExplicitMatch, ExplicitMatchReplayError, replay_explicit_match_dag,
)
from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g25 import NODES_FILE, EDGES_FILE
from .hiroshima_stage13e3g31 import replay_stage25_historical_observations

VERSION = "fmt025-explicit-input-v1"
SANDBOX = "fictional_inline"
HISTORICAL = "stage25_2026_west_secondary"
BLOCK_REASON = "official_annual_draw_and_transfer_evidence_not_independently_approved"
ROUTE_LOCK_FILE = "competitions/2026/hiroshima_fmt025_input_release_locks_stage13e3g32.csv"
ALLOWED_TOP_FIELDS = frozenset((
    "contract_version", "source_kind", "execution_intent", "format_model_id",
    "year", "season", "district_code", "stage_group_id", "qualifier_slots",
    "entrant_ids", "direct_main_entry_ids", "matches", "winners_by_match",
    "official_draw_verified", "official_loser_selector_verified",
    "release_approved", "optional_ranking_requested",
))
MATCH_FIELDS = frozenset((
    "match_id", "phase", "left_source", "right_source", "winner_to_match",
    "loser_to_match", "winner_awards_berth", "loser_retry_authorized",
))


class Fmt025PreflightError(ValueError):
    """No activation on invalid provenance, schema or proposed match edges."""


@dataclass(frozen=True)
class Fmt025PreflightResult:
    payload_sha256: str
    source_kind: str
    match_count: int
    first_entry_count: int
    transfer_count: int
    qualifier_count: int
    direct_exemption_count: int
    qualifiers: tuple[str, ...]
    evidence_grade: str
    accepted_for_read_only_preview: bool = True
    authorized_for_live_fmt025: bool = False
    optional_ranking_allowed: bool = False
    full_official_draw_verified: bool = False
    release_block_reason: str = BLOCK_REASON


def _exact_object(obj: Any, fields: frozenset[str], description: str) -> dict:
    if not isinstance(obj, dict) or set(obj) != fields:
        raise Fmt025PreflightError(
            f"{description} needs exactly the versioned fields; missing/unknown claims forbidden"
        )
    return obj


def _strings(seq: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(seq, list) or (not seq and not allow_empty):
        raise Fmt025PreflightError(f"{field} must be a list of IDs")
    if len(seq) > 2000 or any(not isinstance(s, str) or not s or ":" in s for s in seq):
        raise Fmt025PreflightError(f"{field} contains invalid ID or exceeds limit")
    if len(set(seq)) != len(seq):
        raise Fmt025PreflightError(f"{field} contains duplicate IDs")
    return tuple(seq)


def _matches(value: Any) -> tuple[ExplicitMatch, ...]:
    if not isinstance(value, list) or len(value) > 2000:
        raise Fmt025PreflightError("matches must be a bounded list")
    parsed = []
    for obj in value:
        m = _exact_object(obj, MATCH_FIELDS, "match")
        for key in ("match_id", "phase", "left_source", "right_source"):
            if not isinstance(m[key], str) or not m[key]:
                raise Fmt025PreflightError(f"match {key} must be a nonempty string")
        for key in ("winner_to_match", "loser_to_match"):
            if m[key] is not None and (not isinstance(m[key], str) or not m[key]):
                raise Fmt025PreflightError(f"match {key} must be an ID or null")
        for key in ("winner_awards_berth", "loser_retry_authorized"):
            if type(m[key]) is not bool:
                raise Fmt025PreflightError(f"match {key} must be boolean")
        parsed.append(ExplicitMatch(**m))
    return tuple(parsed)


def _winners(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > 2000:
        raise Fmt025PreflightError("winners_by_match must be a bounded object")
    if any(not isinstance(k,str) or not k or
           not isinstance(v,str) or not v for k,v in value.items()):
        raise Fmt025PreflightError("winner keys and school IDs must be nonempty strings")
    return value


def load_preflight_payload_json(text: str) -> dict:
    """Reject duplicate JSON keys before validating contract fields."""
    def no_duplicate_keys(pairs):
        result = {}
        for key,value in pairs:
            if key in result:
                raise Fmt025PreflightError("JSON has a duplicate key")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=no_duplicate_keys,
                          parse_constant=lambda v: (_ for _ in ()).throw(
                              Fmt025PreflightError(f"non-JSON numeric value: {v}")))
    except (ValueError, TypeError) as exc:
        raise Fmt025PreflightError("invalid JSON for preflight") from exc


def preflight_fmt025_input(payload: dict, *, data_dir: str | Path | None = None) -> Fmt025PreflightResult:
    p = _exact_object(payload, ALLOWED_TOP_FIELDS, "FMT025 input")
    if (p["contract_version"] != VERSION or p["format_model_id"] != "FMT025"
            or p["execution_intent"] != "read_only_preflight"):
        raise Fmt025PreflightError("unknown schema/version or live execution requested")
    # These are not authoritative even if the caller sets them to True:
    for key in ("official_draw_verified", "official_loser_selector_verified",
                "release_approved", "optional_ranking_requested"):
        if type(p[key]) is not bool or p[key]:
            raise Fmt025PreflightError(f"{key} cannot be authorized by submitted data")
    if type(p["qualifier_slots"]) is not int or not 1 <= p["qualifier_slots"] <= 2000:
        raise Fmt025PreflightError("bounded integer qualifier_slots required")
    entrants = _strings(p["entrant_ids"], "entrant_ids", allow_empty=True)
    direct = _strings(p["direct_main_entry_ids"], "direct_main_entry_ids", allow_empty=True)
    plans = _matches(p["matches"])
    winners = _winners(p["winners_by_match"])
    if not isinstance(p["source_kind"], str):
        raise Fmt025PreflightError("known source kind required")
    if p["source_kind"] == SANDBOX:
        if (p["year"] is not None or p["season"] is not None
                or p["district_code"] is not None or p["stage_group_id"] != "SANDBOX"
                or data_dir is not None):
            raise Fmt025PreflightError("fictional preview cannot claim an annual official fixture")
        if not entrants or not plans:
            raise Fmt025PreflightError("fictional preview requires all explicit entrants/matches")
        evidence_grade = "fictional_school_ids_no_official_basis"
        try:
            output = replay_explicit_match_dag(
                entrant_ids=entrants, matches=plans, winners_by_match=winners,
                qualifier_slots=p["qualifier_slots"], direct_main_entry_ids=direct,
            )
        except ExplicitMatchReplayError as exc:
            raise Fmt025PreflightError(str(exc)) from exc
    elif p["source_kind"] == HISTORICAL:
        if (p["year"] != 2026 or type(p["year"]) is not int
                or p["season"] != "autumn" or p["district_code"] != "west"
                or p["stage_group_id"] != "SGR000144" or p["qualifier_slots"] != 7):
            raise Fmt025PreflightError("historical fixture identity or quota does not match Stage25")
        if entrants or direct or plans or winners:
            raise Fmt025PreflightError("history must be resolved from checked-in Stage25 ledger, not caller-supplied")
        if data_dir is None:
            raise Fmt025PreflightError("historical inspection requires an explicit data directory")
        try:
            nodes = _read(Path(data_dir), NODES_FILE)
            edges = _read(Path(data_dir), EDGES_FILE)
            output = replay_stage25_historical_observations(nodes, edges)
        except (ExplicitMatchReplayError, KeyError, ValueError) as exc:
            raise Fmt025PreflightError("historical 25/32 source replay failed") from exc
        evidence_grade = "observed_secondary_results_not_official_drawing"
    else:
        raise Fmt025PreflightError("unrecognized or unsupported source kind")

    # Stable audit checksum binds *all caller-provided fields*, not an official proof.
    digest = hashlib.sha256(json.dumps(
        p, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return Fmt025PreflightResult(
        payload_sha256=digest,
        source_kind=p["source_kind"],
        match_count=len(output.match_traces),
        first_entry_count=len(output.consumed_initial_entrant_ids),
        transfer_count=output.consumed_declared_outcome_transfers,
        qualifier_count=len(output.qualifier_ids),
        direct_exemption_count=len(output.direct_main_entry_ids),
        qualifiers=output.qualifier_ids,
        evidence_grade=evidence_grade,
    )


def require_live_fmt025_release(preflight: Fmt025PreflightResult) -> None:
    """Explicit integration boundary: Stage32 has NO production release path."""
    if not isinstance(preflight, Fmt025PreflightResult):
        raise Fmt025PreflightError("typed, reviewed preflight is required")
    raise Fmt025PreflightError(
        "FMT025 remains blocked: source authenticity, individual draws, "
        "loser transfers and independent annual release approval unproven"
    )
