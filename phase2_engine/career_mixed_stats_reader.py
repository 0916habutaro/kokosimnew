"""Stage43G-18: combine verified sealed cache with uncached/active raw A years.

Segmented reads preserve per-year integrity rules. Cached segments check
ledger/facts/all player rows; raw segments revalidate their A-game payloads.
No cache building, game modification, or top-N truncation during aggregation.
"""
from __future__ import annotations

from collections import defaultdict

from .career_player_records import CareerPlayerRecordView, RANKABLE
from .career_player_stat_cache import CareerPlayerStatCache


class CareerMixedStatReader:
    def __init__(self, raw: CareerPlayerRecordView, cache, plan: list[dict]):
        self.raw, self.cache = raw, cache
        self.plan = plan
        if not plan or all(r["cached"] for r in plan) or not any(
            r["cached"] for r in plan
        ):
            raise ValueError("mixed reader requires both cached and raw years")
        if any(
            plan[i]["year"] + 1 != plan[i+1]["year"]
            for i in range(len(plan) - 1)
        ):
            raise ValueError("cache plan must have contiguous years")

    def _segments(self):
        start = self.plan[0]["year"]
        previous = start
        cached = self.plan[0]["cached"]
        for row in self.plan[1:]:
            if row["cached"] != cached:
                yield cached, start, previous
                start, cached = row["year"], row["cached"]
            previous = row["year"]
        yield cached, start, previous

    def _check_range(self, start_year: int, end_year: int):
        if (start_year != self.plan[0]["year"]
                or end_year != self.plan[-1]["year"]):
            raise ValueError("mixed stats plan year range differs")

    def player_seasons(self, player_id: str, *, start_year: int,
                       end_year: int) -> dict:
        self._check_range(start_year, end_year)
        if not isinstance(player_id, str) or not player_id:
            raise ValueError("invalid player ID")
        seasons = []
        missing = 0
        school_id = None
        for cached, first, last in self._segments():
            reader = self.cache if cached else self.raw
            chunk = reader.player_seasons(
                player_id, start_year=first, end_year=last
            )
            seasons.extend(chunk["seasons"])
            missing += chunk.get("games_without_box_scores", 0)
            if chunk.get("school_id"):
                if school_id and school_id != chunk["school_id"]:
                    raise ValueError("player identity school changed")
                school_id = chunk["school_id"]
        seasons.sort(key=lambda r: r["year"])
        return {
            "player_id": player_id, "school_id": school_id,
            "seasons": seasons,
            "totals": CareerPlayerStatCache._rollup(seasons),
            "games_without_box_scores": missing,
            "source_payloads_rechecked_on_read": False,
            "only_archived_option_a_stats": True,
            "cached_years": [r["year"] for r in self.plan if r["cached"]],
            "raw_years": [r["year"] for r in self.plan if not r["cached"]],
        }

    def school_leaders(self, school_id: str, *, start_year: int,
                       end_year: int, category: str, limit: int = 20) -> dict:
        self._check_range(start_year, end_year)
        if (category not in RANKABLE or type(limit) is not int
                or not 1 <= limit <= 100):
            raise ValueError("invalid school record metric or limit")
        if not isinstance(school_id, str) or not school_id:
            raise ValueError("invalid school ID")
        kind, field = RANKABLE[category]
        totals = defaultdict(lambda: {"games": 0, "value": 0})
        missing = 0
        for cached, first, last in self._segments():
            if cached:
                chunk = self.cache.verified_school_rows(
                    school_id, start_year=first, end_year=last
                )
                rows = (
                    (pid, record)
                    for pid, _year, record in chunk["rows"]
                )
                missing += chunk["missing_box_score_games"]
            else:
                raw = self.raw._aggregate(school_id, first, last)
                rows = ((pid, record) for (pid, _year), record in raw.items())
                missing += self.raw._missing(school_id, first, last)
            for player_id, record in rows:
                target = totals[player_id]
                target["games"] += record[kind]["games"]
                target["value"] += record[kind][field]
        ranked = sorted(
            ({"player_id": pid, "stat_value": row["value"]}
             for pid, row in totals.items() if row["games"]),
            key=lambda r: (-r["stat_value"], r["player_id"]),
        )
        return {
            "school_id": school_id, "start_year": start_year,
            "end_year": end_year, "category": category,
            "rows": ranked[:limit], "candidate_count": len(ranked),
            "only_archived_option_a_stats": True,
            "missing_box_score_games": missing,
            "source_payloads_rechecked_on_read": False,
            "cached_years": [r["year"] for r in self.plan if r["cached"]],
            "raw_years": [r["year"] for r in self.plan if not r["cached"]],
        }
