"""Stage 43G-1: crash-recoverable *sandbox* checkpoint for one future event.

Does not replace LiveGameService's 2026 save or pretend that the full 2027
season exists. Binds the sealed preceding year, immutable player rosters,
verified prior-year access, exact annual inputs, and deterministic replay.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Mapping

from .career_roster_archive import CareerRosterArchive
from .future_competition_bridge import FutureCompetitionPreview
from .future_prior_autumn_access_bridge import (
    prepare_future_prior_autumn_bypass_preview,
)
from .historical_match_archive import HistoricalMatchArchive
from .repository import DataRepository
from .save_slots import SaveSlotManager

_SCHEMA_VERSION = 1
_RESOLVER = "career_preview_ability_v1"
_COMPETITION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class CareerPreviewSaveError(ValueError):
    """Save content, prior-year integrity, or deterministic replay disagrees."""


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False,
        separators=(",", ":"),
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _checksum(payload: Mapping[str, object]) -> str:
    return _digest({
        key: value for key, value in payload.items()
        if key != "payload_checksum"
    })


def _completed(preview: FutureCompetitionPreview) -> list[dict]:
    return [
        dict(record.__dict__)
        for _, record in sorted(preview.scheduled.matches.items())
        if record.status == "completed"
    ]


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _canonical(payload) + "\n"
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n",
            dir=path.parent, prefix=".career-preview-", suffix=".tmp",
            delete=False,
        ) as stream:
            name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name is not None and os.path.exists(name):
            os.unlink(name)


def _read_checkpoint(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CareerPreviewSaveError("career preview checkpoint unreadable") from exc
    if (not isinstance(payload, dict)
            or payload.get("schema_version") != _SCHEMA_VERSION
            or not isinstance(payload.get("payload_checksum"), str)
            or payload["payload_checksum"] != _checksum(payload)):
        raise CareerPreviewSaveError("career preview checkpoint checksum invalid")
    return payload


@dataclass
class CareerPreviewSession:
    slot_id: str
    preview: FutureCompetitionPreview
    inputs: dict
    prior_year_ledger_sha256: str
    checkpoint_checksum: str = ""

    def summary(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "year": self.preview.year,
            "competition_id": self.preview.competition_id,
            "prior_year": self.preview.year - 1,
            "checkpoint_resumable": True,
            "full_season_live": False,
            "official_2027_calendar": False,
            "previous_year_sealed": True,
            "processed_dates": list(self.preview.scheduled.processed_dates),
            "completed_match_count": len(_completed(self.preview)),
            "preview": self.preview.snapshot(),
        }


class CareerPreviewCheckpointService:
    """Namespaced future-preview JSON plus the slot's existing history DB.

    The original manual/autosave files are untouched. This only accepts
    explicitly specified annual entrants/groups and one future competition
    per year/slot. Real multi-competition career sessions are a later stage.
    """

    def __init__(
        self, repo: DataRepository, data_root: str | Path, *,
        save_root: str | Path = "out/saves",
        ability_config_dir: str | Path = "config/abilities",
        match_config_dir: str | Path = "config/match",
    ):
        self.repo = repo
        self.data_root = Path(data_root)
        self.slots = SaveSlotManager(save_root)
        self.ability_config_dir = Path(ability_config_dir)
        self.match_config_dir = Path(match_config_dir)

    def _archive(self, slot_id: str) -> HistoricalMatchArchive:
        return HistoricalMatchArchive(
            self.slots.slot_dir(slot_id) / "historical_matches.sqlite3"
        )

    def _rosters(self, slot_id: str) -> CareerRosterArchive:
        return CareerRosterArchive(
            self.slots.slot_dir(slot_id) / "career_rosters.sqlite3"
        )

    def _path(self, slot_id: str, year: int, cid: str) -> Path:
        if (not isinstance(year, int) or isinstance(year, bool)
                or not 2026 < year <= 9999
                or not isinstance(cid, str)
                or _COMPETITION_ID.fullmatch(cid) is None):
            raise CareerPreviewSaveError("invalid year or competition ID")
        return (self.slots.slot_dir(slot_id) / "career_previews"
                / f"{year}_{cid}.json")

    def _prior_ledger(self, slot_id: str, year: int) -> str:
        archive = self._archive(slot_id)
        if not archive.db_path.is_file():
            raise CareerPreviewSaveError("previous career year archive missing")
        with sqlite3.connect(archive.db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT status, match_count, ledger_sha256 "
                    "FROM career_years WHERE year=?", (year - 1,),
                ).fetchone()
                if row is None or row["status"] != "sealed":
                    raise CareerPreviewSaveError("previous career year is not sealed")
                count, sha = archive._ledger(conn, year - 1)
                if (count, sha) != (row["match_count"], row["ledger_sha256"]):
                    raise CareerPreviewSaveError("previous year ledger changed")
                return sha
            except sqlite3.Error as exc:
                raise CareerPreviewSaveError(
                    "previous career archive schema invalid"
                ) from exc

    def _preview(self, slot_id: str, args: Mapping[str, object]) -> FutureCompetitionPreview:
        return prepare_future_prior_autumn_bypass_preview(
            data_root=self.data_root,
            year=args["year"],
            competition_id=args["competition_id"],
            entrant_school_ids=args["entrant_school_ids"],
            group_entrant_school_ids=args["group_entrant_school_ids"],
            match_archive=self._archive(slot_id),
            roster_archive=self._rosters(slot_id),
            repo=self.repo,
            base_seed=args["base_seed"],
            career_seed=args["career_seed"],
            ability_config_dir=self.ability_config_dir,
            match_config_dir=self.match_config_dir,
            prior_source_competition_id=args["prior_source_competition_id"],
        )

    @staticmethod
    def _plan_fingerprint(session: CareerPreviewSession) -> str:
        return _digest({
            "scope": "single_future_competition_sandbox_v1",
            "slot_id": session.slot_id,
            "inputs": session.inputs,
            "prior_year_ledger_sha256": session.prior_year_ledger_sha256,
            "resolver_contract": _RESOLVER,
        })

    def _register(self, session: CareerPreviewSession) -> dict:
        return self._archive(session.slot_id).register_next_year(
            year=session.preview.year,
            rng_seed=session.inputs["base_seed"],
            resolver_contract=_RESOLVER,
            plan_fingerprint=self._plan_fingerprint(session),
        )

    def _payload(self, session: CareerPreviewSession) -> dict:
        dates = list(session.preview.scheduled.processed_dates)
        if dates != sorted(set(dates)):
            raise CareerPreviewSaveError("non-chronological or duplicate processed dates")
        result = {
            "schema_version": _SCHEMA_VERSION,
            "slot_id": session.slot_id,
            "year": session.preview.year,
            "competition_id": session.preview.competition_id,
            "inputs": session.inputs,
            "prior_year_ledger_sha256": session.prior_year_ledger_sha256,
            "resolver_contract": _RESOLVER,
            "plan_fingerprint": self._plan_fingerprint(session),
            "processed_dates": dates,
            "completed_match_count": len(_completed(session.preview)),
            "completed_match_sha256": _digest(_completed(session.preview)),
            "official_calendar": False,
            "full_year_gameplay": False,
        }
        result["payload_checksum"] = _checksum(result)
        return result

    def _sync(self, session: CareerPreviewSession) -> dict:
        return self._archive(session.slot_id).sync(
            year=session.preview.year,
            rng_seed=session.inputs["base_seed"],
            resolver_contract=_RESOLVER,
            plan_fingerprint=self._plan_fingerprint(session),
            completed=_completed(session.preview),
        )

    def start(
        self, slot_id: str, *, year: int, competition_id: str,
        entrant_school_ids: list[str],
        group_entrant_school_ids: Mapping[str, list[str]],
        base_seed: int, career_seed: int,
        prior_source_competition_id: str | None = None,
    ) -> CareerPreviewSession:
        slot = self.slots.validate_slot_id(slot_id)
        path = self._path(slot, year, competition_id)
        if path.exists():
            raise CareerPreviewSaveError("checkpoint already exists; use load()")
        if path.parent.is_dir() and any(path.parent.glob(f"{year}_*.json")):
            raise CareerPreviewSaveError(
                "only one future preview competition per slot/year is supported"
            )
        args = {
            "year": year, "competition_id": competition_id,
            "entrant_school_ids": list(entrant_school_ids),
            "group_entrant_school_ids": {
                key: list(value)
                for key, value in sorted(group_entrant_school_ids.items())
            },
            "base_seed": base_seed, "career_seed": career_seed,
            "prior_source_competition_id": prior_source_competition_id,
        }
        ledger = self._prior_ledger(slot, year)
        preview = self._preview(slot, args)
        session = CareerPreviewSession(slot, preview, args, ledger)
        self._register(session)
        self.save(session)
        return session

    def save(self, session: CareerPreviewSession) -> dict:
        path = self._path(
            session.slot_id, session.preview.year,
            session.preview.competition_id,
        )
        if self._prior_ledger(session.slot_id, session.preview.year) != (
            session.prior_year_ledger_sha256
        ):
            raise CareerPreviewSaveError("previous year's sealed ledger changed")
        self._register(session)
        if path.exists():
            current = _read_checkpoint(path)
            if current["payload_checksum"] != session.checkpoint_checksum:
                raise CareerPreviewSaveError(
                    "another session modified the preview checkpoint"
                )
        elif session.checkpoint_checksum:
            raise CareerPreviewSaveError("existing preview checkpoint was removed")
        payload = self._payload(session)
        _atomic_write(path, payload)
        session.checkpoint_checksum = payload["payload_checksum"]
        archived = self._sync(session)
        return {"path": str(path), "year": session.preview.year,
                "completed_match_count": payload["completed_match_count"],
                "archive": archived}

    def play_next_date(self, session: CareerPreviewSession) -> dict:
        date_result = session.preview.play_next_date()
        checkpoint = self.save(session)
        return {**date_result, "checkpoint": checkpoint}

    def load(
        self, slot_id: str, *, year: int, competition_id: str,
    ) -> CareerPreviewSession:
        slot = self.slots.validate_slot_id(slot_id)
        path = self._path(slot, year, competition_id)
        payload = _read_checkpoint(path)
        args = payload.get("inputs")
        if (not isinstance(args, dict)
                or payload.get("slot_id") != slot
                or payload.get("year") != year
                or payload.get("competition_id") != competition_id
                or args.get("year") != year
                or args.get("competition_id") != competition_id
                or payload.get("resolver_contract") != _RESOLVER
                or payload.get("official_calendar") is not False
                or payload.get("full_year_gameplay") is not False):
            raise CareerPreviewSaveError("career preview metadata mismatch")
        ledger = self._prior_ledger(slot, year)
        if payload.get("prior_year_ledger_sha256") != ledger:
            raise CareerPreviewSaveError("prior-year ledger differs from saved preview")
        try:
            preview = self._preview(slot, args)
            session = CareerPreviewSession(
                slot, preview, args, ledger, payload["payload_checksum"],
            )
            if payload.get("plan_fingerprint") != self._plan_fingerprint(session):
                raise CareerPreviewSaveError("career preview input fingerprint mismatch")
            dates = payload.get("processed_dates")
            if (not isinstance(dates, list)
                    or dates != sorted(set(dates))
                    or any(not isinstance(d, str) for d in dates)):
                raise CareerPreviewSaveError("invalid replay dates")
            for expected in dates:
                if preview.scheduled.next_scheduled_date() != expected:
                    raise CareerPreviewSaveError("career preview replay date changed")
                preview.play_next_date()
            if (payload.get("completed_match_count") != len(_completed(preview))
                    or payload.get("completed_match_sha256") !=
                    _digest(_completed(preview))):
                raise CareerPreviewSaveError("career preview replay score changed")
            # No source can rewrite a sealed historical year. This also
            # idempotently repairs a crash between checkpoint and 2027 A-history.
            self._register(session)
            self._sync(session)
            return session
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            if isinstance(exc, CareerPreviewSaveError):
                raise
            raise CareerPreviewSaveError(
                "career preview input or deterministic replay rejected"
            ) from exc
