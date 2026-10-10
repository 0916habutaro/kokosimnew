"""Stage 43G-4: gated, crash-replayable next-event regional MAIN sandbox.

This is NOT a 2027 nationwide live-season planner. The only way to create
regional entrants is through the verified same-year feeder view. It refuses
partial/missing sources, missing 3rd-place proof and changing upstream saves.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from .career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService,
    CareerPreviewSaveError,
    _checkpoint,
    _RESOLVER as MULTI_RESOLVER,
)
from .career_preview_checkpoint import (
    _atomic_write, _checksum, _digest, _completed,
)
from .future_competition_bridge import (
    FutureCompetitionPreview,
    prepare_future_direct_main_preview,
)
from .future_season_blueprint import build_future_season_blueprint
from .same_year_regional_feeder_gate import (
    RegionalFeederNotReady, project_same_year_regional_feeders,
)

_SCHEMA_VERSION = 1
_TARGET = "CMP000006"


@dataclass
class RegionalCareerSession:
    slot_id: str
    year: int
    competition_id: str
    upstream_checksum: str
    upstream_plan_fingerprint: str
    feeder_sha256: str
    placement_decider_match_ids: dict[str, str]
    preview: FutureCompetitionPreview
    base_seed: int
    career_seed: int
    initial_draw_sha256: str
    checkpoint_checksum: str = ""

    def summary(self) -> dict:
        return {
            "slot_id": self.slot_id, "year": self.year,
            "competition_id": self.competition_id,
            "entrant_count": len(self.preview.annual.entrant_school_ids),
            "completed_match_count": len(_completed(self.preview)),
            "processed_dates": list(self.preview.scheduled.processed_dates),
            "game_provenance": "game_projection_v1",
            "upstream_feeders_verified": True,
            "official_calendar": False,
            "full_year_gameplay": False,
        }


def _read_regional_checkpoint(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CareerPreviewSaveError("regional checkpoint unreadable") from exc
    if (not isinstance(payload, dict)
            or payload.get("schema_version") != _SCHEMA_VERSION
            or not isinstance(payload.get("payload_checksum"), str)
            or payload["payload_checksum"] != _checksum(payload)):
        raise CareerPreviewSaveError("regional checkpoint checksum invalid")
    return payload


class CareerRegionalMainCheckpointService:
    """Sandbox only: complete sources -> 17-team MAIN -> A-history/replay."""

    def __init__(self, multi: CareerMultiPreviewCheckpointService):
        self.multi = multi

    def _path(self, slot_id: str, year: int) -> Path:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        if not isinstance(year, int) or isinstance(year, bool) or not 2026 < year <= 9999:
            raise CareerPreviewSaveError("invalid regional preview year")
        return (self.multi.solo.slots.slot_dir(slot)
                / "career_regional_previews" / f"{year}_{_TARGET}.json")

    def _context(self, slot: str, year: int, placements: dict[str, str]):
        upstream = self.multi.load(slot, year=year)
        if not all(p.scheduled.is_complete for p in upstream.previews.values()):
            raise RegionalFeederNotReady(
                "all registered prefectural events must complete before regional MAIN"
            )
        gate = project_same_year_regional_feeders(
            self.multi, upstream, _TARGET,
            placement_decider_match_ids=placements,
        )
        if (not gate["all_feeder_results_verified"]
                or gate["unresolved_feeder_rule_ids"]
                or gate["verified_entrant_count"] != 17
                or len(set(gate["verified_school_ids"])) != 17):
            raise RegionalFeederNotReady(
                "regional MAIN blocked by unresolved prefectural feeders: "
                + ",".join(gate["unresolved_feeder_rule_ids"])
            )
        checkpoint = _checkpoint(self.multi._path(slot, year))
        return upstream, gate, checkpoint

    def _preview(self, slot: str, year: int, upstream, gate):
        base_seed = upstream.inputs[0]["base_seed"]
        career_seed = upstream.inputs[0]["career_seed"]
        blueprint = build_future_season_blueprint(
            self.multi.solo.data_root, year=year, base_seed=base_seed,
        )
        preview = prepare_future_direct_main_preview(
            blueprint=blueprint,
            competition_id=_TARGET,
            entrant_school_ids=gate["verified_school_ids"],
            roster_archive=self.multi.solo._rosters(slot),
            repo=self.multi.solo.repo,
            career_seed=career_seed,
            ability_config_dir=str(self.multi.solo.ability_config_dir),
            match_config_dir=str(self.multi.solo.match_config_dir),
        )
        if preview.annual.main_seed_school_ids:
            raise RegionalFeederNotReady(
                "regional MAIN cannot infer seeds from source ranks"
            )
        return preview

    def _initial(self, session: RegionalCareerSession) -> dict:
        return {
            "schema_version": _SCHEMA_VERSION,
            "slot_id": session.slot_id, "year": session.year,
            "competition_id": session.competition_id,
            "upstream_checksum": session.upstream_checksum,
            "upstream_plan_fingerprint": session.upstream_plan_fingerprint,
            "feeder_sha256": session.feeder_sha256,
            "placement_decider_match_ids": session.placement_decider_match_ids,
            "base_seed": session.base_seed,
            "career_seed": session.career_seed,
            "initial_draw_sha256": session.initial_draw_sha256,
            "official_calendar": False,
            "full_year_gameplay": False,
            "automatic_qualification_committed": False,
        }

    def _payload(self, session: RegionalCareerSession) -> dict:
        payload = self._initial(session)
        payload.update({
            "processed_dates": list(session.preview.scheduled.processed_dates),
            "completed_match_count": len(_completed(session.preview)),
            "completed_match_sha256": _digest(_completed(session.preview)),
            "is_complete": session.preview.scheduled.is_complete,
        })
        payload["payload_checksum"] = _checksum(payload)
        return payload

    def _sync(self, session: RegionalCareerSession) -> dict:
        # Annual identity is shared with the upstream 2027 games. No new
        # registered year or unrelated identity is invented.
        return self.multi.solo._archive(session.slot_id).sync(
            year=session.year,
            rng_seed=session.base_seed,
            resolver_contract=MULTI_RESOLVER,
            plan_fingerprint=session.upstream_plan_fingerprint,
            completed=_completed(session.preview),
        )

    def _check_context(self, session: RegionalCareerSession) -> None:
        upstream, gate, checkpoint = self._context(
            session.slot_id, session.year, session.placement_decider_match_ids,
        )
        if (checkpoint["payload_checksum"] != session.upstream_checksum
                or self.multi._fingerprint(upstream) != session.upstream_plan_fingerprint
                or _digest(gate) != session.feeder_sha256
                or upstream.inputs[0]["base_seed"] != session.base_seed
                or upstream.inputs[0]["career_seed"] != session.career_seed):
            raise CareerPreviewSaveError("regional feeder or upstream save changed")

    def start(
        self, slot_id: str, *,
        year: int,
        placement_decider_match_ids: dict[str, str] | None = None,
    ) -> RegionalCareerSession:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        target = self._path(slot, year)
        if target.exists():
            raise CareerPreviewSaveError("regional preview already exists; use load()")
        placements = dict(placement_decider_match_ids or {})
        upstream, gate, checkpoint = self._context(slot, year, placements)
        preview = self._preview(slot, year, upstream, gate)
        session = RegionalCareerSession(
            slot, year, _TARGET,
            checkpoint["payload_checksum"], self.multi._fingerprint(upstream),
            _digest(gate), placements, preview,
            upstream.inputs[0]["base_seed"], upstream.inputs[0]["career_seed"],
            _digest(preview.scheduled.public_snapshot()),
        )
        self.save(session)
        return session

    def save(self, session: RegionalCareerSession) -> dict:
        self._check_context(session)
        path = self._path(session.slot_id, session.year)
        if path.exists():
            old = _read_regional_checkpoint(path)
            if old["payload_checksum"] != session.checkpoint_checksum:
                raise CareerPreviewSaveError("stale regional checkpoint")
        elif session.checkpoint_checksum:
            raise CareerPreviewSaveError("regional checkpoint was removed")
        payload = self._payload(session)
        _atomic_write(path, payload)
        session.checkpoint_checksum = payload["payload_checksum"]
        written = self._sync(session)
        return {
            "path": str(path), "year": session.year,
            "completed_match_count": payload["completed_match_count"],
            "archive": written,
        }

    def play_next_date(self, session: RegionalCareerSession) -> dict:
        self._check_context(session)
        result = session.preview.play_next_date()
        result["checkpoint"] = self.save(session)
        return result

    def load(self, slot_id: str, *, year: int) -> RegionalCareerSession:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        payload = _read_regional_checkpoint(self._path(slot, year))
        if (payload.get("schema_version") != _SCHEMA_VERSION
                or payload.get("slot_id") != slot
                or payload.get("year") != year
                or payload.get("competition_id") != _TARGET
                or payload.get("official_calendar") is not False
                or payload.get("full_year_gameplay") is not False
                or payload.get("automatic_qualification_committed") is not False
                or not isinstance(payload.get("placement_decider_match_ids"), dict)):
            raise CareerPreviewSaveError("regional preview metadata mismatched")
        placements = payload["placement_decider_match_ids"]
        upstream, gate, checkpoint = self._context(slot, year, placements)
        preview = self._preview(slot, year, upstream, gate)
        session = RegionalCareerSession(
            slot, year, _TARGET,
            checkpoint["payload_checksum"], self.multi._fingerprint(upstream),
            _digest(gate), placements, preview,
            upstream.inputs[0]["base_seed"], upstream.inputs[0]["career_seed"],
            _digest(preview.scheduled.public_snapshot()),
            payload["payload_checksum"],
        )
        for k, v in self._initial(session).items():
            if payload.get(k) != v:
                raise CareerPreviewSaveError(f"regional preview identity mismatched: {k}")
        days = payload.get("processed_dates")
        if (not isinstance(days, list)
                or days != sorted(set(days))
                or any(not isinstance(d, str) for d in days)):
            raise CareerPreviewSaveError("regional preview replay dates invalid")
        for day in days:
            if preview.scheduled.next_scheduled_date() != day:
                raise CareerPreviewSaveError("regional preview replay date changed")
            preview.play_next_date()
        if (payload.get("completed_match_count") != len(_completed(preview))
                or payload.get("completed_match_sha256") != _digest(_completed(preview))
                or payload.get("is_complete") != preview.scheduled.is_complete):
            raise CareerPreviewSaveError("regional preview replay match results changed")
        self._sync(session)
        return session
