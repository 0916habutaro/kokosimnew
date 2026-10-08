"""Explicit-date, nonblocking scheduler for optional placement fixtures.

The main competition runtime owns qualification and progression. This sidecar
owns only optional post-qualification ranking outcomes and may be canceled
without modifying qualifiers or the MAIN schedule.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping, Sequence

from .post_qualification_ranking import RankingOnlyEventRuntime


def _validated_date(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("ranking date is required")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError(value)
    except ValueError as exc:
        raise ValueError(f"invalid ranking date: {value}") from exc
    return value


@dataclass
class ScheduledRankingSidecar:
    event: RankingOnlyEventRuntime
    match_dates: tuple[str, ...]
    qualification_locked_on: str
    completed_scores: dict[str, tuple[int | None, int | None]] = field(
        default_factory=dict
    )
    canceled: bool = False

    @classmethod
    def create(
        cls,
        event: RankingOnlyEventRuntime,
        *,
        qualification_locked_on: str,
        match_dates: Sequence[str],
    ) -> "ScheduledRankingSidecar":
        locked_on = _validated_date(qualification_locked_on)
        dates = tuple(_validated_date(value) for value in match_dates)
        expected_rounds = 2 if event.mode == "semifinal_final" else 1
        if len(dates) != expected_rounds:
            raise ValueError("one explicit match date is required per ranking round")
        if len(set(dates)) != len(dates) or list(dates) != sorted(dates):
            raise ValueError("ranking round dates must be strictly increasing")
        if any(value <= locked_on for value in dates):
            raise ValueError("ranking dates must follow qualification lock")
        return cls(event=event, match_dates=dates,
                   qualification_locked_on=locked_on)

    @property
    def is_complete(self) -> bool:
        return self.canceled or self.event.is_complete

    def _rows(self) -> list[dict]:
        rows = []
        for match in self.event.all_fixtures():
            match_id = match["match_id"]
            winner = self.event.results.get(match_id, "")
            team1, team2 = match["team1"], match["team2"]
            scores = self.completed_scores.get(match_id, (None, None))
            rows.append({
                "competition_id": self.event.competition_id,
                "stage_id": self.event.stage_id,
                "stage_code": self.event.stage_code,
                "phase_code": match["phase_code"],
                "group_id": self.event.group_id,
                "match_id": match_id,
                "match_date": self.match_dates[match["round_no"] - 1],
                "round_no": match["round_no"],
                "team1_id": team1,
                "team2_id": team2,
                "winner_id": winner,
                "loser_id": (
                    team2 if winner == team1 else team1
                ) if winner else "",
                "team1_score": scores[0],
                "team2_score": scores[1],
                "status": "completed" if winner else (
                    "canceled" if self.canceled else "pending"
                ),
                "date_source": "explicit_post_qualification_date",
                "qualifier_effect": "none",
                "ranking_only": True,
            })
        return rows

    def matches_for_date(self, target: str) -> list[dict]:
        normalized = _validated_date(target)
        return [r for r in self._rows() if r["match_date"] == normalized]

    def completed_results(self) -> list[dict]:
        return [r for r in self._rows() if r["status"] == "completed"]

    def resolve_date(
        self,
        target: str,
        winners: Mapping[str, str],
        *,
        scores: Mapping[str, tuple[int, int]] | None = None,
    ) -> list[dict]:
        target = _validated_date(target)
        if self.canceled:
            raise ValueError("ranking sidecar was canceled")
        ready = {
            r["match_id"]: r for r in self.event.ready_matches()
            if self.match_dates[r["round_no"] - 1] == target
        }
        if not ready:
            if winners:
                raise ValueError("no ready ranking fixtures on that date")
            return []
        if set(winners) != set(ready):
            raise ValueError("all fixtures on a ranking date require winners")
        supplied_scores = dict(scores or {})
        if not set(supplied_scores).issubset(ready):
            raise ValueError("scores contain an unscheduled ranking match")
        for match_id, values in supplied_scores.items():
            if (len(values) != 2 or any(
                type(v) is not int or v < 0 for v in values
            )):
                raise ValueError("ranking scores must be nonnegative integer pairs")
            row = ready[match_id]
            winner = winners[match_id]
            if values[0] == values[1]:
                raise ValueError("ranking results cannot finish tied")
            if (winner == row["team1"] and values[0] <= values[1]) or (
                winner == row["team2"] and values[1] <= values[0]
            ):
                raise ValueError("ranking winner disagrees with score")
        # Validate all submitted winners before changing any match state.
        for match_id, winner in winners.items():
            row = ready[match_id]
            if winner not in (row["team1"], row["team2"]):
                raise ValueError("ranking winner is not a participant")
        for match_id in sorted(winners):
            self.event.resolve(match_id, winners[match_id])
            if match_id in supplied_scores:
                self.completed_scores[match_id] = tuple(
                    supplied_scores[match_id]
                )
        return [r for r in self._rows()
                if r["match_id"] in winners]

    def cancel_remaining(self) -> None:
        """Canceled optional matches never undo qualification."""
        self.canceled = True

    def snapshot(self) -> dict:
        return {
            "schema": "scheduled_ranking_sidecar_v1",
            "event": self.event.snapshot(),
            "match_dates": list(self.match_dates),
            "qualification_locked_on": self.qualification_locked_on,
            "completed_scores": {
                key: list(value)
                for key, value in sorted(self.completed_scores.items())
            },
            "canceled": self.canceled,
            "matches": self._rows(),
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict) -> "ScheduledRankingSidecar":
        if snapshot.get("schema") != "scheduled_ranking_sidecar_v1":
            raise ValueError("unknown scheduled ranking snapshot format")
        event = RankingOnlyEventRuntime.from_snapshot(snapshot["event"])
        state = cls.create(
            event,
            qualification_locked_on=snapshot["qualification_locked_on"],
            match_dates=snapshot["match_dates"],
        )
        score_rows = snapshot.get("completed_scores", {})
        if not set(score_rows).issubset(event.results):
            raise ValueError("scores exist for unfinished ranking matches")
        state.completed_scores = {
            mid: tuple(values) for mid, values in score_rows.items()
        }
        state.canceled = bool(snapshot["canceled"])
        if state.snapshot()["matches"] != snapshot["matches"]:
            raise ValueError("ranking snapshot contains inconsistent match rows")
        return state
