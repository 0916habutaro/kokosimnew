"""Read-only, deterministic per-match stat filters and ordering.

This is a VIEW projection, not a stored aggregation or an archive rewrite.
It never fills missing box-score fields with fabricated numbers.
"""
from __future__ import annotations

SECTIONS = ("all", "inning_scores", "team_stats", "batter_stats", "pitcher_stats")
SORTS = ("saved", "player_id", "hits_desc", "strikeouts_desc")
STAT_SECTIONS = SECTIONS[1:]


def _metric(section: str, source: dict, order: str) -> int | float | None:
    if order == "hits_desc":
        key = "hits_allowed" if section == "pitcher_stats" else "hits"
    else:
        key = "strikeouts"
    value = source.get(key)
    if type(value) in (int, float) and value >= 0:
        return value
    return None


def match_stat_projection(
    page: dict, *, section: str = "all", school_id: str | None = None,
    sort: str = "saved", offset: int = 0, limit: int = 80,
) -> dict:
    """Select recorded rows, then filter/sort/page without source mutation.

    A school filter is restricted to the two actual match participants; player
    identity and school are never inferred from display names or roster slots.
    The original insertion order is stable for ties and missing metrics.
    """
    if (page.get("screen") != "cross_era_match"
            or section not in SECTIONS or sort not in SORTS
            or type(offset) is not int or offset < 0
            or type(limit) is not int or not 1 <= limit <= 100):
        raise ValueError("invalid saved match table request")
    match = page["match"]
    allowed_schools = (match["team1_id"], match["team2_id"])
    if school_id is not None and school_id not in allowed_schools:
        raise ValueError("match school filter must be a participant")

    entries = []
    for kind in STAT_SECTIONS:
        if section != "all" and section != kind:
            continue
        source_rows = page["details"].get(kind)
        if source_rows is None:
            continue
        for item in source_rows:
            if not isinstance(item, dict):
                raise ValueError("malformed saved stat row")
            team = (
                item.get("batting_team_id") if kind == "inning_scores"
                else item.get("school_id")
            )
            if school_id is not None and team != school_id:
                continue
            entries.append({
                "section": kind, "school_id": team, "saved": item,
            })

    if sort == "player_id":
        # Missing player IDs last. Stable sort keeps the original row order
        # for the same immutable identifier; no player names are used.
        entries.sort(key=lambda r: (
            type(r["saved"].get("player_id")) is not str
            or not r["saved"].get("player_id"),
            str(r["saved"].get("player_id") or "").casefold(),
        ))
    elif sort in ("hits_desc", "strikeouts_desc"):
        entries.sort(key=lambda r: (
            _metric(r["section"], r["saved"], sort) is None,
            -(_metric(r["section"], r["saved"], sort) or 0),
        ))

    return {
        "total": len(entries),
        "offset": offset,
        "limit": limit,
        "rows": entries[offset:offset + limit],
        "section": section,
        "school_id": school_id,
        "sort": sort,
        "original_archive_modified": False,
        "unrecorded_values_inferred": False,
    }
