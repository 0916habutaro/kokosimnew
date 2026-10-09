"""2026 Hiroshima: year-independent *draft* zone grouping contract.

The zone NAMES in the published child events are known; the annual school
draw and exact loser/cross-zone entry edges are not. This module can make
a reproducible balanced SANDBOX DRAFT for arbitrary entrant IDs, not an
official draw and not a FMT025 live runtime plan.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


class ZoneDraftError(ValueError):
    """An invalid or deceptively official annual zone draft."""


@dataclass(frozen=True)
class DraftZoneAllocation:
    zone_school_ids: tuple[tuple[str, tuple[str, ...]], ...]
    proof_scope: str = "seeded_draft_not_official_bracket"
    annual_draw_verified: bool = False
    runtime_enabled: bool = False

    def as_dict(self) -> dict[str, tuple[str, ...]]:
        return dict(self.zone_school_ids)


def make_balanced_zone_draft(
    *,
    entrant_ids: tuple[str, ...],
    zone_codes: tuple[str, ...],
    seed: str,
    direct_main_school_ids: tuple[str, ...] = (),
) -> DraftZoneAllocation:
    """Return stable reproducible sandbox buckets, never a real season draw.

    IDs can be fictional and joint-team IDs count as one entrant. The caller
    must provide exactly the named zones, and cannot ask for a definitive
    bracket or the draw-dependent repechage transfer edges.
    """
    if not isinstance(seed,str) or not seed:
        raise ZoneDraftError("nonempty explicit draft seed required")
    if (not zone_codes or len(set(zone_codes))!=len(zone_codes)
        or any(not isinstance(z,str) or len(z)!=1 or z not in "ABCDEF" for z in zone_codes)
        or tuple(sorted(zone_codes))!=tuple(zone_codes)):
        raise ZoneDraftError("zone codes must be unique sorted named A-F letters")
    if (not entrant_ids or any(not isinstance(s,str) or not s for s in entrant_ids)
        or len(entrant_ids)<len(zone_codes)
        or len(set(entrant_ids))!=len(entrant_ids)):
        raise ZoneDraftError("unique nonempty entrants must cover all published zones")
    if (len(set(direct_main_school_ids))!=len(direct_main_school_ids)
        or any(not isinstance(s,str) or not s for s in direct_main_school_ids)
        or set(entrant_ids).intersection(direct_main_school_ids)):
        raise ZoneDraftError("direct MAIN entries must be distinct from qualifier entrants")

    # Ranking by digest, not Python's process-randomized hash().
    ranked=sorted(
        entrant_ids,
        key=lambda s:(hashlib.sha256((seed+"\0"+s).encode("utf-8")).hexdigest(),s),
    )
    buckets={zone:[] for zone in zone_codes}
    for i, entrant in enumerate(ranked):
        buckets[zone_codes[i%len(zone_codes)]].append(entrant)
    return DraftZoneAllocation(tuple(
        (zone,tuple(buckets[zone])) for zone in zone_codes
    ))
