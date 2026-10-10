"""Stage 43G-9: same-year Kanagawa FMT006 independent, resumable sidecar.

The original common-year input plan is immutable. A sidecar executes the
Kanagawa 4-district tournament against the same A-history annual identity,
using the separately registered complete Senbatsu manifest as its authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .career_invitational_manifest import CareerInvitationalManifestService
from .career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService, _RESOLVER,
)
from .career_preview_checkpoint import (
    CareerPreviewSaveError, _atomic_write, _checksum, _digest, _completed,
)
from .future_kanagawa_fmt006_bridge import (
    TARGET, prepare_future_kanagawa_spring_preview,
)


class KanagawaSpringNotReady(CareerPreviewSaveError):
    """Game-only qualifying right, year archive or save fails verification."""


def _read(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KanagawaSpringNotReady("Kanagawa spring checkpoint unreadable") from exc
    if (not isinstance(payload, dict) or payload.get("schema_version") != 1
            or payload.get("payload_checksum") != _checksum(payload)):
        raise KanagawaSpringNotReady("Kanagawa spring checkpoint checksum invalid")
    return payload


@dataclass
class KanagawaSpringSession:
    slot_id: str
    year: int
    preview: object
    entrant_school_ids: list[str]
    group_entrant_school_ids: dict[str, list[str]]
    upstream_plan_fingerprint: str
    manifest_sha256: str
    base_seed: int
    career_seed: int
    initial_draw_sha256: str
    checkpoint_checksum: str = ""

    def summary(self) -> dict:
        return {
            "year": self.year, "competition_id": TARGET,
            "school_count": len(self.entrant_school_ids),
            "recommended_count": len(self.preview.annual.direct_main_entry_school_ids),
            "qualifier_count": sum(map(len, self.group_entrant_school_ids.values())),
            "completed_matches": len(_completed(self.preview)),
            "processed_dates": list(self.preview.scheduled.processed_dates),
            "is_complete": self.preview.scheduled.is_complete,
            "official_future_calendar": False,
            "automatic_main_seeding": False,
        }


class CareerKanagawaSpringCheckpointService:
    def __init__(self, multi: CareerMultiPreviewCheckpointService):
        self.multi = multi
        self.manifests = CareerInvitationalManifestService(multi)

    def _path(self, slot: str, year: int) -> Path:
        slot = self.multi.solo.slots.validate_slot_id(slot)
        self.multi._path(slot, year)
        return (self.multi.solo.slots.slot_dir(slot) /
                "career_kanagawa_spring_previews" / f"{year}_{TARGET}.json")

    def _context(self, slot: str, year: int):
        source = self.manifests.audit_kanagawa(slot, year=year)
        if (source.get("status") != "complete_same_year_sandbox_participant_manifest"
                or source.get("game_participant_manifest_verified") is not True
                or source.get("source_school_count") != 32):
            raise KanagawaSpringNotReady(
                "same-year complete Senbatsu participant manifest required"
            )
        upstream = self.multi.load(slot, year=year)
        if ("CMP000001" not in upstream.previews
                or any(row["base_seed"] != upstream.inputs[0]["base_seed"]
                       or row["career_seed"] != upstream.inputs[0]["career_seed"]
                       for row in upstream.inputs)):
            raise KanagawaSpringNotReady("Senbatsu annual plan mismatch")
        return upstream, source

    def _preview(self, slot: str, year: int, entrants, groups, source, upstream):
        return prepare_future_kanagawa_spring_preview(
            data_root=self.multi.solo.data_root,
            year=year, entrant_school_ids=entrants,
            group_entrant_school_ids=groups,
            invitation_audit=source,
            roster_archive=self.multi.solo._rosters(slot),
            repo=self.multi.solo.repo,
            base_seed=upstream.inputs[0]["base_seed"],
            career_seed=upstream.inputs[0]["career_seed"],
            ability_config_dir=self.multi.solo.ability_config_dir,
            match_config_dir=self.multi.solo.match_config_dir,
        )

    def _identity(self, session: KanagawaSpringSession) -> dict:
        return {
            "schema_version": 1,
            "slot_id": session.slot_id,
            "year": session.year,
            "competition_id": TARGET,
            "entrant_school_ids": session.entrant_school_ids,
            "group_entrant_school_ids": session.group_entrant_school_ids,
            "upstream_plan_fingerprint": session.upstream_plan_fingerprint,
            "manifest_sha256": session.manifest_sha256,
            "base_seed": session.base_seed, "career_seed": session.career_seed,
            "initial_draw_sha256": session.initial_draw_sha256,
            "game_provenance": "game_projection_v1",
            "official_future_calendar": False,
            "full_year_gameplay": False,
            "automatic_feeder_advancement": False,
        }

    def _payload(self, session: KanagawaSpringSession) -> dict:
        dates = list(session.preview.scheduled.processed_dates)
        if dates != sorted(set(dates)):
            raise KanagawaSpringNotReady("invalid Kanagawa chronological replay dates")
        result = self._identity(session)
        result.update({
            "processed_dates": dates,
            "completed_match_count": len(_completed(session.preview)),
            "completed_match_sha256": _digest(_completed(session.preview)),
            "is_complete": session.preview.scheduled.is_complete,
        })
        result["payload_checksum"] = _checksum(result)
        return result

    def _validate_binding(self, session: KanagawaSpringSession) -> None:
        upstream, source = self._context(session.slot_id, session.year)
        if (self.multi._fingerprint(upstream) != session.upstream_plan_fingerprint
                or source["source_manifest_sha256"] != session.manifest_sha256
                or upstream.inputs[0]["base_seed"] != session.base_seed
                or upstream.inputs[0]["career_seed"] != session.career_seed):
            raise KanagawaSpringNotReady("Senbatsu selection or annual plan changed")

    def _sync(self, session: KanagawaSpringSession):
        return self.multi.solo._archive(session.slot_id).sync(
            year=session.year, rng_seed=session.base_seed,
            resolver_contract=_RESOLVER,
            plan_fingerprint=session.upstream_plan_fingerprint,
            completed=_completed(session.preview),
        )

    def start(self, slot_id: str, *, year: int,
              entrant_school_ids: list[str],
              group_entrant_school_ids: dict[str, list[str]]) -> KanagawaSpringSession:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        target = self._path(slot, year)
        if target.exists():
            raise KanagawaSpringNotReady("Kanagawa spring already started; use load")
        upstream, source = self._context(slot, year)
        groups = {gid: list(ids) for gid, ids in sorted(group_entrant_school_ids.items())}
        entrants = list(entrant_school_ids)
        preview = self._preview(slot, year, entrants, groups, source, upstream)
        first = preview.scheduled.next_scheduled_date()
        if any(day >= first for day in upstream.processed_dates):
            raise KanagawaSpringNotReady(
                "cannot retroactively start Kanagawa after spring qualifier date"
            )
        session = KanagawaSpringSession(
            slot, year, preview, entrants, groups,
            self.multi._fingerprint(upstream),
            source["source_manifest_sha256"],
            upstream.inputs[0]["base_seed"],
            upstream.inputs[0]["career_seed"],
            _digest(preview.scheduled.public_snapshot()),
        )
        self.save(session)
        return session

    def save(self, session: KanagawaSpringSession) -> dict:
        self._validate_binding(session)
        path = self._path(session.slot_id, session.year)
        if path.is_file():
            current = _read(path)
            if current["payload_checksum"] != session.checkpoint_checksum:
                raise KanagawaSpringNotReady("stale Kanagawa spring checkpoint")
        elif session.checkpoint_checksum:
            raise KanagawaSpringNotReady("Kanagawa checkpoint removed")
        payload = self._payload(session)
        _atomic_write(path, payload)
        session.checkpoint_checksum = payload["payload_checksum"]
        added = self._sync(session)
        return {
            "path": str(path), "year": session.year,
            "completed_match_count": payload["completed_match_count"],
            "archive": added,
        }

    def load(self, slot_id: str, *, year: int) -> KanagawaSpringSession:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        payload = _read(self._path(slot, year))
        upstream, source = self._context(slot, year)
        preview = self._preview(
            slot, year, payload["entrant_school_ids"],
            payload["group_entrant_school_ids"], source, upstream,
        )
        session = KanagawaSpringSession(
            slot, year, preview,
            list(payload["entrant_school_ids"]),
            dict(payload["group_entrant_school_ids"]),
            self.multi._fingerprint(upstream),
            source["source_manifest_sha256"],
            upstream.inputs[0]["base_seed"], upstream.inputs[0]["career_seed"],
            _digest(preview.scheduled.public_snapshot()),
            payload["payload_checksum"],
        )
        if any(payload.get(k) != v for k, v in self._identity(session).items()):
            raise KanagawaSpringNotReady("Kanagawa initial plan identity differs")
        days = payload.get("processed_dates")
        if (not isinstance(days, list) or days != sorted(set(days))
                or any(not isinstance(d, str) for d in days)):
            raise KanagawaSpringNotReady("Kanagawa replay date list invalid")
        for day in days:
            if preview.scheduled.next_scheduled_date() != day:
                raise KanagawaSpringNotReady("Kanagawa planned game day changed")
            preview.play_next_date()
        if (payload.get("completed_match_count") != len(_completed(preview))
                or payload.get("completed_match_sha256") != _digest(_completed(preview))
                or payload.get("is_complete") != preview.scheduled.is_complete):
            raise KanagawaSpringNotReady("Kanagawa replay results changed")
        self._sync(session)
        return session

    def play_next_global_date(self, session: KanagawaSpringSession) -> dict:
        """Advance both same-year sources on the earliest pending game date."""
        self._validate_binding(session)
        upstream = self.multi.load(session.slot_id, year=session.year)
        date_a = self.multi._next_date(upstream)
        date_b = session.preview.scheduled.next_scheduled_date() or ""
        next_date = min((x for x in (date_a, date_b) if x), default="")
        if not next_date:
            raise KanagawaSpringNotReady("no remaining Kanagawa/national game date")
        match_count = 0
        competitions = {}
        if date_a == next_date:
            result = self.multi.play_next_date(upstream)
            match_count += result["played_match_count"]
            competitions.update(result["competition_match_counts"])
        if date_b == next_date:
            result = session.preview.play_next_date()
            match_count += result["played_match_count"]
            competitions[TARGET] = result["played_match_count"]
            self.save(session)
        return {
            "date": next_date, "year": session.year,
            "played_match_count": match_count,
            "competition_match_counts": competitions,
            "game_provenance": "game_projection_v1",
            "all_registered_events_complete": (
                not self.multi._next_date(upstream)
                and session.preview.scheduled.is_complete
            ),
        }
