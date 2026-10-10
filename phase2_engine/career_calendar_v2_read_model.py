"""Stage43G-26: strict read-only calendar-v2 / legacy Option-A match bridge.

Explicit fictional year plans are a SEPARATE provenance source. Never rewrite
legacy match_date or claim post-9999 gameplay is available. An absent/invalid
plan fails closed rather than displaying guesses or an "official" schedule.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path

from .career_calendar_v2 import (
    CareerCalendarV2Archive, GameDaySlot, SandboxCalendarConflict, SOURCE,
)
from .career_option_a_storage_profile import _read_only
from .career_era_calendar_contract import _year

MAX_PAGE = 100


class CareerCalendarV2MatchReadModel:
    """Date-by-date & year calendars, verified on original archive bytes."""

    def __init__(self, calendar_path: str | Path,
                 historical_matches_path: str | Path):
        self.calendar = CareerCalendarV2Archive(calendar_path)
        self.history_path = Path(historical_matches_path)

    def _plan(self, year: int) -> dict:
        _year(year)
        plan = self.calendar.read(year)
        if plan is None:
            raise SandboxCalendarConflict(
                "year has no explicitly approved fictional calendar"
            )
        return plan

    def _year_records(self, year: int, plan: dict) -> list[dict]:
        """Validate every source game in this year, even outside a page."""
        if not self.history_path.is_file():
            raise FileNotFoundError("original historical match archive absent")
        approved = {
            (competition, token)
            for competition, tokens in plan["competition_days"].items()
            for token in tokens
        }
        output = []
        with closing(_read_only(self.history_path)) as conn:
            for rec in conn.execute(
                "SELECT year,competition_id,match_id,match_date,"
                "team1_id,team2_id,team1_score,team2_score,"
                "record_sha256,payload_json FROM historical_matches "
                "WHERE year=? ORDER BY match_date,competition_id,match_id",
                (year,),
            ):
                (record_year, competition, match_id, match_date,
                 first_id, second_id, first_score, second_score,
                 digest, raw) = rec
                if hashlib.sha256(raw.encode("utf-8")).hexdigest() != digest:
                    raise SandboxCalendarConflict(
                        "archived A match checksum differs"
                    )
                try:
                    game = json.loads(raw)
                except (TypeError, ValueError) as exc:
                    raise SandboxCalendarConflict(
                        "archived A match payload unreadable"
                    ) from exc
                if (not isinstance(game, dict)
                        or (game.get("year"), game.get("competition_id"),
                            game.get("match_id"), game.get("match_date"),
                            game.get("team1_id"), game.get("team2_id"),
                            game.get("team1_score"), game.get("team2_score"))
                        != (record_year, competition, match_id, match_date,
                            first_id, second_id, first_score, second_score)):
                    raise SandboxCalendarConflict(
                        "archived A match row/payload identity differs"
                    )
                try:
                    slot = GameDaySlot.from_iso(match_date)
                except ValueError as exc:
                    raise SandboxCalendarConflict(
                        "legacy archive date unsupported by v2 read model"
                    ) from exc
                if (slot.year != year
                        or (competition, slot.token) not in approved):
                    raise SandboxCalendarConflict(
                        "archived match date outside saved fictional calendar"
                    )
                output.append({
                    "game_day_token": slot.token,
                    "game_year": year,
                    "match_date_iso": match_date,
                    "competition_id": competition,
                    "match_id": match_id,
                    "team1_id": first_id, "team2_id": second_id,
                    "team1_score": first_score,
                    "team2_score": second_score,
                    "winner_id": game.get("winner_id"),
                    "record_sha256": digest,
                    "source_kind": SOURCE,
                })
        return output

    def year_dates(self, year: int) -> dict:
        """All approved days, even those without a played match."""
        plan = self._plan(year)
        games = self._year_records(year, plan)
        by_day = {}
        for competition, tokens in plan["competition_days"].items():
            for token in tokens:
                day = by_day.setdefault(token, {
                    "game_day_token": token, "game_year": year,
                    "gregorian_iso_date": GameDaySlot.from_token(
                        token
                    ).iso_date,
                    "approved_competition_ids": [],
                    "archived_match_count": 0,
                })
                day["approved_competition_ids"].append(competition)
        for game in games:
            by_day[game["game_day_token"]]["archived_match_count"] += 1
        return {
            "screen": "fictional_calendar_year",
            "game_year": year,
            "days": [by_day[token] for token in sorted(
                by_day, key=lambda value: GameDaySlot.from_token(value)
            )],
            "archived_match_count": len(games),
            "source_kind": SOURCE,
            "official_schedule_inferred": False,
            "legacy_match_date_rewritten": False,
            "post_9999_gameplay_supported": False,
        }

    def date_page(self, day_token: str, *,
                  competition_id: str | None = None,
                  limit: int = 50, offset: int = 0) -> dict:
        """Verified daily match results; filters and pages only after checks."""
        if (type(limit) is not int or not 1 <= limit <= MAX_PAGE
                or type(offset) is not int or offset < 0
                or (competition_id is not None
                    and (not isinstance(competition_id, str)
                         or not competition_id))):
            raise ValueError("invalid daily match page")
        slot = GameDaySlot.from_token(day_token)
        plan = self._plan(slot.year)
        listed = [
            comp for comp, days in plan["competition_days"].items()
            if day_token in days
        ]
        if not listed:
            raise SandboxCalendarConflict(
                "requested date not in saved fictional calendar"
            )
        if competition_id is not None and competition_id not in listed:
            raise SandboxCalendarConflict(
                "requested competition not scheduled for that day"
            )
        games = [
            game for game in self._year_records(slot.year, plan)
            if game["game_day_token"] == day_token
            and (competition_id is None
                 or game["competition_id"] == competition_id)
        ]
        return {
            "screen": "fictional_calendar_day",
            "game_year": slot.year,
            "game_day_token": day_token,
            "gregorian_iso_date": slot.iso_date,
            "competition_id": competition_id,
            "scheduled_competition_ids": listed,
            "rows": games[offset:offset + limit],
            "total": len(games),
            "limit": limit, "offset": offset,
            "source_kind": SOURCE,
            "official_schedule_inferred": False,
            "legacy_match_date_rewritten": False,
            "post_9999_gameplay_supported": False,
        }


def main() -> None:
    """Headless optional inspection of a saved slot: never mutate source."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Read a fictional v2 year/day schedule and A match results"
    )
    parser.add_argument("--slot-root", type=Path, required=True)
    parser.add_argument("--year", type=int)
    parser.add_argument("--day-token")
    parser.add_argument("--competition-id")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    if (args.year is None) == (args.day_token is None):
        parser.error("specify exactly one of --year and --day-token")
    if args.year is not None and args.competition_id:
        parser.error("--competition-id requires --day-token")
    model = CareerCalendarV2MatchReadModel(
        args.slot_root / "sandbox_calendar_v2.sqlite3",
        args.slot_root / "historical_matches.sqlite3",
    )
    result = (
        model.year_dates(args.year) if args.year is not None
        else model.date_page(
            args.day_token, competition_id=args.competition_id,
            limit=args.limit, offset=args.offset,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
