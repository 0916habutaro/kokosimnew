"""Stage13E-3G-21: independent evidence submission shape and review guard.

Even a syntactically complete packet is NOT official-document verification,
nor a license to enable FMT025. Actual document content, provenance and
draw topology need independent human/source review before any code wiring.
"""
from __future__ import annotations

from dataclasses import dataclass


class RouteProofError(ValueError):
    pass


@dataclass(frozen=True)
class ProposedRouteEvidence:
    evidence_key: str
    source_kind: str
    document_ref: str
    pinpoint_location: str
    season_year: str
    supplied_document_body_reviewed: bool = False


@dataclass(frozen=True)
class RouteEvidenceReview:
    route_id: str
    missing_evidence_keys: tuple[str, ...]
    unsupported_evidence_keys: tuple[str, ...]
    structurally_complete_for_manual_review: bool
    source_content_independently_verified: bool = False
    actual_game_runtime_enabled: bool = False
    optional_ranking_enabled: bool = False


_ALLOWED_DOCUMENT_CLASSES = frozenset((
    "federation_bracket_draw",
    "federation_published_regulations",
))
_ALLOWED_KEYS = frozenset((
    "annual_entrant_zone_assignment",
    "official_primary_bracket_pairings",
    "primary_loser_round_to_secondary_selector",
    "secondary_zone_bracket_pairings",
    "runnerup_gate_candidate_selector",
    "conditional_loser_retry_selector",
    "cross_zone_bracket_pairings",
))


def review_proposed_annual_route_evidence(
    *,
    route_id: str,
    required_keys: tuple[str, ...],
    supplied_evidence: tuple[ProposedRouteEvidence, ...],
    season_year: str,
) -> RouteEvidenceReview:
    """Review only packet *shape*; never authorize FMT025 or infer edges.

    Requirements are derived from the separate 87-route public-name ledger.
    History of 2026 game participation and the published tournament event
    *titles* cannot substitute for readable federation bracket/rule content.
    """
    if not route_id or not season_year:
        raise RouteProofError("route ID and year required")
    if (not required_keys or len(set(required_keys))!=len(required_keys)
        or any(k not in _ALLOWED_KEYS for k in required_keys)):
        raise RouteProofError("unknown or duplicate required routing evidence key")
    names=[x.evidence_key for x in supplied_evidence]
    if len(names)!=len(set(names)):
        raise RouteProofError("duplicate submitted annual evidence key")
    if any(k not in _ALLOWED_KEYS for k in names):
        raise RouteProofError("unknown submitted annual evidence key")
    if any(k not in required_keys for k in names):
        raise RouteProofError("unrequested evidence key is not allowed")

    missing=[]
    unsupported=[]
    indexed={x.evidence_key:x for x in supplied_evidence}
    for key in required_keys:
        record=indexed.get(key)
        if record is None:
            missing.append(key)
        elif (
            record.source_kind not in _ALLOWED_DOCUMENT_CLASSES
            or not record.document_ref.strip()
            or not record.pinpoint_location.strip()
            or record.season_year not in (season_year,"year_independent")
            or not record.supplied_document_body_reviewed
        ):
            # Example: SportsOnline title, secondary result, invented/undated
            # external evidence, or a federation URL whose PDF body was not read.
            unsupported.append(key)
    return RouteEvidenceReview(
        route_id=route_id,
        missing_evidence_keys=tuple(missing),
        unsupported_evidence_keys=tuple(unsupported),
        structurally_complete_for_manual_review=not missing and not unsupported,
    )
