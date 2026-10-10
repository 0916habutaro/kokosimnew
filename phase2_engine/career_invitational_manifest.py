"""Stage 43G-8: sealed *game selection* list for same-year Senbatsu access.

Not a reproduction of the real selection committee. The operator explicitly
submits all 32 2027 sandbox participants, with saved year-specific rosters;
the already committed multi-preview tournament is the authority. This module
does not run Kanagawa's FMT006 preliminary or award bracket seeds.
"""
from __future__ import annotations

from pathlib import Path
from .career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService, _checkpoint,
)
from .career_preview_checkpoint import (
    CareerPreviewSaveError, _atomic_write, _checksum, _digest,
)
from .future_kanagawa_invitational_access import (
    NATIONAL_INVITATIONAL, audit_kanagawa_spring_access,
)
import json


class InvitationalManifestConflict(CareerPreviewSaveError):
    """A saved manifest or its underlying season plan cannot be verified."""


class CareerInvitationalManifestService:
    """Persist the complete 32-school participant list, not just played games."""

    SCHEMA = 1
    MODE = "national_invitational_main_v1"

    def __init__(self, multi: CareerMultiPreviewCheckpointService):
        self.multi = multi

    def _path(self, slot_id: str, year: int) -> Path:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        # Use the same future-year validation as the multi-preview.
        self.multi._path(slot, year)
        return (self.multi.solo.slots.slot_dir(slot) /
                "career_invitational_manifests" /
                f"{year}_{NATIONAL_INVITATIONAL}.json")

    def _manifest(self, slot: str, year: int) -> dict:
        session = self.multi.load(slot, year=year)
        row = [x for x in session.inputs if
               x.get("competition_id") == NATIONAL_INVITATIONAL]
        preview = session.previews.get(NATIONAL_INVITATIONAL)
        if len(row) != 1 or preview is None or row[0].get("entry_mode") != self.MODE:
            raise InvitationalManifestConflict(
                "complete same-year national invitational entry plan is missing"
            )
        ids = list(preview.annual.entrant_school_ids)
        source = self.multi.solo.repo.competition(NATIONAL_INVITATIONAL)
        stages = self.multi.solo.repo.stages(NATIONAL_INVITATIONAL)
        if (source.get("competition_type") != "national_invitational"
                or source.get("season_segment") != "spring"
                or len(stages) != 1 or stages[0].get("stage_code") != "MAIN"
                or int(stages[0].get("team_count") or 0) != 32
                or preview.year != year
                or ids != row[0]["entrant_school_ids"]
                or len(ids) != 32 or len(set(ids)) != 32
                or preview.annual.main_seed_school_ids
                or row[0]["group_entrant_school_ids"]
                or row[0]["prior_source_competition_id"] is not None):
            raise InvitationalManifestConflict("national invitational roster or structure differs")

        # load() already replays the immutable checkpoint and verifies the
        # previous sealed year + all currently saved A-game results. Do not
        # bind to its changing per-date checksum: only the year-long plan.
        plan = _checkpoint(self.multi._path(slot, year))
        fingerprint = self.multi._fingerprint(session)
        if plan.get("plan_fingerprint") != fingerprint:
            raise InvitationalManifestConflict("uncommitted national game selection")
        result = {
            "schema_version": self.SCHEMA,
            "slot_id": slot,
            "year": year,
            "competition_id": NATIONAL_INVITATIONAL,
            "source_year": year,
            "selection_provenance": "explicit_sandbox_game_selection_not_committee",
            "complete_participant_list": True,
            "expected_participant_count": 32,
            "entrant_school_ids": ids,
            "entrant_sha256": _digest(ids),
            "source_plan_fingerprint": fingerprint,
            "previous_year_sealed_ledger_sha256": session.prior_ledger_sha256,
            "official_participants_verified": False,
            "future_year_rule_verified": False,
            "automatic_senbatsu_selection": False,
            "full_year_gameplay": False,
        }
        result["payload_checksum"] = _checksum(result)
        return result

    def record(self, slot_id: str, *, year: int) -> dict:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        expected = self._manifest(slot, year)
        path = self._path(slot, year)
        if path.is_file():
            stored = self._read(path)
            if stored != expected:
                raise InvitationalManifestConflict("registered national participant manifest changed")
        else:
            _atomic_write(path, expected)
        return expected

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InvitationalManifestConflict("national manifest unreadable") from exc
        if (not isinstance(payload, dict)
                or payload.get("schema_version") != CareerInvitationalManifestService.SCHEMA
                or payload.get("payload_checksum") != _checksum(payload)):
            raise InvitationalManifestConflict("national manifest checksum invalid")
        return payload

    def audit_kanagawa(self, slot_id: str, *, year: int) -> dict:
        base = audit_kanagawa_spring_access(self.multi.solo.repo, year=year)
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        path = self._path(slot, year)
        if not path.is_file():
            # A missing manifest cannot be read as an authoritative zero.
            return base
        saved = self._read(path)
        current = self._manifest(slot, year)
        if saved != current:
            raise InvitationalManifestConflict(
                "Senbatsu participant manifest differs from sealed game plan"
            )
        pcode = self.multi.solo.repo.competition(base["competition_id"])["prefecture_code"]
        selected = [sid for sid in saved["entrant_school_ids"]
                    if self.multi.solo.repo.schools[sid]["prefecture_code"] == pcode]
        # This may correctly contain zero *only when* an entire verified
        # 32-team game selection list exists.
        return {
            **base,
            "status": "complete_same_year_sandbox_participant_manifest",
            "reason": "full 32-school game entrant list persisted and verified",
            "direct_main_school_ids": selected,
            "preliminary_exempt_school_ids": list(selected),
            "source_school_count": 32,
            "source_manifest_sha256": saved["payload_checksum"],
            "source_plan_fingerprint": saved["source_plan_fingerprint"],
            "game_participant_manifest_verified": True,
            "game_sandbox_selection_only": True,
            "source_may_include_multiple_kanagawa_schools": True,
            "future_official_participants_confirmed": False,
            "main_seed_school_ids": [],
            # Kanagawa's FMT006 qualifier has no future-year bridge yet.
            "automatic_bypass_enabled": False,
            "runtime_ready": False,
        }
