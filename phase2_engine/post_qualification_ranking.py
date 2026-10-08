"""Optional post-qualification ranking events, independent of advancement.

Stage 13E-3G-1:
- FMT022: already seeded top four may play two block finals, or semifinals
  followed by a final; their seed entitlement is immutable.
- FMT025: optional, explicitly drawn pairwise placement deciders among
  already qualified teams; nonparticipants stay qualified.

No match is simulated when the event is created. This module does NOT
automatically schedule extra games in the 2026 live season runtime.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
import re
from pathlib import Path
from typing import Sequence

from .paths import resolve_data_file


PROFILE_NAME = "post_qualification_ranking_profiles.csv"
FMT022_MODES = {"two_block_deciders", "semifinal_final"}
FMT025_MODE = "pairwise_deciders"


def load_post_qualification_profiles(data_dir: str | Path) -> dict[str, dict]:
    path = resolve_data_file(Path(data_dir), PROFILE_NAME)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    profiles = {}
    for row in rows:
        cid = row["competition_id"]
        if cid in profiles:
            raise ValueError(f"duplicate ranking profile {cid}")
        if row["format_model_id"] == "FMT022":
            if row["ranking_event_mode"] not in FMT022_MODES:
                raise ValueError(f"unsupported FMT022 profile {cid}")
        elif row["format_model_id"] == "FMT025":
            if row["ranking_event_mode"] != FMT025_MODE:
                raise ValueError(f"unsupported FMT025 profile {cid}")
        else:
            raise ValueError(f"unsupported ranking-only model: {cid}")
        if row["result_effect"] != "ranking_metadata_only":
            raise ValueError(f"post-qualification may not change entrants: {cid}")
        profiles[cid] = row
    return profiles


@dataclass
class RankingOnlyEventRuntime:
    """Lazy, replayable event; frozen advance/seed cohort never changes."""

    competition_id: str
    stage_id: str
    stage_code: str
    group_id: str
    format_model_id: str
    mode: str
    locked_school_ids: tuple[str, ...]
    pairings: tuple[tuple[str, str], ...]
    event_id: str = ""
    results: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        competition_id: str,
        stage_id: str,
        stage_code: str,
        group_id: str,
        format_model_id: str,
        mode: str,
        locked_school_ids: Sequence[str],
        pairings: Sequence[Sequence[str]] = (),
        event_id: str = "",
    ) -> "RankingOnlyEventRuntime":
        if event_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", event_id):
            raise ValueError("invalid post-qualification event_id")
        locked = tuple(locked_school_ids)
        if len(locked) != len(set(locked)) or not locked or any(not sid for sid in locked):
            raise ValueError("locked qualifiers must be nonempty and unique")
        if format_model_id == "FMT022":
            if mode not in FMT022_MODES or len(locked) != 4:
                raise ValueError("FMT022 needs a locked cohort of exactly four")
            if stage_code != "SEED_EVENT":
                raise ValueError("FMT022 ranking events require SEED_EVENT")
            if not pairings:
                # Deterministic fallback for fictional annual draw. An exact
                # official replay must pass the known pairing explicitly.
                pairings = (
                    ((locked[0], locked[1]), (locked[2], locked[3]))
                    if mode == "two_block_deciders"
                    else ((locked[0], locked[3]), (locked[1], locked[2]))
                )
            if len(pairings) != 2:
                raise ValueError("FMT022 requires two first-round matches")
        elif format_model_id == "FMT025":
            if mode != FMT025_MODE or stage_code != "BRANCH_QUALIFIER":
                raise ValueError("FMT025 expects branch-qualified placement deciders")
            if not pairings:
                raise ValueError("FMT025 placement requires an explicit annual draw")
        else:
            raise ValueError(f"ranking-only model {format_model_id} is unsupported")
        pairs = tuple(tuple(pair) for pair in pairings)
        if any(len(pair) != 2 or pair[0] == pair[1] for pair in pairs):
            raise ValueError("each ranking match needs two different schools")
        flat = [sid for pair in pairs for sid in pair]
        if len(flat) != len(set(flat)) or not set(flat).issubset(locked):
            raise ValueError("ranking pairings must use each locked qualifier at most once")
        if format_model_id == "FMT022" and set(flat) != set(locked):
            raise ValueError("FMT022 first round must include all four seeds")
        return cls(
            competition_id=competition_id,
            stage_id=stage_id,
            stage_code=stage_code,
            group_id=group_id,
            format_model_id=format_model_id,
            mode=mode,
            locked_school_ids=locked,
            pairings=pairs,
            event_id=event_id,
        )

    def _id(self, code: str) -> str:
        suffix = f"{self.event_id}-" if self.event_id else ""
        return f"{self.stage_id}-{self.group_id}-POST_RANK-{suffix}{code}"

    def all_fixtures(self) -> list[dict]:
        fixtures = [
            {
                "match_id": self._id(f"R1-{i:02d}"),
                "phase_code": "POST_QUALIFICATION_RANKING",
                "round_no": 1,
                "team1": a,
                "team2": b,
            }
            for i, (a, b) in enumerate(self.pairings, 1)
        ]
        if self.mode == "semifinal_final" and all(
            f["match_id"] in self.results for f in fixtures
        ):
            a, b = (self.results[f["match_id"]] for f in fixtures)
            fixtures.append({
                "match_id": self._id("FINAL"),
                "phase_code": "POST_QUALIFICATION_RANKING",
                "round_no": 2,
                "team1": a,
                "team2": b,
            })
        return fixtures

    def ready_matches(self) -> list[dict]:
        fixtures = self.all_fixtures()
        open_round = min(
            (f["round_no"] for f in fixtures if f["match_id"] not in self.results),
            default=None,
        )
        return [
            dict(f) for f in fixtures
            if f["match_id"] not in self.results and f["round_no"] == open_round
        ]

    def resolve(self, match_id: str, winner_school_id: str) -> None:
        if match_id in self.results:
            raise ValueError("ranking match already completed")
        candidates = {
            r["match_id"]: r for r in self.ready_matches()
        }
        if match_id not in candidates:
            raise ValueError("ranking match is not ready")
        row = candidates[match_id]
        if winner_school_id not in (row["team1"], row["team2"]):
            raise ValueError("ranking winner must be in the scheduled fixture")
        self.results[match_id] = winner_school_id

    @property
    def is_complete(self) -> bool:
        return bool(self.results) and not self.ready_matches()

    def ranking_metadata(self) -> dict:
        """Publish placement observations without modifying qualification."""
        decided = []
        for fixture in self.all_fixtures():
            winner = self.results.get(fixture["match_id"])
            if not winner:
                continue
            loser = (
                fixture["team2"] if winner == fixture["team1"]
                else fixture["team1"]
            )
            decided.append({
                "match_id": fixture["match_id"],
                "round_no": fixture["round_no"],
                "higher_placed_school_id": winner,
                "lower_placed_school_id": loser,
            })
        metadata = {
            "mode": self.mode,
            "format_model_id": self.format_model_id,
            "group_id": self.group_id,
            "qualifier_effect": "none",
            "locked_qualifiers": list(self.locked_school_ids),
            "placement_decisions": decided,
            "is_complete": self.is_complete,
        }
        if self.mode == "semifinal_final" and self._id("FINAL") in self.results:
            metadata["event_champion_school_id"] = self.results[self._id("FINAL")]
        return metadata

    def snapshot(self) -> dict:
        return {
            **({"event_id": self.event_id} if self.event_id else {}),
            "competition_id": self.competition_id,
            "stage_id": self.stage_id,
            "stage_code": self.stage_code,
            "group_id": self.group_id,
            "format_model_id": self.format_model_id,
            "mode": self.mode,
            "locked_school_ids": list(self.locked_school_ids),
            "pairings": [list(pair) for pair in self.pairings],
            "results": dict(self.results),
            "ready_matches": self.ready_matches(),
            "is_complete": self.is_complete,
            "ranking_metadata": self.ranking_metadata(),
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict) -> "RankingOnlyEventRuntime":
        state = cls.create(
            competition_id=snapshot["competition_id"],
            stage_id=snapshot["stage_id"],
            stage_code=snapshot["stage_code"],
            group_id=snapshot["group_id"],
            format_model_id=snapshot["format_model_id"],
            mode=snapshot["mode"],
            locked_school_ids=snapshot["locked_school_ids"],
            pairings=snapshot["pairings"],
            event_id=snapshot.get("event_id", ""),
        )
        # Replaying through ready_matches validates round ordering and winners.
        for completed_id, winner in snapshot["results"].items():
            state.resolve(completed_id, winner)
        return state
