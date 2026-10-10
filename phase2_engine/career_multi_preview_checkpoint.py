"""Stage 43G-2: one sealed-year-linked sandbox checkpoint for multiple events.

Opt-in future-year development only. A shared career-year identity protects
the append-only A match archive; independent event results are *not*
automatic qualification to any unverified destination event.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Mapping, Sequence

from .career_preview_checkpoint import (
    CareerPreviewCheckpointService,
    CareerPreviewSaveError,
    _atomic_write,
    _checksum,
    _digest,
    _completed,
)
from .future_competition_bridge import (
    FutureCompetitionPreview, prepare_future_direct_main_preview,
)
from .future_season_blueprint import build_future_season_blueprint
from .future_kanto_direct_main_bridge import (
    DIRECT_MAIN_PREFECTURES,
    prepare_future_kanto_direct_main_preview,
)
from .historical_match_archive import HistoricalMatchArchive

_SCHEMA = 2
_RESOLVER = "career_multi_preview_ability_v1"


def _all_completed(previews: Mapping[str, FutureCompetitionPreview]) -> list[dict]:
    return [
        record
        for cid in sorted(previews)
        for record in _completed(previews[cid])
    ]


def _checkpoint(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CareerPreviewSaveError("multi-preview checkpoint unreadable") from exc
    if (not isinstance(data, dict)
            or data.get("schema_version") != _SCHEMA
            or not isinstance(data.get("payload_checksum"), str)
            or data["payload_checksum"] != _checksum(data)):
        raise CareerPreviewSaveError("multi-preview checkpoint checksum invalid")
    return data


@dataclass
class CareerMultiPreviewSession:
    slot_id: str
    year: int
    previews: dict[str, FutureCompetitionPreview]
    inputs: list[dict]
    prior_ledger_sha256: str
    initial_digests: dict[str, str]
    processed_dates: list[str]
    checkpoint_checksum: str = ""

    def summary(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "year": self.year,
            "competition_ids": sorted(self.previews),
            "competition_count": len(self.previews),
            "completed_competition_ids": sorted(
                cid for cid, p in self.previews.items()
                if p.scheduled.is_complete
            ),
            "processed_dates": list(self.processed_dates),
            "completed_match_count": len(_all_completed(self.previews)),
            "previous_year_sealed": True,
            "full_year_gameplay": False,
            "official_future_calendar": False,
            "competition_advancement_automatic": False,
        }

    def completed_runs(self) -> dict[str, object]:
        """Return *in-memory* finished games; no unverified feeder award."""
        return {
            cid: preview.scheduled.to_competition_run()
            for cid, preview in sorted(self.previews.items())
            if preview.scheduled.is_complete
        }


class CareerMultiPreviewCheckpointService:
    """Advance two or more independently verified future-year preview events.

    New namespace: <slot>/career_multi_previews/<year>.json. The existing
    2026 live save and Stage43G-1 single-event JSON are never overwritten.
    All events share ONE annual plan digest, so their A records can coexist.
    """

    def __init__(self, repo, data_root: str | Path, *,
                 save_root: str | Path = "out/saves",
                 ability_config_dir: str | Path = "config/abilities",
                 match_config_dir: str | Path = "config/match"):
        self.solo = CareerPreviewCheckpointService(
            repo, data_root, save_root=save_root,
            ability_config_dir=ability_config_dir,
            match_config_dir=match_config_dir,
        )

    def _path(self, slot: str, year: int) -> Path:
        slot = self.solo.slots.validate_slot_id(slot)
        if (not isinstance(year, int) or isinstance(year, bool)
                or not 2026 < year <= 9999):
            raise CareerPreviewSaveError("invalid multi-preview year")
        return self.solo.slots.slot_dir(slot) / "career_multi_previews" / f"{year}.json"

    @staticmethod
    def _inputs(year: int, competitions: Sequence[Mapping[str, object]],
                *, base_seed: int, career_seed: int) -> list[dict]:
        if (not isinstance(base_seed, int) or isinstance(base_seed, bool)
                or not isinstance(career_seed, int)
                or isinstance(career_seed, bool)):
            raise CareerPreviewSaveError("multi-preview seeds must be integers")
        if not isinstance(competitions, (list, tuple)) or len(competitions) < 2:
            raise CareerPreviewSaveError("two or more future competitions required")
        rows = []
        for comp in competitions:
            if not isinstance(comp, Mapping):
                raise CareerPreviewSaveError("invalid competition specification")
            cid = comp.get("competition_id")
            if not isinstance(cid, str) or not cid:
                raise CareerPreviewSaveError("invalid competition ID")
            schools = comp.get("entrant_school_ids")
            groups = comp.get("group_entrant_school_ids")
            if (not isinstance(schools, (list, tuple))
                    or not isinstance(groups, Mapping)):
                raise CareerPreviewSaveError("explicit schools and groups required")
            if any(not isinstance(k, str) or not isinstance(v, (list, tuple))
                   for k, v in groups.items()):
                raise CareerPreviewSaveError("invalid future group memberships")
            source = comp.get("prior_source_competition_id")
            if source is not None and not isinstance(source, str):
                raise CareerPreviewSaveError("invalid prior game source")
            mode = comp.get("entry_mode", "prior_autumn_bypass_v1")
            if mode not in ("prior_autumn_bypass_v1", "kanto_direct_main_v1",
                            "national_invitational_main_v1"):
                raise CareerPreviewSaveError("unsupported future entrant mode")
            if mode == "kanto_direct_main_v1":
                if cid not in DIRECT_MAIN_PREFECTURES or groups or source is not None:
                    raise CareerPreviewSaveError(
                        "direct MAIN requires whitelisted competition and no feeder override"
                    )
            if mode == "national_invitational_main_v1":
                if (cid != "CMP000001" or groups or source is not None
                        or len(schools) != 32 or len(set(schools)) != 32):
                    raise CareerPreviewSaveError(
                        "national invitational needs explicit complete 32-school game manifest"
                    )
            if cid == "CMP000001" and mode != "national_invitational_main_v1":
                raise CareerPreviewSaveError(
                    "Senbatsu may not be inferred from a prior autumn or prefectural result"
                )
            if cid == "CMP000094":
                if (mode != "prior_autumn_bypass_v1"
                        or not isinstance(source, str)
                        or not source.strip()
                        or source == cid):
                    raise CareerPreviewSaveError(
                        "Tokyo requires explicit sealed prior-autumn game source ID"
                    )
            elif cid == "CMP000092":
                if mode != "prior_autumn_bypass_v1" or source is not None:
                    raise CareerPreviewSaveError(
                        "Chiba requires verified prior-autumn access without source override"
                    )
            row = {
                "year": year, "competition_id": cid,
                "entrant_school_ids": list(schools),
                "group_entrant_school_ids": {
                    k: list(v) for k, v in sorted(groups.items())
                },
                "base_seed": base_seed, "career_seed": career_seed,
                "prior_source_competition_id": source,
            }
            # Preserve old Stage43G-2/3/4 save identities when no new mode
            # was requested; retroactive schema normalization would break
            # the immutable yearly SHA256 fingerprint.
            if "entry_mode" in comp:
                row["entry_mode"] = mode
            rows.append(row)
        rows.sort(key=lambda row: row["competition_id"])
        ids = [x["competition_id"] for x in rows]
        if len(ids) != len(set(ids)):
            raise CareerPreviewSaveError("duplicate future competition ID")
        return rows

    @staticmethod
    def _fingerprint(session: CareerMultiPreviewSession) -> str:
        return _digest({
            "scope": "multiple_future_competitions_sandbox_v1",
            "slot_id": session.slot_id,
            "year": session.year,
            "inputs": session.inputs,
            "prior_ledger_sha256": session.prior_ledger_sha256,
            "initial_digests": session.initial_digests,
            "resolver_contract": _RESOLVER,
        })

    def _register(self, session: CareerMultiPreviewSession) -> dict:
        return self.solo._archive(session.slot_id).register_next_year(
            year=session.year,
            rng_seed=session.inputs[0]["base_seed"],
            resolver_contract=_RESOLVER,
            plan_fingerprint=self._fingerprint(session),
        )

    def _sync(self, session: CareerMultiPreviewSession) -> dict:
        return self.solo._archive(session.slot_id).sync(
            year=session.year, rng_seed=session.inputs[0]["base_seed"],
            resolver_contract=_RESOLVER,
            plan_fingerprint=self._fingerprint(session),
            completed=_all_completed(session.previews),
        )

    def _prepare_all(self, slot: str, inputs: list[dict]) -> dict:
        previews = {}
        for row in inputs:
            if row.get("entry_mode") == "kanto_direct_main_v1":
                preview = prepare_future_kanto_direct_main_preview(
                    data_root=self.solo.data_root, year=row["year"],
                    competition_id=row["competition_id"],
                    entrant_school_ids=row["entrant_school_ids"],
                    roster_archive=self.solo._rosters(slot),
                    repo=self.solo.repo,
                    base_seed=row["base_seed"],
                    career_seed=row["career_seed"],
                    ability_config_dir=self.solo.ability_config_dir,
                    match_config_dir=self.solo.match_config_dir,
                )
            elif row.get("entry_mode") == "national_invitational_main_v1":
                blueprint = build_future_season_blueprint(
                    self.solo.data_root, year=row["year"], base_seed=row["base_seed"],
                )
                preview = prepare_future_direct_main_preview(
                    blueprint=blueprint, competition_id=row["competition_id"],
                    entrant_school_ids=row["entrant_school_ids"],
                    roster_archive=self.solo._rosters(slot), repo=self.solo.repo,
                    career_seed=row["career_seed"],
                    ability_config_dir=self.solo.ability_config_dir,
                    match_config_dir=self.solo.match_config_dir,
                )
            else:
                preview = self.solo._preview(slot, row)
            previews[row["competition_id"]] = preview
        return previews

    @staticmethod
    def _initial_digests(previews: Mapping[str, FutureCompetitionPreview]) -> dict:
        return {
            cid: _digest(preview.scheduled.public_snapshot())
            for cid, preview in sorted(previews.items())
        }

    def _payload(self, session: CareerMultiPreviewSession) -> dict:
        if (session.processed_dates != sorted(set(session.processed_dates))
                or any(not isinstance(d, str) for d in session.processed_dates)):
            raise CareerPreviewSaveError("invalid multi-preview processed dates")
        records = _all_completed(session.previews)
        results = session.completed_runs()
        data = {
            "schema_version": _SCHEMA,
            "slot_id": session.slot_id,
            "year": session.year,
            "inputs": session.inputs,
            "prior_ledger_sha256": session.prior_ledger_sha256,
            "initial_digests": session.initial_digests,
            "resolver_contract": _RESOLVER,
            "plan_fingerprint": self._fingerprint(session),
            "processed_dates": list(session.processed_dates),
            "competition_date_progress": {
                cid: list(preview.scheduled.processed_dates)
                for cid, preview in sorted(session.previews.items())
            },
            "completed_competition_champions": {
                cid: run.outcome.champion_school_id
                for cid, run in sorted(results.items())
            },
            "completed_match_count": len(records),
            "completed_match_sha256": _digest(records),
            "official_future_calendar": False,
            "full_year_gameplay": False,
            "automatic_feeder_advancement": False,
        }
        data["payload_checksum"] = _checksum(data)
        return data

    def _assert_prior(self, session: CareerMultiPreviewSession) -> None:
        sha = self.solo._prior_ledger(session.slot_id, session.year)
        if sha != session.prior_ledger_sha256:
            raise CareerPreviewSaveError("sealed previous-year ledger changed")

    def start(self, slot_id: str, *, year: int,
              competitions: Sequence[Mapping[str, object]],
              base_seed: int, career_seed: int) -> CareerMultiPreviewSession:
        slot = self.solo.slots.validate_slot_id(slot_id)
        target = self._path(slot, year)
        if target.exists():
            raise CareerPreviewSaveError("multi-preview already exists; use load()")
        # Do not reuse an existing G-1 single-event slot/year.
        single = self.solo.slots.slot_dir(slot) / "career_previews"
        if single.is_dir() and any(single.glob(f"{year}_*.json")):
            raise CareerPreviewSaveError("single-event preview already owns year")
        inputs = self._inputs(
            year, competitions, base_seed=base_seed, career_seed=career_seed,
        )
        prior = self.solo._prior_ledger(slot, year)
        previews = self._prepare_all(slot, inputs)
        initial = self._initial_digests(previews)
        session = CareerMultiPreviewSession(
            slot, year, previews, inputs, prior, initial, [],
        )
        self._register(session)
        self.save(session)
        return session

    def save(self, session: CareerMultiPreviewSession) -> dict:
        target = self._path(session.slot_id, session.year)
        self._assert_prior(session)
        self._register(session)
        if target.is_file():
            current = _checkpoint(target)
            if current["payload_checksum"] != session.checkpoint_checksum:
                raise CareerPreviewSaveError("another multi-preview session changed checkpoint")
        elif session.checkpoint_checksum:
            raise CareerPreviewSaveError("multi-preview checkpoint removed")
        payload = self._payload(session)
        _atomic_write(target, payload)
        session.checkpoint_checksum = payload["payload_checksum"]
        archived = self._sync(session)
        return {
            "path": str(target), "year": session.year,
            "completed_match_count": payload["completed_match_count"],
            "archive": archived,
        }

    @staticmethod
    def _next_date(session: CareerMultiPreviewSession) -> str:
        days = [
            preview.scheduled.next_scheduled_date()
            for preview in session.previews.values()
        ]
        available = [day for day in days if day]
        return min(available) if available else ""

    def play_next_date(self, session: CareerMultiPreviewSession) -> dict:
        next_day = self._next_date(session)
        if not next_day:
            raise CareerPreviewSaveError("no next scheduled multi-preview date")
        counts = {}
        for cid, preview in sorted(session.previews.items()):
            if preview.scheduled.next_scheduled_date() == next_day:
                result = preview.play_next_date()
                counts[cid] = result["played_match_count"]
        session.processed_dates.append(next_day)
        checkpoint = self.save(session)
        return {
            "year": session.year, "date": next_day,
            "game_provenance": "game_projection_v1",
            "competition_match_counts": counts,
            "played_match_count": sum(counts.values()),
            "completed_competition_ids": sorted(session.completed_runs()),
            "checkpoint": checkpoint,
        }

    def load(self, slot_id: str, *, year: int) -> CareerMultiPreviewSession:
        slot = self.solo.slots.validate_slot_id(slot_id)
        payload = _checkpoint(self._path(slot, year))
        inputs = payload.get("inputs")
        if (payload.get("slot_id") != slot or payload.get("year") != year
                or payload.get("resolver_contract") != _RESOLVER
                or payload.get("official_future_calendar") is not False
                or payload.get("full_year_gameplay") is not False
                or payload.get("automatic_feeder_advancement") is not False
                or not isinstance(inputs, list) or len(inputs) < 2):
            raise CareerPreviewSaveError("multi-preview metadata mismatch")
        try:
            prior = self.solo._prior_ledger(slot, year)
            specs = self._inputs(
                year, inputs,
                base_seed=inputs[0]["base_seed"],
                career_seed=inputs[0]["career_seed"],
            )
            if specs != inputs:
                raise CareerPreviewSaveError("multi-preview entrant inputs changed")
            previews = self._prepare_all(slot, specs)
            initial = self._initial_digests(previews)
            if payload.get("initial_digests") != initial:
                raise CareerPreviewSaveError("multi-preview initial plan changed")
            session = CareerMultiPreviewSession(
                slot, year, previews, specs, prior, initial, [],
                payload["payload_checksum"],
            )
            if (payload.get("prior_ledger_sha256") != prior
                    or payload.get("plan_fingerprint") != self._fingerprint(session)):
                raise CareerPreviewSaveError("multi-preview archive identity mismatch")
            dates = payload.get("processed_dates")
            if (not isinstance(dates, list) or dates != sorted(set(dates))
                    or any(not isinstance(d, str) for d in dates)):
                raise CareerPreviewSaveError("multi-preview replay dates invalid")
            for expected in dates:
                next_day = self._next_date(session)
                if next_day != expected:
                    raise CareerPreviewSaveError("multi-preview replay date changed")
                for cid, preview in sorted(session.previews.items()):
                    if preview.scheduled.next_scheduled_date() == expected:
                        preview.play_next_date()
                session.processed_dates.append(expected)
            if (payload.get("completed_match_count") !=
                    len(_all_completed(previews))
                    or payload.get("completed_match_sha256") !=
                    _digest(_all_completed(previews))
                    or payload.get("competition_date_progress") != {
                        cid: list(preview.scheduled.processed_dates)
                        for cid, preview in sorted(previews.items())
                    } or payload.get("completed_competition_champions") != {
                        cid: run.outcome.champion_school_id
                        for cid, run in sorted(session.completed_runs().items())
                    }):
                raise CareerPreviewSaveError("multi-preview replay results differ")
            self._register(session)
            self._sync(session)
            return session
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            if isinstance(exc, CareerPreviewSaveError):
                raise
            raise CareerPreviewSaveError(
                "multi-preview input or deterministic replay invalid"
            ) from exc
