"""2026 Hiroshima four-district spring/autumn qualification-route audit.

The source indexes 87 *sub-tournaments*, NOT 87 matches. Their 1st/2nd
place labels describe a route to a berth, not proof that teams in every
match have already qualified. In the absence of a documented pair of
pre-qualified participants, never construct an optional ranking sidecar.
"""
from __future__ import annotations

import csv
from collections import Counter
from datetime import date
from pathlib import Path

from .ranking_reference_2026 import load_2026_ranking_observations
from .ranking_school_reconciliation_2026 import load_ranking_school_mapping_2026


ROUTE_PATH = "competitions/2026/hiroshima_district_qualification_routes.csv"
EXAMPLE_PATH = "competitions/2026/hiroshima_qualification_examples.csv"
DISTRICTS = ("west", "north", "south", "east")
SEASONS = {"spring": "CMP000135", "autumn": "CMP000136"}
EXPECTED_ROUTE_COUNTS = {
    ("spring", "west"): 9,
    ("spring", "north"): 10,
    ("spring", "south"): 15,
    ("spring", "east"): 9,
    ("autumn", "west"): 9,
    ("autumn", "north"): 10,
    ("autumn", "south"): 16,
    ("autumn", "east"): 9,
}
KINDS = {
    "first_place_berth_path",
    "second_place_berth_path",
    "cross_zone_berth_decider",
}


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as reader:
        return list(csv.DictReader(reader))


def load_2026_hiroshima_qualification_routes(data_dir: str | Path) -> list[dict]:
    return _csv(Path(data_dir) / ROUTE_PATH)


def audit_2026_hiroshima_qualification_routes(data_dir: str | Path) -> dict:
    """Verify named route inventory, source scope, quotas and known match guards.

    This does not assert that every individual spring/autumn match was
    exhaustively examined. Only the named route inventory is complete.
    """
    root = Path(data_dir)
    routes = load_2026_hiroshima_qualification_routes(root)
    examples = _csv(root / EXAMPLE_PATH)
    stage_groups = {
        group["stage_group_id"]: group
        for group in _csv(root / "competitions/competition_stage_groups.csv")
    }
    references = {
        r["reference_id"]: r
        for r in load_2026_ranking_observations(root)
    }
    mappings = {
        r["reference_id"]: r
        for r in load_ranking_school_mapping_2026(root)
    }
    errors: list[str] = []
    names = set()
    ids = set()
    counts: Counter[tuple[str, str]] = Counter()
    kinds: Counter[str] = Counter()
    observed_group_by_district = {}
    for row in routes:
        rid = row["route_id"]
        season, district, cid = (
            row["season"], row["district_code"], row["competition_id"]
        )
        ident = (season, district, row["sub_tournament_name"])
        if not rid or rid in ids or ident in names:
            errors.append(f"{rid}: duplicated ID or regional route name")
        ids.add(rid)
        names.add(ident)
        if season not in SEASONS or cid != SEASONS.get(season):
            errors.append(f"{rid}: season/competition mismatch")
        if district not in DISTRICTS:
            errors.append(f"{rid}: unsupported district")
        group = stage_groups.get(row["stage_group_id"])
        if not group or group["competition_id"] != cid or (
            district not in ("west", "north", "south", "east")
            or row["district_name"] not in group["group_name"]
        ):
            errors.append(f"{rid}: stage group does not match region/season")
        old_group = observed_group_by_district.setdefault(
            (season, district), row["stage_group_id"]
        )
        if old_group != row["stage_group_id"]:
            errors.append(f"{rid}: mixed group IDs for same region")
        try:
            start = date.fromisoformat(row["first_calendar_day"])
            end = date.fromisoformat(row["last_calendar_day"])
            min_day, max_day = (
                (date(2026, 3, 21), date(2026, 4, 12))
                if season == "spring" else
                (date(2026, 8, 22), date(2026, 9, 13))
            )
            if start > end or start < min_day or end > max_day:
                errors.append(f"{rid}: date range outside official bracket period")
        except ValueError:
            errors.append(f"{rid}: invalid date range")
        kind = row["route_kind"]
        label = row["sub_tournament_name"]
        if kind not in KINDS or (
            kind == "cross_zone_berth_decider"
            and "出場決定戦" not in label
        ) or (
            kind == "first_place_berth_path" and "一位校" not in label
        ) or (
            kind == "second_place_berth_path"
            and ("二位校" not in label or "出場決定戦" in label)
        ):
            errors.append(f"{rid}: route title and role inconsistent")
        if row["qualification_effect"] != "qualification_sensitive":
            errors.append(f"{rid}: ranking-only route cannot be inferred")
        if row["verification_scope"] != "bracket_level_only":
            errors.append(f"{rid}: no individual-match exhaustive proof")
        if not row["bracket_source_url"].startswith("https://") or (
            not row["federation_source_url"].startswith("https://")
        ):
            errors.append(f"{rid}: missing HTTPS provenance")
        counts[(season, district)] += 1
        kinds[kind] += 1
    if set(counts) != set(EXPECTED_ROUTE_COUNTS) or dict(counts) != EXPECTED_ROUTE_COUNTS:
        errors.append(f"district route counts differ: {dict(counts)}")
    if len(routes) != 87:
        errors.append(f"expected 87 sub-tournament routes; got {len(routes)}")
    slot_counts = {}
    for season, cid in SEASONS.items():
        slots = {}
        for district in DISTRICTS:
            group_id = observed_group_by_district.get((season, district))
            group = stage_groups.get(group_id)
            if group is None:
                errors.append(f"{season}/{district}: missing stage quota")
                continue
            slots[district] = int(group["advance_slots_to_next"])
        slot_counts[season] = slots
        if sum(slots.values()) != 32:
            errors.append(f"{season}: group qualification quota is not 32")
    if slot_counts.get("autumn") != {
        "west": 7, "north": 6, "south": 10, "east": 9
    }:
        errors.append("autumn district berths differ from federation rules")

    seen_refs = set()
    for row in examples:
        ref = row["example_id"]
        if not ref or ref in seen_refs:
            errors.append(f"duplicate named qualifying match: {ref}")
        seen_refs.add(ref)
        if row["competition_id"] not in SEASONS.values() or (
            row["district_code"] not in DISTRICTS
        ):
            errors.append(f"{ref}: invalid season/district")
        if row["qualification_effect"] != "qualifier_effect":
            errors.append(f"{ref}: qualification game misclassified as optional")
        if not row["source_url"].startswith("https://"):
            errors.append(f"{ref}: missing provenance")
        try:
            score1 = int(row["team1_score"])
            score2 = int(row["team2_score"])
            if score1 == score2 or score1 < 0 or score2 < 0:
                raise ValueError("bad score")
            if row["winner_name"] != (
                row["team1_name"] if score1 > score2 else row["team2_name"]
            ):
                errors.append(f"{ref}: winner and score disagree")
            date.fromisoformat(row["match_date"])
        except ValueError:
            errors.append(f"{ref}: invalid date/scores")
        if row["prior_reference_id"]:
            actual = references.get(row["prior_reference_id"])
            mapping = mappings.get(row["prior_reference_id"])
            if not actual or not mapping or actual["reference_classification"] != (
                "qualification_decider_not_ranking"
            ) or mapping["mapping_status"] != "excluded_qualification_decider":
                errors.append(f"{ref}: known qualification match not protected")
            elif (actual["competition_id"] != row["competition_id"]
                  or actual["match_date"] != row["match_date"]
                  or actual["team1_name"] != row["team1_name"]
                  or actual["team2_name"] != row["team2_name"]):
                errors.append(f"{ref}: past reference does not match fixture")

    # Season/source roll-up: an optional ranking label is NOT an automatic
    # license to issue a match after qualifications have been finalized.
    return {
        "ok": not errors, "errors": errors,
        "year": 2026,
        "district_season_count": len(EXPECTED_ROUTE_COUNTS),
        "sub_tournament_route_count": len(routes),
        "region_route_counts": {
            f"{season}_{district}": counts[(season, district)]
            for season in SEASONS for district in DISTRICTS
        },
        "route_kind_counts": dict(kinds),
        "berth_slots": slot_counts,
        "named_qualification_match_count": len(examples),
        "optional_ranking_matches_registered": 0,
        "matching_scope": "bracket_level_inventory_plus_named_qualification_examples",
        "full_match_by_match_berth_state_audit_pending": True,
    }
