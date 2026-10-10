"""Stage 43D: validate a year-end boundary without inventing future seasons."""
from __future__ import annotations

from datetime import date


class YearTransitionBlockedError(ValueError):
    """Live season has unfinished or unresolved work and cannot be sealed."""


def year_end_readiness(state) -> dict:
    """Evaluate one currently instantiated season, without progressing games.

    A true result permits sealing the current year's *match archive*. It does
    not assert that a later year's rosters or competition rules are available.
    """
    year = state.year
    if not isinstance(year, int) or isinstance(year, bool) or year < 1:
        raise ValueError("invalid runtime year")
    summary = state.summary()
    blockers: list[str] = []
    if state.current_date != date(year, 12, 31):
        blockers.append("current_date_not_year_end")

    status_by_competition = getattr(state, "status_by_competition", None)
    if status_by_competition is None:
        blockers.append("dependency_completion_state_unavailable")
        total = 0
        unfinished = []
    else:
        total = len(status_by_competition)
        unfinished = sorted(
            cid for cid, status in status_by_competition.items()
            if status != "completed"
        )
        if not total:
            blockers.append("no_registered_competitions")
        if unfinished:
            blockers.append("unfinished_or_blocked_competitions")

    scheduled_competitions = getattr(state, "competitions", {})
    calendar_gap_count = sum(
        int(scheduled.summary().get("calendar_gap_count", 0))
        for scheduled in scheduled_competitions.values()
    )
    pending_match_count = sum(
        int(scheduled.summary().get("pending_match_count", 0))
        for scheduled in scheduled_competitions.values()
    )
    if calendar_gap_count:
        blockers.append("calendar_gaps_present")
    if pending_match_count:
        blockers.append("scheduled_matches_pending")
    if total and len(scheduled_competitions) < total:
        blockers.append("not_all_competitions_activated")

    completed_results = state.completed_results()
    return {
        "year": year,
        "next_year": year + 1,
        "eligible_to_seal": not blockers,
        "blockers": blockers,
        "unfinished_competition_ids": unfinished,
        "competition_count": total,
        "completed_match_count": len(completed_results),
        "calendar_gap_count": calendar_gap_count,
        "pending_match_count": pending_match_count,
        "current_date": state.current_date.isoformat(),
        "next_year_runtime_available": False,
        "note": (
            "Archive-sealing readiness only. Next year's calendar, rules, "
            "player continuity and runtime must be implemented separately."
        ),
    }


def require_year_end(state) -> dict:
    readiness = year_end_readiness(state)
    if not readiness["eligible_to_seal"]:
        raise YearTransitionBlockedError(
            "cannot seal incomplete season: " + ", ".join(readiness["blockers"])
        )
    return readiness
