"""Stage13E-3G-26: year-flexible Hiroshima qualifier *macro* sandbox.

The official 2026 autumn west overview confirms A/B second-place direct
qualification and a C/D second-place play-in. It does not establish an
annual-independent draw, pairings, or first-loss forwarding selector.

This pure opt-in prototype: (1) creates stable seeded *draft* zone rosters
without making official drawings, and (2) checks externally supplied zone
winners against a declared berth-count template. It never creates matches,
derives losers' round placements, enables FMT025, or grants ranking games.
"""
from __future__ import annotations

from dataclasses import dataclass
from .hiroshima_annual_zone_draft import (
    DraftZoneAllocation, ZoneDraftError, make_balanced_zone_draft,
)


class MacroDraftError(ValueError):
    """Invalid hypothetical macro plan or externally supplied result."""


@dataclass(frozen=True)
class MacroTemplate:
    zone_codes: tuple[str, ...]
    direct_second_place_zones: tuple[str, ...]
    cross_second_place_pairs: tuple[tuple[str, str], ...]
    source_scope: str = "sandbox_template_not_general_official_federation_rule"


@dataclass(frozen=True)
class MacroDraft:
    allocation: DraftZoneAllocation
    template: MacroTemplate
    direct_main_entry_ids: tuple[str, ...]
    qualifier_slots: int
    total_main_entry_slots: int
    proof_scope: str = "year_independent_draft_mechanics_2026_macro_as_example"
    official_annual_draw_verified: bool = False
    official_loser_selector_verified: bool = False
    match_level_pairings_generated: bool = False
    live_fmt025_runtime_enabled: bool = False
    optional_ranking_enabled: bool = False


@dataclass(frozen=True)
class MacroAwardResult:
    qualifier_ids: tuple[str, ...]
    direct_main_entry_ids: tuple[str, ...]
    all_main_entry_ids: tuple[str, ...]
    cross_gate_winners: tuple[tuple[tuple[str, str], str], ...]
    source_scope: str = "externally_declared_zone_and_cross_winners_no_match_generation"
    live_fmt025_runtime_enabled: bool = False


WEST_2026_OBSERVED_MACRO_EXAMPLE = MacroTemplate(
    zone_codes=("A", "B", "C", "D"),
    direct_second_place_zones=("A", "B"),
    cross_second_place_pairs=(("C", "D"),),
    source_scope="official_2026_west_macro_observed_not_2027_regulation",
)


def validate_macro_template(template: MacroTemplate) -> int:
    """Validate complete allocation of one hypothetical runnerup per zone.

    Every zone grants one primary berth. Every runnerup participates in
    exactly one direct award or in one two-zone cross-gate match.
    No optional ranking fixture, double-entry, or unassigned runnerup.
    """
    zones = template.zone_codes
    if (not zones or len(set(zones)) != len(zones)
            or any(not isinstance(x, str) or len(x) != 1 or x not in "ABCDEF" for x in zones)
            or zones != tuple(sorted(zones))):
        raise MacroDraftError("unique, sorted named zones A-F required")
    direct = template.direct_second_place_zones
    if len(set(direct)) != len(direct) or any(x not in zones for x in direct):
        raise MacroDraftError("second-place direct zones must be unique and included")
    paired: list[str] = []
    for pair in template.cross_second_place_pairs:
        if (not isinstance(pair, tuple) or len(pair) != 2 or pair[0] == pair[1]
                or any(z not in zones for z in pair) or pair != tuple(sorted(pair))):
            raise MacroDraftError("cross gate requires two distinct sorted existing zones")
        paired.extend(pair)
    if (len(set(paired)) != len(paired)
            or set(direct).intersection(paired)
            or set(direct).union(paired) != set(zones)):
        raise MacroDraftError("every second-place zone must have exactly one exit")
    if template.source_scope not in (
        "official_2026_west_macro_observed_not_2027_regulation",
        "sandbox_template_not_general_official_federation_rule",
    ):
        raise MacroDraftError("no asserted future official rule or live integration")
    return len(zones) + len(direct) + len(template.cross_second_place_pairs)


def draft_qualification_macro(
    *, entrant_ids: tuple[str, ...], template: MacroTemplate, seed: str,
    direct_main_entry_ids: tuple[str, ...] = (),
) -> MacroDraft:
    """Prepare the *shape* of a fictional draw; do not schedule any games."""
    slots = validate_macro_template(template)
    try:
        allocation = make_balanced_zone_draft(
            entrant_ids=entrant_ids,
            zone_codes=template.zone_codes,
            seed=seed,
            direct_main_school_ids=direct_main_entry_ids,
        )
    except ZoneDraftError as exc:
        raise MacroDraftError(str(exc)) from exc
    # A zone needs at least a champion and a separate runnerup.
    if any(len(members) < 2 for _, members in allocation.zone_school_ids):
        raise MacroDraftError("two or more entrants per zone required for a runnerup")
    return MacroDraft(
        allocation=allocation,
        template=template,
        direct_main_entry_ids=tuple(direct_main_entry_ids),
        qualifier_slots=slots,
        total_main_entry_slots=slots + len(direct_main_entry_ids),
    )


def evaluate_declared_macro_awards(
    plan: MacroDraft,
    *, primary_winners: dict[str, str],
    second_place_winners: dict[str, str],
    cross_gate_winners: dict[tuple[str, str], str],
) -> MacroAwardResult:
    """Check *supplied* champion/runnerup outcomes; do not invent games.

    In particular the caller must determine each second-place candidate
    from separate independently supported match results. This function
    never infers which primary loser enters which second-place pairing.
    """
    if (plan.live_fmt025_runtime_enabled or plan.official_annual_draw_verified
            or plan.official_loser_selector_verified or plan.optional_ranking_enabled
            or plan.match_level_pairings_generated):
        raise MacroDraftError("a sandbox macro draft cannot claim official draw or runtime")
    quota = validate_macro_template(plan.template)
    buckets = plan.allocation.as_dict()
    if (set(buckets) != set(plan.template.zone_codes)
            or len(set(e for xs in buckets.values() for e in xs))
            != sum(len(xs) for xs in buckets.values())
            or any(len(xs) < 2 for xs in buckets.values())):
        raise MacroDraftError("zone allocation must be unique and contain runnerups")
    if (plan.qualifier_slots != quota or
            plan.total_main_entry_slots != quota + len(plan.direct_main_entry_ids) or
            plan.allocation.annual_draw_verified or plan.allocation.runtime_enabled):
        raise MacroDraftError("unverified macro quota or official draw flag changed")
    zones = set(plan.template.zone_codes)
    pairs = set(plan.template.cross_second_place_pairs)
    if (set(primary_winners) != zones
            or set(second_place_winners) != zones
            or set(cross_gate_winners) != pairs):
        raise MacroDraftError("all externally chosen primary/runnerup/cross outcomes required")

    primary: list[str] = []
    runners: dict[str, str] = {}
    for zone in plan.template.zone_codes:
        available = set(buckets[zone])
        first, second = primary_winners[zone], second_place_winners[zone]
        if first == second or first not in available or second not in available:
            raise MacroDraftError(f"primary and runnerup must be distinct zone entrants: {zone}")
        primary.append(first)
        runners[zone] = second
    winners: list[str] = []
    cross_details = []
    for zone in plan.template.direct_second_place_zones:
        winners.append(runners[zone])
    for pair in plan.template.cross_second_place_pairs:
        chosen = cross_gate_winners[pair]
        if chosen not in {runners[pair[0]], runners[pair[1]]}:
            raise MacroDraftError(f"cross winner is not supplied zone runnerup: {pair}")
        winners.append(chosen)
        cross_details.append((pair, chosen))
    qualified = tuple(primary + winners)
    all_entrants = qualified + plan.direct_main_entry_ids
    if (len(qualified) != quota or len(set(all_entrants)) != len(all_entrants)
            or len(all_entrants) != plan.total_main_entry_slots):
        raise MacroDraftError("main berth quota/double award violation")
    return MacroAwardResult(
        qualifier_ids=qualified,
        direct_main_entry_ids=plan.direct_main_entry_ids,
        all_main_entry_ids=all_entrants,
        cross_gate_winners=tuple(cross_details),
    )
