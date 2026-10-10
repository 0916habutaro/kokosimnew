"""Stage 43G-7: evidence-bound Chiba third representative game (sandbox).

The 2026 Chiba federation calendar lists a separate May 3 Kanto-entrant
decider between the semifinal losers. Future years use that *structure*
as a game-only projection; this is not confirmation of a 2027 host quota.
This service never derives third place from arbitrary ranking list order.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3

from game_core.tournament_bridge import AbilityMatchResolver

from .career_competition_outcomes import CareerCompetitionOutcomes, CareerOutcomeConflictError, _main_result
from .career_multi_preview_checkpoint import CareerMultiPreviewCheckpointService
from .career_preview_checkpoint import (
    CareerPreviewSaveError, _atomic_write, _checksum, _digest,
)
from .historical_match_archive import (
    HistoricalMatchArchive, _canonical as _history_canonical,
    _history_payload,
)

CHIBA = "CMP000092"
KANTO = "CMP000006"
SCHEMA = 1
GAME_DATE = (5, 3)
REGIONAL_START = (5, 16)


class ChibaThirdPlaceNotReady(CareerPreviewSaveError):
    """No certified Chiba semifinal/final or valid game-day projection."""


def _read_checkpoint(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ChibaThirdPlaceNotReady("Chiba placement checkpoint unreadable") from exc
    if (not isinstance(data, dict) or data.get("schema_version") != SCHEMA
            or data.get("payload_checksum") != _checksum(data)):
        raise ChibaThirdPlaceNotReady("Chiba placement checkpoint checksum invalid")
    return data


class ChibaThirdPlaceCheckpointService:
    """Play exactly one extra match and archive its A statistics in the same year.

    The source MAIN must be fully finished in the *saved* multi-preview, and
    every MAIN match must match the historical SQLite record. The two opponents
    are exactly the semifinal losers; the resolver uses persisted 2027 rosters.
    """

    def __init__(self, multi: CareerMultiPreviewCheckpointService):
        self.multi = multi

    def _path(self, slot: str, year: int) -> Path:
        slot = self.multi.solo.slots.validate_slot_id(slot)
        if not isinstance(year, int) or isinstance(year, bool) or not 2026 < year <= 9999:
            raise ChibaThirdPlaceNotReady("future sandbox year required")
        return (self.multi.solo.slots.slot_dir(slot) /
                "career_placement_previews" / f"{year}_{CHIBA}_third.json")

    def _source(self, slot: str, year: int) -> dict:
        session = self.multi.load(slot, year=year)
        if CHIBA not in session.previews or CHIBA not in session.completed_runs():
            raise ChibaThirdPlaceNotReady("Chiba MAIN must be completed first")
        try:
            run = session.completed_runs()[CHIBA]
            outcome, matches = _main_result(run)
        except (CareerOutcomeConflictError, ValueError) as exc:
            raise ChibaThirdPlaceNotReady("invalid Chiba MAIN result") from exc

        rounds = sorted({match.round_no for match in matches})
        semi = [match for match in matches
                if len(rounds) >= 2 and match.round_no == rounds[-2]]
        finals = [match for match in matches if match.round_no == rounds[-1]]
        if (len(semi) != 2 or len(finals) != 1 or
                len({m.loser for m in semi}) != 2 or
                any(m.loser in (outcome["champion_school_id"],
                                outcome["runner_up_school_id"]) for m in semi)):
            raise ChibaThirdPlaceNotReady("two distinct semifinal losers required")
        losers = sorted(m.loser for m in semi)
        placement_day = date(year, *GAME_DATE)
        regional_day = date(year, *REGIONAL_START)

        archive = self.multi.solo._archive(slot)
        with sqlite3.connect(archive.db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                manifest = CareerCompetitionOutcomes._check_source_matches(
                    conn, year, CHIBA, matches,
                )
            except (CareerOutcomeConflictError, ValueError) as exc:
                raise ChibaThirdPlaceNotReady("archived Chiba MAIN results invalid") from exc
            game_days = []
            for match_id, _ in manifest:
                row = conn.execute(
                    "SELECT match_date FROM historical_matches "
                    "WHERE year=? AND competition_id=? AND match_id=?",
                    (year, CHIBA, match_id),
                ).fetchone()
                if row is None:
                    raise ChibaThirdPlaceNotReady("Chiba MAIN match date missing")
                try:
                    day = date.fromisoformat(row["match_date"])
                except (TypeError, ValueError) as exc:
                    raise ChibaThirdPlaceNotReady("invalid Chiba MAIN date") from exc
                if day.year != year:
                    raise ChibaThirdPlaceNotReady("cross-year Chiba MAIN result")
                game_days.append(day)
            if not game_days or max(game_days) > placement_day:
                raise ChibaThirdPlaceNotReady("placement must follow the MAIN final")
            if placement_day >= regional_day:
                raise ChibaThirdPlaceNotReady("placement must precede regional start")
            # Do not allow an untracked or second placement decider to coexist.
            for row in conn.execute(
                "SELECT match_id, payload_json, record_sha256 FROM historical_matches "
                "WHERE year=? AND competition_id=?", (year, CHIBA),
            ):
                if (hashlib.sha256(row["payload_json"].encode("utf-8")).hexdigest()
                        != row["record_sha256"]):
                    raise ChibaThirdPlaceNotReady("modified Chiba archive record")
                if row["match_id"] == f"{CHIBA}-ST43G7-{year}-THIRD":
                    continue
                try:
                    payload = json.loads(row["payload_json"])
                except ValueError as exc:
                    raise ChibaThirdPlaceNotReady("corrupted existing Chiba record") from exc
                if (payload.get("stage_code") == "PLACEMENT" and
                        payload.get("phase_code") == "THIRD_PLACE"):
                    raise ChibaThirdPlaceNotReady("another third-place decider exists")

        return {
            "session": session,
            "school_ids": losers,
            "placement_day": placement_day.isoformat(),
            "source_sha256": _digest({
                "year": year, "competition_id": CHIBA,
                "plan_fingerprint": self.multi._fingerprint(session),
                "main_manifest": manifest,
                "semifinal_losers": losers,
                "main_result": outcome,
            }),
        }

    def _game(self, slot: str, year: int, source: dict) -> dict:
        session = source["session"]
        career_seed = session.inputs[0]["career_seed"]
        resolver = AbilityMatchResolver(
            self.multi.solo.repo,
            roster_provider=self.multi.solo._rosters(slot).roster,
            team_generation_seed=career_seed,
            ability_config_dir=self.multi.solo.ability_config_dir,
            match_config_dir=self.multi.solo.match_config_dir,
        )
        resolver.begin_season(year, career_seed)
        match_id = f"{CHIBA}-ST43G7-{year}-THIRD"
        team1, team2 = source["school_ids"]
        outcome = resolver(
            match_id=match_id, competition_id=CHIBA,
            reference_year=year,
            generation_seed=session.previews[CHIBA].annual.rng_seed,
            team1=team1, team2=team2,
        )
        if outcome.score_source != "ability_model_v1":
            raise ChibaThirdPlaceNotReady("third-place game must use ability scorer")
        return {
            "competition_id": CHIBA,
            "competition_name": "春季千葉県大会 関東出場校決定戦（ゲーム内仮日程）",
            "match_id": match_id,
            "match_date": source["placement_day"],
            "completed_on": source["placement_day"],
            "date_source": "game_projection_v1",
            "status": "completed",
            "stage_code": "PLACEMENT",
            "phase_code": "THIRD_PLACE",
            "round_no": 0,
            "team1_id": team1, "team2_id": team2,
            "team1_score": outcome.team1_score,
            "team2_score": outcome.team2_score,
            "winner_id": outcome.winner_id,
            "loser_id": outcome.loser_id,
            "score_source": outcome.score_source,
            "ability_detail": outcome.detail,
        }

    def _payload(self, slot: str, year: int, source: dict, game: dict) -> dict:
        normalized = _history_payload(year, game)
        raw = _history_canonical(normalized)
        payload = {
            "schema_version": SCHEMA,
            "slot_id": slot, "year": year,
            "competition_id": CHIBA, "destination_competition_id": KANTO,
            "match_id": game["match_id"],
            "match_date": game["match_date"],
            "third_place_school_id": game["winner_id"],
            "semifinal_loser_school_ids": source["school_ids"],
            "source_sha256": source["source_sha256"],
            "archived_match_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "official_future_rule_verified": False,
            "date_source": "game_projection_v1",
            "full_year_gameplay": False,
        }
        payload["payload_checksum"] = _checksum(payload)
        return payload

    def _sync(self, slot: str, year: int, source: dict, game: dict) -> None:
        session = source["session"]
        self.multi.solo._archive(slot).sync(
            year=year,
            rng_seed=session.inputs[0]["base_seed"],
            resolver_contract="career_multi_preview_ability_v1",
            plan_fingerprint=self.multi._fingerprint(session),
            completed=[game],
        )

    def start(self, slot_id: str, *, year: int) -> dict:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        path = self._path(slot, year)
        if path.exists():
            raise ChibaThirdPlaceNotReady("placement already started; use load()")
        source = self._source(slot, year)
        game = self._game(slot, year, source)
        payload = self._payload(slot, year, source, game)
        _atomic_write(path, payload)
        # JSON first: load() can repair a crash between checkpoint and SQLite.
        self._sync(slot, year, source, game)
        return payload

    def load(self, slot_id: str, *, year: int) -> dict:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        stored = _read_checkpoint(self._path(slot, year))
        source = self._source(slot, year)
        game = self._game(slot, year, source)
        expected = self._payload(slot, year, source, game)
        if stored != expected:
            raise ChibaThirdPlaceNotReady("Chiba third-place game replay disagrees")
        self._sync(slot, year, source, game)
        return expected
